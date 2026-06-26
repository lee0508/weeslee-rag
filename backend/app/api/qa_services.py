# QA 통합 서비스 API 엔드포인트 (Highlight + Entity Extractor)
"""
QA Services API
- /qa/highlight: 텍스트에서 검색어 하이라이트
- /qa/extract-entities: 문서 속성 자동 추출
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qa", tags=["QA Services"])


# ========== Request/Response Models ==========

class HighlightRequest(BaseModel):
    """하이라이트 요청"""
    query: str = Field(..., description="검색어")
    text: str = Field(..., description="대상 텍스트")
    max_hits: int = Field(3, ge=1, le=10, description="최대 결과 수")
    context: int = Field(60, ge=20, le=200, description="스니펫 전후 문맥 글자 수")
    page: Optional[int] = Field(None, description="페이지 번호")


class HighlightResponse(BaseModel):
    """하이라이트 응답"""
    query: str
    count: int
    highlights: List[Dict[str, Any]]


class ChunkHighlightRequest(BaseModel):
    """청크 리스트 하이라이트 요청"""
    query: str = Field(..., description="검색어")
    chunks: List[Dict[str, Any]] = Field(..., description="청크 리스트 [{text, metadata}, ...]")
    max_per_chunk: int = Field(2, ge=1, le=5, description="청크당 최대 하이라이트 수")


class EntityExtractRequest(BaseModel):
    """엔티티 추출 요청"""
    text: str = Field(..., description="문서 텍스트 (앞부분 8000자까지 사용)")
    source_id: str = Field("unknown", description="문서 식별자")
    provider: Optional[str] = Field(None, description="LLM provider (ollama/claude/openai/gemini)")
    model: Optional[str] = Field(None, description="LLM 모델명")


class EntityExtractFromChunksRequest(BaseModel):
    """청크에서 엔티티 추출 요청"""
    chunks: List[Dict[str, Any]] = Field(..., description="청크 리스트 [{text, ...}, ...]")
    source_id: str = Field("unknown", description="문서 식별자")
    provider: Optional[str] = Field(None, description="LLM provider")
    model: Optional[str] = Field(None, description="LLM 모델명")
    head_chunk_count: int = Field(5, ge=1, le=20, description="사용할 앞부분 청크 수")


# ========== Endpoints ==========

@router.post("/highlight", response_model=HighlightResponse)
async def highlight_text(request: HighlightRequest):
    """
    텍스트에서 검색어 위치를 찾아 하이라이트를 반환한다.

    매칭 전략:
    1. exact: 정확 매칭 (대소문자 무시)
    2. normalized: 공백 정규화 매칭
    3. fuzzy: 퍼지 매칭 (토큰 포함률 기반)
    """
    try:
        from app.services.highlight import find_highlights

        highlights = find_highlights(
            query=request.query,
            text=request.text,
            max_hits=request.max_hits,
            context=request.context,
            page=request.page,
        )

        return HighlightResponse(
            query=request.query,
            count=len(highlights),
            highlights=[
                {
                    "start": h.start,
                    "end": h.end,
                    "matched_text": h.matched_text,
                    "snippet": h.snippet,
                    "marked_snippet": h.marked_snippet,
                    "score": h.score,
                    "match_type": h.match_type,
                    "page": h.page,
                }
                for h in highlights
            ],
        )

    except Exception as e:
        logger.exception("하이라이트 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/highlight/chunks")
async def highlight_chunks(request: ChunkHighlightRequest):
    """
    여러 청크에서 검색어 하이라이트를 추출한다.

    청크 형식: [{text: "...", metadata: {page, chunk_index, ...}}, ...]
    """
    try:
        from app.services.highlight import highlight_in_chunks

        results = highlight_in_chunks(
            query=request.query,
            chunks=request.chunks,
            max_per_chunk=request.max_per_chunk,
        )

        return {
            "query": request.query,
            "chunk_count": len(request.chunks),
            "highlight_count": len(results),
            "highlights": results,
        }

    except Exception as e:
        logger.exception("청크 하이라이트 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract-entities")
async def extract_entities(request: EntityExtractRequest):
    """
    문서 텍스트에서 속성(제목, 기관, 연도, 주제 등)을 LLM으로 추출한다.
    """
    try:
        from app.services.entity_extractor import EntityExtractor, get_llm

        llm = get_llm(provider=request.provider, model=request.model)
        extractor = EntityExtractor(llm)
        attrs = extractor.extract_from_text(
            source_id=request.source_id,
            text=request.text,
        )

        return {
            "source_id": attrs.source_id,
            "attributes": attrs.to_dict(),
        }

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"필요한 패키지가 설치되지 않았습니다: {e}")
    except Exception as e:
        logger.exception("엔티티 추출 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract-entities/chunks")
async def extract_entities_from_chunks(request: EntityExtractFromChunksRequest):
    """
    청크 리스트에서 문서 속성을 LLM으로 추출한다.
    문서 앞부분 청크를 사용하여 제목, 기관, 연도 등을 추출한다.
    """
    try:
        from app.services.entity_extractor import EntityExtractor, get_llm

        llm = get_llm(provider=request.provider, model=request.model)
        extractor = EntityExtractor(llm, head_chunk_count=request.head_chunk_count)
        attrs = extractor.extract(
            source_id=request.source_id,
            chunks=request.chunks,
        )

        return {
            "source_id": attrs.source_id,
            "chunk_count": len(request.chunks),
            "head_chunks_used": min(request.head_chunk_count, len(request.chunks)),
            "attributes": attrs.to_dict(),
        }

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"필요한 패키지가 설치되지 않았습니다: {e}")
    except Exception as e:
        logger.exception("엔티티 추출 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers")
async def list_providers():
    """사용 가능한 LLM provider 목록"""
    return {
        "providers": [
            {
                "name": "ollama",
                "description": "온프레미스 Ollama (gemma3, llama3 등)",
                "default_model": "gemma3:4b",
                "requires": "Ollama 서버 실행 중",
            },
            {
                "name": "claude",
                "description": "Anthropic Claude API",
                "default_model": "claude-sonnet-4-20250514",
                "requires": "ANTHROPIC_API_KEY 환경변수",
            },
            {
                "name": "openai",
                "description": "OpenAI API",
                "default_model": "gpt-4o",
                "requires": "OPENAI_API_KEY 환경변수",
            },
            {
                "name": "gemini",
                "description": "Google Gemini API",
                "default_model": "gemini-2.0-flash",
                "requires": "GEMINI_API_KEY 설정",
            },
            {
                "name": "fake",
                "description": "테스트용 (고정 응답 반환)",
                "default_model": None,
                "requires": "없음",
            },
        ]
    }
