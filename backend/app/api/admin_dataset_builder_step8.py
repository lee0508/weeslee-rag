# Dataset Builder Step 8: Graph Build API
"""
Step 8은 문서 메타데이터와 청크 데이터를 기반으로 Knowledge Graph를 생성합니다.
"""
from datetime import datetime
from typing import Optional, List
from pathlib import Path
import json
import subprocess
import sys
import tempfile

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


def _read_text_tail(path: Path, max_chars: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[-max_chars:]


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

        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", suffix="_step8_graph_build.log", delete=False) as log_file:
            log_path = Path(log_file.name)
            proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                cwd=str(project_root),
            )
            try:
                proc.wait(timeout=300)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
                return GraphBuildResponse(
                    success=False,
                    message="Graph build timed out (300s)",
                    processing_time=300.0,
                    output=_read_text_tail(log_path, 2000) or "Timeout after 300 seconds"
                )

        if proc.returncode != 0:
            return GraphBuildResponse(
                success=False,
                message="Graph build failed",
                processing_time=(datetime.now() - start_time).total_seconds(),
                output=_read_text_tail(log_path, 3000) or "Build script failed"
            )

        # 출력에서 결과 파싱
        node_count = 0
        edge_count = 0

        log_text = _read_text_tail(log_path, 12000)
        for line in reversed(log_text.strip().splitlines()):
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
            output=log_text[-1000:]
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
        # graph.py의 manifest 집계를 우선 활용
        from app.api.graph import _load_graph, _manifest, _graph_summary_from_manifest
        manifest = _manifest(source_id)
        manifest_summary = _graph_summary_from_manifest(manifest)

        if manifest_summary:
            return Step8StatusResponse(
                graph_status="ready" if manifest_summary["has_data"] else "empty",
                node_count=int(manifest.get("node_count") or 0),
                edge_count=int(manifest.get("edge_count") or 0),
                built_at=manifest.get("built_at"),
                schema_version=manifest.get("schema_version", "phase2")
            )

        cache = _load_graph(source_id)
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
