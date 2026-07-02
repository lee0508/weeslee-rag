# Snapshot 관리 API - Dataset과 Snapshot 통합 버전 관리
from datetime import datetime
from pathlib import Path
from typing import Optional
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.dataset_context import (
    ensure_source_dataset_context,
    get_source_dataset_context,
    generate_dataset_id,
)
from app.services.active_snapshot_state import (
    get_active_snapshot_state,
    save_active_snapshot_state,
)
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
FAISS_DIR = DATA_DIR / "indexes" / "faiss"

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


def _parse_snapshot_ids(snapshot_id: str) -> tuple[Optional[str], Optional[str]]:
    """snapshot_id에서 source_id, dataset_id 추출 (표준화)"""
    source_id = None
    dataset_id = None
    if snapshot_id:
        # snapshot_20260616_rag_source_v1 또는 snapshot_20260616_V1 형식 파싱
        parts = snapshot_id.replace("snapshot_", "").split("_")
        if len(parts) >= 2:
            date_part = parts[0]  # YYYYMMDD
            # source_id 추출 (v로 시작하는 버전 부분 제외)
            source_parts = [p for p in parts[1:] if not p.lower().startswith("v")]
            if source_parts:
                source_id = "_".join(source_parts)
            if source_id:
                source_context = get_source_dataset_context(source_id)
                dataset_id = source_context.get("dataset_id") or generate_dataset_id(
                    source_id,
                    f"{date_part}T00:00:00+00:00",
                )
    return source_id, dataset_id


def _load_faiss_manifest(snapshot_id: str) -> Optional[dict]:
    if not snapshot_id:
        return None
    manifest_file = FAISS_DIR / f"{snapshot_id}_ollama.manifest.json"
    if not manifest_file.exists():
        return None
    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _resolve_snapshot_ids(snapshot_id: str) -> tuple[Optional[str], Optional[str]]:
    """Snapshot manifest를 우선 사용해 source_id / dataset_id를 해석한다."""
    snapshot = _load_snapshot(snapshot_id) if snapshot_id else None
    if snapshot:
        source_id = (snapshot.dataset.source_id or "").strip() or None
        dataset_id = (snapshot.dataset.dataset_id or "").strip() or None
        if source_id or dataset_id:
            return source_id, dataset_id
    faiss_manifest = _load_faiss_manifest(snapshot_id)
    if faiss_manifest:
        counts_by_source = faiss_manifest.get("counts_by_source") or {}
        if isinstance(counts_by_source, dict) and len(counts_by_source) == 1:
            source_id = next(iter(counts_by_source.keys()), "").strip() or None
            if source_id:
                source_context = get_source_dataset_context(source_id)
                dataset_id = source_context.get("dataset_id") or None
                return source_id, dataset_id
    return _parse_snapshot_ids(snapshot_id)


def _resolve_embedding_provider(snapshot: Optional[SnapshotManifest], fallback: Optional[str] = None) -> str:
    """provider 이름을 반환한다. 모델명(bge-m3 등)을 provider로 저장하지 않는다."""
    value = str(fallback or "").strip().lower()
    if value in {"ollama", "openai", "gemini", "openrouter", "hashing"}:
        return value
    return "ollama"


