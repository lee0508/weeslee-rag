# Dataset Builder Step 4: OCR/Parser API
"""
Step 4는 검수 완료된 문서에 대해 OCR/파싱을 수행하여 텍스트를 추출합니다.

리팩토링 (2026-06-15):
- DocumentExtractor 통합 클래스 사용으로 if-elif 체인 제거
- 각 파일 형식별 처리 로직은 extractors/*.py에 캡슐화
"""
from datetime import datetime
from typing import Optional, List
from pathlib import Path
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.auth import require_admin_token
from app.core.database import get_db
from app.models.document_metadata import DocumentMetadata, MetaStatus
from app.services.processed_text_store import processed_text_store, ProcessingResult
from app.services.semantic_structure_service import build_pptx_structure, infer_semantic_tags
from app.extractors.extractor import DocumentExtractor
from app.services.metadata_extractor import rule_based_extractor
from app.services.dataset_context import get_source_dataset_context
from app.services.runtime_compute_settings import (
    describe_stage_compute_mode,
    get_runtime_compute_settings,
    is_stage_gpu_enabled,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/admin/dataset-builder/step4",
    tags=["Admin - Dataset Builder Step 4"],
    dependencies=[Depends(require_admin_token)],
)


# ── Request/Response Models ─────────────────────────────────────────────────


class ParseRequest(BaseModel):
    """파싱 실행 요청"""
    source_id: Optional[str] = None
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


