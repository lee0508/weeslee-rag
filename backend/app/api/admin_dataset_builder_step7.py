# Dataset Builder Step 7: FAISS Build API
"""
Step 6에서 생성된 임베딩으로 FAISS 인덱스 생성
기존 Step 7 수동 빌드 결과를 운영 snapshot 파일 형식과 함께 저장한다.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import numpy as np
import faiss
from pathlib import Path
from datetime import datetime
import json

from app.core.config import settings
from app.core.database import get_db
from app.models.snapshot_manifest import DatasetInfo, RAGBuildInfo, SnapshotManifest, SnapshotStatus
from app.services.dataset_context import get_source_dataset_context
from app.services.processed_text_store import ProcessedTextStore
from app.services.runtime_model_settings import get_runtime_embedding_model
from app.services.runtime_compute_settings import is_stage_gpu_enabled
from app.services.snapshot_registry_service import mark_snapshot_queryable, upsert_snapshot_manifest
from app.services.snapshot_manager import create_snapshot_manifest, generate_snapshot_id
from app.services.source_artifact_index import sync_source_index

router = APIRouter(prefix="/admin/dataset-builder/step7")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"


# ── Request/Response Models ──────────────────────────────────────────────

class FAISSBuildRequest(BaseModel):
    """FAISS 인덱스 생성 요청"""
    collection_name: str = Field("weeslee_rag_main", description="컬렉션 이름")
    source_id: Optional[str] = Field(None, description="Document Source ID (특정 소스만 빌드)")
    snapshot_id: Optional[str] = Field(None, description="운영 Snapshot ID")
    document_ids: Optional[List[int]] = Field(None, description="처리할 문서 ID 목록 (비어있으면 전체)")
    index_type: str = Field("flat", description="인덱스 타입 (flat, ivf, hnsw)")
    metric: str = Field("l2", description="거리 메트릭 (l2, ip)")
    normalize: bool = Field(True, description="벡터 정규화 여부")


class DocumentIndexInfo(BaseModel):
    """문서별 인덱스 정보"""
    document_id: int
    file_name: str
    chunks_indexed: int
    status: str  # success, failed, skipped


class FAISSBuildResponse(BaseModel):
    """FAISS 빌드 결과"""
    success: bool
    collection_name: str
    source_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    index_path: str
    total_vectors: int
    embedding_dim: int
    documents_indexed: int
    documents: List[DocumentIndexInfo]
    index_type: str
    created_at: str
    gpu_used: bool = False


class FAISSStatusResponse(BaseModel):
    """FAISS 상태"""
    collections: List[str]
    total_collections: int
    total_vectors: int
    total_documents: int


# ── Helper Functions ─────────────────────────────────────────────────────

def get_text_store(source_id: Optional[str] = None) -> ProcessedTextStore:
    """ProcessedTextStore 인스턴스 반환 (source_id 지정 시 통합 경로 사용)"""
    from app.services.processed_text_store import get_processed_text_store
    return get_processed_text_store(source_id)


def get_faiss_dir(source_id: Optional[str] = None) -> Path:
    """FAISS 저장 디렉토리.

    Args:
        source_id: source_id가 있으면 통합 경로 사용 (/data/source/{source_id}/step7_index/)
                   없으면 기존 전역 경로 사용 (settings.faiss_index_dir)
    """
    if source_id:
        # 통합 경로: /data/source/{source_id}/step7_index/
        faiss_dir = PROJECT_ROOT / "data" / "source" / source_id / "step7_index"
    else:
        faiss_dir = Path(settings.faiss_index_dir).expanduser().resolve()
    faiss_dir.mkdir(parents=True, exist_ok=True)
    return faiss_dir


def get_snapshot_dir() -> Path:
    snapshot_dir = SNAPSHOT_DIR.expanduser().resolve()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    return snapshot_dir


def create_faiss_index(vectors: np.ndarray, index_type: str = "flat", metric: str = "l2") -> faiss.Index:
    """FAISS 인덱스 생성"""
    dim = vectors.shape[1]

    if metric == "ip":
        # Inner Product (코사인 유사도용, 정규화 필수)
        if index_type == "flat":
            index = faiss.IndexFlatIP(dim)
        elif index_type == "ivf":
            quantizer = faiss.IndexFlatIP(dim)
            nlist = min(100, len(vectors) // 10)  # 클러스터 수
            index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
            index.train(vectors)
        elif index_type == "hnsw":
            index = faiss.IndexHNSWFlat(dim, 32, faiss.METRIC_INNER_PRODUCT)
        else:
            raise ValueError(f"Unsupported index type: {index_type}")
    else:
        # L2 (유클리드 거리)
        if index_type == "flat":
            index = faiss.IndexFlatL2(dim)
        elif index_type == "ivf":
            quantizer = faiss.IndexFlatL2(dim)
            nlist = min(100, len(vectors) // 10)
            index = faiss.IndexIVFFlat(quantizer, dim, nlist)
            index.train(vectors)
        elif index_type == "hnsw":
            index = faiss.IndexHNSWFlat(dim, 32)
        else:
            raise ValueError(f"Unsupported index type: {index_type}")

    return index


def save_faiss_collection(
    collection_name: str,
    index: faiss.Index,
    metadata: Dict[str, Any],
    faiss_dir: Path
) -> str:
    """FAISS 인덱스와 메타데이터 저장"""
    collection_dir = faiss_dir / collection_name
    collection_dir.mkdir(parents=True, exist_ok=True)

    # 인덱스 저장
    index_path = collection_dir / "index.faiss"
    faiss.write_index(index, str(index_path))

    # 메타데이터 저장
    metadata_path = collection_dir / "metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    return str(index_path)


def _resolve_source_dataset_snapshot(
    source_id: str,
    requested_snapshot_id: Optional[str],
) -> tuple[str, str]:
    source_context = get_source_dataset_context(source_id)
    dataset_id = str(source_context.get("dataset_id") or "").strip()
    if not dataset_id:
        raise HTTPException(status_code=400, detail=f"dataset_id를 찾을 수 없습니다: source_id={source_id}")

    snapshot_id = str(requested_snapshot_id or "").strip() or generate_snapshot_id(source_id)
    return dataset_id, snapshot_id


def _load_existing_snapshot(snapshot_id: str) -> Optional[SnapshotManifest]:
    snapshot_file = get_snapshot_dir() / f"{snapshot_id}.json"
    if not snapshot_file.exists():
        return None
    try:
        return SnapshotManifest(**json.loads(snapshot_file.read_text(encoding="utf-8")))
    except Exception:
        return None


def _save_snapshot(snapshot: SnapshotManifest) -> None:
    snapshot_file = get_snapshot_dir() / f"{snapshot.snapshot_id}.json"
    snapshot_file.write_text(
        json.dumps(snapshot.dict(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    upsert_snapshot_manifest(snapshot)


def _infer_contract_types(project_name: str, organization: str, file_name: str, source_path: str) -> tuple[str, str]:
    try:
        from app.services.knowledge_graph import classify_project_type, get_organization_type

        organization_type = get_organization_type(organization or "") or ""
        project_types = classify_project_type(
            " ".join(part for part in [project_name, file_name, source_path] if part)
        )
        return organization_type, (project_types[0] if project_types else "")
    except Exception:
        return "", ""


def _normalize_search_keywords(value: object, limit: int = 20) -> list[str]:
    items = value if isinstance(value, list) else []
    keywords: list[str] = []
    for item in items:
        if isinstance(item, dict):
            token = str(item.get("keyword") or item.get("keyword_name") or item.get("name") or "").strip()
        else:
            token = str(item or "").strip()
        if len(token) < 2:
            continue
        if token not in keywords:
            keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords


def _build_snapshot_metadata_row(
    doc,
    chunk: dict,
    chunk_index: int,
    file_name: str,
    dataset_id: str,
    snapshot_id: str,
    total_pages: int,
) -> dict:
    chunk_meta = chunk.get("metadata") or {}
    content = str(chunk.get("content") or "")
    # [2026-07-10] 우선순위 수정: scan(파일명 기반)이 ocr보다 신뢰도 높음
    # ocr_project_name은 목차명("개요 4", "범위 1")이 잘못 추출되는 문제가 있음
    project_name = (
        doc.final_project_name
        or doc.project_name
        or doc.scan_project_name
        or doc.ocr_project_name
        or ""
    )
    organization = (
        doc.final_organization
        or doc.organization
        or doc.scan_organization
        or doc.ocr_organization
        or ""
    )
    organization_type, project_type = _infer_contract_types(
        project_name,
        organization,
        file_name,
        doc.file_path or "",
    )
    client_type = organization_type
    page_no = chunk.get("page_number") or chunk_meta.get("page_no") or chunk_meta.get("page_number")
    section_title = (
        chunk_meta.get("section_title")
        or chunk_meta.get("section_heading")
        or chunk_meta.get("title")
        or ""
    )
    section_id = str(chunk_meta.get("section_id") or f"{doc.document_id}-section-{chunk_index:04d}")
    document_group = doc.document_group or ""
    section_type = (
        doc.section_type
        or doc.final_document_category
        or doc.ocr_document_category
        or doc.scan_document_category
        or ""
    )
    document_category = (
        doc.section_type
        or doc.final_document_category
        or doc.ocr_document_category
        or doc.scan_document_category
        or doc.document_type
        or ""
    )
    chunk_id = str(chunk_meta.get("chunk_id") or f"{doc.document_id}-chunk-{chunk_index:04d}")
    top_section = str(chunk_meta.get("top_section") or "")
    section_name = str(chunk_meta.get("section_name") or section_title or "")
    subsection_titles = chunk_meta.get("subsection_titles") or []
    if not isinstance(subsection_titles, list):
        subsection_titles = [str(subsection_titles)]
    semantic_keywords = chunk_meta.get("keywords") or []
    if not isinstance(semantic_keywords, list):
        semantic_keywords = [str(semantic_keywords)]
    methodology = str(chunk_meta.get("methodology") or "")
    phase = str(chunk_meta.get("phase") or "")
    domain = str(chunk_meta.get("domain") or "")
    technology = str(chunk_meta.get("technology") or "")
    chunk_type = str(chunk_meta.get("chunk_type") or "")
    slide_range = chunk_meta.get("slide_range") or []
    slide_numbers = chunk_meta.get("slide_numbers") or []
    search_keywords = _normalize_search_keywords(doc.keywords)
    business_domain = str(doc.business_domain or "").strip()
    year_value = str(doc.final_year or doc.ocr_year or doc.year or doc.scan_year or "").strip()

    nested_metadata = {
        "document_id": str(doc.document_id),
        "source_id": doc.source_id or "",
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "document_uid": doc.document_uid or "",
        "source_name": "",
        "category": doc.category_id or "",
        "collection_name": "weeslee_rag_main",
        "collection_key": "weeslee_rag_main",
        "document_group": document_group,
        "document_category": document_category,
        "document_type": doc.document_type or "",
        "extension": Path(doc.file_path or "").suffix.lower(),
        "section_type": section_type,
        "section_heading": chunk_meta.get("section_heading") or "",
        "section_title": section_title,
        "section_id": section_id,
        "top_section": top_section,
        "section_name": section_name,
        "subsection_titles": subsection_titles,
        "keywords": semantic_keywords,
        "methodology": methodology,
        "phase": phase,
        "domain": domain,
        "technology": technology,
        "chunk_type": chunk_type,
        "project_name": project_name,
        "project_type": project_type,
        "organization": organization,
        "organization_type": organization_type,
        "client_type": client_type,
        "business_domain": business_domain,
        "year": year_value,
        "search_keywords": search_keywords,
        "keyword": search_keywords[0] if search_keywords else "",
        "relative_path": doc.relative_path or "",
        "original_source_path": doc.file_path or "",
        "file_name": file_name,
        "page_no": page_no,
        "slide_no": chunk_meta.get("slide_no"),
        "slide_range": slide_range,
        "slide_numbers": slide_numbers,
        "start_char": chunk.get("start_char", 0),
        "total_pages": total_pages,
        "matched_terms": [],
        "highlight_offsets": [],
    }

    return {
        "chunk_id": chunk_id,
        "document_id": str(doc.document_id),
        "source_id": doc.source_id or "",
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "document_uid": doc.document_uid or "",
        "category": doc.category_id or "",
        "section_heading": chunk_meta.get("section_heading") or "",
        "section_title": section_title,
        "section_id": section_id,
        "top_section": top_section,
        "section_name": section_name,
        "subsection_titles": subsection_titles,
        "keywords": semantic_keywords,
        "methodology": methodology,
        "phase": phase,
        "domain": domain,
        "technology": technology,
        "chunk_type": chunk_type,
        "section_type": section_type,
        "char_count": chunk.get("char_count") or len(content),
        "source_path": doc.file_path or "",
        "input_path": doc.file_path or "",
        "organization": organization,
        "organization_type": organization_type,
        "client_type": client_type,
        "project_type": project_type,
        "business_domain": business_domain,
        "year": year_value,
        "folder_year": year_value,
        "search_keywords": search_keywords,
        "keyword": search_keywords[0] if search_keywords else "",
        "root_group": "",
        "sub_group": "",
        "section_label": chunk_meta.get("section_label", ""),
        "relative_path": doc.relative_path or "",
        "original_source_path": doc.file_path or "",
        "file_name": file_name,
        "document_category": document_category,
        "document_group": document_group,
        "project_name": project_name,
        "embedding_text_length": len(content),
        "original_text_length": len(content),
        "page_no": page_no,
        "slide_no": chunk_meta.get("slide_no"),
        "slide_range": slide_range,
        "slide_numbers": slide_numbers,
        "start_char": chunk.get("start_char", 0),
        "total_pages": total_pages,
        "matched_terms": [],
        "highlight_offsets": [],
        "metadata": nested_metadata,
    }


def _write_snapshot_outputs(
    snapshot_id: str,
    source_id: str,
    dataset_id: str,
    index: faiss.Index,
    metadata_rows: list[dict],
    embedding_dim: int,
    model_name: str,
    document_count: int,
) -> str:
    # source_id가 있으면 통합 경로 사용 (/data/source/{source_id}/step7_index/)
    faiss_dir = get_faiss_dir(source_id)
    snapshot_index_path = faiss_dir / f"{snapshot_id}_ollama.index"
    snapshot_metadata_path = faiss_dir / f"{snapshot_id}_ollama_metadata.jsonl"

    faiss.write_index(index, str(snapshot_index_path))
    with snapshot_metadata_path.open("w", encoding="utf-8") as handle:
        for row in metadata_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    create_snapshot_manifest(
        snapshot_id=snapshot_id,
        source_id=source_id,
        dataset_id=dataset_id,
        vector_count=len(metadata_rows),
        document_count=document_count,
        embedding_dim=embedding_dim,
        embedding_provider="ollama",
        embedding_model=model_name,
    )

    snapshot = _load_existing_snapshot(snapshot_id)
    if snapshot is None:
        snapshot = SnapshotManifest(
            snapshot_id=snapshot_id,
            snapshot_name=snapshot_id,
            dataset=DatasetInfo(
                dataset_id=dataset_id,
                source_id=source_id,
                document_count=document_count,
                scan_completed_at=datetime.utcnow(),
            ),
            status=SnapshotStatus.DRAFT,
        )

    snapshot.dataset.dataset_id = dataset_id
    snapshot.dataset.source_id = source_id
    snapshot.dataset.document_count = document_count
    snapshot.rag_build = RAGBuildInfo(
        rag_build_id=f"rag_build_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        faiss_index_id=snapshot_id,
        built_at=datetime.utcnow(),
        embedding_model=f"ollama/{model_name}",
        chunk_count=len(metadata_rows),
        vector_count=len(metadata_rows),
        index_file=str(snapshot_index_path),
        metadata_file=str(snapshot_metadata_path),
    )
    snapshot.status = SnapshotStatus.DRAFT if not snapshot.is_active else snapshot.status
    _save_snapshot(snapshot)

    return str(snapshot_index_path)


def _load_collection_metadata(metadata_path: Path) -> Dict[str, Any]:
    """legacy metadata.json 또는 JSONL 기반 metadata 파일을 복구해 읽는다."""
    raw = metadata_path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    total_vectors = 0
    document_ids: set[str] = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        total_vectors += 1
        document_id = str(row.get("document_id") or "").strip()
        if document_id:
            document_ids.add(document_id)

    return {
        "collection_name": metadata_path.parent.name,
        "total_vectors": total_vectors,
        "documents_count": len(document_ids),
        "created_at": None,
        "legacy_jsonl": True,
    }


def _normalize_collection_metadata(metadata: Dict[str, Any], collection_dir: Path) -> Dict[str, Any]:
    normalized = dict(metadata or {})
    normalized.setdefault("collection_name", collection_dir.name)
    normalized.setdefault("total_vectors", 0)
    normalized.setdefault("documents_count", 0)
    return normalized


def _build_index_with_optional_gpu(index: faiss.Index, vectors: np.ndarray) -> tuple[faiss.Index, bool]:
    gpu_requested = is_stage_gpu_enabled("faiss")
    gpu_api_ready = all(
        hasattr(faiss, attr)
        for attr in ("StandardGpuResources", "index_cpu_to_gpu", "index_gpu_to_cpu")
    )
    if gpu_requested and gpu_api_ready:
        try:
            resources = faiss.StandardGpuResources()
            gpu_index = faiss.index_cpu_to_gpu(resources, 0, index)
            gpu_index.add(vectors)
            return faiss.index_gpu_to_cpu(gpu_index), True
        except Exception:
            pass

    index.add(vectors)
    return index, False


# ── API Endpoints ────────────────────────────────────────────────────────

@router.post("/build", response_model=FAISSBuildResponse)
async def build_faiss_index(
    req: FAISSBuildRequest,
    db: Session = Depends(get_db)
):
    """
    Step 7: FAISS 인덱스 생성

    Step 6에서 생성된 임베딩으로 FAISS 인덱스를 빌드합니다.
    """
    try:
        # 처리할 문서 조회 (RAG 포함 + 제외/삭제되지 않은 문서)
        from app.models.document_metadata import DocumentMetadata, ProcessingStatus

        source_id = str(req.source_id or "").strip()
        if not source_id:
            raise HTTPException(status_code=400, detail="source_id는 필수입니다.")

        # source_id 기반 통합 경로 사용 (step7_index 폴더)
        text_store = get_text_store(source_id)
        faiss_dir = get_faiss_dir(source_id)

        dataset_id, snapshot_id = _resolve_source_dataset_snapshot(source_id, req.snapshot_id)

        query = db.query(DocumentMetadata).filter(
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
        ).order_by(DocumentMetadata.document_id)

        query = query.filter(DocumentMetadata.source_id == source_id)
        if req.document_ids:
            query = query.filter(DocumentMetadata.document_id.in_(req.document_ids))

        docs = query.all()

        if not docs:
            raise HTTPException(status_code=400, detail="No documents found")

        # 모든 임베딩 수집
        all_vectors = []
        document_infos = []
        vector_to_doc_map = []  # (vector_index) -> (document_id, chunk_index)
        metadata_rows: list[dict] = []
        preview_chunk_rows: list[dict] = []
        model_name = get_runtime_embedding_model()
        chunks_jsonl_path = DATA_DIR / "staged" / "chunks" / f"{snapshot_id}_chunks.jsonl"

        for doc in docs:
            document_id = doc.document_id
            file_name = Path(doc.file_path).name if doc.file_path else f"doc_{document_id}"

            try:
                # 임베딩 로드
                embeddings = text_store.load_embeddings(document_id)
                chunks = text_store.load_chunks(document_id)
                report = text_store.get_report(str(document_id)) or {}

                if not embeddings or len(embeddings) == 0 or not chunks:
                    document_infos.append(DocumentIndexInfo(
                        document_id=document_id,
                        file_name=file_name,
                        chunks_indexed=0,
                        status="skipped"
                    ))
                    continue

                embedding_meta = text_store.load_embedding_metadata(document_id) or {}
                if embedding_meta.get("model"):
                    model_name = str(embedding_meta["model"])

                valid_count = 0
                total_pages = int(report.get("page_count") or doc.ocr_page_count or 0)
                for chunk_idx, emb in enumerate(embeddings):
                    if chunk_idx >= len(chunks) or not emb or len(emb) == 0:
                        continue
                    all_vectors.append(emb)
                    vector_to_doc_map.append({
                        "document_id": document_id,
                        "chunk_index": chunk_idx,
                        "file_name": file_name,
                        "source_id": doc.source_id or "",
                        "dataset_id": dataset_id,
                        "document_uid": doc.document_uid or "",
                        "category": doc.category_id or "",
                        # [2026-07-10] 우선순위 수정
                        "organization": (
                            doc.final_organization
                            or doc.organization
                            or doc.scan_organization
                            or doc.ocr_organization
                            or ""
                        ),
                        "project_name": (
                            doc.final_project_name
                            or doc.project_name
                            or doc.scan_project_name
                            or doc.ocr_project_name
                            or ""
                        ),
                    })
                    metadata_row = _build_snapshot_metadata_row(
                        doc=doc,
                        chunk=chunks[chunk_idx],
                        chunk_index=chunk_idx,
                        file_name=file_name,
                        dataset_id=dataset_id,
                        snapshot_id=snapshot_id,
                        total_pages=total_pages,
                    )
                    metadata_rows.append(metadata_row)
                    preview_chunk_rows.append({
                        **metadata_row,
                        "text": str(chunks[chunk_idx].get("content") or ""),
                    })
                    valid_count += 1

                if valid_count == 0:
                    document_infos.append(DocumentIndexInfo(
                        document_id=document_id,
                        file_name=file_name,
                        chunks_indexed=0,
                        status="skipped"
                    ))
                    continue

                document_infos.append(DocumentIndexInfo(
                    document_id=document_id,
                    file_name=file_name,
                    chunks_indexed=valid_count,
                    status="success"
                ))
                doc.status = ProcessingStatus.FAISS_INDEXED.value
                doc.faiss_snapshot = snapshot_id
                doc.chunk_count = max(int(doc.chunk_count or 0), valid_count)
                doc.updated_at = datetime.utcnow()

            except Exception:
                document_infos.append(DocumentIndexInfo(
                    document_id=document_id,
                    file_name=file_name,
                    chunks_indexed=0,
                    status="failed"
                ))

        if len(all_vectors) == 0:
            raise HTTPException(status_code=400, detail="No valid embeddings found")

        # NumPy 배열로 변환
        vectors = np.array(all_vectors, dtype=np.float32)

        # 정규화
        if req.normalize:
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            vectors = vectors / (norms + 1e-8)

        # FAISS 인덱스 생성
        index = create_faiss_index(vectors, index_type=req.index_type, metric=req.metric)
        index, gpu_used = _build_index_with_optional_gpu(index, vectors)

        # 메타데이터 준비
        metadata = {
            "collection_name": req.collection_name,
            "source_id": source_id,
            "snapshot_id": snapshot_id,
            "dataset_id": dataset_id,
            "total_vectors": len(vectors),
            "embedding_dim": vectors.shape[1],
            "documents_count": len([d for d in document_infos if d.status == "success"]),
            "index_type": req.index_type,
            "metric": req.metric,
            "normalized": req.normalize,
            "created_at": datetime.now().isoformat(),
            "vector_to_doc_map": vector_to_doc_map
        }

        # 레거시 collection 형식 저장
        save_faiss_collection(
            collection_name=req.collection_name,
            index=index,
            metadata=metadata,
            faiss_dir=faiss_dir
        )

        # 운영 snapshot 형식 저장
        index_path = _write_snapshot_outputs(
            snapshot_id=snapshot_id,
            source_id=source_id,
            dataset_id=dataset_id,
            index=index,
            metadata_rows=metadata_rows,
            embedding_dim=vectors.shape[1],
            model_name=model_name,
            document_count=len([d for d in document_infos if d.status == "success"]),
        )

        # 검색 미리보기를 위해 snapshot용 chunks.jsonl도 같이 기록한다.
        chunks_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with chunks_jsonl_path.open("w", encoding="utf-8") as handle:
            for row in preview_chunk_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        db.commit()
        mark_snapshot_queryable(
            snapshot_id,
            source_id=source_id,
            dataset_id=dataset_id,
            status="queryable",
            vector_count=len(vectors),
            chunk_count=len(metadata_rows),
            document_count=len([d for d in document_infos if d.status == "success"]),
            index_file=index_path,
            metadata_file=str(get_faiss_dir(source_id) / f"{snapshot_id}_ollama_metadata.jsonl"),
            manifest_path=str(get_snapshot_dir() / f"{snapshot_id}.json"),
        )
        sync_source_index(source_id, db=db)

        return FAISSBuildResponse(
            success=True,
            collection_name=req.collection_name,
            source_id=source_id,
            snapshot_id=snapshot_id,
            index_path=index_path,
            total_vectors=len(vectors),
            embedding_dim=vectors.shape[1],
            documents_indexed=len([d for d in document_infos if d.status == "success"]),
            documents=document_infos,
            index_type=req.index_type,
            created_at=metadata["created_at"],
            gpu_used=gpu_used,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FAISS build failed: {str(e)}")


@router.get("/status", response_model=FAISSStatusResponse)
async def get_faiss_status(source_id: Optional[str] = None, db: Session = Depends(get_db)):
    """
    FAISS 인덱스 상태 조회.

    Args:
        source_id: 지정 시 통합 경로(/data/source/{source_id}/step7_index/) 조회
    """
    faiss_dir = get_faiss_dir(source_id)

    try:
        collections = []
        total_vectors = 0
        total_documents = 0

        # 모든 컬렉션 스캔
        for collection_dir in faiss_dir.iterdir():
            if not collection_dir.is_dir():
                continue

            metadata_path = collection_dir / "metadata.json"
            if metadata_path.exists():
                metadata = _normalize_collection_metadata(
                    _load_collection_metadata(metadata_path),
                    collection_dir,
                )
                collections.append(metadata["collection_name"])
                total_vectors += metadata.get("total_vectors", 0)
                total_documents += metadata.get("documents_count", 0)

        return FAISSStatusResponse(
            collections=collections,
            total_collections=len(collections),
            total_vectors=total_vectors,
            total_documents=total_documents
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collection/{collection_name}")
async def get_collection_info(collection_name: str, source_id: Optional[str] = None):
    """
    특정 컬렉션 정보 조회.

    Args:
        source_id: 지정 시 통합 경로(/data/source/{source_id}/step7_index/) 조회
    """
    faiss_dir = get_faiss_dir(source_id)
    collection_dir = faiss_dir / collection_name

    if not collection_dir.exists():
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        metadata_path = collection_dir / "metadata.json"
        if not metadata_path.exists():
            raise HTTPException(status_code=404, detail="Collection metadata not found")

        metadata = _normalize_collection_metadata(
            _load_collection_metadata(metadata_path),
            collection_dir,
        )

        # vector_to_doc_map은 너무 크므로 제외
        if "vector_to_doc_map" in metadata:
            del metadata["vector_to_doc_map"]

        return metadata

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/collection/{collection_name}")
async def delete_collection(collection_name: str, source_id: Optional[str] = None):
    """
    컬렉션 삭제.

    Args:
        source_id: 지정 시 통합 경로(/data/source/{source_id}/step7_index/) 사용
    """
    faiss_dir = get_faiss_dir(source_id)
    collection_dir = faiss_dir / collection_name

    if not collection_dir.exists():
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        import shutil
        shutil.rmtree(collection_dir)

        return {
            "success": True,
            "message": f"Collection '{collection_name}' deleted"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_faiss_stats(source_id: Optional[str] = None):
    """
    FAISS 전체 통계.

    Args:
        source_id: 지정 시 통합 경로(/data/source/{source_id}/step7_index/) 조회
    """
    faiss_dir = get_faiss_dir(source_id)

    try:
        stats = {
            "total_collections": 0,
            "total_vectors": 0,
            "total_documents": 0,
            "collections": []
        }

        for collection_dir in faiss_dir.iterdir():
            if not collection_dir.is_dir():
                continue

            metadata_path = collection_dir / "metadata.json"
            if metadata_path.exists():
                metadata = _normalize_collection_metadata(
                    _load_collection_metadata(metadata_path),
                    collection_dir,
                )

                stats["total_collections"] += 1
                stats["total_vectors"] += metadata.get("total_vectors", 0)
                stats["total_documents"] += metadata.get("documents_count", 0)

                # 컬렉션 요약 정보만 추가
                stats["collections"].append({
                    "name": metadata["collection_name"],
                    "vectors": metadata.get("total_vectors", 0),
                    "documents": metadata.get("documents_count", 0),
                    "created_at": metadata.get("created_at")
                })

        return stats

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
