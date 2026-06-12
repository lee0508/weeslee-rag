# ============================================================
# DEPRECATED: 2026-06-12
# ============================================================
# 이 파일은 과거 Dataset Builder API 실험용 파일입니다.
# 실제 운영 라우터는 main.py에서 import되는 파일을 기준으로 합니다.
#
# 운영 파일:
#   - admin_dataset_builder_simple.py (Step 1-3)
#   - admin_dataset_builder_step4.py ~ step10.py
#
# 신규 수정은 운영 라우터 파일에만 적용하세요.
# 삭제 예정: Dataset Builder Step 1~10 통합 완료 및 안정화 확인 후
# ============================================================

# Dataset Builder 10단계 워크플로우 API (DEPRECATED)
"""
Dataset Builder 10-Step Workflow API

Step 1: Source Scan - 소스 폴더 스캔 및 documents, document_metadata 레코드 생성
Step 2: Metadata Auto - 자동 메타데이터 생성 (프로젝트명, 기관명, 연도 등)

[DEPRECATED] 이 모듈은 더 이상 main.py에서 import되지 않습니다.
"""
from datetime import datetime
from typing import Optional, List
from pathlib import Path
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.auth import require_admin_token
from app.core.database import get_db
from app.models.document import Document
from app.models.document_metadata import DocumentMetadata, MetaStatus

router = APIRouter(
    prefix="/admin/dataset-builder",
    tags=["Admin - Dataset Builder"],
    dependencies=[Depends(require_admin_token)],
)