def _calculate_quality_score(text_length: int) -> float:
    """텍스트 길이 기반 품질 점수 계산"""
    if text_length < 100:
        return 0.3
    elif text_length < 500:
        return 0.6
    return 1.0


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _build_step4_event(
    *,
    stage: str,
    log: str,
    progress: int,
    level: str = "info",
    doc: Optional[DocumentMetadata] = None,
    metadata_ctx: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> dict:
    event = {
        "timestamp": _iso_now(),
        "stage": stage,
        "level": level,
        "log": log,
        "progress": progress,
    }
    if doc is not None:
        event.update({
            "document_id": doc.document_id,
            "document_uid": doc.document_uid,
            "file_name": Path(doc.file_path or "").name if doc.file_path else None,
            "relative_path": doc.relative_path,
            "source_id": doc.source_id,
            "dataset_id": doc.dataset_id,
        })
    elif metadata_ctx:
        event.update({
            "document_uid": metadata_ctx.get("document_uid"),
            "relative_path": metadata_ctx.get("relative_path"),
            "source_id": metadata_ctx.get("source_id"),
            "dataset_id": metadata_ctx.get("dataset_id"),
        })
    if extra:
        event.update(extra)
    return event


def _extract_document_sync(file_path: str, ocr_use_gpu: bool) -> dict:
    """CPU 집약적인 추출을 워커 스레드에서 실행한다."""
    extractor = DocumentExtractor(
        use_ocr=True,
        ocr_use_gpu=ocr_use_gpu,
    )
    # 워커 스레드에서 새 이벤트 루프를 생성하여 async 함수 실행
    # asyncio.run()은 이미 루프가 실행 중일 때 RuntimeError 발생 가능
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(extractor.extract(file_path))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


async def _extract_document_in_worker(file_path: str, ocr_use_gpu: bool) -> dict:
    """이벤트 루프 블로킹을 피하기 위해 문서 추출을 thread worker로 오프로드한다."""
    return await asyncio.to_thread(_extract_document_sync, file_path, ocr_use_gpu)


async def parse_document(
    document_id: int,
    file_path: str,
    force: bool = False,
    metadata_ctx: Optional[dict] = None,
) -> dict:
    """
    단일 문서 파싱 처리 (Strategy Pattern 적용)

    DocumentExtractor를 통해 각 파일 형식별 extractor로 위임한다.

    Returns:
        {"success": bool, "document_id": int, "error": str or None, "text_length": int}
    """
    result = {
        "success": False,
        "document_id": document_id,
        "error": None,
        "text_length": 0,
        "warning": None,
        "parser_type": None,
        "processing_time_ms": 0,
        "ocr_use_gpu": False,
    }

    try:
        # 이미 처리된 문서는 건너뛰기 (force=False인 경우)
        if not force and processed_text_store.exists(str(document_id)):
            logger.info(
                "[Step4] skip existing OCR result: document_id=%s force=%s source_id=%s dataset_id=%s relative_path=%s",
                document_id,
                force,
                str((metadata_ctx or {}).get("source_id") or ""),
                str((metadata_ctx or {}).get("dataset_id") or ""),
                str((metadata_ctx or {}).get("relative_path") or ""),
            )
            result["success"] = True
            result["error"] = "already_processed"
            return result

        logger.info(
            "[Step4] parse_document start: document_id=%s force=%s source_id=%s dataset_id=%s relative_path=%s file=%s",
            document_id,
            force,
            str((metadata_ctx or {}).get("source_id") or ""),
            str((metadata_ctx or {}).get("dataset_id") or ""),
            str((metadata_ctx or {}).get("relative_path") or ""),
            file_path,
        )

        # 파일 존재 확인
        if not Path(file_path).exists():
            result["error"] = f"File not found: {file_path}"
            return result

        file_ext = Path(file_path).suffix.lower()
        file_name = Path(file_path).name

        # ProcessingResult 초기화
        metadata_ctx = metadata_ctx or {}
        try:
            from app.services.knowledge_graph import classify_project_type, get_organization_type
            inferred_org_type = get_organization_type(str(metadata_ctx.get("organization") or ""))
            inferred_project_types = classify_project_type(
                " ".join(
                    part for part in [
                        str(metadata_ctx.get("project_name") or ""),
                        str(file_name or ""),
                        str(file_path or ""),
                    ] if part
                )
            )
        except Exception:
            inferred_org_type = None
            inferred_project_types = []

        processing_result = ProcessingResult(
            document_id=str(document_id),
            file_name=file_name,
            source_path=file_path,
            file_extension=file_ext,
            source_id=str(metadata_ctx.get("source_id") or ""),
            dataset_id=str(metadata_ctx.get("dataset_id") or ""),
            document_uid=str(metadata_ctx.get("document_uid") or ""),
            relative_path=str(metadata_ctx.get("relative_path") or ""),
            project_name=str(metadata_ctx.get("project_name") or ""),
            organization=str(metadata_ctx.get("organization") or ""),
            organization_type=str(metadata_ctx.get("organization_type") or metadata_ctx.get("client_type") or inferred_org_type or ""),
            client_type=str(metadata_ctx.get("client_type") or metadata_ctx.get("organization_type") or inferred_org_type or ""),
            project_type=str(metadata_ctx.get("project_type") or (inferred_project_types[0] if inferred_project_types else "")),
            status="processing",
        )

        start_time = datetime.now()

        runtime_settings = get_runtime_compute_settings()
        ocr_use_gpu = is_stage_gpu_enabled("ocr", runtime_settings)
        result["ocr_use_gpu"] = ocr_use_gpu
        logger.info(
            "[Step4] parse_document worker dispatch: document_id=%s ocr_use_gpu=%s file=%s",
            document_id,
            ocr_use_gpu,
            file_path,
        )

        # CPU 집약적인 OCR/파싱은 워커 스레드에서 실행해 SSE/health check를 막지 않는다.
        extract_result = await _extract_document_in_worker(file_path, ocr_use_gpu)

        # 추출 결과 매핑
        text = extract_result.get("content", "")
        processing_result.parser_type = extract_result.get("method", "unknown")
        result["parser_type"] = processing_result.parser_type
        processing_result.full_text = text
        processing_result.full_text_md = f"# {file_name}\n\n{text}"

        # 메타데이터 처리
        metadata = extract_result.get("metadata", {})
        if metadata:
            processing_result.quality = metadata.get("quality", {})
            processing_result.ocr_required = metadata.get("is_scanned", False) or metadata.get("ocr_required", False)
            if metadata.get("pages"):
                processing_result.pages = [{"page_num": i, "text": "", "char_count": 0} for i in range(1, metadata["pages"] + 1)]

        if file_ext == ".pptx":
            try:
                structured_data = build_pptx_structure(file_path, processing_result.relative_path or file_name)
                semantic_tags = infer_semantic_tags(structured_data)
                structured_data["semantic_tags"] = semantic_tags
                processing_result.structured_data = structured_data
                processing_result.quality = {
                    **(processing_result.quality or {}),
                    "semantic_structure": True,
                    "semantic_sections": sum(len(sec.get("subsections", [])) for sec in structured_data.get("sections", [])),
                }
                if semantic_tags.get("technology") and not processing_result.project_type:
                    processing_result.project_type = semantic_tags.get("technology", "")
            except Exception as structure_exc:
                logger.warning(
                    "[Step4] semantic structure build failed: document_id=%s file=%s error=%s",
                    document_id,
                    file_path,
                    structure_exc,
                )

        if not extract_result.get("success"):
            processing_result.error_message = extract_result.get("error") or "Extraction failed"

        # 처리 시간 및 품질 점수 계산
        end_time = datetime.now()
        processing_time_ms = int((end_time - start_time).total_seconds() * 1000)

        processing_result.processing_time_ms = processing_time_ms
        processing_result.text_length = len(processing_result.full_text or "")
        result["processing_time_ms"] = processing_time_ms

        quality_score = _calculate_quality_score(processing_result.text_length)

        processing_result.quality = {
            **(processing_result.quality or {}),
            "quality_score": quality_score,
            "text_length": processing_result.text_length,
            "recommendation": "excellent" if quality_score > 0.8 else ("acceptable" if quality_score > 0.5 else "review_required"),
            "rag_ready": quality_score >= 0.7 and processing_result.text_length >= 500,
        }

        if not processing_result.full_text.strip():
            processing_result.status = "failed"
            processing_result.error_message = processing_result.error_message or "Extracted text is empty"
            processed_text_store.save_result(processing_result)
            result["error"] = processing_result.error_message
            return result

        if quality_score < 0.7 or processing_result.text_length < 500:
            result["warning"] = (
                processing_result.error_message
                or f"Text quality low: score={quality_score}, text_length={processing_result.text_length}"
            )

        processing_result.status = "done"

        # 저장
        if processed_text_store.save_result(processing_result):
            result["success"] = True
            result["text_length"] = processing_result.text_length
            if result["warning"]:
                result["error"] = result["warning"]
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
            source_id=str((metadata_ctx or {}).get("source_id") or ""),
            dataset_id=str((metadata_ctx or {}).get("dataset_id") or ""),
            document_uid=str((metadata_ctx or {}).get("document_uid") or ""),
            relative_path=str((metadata_ctx or {}).get("relative_path") or ""),
            project_name=str((metadata_ctx or {}).get("project_name") or ""),
            organization=str((metadata_ctx or {}).get("organization") or ""),
            organization_type=str((metadata_ctx or {}).get("organization_type") or (metadata_ctx or {}).get("client_type") or ""),
            client_type=str((metadata_ctx or {}).get("client_type") or (metadata_ctx or {}).get("organization_type") or ""),
            project_type=str((metadata_ctx or {}).get("project_type") or ""),
            status="failed",
            error_message=str(e),
        )
        processed_text_store.save_result(processing_result)

    return result


