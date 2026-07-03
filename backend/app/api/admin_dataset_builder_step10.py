# Dataset Builder Step 10: Search Quality API
"""
Step 10은 RAG 검색 품질을 테스트하고 평가합니다.
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_admin_token
from app.core.database import get_db


router = APIRouter(
    prefix="/admin/dataset-builder/step10",
    tags=["Admin - Dataset Builder Step 10"],
    dependencies=[Depends(require_admin_token)],
)


# ── Request/Response Models ─────────────────────────────────────────────────


class TestQuery(BaseModel):
    """테스트 질의"""
    query: str = Field(..., description="검색 쿼리")
    expected_doc_ids: Optional[List[int]] = Field(None, description="기대하는 문서 ID 목록")
    category: Optional[str] = Field(None, description="카테고리 필터")


class SearchQualityRequest(BaseModel):
    """검색 품질 테스트 요청"""
    test_queries: List[TestQuery] = Field(..., description="테스트 질의 목록")
    source_id: Optional[str] = None
    top_k: int = Field(10, ge=1, le=50, description="검색 결과 수")
    use_graph: bool = Field(False, description="GraphRAG 사용 여부")


class SearchResult(BaseModel):
    """개별 검색 결과"""
    rank: int
    document_id: int
    score: float
    file_name: str
    category: str
    organization: str
    text_preview: str


class QueryTestResult(BaseModel):
    """개별 쿼리 테스트 결과"""
    query: str
    success: bool
    results_count: int
    results: List[SearchResult]
    precision: Optional[float] = None  # 정확도 (expected_doc_ids 제공 시)
    recall: Optional[float] = None  # 재현율 (expected_doc_ids 제공 시)
    search_time_ms: float
    error: Optional[str] = None


class SearchQualityResponse(BaseModel):
    """검색 품질 테스트 전체 결과"""
    success: bool
    total_queries: int
    passed_queries: int
    failed_queries: int
    avg_precision: Optional[float] = None
    avg_recall: Optional[float] = None
    avg_search_time_ms: float
    test_results: List[QueryTestResult]


class Step10StatusResponse(BaseModel):
    """Step 10 상태 응답"""
    faiss_status: str  # ready, empty, error
    faiss_doc_count: int
    graph_status: str  # ready, empty
    graph_node_count: int
    last_test_at: Optional[str] = None
    total_tests: int


# ── Helper Functions ────────────────────────────────────────────────────────


def calculate_precision_recall(
    retrieved_ids: List[int],
    expected_ids: List[int]
) -> tuple[float, float]:
    """
    Precision과 Recall 계산

    Precision = (검색된 문서 중 정답 문서 수) / (검색된 전체 문서 수)
    Recall = (검색된 정답 문서 수) / (전체 정답 문서 수)
    """
    if not retrieved_ids or not expected_ids:
        return 0.0, 0.0

    retrieved_set = set(retrieved_ids)
    expected_set = set(expected_ids)

    true_positives = len(retrieved_set & expected_set)

    precision = true_positives / len(retrieved_set) if retrieved_set else 0.0
    recall = true_positives / len(expected_set) if expected_set else 0.0

    return precision, recall


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.post("/test", response_model=SearchQualityResponse)
async def test_search_quality(
    request: SearchQualityRequest,
    db: Session = Depends(get_db)
):
    """
    검색 품질을 테스트합니다.

    여러 테스트 쿼리를 실행하고 검색 결과의 품질을 평가합니다.
    """
    import time

    test_results = []
    total_precision = 0.0
    total_recall = 0.0
    precision_count = 0
    total_search_time = 0.0

    passed_queries = 0
    failed_queries = 0

    try:
        for test_query in request.test_queries:
            start_time = time.time()

            try:
                # FAISS 검색 실행
                if request.use_graph:
                    # GraphRAG Agent 사용
                    from app.agents.graphrag_agent import get_graphrag_agent

                    agent = get_graphrag_agent(source_id=request.source_id)
                    response = await agent.process(test_query.query)

                    # 결과 변환
                    search_results = []
                    for idx, result in enumerate(response.results[:request.top_k], 1):
                        search_results.append(SearchResult(
                            rank=idx,
                            document_id=result.get("document_id", 0),
                            score=result.get("score", 0.0),
                            file_name=result.get("file_name", ""),
                            category=result.get("category", ""),
                            organization=result.get("organization", ""),
                            text_preview=result.get("text_preview", "")[:200]
                        ))

                    retrieved_ids = [r.document_id for r in search_results]

                else:
                    # FAISS 직접 검색
                    from app.services.faiss_search_service import get_faiss_search_service

                    faiss_service = get_faiss_search_service(source_id=request.source_id)
                    faiss_response = faiss_service.search(
                        query=test_query.query,
                        top_k=request.top_k,
                        category_filter=test_query.category
                    )

                    if not faiss_response.success:
                        raise Exception(faiss_response.error or "Search failed")

                    # 결과 변환
                    search_results = []
                    for result in faiss_response.results:
                        search_results.append(SearchResult(
                            rank=result.rank,
                            document_id=int(result.document_id) if result.document_id else 0,
                            score=result.score,
                            file_name=result.file_name or "",
                            category=result.category or "",
                            organization=result.organization or "",
                            text_preview=result.text_preview or ""
                        ))

                    retrieved_ids = [r.document_id for r in search_results]

                search_time_ms = (time.time() - start_time) * 1000
                total_search_time += search_time_ms

                # Precision/Recall 계산
                precision = None
                recall = None

                if test_query.expected_doc_ids:
                    precision, recall = calculate_precision_recall(
                        retrieved_ids,
                        test_query.expected_doc_ids
                    )
                    total_precision += precision
                    total_recall += recall
                    precision_count += 1

                passed_queries += 1

                test_results.append(QueryTestResult(
                    query=test_query.query,
                    success=True,
                    results_count=len(search_results),
                    results=search_results,
                    precision=precision,
                    recall=recall,
                    search_time_ms=search_time_ms
                ))

            except Exception as e:
                failed_queries += 1
                search_time_ms = (time.time() - start_time) * 1000
                total_search_time += search_time_ms

                test_results.append(QueryTestResult(
                    query=test_query.query,
                    success=False,
                    results_count=0,
                    results=[],
                    search_time_ms=search_time_ms,
                    error=str(e)
                ))

        # 평균 계산
        avg_precision = total_precision / precision_count if precision_count > 0 else None
        avg_recall = total_recall / precision_count if precision_count > 0 else None
        avg_search_time = total_search_time / len(request.test_queries) if request.test_queries else 0.0

        return SearchQualityResponse(
            success=True,
            total_queries=len(request.test_queries),
            passed_queries=passed_queries,
            failed_queries=failed_queries,
            avg_precision=avg_precision,
            avg_recall=avg_recall,
            avg_search_time_ms=avg_search_time,
            test_results=test_results
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search quality test failed: {str(e)}")


@router.get("/status", response_model=Step10StatusResponse)
async def get_step10_status(source_id: Optional[str] = None):
    """
    Step 10 검색 품질 테스트 상태를 조회합니다.
    """
    try:
        # FAISS 상태
        faiss_status = "empty"
        faiss_doc_count = 0

        try:
            from app.services.faiss_search_service import get_faiss_search_service

            faiss_service = get_faiss_search_service(source_id=source_id)
            stats = faiss_service.get_index_stats()

            if stats.get("loaded"):
                faiss_status = "ready"
                faiss_doc_count = int(
                    stats.get("filtered_document_count")
                    or stats.get("document_count")
                    or stats.get("documents_count")
                    or stats.get("filtered_metadata_count")
                    or stats.get("metadata_count")
                    or stats.get("vector_count")
                    or 0
                )
        except Exception:
            faiss_status = "error"

        # Graph 상태
        graph_status = "empty"
        graph_node_count = 0

        try:
            from app.api.graph import _load_graph

            cache = _load_graph(source_id)
            if cache["nodes"]:
                graph_status = "ready"
                graph_node_count = len(cache["nodes"])
        except Exception:
            pass

        return Step10StatusResponse(
            faiss_status=faiss_status,
            faiss_doc_count=faiss_doc_count,
            graph_status=graph_status,
            graph_node_count=graph_node_count,
            last_test_at=None,  # TODO: 테스트 로그에서 가져오기
            total_tests=0  # TODO: 테스트 로그에서 가져오기
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.get("/stats")
async def get_step10_stats(source_id: Optional[str] = None):
    """
    Step 10 통계를 조회합니다.
    """
    try:
        # FAISS 통계
        faiss_stats = {}
        try:
            from app.services.faiss_search_service import get_faiss_search_service

            faiss_service = get_faiss_search_service(source_id=source_id)
            faiss_stats = faiss_service.get_index_stats()
        except Exception:
            faiss_stats = {"error": "FAISS not available"}

        # Graph 통계
        graph_stats = {}
        try:
            from app.api.graph import _load_graph

            cache = _load_graph(source_id)
            graph_stats = {
                "total_nodes": len(cache["nodes"]),
                "total_edges": len(cache["edges"]),
                "has_data": bool(cache["nodes"])
            }
        except Exception:
            graph_stats = {"error": "Graph not available"}

        return {
            "success": True,
            "source_id": source_id or "all",
            "faiss": faiss_stats,
            "graph": graph_stats
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.get("/sample-queries")
async def get_sample_queries():
    """
    테스트용 샘플 쿼리 목록을 반환합니다.
    """
    return {
        "sample_queries": [
            {
                "query": "ISP 방법론이 적용된 프로젝트는?",
                "category": "proposal"
            },
            {
                "query": "클라우드 마이그레이션 관련 문서",
                "category": None
            },
            {
                "query": "한국수자원공사 사업",
                "category": None
            },
            {
                "query": "디지털 전환 전략",
                "category": "final_report"
            },
            {
                "query": "빅데이터 플랫폼 구축",
                "category": None
            }
        ]
    }
