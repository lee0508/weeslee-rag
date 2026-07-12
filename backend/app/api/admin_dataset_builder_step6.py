# Dataset Builder Step 6: Embedding Build API
"""
Step 5에서 생성된 청크에 대해 임베딩 벡터를 생성
"""
import asyncio
import json
import logging
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.config import settings
from app.services.dataset_context import update_source_dataset_status
from app.services.ollama import OllamaService, get_ollama
from app.services.processed_text_store import ProcessedTextStore
from app.services.faiss_job_runner import read_active_index
from app.services.runtime_model_settings import get_runtime_embedding_model
from app.services.source_artifact_index import sync_source_index
from app.services.chunking import TextChunk
from app.services.contextual_chunking import ContextualEnricher, MeaningfulnessGate, OllamaContextLLM
from app.services.late_chunking import (
    LateChunkingEmbedder,
    resolve_late_chunk_model_name,
    supports_late_chunking,
)

router = APIRouter(prefix="/admin/dataset-builder/step6")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
FAISS_DIR = DATA_DIR / "indexes" / "faiss"
logger = logging.getLogger(__name__)
_EMBEDDING_BUILD_JOBS: dict[str, dict[str, Any]] = {}
_STEP6_JOB_DIR = Path(__file__).resolve().parents[3] / "data" / "jobs" / "step6_embed"


def generate_embedding_id(chunk_id: str) -> str:
    """chunk_id를 기반으로 embedding_id 생성.

    형식: {chunk_id}_emb
    예: src_20260711_090331_dda661_96509_0001_emb
    """
    return f"{chunk_id}_emb"


# ── Request/Response Models ──────────────────────────────────────────────

class EmbeddingBuildRequest(BaseModel):
    """임베딩 생성 요청"""
    source_id: Optional[str] = Field(None, description="Document Source ID (특정 소스만 처리)")
    snapshot_id: Optional[str] = Field(None, description="연결할 Snapshot ID")
    document_ids: Optional[List[int]] = Field(None, description="처리할 문서 ID 목록 (비어있으면 전체)")
    model: Optional[str] = Field(None, description="임베딩 모델명")
    batch_size: int = Field(32, ge=1, le=100, description="배치 크기")
    retry_count: int = Field(3, ge=0, le=10, description="실패 시 재시도 횟수")
    force_rebuild: bool = Field(False, description="이미 임베딩된 문서도 재처리")
    embedding_strategy: str = Field("auto", description="임베딩 전략 (auto, standard, late_chunking)")
    contextual_retrieval_mode: str = Field("auto", description="Contextual Retrieval 적용 (auto, off, rfp, all)")
    contextual_weight: float = Field(0.35, ge=0.0, le=1.0, description="Late Chunking + Contextual 결합 가중치")
    drop_meaningless: bool = Field(False, description="Contextual 게이트 탈락 청크를 제외할지 여부")
    wait_for_completion: bool = Field(False, description="True면 동기 실행 후 완료 응답 반환")


class EmbeddingBuildResult(BaseModel):
    """개별 문서 임베딩 결과"""
    document_id: int
    file_name: str
    status: str  # success, failed, skipped
    chunks_count: int
    embeddings_count: int
    embedding_dim: int
    error: Optional[str] = None


class EmbeddingBuildResponse(BaseModel):
    """임베딩 전체 결과"""
    success: bool
    processed: int
    failed: int
    skipped: int
    total_embeddings: int
    results: List[EmbeddingBuildResult]
    model: str
    embedding_dim: int


class EmbeddingBuildJobStartResponse(BaseModel):
    success: bool
    job_id: str
    status: str
    message: str
    source_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    started_at: str


class EmbeddingBuildJobStatusResponse(BaseModel):
    success: bool
    job_id: str
    status: str
    stage: str = ""
    progress: int = 0
    source_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    model: Optional[str] = None
    total_documents: int = 0
    processed: int = 0
    failed: int = 0
    skipped: int = 0
    total_embeddings: int = 0
    embedding_dim: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None


class EmbeddingStatusResponse(BaseModel):
    """임베딩 상태 조회"""
    total_documents: int
    embedded_documents: int
    total_embeddings: int
    avg_embeddings_per_doc: float
    not_embedded: int
    model: Optional[str] = None


class EmbeddingPcaPoint(BaseModel):
    document_id: int
    file_name: str
    source_id: Optional[str] = None
    category_id: Optional[str] = None
    organization: Optional[str] = None
    project_name: Optional[str] = None
    chunk_index: int
    group_key: str
    group_label: str
    preview_text: str
    x: float
    y: float
    z: float


class EmbeddingPcaResponse(BaseModel):
    success: bool
    source_id: Optional[str] = None
    sample_limit: int
    sampled_points: int
    total_embeddings: int
    embedded_documents: int
    embedding_dim: int
    model: Optional[str] = None
    group_by: str
    explained_variance_ratio: List[float]
    points: List[EmbeddingPcaPoint]


# ── Helper Functions ─────────────────────────────────────────────────────

def get_text_store(source_id: Optional[str] = None) -> ProcessedTextStore:
    """ProcessedTextStore 인스턴스 반환 (source_id 지정 시 통합 경로 사용)"""
    from app.services.processed_text_store import get_processed_text_store
    return get_processed_text_store(source_id)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _step6_job_path(job_id: str) -> Path:
    safe_job_id = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in ("-", "_"))
    return _STEP6_JOB_DIR / f"{safe_job_id}.json"


