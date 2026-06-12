# Dataset Builder Step 1, 2 API (Unified schema - MySQL primary)
"""
Dataset Builder API - document_metadata 테이블 사용 (통합 스키마)
MySQL을 primary로, SQLite는 비동기 동기화 대상으로 사용

2026-06-12 수정:
- RAG_SOURCE_ROOT 하드코딩 제거
- Document Source API에서 동적으로 source 설정 조회
- source_id + relative_path 기반 문서 고유 식별자(document_uid) 도입
- file_checksum, file_modified_at, removed_at 등 추적 필드 추가
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.auth import require_admin_token
from app.core.database import get_db
from app.models.document_metadata import DocumentMetadata, MetaStatus, ProcessingStatus
from app.services.document_uid import make_document_uid, detect_file_change, calculate_file_checksum
from app.services.platform_store import list_records, get_record

router = APIRouter(
    prefix="/admin/dataset-builder",
    tags=["Admin - Dataset Builder"],
    dependencies=[Depends(require_admin_token)],
)

# 지원 파일 확장자
SUPPORTED_EXTENSIONS = {".hwp", ".hwpx", ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls"}

# category_id 매핑 (폴더명 기반)
CATEGORY_ID_MAP = {
    "01. 전략및방법론": "cat_strategy_method",
    "02. 기술및기능": "cat_tech_function",
    "03. 프로젝트관리": "cat_project_manage",
    "04. 프로젝트지원": "cat_project_support",
    "05. 연구과제": "cat_research",
    "06. 감리": "cat_audit",
    "07. PMO": "cat_pmo",
    "08. PoC": "cat_poc",
    "01. 환경분석": "cat_env_analysis",
    "02. 현황분석": "cat_status_analysis",
    "03. 목표모델": "cat_target_model",
    "04. 이행계획": "cat_impl_plan"
}


def get_document_source(source_id: str) -> Optional[Dict[str, Any]]:
    """Document Source 설정 조회"""
    return get_record("document_sources", "source_id", source_id)


def get_scan_root(source: Dict[str, Any]) -> Path:
    """Document Source에서 스캔 루트 경로 계산 (mount_path + root_subpath)"""
    mount_path = source.get("mount_path", "")
    root_subpath = source.get("root_subpath", "")
    if root_subpath:
        return Path(mount_path) / root_subpath
    return Path(mount_path)


class ScanRequest(BaseModel):
    source_id: Optional[str] = "rag_source"
    overwrite: bool = False
    compute_checksum: bool = False  # 전체 파일 checksum 계산 여부


class ScanResponse(BaseModel):
    success: bool
    source_id: str
    scan_root: str
    total_files: int
    supported_files: int
    excluded_files: int
    new_files: int
    changed_files: int
    removed_files: int
    unchanged_files: int
    restored_files: int
    documents_created: int
    documents_updated: int
    total_metadata: int
    by_extension: Dict[str, int]
    samples: Dict[str, List[str]]
    warnings: List[str]
    errors: List[str]
    next_action: str
    message: str


class MetadataAutoRequest(BaseModel):
    only_missing: bool = True
    overwrite: bool = False


class MetadataAutoResponse(BaseModel):
    success: bool
    processed: int
    updated: int
    skipped: int
    message: str


def scan_folder(folder_path: str, extensions: set) -> List[dict]:
    """폴더를 재귀적으로 스캔하여 파일 목록 반환"""
    files = []
    if not os.path.exists(folder_path):
        return files

    for root, dirs, filenames in os.walk(folder_path):
        for filename in filenames:
            ext = Path(filename).suffix.lower()
            if ext in extensions:
                filepath = os.path.join(root, filename)
                stat = os.stat(filepath)
                files.append({
                    "filename": filename,
                    "filepath": filepath,
                    "extension": ext.lstrip("."),
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime),
                })
    return files


def extract_project_name(filename: str) -> str:
    """파일명에서 프로젝트명 추출"""
    name = Path(filename).stem

    prefixes = [
        "RFP_", "전략및방법론_", "기술및기능_", "프로젝트관리_",
        "프로젝트지원_", "연구과제_", "감리_", "PMO_", "PoC_",
        "환경분석_", "현황분석_", "목표모델_", "이행계획_"
    ]

    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    if "_" in name and not any(name.startswith(p) for p in prefixes):
        parts = name.split("_", 1)
        if len(parts) > 1 and len(parts[0]) < 10:
            name = parts[1]

    return name.strip()


@router.post("/step1/scan", response_model=ScanResponse)
async def step1_source_scan(request: ScanRequest, db: Session = Depends(get_db)):
    """
    Step 1: Source Scan - Document Source 기반 파일 스캔 및 document_metadata 레코드 생성

    주요 변경사항 (2026-06-12):
    - RAG_SOURCE_ROOT 하드코딩 제거
    - Document Source API에서 source 설정 동적 조회
    - source_id + relative_path 기반 document_uid 생성
    - 변경 감지: file_size + modified_at 기준, 변경 의심 시 checksum 계산
    - removed 상태 파일이 다시 나타나면 기존 레코드 복원
    """
    source_id = request.source_id or "rag_source"
    warnings: List[str] = []
    errors: List[str] = []
    by_extension: Dict[str, int] = {}
    samples: Dict[str, List[str]] = {"new": [], "changed": [], "removed": [], "excluded": [], "restored": []}

    # 1. Document Source 설정 조회
    source = get_document_source(source_id)
    if not source:
        return ScanResponse(
            success=False,
            source_id=source_id,
            scan_root="",
            total_files=0, supported_files=0, excluded_files=0,
            new_files=0, changed_files=0, removed_files=0, unchanged_files=0, restored_files=0,
            documents_created=0, documents_updated=0, total_metadata=0,
            by_extension={}, samples={},
            warnings=[], errors=[f"Document Source '{source_id}'를 찾을 수 없습니다."],
            next_action="Document Source를 먼저 등록하세요.",
            message=f"Document Source '{source_id}'를 찾을 수 없습니다."
        )

    # 2. 스캔 루트 경로 계산
    scan_root = get_scan_root(source)
    scan_root_str = str(scan_root)

    if not scan_root.exists():
        return ScanResponse(
            success=False,
            source_id=source_id,
            scan_root=scan_root_str,
            total_files=0, supported_files=0, excluded_files=0,
            new_files=0, changed_files=0, removed_files=0, unchanged_files=0, restored_files=0,
            documents_created=0, documents_updated=0, total_metadata=0,
            by_extension={}, samples={},
            warnings=[], errors=[f"스캔 경로를 찾을 수 없습니다: {scan_root_str}"],
            next_action="Document Source의 mount_path를 확인하세요.",
            message=f"스캔 경로를 찾을 수 없습니다: {scan_root_str}"
        )

    try:
        # 3. 현재 파일 시스템 스캔
        current_files: Dict[str, dict] = {}
        total_files = 0
        supported_files = 0
        excluded_files = 0

        for root, dirs, filenames in os.walk(scan_root_str):
            for filename in filenames:
                total_files += 1
                ext = Path(filename).suffix.lower()

                if ext not in SUPPORTED_EXTENSIONS:
                    excluded_files += 1
                    continue

                supported_files += 1
                filepath = Path(root) / filename
                relative_path = filepath.relative_to(scan_root).as_posix()

                try:
                    stat = filepath.stat()
                    file_modified_at = datetime.fromtimestamp(stat.st_mtime)
                except Exception as e:
                    warnings.append(f"파일 정보 읽기 실패: {relative_path} - {e}")
                    continue

                # 확장자별 카운트
                ext_key = ext.lstrip(".")
                by_extension[ext_key] = by_extension.get(ext_key, 0) + 1

                # category_id 추출 (첫 번째 폴더명 기준)
                path_parts = relative_path.split("/")
                category_folder = path_parts[0] if path_parts else ""
                category_id = CATEGORY_ID_MAP.get(category_folder, f"cat_{category_folder}")

                current_files[relative_path] = {
                    "filename": filename,
                    "filepath": str(filepath),
                    "relative_path": relative_path,
                    "extension": ext_key,
                    "size": stat.st_size,
                    "modified_at": file_modified_at,
                    "category_id": category_id,
                }

        # 4. 기존 document_metadata 레코드 조회 (같은 source_id)
        existing_records = db.query(DocumentMetadata).filter(
            DocumentMetadata.source_id == source_id
        ).all()

        existing_by_path: Dict[str, DocumentMetadata] = {}
        for rec in existing_records:
            if rec.relative_path:
                existing_by_path[rec.relative_path] = rec
            elif rec.file_path:
                # relative_path가 없으면 file_path에서 역산 시도
                try:
                    rel = Path(rec.file_path).relative_to(scan_root).as_posix()
                    existing_by_path[rel] = rec
                except ValueError:
                    pass

        # 5. 변경 감지 및 처리
        new_count = 0
        changed_count = 0
        unchanged_count = 0
        restored_count = 0
        documents_created = 0
        documents_updated = 0

        next_doc_id = (db.query(func.max(DocumentMetadata.document_id)).scalar() or 0) + 1

        for rel_path, file_info in current_files.items():
            existing = existing_by_path.get(rel_path)
            doc_uid = make_document_uid(source_id, rel_path)

            if existing:
                # 5a. 기존 레코드 - 변경 여부 확인
                if existing.removed_at:
                    # 삭제된 파일이 다시 나타남 - 복원
                    existing.removed_at = None
                    existing.removed_reason = None
                    existing.file_size = file_info["size"]
                    existing.file_modified_at = file_info["modified_at"]
                    existing.updated_at = datetime.utcnow()
                    restored_count += 1
                    documents_updated += 1
                    if len(samples["restored"]) < 5:
                        samples["restored"].append(rel_path)
                else:
                    # 변경 감지 (file_size + modified_at)
                    status, new_checksum = detect_file_change(
                        old_size=existing.file_size,
                        old_modified_at=existing.file_modified_at,
                        old_checksum=existing.file_checksum,
                        current_size=file_info["size"],
                        current_modified_at=file_info["modified_at"],
                        file_path=Path(file_info["filepath"]) if request.compute_checksum else None,
                    )

                    if status in ("changed", "maybe_changed"):
                        existing.file_size = file_info["size"]
                        existing.file_modified_at = file_info["modified_at"]
                        if new_checksum:
                            existing.file_checksum = new_checksum
                        existing.updated_at = datetime.utcnow()
                        changed_count += 1
                        documents_updated += 1
                        if len(samples["changed"]) < 5:
                            samples["changed"].append(rel_path)
                    else:
                        unchanged_count += 1

                # document_uid, relative_path 보정 (없으면 추가)
                if not existing.document_uid:
                    existing.document_uid = doc_uid
                if not existing.relative_path:
                    existing.relative_path = rel_path

            else:
                # 5b. 신규 파일
                checksum = None
                if request.compute_checksum:
                    try:
                        checksum = calculate_file_checksum(Path(file_info["filepath"]))
                    except Exception:
                        pass

                new_meta = DocumentMetadata(
                    document_id=next_doc_id,
                    source_id=source_id,
                    document_uid=doc_uid,
                    file_path=file_info["filepath"],
                    relative_path=rel_path,
                    file_name=file_info["filename"],
                    file_type=file_info["extension"],
                    file_size=file_info["size"],
                    file_checksum=checksum,
                    file_modified_at=file_info["modified_at"],
                    category_id=file_info["category_id"],
                    status=ProcessingStatus.REGISTERED.value,
                    meta_status=MetaStatus.REGISTERED.value,
                    include_in_rag=True,
                    include_in_graph=True,
                    include_in_wiki=True,
                )
                db.add(new_meta)
                new_count += 1
                documents_created += 1
                next_doc_id += 1
                if len(samples["new"]) < 5:
                    samples["new"].append(rel_path)

        # 6. 삭제된 파일 감지 (DB에는 있지만 파일시스템에 없음)
        removed_count = 0
        current_paths = set(current_files.keys())

        for rel_path, existing in existing_by_path.items():
            if rel_path not in current_paths and not existing.removed_at:
                existing.removed_at = datetime.utcnow()
                existing.removed_reason = "source_scan_not_found"
                existing.updated_at = datetime.utcnow()
                removed_count += 1
                documents_updated += 1
                if len(samples["removed"]) < 5:
                    samples["removed"].append(rel_path)

        db.commit()

        # 7. 총 document_metadata 레코드 수 조회
        total_metadata = db.query(func.count(DocumentMetadata.id)).scalar() or 0

        # 8. next_action 결정
        if new_count or changed_count or restored_count:
            next_action = "Metadata Auto를 실행하세요."
        elif removed_count:
            next_action = f"{removed_count}개 파일이 삭제되었습니다. Metadata Review에서 확인하세요."
        else:
            next_action = "변경사항이 없습니다. 현재 상태를 유지해도 됩니다."

        return ScanResponse(
            success=True,
            source_id=source_id,
            scan_root=scan_root_str,
            total_files=total_files,
            supported_files=supported_files,
            excluded_files=excluded_files,
            new_files=new_count,
            changed_files=changed_count,
            removed_files=removed_count,
            unchanged_files=unchanged_count,
            restored_files=restored_count,
            documents_created=documents_created,
            documents_updated=documents_updated,
            total_metadata=total_metadata,
            by_extension=by_extension,
            samples=samples,
            warnings=warnings,
            errors=errors,
            next_action=next_action,
            message=f"Source Scan 완료: {supported_files}개 지원 파일, {new_count}개 신규, {changed_count}개 변경, {removed_count}개 삭제"
        )

    except Exception as e:
        db.rollback()
        return ScanResponse(
            success=False,
            source_id=source_id,
            scan_root=scan_root_str,
            total_files=0, supported_files=0, excluded_files=0,
            new_files=0, changed_files=0, removed_files=0, unchanged_files=0, restored_files=0,
            documents_created=0, documents_updated=0, total_metadata=0,
            by_extension={}, samples={},
            warnings=warnings, errors=[str(e)],
            next_action="오류를 해결한 후 다시 시도하세요.",
            message=f"Source Scan 실패: {str(e)}"
        )


@router.post("/step2/metadata-auto", response_model=MetadataAutoResponse)
async def step2_metadata_auto(request: MetadataAutoRequest, db: Session = Depends(get_db)):
    """
    Step 2: Metadata Auto - 파일명에서 프로젝트명 추출
    """
    try:
        query = db.query(DocumentMetadata)

        if request.only_missing:
            query = query.filter(DocumentMetadata.meta_status == MetaStatus.REGISTERED.value)

        metadata_list = query.all()

        processed = 0
        updated = 0
        skipped = 0

        for metadata in metadata_list:
            if metadata.project_name and not request.overwrite:
                skipped += 1
                continue

            # file_path에서 파일명 추출
            filename = Path(metadata.file_path).name if metadata.file_path else ""
            if not filename:
                skipped += 1
                continue

            project_name = extract_project_name(filename)

            metadata.project_name = project_name
            metadata.project_name_confidence = 0.5
            metadata.meta_status = MetaStatus.METADATA_SUGGESTED.value
            metadata.updated_at = datetime.utcnow()

            updated += 1
            processed += 1

        db.commit()

        return MetadataAutoResponse(
            success=True,
            processed=processed,
            updated=updated,
            skipped=skipped,
            message=f"Metadata Auto 완료: {processed}개 처리, {updated}개 업데이트, {skipped}개 건너뜀"
        )

    except Exception as e:
        db.rollback()
        return MetadataAutoResponse(
            success=False,
            processed=0,
            updated=0,
            skipped=0,
            message=f"Metadata Auto 실패: {str(e)}"
        )


@router.get("/stats")
async def get_dataset_builder_stats(db: Session = Depends(get_db)):
    """Dataset Builder 통계 조회"""
    try:
        total_metadata = db.query(func.count(DocumentMetadata.id)).scalar()

        status_counts = {}
        status_stats = db.query(
            DocumentMetadata.meta_status,
            func.count(DocumentMetadata.id).label('count')
        ).group_by(DocumentMetadata.meta_status).all()

        for status, count in status_stats:
            status_counts[status or "registered"] = count

        source_counts = {}
        source_stats = db.query(
            DocumentMetadata.source_id,
            func.count(DocumentMetadata.id).label('count')
        ).group_by(DocumentMetadata.source_id).all()

        for source_id, count in source_stats:
            source_counts[source_id or "unknown"] = count

        return {
            "success": True,
            "total_metadata": total_metadata,
            "status_counts": status_counts,
            "source_counts": source_counts,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통계 조회 실패: {str(e)}")


# ============================================================
# Cleanup APIs
# ============================================================


class CleanupResponse(BaseModel):
    """Cleanup 작업 응답"""
    success: bool
    action: str
    deleted_count: int
    message: str
    details: List[str] = []


@router.post("/cleanup/hard-delete-removed", response_model=CleanupResponse)
async def hard_delete_removed(
    days_threshold: int = 30,
    dry_run: bool = False,
    db: Session = Depends(get_db)
):
    """
    removed_at이 설정된 문서 중 일정 기간(days_threshold)이 지난 문서를 완전 삭제합니다.

    - 기본: 30일 이상 지난 removed 문서만 삭제
    - dry_run=True: 미리보기만 수행 (실제 삭제 없음)
    - 관련 document_chunks, processed_text 등도 함께 정리
    """
    from datetime import timedelta

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)

        # removed_at이 cutoff_date 이전인 문서 조회
        removed_docs = db.query(DocumentMetadata).filter(
            DocumentMetadata.removed_at.isnot(None),
            DocumentMetadata.removed_at < cutoff_date
        ).all()

        deleted_details = []
        deleted_count = 0

        for doc in removed_docs:
            doc_info = f"document_id={doc.document_id}, file_name={doc.file_name}, removed_at={doc.removed_at}"
            deleted_details.append(doc_info)
            deleted_count += 1

            # dry_run이 아닐 때만 실제 삭제
            if not dry_run:
                db.delete(doc)

        if not dry_run:
            db.commit()

        action = "hard_delete_removed_dry_run" if dry_run else "hard_delete_removed"
        msg_suffix = " (미리보기)" if dry_run else ""

        return CleanupResponse(
            success=True,
            action=action,
            deleted_count=deleted_count,
            message=f"{days_threshold}일 이상 지난 removed 문서 {deleted_count}건 삭제 예정{msg_suffix}",
            details=deleted_details[:20]  # 최대 20건만 반환
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"삭제 실패: {str(e)}")


@router.post("/cleanup/delete-orphans", response_model=CleanupResponse)
async def delete_orphans(
    dry_run: bool = False,
    db: Session = Depends(get_db)
):
    """
    is_orphan=True인 문서(Document Source 매칭 실패)를 삭제합니다.

    - Document Source가 삭제되어 더 이상 매칭되지 않는 문서
    - 경로 변경 등으로 orphan 처리된 문서
    - dry_run=True: 미리보기만 수행 (실제 삭제 없음)
    """
    try:
        orphan_docs = db.query(DocumentMetadata).filter(
            DocumentMetadata.is_orphan == True
        ).all()

        deleted_details = []
        deleted_count = 0

        for doc in orphan_docs:
            doc_info = f"document_id={doc.document_id}, file_name={doc.file_name}, orphan_reason={doc.orphan_reason}"
            deleted_details.append(doc_info)
            deleted_count += 1

            # dry_run이 아닐 때만 실제 삭제
            if not dry_run:
                db.delete(doc)

        if not dry_run:
            db.commit()

        action = "delete_orphans_dry_run" if dry_run else "delete_orphans"
        msg_suffix = " (미리보기)" if dry_run else ""

        return CleanupResponse(
            success=True,
            action=action,
            deleted_count=deleted_count,
            message=f"orphan 문서 {deleted_count}건 삭제 예정{msg_suffix}",
            details=deleted_details[:20]
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"삭제 실패: {str(e)}")


@router.post("/cleanup/mark-excluded", response_model=CleanupResponse)
async def mark_excluded(
    document_ids: List[int],
    reason: str = "수동 제외",
    dry_run: bool = False,
    db: Session = Depends(get_db)
):
    """
    지정된 문서들을 제외 처리합니다.

    - is_excluded=True로 설정
    - exclude_reason에 사유 기록
    - FAISS/Graph/Wiki 빌드에서 자동 제외됨
    - dry_run=True: 미리보기만 수행 (실제 변경 없음)
    """
    try:
        updated_count = 0
        updated_details = []

        for doc_id in document_ids:
            doc = db.query(DocumentMetadata).filter(
                DocumentMetadata.document_id == doc_id
            ).first()

            if doc:
                updated_details.append(f"document_id={doc_id}, file_name={doc.file_name}")
                updated_count += 1

                # dry_run이 아닐 때만 실제 변경
                if not dry_run:
                    doc.is_excluded = True
                    doc.exclude_reason = reason
                    doc.updated_at = datetime.utcnow()

        if not dry_run:
            db.commit()

        action = "mark_excluded_dry_run" if dry_run else "mark_excluded"
        msg_suffix = " (미리보기)" if dry_run else ""

        return CleanupResponse(
            success=True,
            action=action,
            deleted_count=updated_count,
            message=f"{updated_count}건 제외 처리 예정{msg_suffix} (사유: {reason})",
            details=updated_details[:20]
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"제외 처리 실패: {str(e)}")


@router.post("/cleanup/restore-excluded", response_model=CleanupResponse)
async def restore_excluded(
    document_ids: List[int],
    dry_run: bool = False,
    db: Session = Depends(get_db)
):
    """
    제외 처리된 문서들을 복원합니다.

    - is_excluded=False로 복원
    - exclude_reason 초기화
    - dry_run=True: 미리보기만 수행 (실제 변경 없음)
    """
    try:
        restored_count = 0
        restored_details = []

        for doc_id in document_ids:
            doc = db.query(DocumentMetadata).filter(
                DocumentMetadata.document_id == doc_id,
                DocumentMetadata.is_excluded == True
            ).first()

            if doc:
                restored_details.append(f"document_id={doc_id}, file_name={doc.file_name}")
                restored_count += 1

                # dry_run이 아닐 때만 실제 변경
                if not dry_run:
                    doc.is_excluded = False
                    doc.exclude_reason = None
                    doc.updated_at = datetime.utcnow()

        if not dry_run:
            db.commit()

        action = "restore_excluded_dry_run" if dry_run else "restore_excluded"
        msg_suffix = " (미리보기)" if dry_run else ""

        return CleanupResponse(
            success=True,
            action=action,
            deleted_count=restored_count,
            message=f"{restored_count}건 복원 예정{msg_suffix}",
            details=restored_details[:20]
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"복원 실패: {str(e)}")


@router.get("/cleanup/status")
async def get_cleanup_status(db: Session = Depends(get_db)):
    """
    정리 대상 문서 현황을 조회합니다.
    """
    try:
        # removed 문서 수
        removed_count = db.query(func.count(DocumentMetadata.id)).filter(
            DocumentMetadata.removed_at.isnot(None)
        ).scalar() or 0

        # orphan 문서 수
        orphan_count = db.query(func.count(DocumentMetadata.id)).filter(
            DocumentMetadata.is_orphan == True
        ).scalar() or 0

        # excluded 문서 수
        excluded_count = db.query(func.count(DocumentMetadata.id)).filter(
            DocumentMetadata.is_excluded == True
        ).scalar() or 0

        # 30일 이상 지난 removed 문서 수
        from datetime import timedelta
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        old_removed_count = db.query(func.count(DocumentMetadata.id)).filter(
            DocumentMetadata.removed_at.isnot(None),
            DocumentMetadata.removed_at < cutoff_date
        ).scalar() or 0

        return {
            "success": True,
            "removed_count": removed_count,
            "old_removed_count": old_removed_count,
            "orphan_count": orphan_count,
            "excluded_count": excluded_count,
            "message": f"정리 대상: removed={removed_count}건(30일+: {old_removed_count}건), orphan={orphan_count}건, excluded={excluded_count}건"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"상태 조회 실패: {str(e)}")
