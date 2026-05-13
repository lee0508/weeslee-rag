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
from app.services import faiss_job_runner as runner

router = APIRouter(
    prefix="/admin/faiss",
    tags=["FAISS Admin"],
    dependencies=[Depends(require_admin_token)],
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR     = PROJECT_ROOT / "data"
FAISS_DIR    = DATA_DIR / "indexes" / "faiss"
MANIFEST_DIR = DATA_DIR / "staged" / "manifest"
TEXT_DIR     = DATA_DIR / "staged" / "text"
META_DIR     = DATA_DIR / "staged" / "metadata"
CHUNKS_DIR   = DATA_DIR / "staged" / "chunks"

_TIMESTAMP_RE = re.compile(r"_\d{8}_\d{6}$")


# ── helpers ───────────────────────────────────────────────────────────────────

def _index_stats(snapshot: str) -> dict:
    """Return size / existence info for a snapshot's index files."""
    index_file = FAISS_DIR / f"{snapshot}_ollama.index"
    meta_file  = FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl"
    chunk_count = 0
    if meta_file.exists():
        try:
            chunk_count = sum(
                1 for line in meta_file.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        except Exception:
            pass
    return {
        "index_exists":    index_file.exists(),
        "metadata_exists": meta_file.exists(),
        "index_size_mb":   round(index_file.stat().st_size / 1_048_576, 2) if index_file.exists() else 0,
        "chunk_count":     chunk_count,
    }


def _list_snapshots() -> list[str]:
    """Return unique snapshot names found in the FAISS index directory."""
    if not FAISS_DIR.exists():
        return []
    names: set[str] = set()
    for f in FAISS_DIR.glob("*_ollama.index"):
        # strip trailing _ollama.index
        stem = f.name[: -len("_ollama.index")]
        # exclude category sub-indexes (they contain an extra underscore segment after snapshot)
        parts = stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1] in {"rfp", "proposal", "kickoff", "final_report", "presentation"}:
            continue
        names.add(stem)
    return sorted(names, reverse=True)


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def faiss_status():
    """현재 활성 인덱스 상태."""
    active = runner.read_active_index()
    if not active:
        return {"active": None, "stats": None}
    snapshot = active.get("snapshot", "")
    return {
        "active": active,
        "stats":  _index_stats(snapshot) if snapshot else None,
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


_CATEGORY_SUFFIXES = [
    "rfp", "proposal", "kickoff", "final_report", "presentation",
]


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
    """스냅샷과 관련 파일을 모두 삭제한다. 활성 인덱스는 삭제 불가."""
    active = runner.read_active_index()
    if (active or {}).get("snapshot", "") == snapshot:
        raise HTTPException(
            status_code=400,
            detail="활성 인덱스는 삭제할 수 없습니다. 다른 인덱스를 활성화한 후 삭제하세요.",
        )
    if not FAISS_DIR.exists():
        raise HTTPException(status_code=404, detail="FAISS 디렉토리가 없습니다.")

    targets = [
        FAISS_DIR / f"{snapshot}_ollama.index",
        FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl",
    ] + [
        FAISS_DIR / f"{snapshot}_{cat}_ollama.index" for cat in _CATEGORY_SUFFIXES
    ] + [
        FAISS_DIR / f"{snapshot}_{cat}_ollama_metadata.jsonl" for cat in _CATEGORY_SUFFIXES
    ]

    deleted: list[str] = []
    for f in targets:
        if f.exists():
            try:
                f.unlink()
                deleted.append(f.name)
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"삭제 실패: {f.name} — {exc}")

    if not deleted:
        raise HTTPException(status_code=404, detail=f"스냅샷 파일 없음: {snapshot}")

    return {"deleted": deleted, "snapshot": snapshot}


class StartJobRequest(BaseModel):
    snapshot: str


@router.post("/jobs")
async def start_job(req: StartJobRequest):
    """파이프라인 잡 시작 (extract → chunk → faiss → category)."""
    job_id = runner.create_job(req.snapshot)
    asyncio.create_task(runner.run_pipeline(job_id))
    return {"job_id": job_id, "snapshot": req.snapshot, "status": "running"}


@router.get("/jobs")
async def list_jobs():
    """최근 잡 목록."""
    return {"jobs": runner.list_jobs()}




class ActivateRequest(BaseModel):
    snapshot: str


@router.post("/activate")
async def activate_index(req: ActivateRequest):
    """지정한 스냅샷을 활성 인덱스로 설정."""
    stats = _index_stats(req.snapshot)
    if not stats["index_exists"]:
        raise HTTPException(
            status_code=404,
            detail=f"Index file not found for snapshot: {req.snapshot}",
        )
    result = runner.activate_snapshot(req.snapshot)
    return {"activated": result, "stats": stats}


# ── Category status ───────────────────────────────────────────────────────────

_CATEGORIES = ["rfp", "proposal", "kickoff", "final_report", "presentation"]


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

_BENCHMARK_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "run_benchmark.py"


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
