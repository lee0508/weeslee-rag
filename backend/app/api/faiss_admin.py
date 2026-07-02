# -*- coding: utf-8 -*-
"""
FAISS Index Management API.

Endpoints:
  GET    /api/admin/faiss/status              — 현재 활성 인덱스 정보
  GET    /api/admin/faiss/indexes             — 사용 가능한 인덱스 목록
  DELETE /api/admin/faiss/indexes/{snapshot}  — 스냅샷 삭제 (활성 인덱스 불가)
  POST   /api/admin/faiss/jobs                — 파이프라인 잡 시작
  GET    /api/admin/faiss/jobs                — 잡 목록
  GET    /api/admin/faiss/jobs/{job_id}/stream — SSE 진행 스트림
  GET    /api/admin/faiss/category-status     — 활성 스냅샷의 카테고리 인덱스 존재 여부
  POST   /api/admin/faiss/benchmark           — 검색 품질 벤치마크 실행
  POST   /api/admin/faiss/activate            — 스냅샷 활성화
  GET    /api/admin/faiss/staged-summary      — staged 디렉토리 파이프라인 준비 현황
"""
from __future__ import annotations

import asyncio
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.core.config import settings
from app.services import faiss_job_runner as runner
from app.services.active_snapshot_state import get_active_snapshot_state
from app.services.dataset_context import generate_dataset_id, get_source_dataset_context
from app.services.incremental_rag_service import add_documents_to_active_snapshot
from app.models.snapshot_manifest import SnapshotManifest
from app.services.rag_runtime import run_rag_query, get_active_snapshot
from app.services.snapshot_manager import delete_snapshot as delete_snapshot_service

router = APIRouter(
    prefix="/admin/faiss",
    tags=["FAISS Admin"],
    dependencies=[Depends(require_admin_token)],
)

DATA_DIR = Path(settings.data_dir).expanduser().resolve()
FAISS_DIR = Path(settings.faiss_index_dir).expanduser().resolve()
MANIFEST_DIR = Path(settings.staged_manifest_dir).expanduser().resolve()
TEXT_DIR = Path(settings.staged_text_dir).expanduser().resolve()
META_DIR = Path(settings.staged_metadata_dir).expanduser().resolve()
CHUNKS_DIR = Path(settings.staged_chunks_dir).expanduser().resolve()
SNAPSHOT_DIR = DATA_DIR / "snapshots"