def _save_ocr_metadata(db: Session, doc: DocumentMetadata, document_id: int) -> None:
    """파싱 완료 문서의 전문 텍스트로 ocr_* 필드를 추출하여 DB에 저장한다."""
    try:
        report = processed_text_store.get_report(str(document_id))
        if not report:
            doc.ocr_metadata_status = "skipped"
            db.flush()
            return

        full_text = processed_text_store.get_text(str(document_id)) or ""
        if not full_text.strip():
            doc.ocr_metadata_status = "skipped"
            db.flush()
            return

        ocr_meta = rule_based_extractor.extract_all(full_text)

        raw_year = ocr_meta.get("ocr_year")
        doc.ocr_project_name = ocr_meta.get("ocr_project_name")
        doc.ocr_organization = ocr_meta.get("ocr_organization")
        doc.ocr_year = str(raw_year) if raw_year is not None else None
        doc.ocr_document_category = ocr_meta.get("ocr_document_category")
        doc.ocr_confidence = ocr_meta.get("ocr_confidence")
        doc.ocr_quality_score = (report.get("quality") or {}).get("quality_score")
        doc.ocr_parser_type = report.get("parser_type") or None
        doc.ocr_page_count = report.get("page_count") or None
        doc.ocr_metadata_status = "success"
        doc.updated_at = datetime.utcnow()

        db.flush()
    except Exception:
        doc.ocr_metadata_status = "failed"
        # ocr_* 저장 실패는 파싱 성공 여부에 영향 없음