# 지원 파일 확장자
SUPPORTED_EXTENSIONS = {".hwp", ".hwpx", ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls"}

# RAG 소스 루트 경로 (네트워크 마운트 경로)
RAG_SOURCE_ROOT = "/mnt/w2_project/00. RAG 소스"

# source_id 매핑
SOURCE_ID_MAP = {
    "01. RFP": "src_rfp",
    "02. 제안서": "src_proposal",
    "03. 산출물": "src_output"
}

# category_id 매핑
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


# ── Request/Response Models ─────────────────────────────────────────────────


class ScanRequest(BaseModel):
    """Step 1: Source Scan 요청"""
    source_id: Optional[str] = "rag_source"
    overwrite: bool = False


class ScanResponse(BaseModel):
    """Step 1: Source Scan 응답"""
    success: bool
    total_files: int
    documents: int
    by_source: dict  # 소스별 파일 수 {"src_rfp": 10, "src_proposal": 20, "src_output": 15}
    excluded: int    # 제외된 파일 수 (지원하지 않는 확장자)
    message: str


class MetadataAutoRequest(BaseModel):
    """Step 2: Metadata Auto 요청"""
    only_missing: bool = True
    overwrite: bool = False


class MetadataAutoResponse(BaseModel):
    """Step 2: Metadata Auto 응답"""
    success: bool
    processed: int
    updated: int
    skipped: int
    message: str


# ── Helper Functions ────────────────────────────────────────────────────────


def scan_folder(folder_path: str, extensions: set) -> tuple[List[dict], int]:
    """폴더를 재귀적으로 스캔하여 파일 목록 반환

    Returns:
        (files, excluded_count): 지원 파일 목록과 제외된 파일 수
    """
    files = []
    excluded_count = 0

    if not os.path.exists(folder_path):
        return files, excluded_count

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
            elif ext:  # 확장자는 있지만 지원하지 않는 파일
                excluded_count += 1

    return files, excluded_count


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

    # 언더스코어로 시작하는 경우 첫 부분 제거
    if "_" in name and not any(name.startswith(p) for p in prefixes):
        parts = name.split("_", 1)
        if len(parts) > 1 and len(parts[0]) < 10:
            name = parts[1]

    return name.strip()


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.post("/step1/scan", response_model=ScanResponse)
async def step1_source_scan(request: ScanRequest, db: Session = Depends(get_db)):
    """
    Step 1: Source Scan

    - 네트워크 마운트 경로의 RAG 소스 폴더를 스캔
    - documents 테이블에 파일 정보 저장
    - document_metadata 테이블에 초기 레코드 생성 (meta_status='registered')
    """
    try:
        if not os.path.exists(RAG_SOURCE_ROOT):
            raise HTTPException(
                status_code=404,
                detail=f"RAG 소스 폴더를 찾을 수 없습니다: {RAG_SOURCE_ROOT}"
            )

        total_files = 0
        documents_created = 0
        total_excluded = 0
        by_source = {"src_rfp": 0, "src_proposal": 0, "src_output": 0}

        # 01. RFP 폴더 스캔
        rfp_folder = os.path.join(RAG_SOURCE_ROOT, "01. RFP")
        if os.path.exists(rfp_folder):
            files, excluded = scan_folder(rfp_folder, SUPPORTED_EXTENSIONS)
            total_excluded += excluded

            for file_info in files:
                # documents 테이블에 레코드 생성 또는 업데이트
                existing_doc = db.query(Document).filter(
                    Document.file_path == file_info["filepath"]
                ).first()

                if existing_doc:
                    if request.overwrite:
                        existing_doc.filename = file_info["filename"]
                        existing_doc.file_size = file_info["size"]
                        existing_doc.file_extension = file_info["extension"]
                        existing_doc.updated_at = datetime.utcnow()
                else:
                    new_doc = Document(
                        filename=file_info["filename"],
                        file_path=file_info["filepath"],
                        file_size=file_info["size"],
                        file_extension=file_info["extension"],
                        status="registered",
                    )
                    db.add(new_doc)
                    db.flush()  # ID 생성

                    # document_metadata 레코드 생성
                    new_meta = DocumentMetadata(
                        document_id=new_doc.id,
                        source_id="src_rfp",
                        file_path=file_info["filepath"],
                        category_id="cat_rfp",
                        meta_status=MetaStatus.REGISTERED.value,
                        include_in_rag=True,
                        include_in_graph=True,
                        include_in_wiki=True,
                    )
                    db.add(new_meta)
                    documents_created += 1

                total_files += 1
                by_source["src_rfp"] += 1

        # 02. 제안서 폴더 스캔
        proposal_folder = os.path.join(RAG_SOURCE_ROOT, "02. 제안서")
        if os.path.exists(proposal_folder):
            for category_folder in os.listdir(proposal_folder):
                category_path = os.path.join(proposal_folder, category_folder)
                if not os.path.isdir(category_path):
                    continue

                category_id = CATEGORY_ID_MAP.get(category_folder, f"cat_{category_folder}")
                files, excluded = scan_folder(category_path, SUPPORTED_EXTENSIONS)
                total_excluded += excluded

                for file_info in files:
                    existing_doc = db.query(Document).filter(
                        Document.file_path == file_info["filepath"]
                    ).first()

                    if existing_doc:
                        if request.overwrite:
                            existing_doc.filename = file_info["filename"]
                            existing_doc.file_size = file_info["size"]
                            existing_doc.file_extension = file_info["extension"]
                            existing_doc.updated_at = datetime.utcnow()
                    else:
                        new_doc = Document(
                            filename=file_info["filename"],
                            file_path=file_info["filepath"],
                            file_size=file_info["size"],
                            file_extension=file_info["extension"],
                            status="registered",
                        )
                        db.add(new_doc)
                        db.flush()

                        new_meta = DocumentMetadata(
                            document_id=new_doc.id,
                            source_id="src_proposal",
                            file_path=file_info["filepath"],
                            category_id=category_id,
                            meta_status=MetaStatus.REGISTERED.value,
                            include_in_rag=True,
                            include_in_graph=True,
                            include_in_wiki=True,
                        )
                        db.add(new_meta)
                        documents_created += 1

                    total_files += 1
                    by_source["src_proposal"] += 1

        # 03. 산출물 폴더 스캔
        output_folder = os.path.join(RAG_SOURCE_ROOT, "03. 산출물")
        if os.path.exists(output_folder):
            for category_folder in os.listdir(output_folder):
                category_path = os.path.join(output_folder, category_folder)
                if not os.path.isdir(category_path):
                    continue

                category_id = CATEGORY_ID_MAP.get(category_folder, f"cat_{category_folder}")
                files, excluded = scan_folder(category_path, SUPPORTED_EXTENSIONS)
                total_excluded += excluded

                for file_info in files:
                    existing_doc = db.query(Document).filter(
                        Document.file_path == file_info["filepath"]
                    ).first()

                    if existing_doc:
                        if request.overwrite:
                            existing_doc.filename = file_info["filename"]
                            existing_doc.file_size = file_info["size"]
                            existing_doc.file_extension = file_info["extension"]
                            existing_doc.updated_at = datetime.utcnow()
                    else:
                        new_doc = Document(
                            filename=file_info["filename"],
                            file_path=file_info["filepath"],
                            file_size=file_info["size"],
                            file_extension=file_info["extension"],
                            status="registered",
                        )
                        db.add(new_doc)
                        db.flush()

                        new_meta = DocumentMetadata(
                            document_id=new_doc.id,
                            source_id="src_output",
                            file_path=file_info["filepath"],
                            category_id=category_id,
                            meta_status=MetaStatus.REGISTERED.value,
                            include_in_rag=True,
                            include_in_graph=True,
                            include_in_wiki=True,
                        )
                        db.add(new_meta)
                        documents_created += 1

                    total_files += 1
                    by_source["src_output"] += 1

        db.commit()

        return ScanResponse(
            success=True,
            total_files=total_files,
            documents=documents_created,
            by_source=by_source,
            excluded=total_excluded,
            message=f"Source Scan 완료: {total_files}개 파일 스캔, {documents_created}개 문서 등록, {total_excluded}개 파일 제외됨"
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Source Scan 실패: {str(e)}")


@router.post("/step2/metadata-auto", response_model=MetadataAutoResponse)
async def step2_metadata_auto(request: MetadataAutoRequest, db: Session = Depends(get_db)):
    """
    Step 2: Metadata Auto

    - 파일명에서 프로젝트명 추출
    - meta_status를 'metadata_suggested'로 변경
    - 자동 추출된 메타데이터는 confidence 필드에 0.5 설정
    """
    try:
        # meta_status가 'registered'인 레코드 조회
        query = db.query(DocumentMetadata)

        if request.only_missing:
            query = query.filter(DocumentMetadata.meta_status == MetaStatus.REGISTERED.value)

        metadata_list = query.all()

        processed = 0
        updated = 0
        skipped = 0

        for metadata in metadata_list:
            # Document 조회
            doc = db.query(Document).filter(Document.id == metadata.document_id).first()
            if not doc:
                skipped += 1
                continue

            # 이미 메타데이터가 있고 overwrite가 False면 건너뜀
            if metadata.project_name and not request.overwrite:
                skipped += 1
                continue

            # 파일명에서 프로젝트명 추출
            project_name = extract_project_name(doc.filename)

            # 메타데이터 업데이트
            metadata.project_name = project_name
            metadata.project_name_confidence = 0.5  # 자동 추출 confidence
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
        raise HTTPException(status_code=500, detail=f"Metadata Auto 실패: {str(e)}")


@router.get("/stats")
async def get_dataset_builder_stats(db: Session = Depends(get_db)):
    """
    Dataset Builder 통계 조회

    - 전체 문서 수
    - Step별 문서 수
    - source_id별 문서 수
    """
    try:
        # 전체 문서 수
        total_documents = db.query(func.count(Document.id)).scalar()

        # 전체 메타데이터 수
        total_metadata = db.query(func.count(DocumentMetadata.id)).scalar()

        # meta_status별 카운트
        status_counts = {}
        status_stats = db.query(
            DocumentMetadata.meta_status,
            func.count(DocumentMetadata.id).label('count')
        ).group_by(DocumentMetadata.meta_status).all()

        for status, count in status_stats:
            status_counts[status or "registered"] = count

        # source_id별 카운트
        source_counts = {}
        source_stats = db.query(
            DocumentMetadata.source_id,
            func.count(DocumentMetadata.id).label('count')
        ).group_by(DocumentMetadata.source_id).all()

        for source_id, count in source_stats:
            source_counts[source_id or "unknown"] = count

        return {
            "success": True,
            "total_documents": total_documents,
            "total_metadata": total_metadata,
            "status_counts": status_counts,
            "source_counts": source_counts,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통계 조회 실패: {str(e)}")
