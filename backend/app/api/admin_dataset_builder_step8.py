# Dataset Builder Step 8: Graph Build API
"""
Step 8은 문서 메타데이터와 청크 데이터를 기반으로 Knowledge Graph를 생성합니다.
"""
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import require_admin_token
from app.core.database import get_db
from app.models.document_metadata import DocumentMetadata, MetaStatus


router = APIRouter(
    prefix="/admin/dataset-builder/step8",
    tags=["Admin - Dataset Builder Step 8"],
    dependencies=[Depends(require_admin_token)],
)


# ── Request/Response Models ─────────────────────────────────────────────────


class GraphBuildRequest(BaseModel):
    """그래프 빌드 실행 요청"""
    source_id: Optional[str] = None  # None이면 모든 문서 대상
    rebuild: bool = False  # True면 기존 그래프 삭제 후 재빌드


class GraphBuildResponse(BaseModel):
    """그래프 빌드 실행 응답"""
    success: bool
    message: str
    node_count: int = 0
    edge_count: int = 0
    processing_time: float  # seconds
    output: str = ""


class Step8StatusResponse(BaseModel):
    """Step 8 상태 응답"""
    graph_status: str  # empty, ready
    node_count: int
    edge_count: int
    built_at: Optional[str] = None
    schema_version: Optional[str] = None


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.post("/build", response_model=GraphBuildResponse)
async def build_graph(
    request: GraphBuildRequest,
    db: Session = Depends(get_db)
):
    """
    Knowledge Graph를 빌드합니다.

    기존 graph.py의 /api/graph/build 또는 /api/graph/schema/build를 호출합니다.
    """
    import subprocess
    import sys
    import json

    start_time = datetime.now()

    try:
        # build_graph_jsonl.py 스크립트 실행
        project_root = Path(__file__).resolve().parents[3]
        build_script = project_root / "backend" / "scripts" / "build_graph_jsonl.py"

        if not build_script.exists():
            raise HTTPException(
                status_code=500,
                detail=f"build_graph_jsonl.py not found at {build_script}"
            )

        cmd = [sys.executable, str(build_script)]
        if request.source_id:
            cmd += ["--source-id", request.source_id]

        # 스크립트 실행
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            cwd=str(project_root),
        )

        if proc.returncode != 0:
            return GraphBuildResponse(
                success=False,
                message="Graph build failed",
                processing_time=(datetime.now() - start_time).total_seconds(),
                output=proc.stderr.strip() or "Build script failed"
            )

        # 출력에서 결과 파싱
        node_count = 0
        edge_count = 0

        for line in reversed(proc.stdout.strip().splitlines()):
            try:
                data = json.loads(line)
                if data.get("graph_complete"):
                    node_count = data.get("node_count", 0)
                    edge_count = data.get("edge_count", 0)
                    break
            except Exception:
                pass

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()

        return GraphBuildResponse(
            success=True,
            message=f"Graph built successfully: {node_count} nodes, {edge_count} edges",
            node_count=node_count,
            edge_count=edge_count,
            processing_time=processing_time,
            output=proc.stdout.strip()[-500:]
        )

    except subprocess.TimeoutExpired:
        return GraphBuildResponse(
            success=False,
            message="Graph build timed out (300s)",
            processing_time=300.0,
            output="Timeout after 300 seconds"
        )
    except Exception as e:
        return GraphBuildResponse(
            success=False,
            message=f"Graph build failed: {str(e)}",
            processing_time=(datetime.now() - start_time).total_seconds(),
            output=str(e)
        )


@router.get("/status", response_model=Step8StatusResponse)
async def get_step8_status(source_id: Optional[str] = None):
    """
    Step 8 그래프 빌드 상태를 조회합니다.
    """
    try:
        # graph.py의 status 엔드포인트 활용
        from app.api.graph import _load_graph, _manifest

        cache = _load_graph(source_id)
        manifest = _manifest(source_id)

        graph_status = "ready" if cache["nodes"] else "empty"

        return Step8StatusResponse(
            graph_status=graph_status,
            node_count=len(cache["nodes"]),
            edge_count=len(cache["edges"]),
            built_at=manifest.get("built_at"),
            schema_version=manifest.get("schema_version", "phase2")
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.get("/stats")
async def get_step8_stats(source_id: Optional[str] = None):
    """
    Step 8 그래프 통계를 조회합니다.
    """
    try:
        from app.api.graph import _load_graph

        cache = _load_graph(source_id)

        # 노드 타입별 카운트
        node_type_counts = {}
        for node in cache["nodes"]:
            node_type = node.get("type", "unknown")
            node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1

        # 관계 타입별 카운트
        relation_type_counts = {}
        for edge in cache["edges"]:
            relation = edge.get("relation", "unknown")
            relation_type_counts[relation] = relation_type_counts.get(relation, 0) + 1

        return {
            "success": True,
            "source_id": source_id or "all",
            "total_nodes": len(cache["nodes"]),
            "total_edges": len(cache["edges"]),
            "node_types": node_type_counts,
            "relation_types": relation_type_counts
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")
