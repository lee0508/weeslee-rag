# 시스템 설정 관리 API 엔드포인트
# 작업일: 2026-07-08
# 작성자: Claude
"""
관리자용 시스템 설정 API.

엔드포인트:
- GET  /api/admin/system-settings           전체 설정 조회
- GET  /api/admin/system-settings/metadata  설정 메타데이터 조회 (UI용)
- GET  /api/admin/system-settings/{category} 카테고리별 설정 조회
- PUT  /api/admin/system-settings/{category}/{key} 개별 설정 수정
- PUT  /api/admin/system-settings/bulk      일괄 수정
- POST /api/admin/system-settings/refresh   캐시 갱신
- POST /api/admin/system-settings/test-connection 연결 테스트
"""
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.system_settings_service import (
    get_system_settings_service,
)

router = APIRouter(prefix="/api/admin/system-settings", tags=["system-settings"])


# ============================================================
# Request/Response 모델
# ============================================================

class SettingUpdateRequest(BaseModel):
    """단일 설정 수정 요청."""
    value: Any = Field(..., description="새 설정값")
    platform: Optional[str] = Field(None, description="특정 플랫폼 지정 (windows/linux/all)")


class BulkUpdateItem(BaseModel):
    """일괄 수정 항목."""
    category: str
    key: str
    value: Any
    platform: Optional[str] = None


class BulkUpdateRequest(BaseModel):
    """일괄 수정 요청."""
    updates: list[BulkUpdateItem]


class ConnectionTestRequest(BaseModel):
    """연결 테스트 요청."""
    endpoint_type: str = Field(..., description="테스트할 엔드포인트 타입 (ollama, qdrant, mysql)")
    url: Optional[str] = Field(None, description="테스트할 URL (지정 안 하면 현재 설정값 사용)")


# ============================================================
# API 엔드포인트
# ============================================================

@router.get("")
async def get_all_settings(
    include_sensitive: bool = Query(False, description="민감 정보 포함 여부")
):
    """
    전체 시스템 설정 조회.

    카테고리:
    - path: 경로 설정
    - endpoint: 서비스 엔드포인트
    - model: AI 모델 설정
    - rag: RAG 파라미터
    - llm: LLM 생성 파라미터
    - search: 검색 파라미터
    - ocr: OCR 설정
    - security: 보안/CORS 설정
    """
    service = get_system_settings_service()
    settings = service.get_all_settings(include_sensitive=include_sensitive)

    return {
        "success": True,
        "settings": settings,
        "categories": list(settings.keys()),
    }


@router.get("/metadata")
async def get_settings_metadata(
    category: Optional[str] = Query(None, description="특정 카테고리만 조회")
):
    """
    설정 메타데이터 조회 (UI 표시용).

    각 설정의 타입, 설명, 수정 가능 여부, 재시작 필요 여부 등 포함.
    """
    service = get_system_settings_service()
    metadata = service.get_settings_metadata(category)

    # 카테고리별 그룹화
    grouped: dict[str, list] = {}
    for item in metadata:
        cat = item["category"]
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(item)

    return {
        "success": True,
        "metadata": metadata,
        "grouped": grouped,
        "categories": list(grouped.keys()),
    }


@router.get("/{category}")
async def get_category_settings(category: str):
    """특정 카테고리의 설정값 조회."""
    valid_categories = ["path", "endpoint", "model", "rag", "llm", "search", "ocr", "security"]

    if category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 카테고리: {category}. 허용: {valid_categories}"
        )

    service = get_system_settings_service()
    settings = service.get_category_settings(category)

    return {
        "success": True,
        "category": category,
        "settings": settings,
    }


@router.put("/{category}/{key}")
async def update_setting(category: str, key: str, request: SettingUpdateRequest):
    """개별 설정값 수정."""
    service = get_system_settings_service()

    # 기존 설정 확인
    current_value = service.get_setting(category, key)
    if current_value is None:
        raise HTTPException(
            status_code=404,
            detail=f"설정을 찾을 수 없음: {category}.{key}"
        )

    # 업데이트 실행
    success = service.set_setting(category, key, request.value, request.platform)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="설정 업데이트 실패"
        )

    # 새 값 조회
    new_value = service.get_setting(category, key)

    return {
        "success": True,
        "category": category,
        "key": key,
        "previous_value": current_value,
        "new_value": new_value,
    }


