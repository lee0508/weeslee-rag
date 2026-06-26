# -*- coding: utf-8 -*-
# 문서 벡터화 파이프라인 - QA1/QA2 통합
"""
Document Vectorization Pipeline
- OCR/텍스트 추출 → 페이지 인식 청킹 → 임베딩 → VectorDB 저장

Pipeline Stages:
  1. Extract: 문서에서 텍스트 추출 (OCR 포함)
  2. Chunk: 페이지 인식 청킹
  3. Embed: 벡터 임베딩
  4. Store: VectorDB 저장 (Qdrant 또는 FAISS)
"""
from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

from app.core.config import settings
from app.extractors.extractor import document_extractor
from app.services.page_aware_chunking import (
    PageAwareChunkingService,
    PageAwareChunk,
    get_page_aware_chunking_service,
)
from app.services.embedding_adapters import (
    BaseEmbedder,
    get_embedder,
)

logger = logging.getLogger(__name__)


@dataclass
class VectorizationResult:
    """벡터화 결과"""
    success: bool
    file_path: str
    file_id: str
    source_id: str
    chunk_count: int
    error: Optional[str] = None
    processing_time: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BatchVectorizationResult:
    """배치 벡터화 결과"""
    total: int
    success_count: int
    fail_count: int
    total_chunks: int
    results: List[VectorizationResult]
    processing_time: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "total_chunks": self.total_chunks,
            "processing_time": self.processing_time,
            "results": [r.to_dict() for r in self.results],
        }


class DocumentVectorizationPipeline:
    """
    문서 벡터화 파이프라인

    Usage:
        pipeline = DocumentVectorizationPipeline()
        result = await pipeline.process_document(
            file_path="/path/to/doc.pdf",
            source_id="source_001",
        )
    """

    def __init__(
        self,
        embedder: Optional[BaseEmbedder] = None,
        chunking_service: Optional[PageAwareChunkingService] = None,
        vector_store: Optional[Any] = None,
        use_qdrant: bool = False,
    ):
        """
        Args:
            embedder: 임베딩 어댑터 (기본: settings 기반)
            chunking_service: 청킹 서비스 (기본: 페이지 인식 청킹)
            vector_store: 벡터 저장소 (Qdrant 또는 None)
            use_qdrant: Qdrant 사용 여부 (False면 FAISS 파일로 저장)
        """
        self.embedder = embedder or get_embedder()
        self.chunking_service = chunking_service or get_page_aware_chunking_service()
        self.use_qdrant = use_qdrant

        if use_qdrant and vector_store is None:
            from app.services.qdrant_store import get_qdrant_store
            self.vector_store = get_qdrant_store(embedder=self.embedder)
        else:
            self.vector_store = vector_store

    async def process_document(
        self,
        file_path: str,
        source_id: str,
        file_id: Optional[str] = None,
        doc_meta: Optional[Dict[str, Any]] = None,
    ) -> VectorizationResult:
        """
        단일 문서를 벡터화한다.

        Args:
            file_path: 문서 파일 경로
            source_id: 소스 식별자
            file_id: 파일 식별자 (없으면 파일명 사용)
            doc_meta: 추가 메타데이터

        Returns:
            VectorizationResult
        """
        import time
        start_time = time.time()

        path = Path(file_path)
        file_id = file_id or path.stem

        try:
            # 1. 텍스트 추출
            logger.info(f"텍스트 추출 중: {path.name}")
            extraction = await document_extractor.extract(file_path)

            if not extraction.get("success", False):
                return VectorizationResult(
                    success=False,
                    file_path=file_path,
                    file_id=file_id,
                    source_id=source_id,
                    chunk_count=0,
                    error=extraction.get("error", "텍스트 추출 실패"),
                )

            # 추출된 텍스트 조합
            text = self._combine_extracted_text(extraction)
            if not text.strip():
                return VectorizationResult(
                    success=False,
                    file_path=file_path,
                    file_id=file_id,
                    source_id=source_id,
                    chunk_count=0,
                    error="추출된 텍스트가 없습니다",
                )

            # 2. 청킹
            logger.info(f"청킹 중: {path.name}")
            meta = {
                "source_id": source_id,
                "file_id": file_id,
                "file_name": path.name,
                "doc_type": extraction.get("format"),
                **(doc_meta or {}),
            }

            # 페이지 정보가 있으면 페이지별 청킹
            pages = extraction.get("pages")
            if pages:
                chunks = self.chunking_service.chunk_with_pages(pages, meta)
            else:
                chunks = self.chunking_service.chunk_document(text, meta)

            if not chunks:
                return VectorizationResult(
                    success=False,
                    file_path=file_path,
                    file_id=file_id,
                    source_id=source_id,
                    chunk_count=0,
                    error="청크 생성 실패",
                )

            # 3. 임베딩 및 저장
            logger.info(f"임베딩 및 저장 중: {path.name} ({len(chunks)} chunks)")
            if self.use_qdrant and self.vector_store:
                stored_count = self.vector_store.upsert_chunks(chunks)
            else:
                # FAISS 저장은 별도 스크립트에서 처리
                stored_count = len(chunks)

            processing_time = time.time() - start_time

            return VectorizationResult(
                success=True,
                file_path=file_path,
                file_id=file_id,
                source_id=source_id,
                chunk_count=stored_count,
                processing_time=processing_time,
                metadata={
                    "page_count": extraction.get("page_count"),
                    "format": extraction.get("format"),
                },
            )

        except Exception as e:
            logger.exception(f"벡터화 실패: {file_path}")
            return VectorizationResult(
                success=False,
                file_path=file_path,
                file_id=file_id,
                source_id=source_id,
                chunk_count=0,
                error=str(e),
                processing_time=time.time() - start_time,
            )

    async def process_batch(
        self,
        file_paths: List[str],
        source_id: str,
        doc_metas: Optional[List[Dict[str, Any]]] = None,
    ) -> BatchVectorizationResult:
        """
        여러 문서를 배치 벡터화한다.

        Args:
            file_paths: 파일 경로 리스트
            source_id: 공통 소스 식별자
            doc_metas: 각 파일별 추가 메타데이터

        Returns:
            BatchVectorizationResult
        """
        import time
        start_time = time.time()

        doc_metas = doc_metas or [None] * len(file_paths)
        results: List[VectorizationResult] = []

        for i, file_path in enumerate(file_paths):
            result = await self.process_document(
                file_path=file_path,
                source_id=source_id,
                doc_meta=doc_metas[i] if i < len(doc_metas) else None,
            )
            results.append(result)

        success_count = sum(1 for r in results if r.success)
        total_chunks = sum(r.chunk_count for r in results)

        return BatchVectorizationResult(
            total=len(file_paths),
            success_count=success_count,
            fail_count=len(file_paths) - success_count,
            total_chunks=total_chunks,
            results=results,
            processing_time=time.time() - start_time,
        )

    def _combine_extracted_text(self, extraction: Dict[str, Any]) -> str:
        """추출 결과에서 텍스트를 조합한다."""
        # 페이지별 텍스트가 있으면 페이지 마커 삽입
        pages = extraction.get("pages")
        if pages:
            parts = []
            for page in pages:
                page_no = page.get("page_number", 0)
                content = page.get("content", "")
                if content.strip():
                    parts.append(f"===== [PAGE {page_no}] =====\n{content}")
            return "\n\n".join(parts)

        # 단일 텍스트
        return extraction.get("content") or extraction.get("text") or ""


