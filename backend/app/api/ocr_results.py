# OCR 결과 조회 및 품질 점검 API
"""
OCR/파싱 결과 조회 및 품질 점검 API.

4단계 구현: processed_text_store 및 text_quality_checker와 연동.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.services.text_quality_checker import text_quality_checker
from app.services.processed_text_store import processed_text_store


router = APIRouter(
    prefix="/admin/ocr-results",
    tags=["OCR Results"],
    dependencies=[Depends(require_admin_token)],
)


# ─────────────────────────────────────────────────────────────────────────────
# Response Models
# ─────────────────────────────────────────────────────────────────────────────

class QualityCheckRequest(BaseModel):
    text: str
    page_texts: Optional[List[str]] = None


class QualityCheckResponse(BaseModel):
    quality_score: float
    decision: str
    text_length: int
    korean_ratio: float
    garbage_char_ratio: float
    empty_page_ratio: float
    issues: List[str]


class OCRResultSummary(BaseModel):
    document_id: str
    file_name: str
    extraction_method: str
    quality_score: float
    text_length: int
    page_count: int
    ocr_required: bool
    processed_at: str


class OCRResultDetail(BaseModel):
    document_id: str
    file_name: str
    extraction_method: str
    quality: dict
    full_text: Optional[str] = None
    pages: Optional[List[dict]] = None
    tables: Optional[List[dict]] = None
    ocr_report: Optional[dict] = None
    metadata: dict


class StoreStatistics(BaseModel):
    total_documents: int
    total_size_bytes: int
    by_method: dict
    by_quality: dict


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_document_id(report_or_id: Any) -> str:
    if isinstance(report_or_id, str):
        return report_or_id
    if isinstance(report_or_id, dict):
        return str(report_or_id.get("document_id") or report_or_id.get("id") or "")
    return str(report_or_id or "")


def _extraction_method_from_result(result) -> str:
    return (
        getattr(result, "extraction_method", "")
        or getattr(result, "parser_type", "")
        or getattr(result, "ocr_engine", "")
        or "unknown"
    )


def _processed_at_from_result(result) -> str:
    return (
        getattr(result, "processed_at", "")
        or getattr(result, "updated_at", "")
        or getattr(result, "created_at", "")
        or ""
    )


def _quality_bucket(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "good"
    if score >= 0.4:
        return "low"
    return "bad"


@router.post("/quality-check", response_model=QualityCheckResponse)
async def check_text_quality(body: QualityCheckRequest):
    """
    텍스트 품질 점검.

    품질 점수 (0~1), 결정(use_direct_text/need_pdf_convert/need_ocr/need_manual_review),
    상세 지표(korean_ratio, garbage_char_ratio 등)를 반환합니다.
    """
    if not body.text:
        raise HTTPException(status_code=400, detail="text 필드가 필요합니다.")

    result = text_quality_checker.check(body.text, body.page_texts)

    return QualityCheckResponse(
        quality_score=result.quality_score,
        decision=result.decision,
        text_length=result.text_length,
        korean_ratio=result.korean_ratio,
        garbage_char_ratio=result.garbage_char_ratio,
        empty_page_ratio=result.empty_page_ratio,
        issues=result.issues,
    )


@router.get("/list")
async def list_ocr_results(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    method: Optional[str] = Query(None, description="추출 방법 필터 (ocr, direct, merged 등)"),
    min_quality: Optional[float] = Query(None, ge=0, le=1, description="최소 품질 점수"),
):
    """
    저장된 OCR/파싱 결과 목록 조회.

    processed_text_store에 저장된 결과를 페이지네이션하여 반환합니다.
    """
    all_docs = processed_text_store.list_documents(limit=100000)

    # 필터링
    filtered = []
    for item in all_docs:
        doc_id = _extract_document_id(item)
        if not doc_id:
            continue

        result = processed_text_store.get_result(doc_id)
        if not result:
            continue

        extraction_method = _extraction_method_from_result(result)

        # method 필터
        if method and extraction_method != method:
            continue

        # quality 필터
        if min_quality is not None:
            quality = result.quality or {}
            if quality.get("quality_score", 0) < min_quality:
                continue

        quality = result.quality or {}
        filtered.append({
            "document_id": result.document_id,
            "file_name": result.file_name,
            "extraction_method": extraction_method,
            "quality_score": quality.get("quality_score", 0),
            "text_length": result.text_length or (len(result.full_text) if result.full_text else 0),
            "page_count": result.page_count or (len(result.pages) if result.pages else 0),
            "ocr_required": result.ocr_required,
            "processed_at": _processed_at_from_result(result),
            "status": result.status,
        })

    # 정렬 (최신순)
    filtered.sort(key=lambda x: x.get("processed_at", ""), reverse=True)

    # 페이지네이션
    total = len(filtered)
    paginated = filtered[offset:offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": paginated,
    }


@router.get("/detail/{document_id}")
async def get_ocr_result_detail(
    document_id: str,
    include_text: bool = Query(True, description="전체 텍스트 포함 여부"),
    include_pages: bool = Query(False, description="페이지별 텍스트 포함 여부"),
    include_tables: bool = Query(False, description="표 데이터 포함 여부"),
):
    """
    특정 문서의 OCR/파싱 결과 상세 조회.
    """
    result = processed_text_store.get_result(document_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"문서를 찾을 수 없습니다: {document_id}")

    response = {
        "document_id": result.document_id,
        "file_name": result.file_name,
        "source_path": result.source_path,
        "extraction_method": _extraction_method_from_result(result),
        "quality": result.quality or {},
        "ocr_required": result.ocr_required,
        "ocr_pages": result.failed_pages,
        "failed_pages": result.failed_pages,
        "processed_at": _processed_at_from_result(result),
        "status": result.status,
        "error_message": result.error_message,
        "metadata": {
            "source_path": result.source_path,
            "file_extension": result.file_extension,
            "parser_type": result.parser_type,
            "ocr_engine": result.ocr_engine,
            "pdf_converted": result.pdf_converted,
            "page_count": result.page_count or (len(result.pages) if result.pages else 0),
            "table_count": len(result.tables) if result.tables else 0,
            "processing_time_ms": result.processing_time_ms,
        },
    }

    if include_text:
        response["full_text"] = result.full_text
        response["text_length"] = len(result.full_text) if result.full_text else 0

    if include_pages and result.pages:
        response["pages"] = result.pages

    if include_tables and result.tables:
        response["tables"] = result.tables

    report = processed_text_store.get_report(document_id)
    if report:
        response["ocr_report"] = report

    return response


@router.get("/statistics")
async def get_store_statistics():
    """
    OCR/파싱 결과 저장소 통계.
    """
    stats = processed_text_store.get_statistics()

    total_size_bytes = 0
    base_dir = processed_text_store.base_dir
    if base_dir.exists():
        total_size_bytes = sum(
            path.stat().st_size
            for path in base_dir.rglob("*")
            if path.is_file()
        )

    by_method: dict[str, int] = {}
    by_quality: dict[str, int] = {"high": 0, "good": 0, "low": 0, "bad": 0}
    for report in processed_text_store.list_documents(limit=100000):
        doc_id = _extract_document_id(report)
        if not doc_id:
            continue
        method_name = (
            report.get("extraction_method")
            or report.get("parser_type")
            or report.get("ocr_engine")
            or "unknown"
        )
        by_method[method_name] = by_method.get(method_name, 0) + 1

        quality = report.get("quality") or {}
        score = quality.get("quality_score", 0)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0
        bucket = _quality_bucket(score)
        by_quality[bucket] = by_quality.get(bucket, 0) + 1

    return {
        "checked_at": _now(),
        "total_documents": stats.get("total", 0),
        "total_size_bytes": total_size_bytes,
        "by_method": by_method,
        "by_quality": by_quality,
        **stats,
    }


@router.delete("/clear/{document_id}")
async def delete_ocr_result(document_id: str):
    """
    특정 문서의 OCR/파싱 결과 삭제.
    """
    result = processed_text_store.get_result(document_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"문서를 찾을 수 없습니다: {document_id}")

    # 저장 디렉토리 삭제
    import shutil
    doc_dir = processed_text_store.base_dir / document_id
    if doc_dir.exists():
        shutil.rmtree(doc_dir)

    return {
        "success": True,
        "message": f"문서 {document_id}의 OCR 결과가 삭제되었습니다.",
        "document_id": document_id,
    }


@router.post("/reprocess/{document_id}")
async def reprocess_document(document_id: str):
    """
    특정 문서 재처리 요청.

    TODO: 실제 재처리 로직 연동 필요
    """
    return {
        "success": True,
        "message": f"문서 {document_id} 재처리가 요청되었습니다.",
        "document_id": document_id,
        "status": "queued",
    }


@router.get("/methods")
async def list_extraction_methods():
    """
    사용 가능한 추출 방법 목록.
    """
    return {
        "methods": [
            {"id": "pdfplumber", "name": "PDF 직접 추출", "description": "pdfplumber로 PDF 텍스트 추출"},
            {"id": "olmocr", "name": "olmOCR", "description": "GPU 기반 OCR (CUDA 필요)"},
            {"id": "tesseract", "name": "Tesseract OCR", "description": "로컬 OCR 엔진"},
            {"id": "easyocr", "name": "EasyOCR", "description": "딥러닝 기반 OCR"},
            {"id": "hwp5txt", "name": "HWP 직접 추출", "description": "pyhwp로 HWP 텍스트 추출"},
            {"id": "hwp_pdf_conversion", "name": "HWP PDF 변환", "description": "LibreOffice로 PDF 변환 후 추출"},
            {"id": "hwp_ocr", "name": "HWP OCR", "description": "HWP를 PDF로 변환 후 OCR"},
            {"id": "python-pptx", "name": "PPTX 직접 추출", "description": "python-pptx로 텍스트 추출"},
            {"id": "pptx_merged", "name": "PPTX 병합 추출", "description": "직접 추출 + OCR 병합"},
            {"id": "pptx_ocr", "name": "PPTX OCR", "description": "PPTX를 PDF로 변환 후 OCR"},
            {"id": "python-docx", "name": "DOCX 직접 추출", "description": "python-docx로 텍스트 추출"},
            {"id": "openpyxl", "name": "XLSX 직접 추출", "description": "openpyxl로 테이블 추출"},
        ],
    }
