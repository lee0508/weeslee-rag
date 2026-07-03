# -*- coding: utf-8 -*-
# 문서 벡터화 API 엔드포인트
"""
Vectorization API Endpoints
- 문서 벡터화 (OCR → 청킹 → 임베딩 → VectorDB)
- Qdrant 검색
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vectorization", tags=["vectorization"])


class VectorizeDocumentRequest(BaseModel):
    """단일 문서 벡터화 요청"""
    file_path: str = Field(..., description="문서 파일 경로")
    source_id: str = Field(..., description="소스 식별자")
    file_id: Optional[str] = Field(None, description="파일 식별자")
    doc_meta: Optional[Dict[str, Any]] = Field(None, description="추가 메타데이터")
    use_qdrant: bool = Field(False, description="Qdrant 사용 여부")
    embedding_provider: Optional[str] = Field(None, description="임베딩 제공자 (bge-m3, ollama, openai)")


class VectorizeBatchRequest(BaseModel):
    """배치 벡터화 요청"""
    file_paths: List[str] = Field(..., description="파일 경로 리스트")
    source_id: str = Field(..., description="소스 식별자")
    use_qdrant: bool = Field(False, description="Qdrant 사용 여부")
    embedding_provider: Optional[str] = Field(None, description="임베딩 제공자")


class QdrantSearchRequest(BaseModel):
    """Qdrant 검색 요청"""
    query: str = Field(..., description="검색 질의")
    top_k: int = Field(5, ge=1, le=100, description="반환 개수")
    source_id: Optional[str] = Field(None, description="소스 필터")
    page: Optional[int] = Field(None, description="페이지 필터")
    filters: Optional[Dict[str, Any]] = Field(None, description="추가 필터")


@router.post("/document")
async def vectorize_document(request: VectorizeDocumentRequest):
    """
    단일 문서를 벡터화합니다.

    - 텍스트 추출 (OCR 포함)
    - 페이지 인식 청킹
    - 임베딩
    - VectorDB 저장 (Qdrant 또는 JSONL)
    """
    try:
        from app.services.document_vectorization_pipeline import (
            DocumentVectorizationPipeline,
        )
        from app.services.embedding_adapters import get_embedder

        # 임베딩 제공자 설정
        embedder = None
        if request.embedding_provider:
            embedder = get_embedder(provider=request.embedding_provider)

        pipeline = DocumentVectorizationPipeline(
            embedder=embedder,
            use_qdrant=request.use_qdrant,
        )

        result = await pipeline.process_document(
            file_path=request.file_path,
            source_id=request.source_id,
            file_id=request.file_id,
            doc_meta=request.doc_meta,
        )

        return result.to_dict()

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"필요한 패키지가 설치되지 않았습니다: {str(e)}"
        )
    except Exception as e:
        logger.exception("벡터화 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch")
async def vectorize_batch(request: VectorizeBatchRequest):
    """
    여러 문서를 배치 벡터화합니다.
    """
    try:
        from app.services.document_vectorization_pipeline import (
            DocumentVectorizationPipeline,
        )
        from app.services.embedding_adapters import get_embedder

        embedder = None
        if request.embedding_provider:
            embedder = get_embedder(provider=request.embedding_provider)

        pipeline = DocumentVectorizationPipeline(
            embedder=embedder,
            use_qdrant=request.use_qdrant,
        )

        result = await pipeline.process_batch(
            file_paths=request.file_paths,
            source_id=request.source_id,
        )

        return result.to_dict()

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"필요한 패키지가 설치되지 않았습니다: {str(e)}"
        )
    except Exception as e:
        logger.exception("배치 벡터화 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/qdrant/search")
async def qdrant_search(request: QdrantSearchRequest):
    """
    Qdrant에서 유사 문서를 검색합니다.
    """
    try:
        from app.services.qdrant_store import get_qdrant_store

        store = get_qdrant_store()
        results = store.search(
            query=request.query,
            top_k=request.top_k,
            source_id=request.source_id,
            page=request.page,
            filters=request.filters,
        )

        return {
            "query": request.query,
            "count": len(results),
            "results": results,
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Qdrant가 설치되지 않았습니다: {str(e)}"
        )
    except Exception as e:
        logger.exception("Qdrant 검색 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qdrant/info")
async def qdrant_info():
    """
    Qdrant 컬렉션 정보를 조회합니다.
    """
    try:
        from app.services.qdrant_store import get_qdrant_store

        store = get_qdrant_store()
        info = store.get_collection_info()
        return info

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Qdrant가 설치되지 않았습니다: {str(e)}"
        )
    except Exception as e:
        logger.exception("Qdrant 정보 조회 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qdrant/chunks/source/{source_id}")
async def get_chunks_by_source(
    source_id: str,
    limit: int = Query(1000, ge=1, le=10000),
):
    """
    특정 소스의 모든 청크를 조회합니다.
    """
    try:
        from app.services.qdrant_store import get_qdrant_store

        store = get_qdrant_store()
        chunks = store.get_chunks_by_source(source_id, limit=limit)

        return {
            "source_id": source_id,
            "count": len(chunks),
            "chunks": chunks,
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Qdrant가 설치되지 않았습니다: {str(e)}"
        )
    except Exception as e:
        logger.exception("청크 조회 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/qdrant/source/{source_id}")
async def delete_source(source_id: str):
    """
    특정 소스의 모든 청크를 삭제합니다.
    """
    try:
        from app.services.qdrant_store import get_qdrant_store

        store = get_qdrant_store()
        deleted = store.delete_by_source(source_id)

        return {
            "source_id": source_id,
            "deleted_count": deleted,
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Qdrant가 설치되지 않았습니다: {str(e)}"
        )
    except Exception as e:
        logger.exception("삭제 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/embedders")
async def list_embedders():
    """
    사용 가능한 임베딩 제공자 목록을 반환합니다.
    """
    embedders = [
        {
            "provider": "ollama",
            "description": "Ollama 로컬 임베딩 (기본)",
            "models": ["nomic-embed-text", "mxbai-embed-large"],
            "dim": 768,
        },
        {
            "provider": "bge-m3",
            "description": "BGE-M3 온프레미스 임베딩 (한국어 최적화)",
            "models": ["BAAI/bge-m3"],
            "dim": 1024,
            "requires": "sentence-transformers",
        },
        {
            "provider": "openai",
            "description": "OpenAI API 임베딩",
            "models": ["text-embedding-3-large", "text-embedding-3-small"],
            "dim": 3072,
            "requires": "openai, OPENAI_API_KEY",
        },
        {
            "provider": "fake",
            "description": "테스트용 가짜 임베딩",
            "models": [],
            "dim": 64,
        },
    ]

    return {"embedders": embedders}


@router.get("/chunking/config")
async def get_chunking_config():
    """
    현재 청킹 설정을 반환합니다.
    """
    from app.services.page_aware_chunking import get_page_aware_chunking_service

    service = get_page_aware_chunking_service()
    return {
        "chunk_size": service.chunk_size,
        "chunk_overlap": service.chunk_overlap,
        "respect_page_boundary": service.respect_page_boundary,
    }