_TIMESTAMP_RE = re.compile(r"_\d{8}_\d{6}$")
_CATEGORY_SUFFIXES = [
    "rfp", "proposal", "deliverable",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _snapshot_index_files(snapshot: str) -> list[tuple[Optional[str], Path, Path]]:
    files: list[tuple[Optional[str], Path, Path]] = [
        (
            None,
            FAISS_DIR / f"{snapshot}_ollama.index",
            FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl",
        )
    ]
    files.extend(
        (
            cat,
            FAISS_DIR / f"{snapshot}_{cat}_ollama.index",
            FAISS_DIR / f"{snapshot}_{cat}_ollama_metadata.jsonl",
        )
        for cat in _CATEGORY_SUFFIXES
    )
    return files

def _index_stats(snapshot: str) -> dict:
    """Return size / existence info for a snapshot's index files."""
    from datetime import datetime, timezone
    index_file = FAISS_DIR / f"{snapshot}_ollama.index"
    meta_file  = FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl"
    available_categories: list[str] = []
    existing_pairs = 0
    chunk_count = 0
    total_size_bytes = 0
    oldest_mtime: float | None = None
    for category, idx_file, md_file in _snapshot_index_files(snapshot):
        if not (idx_file.exists() and md_file.exists()):
            continue
        existing_pairs += 1
        if category:
            available_categories.append(category)
        try:
            chunk_count += sum(
                1 for line in md_file.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        except Exception:
            pass
        # 인덱스 파일 크기 합산
        try:
            total_size_bytes += idx_file.stat().st_size
        except Exception:
            pass
        # 인덱스 파일 중 가장 오래된 mtime을 생성일로 사용
        try:
            mtime = idx_file.stat().st_mtime
            if oldest_mtime is None or mtime < oldest_mtime:
                oldest_mtime = mtime
        except Exception:
            pass
    # primary index 파일의 mtime 도 확인
    if index_file.exists() and (oldest_mtime is None):
        try:
            oldest_mtime = index_file.stat().st_mtime
        except Exception:
            pass
    created_at = None
    if oldest_mtime is not None:
        created_at = datetime.fromtimestamp(oldest_mtime, tz=timezone.utc).isoformat()
    return {
        "index_exists":    existing_pairs > 0,
        "metadata_exists": existing_pairs > 0,
        "has_primary_index": index_file.exists() and meta_file.exists(),
        "available_categories": available_categories,
        "index_file_count": existing_pairs,
        "index_size_mb":   round(total_size_bytes / 1_048_576, 2),
        "chunk_count":     chunk_count,
        "created_at":      created_at,
    }


def _list_snapshots() -> list[str]:
    """Return unique snapshot names found in the FAISS index directory."""
    if not FAISS_DIR.exists():
        return []
    names: set[str] = set()
    for f in FAISS_DIR.glob("*_ollama.index"):
        # strip trailing _ollama.index
        stem = f.name[: -len("_ollama.index")]
        # category 서브 인덱스도 snapshot 후보로 포함한다.
        parts = stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1] in {"rfp", "proposal", "deliverable"}:
            names.add(parts[0])
            continue
        names.add(stem)
    return sorted(names, reverse=True)


def _normalize_embedding_model(model: Optional[str]) -> Optional[str]:
    value = str(model or "").strip()
    if not value:
        return None
    return value.split("/")[-1]


def _load_snapshot_manifest(snapshot_id: str) -> Optional[SnapshotManifest]:
    if not snapshot_id:
        return None
    snapshot_path = SNAPSHOT_DIR / f"{snapshot_id}.json"
    if not snapshot_path.exists():
        return None
    try:
        return SnapshotManifest(**json.loads(snapshot_path.read_text(encoding="utf-8")))
    except Exception:
        return None


def _load_faiss_manifest(snapshot_id: str) -> Optional[dict]:
    if not snapshot_id:
        return None
    manifest_path = FAISS_DIR / f"{snapshot_id}_ollama.manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _resolve_snapshot_source_dataset(snapshot: str, fallback_source_id: Optional[str] = None, fallback_dataset_id: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    source_id = fallback_source_id or None
    dataset_id = fallback_dataset_id or None
    snapshot_manifest = _load_snapshot_manifest(snapshot)
    faiss_manifest = _load_faiss_manifest(snapshot)

    if snapshot_manifest:
        source_id = (snapshot_manifest.dataset.source_id or "").strip() or source_id
        dataset_id = (snapshot_manifest.dataset.dataset_id or "").strip() or dataset_id
    elif faiss_manifest:
        counts_by_source = faiss_manifest.get("counts_by_source") or {}
        if isinstance(counts_by_source, dict) and len(counts_by_source) == 1:
            source_id = next(iter(counts_by_source.keys()), "").strip() or source_id
            if source_id and not dataset_id:
                dataset_id = get_source_dataset_context(source_id).get("dataset_id") or None

    if snapshot and (not source_id or not dataset_id):
        parts = snapshot.replace("snapshot_", "").split("_")
        if len(parts) >= 2:
            date_part = parts[0]
            source_parts = [p for p in parts[1:] if not p.lower().startswith("v")]
            parsed_source_id = "_".join(source_parts) if source_parts else ""
            if parsed_source_id and not source_id:
                source_id = parsed_source_id
            if source_id and not dataset_id:
                dataset_id = get_source_dataset_context(source_id).get("dataset_id") or generate_dataset_id(
                    source_id,
                    f"{date_part}T00:00:00+00:00",
                )

    return source_id, dataset_id


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def faiss_status():
    """현재 활성 인덱스 상태 및 서버 설정."""
    active = runner.read_active_index()
    snapshot = (active or {}).get("snapshot", "") or (active or {}).get("active_snapshot", "")
    db_state = get_active_snapshot_state()
    if not snapshot:
        snapshot = str(db_state.get("active_snapshot_id") or db_state.get("snapshot_id") or "").strip()
    snapshot_manifest = _load_snapshot_manifest(snapshot)
    faiss_manifest = _load_faiss_manifest(snapshot)

    source_id, dataset_id = _resolve_snapshot_source_dataset(snapshot)

    active_payload = dict(active or {})
    if snapshot:
        active_payload["snapshot"] = snapshot
    if source_id:
        active_payload["source_id"] = source_id
    elif db_state.get("source_id"):
        active_payload["source_id"] = db_state.get("source_id")
    if dataset_id:
        active_payload["dataset_id"] = dataset_id
    elif db_state.get("dataset_id"):
        active_payload["dataset_id"] = db_state.get("dataset_id")
    if snapshot_manifest:
        active_payload["vector_count"] = snapshot_manifest.rag_build.vector_count or active_payload.get("vector_count", 0)
        active_payload["document_count"] = snapshot_manifest.dataset.document_count or active_payload.get("document_count", 0)
        active_payload["chunk_count"] = snapshot_manifest.rag_build.chunk_count or active_payload.get("chunk_count", 0)
        active_payload["embedding_model"] = _normalize_embedding_model(snapshot_manifest.rag_build.embedding_model)
    elif faiss_manifest:
        active_payload["vector_count"] = int(faiss_manifest.get("vector_count") or active_payload.get("vector_count", 0) or 0)
        active_payload["document_count"] = int(faiss_manifest.get("document_count") or active_payload.get("document_count", 0) or 0)
        active_payload["chunk_count"] = int(faiss_manifest.get("vector_count") or active_payload.get("chunk_count", 0) or 0)
    else:
        active_payload["vector_count"] = int(active_payload.get("vector_count") or db_state.get("vector_count") or 0)
        active_payload["document_count"] = int(active_payload.get("document_count") or db_state.get("document_count") or 0)
        active_payload["chunk_count"] = int(active_payload.get("chunk_count") or db_state.get("chunk_count") or 0)

    active_embedding_model = (
        _normalize_embedding_model(snapshot_manifest.rag_build.embedding_model) if snapshot_manifest else None
    ) or _normalize_embedding_model(active_payload.get("embedding_model")) or settings.ollama_embed_model

    # 서버 실제 설정값 (운영 .env 기준)
    server_config = {
        "embedding_provider": settings.embedding_provider,
        "embedding_model": active_embedding_model,
        "embedding_dim": settings.embedding_dim,
        "max_embed_chars": settings.max_embed_chars,
        "ollama_host": settings.ollama_host,
        "answer_provider": settings.answer_provider,
        "answer_model": settings.answer_model,
        "active_snapshot": snapshot,  # active_index.json에서 읽은 값 사용
        "active_source_id": source_id,
        "active_dataset_id": dataset_id,
        "active_embedding_model": active_embedding_model,
    }

    if not active:
        return {
            "active": None,
            "stats": None,
            "server_config": server_config,
            "source_id": None,
            "dataset_id": None,
            "snapshot_id": None,
        }

    return {
        "active": active_payload,
        "stats":  _index_stats(snapshot) if snapshot else None,
        "server_config": server_config,
        # 명시적 ID 필드 추가 (표준화)
        "source_id": source_id,
        "dataset_id": dataset_id,
        "snapshot_id": snapshot,
    }


@router.get("/indexes")
async def list_indexes():
    """FAISS 인덱스 디렉토리에서 사용 가능한 스냅샷 목록."""
    active = runner.read_active_index()
    active_snapshot = (active or {}).get("snapshot", "")
    snapshots = _list_snapshots()
    return {
        "indexes": [
            {
                "snapshot":  s,
                "is_active": s == active_snapshot,
                **_index_stats(s),
            }
            for s in snapshots
        ]
    }

# 작성일: 2026-05-12 | 기능: 특정 스냅샷의 카테고리 서브-인덱스 상세 정보 반환
@router.get("/indexes/{snapshot}/categories")
async def snapshot_categories(snapshot: str):
    """임의 스냅샷의 카테고리별 크기·청크 수 반환."""
    cats = []
    for cat in _CATEGORY_SUFFIXES:
        idx  = FAISS_DIR / f"{snapshot}_{cat}_ollama.index"
        meta = FAISS_DIR / f"{snapshot}_{cat}_ollama_metadata.jsonl"
        chunk_count = 0
        if meta.exists():
            chunk_count = sum(1 for ln in meta.read_text(encoding="utf-8").splitlines() if ln.strip())
        cats.append({
            "category":    cat,
            "exists":      idx.exists(),
            "size_mb":     round(idx.stat().st_size / 1_048_576, 2) if idx.exists() else 0,
            "chunk_count": chunk_count,
        })
    return {"snapshot": snapshot, "categories": cats}


@router.delete("/indexes/{snapshot}")
async def delete_snapshot(snapshot: str):
    """스냅샷과 관련 산출물을 모두 삭제한다. 활성 인덱스는 삭제 불가."""
    active = runner.read_active_index()
    active_snapshot = (active or {}).get("snapshot", "") or (active or {}).get("active_snapshot", "")
    if active_snapshot == snapshot:
        raise HTTPException(
            status_code=400,
            detail="활성 인덱스는 삭제할 수 없습니다. 다른 인덱스를 활성화한 후 삭제하세요.",
        )

    try:
        result = delete_snapshot_service(snapshot, force=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"삭제 실패: {exc}")

    if not result.get("deleted_count"):
        raise HTTPException(status_code=404, detail=f"삭제할 스냅샷 산출물이 없습니다: {snapshot}")

    return {
        "success": True,
        "snapshot": snapshot,
        "deleted_files": result.get("deleted_files", []),
        "deleted_dirs": result.get("deleted_dirs", []),
        "deleted_count": result.get("deleted_count", 0),
    }


class StartJobRequest(BaseModel):
    snapshot: str
    source_id: Optional[str] = None
    start_from_stage: int = 1  # 시작 단계 (1-6)
    end_stage: int = 6  # 종료 단계 (1-6)


class AddDocumentsRequest(BaseModel):
    document_ids: list[int]
    snapshot: str = ""
    collection_key: str = ""


@router.post("/jobs")
async def start_job(req: StartJobRequest):
    """파이프라인 잡 시작 (extract → chunk → faiss → category).

    start_from_stage를 지정하면 해당 단계부터 시작합니다.
    이전 단계가 완료되어 있어야 합니다.
    """
    # stage 범위 검증
    if req.start_from_stage < 1 or req.start_from_stage > 6:
        raise HTTPException(status_code=400, detail="start_from_stage는 1-6 사이여야 합니다.")
    if req.end_stage < 1 or req.end_stage > 6:
        raise HTTPException(status_code=400, detail="end_stage는 1-6 사이여야 합니다.")
    if req.start_from_stage > req.end_stage:
        raise HTTPException(status_code=400, detail="start_from_stage는 end_stage보다 클 수 없습니다.")
    if not (req.source_id or "").strip():
        raise HTTPException(status_code=400, detail="source_id는 필수입니다.")

    job_id = runner.create_job(
        req.snapshot,
        source_id=req.source_id.strip(),
        start_from_stage=req.start_from_stage,
        end_stage=req.end_stage,
    )
    asyncio.create_task(runner.run_pipeline(job_id))
    return {
        "job_id": job_id,
        "snapshot": req.snapshot,
        "source_id": req.source_id,
        "start_from_stage": req.start_from_stage,
        "end_stage": req.end_stage,
        "status": "running",
    }


@router.get("/jobs")
async def list_jobs():
    """최근 잡 목록."""
    return {"jobs": runner.list_jobs()}


@router.post("/documents/add")
async def add_documents(req: AddDocumentsRequest):
    """선택 문서를 기존 active snapshot에 증분 추가한다."""
    if not req.document_ids:
        raise HTTPException(status_code=400, detail="document_ids is required")
    try:
        result = await add_documents_to_active_snapshot(
            document_ids=req.document_ids,
            snapshot=req.snapshot,
            collection_key=req.collection_key,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "success": True,
        "snapshot": result.snapshot,
        "document_ids": result.document_ids,
        "processed": result.processed,
        "skipped": result.skipped,
        "chunk_count": result.chunk_count,
        "category_counts": result.category_counts,
        "embedding_provider": result.embedding_provider,
    }




class ActivateRequest(BaseModel):
    snapshot: str
    source_id: Optional[str] = None
    dataset_id: Optional[str] = None


@router.post("/activate")
async def activate_index(req: ActivateRequest):
    """지정한 스냅샷을 활성 인덱스로 설정."""
    stats = _index_stats(req.snapshot)
    if not stats["index_exists"]:
        raise HTTPException(
            status_code=404,
            detail=f"Index file not found for snapshot: {req.snapshot}",
        )
    resolved_source_id, resolved_dataset_id = _resolve_snapshot_source_dataset(
        req.snapshot,
        req.source_id,
        req.dataset_id,
    )
    result = runner.activate_snapshot(req.snapshot, resolved_source_id, resolved_dataset_id)
    return {
        "activated": result,
        "stats": stats,
        "source_id": resolved_source_id,
        "dataset_id": resolved_dataset_id,
        "snapshot": req.snapshot,
    }


# ── Category status ───────────────────────────────────────────────────────────

_CATEGORIES = ["rfp", "proposal", "deliverable"]


@router.get("/category-status")
async def category_status():
    # 작성일: 2026-05-12 | 기능: 카테고리별 인덱스 크기 및 청크 수 반환
    """활성 스냅샷의 카테고리 서브-인덱스 존재 여부 + 청크 수."""
    active = runner.read_active_index()
    if not active:
        return {"snapshot": None, "categories": []}
    snapshot = active.get("snapshot", "")
    cats = []
    for cat in _CATEGORIES:
        idx  = FAISS_DIR / f"{snapshot}_{cat}_ollama.index"
        meta = FAISS_DIR / f"{snapshot}_{cat}_ollama_metadata.jsonl"
        chunk_count = 0
        if meta.exists():
            chunk_count = sum(1 for ln in meta.read_text(encoding="utf-8").splitlines() if ln.strip())
        cats.append({
            "category":    cat,
            "exists":      idx.exists(),
            "size_mb":     round(idx.stat().st_size / 1_048_576, 2) if idx.exists() else 0,
            "chunk_count": chunk_count,
        })
    return {"snapshot": snapshot, "categories": cats}


# ── Benchmark ─────────────────────────────────────────────────────────────────

_BENCHMARK_SCRIPT = Path(settings.rag_scripts_dir).expanduser().resolve() / "run_benchmark.py"


@router.post("/benchmark")
async def run_benchmark():
    """tests/queries/*.json 파일 기준으로 RAG 검색 품질 벤치마크 실행."""
    if not _BENCHMARK_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="run_benchmark.py not found")

    try:
        proc = subprocess.run(
            [sys.executable, str(_BENCHMARK_SCRIPT),
             "--server", "http://127.0.0.1:8080",
             "--answer-provider", "search_only"],
            capture_output=True, text=True, encoding="utf-8",
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Benchmark timed out (10 min)")

    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=proc.stderr.strip() or "Benchmark script failed",
        )

    # Parse the final `benchmark_complete` JSONL line
    for line in reversed(proc.stdout.strip().splitlines()):
        try:
            data = json.loads(line)
            if data.get("benchmark_complete"):
                # Also collect per-query results from previous lines
                results = []
                for prev_line in proc.stdout.strip().splitlines():
                    try:
                        ev = json.loads(prev_line)
                        if "result" in ev:
                            results.append(ev["result"])
                    except Exception:
                        pass
                return {**data, "results": results}
        except Exception:
            pass

    raise HTTPException(status_code=500, detail="Could not parse benchmark output")


