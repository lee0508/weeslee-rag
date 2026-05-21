# 관리자용 사용자 질의 로그와 결과 통계를 조회하는 API
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth import require_admin_token
from app.services.query_log_service import query_log_service


router = APIRouter(
    prefix="/admin/query-logs",
    tags=["Admin Query Logs"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("")
async def list_query_logs(
    endpoint: str = Query("", description="Endpoint filter"),
    success: str = Query("", description="success | failed"),
    search: str = Query("", description="Search query text"),
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(100, ge=1, le=500),
):
    logs = query_log_service.list_query_logs(
        endpoint=endpoint,
        success=success,
        search=search,
        days=days,
        limit=limit,
    )
    return {"logs": logs, "count": len(logs)}


@router.get("/summary")
async def get_query_log_summary(
    days: int = Query(7, ge=1, le=90),
    top_n: int = Query(10, ge=1, le=50),
):
    return query_log_service.get_summary(days=days, top_n=top_n)
