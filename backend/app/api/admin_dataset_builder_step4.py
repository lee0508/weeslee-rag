# Dataset Builder Step 4: OCR/Parser API
"""
Step 4는 검수 완료된 문서에 대해 OCR/파싱을 수행하여 텍스트를 추출합니다.
"""
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.auth import require_admin_token
from app.core.database import get_db
from app.models.document_metadata import DocumentMetadata, MetaStatus
from app.services.processed_text_store import processed_text_store, ProcessingResult
from app.extractors.hwp_extractor import extract_hwp_text
from app.extractors.pptx_extractor import extract_pptx_text


router = APIRouter(
    prefix="/admin/dataset-builder/step4",
    tags=["Admin - Dataset Builder Step 4"],
    dependencies=[Depends(require_admin_token)],
)


# ── Request/Response Models ─────────────────────────────────────────────────


class ParseRequest(BaseModel):
    """파싱 실행 요청"""
    document_ids: Optional[List[int]] = None  # None이면 모든 검수 완료 문서
    force_reparse: bool = False  # True면 이미 처리된 문서도 재처리


class ParseResponse(BaseModel):
    """파싱 실행 응답"""
    success: bool
    message: str
    total_documents: int
    processed: int
    failed: int
    skipped: int
    processing_time: float  # seconds
    failures: List[dict] = []


class Step4StatusResponse(BaseModel):
    """Step 4 상태 응답"""
    total: int
    pending: int
    processing: int
    completed: int
    failed: int
    by_source: dict
    by_file_type: dict


# ── Helper Functions ────────────────────────────────────────────────────────


