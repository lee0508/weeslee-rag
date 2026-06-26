# -*- coding: utf-8 -*-
# 페이지 인식 청킹 서비스 - QA2 chunker.py 기반
"""
Page-Aware Chunking Service
- 페이지 마커 [PAGE n]를 인식하여 페이지별 분리 후 청킹
- 청크가 페이지를 넘나들지 않아 page 메타데이터가 정확함
- LangChain RecursiveCharacterTextSplitter 사용
"""
from __future__ import annotations

import re
import uuid
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False


@dataclass
class PageAwareChunk:
    """페이지 정보를 포함한 청크"""
    chunk_id: str
    text: str
    chunk_index: int
    page: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "chunk_index": self.chunk_index,
            "page": self.page,
            **self.metadata,
        }


# 페이지 마커 패턴 (normalizer에서 삽입한 마커와 동일 규약)
_PAGE_MARKER = re.compile(r"=====\s*\[PAGE\s+(\d+)\]\s*=====")


def split_by_page(text: str) -> List[Tuple[int, str]]:
    """
    페이지 마커가 삽입된 텍스트를 (페이지번호, 본문) 리스트로 분리한다.

    Args:
        text: [PAGE n] 마커가 포함된 텍스트

    Returns:
        [(page_no, page_text), ...] 리스트
    """
    parts = _PAGE_MARKER.split(text)
    result: List[Tuple[int, str]] = []

    # split 결과: [선두텍스트, 페이지번호, 본문, 페이지번호, 본문, ...]
    if parts[0].strip():
        result.append((0, parts[0].strip()))  # 마커 이전 텍스트 = 페이지 0
    for i in range(1, len(parts), 2):
        page_no = int(parts[i])
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if body:
            result.append((page_no, body))
    return result


class PageAwareChunkingService:
    """페이지 경계를 존중하는 청킹 서비스"""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 300,
        respect_page_boundary: bool = True,
        separators: Optional[List[str]] = None,
    ):
        """
        Args:
            chunk_size: 청크 최대 길이 (문자 수)
            chunk_overlap: 인접 청크 중복 (문맥 연속성)
            respect_page_boundary: 페이지 경계 존중 여부
            separators: 분할 우선순위 구분자 목록
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.respect_page_boundary = respect_page_boundary

        if not HAS_LANGCHAIN:
            raise ImportError(
                "langchain-text-splitters가 필요합니다. "
                "pip install langchain-text-splitters"
            )

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            # 분할 우선순위: 문단 → 줄 → 문장(한/영) → 공백 → 문자
            separators=separators or ["\n\n", "\n", ". ", "。", "! ", "? ", " ", ""],
            length_function=len,
        )

    def chunk_document(
        self,
        text: str,
        doc_meta: Optional[Dict[str, Any]] = None,
    ) -> List[PageAwareChunk]:
        """
        텍스트를 청킹하고 청크별 메타데이터를 부착한다.

        Args:
            text: 페이지 마커가 포함될 수 있는 텍스트
            doc_meta: 문서 메타데이터 (source_id, file_id 등)

        Returns:
            PageAwareChunk 리스트
        """
        doc_meta = doc_meta or {}
        chunks: List[PageAwareChunk] = []
        chunk_index = 0

        if self.respect_page_boundary:
            # 페이지별로 분리한 뒤, 페이지 내에서만 청킹
            pages = split_by_page(text)
            for page_no, page_text in pages:
                sub_chunks = self.splitter.split_text(page_text)
                for sc in sub_chunks:
                    chunks.append(self._make_chunk(sc, doc_meta, chunk_index, page_no))
                    chunk_index += 1
        else:
            # 페이지 무시하고 전체를 청킹 (page=None)
            clean = _PAGE_MARKER.sub("\n", text)
            for sc in self.splitter.split_text(clean):
                chunks.append(self._make_chunk(sc, doc_meta, chunk_index, None))
                chunk_index += 1

        # 총 청크 수를 메타데이터에 기록
        for c in chunks:
            c.metadata["chunk_total"] = len(chunks)

        return chunks

    def _make_chunk(
        self,
        text: str,
        doc_meta: Dict[str, Any],
        chunk_index: int,
        page_no: Optional[int],
    ) -> PageAwareChunk:
        """청크 본문에 메타데이터를 부착하여 Chunk 생성"""
        chunk_id = str(uuid.uuid4())

        metadata = {
            # --- 식별자 ---
            "source_id": doc_meta.get("source_id"),
            "file_id": doc_meta.get("file_id"),
            "chunk_id": chunk_id,
            "chunk_index": chunk_index,
            # --- 위치 ---
            "page": page_no,
            # --- 문서 구조 정보 ---
            "doc_type": doc_meta.get("doc_type"),
            "file_name": doc_meta.get("file_name"),
            "source_name": doc_meta.get("source_name"),
            # --- 문서 속성 ---
            "title": doc_meta.get("title", ""),
            "organization": doc_meta.get("organization", ""),
            "year": doc_meta.get("year"),
            # --- 운영 ---
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        return PageAwareChunk(
            chunk_id=chunk_id,
            text=text,
            chunk_index=chunk_index,
            page=page_no,
            metadata=metadata,
        )

    def chunk_with_pages(
        self,
        pages: List[Dict[str, Any]],
        doc_meta: Optional[Dict[str, Any]] = None,
    ) -> List[PageAwareChunk]:
        """
        이미 페이지별로 분리된 텍스트를 청킹한다.

        Args:
            pages: [{"page_number": 1, "content": "..."}, ...]
            doc_meta: 문서 메타데이터

        Returns:
            PageAwareChunk 리스트
        """
        doc_meta = doc_meta or {}
        chunks: List[PageAwareChunk] = []
        chunk_index = 0

        for page in pages:
            page_no = page.get("page_number")
            content = page.get("content", "")
            if not content.strip():
                continue

            sub_chunks = self.splitter.split_text(content)
            for sc in sub_chunks:
                chunks.append(self._make_chunk(sc, doc_meta, chunk_index, page_no))
                chunk_index += 1

        # 총 청크 수 기록
        for c in chunks:
            c.metadata["chunk_total"] = len(chunks)

        return chunks


# 싱글톤 인스턴스 (1000 문자, 300 오버랩 - QA2 검증값)
page_aware_chunking_service = PageAwareChunkingService(
    chunk_size=1000,
    chunk_overlap=300,
    respect_page_boundary=True,
)


def get_page_aware_chunking_service() -> PageAwareChunkingService:
    """의존성 주입용"""
    return page_aware_chunking_service
