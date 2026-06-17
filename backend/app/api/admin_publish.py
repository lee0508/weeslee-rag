# Publish 관리 API - Dataset Builder에서 분리된 독립 메뉴용
"""
Publish 메뉴용 API 엔드포인트.
- Search Quality Check (검색 품질 테스트)
- Active Dataset / Snapshot 관리
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_admin_token
from app.core.database import get_db


router = APIRouter(
    prefix="/admin/publish",
    tags=["Admin - Publish"],
    dependencies=[Depends(require_admin_token)],
)


# ── Request/Response Models ─────────────────────────────────────────────────


class TestQuery(BaseModel):
    """테스트 질의"""
    query: str
    expected_doc_ids: Optional[List[int]] = None
    category: Optional[str] = None


class SearchQualityRequest(BaseModel):
    """검색 품질 테스트 요청"""
    test_queries: List[TestQuery]
    source_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    top_k: int = Field(10, ge=1, le=50)
    use_graph: bool = False


class SearchResult(BaseModel):
    """검색 결과"""
    rank: int
    document_id: int
    score: float
    file_name: str
    category: str
    organization: str
    text_preview: str


class QueryTestResult(BaseModel):
    """쿼리 테스트 결과"""
    query: str
    success: bool
    results_count: int
    results: List[SearchResult]
    precision: Optional[float] = None
    recall: Optional[float] = None
    search_time_ms: float
    error: Optional[str] = None


class SearchQualityResponse(BaseModel):
    """검색 품질 테스트 응답"""
    success: bool
    total_queries: int
    passed_queries: int
    failed_queries: int
    avg_precision: Optional[float] = None
    avg_recall: Optional[float] = None
    avg_search_time_ms: float
    test_results: List[QueryTestResult]
    quality_score: float = 0.0  # 0-100 점수


class PublishStatusResponse(BaseModel):
    """Publish 상태 응답"""
    faiss_status: str  # ready, empty, error
    faiss_doc_count: int = 0
    graph_status: str  # ready, empty
    graph_node_count: int = 0
    wiki_status: str  # ready, empty
    wiki_count: int = 0
    active_snapshot: Optional[str] = None
    active_collections: List[str] = []
    quality_passed: bool = False
    quality_score: float = 0.0
    last_published_at: Optional[str] = None
    # 명시적 ID 필드 추가 (표준화)
    source_id: Optional[str] = None
    dataset_id: Optional[str] = None
    snapshot_id: Optional[str] = None


class SnapshotInfo(BaseModel):
    """Snapshot 정보"""
    snapshot_id: str
    source_id: str
    created_at: str
    document_count: int = 0
    chunk_count: int = 0
    is_active: bool = False
    has_faiss: bool = False
    has_graph: bool = False
    has_wiki: bool = False


class SnapshotListResponse(BaseModel):
    """Snapshot 목록 응답"""
    success: bool
    snapshots: List[SnapshotInfo]
    active_snapshot: Optional[str] = None


class ActivateRequest(BaseModel):
    """활성화 요청"""
    snapshot_id: str
    source_id: Optional[str] = None


class ActivateResponse(BaseModel):
    """활성화 응답"""
    success: bool
    message: str
    activated_snapshot: Optional[str] = None
    previous_snapshot: Optional[str] = None


# ── Helper Functions ────────────────────────────────────────────────────────


def _get_project_root() -> Path:
    """프로젝트 루트 경로 반환"""
    return Path(__file__).resolve().parents[3]


def _calculate_precision_recall(
    retrieved_ids: List[int],
    expected_ids: List[int]
) -> tuple[float, float]:
    """Precision과 Recall 계산"""
    if not retrieved_ids or not expected_ids:
        return 0.0, 0.0

    retrieved_set = set(retrieved_ids)
    expected_set = set(expected_ids)
    true_positives = len(retrieved_set & expected_set)

    precision = true_positives / len(retrieved_set) if retrieved_set else 0.0
    recall = true_positives / len(expected_set) if expected_set else 0.0

    return precision, recall


def _get_active_info(source_id: Optional[str] = None) -> Dict[str, Any]:
    """현재 활성 Snapshot 정보 조회 - active_snapshot.json 또는 active_index.json에서 읽기"""
    project_root = _get_project_root()

    if source_id:
        active_file = project_root / "data" / "snapshots" / source_id / "active.json"
    else:
        active_file = project_root / "data" / "active_snapshot.json"

    if active_file.exists():
        with open(active_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # Fallback: active_index.json에서 읽기 (RAG 검색이 사용하는 파일)
    active_index_file = project_root / "data" / "active_index.json"
    if active_index_file.exists():
        with open(active_index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # snapshot 또는 active_snapshot 키 지원
        snapshot_id = data.get("snapshot") or data.get("active_snapshot")
        return {"snapshot_id": snapshot_id, "snapshot": snapshot_id, **data}

    return {}


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.post("/quality/test", response_model=SearchQualityResponse)
async def test_search_quality(
    request: SearchQualityRequest,
    db: Session = Depends(get_db)
):
    """
    검색 품질을 테스트합니다.
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
                if request.use_graph:
                    from app.agents.graphrag_agent import get_graphrag_agent

                    agent = get_graphrag_agent(source_id=request.source_id)
                    response = await agent.process(test_query.query)

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
                    from app.services.faiss_search_service import get_faiss_search_service

                    faiss_service = get_faiss_search_service(source_id=request.source_id)
                    faiss_response = faiss_service.search(
                        query=test_query.query,
                        top_k=request.top_k,
                        category_filter=test_query.category
                    )

                    if not faiss_response.success:
                        raise Exception(faiss_response.error or "Search failed")

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

                precision = None
                recall = None

                if test_query.expected_doc_ids:
                    precision, recall = _calculate_precision_recall(
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

        avg_precision = total_precision / precision_count if precision_count > 0 else None
        avg_recall = total_recall / precision_count if precision_count > 0 else None
        avg_search_time = total_search_time / len(request.test_queries) if request.test_queries else 0.0

        # 품질 점수 계산 (0-100)
        total_queries = len(request.test_queries)
        success_rate = passed_queries / total_queries if total_queries > 0 else 0
        quality_score = success_rate * 100

        return SearchQualityResponse(
            success=True,
            total_queries=total_queries,
            passed_queries=passed_queries,
            failed_queries=failed_queries,
            avg_precision=avg_precision,
            avg_recall=avg_recall,
            avg_search_time_ms=avg_search_time,
            test_results=test_results,
            quality_score=quality_score
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search quality test failed: {str(e)}")


@router.get("/quality/sample-queries")
async def get_sample_queries():
    """테스트용 샘플 쿼리 목록을 반환합니다."""
    return {
        "sample_queries": [
            {"query": "ISP 방법론이 적용된 프로젝트는?", "category": "proposal"},
            {"query": "클라우드 마이그레이션 관련 문서", "category": None},
            {"query": "한국수자원공사 사업", "category": None},
            {"query": "디지털 전환 전략", "category": "final_report"},
            {"query": "빅데이터 플랫폼 구축", "category": None}
        ]
    }


@router.get("/status", response_model=PublishStatusResponse)
async def get_publish_status(source_id: Optional[str] = None):
    """
    Publish 상태를 조회합니다.
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
                faiss_doc_count = stats.get("total_vectors", 0)
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

        # Wiki 상태
        wiki_status = "empty"
        wiki_count = 0

        try:
            project_root = _get_project_root()
            wiki_dir = project_root / "data" / "wiki"
            if source_id:
                wiki_dir = wiki_dir / source_id

            if wiki_dir.exists():
                wiki_count = len(list(wiki_dir.rglob("*.md")))
                if wiki_count > 0:
                    wiki_status = "ready"
        except Exception:
            pass

        # Active Snapshot 정보
        active_info = _get_active_info(source_id)
        active_snapshot = active_info.get("snapshot") or active_info.get("snapshot_id")
        active_collections = active_info.get("collections", [])

        # snapshot_id에서 source_id, dataset_id 추출 (표준화)
        resolved_source_id = source_id or "rag_source"
        resolved_dataset_id = None
        if active_snapshot:
            # snapshot_20260616_rag_source_v1 형식 파싱
            parts = active_snapshot.replace("snapshot_", "").split("_")
            if len(parts) >= 2:
                date_part = parts[0]  # YYYYMMDD
                # source_id 추출 (v로 시작하는 버전 부분 제외)
                source_parts = [p for p in parts[1:] if not p.lower().startswith("v")]
                if source_parts:
                    resolved_source_id = "_".join(source_parts)
                resolved_dataset_id = f"dataset_{resolved_source_id}_{date_part}"

        return PublishStatusResponse(
            faiss_status=faiss_status,
            faiss_doc_count=faiss_doc_count,
            graph_status=graph_status,
            graph_node_count=graph_node_count,
            wiki_status=wiki_status,
            wiki_count=wiki_count,
            active_snapshot=active_snapshot,
            active_collections=active_collections,
            quality_passed=faiss_status == "ready",
            quality_score=100.0 if faiss_status == "ready" else 0.0,
            # 명시적 ID 필드 (표준화)
            source_id=resolved_source_id,
            dataset_id=resolved_dataset_id,
            snapshot_id=active_snapshot
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.get("/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(source_id: Optional[str] = None):
    """
    사용 가능한 Snapshot 목록을 조회합니다.
    """
    try:
        project_root = _get_project_root()
        snapshots_dir = project_root / "data" / "snapshots"

        if source_id:
            snapshots_dir = snapshots_dir / source_id

        snapshots: List[SnapshotInfo] = []
        active_info = _get_active_info(source_id)
        active_snapshot = active_info.get("snapshot") or active_info.get("snapshot_id")

        if snapshots_dir.exists():
            for snapshot_dir in sorted(snapshots_dir.iterdir(), reverse=True):
                if not snapshot_dir.is_dir():
                    continue
                if snapshot_dir.name in ["active.json", "manifest.json"]:
                    continue

                snapshot_id = snapshot_dir.name

                # manifest.json 읽기
                manifest_file = snapshot_dir / "manifest.json"
                document_count = 0
                chunk_count = 0
                created_at = ""

                if manifest_file.exists():
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    document_count = manifest.get("document_count", 0)
                    chunk_count = manifest.get("chunk_count", 0)
                    created_at = manifest.get("created_at", "")

                # FAISS 존재 여부
                has_faiss = any(snapshot_dir.glob("*.index"))

                # Graph 존재 여부
                has_graph = (snapshot_dir / "graph_nodes.jsonl").exists()

                # Wiki 존재 여부
                wiki_dir = project_root / "data" / "wiki"
                if source_id:
                    wiki_dir = wiki_dir / source_id
                has_wiki = wiki_dir.exists() and any(wiki_dir.rglob("*.md"))

                snapshots.append(SnapshotInfo(
                    snapshot_id=snapshot_id,
                    source_id=source_id or "default",
                    created_at=created_at,
                    document_count=document_count,
                    chunk_count=chunk_count,
                    is_active=(snapshot_id == active_snapshot),
                    has_faiss=has_faiss,
                    has_graph=has_graph,
                    has_wiki=has_wiki
                ))

        return SnapshotListResponse(
            success=True,
            snapshots=snapshots[:20],  # 최대 20개
            active_snapshot=active_snapshot
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list snapshots: {str(e)}")


@router.post("/activate", response_model=ActivateResponse)
async def activate_snapshot(request: ActivateRequest):
    """
    Snapshot을 활성화합니다.
    """
    try:
        project_root = _get_project_root()

        # 현재 active 정보
        previous_info = _get_active_info(request.source_id)
        previous_snapshot = previous_info.get("snapshot") or previous_info.get("snapshot_id")

        # active.json 파일 경로
        if request.source_id:
            active_file = project_root / "data" / "snapshots" / request.source_id / "active.json"
        else:
            active_file = project_root / "data" / "active_snapshot.json"

        # 새 active 정보 저장
        active_data = {
            "snapshot": request.snapshot_id,
            "snapshot_id": request.snapshot_id,
            "source_id": request.source_id,
            "activated_at": datetime.now().isoformat(),
            "previous_snapshot": previous_snapshot
        }

        active_file.parent.mkdir(parents=True, exist_ok=True)
        with open(active_file, "w", encoding="utf-8") as f:
            json.dump(active_data, f, ensure_ascii=False, indent=2)

        return ActivateResponse(
            success=True,
            message=f"Snapshot '{request.snapshot_id}' 활성화 완료",
            activated_snapshot=request.snapshot_id,
            previous_snapshot=previous_snapshot
        )

    except Exception as e:
        return ActivateResponse(
            success=False,
            message=f"Activation failed: {str(e)}"
        )


@router.post("/rollback", response_model=ActivateResponse)
async def rollback_snapshot(source_id: Optional[str] = None):
    """
    이전 Snapshot으로 롤백합니다.
    """
    try:
        active_info = _get_active_info(source_id)
        previous_snapshot = active_info.get("previous_snapshot")

        if not previous_snapshot:
            return ActivateResponse(
                success=False,
                message="롤백할 이전 Snapshot이 없습니다"
            )

        return await activate_snapshot(ActivateRequest(
            snapshot_id=previous_snapshot,
            source_id=source_id
        ))

    except Exception as e:
        return ActivateResponse(
            success=False,
            message=f"Rollback failed: {str(e)}"
        )


@router.get("/stats")
async def get_publish_stats(source_id: Optional[str] = None):
    """
    Publish 통계를 조회합니다.
    """
    try:
        project_root = _get_project_root()

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

        # Active 정보
        active_info = _get_active_info(source_id)

        return {
            "success": True,
            "source_id": source_id or "all",
            "faiss": faiss_stats,
            "graph": graph_stats,
            "active_snapshot": active_info.get("snapshot") or active_info.get("snapshot_id"),
            "active_collections": active_info.get("collections", [])
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")
