# Benchmark History API
"""
Benchmark and Search Quality API.

GET /api/benchmark/history - 벤치마크 실행 이력 조회
"""
from fastapi import APIRouter

router = APIRouter(prefix="/benchmark", tags=["Benchmark"])


@router.get("/history")
async def get_benchmark_history():
    """벤치마크 실행 이력 조회.

    현재는 빈 응답 반환 (향후 구현 예정).
    프론트엔드에서 404 에러 방지용.
    """
    return {
        "history": [],
        "total_queries": 0,
        "success_rate": 0.0,
        "avg_response_time": 0.0,
        "referenced_docs": 0,
    }
