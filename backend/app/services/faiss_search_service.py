# FAISS 벡터 검색 서비스
# -*- coding: utf-8 -*-
"""
FAISS Search Service - 벡터 기반 유사도 검색 서비스.

Phase 6.4에서 GraphRAG Agent의 fallback으로 사용.
기존 build_faiss_index.py, search_faiss_index.py 로직 재사용.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
INDEXES_DIR = DATA_DIR / "indexes" / "faiss"
ACTIVE_INDEX_PATH = DATA_DIR / "active_index.json"
_CATEGORY_SUFFIXES = ("rfp", "proposal", "deliverable")

TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣_]+")


@dataclass
class FaissSearchResult:
    """FAISS 검색 결과 항목."""
    rank: int
    score: float
    chunk_id: str
    document_id: str
    category: Optional[str] = None
    section_heading: Optional[str] = None
    section_title: Optional[str] = None
    section_id: Optional[str] = None
    source_path: Optional[str] = None
    input_path: Optional[str] = None
    organization: Optional[str] = None
    organization_type: Optional[str] = None
    client_type: Optional[str] = None
    project_type: Optional[str] = None
    file_name: Optional[str] = None
    text_preview: Optional[str] = None
    # Phase 2: 페이지/슬라이드 정보
    page_no: Optional[int] = None
    slide_no: Optional[int] = None
    total_pages: Optional[int] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class FaissSearchResponse:
    """FAISS 검색 응답."""
    success: bool
    query: str
    results: list[FaissSearchResult] = field(default_factory=list)
    result_count: int = 0
    search_time_ms: int = 0
    embedding_provider: str = "hashing"
    error: Optional[str] = None


def _tokenize(text: str) -> list[str]:
    """텍스트를 토큰화."""
    return TOKEN_PATTERN.findall(text.lower())


def _resolve_snapshot_index_files(snapshot: Optional[str]) -> tuple[Optional[Path], Optional[Path], Optional[Path], Optional[str]]:
    snapshot = str(snapshot or "").strip()
    if not snapshot:
        return None, None, None, None

    primary_index = INDEXES_DIR / f"{snapshot}_ollama.index"
    primary_meta = INDEXES_DIR / f"{snapshot}_ollama_metadata.jsonl"
    primary_manifest = INDEXES_DIR / f"{snapshot}_ollama.manifest.json"
    if primary_index.exists() and primary_meta.exists():
        return primary_index, primary_meta, primary_manifest, None

    for category in _CATEGORY_SUFFIXES:
        cat_index = INDEXES_DIR / f"{snapshot}_{category}_ollama.index"
        cat_meta = INDEXES_DIR / f"{snapshot}_{category}_ollama_metadata.jsonl"
        cat_manifest = INDEXES_DIR / f"{snapshot}_{category}_ollama.manifest.json"
        if cat_index.exists() and cat_meta.exists():
            return cat_index, cat_meta, cat_manifest, category

    return primary_index, primary_meta, primary_manifest, None


def _normalize_vector(vector: np.ndarray) -> np.ndarray:
    """벡터 정규화."""
    norm = np.linalg.norm(vector)
    if norm == 0.0:
        return vector
    return vector / norm


def _hashing_embedding(text: str, dim: int = 768) -> np.ndarray:
    """해싱 기반 임베딩 (검증용)."""
    vector = np.zeros(dim, dtype=np.float32)
    for token in _tokenize(text):
        digest = hashlib.sha1(token.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % dim
        sign = -1.0 if int(digest[8:10], 16) % 2 else 1.0
        vector[bucket] += sign
    return _normalize_vector(vector)


def _ollama_embedding(
    text: str,
    model: str = "nomic-embed-text",
    url: str = "http://127.0.0.1:11434/api/embeddings",
    max_retries: int = 3,
) -> np.ndarray:
    """Ollama 임베딩."""
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            embedding = np.array(data.get("embedding", []), dtype=np.float32)
            if embedding.size == 0:
                raise RuntimeError("Ollama returned an empty embedding")
            return _normalize_vector(embedding)
        except (urllib.error.URLError, RuntimeError) as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Ollama embedding failed: {last_exc}") from last_exc


class FaissSearchService:
    """FAISS 벡터 검색 서비스."""

    def __init__(
        self,
        source_id: Optional[str] = None,
        embedding_provider: str = "hashing",
        embedding_dim: Optional[int] = None,
        ollama_url: Optional[str] = None,
        ollama_model: Optional[str] = None,
    ):
        """
        Args:
            source_id: 데이터 소스 ID
            embedding_provider: 임베딩 제공자 (hashing/ollama)
            embedding_dim: 임베딩 차원 (None이면 manifest에서 읽음)
            ollama_url: Ollama API URL (None이면 settings에서 읽음)
            ollama_model: Ollama 모델명 (None이면 settings에서 읽음)
        """
        self.source_id = source_id
        self.embedding_provider = embedding_provider
        # settings에서 기본값 읽기
        self.ollama_url = ollama_url or f"{settings.ollama_host}/api/embeddings"
        self.ollama_model = ollama_model or settings.ollama_embed_model
        # embedding_dim은 manifest에서 동적으로 읽도록 초기값 None 허용
        self._manifest_dim: Optional[int] = None
        self._init_embedding_dim = embedding_dim
        self._index = None
        self._metadata: list[dict] = []
        self._active_metadata: list[dict] = []
        self._active_document_ids: set[str] = set()
        self._chunks: dict[str, dict] = {}  # chunk_id -> chunk data
        self._loaded = False

    @property
    def embedding_dim(self) -> int:
        """임베딩 차원. manifest에서 읽은 값 우선, 없으면 초기값 또는 기본값."""
        if self._manifest_dim is not None:
            return self._manifest_dim
        if self._init_embedding_dim is not None:
            return self._init_embedding_dim
        return 768  # fallback default

    def _get_index_dir(self) -> Path:
        """source_id별 인덱스 디렉토리 반환."""
        if self.source_id:
            return INDEXES_DIR / self.source_id
        return INDEXES_DIR

    def _get_active_snapshot(self) -> Optional[str]:
        """active_index.json에서 현재 활성 스냅샷 이름을 읽는다."""
        if not ACTIVE_INDEX_PATH.exists():
            return None
        try:
            with open(ACTIVE_INDEX_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("snapshot") or data.get("active_snapshot")
        except Exception:
            return None

    def _load_index(self) -> bool:
        """FAISS 인덱스 로드. active_index.json 기준으로 {snapshot}_ollama.index 파일을 찾는다."""
        if self._loaded:
            return self._index is not None

        try:
            import faiss
        except ImportError:
            return False

        index_dir = self._get_index_dir()
        index_path = None
        metadata_path = None
        manifest_path = None

        selected_category = None

        # 1. active_index.json에서 snapshot 읽기
        snapshot = self._get_active_snapshot()
        if snapshot:
            index_path, metadata_path, manifest_path, selected_category = _resolve_snapshot_index_files(snapshot)

        # 2. 새 규칙 파일이 없으면 legacy 파일명 시도
        if not index_path or not index_path.exists():
            index_path = index_dir / "chunks.index"
            metadata_path = index_dir / "chunks_metadata.jsonl"
            manifest_path = None

        if not index_path.exists() or not metadata_path.exists():
            # 기본 경로 시도
            index_path = INDEXES_DIR / "chunks.index"
            metadata_path = INDEXES_DIR / "chunks_metadata.jsonl"
            manifest_path = None

        if not index_path.exists():
            self._loaded = True
            return False

        try:
            self._index = faiss.read_index(str(index_path))

            # manifest에서 embedding_dim 및 모델 정보 읽기
            if manifest_path and manifest_path.exists():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                self._manifest_dim = manifest.get("embedding_dim")
                # manifest에 모델 정보가 있으면 사용
                if manifest.get("embedding_model"):
                    self.ollama_model = manifest["embedding_model"]

            # 메타데이터에서 embedding_provider 감지
            if metadata_path.exists():
                with open(metadata_path, "r", encoding="utf-8") as f:
                    self._metadata = [
                        json.loads(line)
                        for line in f
                        if line.strip()
                    ]
                if self.source_id:
                    self._active_metadata = [
                        row for row in self._metadata
                        if str(row.get("source_id") or row.get("metadata", {}).get("source_id") or "").strip() == self.source_id
                    ]
                else:
                    self._active_metadata = list(self._metadata)
                self._active_document_ids = {
                    str(row.get("document_id") or "").strip()
                    for row in self._active_metadata
                    if str(row.get("document_id") or "").strip()
                }
                # ollama 인덱스면 embedding_provider 업데이트
                if "_ollama" in str(index_path):
                    self.embedding_provider = "ollama"
                if selected_category:
                    for row in self._metadata:
                        row.setdefault("category", selected_category)

            # 청크 텍스트 로드 (있으면)
            chunks_path = index_dir / "chunks.jsonl"
            if not chunks_path.exists():
                chunks_path = DATA_DIR / "processed" / "chunks" / "all_chunks.jsonl"
            if chunks_path.exists():
                with open(chunks_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            chunk = json.loads(line)
                            chunk_id = chunk.get("chunk_id")
                            if chunk_id:
                                self._chunks[chunk_id] = chunk

            self._loaded = True
            return True

        except Exception:
            self._loaded = True
            return False

    def _get_embedding(self, text: str) -> np.ndarray:
        """텍스트 임베딩 생성."""
        if self.embedding_provider == "ollama":
            try:
                return _ollama_embedding(
                    text, self.ollama_model, self.ollama_url
                ).astype(np.float32)
            except RuntimeError:
                # fallback to hashing
                return _hashing_embedding(text, self.embedding_dim).astype(np.float32)
        return _hashing_embedding(text, self.embedding_dim).astype(np.float32)

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
        category_filter: Optional[str] = None,
        organization_filter: Optional[str] = None,
    ) -> FaissSearchResponse:
        """
        FAISS 벡터 검색.

        Args:
            query: 검색 쿼리
            top_k: 반환할 최대 결과 수
            min_score: 최소 유사도 점수
            category_filter: 카테고리 필터
            organization_filter: 기관 필터

        Returns:
            FaissSearchResponse: 검색 결과
        """
        start_time = time.time()

        if not self._load_index():
            return FaissSearchResponse(
                success=False,
                query=query,
                error="FAISS 인덱스를 로드할 수 없습니다.",
                search_time_ms=int((time.time() - start_time) * 1000),
            )

        if self._index is None:
            return FaissSearchResponse(
                success=False,
                query=query,
                error="FAISS 인덱스가 존재하지 않습니다.",
                search_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            # 쿼리 임베딩
            query_vector = self._get_embedding(query)

            # 검색 (필터링 고려하여 더 많이 검색)
            search_k = top_k * 3 if category_filter or organization_filter else top_k
            scores, ids = self._index.search(
                np.array([query_vector], dtype=np.float32),
                search_k
            )

            results = []
            for idx, score in zip(ids[0], scores[0]):
                if idx < 0 or idx >= len(self._metadata):
                    continue

                if score < min_score:
                    continue

                row = self._metadata[idx]

                if self.source_id:
                    row_source_id = str(row.get("source_id") or row.get("metadata", {}).get("source_id") or "").strip()
                    if row_source_id != self.source_id:
                        continue

                # 필터 적용
                if category_filter:
                    if row.get("category", "").lower() != category_filter.lower():
                        continue
                if organization_filter:
                    if organization_filter.lower() not in row.get("organization", "").lower():
                        continue

                # 청크 텍스트 미리보기
                text_preview = None
                chunk_id = row.get("chunk_id")
                if chunk_id and chunk_id in self._chunks:
                    text = self._chunks[chunk_id].get("text", "")
                    text_preview = text[:200] + "..." if len(text) > 200 else text

                results.append(FaissSearchResult(
                    rank=len(results) + 1,
                    score=float(score),
                    chunk_id=row.get("chunk_id", ""),
                    document_id=row.get("document_id", ""),
                    category=row.get("category"),
                    section_heading=row.get("section_heading"),
                    section_title=row.get("section_title") or row.get("metadata", {}).get("section_title"),
                    section_id=row.get("section_id") or row.get("metadata", {}).get("section_id"),
                    source_path=row.get("source_path"),
                    input_path=row.get("input_path"),
                    organization=row.get("organization"),
                    organization_type=row.get("organization_type") or row.get("metadata", {}).get("organization_type"),
                    client_type=row.get("client_type") or row.get("metadata", {}).get("client_type"),
                    project_type=row.get("project_type") or row.get("metadata", {}).get("project_type"),
                    file_name=row.get("file_name"),
                    text_preview=text_preview,
                    # Phase 2: 페이지/슬라이드 정보
                    page_no=row.get("page_no"),
                    slide_no=row.get("slide_no"),
                    total_pages=row.get("total_pages"),
                    metadata=row.get("metadata", {}),
                ))

                if len(results) >= top_k:
                    break

            return FaissSearchResponse(
                success=True,
                query=query,
                results=results,
                result_count=len(results),
                embedding_provider=self.embedding_provider,
                search_time_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            return FaissSearchResponse(
                success=False,
                query=query,
                error=f"검색 오류: {str(e)}",
                search_time_ms=int((time.time() - start_time) * 1000),
            )

    def get_chunk_text(self, chunk_id: str) -> Optional[str]:
        """청크 ID로 텍스트 조회."""
        self._load_index()
        chunk = self._chunks.get(chunk_id)
        return chunk.get("text") if chunk else None

    def get_index_stats(self) -> dict:
        """인덱스 통계."""
        self._load_index()
        return {
            "loaded": self._index is not None,
            "vector_count": self._index.ntotal if self._index else 0,
            "metadata_count": len(self._metadata),
            "filtered_metadata_count": len(self._active_metadata),
            "filtered_document_count": len(self._active_document_ids),
            "chunks_count": len(self._chunks),
            "embedding_provider": self.embedding_provider,
            "source_id": self.source_id,
            "active_snapshot": self._get_active_snapshot(),
            "fallback_category": next(
                (
                    category for category in _CATEGORY_SUFFIXES
                    if (INDEXES_DIR / f"{self._get_active_snapshot()}_{category}_ollama.index").exists()
                    and not (INDEXES_DIR / f"{self._get_active_snapshot()}_ollama.index").exists()
                ),
                None,
            ),
        }


# 싱글톤 인스턴스 캐시
_services: dict[str, FaissSearchService] = {}


def get_faiss_search_service(
    source_id: Optional[str] = None,
    embedding_provider: str = "hashing",
) -> FaissSearchService:
    """FaissSearchService 싱글톤 반환."""
    key = f"{source_id or '_default_'}_{embedding_provider}"
    if key not in _services:
        _services[key] = FaissSearchService(source_id, embedding_provider)
    return _services[key]
