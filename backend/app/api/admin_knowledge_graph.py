# Knowledge Graph 관리 API - Dataset Builder에서 분리된 독립 메뉴용
"""
Knowledge Graph 메뉴용 API 엔드포인트.
- Ontology 설정
- Knowledge Graph 생성
- Graph View 미리보기
- Graph 검증
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
    prefix="/admin/knowledge-graph",
    tags=["Admin - Knowledge Graph"],
    dependencies=[Depends(require_admin_token)],
)


# ── Request/Response Models ─────────────────────────────────────────────────


class OntologyNodeType(BaseModel):
    """노드 타입 정의"""
    name: str
    label: str
    description: str = ""
    properties: List[str] = []


class OntologyRelationType(BaseModel):
    """관계 타입 정의"""
    name: str
    label: str
    description: str = ""
    source_types: List[str] = []
    target_types: List[str] = []


class OntologySchema(BaseModel):
    """Ontology 스키마"""
    version: str = "1.0"
    node_types: List[OntologyNodeType] = []
    relation_types: List[OntologyRelationType] = []
    path_mappings: Dict[str, str] = {}
    prefix_mappings: Dict[str, str] = {}


class OntologyResponse(BaseModel):
    """Ontology 응답"""
    success: bool
    schema: Optional[OntologySchema] = None
    message: str = ""


class GraphBuildRequest(BaseModel):
    """그래프 빌드 실행 요청"""
    source_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    rebuild: bool = False
    use_ontology: bool = True


class GraphBuildResponse(BaseModel):
    """그래프 빌드 실행 응답"""
    success: bool
    message: str
    node_count: int = 0
    edge_count: int = 0
    processing_time: float = 0.0
    output: str = ""


class GraphStatusResponse(BaseModel):
    """Graph 상태 응답"""
    status: str  # empty, building, ready, error
    node_count: int = 0
    edge_count: int = 0
    built_at: Optional[str] = None
    schema_version: Optional[str] = None
    snapshot_id: Optional[str] = None


class GraphValidationResult(BaseModel):
    """Graph 검증 결과"""
    valid: bool
    total_nodes: int = 0
    total_edges: int = 0
    orphan_nodes: int = 0
    missing_relations: List[str] = []
    warnings: List[str] = []
    errors: List[str] = []


class NodeInfo(BaseModel):
    """노드 정보"""
    id: str
    type: str
    label: str
    properties: Dict[str, Any] = {}


class EdgeInfo(BaseModel):
    """엣지 정보"""
    source: str
    target: str
    relation: str
    properties: Dict[str, Any] = {}


class GraphPreviewResponse(BaseModel):
    """Graph 미리보기 응답"""
    success: bool
    node_count: int = 0
    edge_count: int = 0
    nodes: List[NodeInfo] = []
    edges: List[EdgeInfo] = []
    node_type_counts: Dict[str, int] = {}
    relation_type_counts: Dict[str, int] = {}


# ── Helper Functions ────────────────────────────────────────────────────────


def _get_default_ontology() -> OntologySchema:
    """기본 Ontology 스키마 반환"""
    return OntologySchema(
        version="1.0",
        node_types=[
            OntologyNodeType(name="DocumentSource", label="문서소스", description="RAG 소스 폴더"),
            OntologyNodeType(name="Dataset", label="데이터셋", description="Dataset Builder로 생성된 데이터셋"),
            OntologyNodeType(name="Snapshot", label="스냅샷", description="특정 시점의 데이터셋 버전"),
            OntologyNodeType(name="Document", label="문서", description="개별 문서 파일"),
            OntologyNodeType(name="File", label="파일", description="원본 파일"),
            OntologyNodeType(name="Project", label="프로젝트", description="컨설팅 프로젝트"),
            OntologyNodeType(name="DocumentGroup", label="문서그룹", description="문서 분류 (RFP, 제안서, 산출물)"),
            OntologyNodeType(name="DocumentSection", label="문서섹션", description="문서 하위 분류"),
            OntologyNodeType(name="Organization", label="기관", description="발주기관/수행기관"),
            OntologyNodeType(name="Technology", label="기술", description="적용 기술"),
            OntologyNodeType(name="Methodology", label="방법론", description="적용 방법론"),
            OntologyNodeType(name="Keyword", label="키워드", description="추출된 키워드"),
            OntologyNodeType(name="Collection", label="컬렉션", description="FAISS 컬렉션"),
            OntologyNodeType(name="Chunk", label="청크", description="문서 청크"),
        ],
        relation_types=[
            OntologyRelationType(name="HAS_DATASET", label="데이터셋보유", source_types=["DocumentSource"], target_types=["Dataset"]),
            OntologyRelationType(name="HAS_SNAPSHOT", label="스냅샷보유", source_types=["Dataset"], target_types=["Snapshot"]),
            OntologyRelationType(name="INCLUDES_DOCUMENT", label="문서포함", source_types=["Snapshot"], target_types=["Document"]),
            OntologyRelationType(name="HAS_DOCUMENT", label="문서보유", source_types=["Project"], target_types=["Document"]),
            OntologyRelationType(name="HAS_FILE", label="파일보유", source_types=["Document"], target_types=["File"]),
            OntologyRelationType(name="BELONGS_TO_GROUP", label="그룹소속", source_types=["Document"], target_types=["DocumentGroup"]),
            OntologyRelationType(name="HAS_SECTION", label="섹션보유", source_types=["DocumentGroup"], target_types=["DocumentSection"]),
            OntologyRelationType(name="ABOUT_PROJECT", label="프로젝트관련", source_types=["Document"], target_types=["Project"]),
            OntologyRelationType(name="REQUESTED_BY", label="발주기관", source_types=["Project"], target_types=["Organization"]),
            OntologyRelationType(name="USES_TECHNOLOGY", label="기술적용", source_types=["Project", "Document"], target_types=["Technology"]),
            OntologyRelationType(name="USES_METHODOLOGY", label="방법론적용", source_types=["Project", "Document"], target_types=["Methodology"]),
            OntologyRelationType(name="HAS_KEYWORD", label="키워드보유", source_types=["Document", "Chunk"], target_types=["Keyword"]),
            OntologyRelationType(name="IN_COLLECTION", label="컬렉션소속", source_types=["Chunk"], target_types=["Collection"]),
            OntologyRelationType(name="CHUNKED_INTO", label="청크분할", source_types=["Document"], target_types=["Chunk"]),
            OntologyRelationType(name="SIMILAR_TO", label="유사문서", source_types=["Document"], target_types=["Document"]),
        ],
        path_mappings={
            "01. RFP": "RFP",
            "02. 제안서": "제안서",
            "03. 산출물": "산출물",
        },
        prefix_mappings={
            "전략및방법론_": "전략및방법론",
            "현황분석_": "현황분석",
            "요구사항분석_": "요구사항분석",
            "아키텍처_": "아키텍처",
        }
    )


def _get_project_root() -> Path:
    """프로젝트 루트 경로 반환"""
    return Path(__file__).resolve().parents[3]


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.get("/ontology", response_model=OntologyResponse)
async def get_ontology(source_id: Optional[str] = None):
    """
    현재 Ontology 스키마를 조회합니다.
    """
    try:
        project_root = _get_project_root()

        # source_id별 또는 기본 ontology 파일 경로
        if source_id:
            ontology_path = project_root / "data" / "graph" / source_id / "ontology_schema.json"
        else:
            ontology_path = project_root / "data" / "graph" / "ontology_schema.json"

        if ontology_path.exists():
            with open(ontology_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return OntologyResponse(
                success=True,
                schema=OntologySchema(**data),
                message="Ontology loaded successfully"
            )
        else:
            # 기본 ontology 반환
            return OntologyResponse(
                success=True,
                schema=_get_default_ontology(),
                message="Default ontology returned (no custom schema found)"
            )

    except Exception as e:
        return OntologyResponse(
            success=False,
            message=f"Failed to load ontology: {str(e)}"
        )


@router.post("/ontology", response_model=OntologyResponse)
async def save_ontology(
    schema: OntologySchema,
    source_id: Optional[str] = None
):
    """
    Ontology 스키마를 저장합니다.
    """
    try:
        project_root = _get_project_root()

        if source_id:
            ontology_dir = project_root / "data" / "graph" / source_id
        else:
            ontology_dir = project_root / "data" / "graph"

        ontology_dir.mkdir(parents=True, exist_ok=True)
        ontology_path = ontology_dir / "ontology_schema.json"

        with open(ontology_path, "w", encoding="utf-8") as f:
            json.dump(schema.model_dump(), f, ensure_ascii=False, indent=2)

        return OntologyResponse(
            success=True,
            schema=schema,
            message="Ontology saved successfully"
        )

    except Exception as e:
        return OntologyResponse(
            success=False,
            message=f"Failed to save ontology: {str(e)}"
        )


@router.post("/ontology/reset", response_model=OntologyResponse)
async def reset_ontology(source_id: Optional[str] = None):
    """
    Ontology 스키마를 기본값으로 리셋합니다.
    """
    default_schema = _get_default_ontology()
    return await save_ontology(default_schema, source_id)


@router.post("/build", response_model=GraphBuildResponse)
async def build_knowledge_graph(
    request: GraphBuildRequest,
    db: Session = Depends(get_db)
):
    """
    Knowledge Graph를 빌드합니다.
    """
    import subprocess
    import sys

    start_time = datetime.now()

    try:
        project_root = _get_project_root()
        build_script = project_root / "backend" / "scripts" / "build_graph_jsonl.py"

        if not build_script.exists():
            raise HTTPException(
                status_code=500,
                detail=f"build_graph_jsonl.py not found at {build_script}"
            )

        cmd = [sys.executable, str(build_script)]
        if request.source_id:
            cmd += ["--source-id", request.source_id]
        if request.snapshot_id:
            cmd += ["--snapshot-id", request.snapshot_id]
        if request.rebuild:
            cmd += ["--rebuild"]

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

        processing_time = (datetime.now() - start_time).total_seconds()

        return GraphBuildResponse(
            success=True,
            message=f"Knowledge Graph 생성 완료: {node_count} 노드, {edge_count} 엣지",
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


@router.get("/status", response_model=GraphStatusResponse)
async def get_graph_status(source_id: Optional[str] = None):
    """
    Knowledge Graph 상태를 조회합니다.
    """
    try:
        from app.api.graph import _load_graph, _manifest

        cache = _load_graph(source_id)
        manifest = _manifest(source_id)

        if not cache["nodes"]:
            status = "empty"
        else:
            status = "ready"

        return GraphStatusResponse(
            status=status,
            node_count=len(cache["nodes"]),
            edge_count=len(cache["edges"]),
            built_at=manifest.get("built_at"),
            schema_version=manifest.get("schema_version", "phase2"),
            snapshot_id=manifest.get("snapshot_id")
        )

    except Exception as e:
        return GraphStatusResponse(
            status="error",
            node_count=0,
            edge_count=0
        )


@router.get("/preview", response_model=GraphPreviewResponse)
async def get_graph_preview(
    source_id: Optional[str] = None,
    node_type: Optional[str] = None,
    limit: int = 100
):
    """
    Knowledge Graph 미리보기 데이터를 반환합니다.
    """
    try:
        from app.api.graph import _load_graph

        cache = _load_graph(source_id)

        # 노드 타입별 카운트
        node_type_counts: Dict[str, int] = {}
        for node in cache["nodes"]:
            nt = node.get("type", "unknown")
            node_type_counts[nt] = node_type_counts.get(nt, 0) + 1

        # 관계 타입별 카운트
        relation_type_counts: Dict[str, int] = {}
        for edge in cache["edges"]:
            rel = edge.get("relation", "unknown")
            relation_type_counts[rel] = relation_type_counts.get(rel, 0) + 1

        # 노드 필터링
        filtered_nodes = cache["nodes"]
        if node_type:
            filtered_nodes = [n for n in cache["nodes"] if n.get("type") == node_type]

        # limit 적용
        nodes = [
            NodeInfo(
                id=n.get("id", ""),
                type=n.get("type", ""),
                label=n.get("label", n.get("name", "")),
                properties={k: v for k, v in n.items() if k not in ["id", "type", "label", "name"]}
            )
            for n in filtered_nodes[:limit]
        ]

        # 관련 엣지만 반환
        node_ids = {n.id for n in nodes}
        edges = [
            EdgeInfo(
                source=e.get("source", ""),
                target=e.get("target", ""),
                relation=e.get("relation", ""),
                properties={k: v for k, v in e.items() if k not in ["source", "target", "relation"]}
            )
            for e in cache["edges"]
            if e.get("source") in node_ids or e.get("target") in node_ids
        ][:limit]

        return GraphPreviewResponse(
            success=True,
            node_count=len(cache["nodes"]),
            edge_count=len(cache["edges"]),
            nodes=nodes,
            edges=edges,
            node_type_counts=node_type_counts,
            relation_type_counts=relation_type_counts
        )

    except Exception as e:
        return GraphPreviewResponse(
            success=False,
            node_count=0,
            edge_count=0
        )


@router.post("/validate", response_model=GraphValidationResult)
async def validate_graph(source_id: Optional[str] = None):
    """
    Knowledge Graph를 검증합니다.
    """
    try:
        from app.api.graph import _load_graph

        cache = _load_graph(source_id)

        nodes = cache["nodes"]
        edges = cache["edges"]

        warnings: List[str] = []
        errors: List[str] = []

        # 노드 ID 집합
        node_ids = {n.get("id") for n in nodes}

        # 고아 노드 찾기 (연결된 엣지가 없는 노드)
        connected_nodes = set()
        for edge in edges:
            connected_nodes.add(edge.get("source"))
            connected_nodes.add(edge.get("target"))

        orphan_nodes = len(node_ids - connected_nodes)
        if orphan_nodes > 0:
            warnings.append(f"{orphan_nodes}개의 고아 노드 발견 (연결된 관계 없음)")

        # 존재하지 않는 노드를 참조하는 엣지 찾기
        missing_relations: List[str] = []
        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            if source not in node_ids:
                missing_relations.append(f"Missing source node: {source}")
            if target not in node_ids:
                missing_relations.append(f"Missing target node: {target}")

        if missing_relations:
            errors.extend(missing_relations[:10])  # 최대 10개만
            if len(missing_relations) > 10:
                errors.append(f"... and {len(missing_relations) - 10} more")

        # 유효성 판정
        valid = len(errors) == 0

        return GraphValidationResult(
            valid=valid,
            total_nodes=len(nodes),
            total_edges=len(edges),
            orphan_nodes=orphan_nodes,
            missing_relations=missing_relations[:20],
            warnings=warnings,
            errors=errors
        )

    except Exception as e:
        return GraphValidationResult(
            valid=False,
            errors=[f"Validation failed: {str(e)}"]
        )


@router.get("/stats")
async def get_graph_stats(source_id: Optional[str] = None):
    """
    Knowledge Graph 통계를 조회합니다.
    """
    try:
        from app.api.graph import _load_graph

        cache = _load_graph(source_id)

        # 노드 타입별 카운트
        node_type_counts: Dict[str, int] = {}
        for node in cache["nodes"]:
            node_type = node.get("type", "unknown")
            node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1

        # 관계 타입별 카운트
        relation_type_counts: Dict[str, int] = {}
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
