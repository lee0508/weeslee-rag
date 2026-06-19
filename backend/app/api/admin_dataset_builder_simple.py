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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.auth import require_admin_token
from app.core.database import SessionLocal, get_db
from app.models.document_metadata import DocumentMetadata, MetaStatus, ProcessingStatus
from app.services.document_source_paths import resolve_scan_root
from app.services.document_uid import make_document_uid, detect_file_change, calculate_file_checksum
from app.services.platform_store import get_record
from app.services.tag_keyword_generator import TagKeywordGenerator
from app.services.dataset_context import get_source_dataset_context

router = APIRouter(
    prefix="/admin/dataset-builder",
    tags=["Admin - Dataset Builder"],
    dependencies=[Depends(require_admin_token)],
)

# 지원 파일 확장자
SUPPORTED_EXTENSIONS = {".hwp", ".hwpx", ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls"}

# category_id 매핑 (폴더명 기반)
# 제안서/산출물 하위 폴더 → category_id
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
    "04. 이행계획": "cat_impl_plan",
}

# document_group 매핑 (최상위 폴더 → 문서 그룹)
DOCUMENT_GROUP_MAP = {
    "01. RFP": "RFP",
    "02. 제안서": "제안서",
    "03. 산출물": "산출물",
}


def normalize_numbered_name(name: str) -> str:
    """
    '01. 전략및방법론' -> '전략및방법론'
    '02. 현황분석' -> '현황분석'
    """
    import re
    if not name:
        return ""
    return re.sub(r"^\d+\.\s*", "", name).strip()


def normalize_slug(value: str) -> str:
    """
    category_id fallback 생성용.
    한글/공백/특수문자가 섞인 폴더명을 안전한 문자열로 변환.
    """
    import re
    value = normalize_numbered_name(value)
    value = value.strip().lower()
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^\w가-힣_]+", "_", value)
    value = value.strip("_")
    return value or "unknown"


def split_path_parts(value: str) -> List[str]:
    return [part for part in str(value or "").replace("\\", "/").split("/") if part and part != "."]


def looks_like_file(name: str) -> bool:
    if not name:
        return False
    suffix = Path(name).suffix.lower()
    return suffix in SUPPORTED_EXTENSIONS


def extract_source_context_parts(source: Optional[Dict[str, Any]]) -> List[str]:
    if not source:
        return []

    scan_root = str(resolve_scan_root(source)).replace("\\", "/")
    parts = split_path_parts(scan_root)
    if not parts:
        return []

    try:
        root_idx = parts.index("00. RAG 소스")
        return parts[root_idx + 1:]
    except ValueError:
        pass

    for idx, part in enumerate(parts):
        if part in DOCUMENT_GROUP_MAP:
            return parts[idx:]

    return []


def fit_text(value: str, max_len: int) -> str:
    value = str(value or "").strip()
    return value[:max_len] if len(value) > max_len else value


