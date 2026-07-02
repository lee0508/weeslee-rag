# Dataset Builder 단계별 설정 서비스
from __future__ import annotations

from typing import Any

from app.services.platform_store import create_record, get_record, update_record

STORE_NAME = "dataset_build_settings"

# Step별 기본 설정값
DEFAULT_STEP_CONFIGS: dict[str, Any] = {
    "step3_config": {
        "extraction_rules": "default",
        "category_mapping": {},
    },
    "step4_config": {
        "ocr_engine": "tesseract",
        "ocr_dpi": 300,
        "ocr_language": "kor+eng",
        "ocr_mode": "auto",
        "ocr_min_text_length": 50,
    },
    "step5_config": {
        "llm_model": "claude-3-5-sonnet",
        "max_tags": 10,
        "max_keywords": 20,
        "use_ollama_fallback": True,
    },
    "step6_config": {
        "chunk_size": 512,
        "chunk_overlap": 50,
        "embedding_model": "ollama/nomic-embed-text",
        "embedding_provider": "ollama",
    },
    "step7_config": {
        "ontology_id": "default",
        "graph_mode": "basic",
        "max_nodes": 1000,
    },
    "step8_config": {
        "llm_model": "claude-3-5-sonnet",
        "max_articles": 30,
        "temperature": 0.3,
    },
    "step10_config": {
        "index_type": "Flat",
        "use_gpu": True,
        "gpu_devices": "0",
    },
}


def get_dataset_build_settings(source_id: str) -> dict[str, Any]:
    """source_id에 해당하는 빌드 설정 조회. 없으면 기본값 반환."""
    saved = get_record(STORE_NAME, "source_id", source_id)
    if not saved:
        return {
            "source_id": source_id,
            "step3_enabled": True,
            "step4_enabled": True,
            "step5_enabled": True,
            "step6_enabled": True,
            "step7_enabled": True,
            "step8_enabled": True,
            "step10_enabled": True,
            **DEFAULT_STEP_CONFIGS,
        }

    # 저장된 설정에 기본값 병합
    result = {
        "source_id": source_id,
        "step3_enabled": True,
        "step4_enabled": True,
        "step5_enabled": True,
        "step6_enabled": True,
        "step7_enabled": True,
        "step8_enabled": True,
        "step10_enabled": True,
        **DEFAULT_STEP_CONFIGS,
        **saved,
    }
    return result


def save_dataset_build_settings(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """source_id에 해당하는 빌드 설정 저장."""
    current = get_record(STORE_NAME, "source_id", source_id)
    merged = {
        **(current or {}),
        **payload,
        "source_id": source_id,
    }

    if current:
        return update_record(STORE_NAME, "source_id", source_id, merged) or merged
    return create_record(STORE_NAME, merged, "source_id")


def get_step_config(source_id: str, step: str) -> dict[str, Any]:
    """특정 step의 설정만 조회."""
    settings = get_dataset_build_settings(source_id)
    config_key = f"step{step}_config"
    return settings.get(config_key) or DEFAULT_STEP_CONFIGS.get(config_key, {})


def is_step_enabled(source_id: str, step: str) -> bool:
    """특정 step이 활성화되어 있는지 확인."""
    settings = get_dataset_build_settings(source_id)
    enabled_key = f"step{step}_enabled"
    return bool(settings.get(enabled_key, True))
