# entity_mappings.json 로드 및 접근 유틸리티
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_MAPPINGS_PATH = Path(__file__).parent / "entity_mappings.json"


@lru_cache(maxsize=1)
def _load_mappings() -> dict[str, Any]:
    """entity_mappings.json 파일을 로드하여 캐싱한다."""
    if not _MAPPINGS_PATH.exists():
        raise FileNotFoundError(f"Mappings file not found: {_MAPPINGS_PATH}")
    return json.loads(_MAPPINGS_PATH.read_text(encoding="utf-8"))


def get_mapping(key: str) -> dict[str, Any]:
    """지정된 키의 매핑 딕셔너리를 반환한다."""
    mappings = _load_mappings()
    if key not in mappings:
        raise KeyError(f"Mapping key not found: {key}")
    result = mappings[key]
    # _description 등 메타 필드 제거
    if isinstance(result, dict):
        return {k: v for k, v in result.items() if not k.startswith("_")}
    return result


def get_list(key: str) -> list[str]:
    """지정된 키의 리스트를 반환한다."""
    mappings = _load_mappings()
    if key not in mappings:
        raise KeyError(f"Mapping key not found: {key}")
    return mappings[key]


# 자주 사용하는 매핑들을 모듈 레벨에서 lazy 로딩
class _LazyMappings:
    """지연 로딩으로 매핑을 제공하는 클래스."""

    @property
    def SOURCE_ID_MAP(self) -> dict[str, str]:
        return get_mapping("source_id_map")

    @property
    def DOCUMENT_GROUP_MAP(self) -> dict[str, str]:
        return get_mapping("document_group_map")

    @property
    def CATEGORY_ID_MAP(self) -> dict[str, str]:
        return get_mapping("category_id_map")

    @property
    def DOCUMENT_CATEGORY_ORDER(self) -> dict[str, int]:
        return get_mapping("document_category_order")

    @property
    def SUPPORTED_EXTENSIONS(self) -> set[str]:
        return set(get_mapping("supported_extensions").get("indexable", []))

    @property
    def COLLECTION_CATEGORY_MAP(self) -> dict[str, str]:
        return get_mapping("collection_category_map")

    @property
    def CATEGORY_SUFFIXES(self) -> list[str]:
        return get_list("category_suffixes")


# 싱글톤 인스턴스
mappings = _LazyMappings()


def reload_mappings() -> None:
    """캐시를 무효화하고 매핑을 다시 로드한다."""
    _load_mappings.cache_clear()