@router.put("/bulk")
async def bulk_update_settings(request: BulkUpdateRequest):
    """설정값 일괄 수정."""
    service = get_system_settings_service()

    updates = [
        {
            "category": item.category,
            "key": item.key,
            "value": item.value,
            "platform": item.platform,
        }
        for item in request.updates
    ]

    result = service.bulk_update(updates)

    return {
        "success": result["failed"] == 0,
        **result,
    }


@router.post("/refresh")
async def refresh_cache():
    """설정 캐시 강제 갱신."""
    service = get_system_settings_service()
    service.refresh_cache()

    return {
        "success": True,
        "message": "캐시가 갱신되었습니다.",
    }


@router.post("/test-connection")
async def test_connection(request: ConnectionTestRequest):
    """
    엔드포인트 연결 테스트.

    endpoint_type:
    - ollama: Ollama 서버 연결 테스트
    - qdrant: Qdrant 벡터 DB 연결 테스트
    - mysql: MySQL 데이터베이스 연결 테스트
    """
    service = get_system_settings_service()

    if request.endpoint_type == "ollama":
        url = request.url or service.get_setting("endpoint", "ollama_host", "http://localhost:11434")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{url}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    return {
                        "success": True,
                        "endpoint_type": "ollama",
                        "url": url,
                        "status": "connected",
                        "models": models[:10],
                    }
                else:
                    return {
                        "success": False,
                        "endpoint_type": "ollama",
                        "url": url,
                        "status": "error",
                        "error": f"HTTP {response.status_code}",
                    }
        except Exception as e:
            return {
                "success": False,
                "endpoint_type": "ollama",
                "url": url,
                "status": "error",
                "error": str(e),
            }

    elif request.endpoint_type == "qdrant":
        url = request.url or service.get_setting("endpoint", "qdrant_url", "http://localhost:6333")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{url}/collections")
                if response.status_code == 200:
                    data = response.json()
                    collections = [c.get("name") for c in data.get("result", {}).get("collections", [])]
                    return {
                        "success": True,
                        "endpoint_type": "qdrant",
                        "url": url,
                        "status": "connected",
                        "collections": collections,
                    }
                else:
                    return {
                        "success": False,
                        "endpoint_type": "qdrant",
                        "url": url,
                        "status": "error",
                        "error": f"HTTP {response.status_code}",
                    }
        except Exception as e:
            return {
                "success": False,
                "endpoint_type": "qdrant",
                "url": url,
                "status": "error",
                "error": str(e),
            }

    elif request.endpoint_type == "mysql":
        # MySQL 연결 테스트는 기존 engine 사용
        from app.core.database import engine
        from sqlalchemy import text

        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                result.fetchone()
                return {
                    "success": True,
                    "endpoint_type": "mysql",
                    "status": "connected",
                }
        except Exception as e:
            return {
                "success": False,
                "endpoint_type": "mysql",
                "status": "error",
                "error": str(e),
            }

    else:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 endpoint_type: {request.endpoint_type}"
        )


# ============================================================
# 카테고리 정보
# ============================================================

CATEGORY_INFO = {
    "path": {
        "name": "경로 설정",
        "description": "파일 시스템 경로 (플랫폼별로 다름)",
        "icon": "folder",
    },
    "endpoint": {
        "name": "서비스 엔드포인트",
        "description": "외부 서비스 URL 및 연결 정보",
        "icon": "link",
    },
    "model": {
        "name": "모델 설정",
        "description": "AI/LLM/임베딩 모델 지정",
        "icon": "cpu",
    },
    "rag": {
        "name": "RAG 파라미터",
        "description": "청킹, 임베딩, 검색 관련 설정",
        "icon": "database",
    },
    "llm": {
        "name": "LLM 생성 파라미터",
        "description": "텍스트 생성 온도, 토큰 수 등",
        "icon": "message-square",
    },
    "search": {
        "name": "검색 파라미터",
        "description": "검색 결과 수, 제한 등",
        "icon": "search",
    },
    "ocr": {
        "name": "OCR 설정",
        "description": "문서 OCR 처리 옵션",
        "icon": "file-text",
    },
    "security": {
        "name": "보안 설정",
        "description": "CORS, JWT 등 보안 관련",
        "icon": "shield",
    },
}


@router.get("/categories/info")
async def get_categories_info():
    """카테고리 정보 조회."""
    return {
        "success": True,
        "categories": CATEGORY_INFO,
    }
