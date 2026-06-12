# Dataset Builder Step 6: Embedding Build API
"""
Step 5에서 생성된 청크에 대해 임베딩 벡터를 생성
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from pydantic import BaseModel, Field
import numpy as np
from pathlib import Path
from datetime import datetime
import asyncio

from app.core.database import get_db
from app.services.ollama import OllamaService, get_ollama
from app.services.processed_text_store import ProcessedTextStore
# 확장 메서드 로드
import app.services.processed_text_store_extensions

router = APIRouter(prefix="/admin/dataset-builder/step6")


# ── Request/Response Models ──────────────────────────────────────────────

class EmbeddingBuildRequest(BaseModel):
    """임베딩 생성 요청"""
    document_ids: Optional[List[int]] = Field(None, description="처리할 문서 ID 목록 (비어있으면 전체)")
    model: str = Field("nomic-embed-text", description="임베딩 모델명")
    batch_size: int = Field(32, ge=1, le=100, description="배치 크기")
    force_rebuild: bool = Field(False, description="이미 임베딩된 문서도 재처리")


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


class EmbeddingStatusResponse(BaseModel):
    """임베딩 상태 조회"""
    total_documents: int
    embedded_documents: int
    total_embeddings: int
    avg_embeddings_per_doc: float
    not_embedded: int
    model: Optional[str] = None


# ── Helper Functions ─────────────────────────────────────────────────────

def get_text_store() -> ProcessedTextStore:
    """ProcessedTextStore 인스턴스 반환"""
    return ProcessedTextStore()


async def generate_embeddings_for_document(
    document_id: int,
    chunks: list,
    model: str,
    batch_size: int,
    ollama: OllamaService,
    text_store: ProcessedTextStore
) -> dict:
    """문서의 청크들에 대해 임베딩 생성"""
    try:
        # 청크 텍스트 추출
        texts = [chunk["content"] for chunk in chunks]

        # 배치 단위로 임베딩 생성
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            try:
                batch_embeddings = await ollama.get_embeddings_batch(batch_texts, model=model)
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                # 배치 실패 시 개별로 재시도
                for text in batch_texts:
                    try:
                        emb = await ollama.get_embedding(text, model=model)
                        all_embeddings.append(emb)
                    except:
                        # 실패한 청크는 빈 벡터로 채움
                        all_embeddings.append([])

        # 임베딩 차원 확인
        valid_embeddings = [e for e in all_embeddings if len(e) > 0]
        if not valid_embeddings:
            return {
                "success": False,
                "error": "No valid embeddings generated"
            }

        embedding_dim = len(valid_embeddings[0])

        # 임베딩 저장
        text_store.save_embeddings(document_id, all_embeddings, model=model)

        return {
            "success": True,
            "chunks_count": len(chunks),
            "embeddings_count": len(valid_embeddings),
            "embedding_dim": embedding_dim
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ── API Endpoints ────────────────────────────────────────────────────────

@router.post("/embed", response_model=EmbeddingBuildResponse)
async def build_embeddings(
    req: EmbeddingBuildRequest,
    db: Session = Depends(get_db),
    ollama: OllamaService = Depends(get_ollama)
):
    """
    Step 6: 임베딩 생성 실행

    Step 5에서 생성된 청크에 대해 임베딩 벡터를 생성합니다.
    """
    text_store = get_text_store()

    results = []
    processed = 0
    failed = 0
    skipped = 0
    total_embeddings = 0
    embedding_dim = 0

    try:
        # Ollama 연결 확인
        health = await ollama.check_connection()
        if not health.get("connected"):
            raise HTTPException(status_code=503, detail="Ollama service not available")

        # 처리할 문서 조회 (검수 완료 + RAG 포함 + 제외/삭제되지 않은 문서)
        from app.models.document_metadata import DocumentMetadata, MetaStatus

        query = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag == True,
            DocumentMetadata.is_excluded == False,
            DocumentMetadata.removed_at.is_(None),
        )

        if req.document_ids:
            query = query.filter(DocumentMetadata.document_id.in_(req.document_ids))

        docs = query.all()

        for doc in docs:
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
                            continue

                # 임베딩 생성
                result = await generate_embeddings_for_document(
                    document_id=document_id,
                    chunks=chunks,
                    model=req.model,
                    batch_size=req.batch_size,
                    ollama=ollama,
                    text_store=text_store
                )

                if result["success"]:
                    processed += 1
                    total_embeddings += result["embeddings_count"]
                    if embedding_dim == 0:
                        embedding_dim = result["embedding_dim"]

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

        return EmbeddingBuildResponse(
            success=True,
            processed=processed,
            failed=failed,
            skipped=skipped,
            total_embeddings=total_embeddings,
            results=results,
            model=req.model,
            embedding_dim=embedding_dim
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding build failed: {str(e)}")


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
            DocumentMetadata.include_in_rag == True,
            DocumentMetadata.is_excluded == False,
            DocumentMetadata.removed_at.is_(None),
        ).count()

        # 임베딩된 문서 수 계산
        embedded_documents = 0
        total_embeddings = 0
        model_used = None

        docs = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag == True,
            DocumentMetadata.is_excluded == False,
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
            DocumentMetadata.include_in_rag == True,
            DocumentMetadata.is_excluded == False,
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