# ── Staged Summary ────────────────────────────────────────────────────────────

# 작성일: 2026-05-12 | 기능: staged 디렉토리의 스냅샷별 파이프라인 준비 상태 반환
@router.get("/staged-summary")
async def staged_summary():
    """staged 디렉토리를 스캔하여 파이프라인 실행 가능 상태를 반환한다."""

    def _snapshot_from_stem(stem: str) -> str:
        """manifest 파일 stem → 스냅샷 이름 추출."""
        name = _TIMESTAMP_RE.sub("", stem)   # 말미 _YYYYMMDD_HHMMSS 제거
        name = re.sub(r"_manifest$", "", name)
        return name

    def _count_manifest(path: Path) -> int:
        try:
            if path.suffix == ".jsonl":
                return sum(1 for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())
            # CSV: 헤더 1행 제외
            with path.open("r", encoding="utf-8-sig") as f:
                return max(0, sum(1 for _ in csv.reader(f)) - 1)
        except Exception:
            return 0

    # ── manifest 파일 스캔 ────────────────────────────────────────────────
    seen: dict[str, dict] = {}  # snapshot → entry (중복 제거)
    # 매니페스트가 아닌 부가 파일 제외 패턴
    _SKIP_SUFFIXES = ("_extraction_summary", "_selection_summary", "_manifest_extraction_summary")

    if MANIFEST_DIR.exists():
        for mf in sorted(MANIFEST_DIR.glob("snapshot_*.*"), reverse=True):
            if mf.suffix not in {".csv", ".jsonl"}:
                continue
            # 집계/요약 파일 제외
            if any(mf.stem.endswith(s) for s in _SKIP_SUFFIXES):
                continue
            snapshot = _snapshot_from_stem(mf.stem)
            if not snapshot.startswith("snapshot_"):
                continue
            if snapshot in seen:
                continue  # 같은 스냅샷의 중복 파일은 첫 번째만 사용

            chunks_path = CHUNKS_DIR / f"{snapshot}_chunks.jsonl"
            chunks_exist = chunks_path.exists()
            chunks_size_mb = (
                round(chunks_path.stat().st_size / 1_048_576, 1) if chunks_exist else 0
            )
            chunk_count = 0
            if chunks_exist:
                chunk_count = sum(
                    1 for ln in chunks_path.read_text(encoding="utf-8").splitlines() if ln.strip()
                )

            faiss_indexed = (FAISS_DIR / f"{snapshot}_ollama.index").exists()

            seen[snapshot] = {
                "snapshot":       snapshot,
                "manifest_file":  mf.name,
                "doc_count":      _count_manifest(mf),
                "chunks_exist":   chunks_exist,
                "chunks_size_mb": chunks_size_mb,
                "chunk_count":    chunk_count,
                "faiss_indexed":  faiss_indexed,
            }

    # ── 전체 텍스트/메타데이터 파일 수 ───────────────────────────────────
    text_count = len(list(TEXT_DIR.glob("*.txt"))) if TEXT_DIR.exists() else 0
    meta_count = len(list(META_DIR.glob("*.json"))) if META_DIR.exists() else 0

    return {
        "snapshots": list(seen.values()),
        "totals": {
            "text_count":     text_count,
            "metadata_count": meta_count,
        },
    }