def parse_document(document_id: int, file_path: str, force: bool = False) -> dict:
    """
    단일 문서 파싱 처리

    Returns:
        {"success": bool, "document_id": int, "error": str or None, "text_length": int}
    """
    result = {
        "success": False,
        "document_id": document_id,
        "error": None,
        "text_length": 0,
    }

    try:
        # 이미 처리된 문서는 건너뛰기 (force=False인 경우)
        if not force and processed_text_store.exists(str(document_id)):
            result["success"] = True
            result["error"] = "already_processed"
            return result

        # 파일 존재 확인
        if not Path(file_path).exists():
            result["error"] = f"File not found: {file_path}"
            return result

        # 파일 확장자 확인
        file_ext = Path(file_path).suffix.lower()

        # ProcessingResult 초기화
        processing_result = ProcessingResult(
            document_id=str(document_id),
            file_name=Path(file_path).name,
            source_path=file_path,
            file_extension=file_ext,
            status="processing",
        )

        start_time = datetime.now()

        # 파일 형식별 파싱
        if file_ext in ['.hwp', '.hwpx']:
            # HWP 파싱
            text = extract_hwp_text(file_path)
            processing_result.parser_type = "hwp5txt"
            processing_result.full_text = text
            processing_result.full_text_md = f"# {Path(file_path).name}\n\n{text}"

        elif file_ext == '.pdf':
            # PDF 파싱
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                pages = []
                full_text_parts = []

                for i, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text() or ""
                    full_text_parts.append(page_text)
                    pages.append({
                        "page_num": i,
                        "text": page_text,
                        "char_count": len(page_text)
                    })

                processing_result.full_text = "\n\n".join(full_text_parts)
                processing_result.full_text_md = f"# {Path(file_path).name}\n\n{processing_result.full_text}"
                processing_result.pages = pages
                processing_result.parser_type = "pdfplumber"

        elif file_ext in ['.docx', '.doc']:
            # DOCX 파싱
            from docx import Document
            doc = Document(file_path)
            paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
            processing_result.full_text = "\n\n".join(paragraphs)
            processing_result.full_text_md = f"# {Path(file_path).name}\n\n{processing_result.full_text}"
            processing_result.parser_type = "python-docx"

        elif file_ext in ['.pptx', '.ppt']:
            # PPTX 파싱
            text = extract_pptx_text(file_path)
            processing_result.full_text = text
            processing_result.full_text_md = f"# {Path(file_path).name}\n\n{text}"
            processing_result.parser_type = "python-pptx"

        elif file_ext in ['.xlsx', '.xls']:
            # XLSX 파싱
            import pandas as pd
            df_dict = pd.read_excel(file_path, sheet_name=None)
            text_parts = []
            for sheet_name, df in df_dict.items():
                text_parts.append(f"[Sheet: {sheet_name}]\n{df.to_string()}")
            processing_result.full_text = "\n\n".join(text_parts)
            processing_result.full_text_md = f"# {Path(file_path).name}\n\n{processing_result.full_text}"
            processing_result.parser_type = "pandas"

        else:
            result["error"] = f"Unsupported file type: {file_ext}"
            processing_result.status = "failed"
            processing_result.error_message = result["error"]
            processed_text_store.save_result(processing_result)
            return result

        # 처리 완료
        end_time = datetime.now()
        processing_time_ms = int((end_time - start_time).total_seconds() * 1000)

        processing_result.status = "done"
        processing_result.processing_time_ms = processing_time_ms
        processing_result.text_length = len(processing_result.full_text)

        # 품질 체크 (간단한 버전)
        quality_score = 1.0
        if processing_result.text_length < 100:
            quality_score = 0.3
        elif processing_result.text_length < 500:
            quality_score = 0.6

        processing_result.quality = {
            "quality_score": quality_score,
            "text_length": processing_result.text_length,
            "recommendation": "excellent" if quality_score > 0.8 else ("acceptable" if quality_score > 0.5 else "review_required")
        }

        # 저장
        if processed_text_store.save_result(processing_result):
            result["success"] = True
            result["text_length"] = processing_result.text_length
        else:
            result["error"] = "Failed to save result"

    except Exception as e:
        result["error"] = str(e)

        # 실패 결과도 저장
        processing_result = ProcessingResult(
            document_id=str(document_id),
            file_name=Path(file_path).name,
            source_path=file_path,
            file_extension=Path(file_path).suffix.lower(),
            status="failed",
            error_message=str(e),
        )
        processed_text_store.save_result(processing_result)

    return result


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.post("/parse", response_model=ParseResponse)
async def parse_documents(
    request: ParseRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    검수 완료된 문서들에 대해 OCR/파싱을 실행합니다.

    - document_ids가 없으면 모든 검수 완료(metadata_reviewed) 문서를 처리
    - force_reparse=True이면 이미 처리된 문서도 재처리
    """
    start_time = datetime.now()

    try:
        # 처리 대상 문서 조회
        query = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag == True,
        )

        if request.document_ids:
            query = query.filter(DocumentMetadata.document_id.in_(request.document_ids))

        documents = query.all()

        if not documents:
            return ParseResponse(
                success=True,
                message="No documents to process",
                total_documents=0,
                processed=0,
                failed=0,
                skipped=0,
                processing_time=0.0,
            )

        # 문서 처리
        total = len(documents)
        processed = 0
        failed = 0
        skipped = 0
        failures = []

        for doc in documents:
            if not doc.file_path:
                failures.append({
                    "document_id": doc.document_id,
                    "file_path": None,
                    "error": "No file path"
                })
                failed += 1
                continue

            result = parse_document(
                document_id=doc.document_id,
                file_path=doc.file_path,
                force=request.force_reparse
            )

            if result["success"]:
                if result.get("error") == "already_processed":
                    skipped += 1
                else:
                    processed += 1
            else:
                failed += 1
                failures.append({
                    "document_id": result["document_id"],
                    "file_path": doc.file_path,
                    "error": result["error"]
                })

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()

        return ParseResponse(
            success=True,
            message=f"Processed {processed} documents, {failed} failed, {skipped} skipped",
            total_documents=total,
            processed=processed,
            failed=failed,
            skipped=skipped,
            processing_time=processing_time,
            failures=failures[:10],  # 최대 10개만 반환
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse failed: {str(e)}")


@router.get("/status", response_model=Step4StatusResponse)
async def get_step4_status(db: Session = Depends(get_db)):
    """
    Step 4 처리 상태를 조회합니다.
    """
    try:
        # 전체 검수 완료 문서 수
        total = db.query(func.count(DocumentMetadata.id)).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag == True,
        ).scalar()

        # 처리 완료 문서 확인
        documents = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag == True,
        ).all()

        completed = 0
        failed = 0
        pending = 0
        by_source = {}
        by_file_type = {}

        for doc in documents:
            # 처리 상태 확인
            report = processed_text_store.get_report(str(doc.document_id))

            if report:
                status = report.get("status", "pending")
                if status == "done":
                    completed += 1
                elif status == "failed":
                    failed += 1
                else:
                    pending += 1
            else:
                pending += 1

            # Source별 집계
            source_id = doc.source_id or "unknown"
            if source_id not in by_source:
                by_source[source_id] = {"completed": 0, "failed": 0, "pending": 0}

            if report and report.get("status") == "done":
                by_source[source_id]["completed"] += 1
            elif report and report.get("status") == "failed":
                by_source[source_id]["failed"] += 1
            else:
                by_source[source_id]["pending"] += 1

            # 파일 타입별 집계
            if doc.file_path:
                file_ext = Path(doc.file_path).suffix.lower().lstrip('.')
                if file_ext not in by_file_type:
                    by_file_type[file_ext] = {"completed": 0, "failed": 0, "pending": 0}

                if report and report.get("status") == "done":
                    by_file_type[file_ext]["completed"] += 1
                elif report and report.get("status") == "failed":
                    by_file_type[file_ext]["failed"] += 1
                else:
                    by_file_type[file_ext]["pending"] += 1

        return Step4StatusResponse(
            total=total,
            pending=pending,
            processing=0,  # 현재는 동기 처리이므로 0
            completed=completed,
            failed=failed,
            by_source=by_source,
            by_file_type=by_file_type,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.get("/stats")
async def get_step4_stats():
    """
    Step 4 전체 통계를 조회합니다.
    """
    try:
        stats = processed_text_store.get_statistics()
        return {
            "success": True,
            **stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.get("/document/{document_id}/text")
async def get_document_text(
    document_id: int,
    format: str = "txt",  # txt or md
    db: Session = Depends(get_db)
):
    """
    특정 문서의 추출된 텍스트를 조회합니다.
    """
    try:
        # 문서 존재 확인
        doc = db.query(DocumentMetadata).filter(
            DocumentMetadata.document_id == document_id
        ).first()

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # 텍스트 조회
        text = processed_text_store.get_text(str(document_id), format=format)

        if not text:
            raise HTTPException(status_code=404, detail="Text not found. Run Step 4 first.")

        return {
            "success": True,
            "document_id": document_id,
            "format": format,
            "text": text,
            "text_length": len(text),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get text: {str(e)}")