# 편의 함수
async def vectorize_document(
    file_path: str,
    source_id: str,
    **kwargs,
) -> VectorizationResult:
    """단일 문서 벡터화 (편의 함수)"""
    pipeline = DocumentVectorizationPipeline(**kwargs)
    return await pipeline.process_document(file_path, source_id)


async def vectorize_batch(
    file_paths: List[str],
    source_id: str,
    **kwargs,
) -> BatchVectorizationResult:
    """배치 문서 벡터화 (편의 함수)"""
    pipeline = DocumentVectorizationPipeline(**kwargs)
    return await pipeline.process_batch(file_paths, source_id)


# 청크를 JSONL로 저장 (FAISS 빌드용)
def save_chunks_jsonl(
    chunks: List[PageAwareChunk],
    output_path: Path,
    append: bool = False,
) -> int:
    """
    청크를 JSONL 파일로 저장한다 (FAISS 빌드용).

    Args:
        chunks: 청크 리스트
        output_path: 출력 파일 경로
        append: 기존 파일에 추가할지 여부

    Returns:
        저장된 청크 수
    """
    mode = "a" if append else "w"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, mode, encoding="utf-8") as f:
        for chunk in chunks:
            record = {
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "chunk_index": chunk.chunk_index,
                "page": chunk.page,
                **chunk.metadata,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return len(chunks)


def load_chunks_jsonl(input_path: Path) -> List[Dict[str, Any]]:
    """
    JSONL 파일에서 청크를 로드한다.

    Args:
        input_path: 입력 파일 경로

    Returns:
        청크 dict 리스트
    """
    chunks = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks
