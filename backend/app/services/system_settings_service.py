# 시스템 설정 서비스 - DB 기반 설정값 관리
# 작업일: 2026-07-08
# 작성자: Claude
"""
SystemSettingsService: 하드코딩된 설정값을 DB에서 관리하기 위한 서비스.

주요 기능:
- 카테고리별 설정값 조회
- 플랫폼(Windows/Linux)별 설정값 자동 선택
- 설정값 수정 및 저장
- 캐싱을 통한 성능 최적화
"""
from __future__ import annotations

import json
import platform
from datetime import datetime
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy import text

from app.core.database import engine


# 캐시 TTL (초) - 설정값 변경 시 캐시 무효화 필요
_CACHE_TTL_SECONDS = 300

# 현재 플랫폼
_CURRENT_PLATFORM = "windows" if platform.system() == "Windows" else "linux"


class SystemSettingsService:
    """시스템 설정 서비스."""

    def __init__(self):
        self._cache: dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None

    def _is_cache_valid(self) -> bool:
        """캐시 유효성 확인."""
        if not self._cache_time:
            return False
        elapsed = (datetime.now() - self._cache_time).total_seconds()
        return elapsed < _CACHE_TTL_SECONDS

    def _invalidate_cache(self):
        """캐시 무효화."""
        self._cache.clear()
        self._cache_time = None

    def _convert_value(self, value: str, value_type: str) -> Any:
        """문자열 값을 지정된 타입으로 변환."""
        if value is None:
            return None

        try:
            if value_type == "int":
                return int(value)
            elif value_type == "float":
                return float(value)
            elif value_type == "bool":
                return value.lower() in ("true", "1", "yes", "on")
            elif value_type == "json":
                return json.loads(value)
            elif value_type == "list":
                return json.loads(value) if value.startswith("[") else value.split(",")
            else:
                return value
        except (ValueError, json.JSONDecodeError):
            return value

    def _serialize_value(self, value: Any, value_type: str) -> str:
        """값을 문자열로 직렬화."""
        if value is None:
            return ""

        if value_type in ("json", "list"):
            return json.dumps(value, ensure_ascii=False)
        elif value_type == "bool":
            return "true" if value else "false"
        else:
            return str(value)

    def get_all_settings(self, include_sensitive: bool = False) -> dict[str, dict[str, Any]]:
        """
        전체 설정값 조회 (카테고리별 그룹).

        Returns:
            {
                "path": {"structured_txt_root": "/data/...", ...},
                "endpoint": {"ollama_host": "http://...", ...},
                ...
            }
        """
        if self._is_cache_valid() and "all" in self._cache:
            return self._cache["all"]

        result: dict[str, dict[str, Any]] = {}

        with engine.connect() as conn:
            # 플랫폼별 설정: 현재 플랫폼 또는 'all'인 것만 조회
            query = text("""
                SELECT category, setting_key, setting_value, value_type,
                       description, is_sensitive, platform, requires_restart,
                       editable, display_order
                FROM system_settings
                WHERE platform IN ('all', :platform)
                ORDER BY category, display_order, setting_key
            """)

            rows = conn.execute(query, {"platform": _CURRENT_PLATFORM}).fetchall()

            for row in rows:
                category = row[0]
                key = row[1]
                value = row[2]
                value_type = row[3]
                is_sensitive = row[5]

                if category not in result:
                    result[category] = {}

                # 민감 정보는 마스킹 (include_sensitive=False인 경우)
                if is_sensitive and not include_sensitive:
                    converted_value = "********"
                else:
                    converted_value = self._convert_value(value, value_type)

                result[category][key] = converted_value

        self._cache["all"] = result
        self._cache_time = datetime.now()
        return result

    def get_category_settings(self, category: str) -> dict[str, Any]:
        """
        특정 카테고리의 설정값 조회.

        Args:
            category: 카테고리명 (path, endpoint, model, rag, llm, search, ocr, security)

        Returns:
            {"setting_key": value, ...}
        """
        cache_key = f"category_{category}"
        if self._is_cache_valid() and cache_key in self._cache:
            return self._cache[cache_key]

        result: dict[str, Any] = {}

        with engine.connect() as conn:
            query = text("""
                SELECT setting_key, setting_value, value_type
                FROM system_settings
                WHERE category = :category
                  AND platform IN ('all', :platform)
                ORDER BY display_order, setting_key
            """)

            rows = conn.execute(query, {
                "category": category,
                "platform": _CURRENT_PLATFORM
            }).fetchall()

            for row in rows:
                key = row[0]
                value = row[1]
                value_type = row[2]
                result[key] = self._convert_value(value, value_type)

        self._cache[cache_key] = result
        return result

    def get_setting(self, category: str, key: str, default: Any = None) -> Any:
        """
        단일 설정값 조회.

        Args:
            category: 카테고리명
            key: 설정 키
            default: 기본값 (설정이 없을 때)

        Returns:
            설정값 또는 기본값
        """
        cache_key = f"single_{category}_{key}"
        if self._is_cache_valid() and cache_key in self._cache:
            return self._cache[cache_key]

        with engine.connect() as conn:
            query = text("""
                SELECT setting_value, value_type
                FROM system_settings
                WHERE category = :category
                  AND setting_key = :key
                  AND platform IN ('all', :platform)
                ORDER BY CASE WHEN platform = :platform THEN 0 ELSE 1 END
                LIMIT 1
            """)

            row = conn.execute(query, {
                "category": category,
                "key": key,
                "platform": _CURRENT_PLATFORM
            }).fetchone()

            if row:
                value = self._convert_value(row[0], row[1])
                self._cache[cache_key] = value
                return value

        return default

    def set_setting(self, category: str, key: str, value: Any,
                    platform_specific: Optional[str] = None) -> bool:
        """
        설정값 수정.

        Args:
            category: 카테고리명
            key: 설정 키
            value: 새 값
            platform_specific: 특정 플랫폼에만 적용 (None이면 현재 플랫폼 또는 'all')

        Returns:
            성공 여부
        """
        target_platform = platform_specific or _CURRENT_PLATFORM

        with engine.connect() as conn:
            # 기존 설정의 value_type 조회
            query = text("""
                SELECT value_type
                FROM system_settings
                WHERE category = :category
                  AND setting_key = :key
                  AND platform = :platform
                LIMIT 1
            """)

            row = conn.execute(query, {
                "category": category,
                "key": key,
                "platform": target_platform
            }).fetchone()

            if not row:
                # 'all' 플랫폼에서 찾기
                row = conn.execute(query, {
                    "category": category,
                    "key": key,
                    "platform": "all"
                }).fetchone()

            if not row:
                return False

            value_type = row[0]
            serialized_value = self._serialize_value(value, value_type)

            # 업데이트 실행
            update_query = text("""
                UPDATE system_settings
                SET setting_value = :value,
                    updated_at = NOW()
                WHERE category = :category
                  AND setting_key = :key
                  AND platform = :platform
            """)

            result = conn.execute(update_query, {
                "value": serialized_value,
                "category": category,
                "key": key,
                "platform": target_platform if row else "all"
            })
            conn.commit()

            # 캐시 무효화
            self._invalidate_cache()

            return result.rowcount > 0

    def bulk_update(self, updates: list[dict[str, Any]]) -> dict[str, Any]:
        """
        일괄 설정 업데이트.

        Args:
            updates: [{"category": "...", "key": "...", "value": ...}, ...]

        Returns:
            {"success": int, "failed": int, "errors": [...]}
        """
        success = 0
        failed = 0
        errors = []

        for item in updates:
            try:
                category = item.get("category")
                key = item.get("key")
                value = item.get("value")
                platform_specific = item.get("platform")

                if self.set_setting(category, key, value, platform_specific):
                    success += 1
                else:
                    failed += 1
                    errors.append(f"{category}.{key}: 설정을 찾을 수 없음")
            except Exception as e:
                failed += 1
                errors.append(f"{item}: {str(e)}")

        return {
            "success": success,
            "failed": failed,
            "errors": errors
        }

    def get_settings_metadata(self, category: Optional[str] = None) -> list[dict[str, Any]]:
        """
        설정 메타데이터 조회 (UI 표시용).

        Returns:
            [
                {
                    "category": "path",
                    "key": "structured_txt_root",
                    "value": "/data/...",
                    "value_type": "string",
                    "description": "...",
                    "is_sensitive": false,
                    "platform": "linux",
                    "requires_restart": false,
                    "editable": true
                },
                ...
            ]
        """
        result = []

        with engine.connect() as conn:
            query = text("""
                SELECT category, setting_key, setting_value, value_type,
                       description, is_sensitive, platform, requires_restart,
                       editable, display_order
                FROM system_settings
                WHERE (:category IS NULL OR category = :category)
                ORDER BY category, display_order, setting_key
            """)

            rows = conn.execute(query, {"category": category}).fetchall()

            for row in rows:
                result.append({
                    "category": row[0],
                    "key": row[1],
                    "value": row[2],
                    "value_type": row[3],
                    "description": row[4],
                    "is_sensitive": bool(row[5]),
                    "platform": row[6],
                    "requires_restart": bool(row[7]),
                    "editable": bool(row[8]),
                    "display_order": row[9],
                })

        return result

    def refresh_cache(self):
        """캐시 강제 갱신."""
        self._invalidate_cache()
        self.get_all_settings()


# 싱글톤 인스턴스
_service_instance: Optional[SystemSettingsService] = None


def get_system_settings_service() -> SystemSettingsService:
    """SystemSettingsService 싱글톤 인스턴스 반환."""
    global _service_instance
    if _service_instance is None:
        _service_instance = SystemSettingsService()
    return _service_instance


# 편의 함수들
def get_system_setting(category: str, key: str, default: Any = None) -> Any:
    """단일 설정값 조회 (편의 함수)."""
    return get_system_settings_service().get_setting(category, key, default)


def get_path_setting(key: str, default: str = "") -> str:
    """경로 설정값 조회."""
    return get_system_settings_service().get_setting("path", key, default)


def get_endpoint_setting(key: str, default: str = "") -> str:
    """엔드포인트 설정값 조회."""
    return get_system_settings_service().get_setting("endpoint", key, default)


def get_model_setting(key: str, default: str = "") -> str:
    """모델 설정값 조회."""
    return get_system_settings_service().get_setting("model", key, default)


def get_rag_setting(key: str, default: Any = None) -> Any:
    """RAG 파라미터 설정값 조회."""
    return get_system_settings_service().get_setting("rag", key, default)


def get_llm_setting(key: str, default: Any = None) -> Any:
    """LLM 파라미터 설정값 조회."""
    return get_system_settings_service().get_setting("llm", key, default)
