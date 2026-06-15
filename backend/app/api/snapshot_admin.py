# Snapshot 관리 API - Dataset과 Snapshot 통합 버전 관리
from datetime import datetime
from pathlib import Path
from typing import Optional
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.snapshot_manifest import (
    SnapshotManifest,
    SnapshotStatus,
    DatasetInfo,
    MetadataBuildInfo,
    TagKeywordBuildInfo,
    RAGBuildInfo,
    GraphBuildInfo,
    WikiBuildInfo,
    ActiveSnapshotConfig,
)


router = APIRouter(prefix="/snapshot", tags=["Snapshot Admin"])

# 데이터 경로 - RAG 검색과 동일한 경로 사용
DATA_DIR = Path("/data/weeslee/weeslee-rag/data")
SNAPSHOT_DIR = DATA_DIR / "snapshots"

# 메인 active_index.json - RAG 검색이 사용하는 파일 (data/active_index.json)
ACTIVE_INDEX_FILE = DATA_DIR / "active_index.json"

# 새 Snapshot Manifest 설정 파일
ACTIVE_SNAPSHOT_FILE = DATA_DIR / "active_snapshot.json"


def _ensure_dirs():
    """필요한 디렉토리 생성"""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _load_snapshot(snapshot_id: str) -> Optional[SnapshotManifest]:
    """Snapshot 파일 로드"""
    snapshot_file = SNAPSHOT_DIR / f"{snapshot_id}.json"
    if not snapshot_file.exists():
        return None
    with open(snapshot_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return SnapshotManifest(**data)


def _save_snapshot(snapshot: SnapshotManifest):
    """Snapshot 파일 저장"""
    _ensure_dirs()
    snapshot_file = SNAPSHOT_DIR / f"{snapshot.snapshot_id}.json"
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot.dict(), f, ensure_ascii=False, indent=2, default=str)