# ── 스냅샷 단계 감지 및 상태 조회 API ─────────────────────────────────────────────

@router.get("/snapshots/{snapshot}/stages")
async def get_snapshot_stages(snapshot: str):
    """스냅샷의 완료된 단계를 파일 시스템 검사로 감지한다.

    Returns:
        stages: 각 단계별 완료 여부
        recommended_start: 권장 시작 단계 (미완료된 첫 단계)
    """
    result = runner.detect_completed_stages(snapshot)
    return result


@router.get("/pipeline-state")
async def get_pipeline_state(source_id: str, snapshot: str):
    """저장된 파이프라인 상태를 조회한다.

    파이프라인 실행 중 저장된 상태 파일을 로드합니다.
    파일이 없으면 detect_completed_stages로 감지합니다.
    """
    # 저장된 상태 확인
    state = runner.load_pipeline_state(source_id, snapshot)
    if state:
        return {"source": "saved", **state}

    # 없으면 파일 시스템 감지
    detected = runner.detect_completed_stages(snapshot)
    return {"source": "detected", **detected}


@router.get("/pipeline-stages")
async def list_pipeline_stages():
    """파이프라인 단계 정보를 반환한다."""
    return {
        "stages": [
            {"stage": i, **info}
            for i, info in runner.PIPELINE_STAGES.items()
        ]
    }


