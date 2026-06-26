# -*- coding: utf-8 -*-
# 임베딩 어댑터 계층 - QA2 embedder.py 기반
"""
Embedding Adapters (Adapter Pattern)
- BGE-M3 (온프레미스, 한국어 우수)
- OpenAI (API)
- Ollama (기존 호환)
- Fake (테스트용)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class BaseEmbedder(ABC):
    """임베딩 엔진 공통 인터페이스"""

    @property
    @abstractmethod
    def dim(self) -> int:
        """임베딩 차원"""
        raise NotImplementedError

    @abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """여러 텍스트를 임베딩 (배치)"""
        raise NotImplementedError

    def embed_query(self, text: str) -> List[float]:
        """단일 질의 임베딩 (검색용)"""
        return self.embed_texts([text])[0]


class BGEM3Embedder(BaseEmbedder):
    """
    sentence-transformers 기반 BGE-M3 임베더
    - 한국어에 최적화된 다국어 임베딩 모델
    - 1024차원, 코사인 유사도 안정화
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        normalize: bool = True,
        batch_size: int = 32,
    ):
        self.model_name = model_name
        self.normalize = normalize
        self.batch_size = batch_size
        self._model = None
        self._dim = 1024  # bge-m3 기본 차원

    def _ensure_loaded(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
                # 실제 차원으로 갱신
                self._dim = self._model.get_sentence_embedding_dimension()
                logger.info(f"BGE-M3 모델 로드 완료: {self.model_name}, dim={self._dim}")
            except ImportError:
                raise ImportError(
                    "sentence-transformers가 필요합니다. "
                    "pip install sentence-transformers"
                )

    @property
    def dim(self) -> int:
        return self._dim

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        self._ensure_loaded()
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,  # 코사인 유사도 안정화
            show_progress_bar=False,
        )
        return vectors.tolist()


class OpenAIEmbedder(BaseEmbedder):
    """OpenAI 임베딩 API (text-embedding-3-large 등)"""

    def __init__(self, model: str = "text-embedding-3-large"):
        self.model = model
        self._dim = 3072  # 3-large 기준

    @property
    def dim(self) -> int:
        return self._dim

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 패키지가 필요합니다. pip install openai")

        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]


class OllamaEmbedder(BaseEmbedder):
    """Ollama 임베딩 (기존 시스템 호환용)"""

    def __init__(
        self,
        model: str = None,
        host: str = None,
    ):
        self.model = model or settings.ollama_embed_model
        self.host = host or settings.ollama_host
        self._dim = settings.embedding_dim or 768

    @property
    def dim(self) -> int:
        return self._dim

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        import httpx

        vectors = []
        for text in texts:
            resp = httpx.post(
                f"{self.host.rstrip('/')}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=60.0,
            )
            resp.raise_for_status()
            vectors.append(resp.json()["embedding"])
        return vectors


class FakeEmbedder(BaseEmbedder):
    """
    테스트용 임베더 - 외부 의존성 없이 동작
    - 텍스트 해시를 시드로 한 결정론적 벡터 생성
    - 같은 텍스트 → 같은 벡터 (검색 동작 검증 가능)
    """

    def __init__(self, dim: int = 64):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        import hashlib

        vectors = []
        for t in texts:
            # 텍스트 해시를 시드로 의사난수 벡터 생성
            seed = int(hashlib.sha256(t.encode("utf-8")).hexdigest()[:8], 16)
            rng = _SimpleRNG(seed)
            v = [rng.next_float() for _ in range(self._dim)]
            # L2 정규화
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            vectors.append([x / norm for x in v])
        return vectors


class _SimpleRNG:
    """의존성 없는 결정론적 난수 생성기 (LCG)"""

    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF

    def next_float(self) -> float:
        self.state = (1103515245 * self.state + 12345) & 0x7FFFFFFF
        return (self.state / 0x7FFFFFFF) * 2 - 1  # [-1, 1]


def get_embedder(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs,
) -> BaseEmbedder:
    """
    설정에 따라 임베더 인스턴스를 반환

    Args:
        provider: 임베딩 제공자 (bge-m3, openai, ollama, fake)
        model: 모델 이름 (제공자별로 다름)
        **kwargs: 추가 옵션

    Returns:
        BaseEmbedder 인스턴스
    """
    provider = (provider or settings.embedding_provider).lower()

    if provider == "bge-m3":
        return BGEM3Embedder(
            model_name=model or "BAAI/bge-m3",
            normalize=kwargs.get("normalize", True),
            batch_size=kwargs.get("batch_size", 32),
        )
    elif provider == "openai":
        return OpenAIEmbedder(
            model=model or "text-embedding-3-large",
        )
    elif provider == "ollama":
        return OllamaEmbedder(
            model=model or settings.ollama_embed_model,
            host=kwargs.get("host", settings.ollama_host),
        )
    elif provider == "fake":
        return FakeEmbedder(
            dim=kwargs.get("dim", 64),
        )
    else:
        raise ValueError(f"지원하지 않는 임베딩 provider: {provider}")


# 싱글톤 인스턴스 (설정 기반)
_default_embedder: Optional[BaseEmbedder] = None


def get_default_embedder() -> BaseEmbedder:
    """기본 임베더 인스턴스 반환 (싱글톤)"""
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = get_embedder()
    return _default_embedder
