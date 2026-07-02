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
    """단일 인덱스 파일 반환 (호환성 유지용)."""
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


def _resolve_all_snapshot_index_files(snapshot: Optional[str]) -> list[tuple[Path, Path, Optional[Path], Optional[str]]]:
    """스냅샷에 대한 모든 카테고리별 인덱스 파일 반환."""
    snapshot = str(snapshot or "").strip()
    if not snapshot:
        return []

    results: list[tuple[Path, Path, Optional[Path], Optional[str]]] = []

    # 1. 통합 인덱스가 있으면 그것만 사용
    primary_index = INDEXES_DIR / f"{snapshot}_ollama.index"
    primary_meta = INDEXES_DIR / f"{snapshot}_ollama_metadata.jsonl"
    primary_manifest = INDEXES_DIR / f"{snapshot}_ollama.manifest.json"
    if primary_index.exists() and primary_meta.exists():
        return [(primary_index, primary_meta, primary_manifest, None)]

    # 2. 카테고리별 인덱스 모두 수집
    for category in _CATEGORY_SUFFIXES:
        cat_index = INDEXES_DIR / f"{snapshot}_{category}_ollama.index"
        cat_meta = INDEXES_DIR / f"{snapshot}_{category}_ollama_metadata.jsonl"
        cat_manifest = INDEXES_DIR / f"{snapshot}_{category}_ollama.manifest.json"
        if cat_index.exists() and cat_meta.exists():
            results.append((cat_index, cat_meta, cat_manifest if cat_manifest.exists() else None, category))

    return results


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
        # 카테고리별 인덱스 지원
        self._indexes: dict[str, Any] = {}  # category -> faiss index
        self._metadata: list[dict] = []
        self._metadata_by_category: dict[str, list[dict]] = {}  # category -> metadata list
        self._category_offsets: dict[str, int] = {}  # category -> start offset in _metadata
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
        """FAISS 인덱스 로드. 모든 카테고리별 인덱스를 로드한다."""
        if self._loaded:
            return self._index is not None or bool(self._indexes)

        try:
            import faiss
        except ImportError:
            self._loaded = True
            return False

        index_dir = self._get_index_dir()
        snapshot = self._get_active_snapshot()

        # 모든 카테고리 인덱스 수집
        all_index_files = _resolve_all_snapshot_index_files(snapshot) if snapshot else []

        # Legacy 파일 시도
        if not all_index_files:
            legacy_index = index_dir / "chunks.index"
            legacy_meta = index_dir / "chunks_metadata.jsonl"
            if not legacy_index.exists():
                legacy_index = INDEXES_DIR / "chunks.index"
                legacy_meta = INDEXES_DIR / "chunks_metadata.jsonl"
            if legacy_index.exists() and legacy_meta.exists():
                all_index_files = [(legacy_index, legacy_meta, None, None)]

        if not all_index_files:
            self._loaded = True
            return False

        try:
            # 모든 인덱스와 메타데이터 로드
            for index_path, metadata_path, manifest_path, category in all_index_files:
                if not index_path.exists() or not metadata_path.exists():
                    continue

                cat_key = category or "_default_"
                cat_index = faiss.read_index(str(index_path))
                self._indexes[cat_key] = cat_index

                # manifest에서 embedding_dim 읽기
                if manifest_path and manifest_path.exists():
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    if self._manifest_dim is None:
                        self._manifest_dim = manifest.get("embedding_dim")
                    if manifest.get("embedding_model"):
                        self.ollama_model = manifest["embedding_model"]

                # 메타데이터 로드
                cat_metadata: list[dict] = []
                with open(metadata_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            row = json.loads(line)
                            if category:
                                row.setdefault("category", category)
                            cat_metadata.append(row)

                # 카테고리별 메타데이터 저장
                self._metadata_by_category[cat_key] = cat_metadata
                self._category_offsets[cat_key] = len(self._metadata)
                self._metadata.extend(cat_metadata)

                # ollama 인덱스면 embedding_provider 업데이트
                if "_ollama" in str(index_path):
                    self.embedding_provider = "ollama"

            # 호환성: 첫 번째 인덱스를 기본 인덱스로 설정
            if self._indexes:
                first_key = next(iter(self._indexes))
                self._index = self._indexes[first_key]

            # active_metadata 구성
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
            return bool(self._indexes)

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
        FAISS 벡터 검색. 모든 카테고리 인덱스를 검색하고 결과를 병합한다.

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

        if not self._indexes:
            return FaissSearchResponse(
                success=False,
                query=query,
                error="FAISS 인덱스가 존재하지 않습니다.",
                search_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            # 쿼리 임베딩
            query_vector = self._get_embedding(query)
            query_array = np.array([query_vector], dtype=np.float32)

            # 검색 (필터링 고려하여 더 많이 검색)
            search_k = top_k * 3 if category_filter or organization_filter else top_k

            # 모든 카테고리 인덱스에서 검색 후 결과 수집
            all_candidates: list[tuple[float, dict]] = []

            for cat_key, cat_index in self._indexes.items():
                cat_metadata = self._metadata_by_category.get(cat_key, [])
                if not cat_metadata:
                    continue

                # 카테고리 필터 적용: 해당 카테고리만 검색
                if category_filter and cat_key != "_default_":
                    if cat_key.lower() != category_filter.lower():
                        continue

                try:
                    scores, ids = cat_index.search(query_array, min(search_k, cat_index.ntotal))
                except Exception:
                    continue

                for idx, score in zip(ids[0], scores[0]):
                    if idx < 0 or idx >= len(cat_metadata):
                        continue

                    if score < min_score:
                        continue

                    row = cat_metadata[idx]

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

                    all_candidates.append((float(score), row))

            # 점수 기준 정렬 (내림차순)
            all_candidates.sort(key=lambda x: x[0], reverse=True)

            results = []
            seen_chunk_ids: set[str] = set()

            for score, row in all_candidates:
                chunk_id = row.get("chunk_id", "")
                if chunk_id and chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk_id)

                # 청크 텍스트 미리보기
                text_preview = None
                if chunk_id and chunk_id in self._chunks:
                    text = self._chunks[chunk_id].get("text", "")
                    text_preview = text[:200] + "..." if len(text) > 200 else text

                results.append(FaissSearchResult(
                    rank=len(results) + 1,
                    score=score,
                    chunk_id=chunk_id,
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
                    metadata={
                        **(row.get("metadata", {}) or {}),
                        "source_id": row.get("source_id") or row.get("metadata", {}).get("source_id"),
                        "dataset_id": row.get("dataset_id") or row.get("metadata", {}).get("dataset_id"),
                        "snapshot_id": (
                            row.get("snapshot_id")
                            or row.get("faiss_snapshot")
                            or row.get("metadata", {}).get("snapshot_id")
                            or row.get("metadata", {}).get("faiss_snapshot")
                        ),
                        "document_uid": row.get("document_uid") or row.get("metadata", {}).get("document_uid"),
                        "relative_path": row.get("relative_path") or row.get("metadata", {}).get("relative_path"),
                        "source_path": row.get("source_path") or row.get("metadata", {}).get("source_path"),
                        "page_no": row.get("page_no") or row.get("metadata", {}).get("page_no"),
                        "slide_no": row.get("slide_no") or row.get("metadata", {}).get("slide_no"),
                        "section_title": row.get("section_title") or row.get("metadata", {}).get("section_title"),
                        "section_id": row.get("section_id") or row.get("metadata", {}).get("section_id"),
                        "project_name": (
                            row.get("project_name")
                            or row.get("final_project_name")
                            or row.get("ocr_project_name")
                            or row.get("scan_project_name")
                            or row.get("metadata", {}).get("project_name")
                            or row.get("metadata", {}).get("final_project_name")
                            or row.get("metadata", {}).get("ocr_project_name")
                            or row.get("metadata", {}).get("scan_project_name")
                        ),
                        "project_id": (
                            row.get("project_id")
                            or row.get("metadata", {}).get("project_id")
                        ),
                        "faiss_snapshot": (
                            row.get("faiss_snapshot")
                            or row.get("snapshot_id")
                            or row.get("metadata", {}).get("faiss_snapshot")
                            or row.get("metadata", {}).get("snapshot_id")
                        ),
                    },
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
        total_vectors = sum(idx.ntotal for idx in self._indexes.values()) if self._indexes else 0
        return {
            "loaded": bool(self._indexes),
            "index_count": len(self._indexes),
            "categories_loaded": list(self._indexes.keys()),
            "vector_count": total_vectors,
            "metadata_count": len(self._metadata),
            "filtered_metadata_count": len(self._active_metadata),
            "filtered_document_count": len(self._active_document_ids),
            "chunks_count": len(self._chunks),
            "embedding_provider": self.embedding_provider,
            "source_id": self.source_id,
            "active_snapshot": self._get_active_snapshot(),
            "category_stats": {
                cat: {"vectors": idx.ntotal, "metadata": len(self._metadata_by_category.get(cat, []))}
                for cat, idx in self._indexes.items()
            },
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
