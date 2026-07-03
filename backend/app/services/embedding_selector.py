# 임베딩 모델 선택 서비스 - 환경에 따라 최적 모델 자동 선택
"""
임베딩 모델 선택 서비스.

주요 기능:
  - get_recommended_model(): 환경에 따라 최적 모델 반환
  - get_embedding_dim(): 모델별 임베딩 차원 반환
  - is_gpu_available(): GPU 사용 가능 여부 확인

사용 예시:
    from app.services.embedding_selector import get_recommended_model, get_embedding_dim

    model = get_recommended_model()  # "bge-m3" or "nomic-embed-text"
    dim = get_embedding_dim(model)   # 1024 or 768
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Optional

from app.core.config import settings


class EmbeddingProvider(str, Enum):
    """임베딩 제공자."""
    OLLAMA = "ollama"
    SENTENCE_TRANSFORMERS = "sentence_transformers"
    OPENAI = "openai"


class EmbeddingModel(str, Enum):
    """지원되는 임베딩 모델."""
    # Ollama 모델
    BGE_M3 = "bge-m3"  # 1024D, 한국어 우수, GPU 권장
    NOMIC_EMBED = "nomic-embed-text"  # 768D, 범용, CPU OK

    # Sentence Transformers 모델
    BGE_M3_HF = "BAAI/bge-m3"  # HuggingFace, 1024D
    MINI_LM = "paraphrase-multilingual-MiniLM-L12-v2"  # 384D, 매우 빠름

    # OpenAI 모델
    TEXT_EMBEDDING_3_SMALL = "text-embedding-3-small"  # 1536D
    TEXT_EMBEDDING_3_LARGE = "text-embedding-3-large"  # 3072D


# 모델별 임베딩 차원
EMBEDDING_DIMS = {
    # Ollama
    "bge-m3": 1024,
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "snowflake-arctic-embed": 1024,
    "all-minilm": 384,

    # Sentence Transformers
    "BAAI/bge-m3": 1024,
    "paraphrase-multilingual-MiniLM-L12-v2": 384,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "intfloat/multilingual-e5-large": 1024,

    # OpenAI
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


@lru_cache(maxsize=1)
def is_gpu_available() -> bool:
    """GPU(CUDA) 사용 가능 여부 확인."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


@lru_cache(maxsize=1)
def get_gpu_name() -> Optional[str]:
    """GPU 이름 반환 (없으면 None)."""
    if not is_gpu_available():
        return None
    try:
        import torch
        return torch.cuda.get_device_name(0)
    except Exception:
        return None


def get_recommended_model(
    provider: Optional[str] = None,
    prefer_quality: bool = True,
) -> str:
    """
    환경에 따라 추천 임베딩 모델 반환.

    Args:
        provider: 사용할 제공자 (None이면 설정값 사용)
        prefer_quality: True면 품질 우선, False면 속도 우선

    Returns:
        추천 모델명
    """
    provider = provider or getattr(settings, "embedding_provider", "ollama")

    if provider == "ollama":
        # 현재 Ollama에서 bge-m3가 설치되어 있고 잘 동작하므로 기본 사용
        ollama_model = getattr(settings, "ollama_embed_model", None)
        if ollama_model:
            return ollama_model

        # GPU 있으면 bge-m3, 없으면 nomic-embed-text
        if is_gpu_available() and prefer_quality:
            return EmbeddingModel.BGE_M3.value
        else:
            # CPU에서도 bge-m3가 동작하지만 느릴 수 있음
            # 현재 서버는 bge-m3 사용 중이므로 유지
            return getattr(settings, "ollama_embed_model", "bge-m3")

    elif provider == "sentence_transformers":
        if is_gpu_available() and prefer_quality:
            return EmbeddingModel.BGE_M3_HF.value
        else:
            return EmbeddingModel.MINI_LM.value

    elif provider == "openai":
        if prefer_quality:
            return EmbeddingModel.TEXT_EMBEDDING_3_LARGE.value
        else:
            return EmbeddingModel.TEXT_EMBEDDING_3_SMALL.value

    # 기본값
    return EmbeddingModel.BGE_M3.value


def get_embedding_dim(model_name: str) -> int:
    """
    모델별 임베딩 차원 반환.

    Args:
        model_name: 모델명

    Returns:
        임베딩 차원 (알 수 없으면 settings 기본값)
    """
    # 설정에서 명시된 차원이 있으면 우선 사용
    config_dim = getattr(settings, "embedding_dim", None)

    # 알려진 모델의 차원 반환
    if model_name in EMBEDDING_DIMS:
        return EMBEDDING_DIMS[model_name]

    # 부분 매칭 시도
    for key, dim in EMBEDDING_DIMS.items():
        if key in model_name or model_name in key:
            return dim

    # 설정값 또는 기본값
    return config_dim or 1024


def get_model_info(model_name: str) -> dict:
    """
    모델 상세 정보 반환.

    Args:
        model_name: 모델명

    Returns:
        모델 정보 딕셔너리
    """
    dim = get_embedding_dim(model_name)

    # 제공자 추정
    if model_name.startswith("text-embedding"):
        provider = "openai"
    elif "/" in model_name:
        provider = "sentence_transformers"
    else:
        provider = "ollama"

    # 한국어 지원 수준
    korean_support = "excellent" if "bge" in model_name.lower() else "good"

    # GPU 필요 여부
    gpu_required = dim >= 1024 and provider != "openai"

    return {
        "model_name": model_name,
        "provider": provider,
        "embedding_dim": dim,
        "korean_support": korean_support,
        "gpu_recommended": gpu_required,
        "gpu_available": is_gpu_available(),
        "gpu_name": get_gpu_name(),
    }


def list_available_models(provider: Optional[str] = None) -> list[dict]:
    """
    사용 가능한 모델 목록 반환.

    Args:
        provider: 필터링할 제공자 (None이면 전체)

    Returns:
        모델 정보 목록
    """
    models = []

    for model_name, dim in EMBEDDING_DIMS.items():
        info = get_model_info(model_name)

        if provider and info["provider"] != provider:
            continue

        models.append(info)

    # 차원 내림차순 정렬
    return sorted(models, key=lambda x: x["embedding_dim"], reverse=True)


def validate_model_compatibility(
    model_name: str,
    existing_dim: Optional[int] = None,
) -> dict:
    """
    모델 호환성 검증.

    Args:
        model_name: 확인할 모델명
        existing_dim: 기존 인덱스의 차원 (None이면 검증 안함)

    Returns:
        검증 결과 딕셔너리
    """
    model_dim = get_embedding_dim(model_name)

    compatible = True
    warnings = []
    errors = []

    # 차원 불일치 확인
    if existing_dim and existing_dim != model_dim:
        compatible = False
        errors.append(
            f"차원 불일치: 모델={model_dim}D, 기존 인덱스={existing_dim}D. "
            f"인덱스를 재생성해야 합니다."
        )

    # GPU 권장 모델인데 GPU 없음
    info = get_model_info(model_name)
    if info["gpu_recommended"] and not is_gpu_available():
        warnings.append(
            "이 모델은 GPU 사용이 권장됩니다. "
            "CPU 모드에서는 속도가 느릴 수 있습니다."
        )

    return {
        "model_name": model_name,
        "model_dim": model_dim,
        "existing_dim": existing_dim,
        "compatible": compatible,
        "warnings": warnings,
        "errors": errors,
        "info": info,
    }
