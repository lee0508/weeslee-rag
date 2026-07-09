# Dataset Builder 단계별 설정 서비스
# 작업일: 2026-07-08 - DB 시스템 설정 연동 추가
from __future__ import annotations

import platform
from typing import Any

from app.services.platform_store import create_record, get_record, update_record

STORE_NAME = "dataset_build_settings"


def _get_db_setting(category: str, key: str, default):
    """DB 설정 조회 헬퍼. 실패 시 default 반환."""
    try:
        from app.services.system_settings_service import get_system_setting
        return get_system_setting(category, key, default)
    except Exception:
        return default


def _get_structured_txt_root() -> str:
    """DB에서 structured_txt_root 경로 조회. 플랫폼별 자동 선택."""
    if platform.system() == "Windows":
        fallback = r"C:\xampp\htdocs\weeslee-mnt\structured_txt"
    else:
        fallback = "/data/weeslee/weeslee-mnt/structured_txt"
    return _get_db_setting("path", "structured_txt_root", fallback)


def _get_structured_json_root() -> str:
    """DB에서 structured_json_root 경로 조회. 플랫폼별 자동 선택."""
    if platform.system() == "Windows":
        fallback = r"C:\xampp\htdocs\weeslee-mnt\structured_json"
    else:
        fallback = "/data/weeslee/weeslee-mnt/structured_json"
    return _get_db_setting("path", "structured_json_root", fallback)

def _get_default_step_configs() -> dict[str, Any]:
    """Step별 기본 설정값 생성. DB 설정 우선, 없으면 하드코딩 fallback."""
    return {
        "step3_config": {
            "extraction_rules": "default",
            "category_mapping": {},
            "use_structured_txt": True,
            "use_structured_json": True,
            "structured_txt_root": _get_structured_txt_root(),
            "structured_json_root": _get_structured_json_root(),
            "prefer_structured_content": True,
            "max_text_chars": _get_db_setting("rag", "max_text_chars", 12000),
        },
        "step4_config": {
            "ocr_engine": _get_db_setting("ocr", "ocr_engine", "tesseract"),
            "ocr_dpi": _get_db_setting("ocr", "ocr_dpi", 300),
            "ocr_language": _get_db_setting("ocr", "ocr_language", "kor+eng"),
            "ocr_mode": _get_db_setting("ocr", "ocr_mode", "auto"),
            "ocr_min_text_length": _get_db_setting("ocr", "ocr_min_text_length", 50),
        },
        "step5_config": {
            "llm_model": _get_db_setting("model", "step5_llm_model", "claude-3-5-sonnet"),
            "max_tags": 10,
            "max_keywords": 20,
            "use_ollama_fallback": True,
            "use_structured_txt": True,
            "use_structured_json": True,
            "structured_txt_root": _get_structured_txt_root(),
            "structured_json_root": _get_structured_json_root(),
            "prefer_structured_content": True,
            "max_text_chars": _get_db_setting("rag", "max_text_chars", 12000),
        },
        "step6_config": {
            "chunk_size": _get_db_setting("rag", "chunk_size", 512),
            "chunk_overlap": _get_db_setting("rag", "chunk_overlap", 50),
            "embedding_model": _get_db_setting("model", "step6_embedding_model", "ollama/nomic-embed-text"),
            "embedding_provider": "ollama",
        },
        "step7_config": {
            "ontology_id": "default",
            "graph_mode": "basic",
            "max_nodes": 1000,
        },
        "step8_config": {
            "llm_model": _get_db_setting("model", "step8_llm_model", "claude-3-5-sonnet"),
            "max_articles": 30,
            "temperature": _get_db_setting("llm", "temperature", 0.3),
        },
        "step10_config": {
            "index_type": "Flat",
            "use_gpu": True,
            "gpu_devices": "0",
        },
    }


# 하위 호환성을 위해 DEFAULT_STEP_CONFIGS 변수 유지 (lazy 초기화)
_cached_default_configs = None


def _get_cached_default_configs() -> dict[str, Any]:
    """캐시된 기본 설정 반환."""
    global _cached_default_configs
    if _cached_default_configs is None:
        _cached_default_configs = _get_default_step_configs()
    return _cached_default_configs


def get_dataset_build_settings(source_id: str) -> dict[str, Any]:
    """source_id에 해당하는 빌드 설정 조회. 없으면 기본값 반환."""
    default_configs = _get_default_step_configs()
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
            **default_configs,
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
        **default_configs,
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
    default_configs = _get_default_step_configs()
    return settings.get(config_key) or default_configs.get(config_key, {})


def is_step_enabled(source_id: str, step: str) -> bool:
    """특정 step이 활성화되어 있는지 확인."""
    settings = get_dataset_build_settings(source_id)
    enabled_key = f"step{step}_enabled"
    return bool(settings.get(enabled_key, True))
