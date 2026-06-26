# -*- coding: utf-8 -*-
# Qdrant 벡터 저장소 어댑터 - QA2 vectorstore.py 기반
"""
Qdrant Vector Store Adapter
- 청크 벡터 + 메타데이터를 upsert (멱등 저장)
- source_id / page 등 메타데이터 필터링 검색 지원
- chunk_id를 포인트 ID로 사용 → 재처리 시 중복 없이 갱신
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.services.embedding_adapters import BaseEmbedder, get_embedder
from app.services.page_aware_chunking import PageAwareChunk

logger = logging.getLogger(__name__)


# Qdrant client import with fallback
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams, PointStruct,
        Filter, FieldCondition, MatchValue,
    )
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False
    QdrantClient = None


class QdrantStoreConfig:
    """Qdrant 연결 설정"""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection: str = "documents",
        location: str = "url",  # "url" | "memory"
    ):
        self.url = url
        self.collection = collection
        self.location = location

    @classmethod
    def from_settings(cls) -> "QdrantStoreConfig":
        """settings에서 Qdrant 설정 로드"""
        return cls(
            url=getattr(settings, "qdrant_url", "http://localhost:6333"),
            collection=getattr(settings, "qdrant_collection", "documents"),
            location=getattr(settings, "qdrant_location", "url"),
        )


class QdrantStore:
    """Qdrant 벡터 저장소 래퍼"""

    def __init__(
        self,
        embedder: BaseEmbedder,
        config: Optional[QdrantStoreConfig] = None,
    ):
        if not HAS_QDRANT:
            raise ImportError(
                "qdrant-client가 필요합니다. pip install qdrant-client"
            )

        self.config = config or QdrantStoreConfig.from_settings()
        self.embedder = embedder
        self.collection = self.config.collection

        # 연결 모드: 운영(url) vs 테스트(memory)
        if self.config.location == "memory":
            self.client = QdrantClient(location=":memory:")
            logger.info("Qdrant: 인메모리 모드 (테스트용)")
        else:
            self.client = QdrantClient(url=self.config.url)
            logger.info(f"Qdrant 연결: {self.config.url}")

        self._ensure_collection()

    def _ensure_collection(self):
        """컬렉션이 없으면 생성 (벡터 차원 = 임베더 차원)"""
        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection not in existing:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=self.embedder.dim,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Qdrant 컬렉션 생성: {self.collection} (dim={self.embedder.dim})")

    def upsert_chunks(self, chunks: List[PageAwareChunk]) -> int:
        """
        청크들을 임베딩하여 Qdrant에 upsert한다.
        - chunk_id를 포인트 ID로 사용 → 재처리 시 중복 없이 갱신(멱등)

        Args:
            chunks: 저장할 청크 리스트

        Returns:
            저장된 청크 수
        """
        if not chunks:
            return 0

        # 1) 배치 임베딩
        texts = [c.text for c in chunks]
        vectors = self.embedder.embed_texts(texts)

        # 2) 포인트 구성 (벡터 + payload)
        points = []
        for chunk, vector in zip(chunks, vectors):
            payload = dict(chunk.metadata)
            payload["text"] = chunk.text  # 본문도 저장 (검색 결과 표시용)
            points.append(PointStruct(
                id=chunk.chunk_id,  # uuid를 포인트 ID로
                vector=vector,
                payload=payload,
            ))

        # 3) upsert
        self.client.upsert(collection_name=self.collection, points=points)
        logger.info(f"Qdrant upsert 완료: {len(points)}개 청크")
        return len(points)

    def upsert_raw(
        self,
        ids: List[str],
        texts: List[str],
        vectors: List[List[float]],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        원시 데이터를 직접 upsert (이미 임베딩된 경우)

        Args:
            ids: 포인트 ID 리스트
            texts: 텍스트 리스트
            vectors: 임베딩 벡터 리스트
            metadatas: 메타데이터 리스트

        Returns:
            저장된 포인트 수
        """
        if not ids:
            return 0

        metadatas = metadatas or [{}] * len(ids)

        points = []
        for id_, text, vector, meta in zip(ids, texts, vectors, metadatas):
            payload = dict(meta)
            payload["text"] = text
            points.append(PointStruct(
                id=id_,
                vector=vector,
                payload=payload,
            ))

        self.client.upsert(collection_name=self.collection, points=points)
        return len(points)

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_id: Optional[str] = None,
        page: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        의미 검색 + 메타데이터 필터링.

        Args:
            query: 검색 질의
            top_k: 반환 개수
            source_id: 특정 source로 한정 (선택)
            page: 특정 페이지로 한정 (선택)
            filters: 추가 필터 조건 {"key": "value"}

        Returns:
            검색 결과 리스트 [{score, text, metadata}]
        """
        query_vec = self.embedder.embed_query(query)

        # 메타데이터 필터 구성
        conditions = []
        if source_id is not None:
            conditions.append(FieldCondition(
                key="source_id", match=MatchValue(value=source_id)
            ))
        if page is not None:
            conditions.append(FieldCondition(
                key="page", match=MatchValue(value=page)
            ))
        if filters:
            for key, value in filters.items():
                conditions.append(FieldCondition(
                    key=key, match=MatchValue(value=value)
                ))

        query_filter = Filter(must=conditions) if conditions else None

        # qdrant-client 1.10+ : query_points 사용
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vec,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )
        hits = response.points

        results = []
        for h in hits:
            payload = dict(h.payload)
            text = payload.pop("text", "")
            results.append({
                "score": h.score,
                "text": text,
                "metadata": payload,
            })
        return results

    def search_by_vector(
        self,
        vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        이미 임베딩된 벡터로 검색

        Args:
            vector: 임베딩 벡터
            top_k: 반환 개수
            filters: 필터 조건

        Returns:
            검색 결과 리스트
        """
        conditions = []
        if filters:
            for key, value in filters.items():
                conditions.append(FieldCondition(
                    key=key, match=MatchValue(value=value)
                ))

        query_filter = Filter(must=conditions) if conditions else None

        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )

        results = []
        for h in response.points:
            payload = dict(h.payload)
            text = payload.pop("text", "")
            results.append({
                "score": h.score,
                "text": text,
                "metadata": payload,
            })
        return results

    def count(self) -> int:
        """저장된 포인트 수"""
        return self.client.count(collection_name=self.collection).count

    def get_chunks_by_source(
        self,
        source_id: str,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        특정 source의 모든 청크를 조회한다 (Layer 3 입력으로 사용).
        - 검색이 아닌 스크롤(scroll)로 전체 조회
        """
        records, _ = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(must=[
                FieldCondition(key="source_id", match=MatchValue(value=source_id))
            ]),
            limit=limit,
            with_payload=True,
        )

        results = []
        for r in records:
            payload = dict(r.payload)
            text = payload.pop("text", "")
            results.append({"text": text, "metadata": payload})

        # 청크 순서 보장 (chunk_index 정렬)
        results.sort(key=lambda x: x["metadata"].get("chunk_index", 0))
        return results

    def get_chunks_by_file(
        self,
        file_id: str,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """특정 파일의 모든 청크를 조회한다."""
        records, _ = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(must=[
                FieldCondition(key="file_id", match=MatchValue(value=file_id))
            ]),
            limit=limit,
            with_payload=True,
        )

        results = []
        for r in records:
            payload = dict(r.payload)
            text = payload.pop("text", "")
            results.append({"text": text, "metadata": payload})

        results.sort(key=lambda x: x["metadata"].get("chunk_index", 0))
        return results

    def delete_by_source(self, source_id: str) -> int:
        """특정 source의 모든 청크를 삭제한다."""
        # 먼저 삭제할 포인트 ID를 수집
        records, _ = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(must=[
                FieldCondition(key="source_id", match=MatchValue(value=source_id))
            ]),
            limit=10000,
            with_payload=False,
        )

        if not records:
            return 0

        ids = [r.id for r in records]
        self.client.delete(
            collection_name=self.collection,
            points_selector=ids,
        )
        logger.info(f"Qdrant 삭제 완료: source_id={source_id}, {len(ids)}개")
        return len(ids)

    def delete_by_file(self, file_id: str) -> int:
        """특정 파일의 모든 청크를 삭제한다."""
        records, _ = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(must=[
                FieldCondition(key="file_id", match=MatchValue(value=file_id))
            ]),
            limit=10000,
            with_payload=False,
        )

        if not records:
            return 0

        ids = [r.id for r in records]
        self.client.delete(
            collection_name=self.collection,
            points_selector=ids,
        )
        logger.info(f"Qdrant 삭제 완료: file_id={file_id}, {len(ids)}개")
        return len(ids)

    def get_collection_info(self) -> Dict[str, Any]:
        """컬렉션 정보 조회"""
        info = self.client.get_collection(collection_name=self.collection)
        return {
            "name": self.collection,
            "points_count": info.points_count,
            "vectors_count": info.vectors_count,
            "indexed_vectors_count": info.indexed_vectors_count,
            "status": info.status.name if info.status else "unknown",
        }


# 싱글톤 인스턴스 (지연 생성)
_qdrant_store: Optional[QdrantStore] = None


def get_qdrant_store(
    embedder: Optional[BaseEmbedder] = None,
    config: Optional[QdrantStoreConfig] = None,
) -> QdrantStore:
    """Qdrant 스토어 인스턴스 반환"""
    global _qdrant_store
    if _qdrant_store is None:
        emb = embedder or get_embedder()
        _qdrant_store = QdrantStore(embedder=emb, config=config)
    return _qdrant_store
