# -*- coding: utf-8 -*-
"""
FAISS pipeline job runner.

Runs the 4-stage pipeline (extract → chunk → faiss → category-indexes)
as an async subprocess chain and emits progress events via asyncio.Queue.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"
DATA_DIR = PROJECT_ROOT / "data"
ACTIVE_INDEX_PATH = DATA_DIR / "active_index.json"

# job_id → job state dict
_jobs: dict[str, dict] = {}


def create_job(snapshot: str) -> str:
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {
        "job_id": job_id,
        "snapshot": snapshot,
        "status": "pending",
        "progress": 0,
        "stage": "",
        "log": [],
        "error": None,
        "created_at": datetime.now().isoformat(),
        "queue": asyncio.Queue(),
    }
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    return _jobs.get(job_id)


def list_jobs() -> list[dict]:
    return [
        {k: v for k, v in j.items() if k != "queue"}
        for j in reversed(list(_jobs.values()))
    ]


def _paths(snapshot: str) -> dict[str, Path]:
    manifest_dir = DATA_DIR / "staged" / "manifest"
    return {
        "manifest_csv":   manifest_dir / f"{snapshot}_manifest.csv",
        "summary_csv":    manifest_dir / f"{snapshot}_manifest_extraction_summary.csv",
        "text_dir":       DATA_DIR / "staged" / "text",
        "metadata_dir":   DATA_DIR / "staged" / "metadata",
        "chunks_dir":     DATA_DIR / "staged" / "chunks",
        "chunks_jsonl":   DATA_DIR / "staged" / "chunks" / f"{snapshot}_chunks.jsonl",
        "faiss_dir":      DATA_DIR / "indexes" / "faiss",
        "index_path":     DATA_DIR / "indexes" / "faiss" / f"{snapshot}_ollama.index",
        "meta_path":      DATA_DIR / "indexes" / "faiss" / f"{snapshot}_ollama_metadata.jsonl",
    }


async def run_pipeline(job_id: str) -> None:
    job = _jobs[job_id]
    q: asyncio.Queue = job["queue"]
    snapshot = job["snapshot"]
    p = _paths(snapshot)

    def emit(pct: int, stage: str, log: str = "") -> None:
        job["progress"] = pct
        job["stage"] = stage
        if log:
            job["log"].append(log)
        q.put_nowait({"progress": pct, "stage": stage, "log": log})

    job["status"] = "running"
    emit(0, "파이프라인 시작")

    try:
        # ── Stage 1: manifest CSV 확인 (5%) ───────────────────────────────
        emit(5, "manifest CSV 확인")
        if not p["manifest_csv"].exists():
            raise FileNotFoundError(
                f"Manifest CSV 없음: {p['manifest_csv']}\n"
                "data/staged/manifest/ 에 {snapshot}_manifest.csv 를 먼저 준비하세요."
            )
        emit(5, "manifest CSV 확인", f"OK: {p['manifest_csv'].name}")

        # ── Stage 2: 텍스트 추출 (10%) ────────────────────────────────────
        p["text_dir"].mkdir(parents=True, exist_ok=True)
        p["metadata_dir"].mkdir(parents=True, exist_ok=True)
        emit(10, "텍스트 추출 중...")
        rc = await _run_script(
            [
                "extract_manifest_batch.py",
                "--manifest-csv", str(p["manifest_csv"]),
                "--text-dir", str(p["text_dir"]),
                "--metadata-dir", str(p["metadata_dir"]),
                "--summary-csv", str(p["summary_csv"]),
                "--use-ocr",   # auto-fall-back to tesseract for scanned PDFs
            ],
            emit, 10, 50,
        )
        if rc != 0:
            raise RuntimeError("extract_manifest_batch.py 실패")

        # ── Stage 3: 청크 생성 (55%) ──────────────────────────────────────
        p["chunks_dir"].mkdir(parents=True, exist_ok=True)
        emit(55, "청크 생성 중...")
        rc = await _run_script(
            [
                "build_chunk_batch.py",
                "--summary-csv", str(p["summary_csv"]),
                "--output-jsonl", str(p["chunks_jsonl"]),
            ],
            emit, 55, 68,
        )
        if rc != 0:
            raise RuntimeError("build_chunk_batch.py 실패")

        # ── Stage 4: FAISS 인덱스 빌드 (70%) ─────────────────────────────
        p["faiss_dir"].mkdir(parents=True, exist_ok=True)
        emit(70, "FAISS 인덱스 빌드 중...")
        rc = await _run_script(
            [
                "build_faiss_index.py",
                "--chunks-jsonl", str(p["chunks_jsonl"]),
                "--output-index", str(p["index_path"]),
                "--output-metadata", str(p["meta_path"]),
                "--embedding-provider", "ollama",
            ],
            emit, 70, 88,
        )
        if rc != 0:
            raise RuntimeError("build_faiss_index.py 실패")

        # ── Stage 5: 카테고리 인덱스 (90%) ───────────────────────────────
        emit(90, "카테고리 인덱스 빌드 중...")
        rc = await _run_script(
            [
                "build_category_indexes.py",
                "--combined-chunks", str(p["chunks_jsonl"]),
                "--output-dir", str(p["faiss_dir"]),
                "--snapshot", snapshot,
                "--embedding-provider", "ollama",
            ],
            emit, 90, 93,
        )
        if rc != 0:
            emit(90, "카테고리 인덱스", "경고: build_category_indexes.py 실패 (비필수)")

        # ── Stage 6: 완료 알림 (95%) ──────────────────────────────────────
        emit(95, "준비 완료", f"인덱스 준비됨: {snapshot} — admin에서 Activate 하세요.")

        job["status"] = "completed"
        emit(100, "완료")

    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        emit(job["progress"], f"오류", str(exc))

    finally:
        q.put_nowait({"done": True})


async def _run_script(
    args: list[str],
    emit,
    pct_start: int,
    pct_end: int,
) -> int:
    """Run a pipeline script; stream stdout lines as log events."""
    script = SCRIPTS_DIR / args[0]
    cmd = [sys.executable, str(script)] + args[1:]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(SCRIPTS_DIR),
    )
    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip()
        emit(pct_start, args[0], line)
    await proc.wait()
    return proc.returncode


def activate_snapshot(snapshot: str) -> dict:
    """Write active_index.json and return the new content."""
    content = {
        "snapshot": snapshot,
        "activated_at": datetime.now().isoformat(),
    }
    ACTIVE_INDEX_PATH.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return content


def read_active_index() -> Optional[dict]:
    if not ACTIVE_INDEX_PATH.exists():
        return None
    try:
        return json.loads(ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