def _get_step4_target_documents(
    db: Session,
    document_ids: Optional[List[int]],
    source_id: Optional[str] = None,
) -> List[DocumentMetadata]:
    """Step 4 대상 문서를 조회한다."""
    query = db.query(DocumentMetadata).filter(
        DocumentMetadata.include_in_rag.is_(True),
        DocumentMetadata.is_excluded.is_(False),
        DocumentMetadata.removed_at.is_(None),
    )

    if source_id:
        query = query.filter(DocumentMetadata.source_id == source_id)

    if document_ids:
        query = query.filter(DocumentMetadata.document_id.in_(document_ids))

    return query.all()


def _fill_dataset_id_if_needed(doc: DocumentMetadata, dataset_id_cache: dict) -> None:
    """source 설정 기준 dataset_id를 보완한다."""
    if doc.dataset_id or not doc.source_id:
        return

    if doc.source_id not in dataset_id_cache:
        ctx = get_source_dataset_context(doc.source_id)
        dataset_id_cache[doc.source_id] = ctx.get("dataset_id")

    doc.dataset_id = dataset_id_cache[doc.source_id]


def _build_processing_metadata_ctx(doc: DocumentMetadata, dataset_id_cache: dict) -> dict:
    """Step 4 산출물에 저장할 문서 컨텍스트를 정규화한다."""
    _fill_dataset_id_if_needed(doc, dataset_id_cache)

    project_name = (
        doc.final_project_name
        or doc.ocr_project_name
        or doc.project_name
        or doc.scan_project_name
        or ""
    )
    organization = (
        doc.final_organization
        or doc.ocr_organization
        or doc.organization
        or doc.scan_organization
        or ""
    )

    return {
        "source_id": doc.source_id,
        "dataset_id": doc.dataset_id,
        "document_uid": doc.document_uid,
        "relative_path": doc.relative_path,
        "project_name": project_name,
        "organization": organization,
        "organization_type": None,
        "client_type": None,
        "project_type": None,
    }