def _load_active_config() -> Optional[ActiveSnapshotConfig]:
    """활성 Snapshot 설정 로드.

    권장 계약:
    - active_snapshot_id: 현재 운영 Snapshot ID (snapshot_20260629_src_...V1 형식)
    - faiss_index_id: 참조하는 FAISS Index ID (active_snapshot_id와 동일)

    우선순위:
    1. active_index.json (faiss/status와 동일한 소스) - 권장
    2. active_snapshot.json (확장 정보)
    """
    db_state = get_active_snapshot_state()

    # 1. active_index.json에서 읽기 (faiss/status와 동일한 소스 - 권장)
    if ACTIVE_INDEX_FILE.exists():
        with open(ACTIVE_INDEX_FILE, "r", encoding="utf-8") as f:
            index_data = json.load(f)
        # snapshot 또는 active_snapshot 키 지원 (snapshot 우선 - faiss/status 형식)
        snap_id = index_data.get("snapshot") or index_data.get("active_snapshot", "")
        if snap_id:
            snapshot = _load_snapshot(snap_id)
            faiss_manifest = _load_faiss_manifest(snap_id)
            src_id, ds_id = _resolve_snapshot_ids(snap_id)

            # active_snapshot.json에서 추가 정보 병합 (있으면)
            extra_data = {}
            if ACTIVE_SNAPSHOT_FILE.exists():
                try:
                    with open(ACTIVE_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                        extra_data = json.load(f)
                except Exception:
                    pass

            return ActiveSnapshotConfig(
                active_snapshot_id=snap_id,
                faiss_index_id=snap_id,  # faiss_index_id는 active_snapshot_id와 동일
                index_file=(snapshot.rag_build.index_file if snapshot else None) or index_data.get("index_file"),
                metadata_file=(snapshot.rag_build.metadata_file if snapshot else None) or index_data.get("metadata_file"),
                embedding_provider=_resolve_embedding_provider(snapshot, index_data.get("embedding_provider", "ollama")),
                vector_count=(snapshot.rag_build.vector_count if snapshot else 0) or int((faiss_manifest or {}).get("vector_count") or 0) or index_data.get("vector_count", 0),
                document_count=(snapshot.dataset.document_count if snapshot else 0) or int((faiss_manifest or {}).get("document_count") or 0) or index_data.get("document_count", 0),
                chunk_count=(snapshot.rag_build.chunk_count if snapshot else 0) or int((faiss_manifest or {}).get("vector_count") or 0) or index_data.get("chunk_count", 0),
                activated_at=datetime.fromisoformat(index_data["activated_at"]) if index_data.get("activated_at") else None,
                source_id=src_id or extra_data.get("source_id") or db_state.get("source_id"),
                dataset_id=ds_id or extra_data.get("dataset_id") or db_state.get("dataset_id"),
                tag_keyword_build_id=extra_data.get("tag_keyword_build_id") or db_state.get("tag_keyword_build_id"),
                graph_build_id=extra_data.get("graph_build_id") or db_state.get("graph_build_id"),
                ontology_id=extra_data.get("ontology_id") or db_state.get("ontology_id"),
                wiki_build_id=extra_data.get("wiki_build_id") or db_state.get("wiki_build_id"),
                previous_snapshot_id=extra_data.get("previous_snapshot_id") or db_state.get("previous_snapshot_id"),
                rollback_available=extra_data.get("rollback_available", False) or bool(db_state.get("rollback_available")),
            )

    # 2. active_snapshot.json만 있는 경우 (fallback)
    if ACTIVE_SNAPSHOT_FILE.exists():
        with open(ACTIVE_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        config = ActiveSnapshotConfig(**data)
        snapshot = _load_snapshot(config.active_snapshot_id) if config.active_snapshot_id else None
        faiss_manifest = _load_faiss_manifest(config.active_snapshot_id)
        src_id, ds_id = _resolve_snapshot_ids(config.active_snapshot_id)
        if src_id:
            config.source_id = src_id
        if ds_id:
            config.dataset_id = ds_id
        # faiss_index_id를 active_snapshot_id와 동일하게 설정
        config.faiss_index_id = config.active_snapshot_id
        if snapshot:
            config.index_file = snapshot.rag_build.index_file or config.index_file
            config.metadata_file = snapshot.rag_build.metadata_file or config.metadata_file
            config.vector_count = snapshot.rag_build.vector_count or config.vector_count
            config.document_count = snapshot.dataset.document_count or config.document_count
            config.chunk_count = snapshot.rag_build.chunk_count or config.chunk_count
            config.embedding_provider = _resolve_embedding_provider(snapshot, config.embedding_provider)
        if faiss_manifest:
            config.vector_count = int(faiss_manifest.get("vector_count") or config.vector_count or 0)
            config.document_count = int(faiss_manifest.get("document_count") or config.document_count or 0)
            config.chunk_count = int(faiss_manifest.get("vector_count") or config.chunk_count or 0)
        return config

    if db_state.get("active_snapshot_id"):
        activated_at = None
        if db_state.get("activated_at"):
            try:
                activated_at = datetime.fromisoformat(str(db_state["activated_at"]))
            except Exception:
                activated_at = None
        return ActiveSnapshotConfig(
            active_snapshot_id=str(db_state.get("active_snapshot_id") or ""),
            faiss_index_id=str(db_state.get("faiss_index_id") or db_state.get("active_snapshot_id") or ""),
            index_file=db_state.get("index_file"),
            metadata_file=db_state.get("metadata_file"),
            embedding_provider=str(db_state.get("embedding_provider") or "ollama"),
            vector_count=int(db_state.get("vector_count") or 0),
            document_count=int(db_state.get("document_count") or 0),
            chunk_count=int(db_state.get("chunk_count") or 0),
            source_id=db_state.get("source_id"),
            dataset_id=db_state.get("dataset_id"),
            tag_keyword_build_id=db_state.get("tag_keyword_build_id"),
            graph_build_id=db_state.get("graph_build_id"),
            ontology_id=db_state.get("ontology_id"),
            wiki_build_id=db_state.get("wiki_build_id"),
            activated_at=activated_at,
            activated_by=db_state.get("activated_by"),
            previous_snapshot_id=db_state.get("previous_snapshot_id"),
            rollback_available=bool(db_state.get("rollback_available")),
        )

    return None


def _save_active_config(config: ActiveSnapshotConfig):
    """활성 Snapshot 설정 저장 - 두 파일 모두 업데이트.

    권장 계약:
    - active_index.json의 snapshot 키: snapshot_20260629_src_...V1 형식 사용
    - faiss/status와 snapshot/active가 동일한 snapshot ID 반환
    """
    _ensure_dirs()

    # 저장 파일도 권장 계약을 그대로 유지한다.
    config.faiss_index_id = config.active_snapshot_id
    config.embedding_provider = _resolve_embedding_provider(None, config.embedding_provider)

    save_active_snapshot_state(
        {
            "active_snapshot_id": config.active_snapshot_id,
            "snapshot_id": config.active_snapshot_id,
            "faiss_index_id": config.faiss_index_id,
            "source_id": config.source_id,
            "dataset_id": config.dataset_id,
            "index_file": config.index_file,
            "metadata_file": config.metadata_file,
            "embedding_provider": config.embedding_provider,
            "vector_count": config.vector_count,
            "document_count": config.document_count,
            "chunk_count": config.chunk_count,
            "tag_keyword_build_id": config.tag_keyword_build_id,
            "graph_build_id": config.graph_build_id,
            "ontology_id": config.ontology_id,
            "wiki_build_id": config.wiki_build_id,
            "activated_at": config.activated_at.isoformat() if config.activated_at else "",
            "activated_by": config.activated_by,
            "previous_snapshot_id": config.previous_snapshot_id,
            "rollback_available": config.rollback_available,
        }
    )

    # 1. active_snapshot.json 저장 (확장 정보)
    with open(ACTIVE_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(config.dict(), f, ensure_ascii=False, indent=2, default=str)

    # 2. active_index.json 업데이트 (RAG 검색 + faiss/status 공용)
    # snapshot 키 사용 (faiss/status 형식과 일치)
    index_format = {
        "snapshot": config.active_snapshot_id,  # 권장 계약: snapshot 키 사용
        "index_file": config.index_file,
        "metadata_file": config.metadata_file,
        "embedding_provider": config.embedding_provider,
        "vector_count": config.vector_count,
        "document_count": config.document_count,
        "source_count": 1,
        "activated_at": config.activated_at.isoformat() if config.activated_at else None,
    }
    with open(ACTIVE_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index_format, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# API Request/Response Models
# ═══════════════════════════════════════════════════════════════════════════

class CreateSnapshotRequest(BaseModel):
    """Snapshot 생성 요청"""
    source_id: Optional[str] = None
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

    source_id = (body.source_id or "").strip()
    if not source_id:
        raise HTTPException(status_code=400, detail="source_id는 필수입니다.")

    # Snapshot ID 생성
    date_str = datetime.now().strftime("%Y%m%d")
    version = 1

    # 기존 Snapshot 확인하여 버전 증가
    existing = list(SNAPSHOT_DIR.glob(f"snapshot_{date_str}_{source_id}_v*.json"))
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

    snapshot_id = f"snapshot_{date_str}_{source_id}_v{version}"
    source_context, _ = ensure_source_dataset_context(source_id)
    dataset_id = (
        source_context.get("dataset_id")
        if source_context
        else generate_dataset_id(source_id)
    )

    # 문서 수 조회
    db = SessionLocal()
    try:
        doc_count = db.query(DocumentMetadata).filter(
            DocumentMetadata.source_id == source_id
        ).count()
    finally:
        db.close()

    # Snapshot 생성
    snapshot = SnapshotManifest(
        snapshot_id=snapshot_id,
        snapshot_name=body.snapshot_name or f"{source_id} - {date_str} v{version}",
        description=body.description,
        dataset=DatasetInfo(
            dataset_id=dataset_id,
            source_id=source_id,
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
        faiss_index_id=snapshot.snapshot_id,
        index_file=snapshot.rag_build.index_file,
        metadata_file=snapshot.rag_build.metadata_file,
        embedding_provider="ollama",
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
async def delete_snapshot_endpoint(snapshot_id: str, force: bool = False):
    """Snapshot 및 연관 데이터 삭제 (활성 Snapshot은 삭제 불가)

    삭제 대상:
    - Snapshot manifest
    - FAISS Index 파일
    - 청크 데이터 (staged/chunks/)
    - 메타데이터 (staged/metadata/)
    - 그래프 데이터 (graph/)
    - Wiki 데이터 (wiki/)
    """
    from app.services.snapshot_manager import delete_snapshot as delete_snapshot_service

    snapshot = _load_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_id}' not found")

    if snapshot.is_active and not force:
        raise HTTPException(status_code=400, detail="활성 Snapshot은 삭제할 수 없습니다. force=true로 강제 삭제 가능합니다.")

    try:
        result = delete_snapshot_service(snapshot_id, force=force)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "success": True,
        "message": f"Snapshot '{snapshot_id}' 및 연관 데이터 삭제 완료",
        "deleted_files": result.get("deleted_files", []),
        "deleted_dirs": result.get("deleted_dirs", []),
        "deleted_count": result.get("deleted_count", 0),
        "db_updates": result.get("db_updates", {}),
    }