def _load_active_config() -> Optional[ActiveSnapshotConfig]:
    """활성 Snapshot 설정 로드 - data/active_index.json에서 읽기"""
    # 1. 새 active_snapshot.json 파일이 있으면 우선 사용
    if ACTIVE_SNAPSHOT_FILE.exists():
        with open(ACTIVE_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ActiveSnapshotConfig(**data)

    # 2. 기존 active_index.json에서 읽기 (RAG 검색이 사용하는 파일)
    if ACTIVE_INDEX_FILE.exists():
        with open(ACTIVE_INDEX_FILE, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        # active_snapshot 또는 snapshot 키 지원 (하위 호환성)
        snap_id = old_data.get("active_snapshot") or old_data.get("snapshot", "")
        return ActiveSnapshotConfig(
            active_snapshot_id=snap_id,
            faiss_index_id=snap_id,
            index_file=old_data.get("index_file"),
            metadata_file=old_data.get("metadata_file"),
            embedding_provider=old_data.get("embedding_provider", "ollama"),
            vector_count=old_data.get("vector_count", 0),
            document_count=old_data.get("document_count", 0),
            activated_at=datetime.fromisoformat(old_data["activated_at"]) if old_data.get("activated_at") else None,
        )

    return None


def _save_active_config(config: ActiveSnapshotConfig):
    """활성 Snapshot 설정 저장 - 두 파일 모두 업데이트"""
    _ensure_dirs()

    # 1. 새 active_snapshot.json 저장 (확장 정보)
    with open(ACTIVE_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(config.dict(), f, ensure_ascii=False, indent=2, default=str)

    # 2. 기존 active_index.json 업데이트 (RAG 검색 호환성 - 필수)
    # RAG 검색이 이 파일을 읽으므로 반드시 업데이트해야 함
    old_format = {
        "active_snapshot": config.faiss_index_id or config.active_snapshot_id,
        "index_file": config.index_file,
        "metadata_file": config.metadata_file,
        "embedding_provider": config.embedding_provider,
        "vector_count": config.vector_count,
        "document_count": config.document_count,
        "source_count": 1,
        "activated_at": config.activated_at.isoformat() if config.activated_at else None,
    }
    with open(ACTIVE_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(old_format, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# API Request/Response Models
# ═══════════════════════════════════════════════════════════════════════════

class CreateSnapshotRequest(BaseModel):
    """Snapshot 생성 요청"""
    source_id: str = "rag_source"
    snapshot_name: Optional[str] = None
    description: Optional[str] = None
    parent_snapshot_id: Optional[str] = None


class UpdateSnapshotBuildRequest(BaseModel):
    """Snapshot 빌드 정보 업데이트 요청"""
    snapshot_id: str
    build_type: str  # metadata, tag_keyword, rag, graph, wiki
    build_data: dict


class ActivateSnapshotRequest(BaseModel):
    """Snapshot 활성화 요청"""
    snapshot_id: str
    activated_by: Optional[str] = "admin"


# ═══════════════════════════════════════════════════════════════════════════
# API Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/active")
async def get_active_snapshot():
    """현재 활성 Snapshot 조회"""
    config = _load_active_config()
    if not config:
        return {
            "success": False,
            "message": "활성화된 Snapshot이 없습니다.",
            "active_snapshot": None,
        }

    # 상세 Snapshot 정보 로드 시도
    snapshot = _load_snapshot(config.active_snapshot_id) if config.active_snapshot_id else None

    return {
        "success": True,
        "active_config": config.dict(),
        "snapshot_detail": snapshot.get_build_summary() if snapshot else None,
    }


@router.get("/list")
async def list_snapshots(source_id: Optional[str] = None, limit: int = 20):
    """Snapshot 목록 조회"""
    _ensure_dirs()

    snapshots = []
    for f in SNAPSHOT_DIR.glob("*.json"):
        try:
            snap = _load_snapshot(f.stem)
            if snap:
                if source_id and snap.dataset.source_id != source_id:
                    continue
                snapshots.append(snap.get_build_summary())
        except Exception:
            continue

    # 최신순 정렬
    snapshots.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return {
        "success": True,
        "count": len(snapshots),
        "snapshots": snapshots[:limit],
    }


@router.get("/detail/{snapshot_id}")
async def get_snapshot_detail(snapshot_id: str):
    """Snapshot 상세 조회"""
    snapshot = _load_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_id}' not found")

    return {
        "success": True,
        "snapshot": snapshot.dict(),
    }


@router.post("/create")
async def create_snapshot(body: CreateSnapshotRequest):
    """새 Snapshot 생성 (Draft 상태)"""
    from app.core.database import SessionLocal
    from app.models.document_metadata import DocumentMetadata

    # Snapshot ID 생성
    date_str = datetime.now().strftime("%Y%m%d")
    version = 1

    # 기존 Snapshot 확인하여 버전 증가
    existing = list(SNAPSHOT_DIR.glob(f"snapshot_{date_str}_{body.source_id}_v*.json"))
    if existing:
        versions = []
        for f in existing:
            try:
                v = int(f.stem.split("_v")[-1])
                versions.append(v)
            except:
                pass
        if versions:
            version = max(versions) + 1

    snapshot_id = f"snapshot_{date_str}_{body.source_id}_v{version}"
    dataset_id = f"dataset_{body.source_id}_{date_str}"

    # 문서 수 조회
    db = SessionLocal()
    try:
        doc_count = db.query(DocumentMetadata).filter(
            DocumentMetadata.source_id == body.source_id
        ).count()
    finally:
        db.close()

    # Snapshot 생성
    snapshot = SnapshotManifest(
        snapshot_id=snapshot_id,
        snapshot_name=body.snapshot_name or f"{body.source_id} - {date_str} v{version}",
        description=body.description,
        dataset=DatasetInfo(
            dataset_id=dataset_id,
            source_id=body.source_id,
            document_count=doc_count,
            scan_completed_at=datetime.utcnow(),
        ),
        status=SnapshotStatus.DRAFT,
        version=version,
        parent_snapshot_id=body.parent_snapshot_id,
        created_at=datetime.utcnow(),
    )

    _save_snapshot(snapshot)

    return {
        "success": True,
        "message": f"Snapshot '{snapshot_id}' 생성 완료",
        "snapshot_id": snapshot_id,
        "dataset_id": dataset_id,
        "document_count": doc_count,
    }


@router.post("/update-build")
async def update_snapshot_build(body: UpdateSnapshotBuildRequest):
    """Snapshot의 특정 빌드 정보 업데이트"""
    snapshot = _load_snapshot(body.snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot '{body.snapshot_id}' not found")

    build_type = body.build_type
    build_data = body.build_data

    if build_type == "metadata":
        snapshot.metadata_build = MetadataBuildInfo(**build_data)
        snapshot.dataset.metadata_extracted_count = build_data.get("document_count", 0)
    elif build_type == "tag_keyword":
        snapshot.tag_keyword = TagKeywordBuildInfo(**build_data)
    elif build_type == "rag":
        snapshot.rag_build = RAGBuildInfo(**build_data)
    elif build_type == "graph":
        snapshot.graph_build = GraphBuildInfo(**build_data)
    elif build_type == "wiki":
        snapshot.wiki_build = WikiBuildInfo(**build_data)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown build_type: {build_type}")

    _save_snapshot(snapshot)

    return {
        "success": True,
        "message": f"Snapshot '{body.snapshot_id}' {build_type} 빌드 정보 업데이트 완료",
        "snapshot": snapshot.get_build_summary(),
    }


@router.post("/validate/{snapshot_id}")
async def validate_snapshot(snapshot_id: str):
    """Snapshot 검증 및 상태 변경"""
    snapshot = _load_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_id}' not found")

    # 필수 빌드 확인
    issues = []
    if not snapshot.rag_build.faiss_index_id:
        issues.append("FAISS Index가 빌드되지 않았습니다.")
    if snapshot.rag_build.vector_count == 0:
        issues.append("Vector가 없습니다.")

    if issues:
        return {
            "success": False,
            "message": "Snapshot 검증 실패",
            "issues": issues,
            "status": snapshot.status.value,
        }

    snapshot.status = SnapshotStatus.VALIDATED
    _save_snapshot(snapshot)

    return {
        "success": True,
        "message": f"Snapshot '{snapshot_id}' 검증 완료",
        "status": snapshot.status.value,
    }


@router.post("/activate")
async def activate_snapshot(body: ActivateSnapshotRequest):
    """Snapshot 활성화 (서비스 전환)"""
    snapshot = _load_snapshot(body.snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot '{body.snapshot_id}' not found")

    # 현재 활성 Snapshot 비활성화
    current_config = _load_active_config()
    previous_snapshot_id = None
    if current_config and current_config.active_snapshot_id:
        previous_snapshot_id = current_config.active_snapshot_id
        prev_snapshot = _load_snapshot(previous_snapshot_id)
        if prev_snapshot:
            prev_snapshot.is_active = False
            prev_snapshot.status = SnapshotStatus.ARCHIVED
            prev_snapshot.archived_at = datetime.utcnow()
            _save_snapshot(prev_snapshot)

    # 새 Snapshot 활성화
    snapshot.is_active = True
    snapshot.status = SnapshotStatus.ACTIVE
    snapshot.activated_at = datetime.utcnow()
    snapshot.activated_by = body.activated_by
    _save_snapshot(snapshot)

    # 활성 설정 저장
    new_config = ActiveSnapshotConfig(
        active_snapshot_id=snapshot.snapshot_id,
        faiss_index_id=snapshot.rag_build.faiss_index_id,
        index_file=snapshot.rag_build.index_file,
        metadata_file=snapshot.rag_build.metadata_file,
        embedding_provider=snapshot.rag_build.embedding_model.split("/")[-1] if snapshot.rag_build.embedding_model else "ollama",
        vector_count=snapshot.rag_build.vector_count,
        document_count=snapshot.dataset.document_count,
        chunk_count=snapshot.rag_build.chunk_count,
        dataset_id=snapshot.dataset.dataset_id,
        source_id=snapshot.dataset.source_id,
        tag_keyword_build_id=snapshot.tag_keyword.tag_keyword_build_id,
        graph_build_id=snapshot.graph_build.graph_build_id,
        ontology_id=snapshot.graph_build.ontology_id,
        wiki_build_id=snapshot.wiki_build.wiki_build_id,
        activated_at=snapshot.activated_at,
        activated_by=body.activated_by,
        previous_snapshot_id=previous_snapshot_id,
        rollback_available=previous_snapshot_id is not None,
    )
    _save_active_config(new_config)

    return {
        "success": True,
        "message": f"Snapshot '{body.snapshot_id}' 활성화 완료",
        "active_snapshot": snapshot.snapshot_id,
        "previous_snapshot": previous_snapshot_id,
        "rollback_available": previous_snapshot_id is not None,
    }


@router.post("/rollback")
async def rollback_snapshot():
    """이전 Snapshot으로 롤백"""
    config = _load_active_config()
    if not config or not config.previous_snapshot_id:
        raise HTTPException(status_code=400, detail="롤백 가능한 이전 Snapshot이 없습니다.")

    # 이전 Snapshot으로 활성화
    return await activate_snapshot(ActivateSnapshotRequest(
        snapshot_id=config.previous_snapshot_id,
        activated_by="rollback",
    ))


@router.delete("/{snapshot_id}")
async def delete_snapshot(snapshot_id: str):
    """Snapshot 삭제 (활성 Snapshot은 삭제 불가)"""
    snapshot = _load_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_id}' not found")

    if snapshot.is_active:
        raise HTTPException(status_code=400, detail="활성 Snapshot은 삭제할 수 없습니다.")

    snapshot_file = SNAPSHOT_DIR / f"{snapshot_id}.json"
    snapshot_file.unlink()

    return {
        "success": True,
        "message": f"Snapshot '{snapshot_id}' 삭제 완료",
    }