def _serialize_embedding_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status", "unknown"),
        "stage": job.get("stage", ""),
        "progress": int(job.get("progress", 0) or 0),
        "source_id": job.get("source_id") or "",
        "snapshot_id": job.get("snapshot_id") or "",
        "model": job.get("model") or "",
        "total_documents": int(job.get("total_documents", 0) or 0),
        "processed": int(job.get("processed", 0) or 0),
        "failed": int(job.get("failed", 0) or 0),
        "skipped": int(job.get("skipped", 0) or 0),
        "total_embeddings": int(job.get("total_embeddings", 0) or 0),
        "embedding_dim": int(job.get("embedding_dim", 0) or 0),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "error": job.get("error"),
        "result": job.get("result"),
        "persisted_at": _now_iso(),
    }


def _persist_embedding_job(job: dict[str, Any]) -> None:
    try:
        _STEP6_JOB_DIR.mkdir(parents=True, exist_ok=True)
        _step6_job_path(str(job.get("job_id") or "")).write_text(
            json.dumps(_serialize_embedding_job(job), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("[Step6] failed to persist embedding job: job_id=%s", job.get("job_id"))


def _load_persisted_embedding_job(job_id: str) -> Optional[dict[str, Any]]:
    try:
        job_path = _step6_job_path(job_id)
        if not job_path.exists():
            return None
        payload = json.loads(job_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return {
            "job_id": payload.get("job_id") or job_id,
            "status": payload.get("status", "unknown"),
            "stage": payload.get("stage", ""),
            "progress": int(payload.get("progress", 0) or 0),
            "source_id": payload.get("source_id") or "",
            "snapshot_id": payload.get("snapshot_id") or "",
            "model": payload.get("model") or "",
            "total_documents": int(payload.get("total_documents", 0) or 0),
            "processed": int(payload.get("processed", 0) or 0),
            "failed": int(payload.get("failed", 0) or 0),
            "skipped": int(payload.get("skipped", 0) or 0),
            "total_embeddings": int(payload.get("total_embeddings", 0) or 0),
            "embedding_dim": int(payload.get("embedding_dim", 0) or 0),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "error": payload.get("error"),
            "result": payload.get("result"),
            "persisted_only": True,
        }
    except Exception:
        logger.exception("[Step6] failed to load persisted embedding job: job_id=%s", job_id)
        return None


def _list_persisted_embedding_jobs() -> list[dict[str, Any]]:
    if not _STEP6_JOB_DIR.exists():
        return []
    jobs: list[dict[str, Any]] = []
    for path in sorted(_STEP6_JOB_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        job = _load_persisted_embedding_job(path.stem)
        if job:
            jobs.append(job)
    return jobs


def _create_embedding_job(req: EmbeddingBuildRequest) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "status": "running",
        "stage": "초기화",
        "progress": 0,
        "source_id": req.source_id or "",
        "snapshot_id": req.snapshot_id or "",
        "model": req.model or "",
        "total_documents": 0,
        "processed": 0,
        "failed": 0,
        "skipped": 0,
        "total_embeddings": 0,
        "embedding_dim": 0,
        "started_at": _now_iso(),
        "finished_at": None,
        "error": None,
        "result": None,
    }
    _EMBEDDING_BUILD_JOBS[job_id] = job
    _persist_embedding_job(job)
    return job


def _update_embedding_job(job_id: str, **updates: Any) -> None:
    job = _EMBEDDING_BUILD_JOBS.get(job_id)
    if not job:
        persisted = _load_persisted_embedding_job(job_id)
        if not persisted:
            return
        _EMBEDDING_BUILD_JOBS[job_id] = persisted
        job = persisted
    job.update(updates)
    _persist_embedding_job(job)


def _get_embedding_job(job_id: str) -> Optional[dict[str, Any]]:
    job = _EMBEDDING_BUILD_JOBS.get(job_id)
    if job:
        return job
    persisted = _load_persisted_embedding_job(job_id)
    if persisted:
        _EMBEDDING_BUILD_JOBS[job_id] = persisted
        return persisted
    return None


def _list_embedding_jobs(source_id: Optional[str] = None, status: Optional[str] = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    jobs: list[dict[str, Any]] = []
    for job in list(_EMBEDDING_BUILD_JOBS.values()) + _list_persisted_embedding_jobs():
        job_id = str(job.get("job_id") or "").strip()
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        if source_id and str(job.get("source_id") or "") != str(source_id):
            continue
        if status and str(job.get("status") or "") != str(status):
            continue
        jobs.append(_serialize_embedding_job(job))
    jobs.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    return jobs


def _doc_to_text_chunks(chunks: list) -> list[TextChunk]:
    result: list[TextChunk] = []
    for idx, chunk in enumerate(chunks):
        result.append(
            TextChunk(
                content=str(chunk.get("content") or ""),
                index=int(chunk.get("chunk_index", idx) or idx),
                start_char=int(chunk.get("start_char") or 0),
                end_char=int(chunk.get("end_char") or 0),
                token_count=int(chunk.get("token_count") or 0),
                page_number=chunk.get("page_number"),
                metadata=chunk.get("metadata") or {},
            )
        )
    return result


def _is_rfp_document(doc) -> bool:
    candidates = [
        doc.document_group,
        doc.document_type,
        doc.category_id,
        doc.section_type,
        doc.file_name,
        doc.relative_path,
    ]
    joined = " ".join(str(value or "") for value in candidates).lower()
    return "rfp" in joined or "제안요청서" in joined or "과업지시서" in joined


def _resolve_embedding_strategy(req: EmbeddingBuildRequest) -> str:
    strategy = str(req.embedding_strategy or "auto").strip().lower()
    if strategy != "auto":
        return strategy
    return "late_chunking" if supports_late_chunking(req.model) else "standard"


def _resolve_contextual_mode(req: EmbeddingBuildRequest, doc) -> str:
    mode = str(req.contextual_retrieval_mode or "auto").strip().lower()
    if mode in {"off", "all", "rfp"}:
        return mode
    return "rfp" if _is_rfp_document(doc) else "off"


def _build_contextual_texts(
    full_text: str,
    chunk_objs: list[TextChunk],
    req: EmbeddingBuildRequest,
) -> tuple[list[str], int]:
    context_llm = OllamaContextLLM(
        model=getattr(settings, "contextual_retrieval_model", settings.ollama_model),
        host=settings.ollama_host,
        max_document_chars=getattr(settings, "contextual_retrieval_doc_chars", 6000),
    )
    enricher = ContextualEnricher(
        gate=MeaningfulnessGate(),
        context_llm=context_llm,
        drop_meaningless=req.drop_meaningless,
    )
    enriched = enricher.enrich(full_text, chunk_objs)
    by_index = {item.original.index: item for item in enriched}
    ordered_texts: list[str] = []
    contextual_count = 0
    for chunk in chunk_objs:
        item = by_index.get(chunk.index)
        if not item:
            ordered_texts.append(chunk.content)
            continue
        ordered_texts.append(item.embed_text or chunk.content)
        if item.context:
            contextual_count += 1
    return ordered_texts, contextual_count


def _eligible_documents_query(db: Session, source_id: Optional[str] = None):
    from app.models.document_metadata import DocumentMetadata

    query = db.query(DocumentMetadata).filter(
        DocumentMetadata.include_in_rag.is_(True),
        DocumentMetadata.is_excluded.is_(False),
        DocumentMetadata.removed_at.is_(None),
    )
    if source_id:
        query = query.filter(DocumentMetadata.source_id == source_id)
    return query.order_by(DocumentMetadata.document_id)


def _group_value(doc, group_by: str) -> tuple[str, str]:
    if group_by == "document":
        label = doc.file_name or (Path(doc.file_path).name if doc.file_path else f"doc_{doc.document_id}")
        return f"document:{doc.document_id}", label
    if group_by == "organization":
        label = doc.final_organization or doc.organization or doc.scan_organization or "미분류 기관"
        return f"organization:{label}", label
    if group_by == "project":
        label = doc.final_project_name or doc.project_name or doc.scan_project_name or "미분류 프로젝트"
        return f"project:{label}", label
    label = doc.category_id or doc.final_document_category or doc.document_type or "미분류 카테고리"
    return f"category:{label}", label


def _preview_text(chunks: list, chunk_index: int) -> str:
    if chunk_index < 0 or chunk_index >= len(chunks):
        return ""
    text = str(chunks[chunk_index].get("content") or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > 140:
        return text[:137] + "..."
    return text


def _active_snapshot_name() -> Optional[str]:
    active = read_active_index() or {}
    snapshot = str(active.get("snapshot") or active.get("active_snapshot") or "").strip()
    return snapshot or None


def _snapshot_source_id(row: dict) -> str:
    meta = row.get("metadata") or {}
    return str(row.get("source_id") or meta.get("source_id") or "").strip()


def _snapshot_group_value(row: dict, group_by: str) -> tuple[str, str]:
    meta = row.get("metadata") or {}
    document_id = str(row.get("document_id") or row.get("chunk_id") or "unknown")

    if group_by == "document":
        label = (
            row.get("file_name")
            or meta.get("file_name")
            or meta.get("relative_path")
            or f"doc_{document_id}"
        )
        return f"document:{document_id}", str(label)

    if group_by == "organization":
        label = row.get("organization") or meta.get("organization") or "미분류 기관"
        return f"organization:{label}", str(label)

    if group_by == "project":
        label = meta.get("project_name") or "미분류 프로젝트"
        return f"project:{label}", str(label)

    label = (
        meta.get("category_id")
        or row.get("category_id")
        or row.get("category")
        or meta.get("document_category")
        or "미분류 카테고리"
    )
    return f"category:{label}", str(label)


def _snapshot_preview_text(row: dict) -> str:
    meta = row.get("metadata") or {}
    candidates = [
        row.get("section_heading"),
        meta.get("section_heading"),
        meta.get("section_label"),
        meta.get("project_name"),
        row.get("file_name"),
        meta.get("file_name"),
    ]
    for candidate in candidates:
        text = str(candidate or "").replace("\r", " ").replace("\n", " ").strip()
        if not text:
            continue
        if len(text) > 140:
            return text[:137] + "..."
        return text
    return ""


def _sample_snapshot_rows(meta_path: Path, source_id: Optional[str], sample_limit: int) -> tuple[list[dict], int, int, bool]:
    requested_source = (source_id or "").strip()
    rng = random.Random(42)
    reservoir: list[dict] = []
    total_embeddings = 0
    seen_points = 0
    embedded_documents: set[str] = set()
    matched_requested_source = False

    with meta_path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            if not line.strip():
                continue
            row = json.loads(line)
            row_source_id = _snapshot_source_id(row)

            if requested_source:
                if row_source_id == requested_source:
                    matched_requested_source = True
                else:
                    continue

            total_embeddings += 1
            document_id = str(row.get("document_id") or "").strip()
            if document_id:
                embedded_documents.add(document_id)

            point = {
                "faiss_pos": idx,
                "row": row,
            }
            seen_points += 1

            if len(reservoir) < sample_limit:
                reservoir.append(point)
                continue

            replace_index = rng.randint(0, seen_points - 1)
            if replace_index < sample_limit:
                reservoir[replace_index] = point

    return reservoir, total_embeddings, len(embedded_documents), matched_requested_source


def _build_snapshot_pca_response(source_id: Optional[str], sample_limit: int, group_by: str) -> Optional[EmbeddingPcaResponse]:
    snapshot = _active_snapshot_name()
    if not snapshot:
        return None

    index_path = FAISS_DIR / f"{snapshot}_ollama.index"
    meta_path = FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl"
    manifest_path = FAISS_DIR / f"{snapshot}_ollama.manifest.json"
    if not index_path.exists() or not meta_path.exists():
        return None

    try:
        import faiss  # type: ignore
    except Exception:
        return None

    reservoir, total_embeddings, embedded_documents, matched_source = _sample_snapshot_rows(
        meta_path,
        source_id,
        sample_limit,
    )

    requested_source = (source_id or "").strip()
    # snapshot_20260622_bge_m3_v2 처럼 snapshot 이름이 source_id처럼 보이는 경우는
    # 문서 source 필터가 아니라 활성 snapshot 전체를 보려는 요청으로 해석한다.
    if requested_source and not matched_source and requested_source in snapshot:
        reservoir, total_embeddings, embedded_documents, _ = _sample_snapshot_rows(
            meta_path,
            None,
            sample_limit,
        )

    model_used = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            model_used = manifest.get("embedding_model") or manifest.get("ollama_model")
        except Exception:
            model_used = None
    if not model_used:
        model_used = get_runtime_embedding_model()

    if not reservoir:
        return EmbeddingPcaResponse(
            success=True,
            source_id=source_id,
            sample_limit=sample_limit,
            sampled_points=0,
            total_embeddings=total_embeddings,
            embedded_documents=embedded_documents,
            embedding_dim=0,
            model=model_used,
            group_by=group_by,
            explained_variance_ratio=[0.0, 0.0, 0.0],
            points=[],
        )

    index = faiss.read_index(str(index_path))
    vectors = []
    point_rows = []
    for item in reservoir:
        row = item["row"]
        vector = np.asarray(index.reconstruct(int(item["faiss_pos"])), dtype=np.float32)
        vectors.append(vector)
        point_rows.append(row)

    matrix = np.vstack(vectors).astype(np.float32)
    coords, explained_variance_ratio = _compute_pca_3d(matrix)

    points = []
    for row, coord in zip(point_rows, coords):
        meta = row.get("metadata") or {}
        group_key, group_label = _snapshot_group_value(row, group_by)
        chunk_id = str(row.get("chunk_id") or "")
        chunk_index = -1
        if chunk_id:
            try:
                chunk_index = int(chunk_id.rsplit("_", 1)[-1])
            except Exception:
                chunk_index = -1
        points.append(
            EmbeddingPcaPoint(
                document_id=int(str(row.get("document_id") or 0) or 0),
                file_name=str(row.get("file_name") or meta.get("file_name") or f"doc_{row.get('document_id') or 0}"),
                source_id=_snapshot_source_id(row) or None,
                category_id=str(meta.get("category_id") or row.get("category") or meta.get("document_category") or "") or None,
                organization=str(row.get("organization") or meta.get("organization") or "") or None,
                project_name=str(meta.get("project_name") or "") or None,
                chunk_index=chunk_index,
                group_key=group_key,
                group_label=group_label,
                preview_text=_snapshot_preview_text(row),
                x=round(float(coord[0]), 6),
                y=round(float(coord[1]), 6),
                z=round(float(coord[2]), 6),
            )
        )

    return EmbeddingPcaResponse(
        success=True,
        source_id=source_id,
        sample_limit=sample_limit,
        sampled_points=len(points),
        total_embeddings=total_embeddings,
        embedded_documents=embedded_documents,
        embedding_dim=int(matrix.shape[1]) if matrix.size else 0,
        model=model_used,
        group_by=group_by,
        explained_variance_ratio=explained_variance_ratio,
        points=points,
    )


def _compute_pca_3d(matrix: np.ndarray) -> tuple[np.ndarray, list[float]]:
    sample_count = matrix.shape[0]
    if sample_count == 0:
        return np.empty((0, 3), dtype=np.float32), [0.0, 0.0, 0.0]

    centered = matrix - matrix.mean(axis=0, keepdims=True)
    if sample_count == 1:
        return np.zeros((1, 3), dtype=np.float32), [1.0, 0.0, 0.0]

    _, singular_values, vt = np.linalg.svd(centered, full_matrices=False)
    component_count = min(3, vt.shape[0])
    coords = centered @ vt[:component_count].T
    if component_count < 3:
        coords = np.pad(coords, ((0, 0), (0, 3 - component_count)), mode="constant")

    variances = (singular_values ** 2) / max(sample_count - 1, 1)
    total_variance = float(variances.sum()) if variances.size else 0.0
    ratios = []
    for i in range(3):
        if i < variances.size and total_variance > 0:
            ratios.append(round(float(variances[i] / total_variance), 4))
        else:
            ratios.append(0.0)
    return coords.astype(np.float32), ratios


async def generate_embeddings_for_document(
    document_id: int,
    chunks: list,
    doc_meta: dict,
    model: str,
    batch_size: int,
    retry_count: int,
    req: EmbeddingBuildRequest,
    ollama: OllamaService,
    text_store: ProcessedTextStore
) -> dict:
    """문서의 청크들에 대해 임베딩 생성"""
    try:
        full_text = text_store.get_text(str(document_id), format="txt") or ""
        chunk_objs = _doc_to_text_chunks(chunks)
        strategy = _resolve_embedding_strategy(req)
        contextual_mode = _resolve_contextual_mode(req, doc_meta["doc"])
        contextual_enabled = contextual_mode == "all" or (contextual_mode == "rfp" and _is_rfp_document(doc_meta["doc"]))

        contextual_texts: list[str] = [chunk.content for chunk in chunk_objs]
        contextual_chunks = 0
        if contextual_enabled and full_text.strip():
            contextual_texts, contextual_chunks = _build_contextual_texts(full_text, chunk_objs, req)

        all_embeddings: list[list[float]] = []
        late_chunking_applied = False
        applied_strategy = "standard"

        if strategy == "late_chunking" and full_text.strip():
            try:
                late_embedder = LateChunkingEmbedder(
                    model_name=resolve_late_chunk_model_name(model),
                    model_max_length=getattr(settings, "late_chunk_model_max_length", 8192),
                    macro_overlap_tokens=getattr(settings, "late_chunk_macro_overlap_tokens", 128),
                )
                late_vectors = late_embedder.embed_existing_chunks(
                    full_text,
                    chunk_objs,
                    contextual_texts=contextual_texts if contextual_enabled else None,
                    contextual_weight=req.contextual_weight,
                )
                if len(late_vectors) == len(chunk_objs):
                    all_embeddings = [item.embedding for item in late_vectors]
                    late_chunking_applied = True
                    applied_strategy = "late_chunking"
            except Exception as exc:
                applied_strategy = "standard_fallback"
                logger.warning("Late chunking fallback for document %s: %s", document_id, exc)

        if not all_embeddings:
            texts = contextual_texts if contextual_enabled else [chunk["content"] for chunk in chunks]
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                try:
                    batch_embeddings = await ollama.get_embeddings_batch(
                        batch_texts,
                        model=model,
                        batch_size=batch_size,
                    )
                    all_embeddings.extend(batch_embeddings)
                except Exception:
                    for text in batch_texts:
                        emb = []
                        for _ in range(retry_count + 1):
                            try:
                                emb = await ollama.get_embedding(text, model=model)
                                if emb:
                                    break
                            except Exception:
                                emb = []
                        all_embeddings.append(emb or [])

        valid_embeddings = [e for e in all_embeddings if len(e) > 0]
        if not valid_embeddings:
            return {
                "success": False,
                "error": "No valid embeddings generated"
            }

        embedding_dim = len(valid_embeddings[0])

        # 청크별 chunk_id와 embedding_id 생성
        embedding_ids = []
        for idx, chunk in enumerate(chunks):
            chunk_id = chunk.get("chunk_id") or f"{doc_meta.get('source_id', '')}_{document_id}_{idx:04d}"
            embedding_id = generate_embedding_id(chunk_id)
            embedding_ids.append(embedding_id)

        # 임베딩 저장
        text_store.save_embeddings(
            document_id,
            all_embeddings,
            model=model,
            metadata={
                **doc_meta,
                "embedding_provider": "late_chunking_hf" if late_chunking_applied else "ollama",
                "embedding_strategy": applied_strategy,
                "contextual_retrieval_mode": contextual_mode if contextual_enabled else "off",
                "contextual_model": getattr(settings, "contextual_retrieval_model", settings.ollama_model) if contextual_enabled else "",
                "late_chunking_applied": late_chunking_applied,
                "contextual_chunks": contextual_chunks,
                "embedding_ids": embedding_ids,
            },
        )

        return {
            "success": True,
            "chunks_count": len(chunks),
            "embeddings_count": len(valid_embeddings),
            "embedding_dim": embedding_dim,
            "embedding_strategy": applied_strategy,
            "contextual_retrieval_mode": contextual_mode if contextual_enabled else "off",
            "embedding_ids": embedding_ids,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ── API Endpoints ────────────────────────────────────────────────────────

async def execute_embedding_build(
    req: EmbeddingBuildRequest,
    db: Session,
    ollama: OllamaService,
    progress_callback: Optional[Callable[..., None]] = None,
) -> EmbeddingBuildResponse:
    """Step 6 동기 임베딩 실행 로직."""
    # source_id 지정 시 통합 경로 사용 (step6_embed 폴더)
    text_store = get_text_store(req.source_id)

    results = []
    processed = 0
    failed = 0
    skipped = 0
    total_embeddings = 0
    embedding_dim = 0

    try:
        req.model = get_runtime_embedding_model(req.model)

        # Ollama 연결 확인
        health = await ollama.check_connection()
        if not health.get("connected"):
            raise HTTPException(status_code=503, detail="Ollama service not available")

        # 처리할 문서 조회 (RAG 포함 + 제외/삭제되지 않은 문서)
        from app.models.document_metadata import DocumentMetadata, ProcessingStatus

        query = db.query(DocumentMetadata).filter(
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
        )

        if req.source_id:
            query = query.filter(DocumentMetadata.source_id == req.source_id)

        if req.document_ids:
            query = query.filter(DocumentMetadata.document_id.in_(req.document_ids))

        docs = query.all()
        total_documents = len(docs)
        if progress_callback:
            progress_callback(
                stage="임베딩 준비",
                progress=0,
                total_documents=total_documents,
                processed=processed,
                failed=failed,
                skipped=skipped,
                total_embeddings=total_embeddings,
                embedding_dim=embedding_dim,
            )

        for index, doc in enumerate(docs, start=1):
            document_id = doc.document_id
            file_name = Path(doc.file_path).name if doc.file_path else f"doc_{document_id}"

            try:
                # 청크 로드
                chunks = text_store.load_chunks(document_id)
                if not chunks or len(chunks) == 0:
                    skipped += 1
                    results.append(EmbeddingBuildResult(
                        document_id=document_id,
                        file_name=file_name,
                        status="skipped",
                        chunks_count=0,
                        embeddings_count=0,
                        embedding_dim=0,
                        error="No chunks found"
                    ))
                    if progress_callback:
                        progress_callback(
                            stage=f"임베딩 진행 중 ({index}/{total_documents})",
                            progress=int((index / max(total_documents, 1)) * 100),
                            total_documents=total_documents,
                            processed=processed,
                            failed=failed,
                            skipped=skipped,
                            total_embeddings=total_embeddings,
                            embedding_dim=embedding_dim,
                        )
                    continue

                # 이미 임베딩되었는지 확인
                if not req.force_rebuild:
                    existing_embeddings = text_store.load_embeddings(document_id)
                    if existing_embeddings and len(existing_embeddings) > 0:
                        # 임베딩 차원 확인
                        valid_emb = [e for e in existing_embeddings if len(e) > 0]
                        if valid_emb:
                            emb_dim = len(valid_emb[0])
                            skipped += 1
                            results.append(EmbeddingBuildResult(
                                document_id=document_id,
                                file_name=file_name,
                                status="skipped",
                                chunks_count=len(chunks),
                                embeddings_count=len(valid_emb),
                                embedding_dim=emb_dim
                            ))
                            if progress_callback:
                                progress_callback(
                                    stage=f"임베딩 진행 중 ({index}/{total_documents})",
                                    progress=int((index / max(total_documents, 1)) * 100),
                                    total_documents=total_documents,
                                    processed=processed,
                                    failed=failed,
                                    skipped=skipped,
                                    total_embeddings=total_embeddings,
                                    embedding_dim=embedding_dim,
                                )
                            continue

                # 임베딩 생성
                result = await generate_embeddings_for_document(
                    document_id=document_id,
                    chunks=chunks,
                    doc_meta={
                        "doc": doc,
                        "source_id": doc.source_id or "",
                        "dataset_id": doc.dataset_id or "",
                        "document_uid": doc.document_uid or "",
                        "relative_path": doc.relative_path or "",
                        "snapshot_id": req.snapshot_id or doc.faiss_snapshot or "",
                    },
                    model=req.model,
                    batch_size=req.batch_size,
                    retry_count=req.retry_count,
                    req=req,
                    ollama=ollama,
                    text_store=text_store
                )

                if result["success"]:
                    text_store.save_run_config(
                        str(document_id),
                        {
                            "source_id": doc.source_id or "",
                            "dataset_id": doc.dataset_id or "",
                            "document_uid": doc.document_uid or "",
                            "relative_path": doc.relative_path or "",
                            "snapshot_id": req.snapshot_id or doc.faiss_snapshot or "",
                            "embedding": {
                                "provider": "ollama",
                                "model": req.model,
                                "batch_size": req.batch_size,
                                "retry_count": req.retry_count,
                                "embedding_dim": result["embedding_dim"],
                                "embeddings_count": result["embeddings_count"],
                                "embedding_strategy": result.get("embedding_strategy") or req.embedding_strategy,
                                "contextual_retrieval_mode": result.get("contextual_retrieval_mode") or req.contextual_retrieval_mode,
                                "contextual_model": getattr(settings, "contextual_retrieval_model", settings.ollama_model),
                            },
                        },
                        snapshot_id=req.snapshot_id or doc.faiss_snapshot or "",
                    )
                    processed += 1
                    total_embeddings += result["embeddings_count"]
                    if embedding_dim == 0:
                        embedding_dim = result["embedding_dim"]
                    if req.snapshot_id:
                        doc.faiss_snapshot = req.snapshot_id
                    doc.status = ProcessingStatus.EMBEDDED.value
                    doc.updated_at = datetime.utcnow()

                    results.append(EmbeddingBuildResult(
                        document_id=document_id,
                        file_name=file_name,
                        status="success",
                        chunks_count=result["chunks_count"],
                        embeddings_count=result["embeddings_count"],
                        embedding_dim=result["embedding_dim"]
                    ))
                else:
                    failed += 1
                    results.append(EmbeddingBuildResult(
                        document_id=document_id,
                        file_name=file_name,
                        status="failed",
                        chunks_count=len(chunks),
                        embeddings_count=0,
                        embedding_dim=0,
                        error=result["error"]
                    ))

            except Exception as e:
                failed += 1
                results.append(EmbeddingBuildResult(
                    document_id=document_id,
                    file_name=file_name,
                    status="failed",
                    chunks_count=0,
                    embeddings_count=0,
                    embedding_dim=0,
                    error=str(e)
                ))

            if progress_callback:
                progress_callback(
                    stage=f"임베딩 진행 중 ({index}/{total_documents})",
                    progress=int((index / max(total_documents, 1)) * 100),
                    total_documents=total_documents,
                    processed=processed,
                    failed=failed,
                    skipped=skipped,
                    total_embeddings=total_embeddings,
                    embedding_dim=embedding_dim,
                )

        db.commit()
        if req.source_id:
            if processed > 0:
                update_source_dataset_status(req.source_id, "embedded")
            sync_source_index(req.source_id, db=db)

        response = EmbeddingBuildResponse(
            success=True,
            processed=processed,
            failed=failed,
            skipped=skipped,
            total_embeddings=total_embeddings,
            results=results,
            model=req.model,
            embedding_dim=embedding_dim
        )
        if progress_callback:
            progress_callback(
                stage="임베딩 완료",
                progress=100,
                total_documents=total_documents,
                processed=processed,
                failed=failed,
                skipped=skipped,
                total_embeddings=total_embeddings,
                embedding_dim=embedding_dim,
            )
        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding build failed: {str(e)}")


async def _run_embedding_job(job_id: str, req_data: dict[str, Any]) -> None:
    db = SessionLocal()
    ollama = OllamaService()

    def progress_callback(**updates: Any) -> None:
        _update_embedding_job(job_id, **updates)

    try:
        req = EmbeddingBuildRequest(**req_data)
        result = await execute_embedding_build(req, db, ollama, progress_callback=progress_callback)
        _update_embedding_job(
            job_id,
            status="completed",
            stage="임베딩 완료",
            progress=100,
            finished_at=_now_iso(),
            result=result.model_dump(),
            processed=result.processed,
            failed=result.failed,
            skipped=result.skipped,
            total_embeddings=result.total_embeddings,
            embedding_dim=result.embedding_dim,
            total_documents=result.processed + result.failed + result.skipped,
        )
    except Exception as exc:
        _update_embedding_job(
            job_id,
            status="failed",
            stage="오류",
            finished_at=_now_iso(),
            error=str(exc),
        )
        logger.exception("[Step6] embedding job failed: job_id=%s", job_id)
    finally:
        db.close()


@router.post("/embed")
async def build_embeddings(
    req: EmbeddingBuildRequest,
    db: Session = Depends(get_db),
    ollama: OllamaService = Depends(get_ollama)
):
    """
    Step 6: 임베딩 생성 실행

    기본값은 비동기 job 시작이다. 내부 API/일괄 실행에서는 wait_for_completion=True로 동기 실행할 수 있다.
    """
    if req.wait_for_completion:
        result = await execute_embedding_build(req, db, ollama)
        return result.model_dump()

    req.model = get_runtime_embedding_model(req.model)
    job = _create_embedding_job(req)
    asyncio.create_task(_run_embedding_job(job["job_id"], req.model_dump()))
    return EmbeddingBuildJobStartResponse(
        success=True,
        job_id=job["job_id"],
        status="running",
        message="Embedding build started",
        source_id=req.source_id,
        snapshot_id=req.snapshot_id,
        started_at=job["started_at"],
    )


@router.get("/embed/jobs")
async def list_embedding_build_jobs(source_id: Optional[str] = None, status: Optional[str] = None, limit: int = 20):
    jobs = _list_embedding_jobs(source_id=source_id, status=status)
    safe_limit = max(1, min(int(limit or 20), 200))
    return {
        "success": True,
        "jobs": jobs[:safe_limit],
        "count": len(jobs[:safe_limit]),
        "total": len(jobs),
    }


@router.get("/embed/jobs/{job_id}", response_model=EmbeddingBuildJobStatusResponse)
async def get_embedding_build_job(job_id: str):
    job = _get_embedding_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Embedding job not found: {job_id}")
    return EmbeddingBuildJobStatusResponse(success=True, **job)


@router.get("/status", response_model=EmbeddingStatusResponse)
async def get_embedding_status(db: Session = Depends(get_db)):
    """
    임베딩 상태 조회
    """
    from app.models.document_metadata import DocumentMetadata, MetaStatus
    text_store = get_text_store()

    try:
        # 전체 문서 수 (검수 완료 + RAG 포함 + 제외/삭제되지 않은 문서)
        total_documents = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
        ).count()

        # 임베딩된 문서 수 계산
        embedded_documents = 0
        total_embeddings = 0
        model_used = None

        docs = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
        ).all()

        for doc in docs:
            embeddings = text_store.load_embeddings(doc.document_id)
            if embeddings and len(embeddings) > 0:
                embedded_documents += 1
                total_embeddings += len(embeddings)
                # 모델 정보 가져오기 (첫 번째 문서에서)
                if model_used is None:
                    meta = text_store.load_embedding_metadata(doc.document_id)
                    if meta:
                        model_used = meta.get("model")

        avg_embeddings = total_embeddings / embedded_documents if embedded_documents > 0 else 0.0

        return EmbeddingStatusResponse(
            total_documents=total_documents,
            embedded_documents=embedded_documents,
            total_embeddings=total_embeddings,
            avg_embeddings_per_doc=round(avg_embeddings, 2),
            not_embedded=total_documents - embedded_documents,
            model=model_used
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_embedding_stats(db: Session = Depends(get_db)):
    """
    임베딩 통계 정보
    """
    from app.models.document_metadata import DocumentMetadata, MetaStatus
    text_store = get_text_store()

    try:
        # 검수 완료 + RAG 포함 + 제외/삭제되지 않은 문서
        docs = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
        ).all()

        stats = {
            "total_documents": 0,
            "embedded_documents": 0,
            "total_embeddings": 0,
            "min_embeddings": None,
            "max_embeddings": None,
            "avg_embeddings": 0.0,
            "models_used": []
        }

        embedding_counts = []
        models_set = set()

        for doc in docs:
            stats["total_documents"] += 1
            embeddings = text_store.load_embeddings(doc.document_id)
            if embeddings and len(embeddings) > 0:
                stats["embedded_documents"] += 1
                stats["total_embeddings"] += len(embeddings)
                embedding_counts.append(len(embeddings))

                # 모델 정보
                meta = text_store.load_embedding_metadata(doc.document_id)
                if meta and meta.get("model"):
                    models_set.add(meta["model"])

        if embedding_counts:
            stats["min_embeddings"] = min(embedding_counts)
            stats["max_embeddings"] = max(embedding_counts)
            stats["avg_embeddings"] = round(sum(embedding_counts) / len(embedding_counts), 2)

        stats["models_used"] = list(models_set)

        return stats

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/document/{document_id}/embeddings")
async def get_document_embeddings(
    document_id: int,
    db: Session = Depends(get_db)
):
    """
    특정 문서의 임베딩 정보 조회 (벡터 값 제외, 메타데이터만)
    """
    from app.models.document_metadata import DocumentMetadata
    text_store = get_text_store()

    try:
        # 문서 정보 조회
        doc = db.query(DocumentMetadata).filter(
            DocumentMetadata.document_id == document_id
        ).first()

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        file_name = Path(doc.file_path).name if doc.file_path else f"doc_{document_id}"

        # 임베딩 로드
        embeddings = text_store.load_embeddings(document_id)
        metadata = text_store.load_embedding_metadata(document_id)

        if not embeddings or len(embeddings) == 0:
            return {
                "document_id": document_id,
                "file_name": file_name,
                "embeddings_count": 0,
                "embedding_dim": 0,
                "model": None
            }

        # 차원 확인
        valid_emb = [e for e in embeddings if len(e) > 0]
        embedding_dim = len(valid_emb[0]) if valid_emb else 0

        return {
            "document_id": document_id,
            "file_name": file_name,
            "embeddings_count": len(embeddings),
            "embedding_dim": embedding_dim,
            "model": metadata.get("model") if metadata else None,
            "created_at": metadata.get("created_at") if metadata else None
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pca-3d", response_model=EmbeddingPcaResponse)
async def get_embedding_pca_3d(
    source_id: Optional[str] = Query(None, description="Document Source ID"),
    sample_limit: int = Query(600, ge=50, le=2000, description="최대 샘플 포인트 수"),
    group_by: str = Query("category", pattern="^(category|document|organization|project)$"),
    db: Session = Depends(get_db)
):
    """
    Step 6 임베딩 샘플을 PCA 3D 좌표로 축소하여 반환합니다.
    원본 임베딩 전체를 내리지 않고, 샘플링된 3차원 좌표만 admin UI에 제공합니다.
    """
    try:
        # 운영에서는 활성 snapshot 벡터가 최신 진실원본이므로 먼저 snapshot 기준으로 시도한다.
        snapshot_response = _build_snapshot_pca_response(source_id, sample_limit, group_by)
        if snapshot_response is not None:
            return snapshot_response

        text_store = get_text_store()
        docs = _eligible_documents_query(db, source_id).all()
        if not docs:
            return EmbeddingPcaResponse(
                success=True,
                source_id=source_id,
                sample_limit=sample_limit,
                sampled_points=0,
                total_embeddings=0,
                embedded_documents=0,
                embedding_dim=0,
                model=None,
                group_by=group_by,
                explained_variance_ratio=[0.0, 0.0, 0.0],
                points=[],
            )

        rng = random.Random(42)
        reservoir: list[dict] = []
        total_embeddings = 0
        embedded_documents = 0
        embedding_dim = 0
        model_used = None
        seen_points = 0

        for doc in docs:
            embeddings = text_store.load_embeddings(doc.document_id)
            if not embeddings:
                continue

            valid_indices = [idx for idx, vector in enumerate(embeddings) if vector and len(vector) > 0]
            if not valid_indices:
                continue

            embedded_documents += 1
            total_embeddings += len(valid_indices)
            if embedding_dim == 0:
                embedding_dim = len(embeddings[valid_indices[0]])

            if model_used is None:
                meta = text_store.load_embedding_metadata(doc.document_id)
                if meta and meta.get("model"):
                    model_used = meta.get("model")

            chunks = text_store.load_chunks(doc.document_id)
            group_key, group_label = _group_value(doc, group_by)
            file_name = doc.file_name or (Path(doc.file_path).name if doc.file_path else f"doc_{doc.document_id}")
            organization = doc.final_organization or doc.organization or doc.scan_organization
            project_name = doc.final_project_name or doc.project_name or doc.scan_project_name

            for chunk_index in valid_indices:
                seen_points += 1
                point = {
                    "vector": np.asarray(embeddings[chunk_index], dtype=np.float32),
                    "document_id": doc.document_id,
                    "file_name": file_name,
                    "source_id": doc.source_id,
                    "category_id": doc.category_id,
                    "organization": organization,
                    "project_name": project_name,
                    "chunk_index": chunk_index,
                    "group_key": group_key,
                    "group_label": group_label,
                    "preview_text": _preview_text(chunks, chunk_index),
                }
                if len(reservoir) < sample_limit:
                    reservoir.append(point)
                    continue
                replace_index = rng.randint(0, seen_points - 1)
                if replace_index < sample_limit:
                    reservoir[replace_index] = point

        if not reservoir:
            return EmbeddingPcaResponse(
                success=True,
                source_id=source_id,
                sample_limit=sample_limit,
                sampled_points=0,
                total_embeddings=total_embeddings,
                embedded_documents=embedded_documents,
                embedding_dim=embedding_dim,
                model=model_used,
                group_by=group_by,
                explained_variance_ratio=[0.0, 0.0, 0.0],
                points=[],
            )

        matrix = np.vstack([row["vector"] for row in reservoir]).astype(np.float32)
        coords, explained_variance_ratio = _compute_pca_3d(matrix)

        points = []
        for row, coord in zip(reservoir, coords):
            points.append(
                EmbeddingPcaPoint(
                    document_id=row["document_id"],
                    file_name=row["file_name"],
                    source_id=row["source_id"],
                    category_id=row["category_id"],
                    organization=row["organization"],
                    project_name=row["project_name"],
                    chunk_index=row["chunk_index"],
                    group_key=row["group_key"],
                    group_label=row["group_label"],
                    preview_text=row["preview_text"],
                    x=round(float(coord[0]), 6),
                    y=round(float(coord[1]), 6),
                    z=round(float(coord[2]), 6),
                )
            )

        return EmbeddingPcaResponse(
            success=True,
            source_id=source_id,
            sample_limit=sample_limit,
            sampled_points=len(points),
            total_embeddings=total_embeddings,
            embedded_documents=embedded_documents,
            embedding_dim=embedding_dim,
            model=model_used,
            group_by=group_by,
            explained_variance_ratio=explained_variance_ratio,
            points=points,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PCA 3D 생성 실패: {str(e)}")
