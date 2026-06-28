# Document Source 기반 동적 카테고리 관리 서비스
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.platform_store import get_record


# 기본 카테고리 키 매핑 (디렉토리명 → 영문 키)
DEFAULT_CATEGORY_MAPPINGS = {
    # RFP 관련
    "rfp": "rfp",
    "01. rfp": "rfp",
    "제안요청서": "rfp",
    # 제안서 관련
    "제안서": "proposal",
    "02. 제안서": "proposal",
    "proposal": "proposal",
    # 산출물 관련
    "산출물": "deliverable",
    "03. 산출물": "deliverable",
    "deliverable": "deliverable",
    "최종보고서": "deliverable",
}


def normalize_category_key(dir_name: str) -> str:
    """디렉토리명에서 카테고리 키 추출."""
    name_lower = dir_name.lower().strip()

    # 정확한 매핑 먼저 확인
    if name_lower in DEFAULT_CATEGORY_MAPPINGS:
        return DEFAULT_CATEGORY_MAPPINGS[name_lower]

    # 번호 접두사 제거 후 확인 (예: "01. RFP" → "RFP")
    stripped = re.sub(r"^\d+\.\s*", "", name_lower).strip()
    if stripped in DEFAULT_CATEGORY_MAPPINGS:
        return DEFAULT_CATEGORY_MAPPINGS[stripped]

    # 알려진 키워드 포함 여부 확인
    for keyword, key in DEFAULT_CATEGORY_MAPPINGS.items():
        if keyword in name_lower:
            return key

    # 매칭 안 되면 원본 이름을 소문자로 반환
    return stripped or name_lower


def detect_categories_from_directory(root_path: str) -> list[dict[str, str]]:
    """루트 경로의 1단계 하위 디렉토리에서 카테고리 자동 감지."""
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        return []

    categories = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue

        dir_name = child.name
        key = normalize_category_key(dir_name)

        categories.append({
            "path": dir_name,
            "name": re.sub(r"^\d+\.\s*", "", dir_name).strip() or dir_name,
            "key": key,
        })

    return categories


def get_source_categories(source_id: str) -> list[dict[str, str]]:
    """Document Source의 카테고리 설정 조회."""
    source = get_record("document_sources", "source_id", source_id)
    if not source:
        return []

    config = source.get("category_config") or {}
    return config.get("categories", [])


def get_category_keys(source_id: str) -> list[str]:
    """Document Source의 카테고리 키 목록 반환."""
    categories = get_source_categories(source_id)
    return [cat.get("key", "") for cat in categories if cat.get("key")]


def get_category_key_from_path(source_id: str, file_path: str) -> str:
    """파일 경로에서 카테고리 키 추출."""
    categories = get_source_categories(source_id)
    if not categories:
        return ""

    path_lower = file_path.lower()

    for cat in categories:
        cat_path = cat.get("path", "")
        cat_key = cat.get("key", "")
        if cat_path and cat_path.lower() in path_lower:
            return cat_key

    return ""


def build_category_map(source_id: str) -> dict[str, str]:
    """한글/경로명 → 영문 키 매핑 딕셔너리 생성."""
    categories = get_source_categories(source_id)
    mapping = {}

    for cat in categories:
        path = cat.get("path", "")
        name = cat.get("name", "")
        key = cat.get("key", "")

        if path:
            mapping[path] = key
            mapping[path.lower()] = key
        if name:
            mapping[name] = key
            mapping[name.lower()] = key
        if key:
            mapping[key] = key

    # 기본 매핑도 포함
    mapping.update(DEFAULT_CATEGORY_MAPPINGS)

    return mapping