# ── 검색 테스트 API ─────────────────────────────────────────────────────────────


class SearchTestRequest(BaseModel):
    query: str
    top_k: int = 5
    top_docs: int = 3
    category: Optional[str] = None
    organization: Optional[str] = None
    year: Optional[str] = None
    max_chunks_per_doc: int = 3
    mode: str = "hybrid"
    answer_provider: str = "search_only"  # 기본값: 검색만 (LLM 답변 생성 안 함)
    answer_model: str = ""


@router.post("/test-search")
async def test_search(req: SearchTestRequest):
    """활성 인덱스로 검색 테스트를 수행한다.

    LLM 답변 생성 없이 검색 결과만 반환하려면 answer_provider='search_only' 사용.
    """
    import time
    start_time = time.time()

    try:
        snapshot = get_active_snapshot()
        if not snapshot:
            raise HTTPException(status_code=404, detail="활성 인덱스가 설정되지 않았습니다.")

        result = run_rag_query(
            query=req.query,
            top_k=req.top_k,
            top_docs=req.top_docs,
            answer_provider=req.answer_provider,
            answer_model=req.answer_model,
            category=req.category,
            organization=req.organization,
            year=req.year,
            max_chunks_per_doc=req.max_chunks_per_doc,
            mode=req.mode,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "snapshot": snapshot,
            "query": req.query,
            "elapsed_ms": elapsed_ms,
            "document_count": len(result.get("documents", [])),
            "documents": result.get("documents", []),
            "results": result.get("results", []),
            "answer": result.get("answer", ""),
            "embedding_provider": result.get("embedding_provider", settings.embedding_provider),
            "mode": result.get("mode", req.mode),
        }

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"검색 오류: {str(exc)}")


# ── SSE 전용 라우터 (auth 없음 — query param 토큰으로 자체 검증) ──────────────────
# EventSource는 커스텀 헤더를 보낼 수 없으므로 router-level auth 의존성 없이 등록한다.

sse_router = APIRouter(prefix="/admin/faiss", tags=["FAISS Admin SSE"])


@sse_router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, token: Optional[str] = None):
    """SSE 스트림으로 잡 진행 상황 수신.

    브라우저 EventSource는 커스텀 헤더를 지원하지 않으므로 ?token= query param으로 인증한다.
    """
    from app.core.auth import decode_token

    if not token or not decode_token(token):
        raise HTTPException(status_code=401, detail="유효하지 않거나 만료된 토큰입니다.")

    job = runner.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    q: asyncio.Queue = job["queue"]

    async def generate():
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30)
            except asyncio.TimeoutError:
                yield "data: {\"heartbeat\": true}\n\n"
                continue

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if event.get("done"):
                break

    return StreamingResponse(generate(), media_type="text/event-stream")