def _commit_step4_progress(db: Session) -> None:
    """Step 4 진행 상태를 중간 커밋해 MySQL 가시성과 장애 복구성을 높인다."""
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.post("/parse", response_model=ParseResponse)
async def parse_documents(
    request: ParseRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Document Source 문서들에 대해 OCR/파싱을 실행합니다.

    - source_id가 있으면 해당 Source의 모든 활성 문서를 처리
    - document_ids가 있으면 지정 문서만 처리
    - force_reparse=True이면 이미 처리된 문서도 재처리
    """
    start_time = datetime.now()

    try:
        documents = _get_step4_target_documents(
            db,
            request.document_ids,
            request.source_id,
        )
        logger.info(
            "[Step4] parse request: source_id=%s force_reparse=%s document_ids=%s target_count=%s",
            request.source_id,
            request.force_reparse,
            request.document_ids,
            len(documents),
        )

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

        # source_id → dataset_id 캐시 (같은 source의 문서들은 한 번만 조회)
        _dataset_id_cache: dict = {}

        for doc in documents:
            if not doc.file_path:
                failures.append({
                    "document_id": doc.document_id,
                    "file_path": None,
                    "error": "No file path"
                })
                failed += 1
                continue

            metadata_ctx = _build_processing_metadata_ctx(doc, _dataset_id_cache)
            result = await parse_document(
                document_id=doc.document_id,
                file_path=doc.file_path,
                force=request.force_reparse,
                metadata_ctx=metadata_ctx,
            )

            if result["success"]:
                if result.get("error") == "already_processed":
                    skipped += 1
                else:
                    processed += 1
                    # OCR 추출 텍스트로 ocr_* 메타데이터 추출 및 DB 저장
                    _save_ocr_metadata(db, doc, result["document_id"])
                    doc.status = "text_extracted"
                    doc.updated_at = datetime.utcnow()
                    _commit_step4_progress(db)
            else:
                failed += 1
                failures.append({
                    "document_id": result["document_id"],
                    "file_path": doc.file_path,
                    "error": result["error"]
                })

        # ocr_* flush 후 일괄 커밋
        _commit_step4_progress(db)

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
        logger.exception(
            "[Step4] parse request failed: source_id=%s force_reparse=%s document_ids=%s",
            request.source_id,
            request.force_reparse,
            request.document_ids,
        )
        raise HTTPException(status_code=500, detail=f"Parse failed: {str(e)}")


@router.post("/refresh-metadata", response_model=ParseResponse)
async def refresh_ocr_metadata(
    request: ParseRequest,
    db: Session = Depends(get_db)
):
    """
    Step 4에서 이미 추출된 텍스트를 재사용해 ocr_* 메타데이터만 다시 계산한다.

    - processed_text_store에 저장된 full_text를 사용한다.
    - OCR/Parser는 다시 실행하지 않는다.
    """
    start_time = datetime.now()

    try:
        documents = _get_step4_target_documents(
            db,
            request.document_ids,
            request.source_id,
        )

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

        processed = 0
        failed = 0
        skipped = 0
        failures = []
        dataset_id_cache: dict = {}

        for doc in documents:
            report = processed_text_store.get_report(str(doc.document_id))
            full_text = processed_text_store.get_text(str(doc.document_id)) or ""

            if not report or not full_text.strip():
                doc.ocr_metadata_status = "skipped"
                skipped += 1
                failures.append({
                    "document_id": doc.document_id,
                    "file_path": doc.file_path,
                    "error": "Processed text not found",
                })
                continue

            _fill_dataset_id_if_needed(doc, dataset_id_cache)
            _save_ocr_metadata(db, doc, doc.document_id)

            if doc.ocr_metadata_status == "success":
                processed += 1
                doc.status = "text_extracted"
                _commit_step4_progress(db)
            elif doc.ocr_metadata_status == "skipped":
                skipped += 1
            else:
                failed += 1
                failures.append({
                    "document_id": doc.document_id,
                    "file_path": doc.file_path,
                    "error": "OCR metadata refresh failed",
                })

        _commit_step4_progress(db)

        processing_time = (datetime.now() - start_time).total_seconds()

        return ParseResponse(
            success=True,
            message=f"Refreshed OCR metadata for {processed} documents, {failed} failed, {skipped} skipped",
            total_documents=len(documents),
            processed=processed,
            failed=failed,
            skipped=skipped,
            processing_time=processing_time,
            failures=failures[:10],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR metadata refresh failed: {str(e)}")


@router.get("/status", response_model=Step4StatusResponse)
async def get_step4_status(db: Session = Depends(get_db)):
    """
    Step 4 처리 상태를 조회합니다.
    """
    try:
        # 전체 검수 완료 문서 수 (제외/삭제되지 않은 문서만)
        total = db.query(func.count(DocumentMetadata.id)).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
        ).scalar()

        # 처리 완료 문서 확인
        documents = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
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


@router.get("/parse/results")
async def get_parse_results(
    min_quality_score: Optional[float] = None,
    min_text_length: Optional[int] = None,
    status_filter: Optional[str] = None,  # "success", "failed", "skipped"
    rag_ready_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    Step 4 OCR/Parser 결과 목록을 조회합니다.

    필터 옵션:
    - min_quality_score: 최소 품질 점수
    - min_text_length: 최소 텍스트 길이
    - status_filter: 상태 필터 (success/failed/skipped)
    - rag_ready_only: True이면 RAG 준비 완료된 문서만
    """
    try:
        # ProcessedTextStore에서 모든 결과 조회 (limit을 크게 설정)
        all_results = processed_text_store.list_documents(status=None, limit=10000)

        # 필터링
        filtered_results = []
        for result in all_results:
            # status 필터 (API에서는 "success"를 사용하지만 store에서는 "done"을 사용)
            result_status = result.get("status", "")
            if status_filter:
                # "success" -> "done" 매핑
                if status_filter == "success" and result_status != "done":
                    continue
                elif status_filter != "success" and result_status != status_filter:
                    continue

            # quality 필터
            quality = result.get("quality", {})
            quality_score = quality.get("quality_score", 0)
            text_length = result.get("text_length", 0)
            inferred_rag_ready = bool(
                quality.get("rag_ready")
                or (
                    result.get("status") == "done"
                    and quality_score >= 0.7
                    and text_length >= 500
                )
            )
            quality["rag_ready"] = inferred_rag_ready
            result["quality"] = quality

            if min_quality_score and quality_score < min_quality_score:
                continue

            # text_length 필터
            if min_text_length and text_length < min_text_length:
                continue

            # rag_ready 필터
            if rag_ready_only and not inferred_rag_ready:
                continue

            filtered_results.append(result)

        # 통계 계산 (store의 "done" status를 "success"로 표시)
        total = len(filtered_results)
        success_count = sum(1 for r in filtered_results if r.get("status") == "done")
        failed_count = sum(1 for r in filtered_results if r.get("status") == "failed")
        skipped_count = sum(1 for r in filtered_results if r.get("status") == "skipped")
        rag_ready_count = sum(1 for r in filtered_results if r.get("quality", {}).get("rag_ready", False))

        # 결과에서 status를 "done" -> "success"로 변환
        for r in filtered_results:
            if r.get("status") == "done":
                r["status"] = "success"

        return {
            "success": True,
            "total": total,
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "rag_ready_count": rag_ready_count,
            "results": filtered_results,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get parse results: {str(e)}")


# ── SSE Streaming ───────────────────────────────────────────────────────────

# Step 4 파싱 작업을 위한 job 저장소 (간단한 in-memory 구현)
_parse_jobs: dict[str, dict] = {}


def create_parse_job(job_id: str) -> dict:
    """새 파싱 작업 생성."""
    job = {
        "job_id": job_id,
        "queue": asyncio.Queue(),
        "status": "running",
        "created_at": datetime.now().isoformat(),
        "last_event": None,
        "result": None,
        "error": None,
    }
    _parse_jobs[job_id] = job
    return job


def get_parse_job(job_id: str) -> Optional[dict]:
    """파싱 작업 조회."""
    return _parse_jobs.get(job_id)


async def emit_parse_event(job_id: str, event: dict):
    """파싱 이벤트 전송."""
    job = get_parse_job(job_id)
    if not job:
        return

    job["last_event"] = event
    if event.get("done"):
        if event.get("error"):
            job["status"] = "failed"
            job["error"] = event.get("error")
        else:
            job["status"] = "completed"
            job["result"] = event.get("result")

    if job["queue"]:
        await job["queue"].put(event)


async def parse_documents_streaming(
    job_id: str,
    document_ids: Optional[List[int]],
    source_id: Optional[str],
    force_reparse: bool,
    db: Session
):
    """백그라운드에서 문서를 파싱하고 SSE로 진행 상황 전송."""
    try:
        # 기본 일괄 실행은 검수 완료 문서만 대상으로 유지한다.
        # 단, 명시적인 document_ids 재처리는 개별 진단/복구 목적이므로 meta_status 제한을 두지 않는다.
        documents = _get_step4_target_documents(db, document_ids, source_id)
        total = len(documents)
        logger.info(
            "[Step4] stream start: job_id=%s source_id=%s force_reparse=%s document_ids=%s target_count=%s",
            job_id,
            source_id,
            force_reparse,
            document_ids,
            total,
        )

        await emit_parse_event(job_id, {
            "stage": "초기화",
            "log": f"총 {total}개 문서 파싱 시작",
            "progress": 0,
            "timestamp": _iso_now(),
            "source_id": source_id,
        })
        await emit_parse_event(job_id, {
            "stage": "초기화",
            "log": f"OCR 실행 모드: {describe_stage_compute_mode('ocr')}",
            "progress": 0,
            "timestamp": _iso_now(),
            "source_id": source_id,
        })

        if total == 0:
            await emit_parse_event(job_id, {
                "stage": "완료",
                "log": "처리할 문서가 없습니다",
                "progress": 100,
                "done": True,
                "result": {
                    "total_documents": 0,
                    "processed": 0,
                    "failed": 0,
                    "skipped": 0,
                }
            })
            return

        # 문서 처리
        processed = 0
        failed = 0
        skipped = 0
        dataset_id_cache: dict = {}

        for idx, doc in enumerate(documents, 1):
            if not doc.file_path:
                await emit_parse_event(job_id, _build_step4_event(
                    stage=f"파싱 중 ({idx}/{total})",
                    level="error",
                    log=f"[{idx}/{total}] document_id={doc.document_id}: 파일 경로 없음",
                    progress=int((idx / total) * 100),
                    doc=doc,
                    extra={"sequence": idx, "total_documents": total},
                ))
                failed += 1
                continue

            metadata_ctx = _build_processing_metadata_ctx(doc, dataset_id_cache)
            await emit_parse_event(job_id, _build_step4_event(
                stage=f"파싱 중 ({idx}/{total})",
                log=f"[{idx}/{total}] {Path(doc.file_path).name} 파싱 시작",
                progress=int(((idx - 1) / total) * 100),
                doc=doc,
                metadata_ctx=metadata_ctx,
                extra={
                    "sequence": idx,
                    "total_documents": total,
                    "phase": "start",
                },
            ))
            result = await parse_document(
                document_id=doc.document_id,
                file_path=doc.file_path,
                force=force_reparse,
                metadata_ctx=metadata_ctx,
            )

            if result["success"]:
                if result.get("error") == "already_processed":
                    logger.warning(
                        "[Step4] stream skip detected: job_id=%s document_id=%s source_id=%s force_reparse=%s relative_path=%s",
                        job_id,
                        doc.document_id,
                        doc.source_id,
                        force_reparse,
                        doc.relative_path,
                    )
                    await emit_parse_event(job_id, _build_step4_event(
                        stage=f"파싱 중 ({idx}/{total})",
                        level="warning",
                        log=f"[{idx}/{total}] {Path(doc.file_path).name}: 이미 처리됨 (skip)",
                        progress=int((idx / total) * 100),
                        doc=doc,
                        metadata_ctx=metadata_ctx,
                        extra={
                            "sequence": idx,
                            "total_documents": total,
                            "phase": "skip",
                            "skip_reason": "already_processed",
                        },
                    ))
                    skipped += 1
                else:
                    text_len = result.get("text_length", 0)
                    _save_ocr_metadata(db, doc, result["document_id"])
                    doc.status = "text_extracted"
                    doc.updated_at = datetime.utcnow()
                    _commit_step4_progress(db)
                    await emit_parse_event(job_id, _build_step4_event(
                        stage=f"파싱 중 ({idx}/{total})",
                        level="success" if not result.get("warning") else "warning",
                        log=(
                            f"[{idx}/{total}] {Path(doc.file_path).name}: 성공 ({text_len} chars)"
                            + (f" | 경고: {result['warning']}" if result.get("warning") else "")
                        ),
                        progress=int((idx / total) * 100),
                        doc=doc,
                        metadata_ctx=metadata_ctx,
                        extra={
                            "sequence": idx,
                            "total_documents": total,
                            "phase": "success",
                            "parser_type": result.get("parser_type"),
                            "text_length": text_len,
                            "processing_time_ms": result.get("processing_time_ms"),
                            "ocr_use_gpu": result.get("ocr_use_gpu"),
                            "warning": result.get("warning"),
                        },
                    ))
                    processed += 1
            else:
                error_msg = result.get("error", "Unknown error")
                await emit_parse_event(job_id, _build_step4_event(
                    stage=f"파싱 중 ({idx}/{total})",
                    level="error",
                    log=f"[{idx}/{total}] {Path(doc.file_path).name}: 실패 - {error_msg}",
                    progress=int((idx / total) * 100),
                    doc=doc,
                    metadata_ctx=metadata_ctx,
                    extra={
                        "sequence": idx,
                        "total_documents": total,
                        "phase": "failed",
                        "parser_type": result.get("parser_type"),
                        "processing_time_ms": result.get("processing_time_ms"),
                        "ocr_use_gpu": result.get("ocr_use_gpu"),
                        "error_detail": error_msg,
                    },
                ))
                failed += 1

            # 다음 SSE heartbeat와 다른 요청 처리를 위해 매 문서 뒤 제어권을 반환한다.
            await asyncio.sleep(0)

        _commit_step4_progress(db)

        logger.info(
            "[Step4] stream complete: job_id=%s source_id=%s force_reparse=%s total=%s processed=%s failed=%s skipped=%s",
            job_id,
            source_id,
            force_reparse,
            total,
            processed,
            failed,
            skipped,
        )

        # 완료
        await emit_parse_event(job_id, {
            "stage": "완료",
            "log": f"파싱 완료: {processed}개 성공, {failed}개 실패, {skipped}개 건너뜀",
            "progress": 100,
            "done": True,
            "timestamp": _iso_now(),
            "source_id": source_id,
            "result": {
                "total_documents": total,
                "processed": processed,
                "failed": failed,
                "skipped": skipped,
            }
        })

    except Exception as e:
        logger.exception(
            "[Step4] stream failed: job_id=%s source_id=%s force_reparse=%s document_ids=%s",
            job_id,
            source_id,
            force_reparse,
            document_ids,
        )
        await emit_parse_event(job_id, {
            "stage": "오류",
            "level": "error",
            "log": f"파싱 작업 실패: {str(e)}",
            "progress": 0,
            "done": True,
            "timestamp": _iso_now(),
            "source_id": source_id,
            "error": str(e),
        })


# SSE 라우터 (인증 없이 token query param으로 인증)
sse_router = APIRouter(
    prefix="/admin/dataset-builder/step4",
    tags=["Admin - Dataset Builder Step 4 SSE"],
)


@router.post("/parse/stream")
async def start_parse_stream(
    request: ParseRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    SSE 스트리밍 방식으로 파싱 작업을 시작합니다.

    Returns:
        job_id를 반환하고, 클라이언트는 /parse/stream/{job_id}로 SSE 연결
    """
    import uuid
    job_id = str(uuid.uuid4())

    # Job 생성
    create_parse_job(job_id)

    # 백그라운드에서 파싱 실행
    background_tasks.add_task(
        parse_documents_streaming,
        job_id=job_id,
        document_ids=request.document_ids,
        source_id=request.source_id,
        force_reparse=request.force_reparse,
        db=db
    )

    return {
        "success": True,
        "job_id": job_id,
        "message": "Parsing job started. Connect to /parse/stream/{job_id} for progress updates."
    }


@router.get("/parse/jobs/{job_id}")
async def get_parse_job_status(job_id: str):
    """Step 4 파싱 작업 상태 조회. SSE 연결 실패 시 폴링 폴백 용도."""
    job = get_parse_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return {
        "success": True,
        "job_id": job["job_id"],
        "status": job.get("status", "unknown"),
        "created_at": job.get("created_at"),
        "last_event": job.get("last_event"),
        "result": job.get("result"),
        "error": job.get("error"),
    }


@sse_router.get("/parse/stream/{job_id}")
async def stream_parse_progress(job_id: str, token: Optional[str] = None):
    """
    SSE 스트림으로 파싱 진행 상황을 수신합니다.

    브라우저 EventSource는 커스텀 헤더를 지원하지 않으므로 ?token= query param으로 인증합니다.
    """
    from app.core.auth import decode_token
    from app.core.config import settings

    if settings.debug and settings.app_env == "development":
        username = "dev-user"
    else:
        username = decode_token(token) if token else None

    if not username:
        raise HTTPException(status_code=401, detail="유효하지 않거나 만료된 토큰입니다.")

    job = get_parse_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    queue: asyncio.Queue = job["queue"]

    async def generate():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                yield "data: {\"heartbeat\": true}\n\n"
                continue

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if event.get("done"):
                break

    return StreamingResponse(generate(), media_type="text/event-stream")
