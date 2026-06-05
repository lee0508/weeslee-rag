# Dataset Builder Step 1, 2 API (Simplified - metadata only)
"""
Dataset Builder API - document_metadata 테이블만 사용
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
from app.models.document_metadata import DocumentMetadata, MetaStatus

router = APIRouter(
    prefix="/admin/dataset-builder",
    tags=["Admin - Dataset Builder"],
    dependencies=[Depends(require_admin_token)],
)

# 지원 파일 확장자
SUPPORTED_EXTENSIONS = {".hwp", ".hwpx", ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls"}

# RAG 소스 루트 경로
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


class ScanRequest(BaseModel):
    source_id: Optional[str] = "rag_source"
    overwrite: bool = False


class ScanResponse(BaseModel):
    success: bool
    total_files: int
    metadata_records: int
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
    Step 1: Source Scan - document_metadata 테이블에만 레코드 생성
    """
    try:
        if not os.path.exists(RAG_SOURCE_ROOT):
            return ScanResponse(
                success=False,
                total_files=0,
                metadata_records=0,
                message=f"RAG 소스 폴더를 찾을 수 없습니다: {RAG_SOURCE_ROOT}"
            )

        total_files = 0
        metadata_created = 0

        # 01. RFP 폴더 스캔
        rfp_folder = os.path.join(RAG_SOURCE_ROOT, "01. RFP")
        if os.path.exists(rfp_folder):
            files = scan_folder(rfp_folder, SUPPORTED_EXTENSIONS)
            for file_info in files:
                existing_meta = db.query(DocumentMetadata).filter(
                    DocumentMetadata.file_path == file_info["filepath"]
                ).first()

                if existing_meta:
                    if request.overwrite:
                        existing_meta.updated_at = datetime.utcnow()
                else:
                    new_meta = DocumentMetadata(
                        document_id=0,  # Placeholder
                        source_id="src_rfp",
                        file_path=file_info["filepath"],
                        category_id="cat_rfp",
                        meta_status=MetaStatus.REGISTERED.value,
                        include_in_rag=True,
                        include_in_graph=True,
                        include_in_wiki=True,
                    )
                    db.add(new_meta)
                    metadata_created += 1

                total_files += 1

        # 02. 제안서 폴더 스캔
        proposal_folder = os.path.join(RAG_SOURCE_ROOT, "02. 제안서")
        if os.path.exists(proposal_folder):
            for category_folder in os.listdir(proposal_folder):
                category_path = os.path.join(proposal_folder, category_folder)
                if not os.path.isdir(category_path):
                    continue

                category_id = CATEGORY_ID_MAP.get(category_folder, f"cat_{category_folder}")
                files = scan_folder(category_path, SUPPORTED_EXTENSIONS)

                for file_info in files:
                    existing_meta = db.query(DocumentMetadata).filter(
                        DocumentMetadata.file_path == file_info["filepath"]
                    ).first()

                    if existing_meta:
                        if request.overwrite:
                            existing_meta.updated_at = datetime.utcnow()
                    else:
                        new_meta = DocumentMetadata(
                            document_id=0,
                            source_id="src_proposal",
                            file_path=file_info["filepath"],
                            category_id=category_id,
                            meta_status=MetaStatus.REGISTERED.value,
                            include_in_rag=True,
                            include_in_graph=True,
                            include_in_wiki=True,
                        )
                        db.add(new_meta)
                        metadata_created += 1

                    total_files += 1

        # 03. 산출물 폴더 스캔
        output_folder = os.path.join(RAG_SOURCE_ROOT, "03. 산출물")
        if os.path.exists(output_folder):
            for category_folder in os.listdir(output_folder):
                category_path = os.path.join(output_folder, category_folder)
                if not os.path.isdir(category_path):
                    continue

                category_id = CATEGORY_ID_MAP.get(category_folder, f"cat_{category_folder}")
                files = scan_folder(category_path, SUPPORTED_EXTENSIONS)

                for file_info in files:
                    existing_meta = db.query(DocumentMetadata).filter(
                        DocumentMetadata.file_path == file_info["filepath"]
                    ).first()

                    if existing_meta:
                        if request.overwrite:
                            existing_meta.updated_at = datetime.utcnow()
                    else:
                        new_meta = DocumentMetadata(
                            document_id=0,
                            source_id="src_output",
                            file_path=file_info["filepath"],
                            category_id=category_id,
                            meta_status=MetaStatus.REGISTERED.value,
                            include_in_rag=True,
                            include_in_graph=True,
                            include_in_wiki=True,
                        )
                        db.add(new_meta)
                        metadata_created += 1

                    total_files += 1

        db.commit()

        return ScanResponse(
            success=True,
            total_files=total_files,
            metadata_records=metadata_created,
            message=f"Source Scan 완료: {total_files}개 파일 스캔, {metadata_created}개 메타데이터 레코드 생성"
        )

    except Exception as e:
        db.rollback()
        return ScanResponse(
            success=False,
            total_files=0,
            metadata_records=0,
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