def classify_relative_path(relative_path: str, source: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    00. RAG 소스 기준 relative_path를 분석하여
    document_group, category_folder, category_id, section_type을 반환.

    폴더 구조 예시:
    - 01. RFP/RFP_축산유통 데이터랩 고도화.hwp
    - 02. 제안서/01. 전략및방법론/전략및방법론_사업명.pptx
    - 03. 산출물/02. 현황분석/현황분석_사업명.pptx
    """
    path_parts = extract_source_context_parts(source) + split_path_parts(relative_path)

    top_folder = path_parts[0] if len(path_parts) >= 1 else ""
    second_folder = path_parts[1] if len(path_parts) >= 2 else ""

    document_group = DOCUMENT_GROUP_MAP.get(top_folder, normalize_numbered_name(top_folder))

    if looks_like_file(top_folder):
        source_name = normalize_numbered_name((source or {}).get("source_name", ""))
        document_group = source_name or ""
        category_folder = source_name or ""
        category_id = f"cat_{normalize_slug(category_folder)}" if category_folder else "cat_unknown"
        section_type = source_name or ""
        return {
            "document_group": fit_text(document_group, 50),
            "category_folder": fit_text(category_folder, 100),
            "category_id": fit_text(category_id, 100),
            "section_type": fit_text(section_type, 100),
        }

    # RFP는 하위 섹션 폴더가 없으므로 cat_rfp로 처리
    if top_folder == "01. RFP":
        category_folder = top_folder
        category_id = "cat_rfp"
        section_type = "RFP"

    # 제안서/산출물은 두 번째 폴더가 실제 섹션
    elif top_folder in ("02. 제안서", "03. 산출물"):
        category_folder = second_folder
        category_id = CATEGORY_ID_MAP.get(
            second_folder,
            f"cat_{normalize_slug(second_folder)}" if second_folder else "cat_unknown"
        )
        section_type = normalize_numbered_name(second_folder) if second_folder else ""

    else:
        # 기타 폴더 구조
        category_folder = second_folder or top_folder
        category_id = CATEGORY_ID_MAP.get(
            category_folder,
            f"cat_{normalize_slug(category_folder)}"
        )
        section_type = normalize_numbered_name(category_folder)

    return {
        "document_group": fit_text(document_group, 50),
        "category_folder": fit_text(category_folder, 100),
        "category_id": fit_text(category_id, 100),
        "section_type": fit_text(section_type, 100),
    }


def get_document_source(source_id: str) -> Optional[Dict[str, Any]]:
    """Document Source 설정 조회"""
    return get_record("document_sources", "source_id", source_id)


def get_scan_root(source: Dict[str, Any]) -> Path:
    """Document Source에서 실제 스캔 루트 경로를 계산한다."""
    return resolve_scan_root(source)


class ScanRequest(BaseModel):
    source_id: Optional[str] = None
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


class TagKeywordGenerateRequest(BaseModel):
    source_id: str
    snapshot_id: Optional[str] = None
    overwrite: bool = False


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


def extract_scan_metadata(filename: str, relative_path: str) -> Dict[str, Any]:
    """파일명과 상대 경로에서 scan_* 메타데이터를 추출한다."""
    import re

    project_name = extract_project_name(filename) or None

    # 연도 추출: 파일명 또는 경로에서 20XX 패턴 (2000-2029)
    year = None
    year_match = re.search(r'\b(20[012]\d)\b', filename + "/" + relative_path)
    if year_match:
        year = int(year_match.group(1))

    return {
        "scan_project_name": project_name,
        "scan_year": str(year) if year is not None else None,
    }


def generate_tag_keyword_for_source(body: TagKeywordGenerateRequest) -> dict:
    db = SessionLocal()
    try:
        generator = TagKeywordGenerator(
            db=db,
            source_id=body.source_id,
            snapshot_id=body.snapshot_id,
            overwrite=body.overwrite,
        )
        return generator.run()
    except Exception as exc:
        import traceback
        return {
            "success": False,
            "message": f"Tag/Keyword 생성 중 오류 발생: {str(exc)}",
            "source_id": body.source_id,
            "snapshot_id": body.snapshot_id,
            "error_detail": traceback.format_exc(),
        }
    finally:
        db.close()


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
    source_id = (request.source_id or "").strip()
    warnings: List[str] = []
    errors: List[str] = []
    by_extension: Dict[str, int] = {}
    samples: Dict[str, List[str]] = {"new": [], "changed": [], "removed": [], "excluded": [], "restored": []}

    if not source_id:
        return ScanResponse(
            success=False,
            source_id="",
            scan_root="",
            total_files=0, supported_files=0, excluded_files=0,
            new_files=0, changed_files=0, removed_files=0, unchanged_files=0, restored_files=0,
            documents_created=0, documents_updated=0, total_metadata=0,
            by_extension={}, samples={},
            warnings=[], errors=["source_id가 지정되지 않았습니다."],
            next_action="Document Source를 먼저 선택하세요.",
            message="source_id가 지정되지 않았습니다."
        )

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
                    file_modified_at = datetime.fromtimestamp(stat.st_mtime).replace(microsecond=0)
                except Exception as e:
                    warnings.append(f"파일 정보 읽기 실패: {relative_path} - {e}")
                    continue

                # 확장자별 카운트
                ext_key = ext.lstrip(".")
                by_extension[ext_key] = by_extension.get(ext_key, 0) + 1

                # classify_relative_path()로 분류 정보 추출
                classification = classify_relative_path(relative_path, source)

                current_files[relative_path] = {
                    "filename": filename,
                    "filepath": str(filepath),
                    "relative_path": relative_path,
                    "extension": ext_key,
                    "size": stat.st_size,
                    "modified_at": file_modified_at,
                    "category_id": classification["category_id"],
                    "document_group": classification["document_group"],
                    "section_type": classification["section_type"],
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

        # source dataset_id 조회 (없으면 None)
        _source_dataset_id = get_source_dataset_context(source_id).get("dataset_id")

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
                metadata_backfilled = False
                if not existing.document_uid:
                    existing.document_uid = doc_uid
                    metadata_backfilled = True
                if not existing.relative_path:
                    existing.relative_path = rel_path
                    metadata_backfilled = True
                if existing.category_id != file_info.get("category_id"):
                    existing.category_id = file_info.get("category_id")
                    metadata_backfilled = True
                if existing.document_group != file_info.get("document_group"):
                    existing.document_group = file_info.get("document_group")
                    metadata_backfilled = True
                if existing.section_type != file_info.get("section_type"):
                    existing.section_type = file_info.get("section_type")
                    metadata_backfilled = True

                # scan_* 필드 보정 (없으면 추가)
                if not existing.scan_project_name or not existing.scan_year:
                    scan_meta = extract_scan_metadata(file_info["filename"], rel_path)
                    if not existing.scan_project_name and scan_meta["scan_project_name"]:
                        existing.scan_project_name = scan_meta["scan_project_name"]
                        metadata_backfilled = True
                    if not existing.scan_year and scan_meta["scan_year"]:
                        existing.scan_year = scan_meta["scan_year"]
                        metadata_backfilled = True
                if not existing.scan_document_category and file_info.get("document_group"):
                    existing.scan_document_category = file_info.get("document_group")
                    metadata_backfilled = True
                if not existing.dataset_id and _source_dataset_id:
                    existing.dataset_id = _source_dataset_id
                    metadata_backfilled = True

                if metadata_backfilled:
                    existing.updated_at = datetime.utcnow()
                    documents_updated += 1

            else:
                # 5b. 신규 파일
                checksum = None
                if request.compute_checksum:
                    try:
                        checksum = calculate_file_checksum(Path(file_info["filepath"]))
                    except Exception:
                        pass

                scan_meta = extract_scan_metadata(file_info["filename"], rel_path)
                document_group = file_info.get("document_group", "") or ""

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
                    document_group=document_group,
                    section_type=file_info.get("section_type", ""),
                    dataset_id=_source_dataset_id,
                    scan_project_name=scan_meta["scan_project_name"],
                    scan_year=scan_meta["scan_year"],
                    scan_document_category=document_group or None,
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


@router.post("/tag-keyword/generate")
async def dataset_builder_tag_keyword_generate(body: TagKeywordGenerateRequest):
    """현재 Document Source 기준 Tag/Keyword 생성 alias."""
    return generate_tag_keyword_for_source(body)


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


@router.get("/step1/records")
async def get_step1_records(
    source_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    meta_status: Optional[str] = Query(None),
    include_removed: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Step 1 Source Scan으로 등록된 document_metadata 레코드 조회"""
    try:
        query = db.query(DocumentMetadata)

        if source_id:
            query = query.filter(DocumentMetadata.source_id == source_id)
        if status:
            query = query.filter(DocumentMetadata.status == status)
        if meta_status:
            query = query.filter(DocumentMetadata.meta_status == meta_status)
        if not include_removed:
            query = query.filter(DocumentMetadata.removed_at.is_(None))

        total = query.count()

        rows = (
            query
            .order_by(DocumentMetadata.updated_at.desc(), DocumentMetadata.document_id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        items = []
        for row in rows:
            item = row.to_dict()
            items.append({
                "id": item.get("id"),
                "document_id": item.get("document_id"),
                "source_id": item.get("source_id"),
                "document_uid": item.get("document_uid"),
                "relative_path": item.get("relative_path"),
                "file_name": item.get("file_name"),
                "file_type": item.get("file_type"),
                "file_size": item.get("file_size"),
                "file_modified_at": item.get("file_modified_at"),
                "category_id": item.get("category_id"),
                "document_group": item.get("document_group"),
                "section_type": item.get("section_type"),
                "status": item.get("status"),
                "meta_status": item.get("meta_status"),
                "is_excluded": item.get("is_excluded"),
                "removed_at": item.get("removed_at"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            })

        return {
            "success": True,
            "source_id": source_id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "count": len(items),
            "items": items,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Step 1 레코드 조회 실패: {str(e)}")


@router.get("/step2/records")
async def get_step2_records(
    source_id: Optional[str] = Query(None),
    meta_status: Optional[str] = Query(MetaStatus.METADATA_SUGGESTED.value),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Step 2 Metadata Builder 결과 레코드 조회"""
    try:
        query = db.query(DocumentMetadata)

        if source_id:
            query = query.filter(DocumentMetadata.source_id == source_id)
        if meta_status:
            query = query.filter(DocumentMetadata.meta_status == meta_status)

        total = query.count()

        rows = (
            query
            .order_by(DocumentMetadata.updated_at.desc(), DocumentMetadata.document_id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        items = []
        for row in rows:
            item = row.to_dict()
            items.append({
                "id": item.get("id"),
                "document_id": item.get("document_id"),
                "source_id": item.get("source_id"),
                "document_uid": item.get("document_uid"),
                "relative_path": item.get("relative_path"),
                "file_name": item.get("file_name"),
                "file_type": item.get("file_type"),
                "category_id": item.get("category_id"),
                "document_group": item.get("document_group"),
                "section_type": item.get("section_type"),
                "project_name": item.get("project_name"),
                "project_name_confidence": item.get("project_name_confidence"),
                "organization": item.get("organization"),
                "organization_confidence": item.get("organization_confidence"),
                "document_type": item.get("document_type"),
                "document_type_confidence": item.get("document_type_confidence"),
                "year": item.get("year"),
                "collection_candidates": item.get("collection_candidates") or [],
                "final_collections": item.get("final_collections") or [],
                "status": item.get("status"),
                "meta_status": item.get("meta_status"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            })

        return {
            "success": True,
            "source_id": source_id,
            "meta_status": meta_status,
            "total": total,
            "limit": limit,
            "offset": offset,
            "count": len(items),
            "items": items,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Step 2 레코드 조회 실패: {str(e)}")


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
