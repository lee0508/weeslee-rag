# Dataset Builder Step 7: FAISS Build API
"""
Step 6에서 생성된 임베딩으로 FAISS 인덱스 생성
기존 FAISS Admin API와 통합하여 Dataset Builder 워크플로우에 맞게 조정
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import numpy as np
import faiss
from pathlib import Path
from datetime import datetime
import json

from app.core.database import get_db
from app.services.processed_text_store import ProcessedTextStore
# 확장 메서드 로드
import app.services.processed_text_store_extensions

router = APIRouter(prefix="/admin/dataset-builder/step7")


# ── Request/Response Models ──────────────────────────────────────────────

class FAISSBuildRequest(BaseModel):
    """FAISS 인덱스 생성 요청"""
    collection_name: str = Field(..., description="컬렉션 이름")
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
    index_path: str
    total_vectors: int
    embedding_dim: int
    documents_indexed: int
    documents: List[DocumentIndexInfo]
    index_type: str
    created_at: str


class FAISSStatusResponse(BaseModel):
    """FAISS 상태"""
    collections: List[str]
    total_collections: int
    total_vectors: int
    total_documents: int


# ── Helper Functions ─────────────────────────────────────────────────────

def get_text_store() -> ProcessedTextStore:
    """ProcessedTextStore 인스턴스 반환"""
    return ProcessedTextStore()


def get_faiss_dir() -> Path:
    """FAISS 저장 디렉토리"""
    # ProcessedTextStore와 동일한 경로 구조 사용
    project_root = Path(__file__).resolve().parents[3]
    faiss_dir = project_root / "data" / "faiss"
    faiss_dir.mkdir(parents=True, exist_ok=True)
    return faiss_dir


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
    text_store = get_text_store()
    faiss_dir = get_faiss_dir()

    try:
        # 처리할 문서 조회
        from app.models.document_metadata import DocumentMetadata, MetaStatus

        query = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag == True
        ).order_by(DocumentMetadata.document_id)

        if req.document_ids:
            query = query.filter(DocumentMetadata.document_id.in_(req.document_ids))

        docs = query.all()

        if not docs:
            raise HTTPException(status_code=400, detail="No documents found")

        # 모든 임베딩 수집
        all_vectors = []
        document_infos = []
        vector_to_doc_map = []  # (vector_index) -> (document_id, chunk_index)

        for doc in docs:
            document_id = doc.document_id
            file_name = Path(doc.file_path).name if doc.file_path else f"doc_{document_id}"

            try:
                # 임베딩 로드
                embeddings = text_store.load_embeddings(document_id)

                if not embeddings or len(embeddings) == 0:
                    document_infos.append(DocumentIndexInfo(
                        document_id=document_id,
                        file_name=file_name,
                        chunks_indexed=0,
                        status="skipped"
                    ))
                    continue

                # 유효한 임베딩만 필터링
                valid_embeddings = [e for e in embeddings if len(e) > 0]

                if not valid_embeddings:
                    document_infos.append(DocumentIndexInfo(
                        document_id=document_id,
                        file_name=file_name,
                        chunks_indexed=0,
                        status="skipped"
                    ))
                    continue

                # 벡터 추가
                for chunk_idx, emb in enumerate(valid_embeddings):
                    all_vectors.append(emb)
                    vector_to_doc_map.append({
                        "document_id": document_id,
                        "chunk_index": chunk_idx,
                        "file_name": file_name
                    })

                document_infos.append(DocumentIndexInfo(
                    document_id=document_id,
                    file_name=file_name,
                    chunks_indexed=len(valid_embeddings),
                    status="success"
                ))

            except Exception as e:
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

        # 벡터 추가
        index.add(vectors)

        # 메타데이터 준비
        metadata = {
            "collection_name": req.collection_name,
            "total_vectors": len(vectors),
            "embedding_dim": vectors.shape[1],
            "documents_count": len([d for d in document_infos if d.status == "success"]),
            "index_type": req.index_type,
            "metric": req.metric,
            "normalized": req.normalize,
            "created_at": datetime.now().isoformat(),
            "vector_to_doc_map": vector_to_doc_map
        }

        # 저장
        index_path = save_faiss_collection(
            collection_name=req.collection_name,
            index=index,
            metadata=metadata,
            faiss_dir=faiss_dir
        )

        return FAISSBuildResponse(
            success=True,
            collection_name=req.collection_name,
            index_path=index_path,
            total_vectors=len(vectors),
            embedding_dim=vectors.shape[1],
            documents_indexed=len([d for d in document_infos if d.status == "success"]),
            documents=document_infos,
            index_type=req.index_type,
            created_at=metadata["created_at"]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FAISS build failed: {str(e)}")


@router.get("/status", response_model=FAISSStatusResponse)
async def get_faiss_status(db: Session = Depends(get_db)):
    """
    FAISS 인덱스 상태 조회
    """
    faiss_dir = get_faiss_dir()

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
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
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
async def get_collection_info(collection_name: str):
    """
    특정 컬렉션 정보 조회
    """
    faiss_dir = get_faiss_dir()
    collection_dir = faiss_dir / collection_name

    if not collection_dir.exists():
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        metadata_path = collection_dir / "metadata.json"
        if not metadata_path.exists():
            raise HTTPException(status_code=404, detail="Collection metadata not found")

        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # vector_to_doc_map은 너무 크므로 제외
        if "vector_to_doc_map" in metadata:
            del metadata["vector_to_doc_map"]

        return metadata

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/collection/{collection_name}")
async def delete_collection(collection_name: str):
    """
    컬렉션 삭제
    """
    faiss_dir = get_faiss_dir()
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
async def get_faiss_stats():
    """
    FAISS 전체 통계
    """
    faiss_dir = get_faiss_dir()

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
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

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
