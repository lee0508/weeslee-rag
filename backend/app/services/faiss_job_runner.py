# -*- coding: utf-8 -*-
"""
FAISS pipeline job runner.

Runs the 4-stage pipeline (extract → chunk → faiss → category-indexes)
as an async subprocess chain and emits progress events via asyncio.Queue.

Pipeline Stages:
  1: manifest   - Manifest CSV 확인/생성
  2: extract    - 텍스트 추출 (OCR 포함)
  3: chunk      - 청크 생성
  4: faiss      - FAISS 인덱스 빌드
  5: category   - 카테고리 인덱스 빌드
  6: graph      - 그래프 데이터 빌드
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.rag_source_pipeline import build_manifest
from app.services.platform_store import get_record
from app.services.runtime_compute_settings import (
    build_runtime_compute_env,
    describe_stage_compute_mode,
    get_runtime_compute_settings,
)
from app.services.dataset_build_settings import get_step_config
from app.services.runtime_model_settings import get_runtime_embedding_model
from app.services.source_data_paths import get_source_paths

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"
DATA_DIR = PROJECT_ROOT / "data"
STAGED_DIR = DATA_DIR / "staged"
ACTIVE_INDEX_PATH = DATA_DIR / "active_index.json"

# job_id → job state dict
_jobs: dict[str, dict] = {}

# 파이프라인 단계 정의
PIPELINE_STAGES = {
    1: {"name": "manifest", "label": "Manifest CSV 확인", "pct_start": 0, "pct_end": 5},
    2: {"name": "extract", "label": "텍스트 추출", "pct_start": 5, "pct_end": 50},
    3: {"name": "chunk", "label": "청크 생성", "pct_start": 50, "pct_end": 68},
    4: {"name": "faiss", "label": "FAISS 인덱스 빌드", "pct_start": 68, "pct_end": 88},
    5: {"name": "category", "label": "카테고리 인덱스 빌드", "pct_start": 88, "pct_end": 93},
    6: {"name": "graph", "label": "그래프 데이터 빌드", "pct_start": 93, "pct_end": 97},
}


def create_job(
    snapshot: str,
    source_id: str,
    start_from_stage: int = 1,
    end_stage: int = 6,
) -> str:
    """파이프라인 잡을 생성한다.

    Args:
        snapshot: 스냅샷 이름
        source_id: Document Source ID
        start_from_stage: 시작 단계 (1-6). 이전 단계가 완료되어 있어야 함.
        end_stage: 종료 단계 (1-6).
    """
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {
        "job_id": job_id,
        "snapshot": snapshot,
        "source_id": source_id,
        "start_from_stage": start_from_stage,
        "end_stage": end_stage,
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


_MANIFEST_SKIP = ("_extraction_summary", "_selection_summary", "_manifest_extraction_summary")


def _find_manifest_csv(manifest_dir: Path, snapshot: str) -> Path:
    """스냅샷 이름에 맞는 실제 manifest CSV를 찾는다.

    두 가지 명명 패턴을 모두 지원한다.
      - 신버전: {snapshot}_manifest.csv
      - 구버전: {snapshot}_{YYYYMMDD}_{HHMMSS}.csv
    """
    # 신버전 우선
    preferred = manifest_dir / f"{snapshot}_manifest.csv"
    if preferred.exists():
        return preferred

    # 구버전: snapshot 이름으로 시작하는 CSV 중 요약 파일 제외
    candidates = [
        f for f in manifest_dir.glob(f"{snapshot}*.csv")
        if not any(f.stem.endswith(s) for s in _MANIFEST_SKIP)
    ]
    if candidates:
        return sorted(candidates)[0]

    # 미존재 시 오류 메시지용으로 신버전 경로 반환 (FileNotFoundError 발생시킴)
    return preferred


def _paths(snapshot: str, source_id: str = None) -> dict[str, Path]:
    """경로 딕셔너리 반환. source_id가 있으면 통합 경로 사용."""
    # 통합 경로 사용 (source_id가 있는 경우)
    if source_id:
        paths = get_source_paths(source_id)
        paths.ensure_dirs()
        return {
            "manifest_csv":   paths.base_dir / f"{snapshot}_manifest.csv",
            "summary_csv":    paths.step1_dir / f"{snapshot}_extraction_summary.csv",
            "text_dir":       paths.step2_dir,
            "metadata_dir":   paths.step4_dir,
            "chunks_dir":     paths.step3_dir,
            "chunks_jsonl":   paths.chunks_jsonl,
            "faiss_dir":      paths.step6_dir,
            "index_path":     paths.faiss_index,
            "meta_path":      paths.faiss_metadata_jsonl,
        }

    # 기존 경로 (하위 호환)
    manifest_dir = DATA_DIR / "staged" / "manifest"
    manifest_csv = _find_manifest_csv(manifest_dir, snapshot)
    return {
        "manifest_csv":   manifest_csv,
        "summary_csv":    manifest_dir / f"{snapshot}_manifest_extraction_summary.csv",
        "text_dir":       DATA_DIR / "staged" / "text",
        "metadata_dir":   DATA_DIR / "staged" / "metadata",
        "chunks_dir":     DATA_DIR / "staged" / "chunks",
        "chunks_jsonl":   DATA_DIR / "staged" / "chunks" / f"{snapshot}_chunks.jsonl",
        "faiss_dir":      DATA_DIR / "indexes" / "faiss",
        "index_path":     DATA_DIR / "indexes" / "faiss" / f"{snapshot}_ollama.index",
        "meta_path":      DATA_DIR / "indexes" / "faiss" / f"{snapshot}_ollama_metadata.jsonl",
    }


def _pipeline_state_path(source_id: str, snapshot: str) -> Path:
    """파이프라인 상태 파일 경로를 반환한다."""
    return STAGED_DIR / f"{source_id}_{snapshot}_pipeline_state.json"


def save_pipeline_state(source_id: str, snapshot: str, completed_stage: int) -> dict:
    """파이프라인 진행 상태를 저장한다."""
    STAGED_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "source_id": source_id,
        "snapshot": snapshot,
        "completed_stage": completed_stage,
        "completed_at": datetime.now().isoformat(),
        "stages": {
            str(i): {
                "name": info["name"],
                "label": info["label"],
                "completed": i <= completed_stage,
            }
            for i, info in PIPELINE_STAGES.items()
        },
    }
    state_path = _pipeline_state_path(source_id, snapshot)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def load_pipeline_state(source_id: str, snapshot: str) -> Optional[dict]:
    """저장된 파이프라인 상태를 로드한다."""
    state_path = _pipeline_state_path(source_id, snapshot)
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def detect_completed_stages(snapshot: str) -> dict:
    """파일 시스템을 검사하여 완료된 단계를 감지한다."""
    p = _paths(snapshot)
    result = {
        "snapshot": snapshot,
        "stages": {},
        "recommended_start": 1,
    }

    # Stage 1: manifest CSV 존재 여부
    manifest_exists = p["manifest_csv"].exists()
    result["stages"]["1"] = {
        "name": "manifest",
        "label": "Manifest CSV 확인",
        "completed": manifest_exists,
        "file": str(p["manifest_csv"]) if manifest_exists else None,
    }

    # Stage 2: 텍스트 추출 (summary_csv 존재 여부로 판단)
    summary_exists = p["summary_csv"].exists()
    text_count = len(list(p["text_dir"].glob("*.txt"))) if p["text_dir"].exists() else 0
    result["stages"]["2"] = {
        "name": "extract",
        "label": "텍스트 추출",
        "completed": summary_exists and text_count > 0,
        "text_count": text_count,
    }

    # Stage 3: 청크 생성
    chunks_exists = p["chunks_jsonl"].exists()
    chunk_count = 0
    if chunks_exists:
        try:
            chunk_count = sum(1 for ln in p["chunks_jsonl"].read_text(encoding="utf-8").splitlines() if ln.strip())
        except Exception:
            pass
    result["stages"]["3"] = {
        "name": "chunk",
        "label": "청크 생성",
        "completed": chunks_exists and chunk_count > 0,
        "chunk_count": chunk_count,
    }

    # Stage 4: FAISS 인덱스 빌드
    faiss_exists = p["index_path"].exists() and p["meta_path"].exists()
    result["stages"]["4"] = {
        "name": "faiss",
        "label": "FAISS 인덱스 빌드",
        "completed": faiss_exists,
    }

    # Stage 5: 카테고리 인덱스 (선택적이므로 항상 false로 표시)
    result["stages"]["5"] = {
        "name": "category",
        "label": "카테고리 인덱스 빌드",
        "completed": False,  # 비필수 단계
    }

    # Stage 6: 그래프 빌드 (선택적)
    graph_dir = DATA_DIR / "indexes" / "graph"
    graph_exists = (graph_dir / "projects.jsonl").exists() or (graph_dir / "edges.jsonl").exists()
    result["stages"]["6"] = {
        "name": "graph",
        "label": "그래프 데이터 빌드",
        "completed": graph_exists,
    }

    # 권장 시작 단계 계산
    for i in range(1, 7):
        if not result["stages"][str(i)]["completed"]:
            result["recommended_start"] = i
            break
    else:
        result["recommended_start"] = 7  # 모두 완료됨

    return result


async def run_pipeline(job_id: str) -> None:
    job = _jobs[job_id]
    q: asyncio.Queue = job["queue"]
    snapshot = job["snapshot"]
    source_id = job.get("source_id") or ""
    start_from = job.get("start_from_stage", 1)
    end_stage = job.get("end_stage", 6)
    # source_id가 있으면 통합 경로 사용
    p = _paths(snapshot, source_id=source_id if source_id else None)

    def should_run(stage: int) -> bool:
        return start_from <= stage <= end_stage

    def emit(pct: int, stage: str, log: str = "") -> None:
        job["progress"] = pct
        job["stage"] = stage
        if log:
            job["log"].append(log)
        q.put_nowait({"progress": pct, "stage": stage, "log": log})

    job["status"] = "running"
    if start_from > 1:
        emit(0, "파이프라인 재개", f"Stage {start_from}부터 시작")
    else:
        emit(0, "파이프라인 시작")

    try:
        runtime_settings = get_runtime_compute_settings()

        # ── Stage 1: manifest CSV 확인 (5%) ───────────────────────────────
        if should_run(1):
            emit(5, "manifest CSV 확인")
            if not p["manifest_csv"].exists():
                emit(5, "manifest CSV 생성", f"source_id={source_id}")
                manifest = build_manifest(snapshot_name=snapshot, source_id=source_id, overwrite=True)
                p = _paths(snapshot, source_id=source_id if source_id else None)
                emit(5, "manifest CSV 생성", f"생성 완료: {Path(manifest['manifest_csv']).name} ({manifest['total']}건)")
            if not p["manifest_csv"].exists():
                raise FileNotFoundError(
                    f"Manifest CSV 없음: {p['manifest_csv']}\n"
                    f"data/staged/manifest/ 에 {snapshot}_manifest.csv 를 생성하지 못했습니다."
                )
            emit(5, "manifest CSV 확인", f"OK: {p['manifest_csv'].name}")
            save_pipeline_state(source_id, snapshot, 1)
        elif start_from > 1:
            emit(5, "Stage 1 건너뜀", "이전에 완료됨")

        # ── Stage 2: 텍스트 추출 (10%) ────────────────────────────────────
        if should_run(2):
            p["text_dir"].mkdir(parents=True, exist_ok=True)
            p["metadata_dir"].mkdir(parents=True, exist_ok=True)
            emit(10, "텍스트 추출 중...")
            emit(10, "실행 모드", describe_stage_compute_mode("ocr", runtime_settings))
            step4_config = get_step_config(source_id, "4") if source_id else {}
            ocr_dpi = int(step4_config.get("ocr_dpi") or 300)
            ocr_language = str(step4_config.get("ocr_language") or "kor+eng")
            ocr_min_text_length = int(step4_config.get("ocr_min_text_length") or 50)
            rc = await _run_script(
                [
                    "extract_manifest_batch.py",
                    "--manifest-csv", str(p["manifest_csv"]),
                    "--text-dir", str(p["text_dir"]),
                    "--metadata-dir", str(p["metadata_dir"]),
                    "--summary-csv", str(p["summary_csv"]),
                    "--use-ocr",   # auto-fall-back to tesseract for scanned PDFs
                    "--ocr-dpi", str(ocr_dpi),
                    "--ocr-lang", ocr_language,
                    "--ocr-min-text-length", str(ocr_min_text_length),
                ],
                emit, 10, 50,
                env=build_runtime_compute_env("ocr", runtime_settings),
            )
            if rc != 0:
                raise RuntimeError("extract_manifest_batch.py 실패")
            save_pipeline_state(source_id, snapshot, 2)
        elif start_from > 2:
            emit(50, "Stage 2 건너뜀", "이전에 완료됨")

        # ── Stage 3: 청크 생성 (55%) ──────────────────────────────────────
        if should_run(3):
            p["chunks_dir"].mkdir(parents=True, exist_ok=True)
            emit(55, "청크 생성 중...")
            emit(55, "실행 모드", describe_stage_compute_mode("chunk", runtime_settings))
            rc = await _run_script(
                [
                    "build_chunk_batch.py",
                    "--summary-csv", str(p["summary_csv"]),
                    "--output-jsonl", str(p["chunks_jsonl"]),
                ],
                emit, 55, 68,
                env=build_runtime_compute_env("chunk", runtime_settings),
            )
            if rc != 0:
                raise RuntimeError("build_chunk_batch.py 실패")
            save_pipeline_state(source_id, snapshot, 3)
        elif start_from > 3:
            emit(68, "Stage 3 건너뜀", "이전에 완료됨")

        # ── Stage 4: FAISS 인덱스 빌드 (70%) ─────────────────────────────
        if should_run(4):
            p["faiss_dir"].mkdir(parents=True, exist_ok=True)
            emit(70, "FAISS 인덱스 빌드 중...")
            emit(70, "실행 모드", describe_stage_compute_mode("faiss", runtime_settings))
            emit(70, "Stage 4", "임베딩 생성과 FAISS 인덱스 저장을 시작합니다.")
            emit(70, "Stage 4", f"입력 청크: {p['chunks_jsonl'].name}")
            rc = await _run_script(
                [
                    "build_faiss_index.py",
                    "--chunks-jsonl", str(p["chunks_jsonl"]),
                    "--output-index", str(p["index_path"]),
                    "--output-metadata", str(p["meta_path"]),
                    "--snapshot-id", snapshot,
                    "--embedding-provider", "ollama",
                    "--ollama-model", get_runtime_embedding_model(),
                ],
                emit, 70, 88,
                env=build_runtime_compute_env("faiss", runtime_settings),
            )
            if rc != 0:
                raise RuntimeError(_format_script_failure("build_faiss_index.py", rc))
            save_pipeline_state(source_id, snapshot, 4)
        elif start_from > 4:
            emit(88, "Stage 4 건너뜀", "이전에 완료됨")

        # ── Stage 5: 카테고리 인덱스 (90%) ───────────────────────────────
        if should_run(5):
            emit(90, "카테고리 인덱스 빌드 중...")
            emit(90, "실행 모드", describe_stage_compute_mode("faiss", runtime_settings))
            emit(90, "Stage 5", "카테고리별 보조 인덱스를 생성합니다.")

            # Document Source에서 동적 카테고리 가져오기
            category_keys = []
            if source_id:
                source = get_record("document_sources", "source_id", source_id)
                if source:
                    cat_config = source.get("category_config") or {}
                    categories = cat_config.get("categories", [])
                    category_keys = [c.get("key") for c in categories if c.get("key")]

            # 카테고리가 없으면 기본값 사용
            if not category_keys:
                category_keys = ["rfp", "proposal", "deliverable"]

            emit(90, "Stage 5", f"카테고리 대상: {', '.join(category_keys)}")

            cmd_args = [
                "build_category_indexes.py",
                "--combined-chunks", str(p["chunks_jsonl"]),
                "--output-dir", str(p["faiss_dir"]),
                "--snapshot", snapshot,
                "--embedding-provider", "ollama",
                "--ollama-model", get_runtime_embedding_model(),
                "--categories",
            ] + category_keys

            rc = await _run_script(
                cmd_args,
                emit,
                90,
                93,
                env=build_runtime_compute_env("faiss", runtime_settings),
            )
            if rc != 0:
                emit(90, "카테고리 인덱스", f"경고: {_format_script_failure('build_category_indexes.py', rc)} (비필수)")
            save_pipeline_state(source_id, snapshot, 5)
        elif start_from > 5:
            emit(93, "Stage 5 건너뜀", "이전에 완료됨")

        # ── Stage 6: 그래프 빌드 (94%) ───────────────────────────────────
        if should_run(6):
            emit(94, "그래프 데이터 빌드 중...")
            rc = await _run_script(
                ["build_graph_jsonl.py", "--snapshot", snapshot],
                emit, 94, 96,
            )
            if rc != 0:
                emit(94, "그래프 빌드", f"경고: {_format_script_failure('build_graph_jsonl.py', rc)} (비필수)")
            save_pipeline_state(source_id, snapshot, 6)
        elif start_from > 6:
            emit(96, "Stage 6 건너뜀", "이전에 완료됨")

        if end_stage <= 3:
            emit(97, "청킹 완료", f"청크 준비됨: {snapshot} — 다음 단계에서 FAISS를 생성하세요.")
        else:
            emit(97, "준비 완료", f"인덱스 준비됨: {snapshot} — admin에서 Activate 하세요.")

        job["status"] = "completed"
        emit(100, "완료")

    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        emit(job["progress"], "오류", str(exc))

    finally:
        q.put_nowait({
            "done": True,
            "status": job.get("status"),
            "error": job.get("error"),
        })


async def _run_script(
    args: list[str],
    emit,
    pct_start: int,
    pct_end: int,
    env: Optional[dict[str, str]] = None,
) -> int:
    """Run a pipeline script; stream stdout lines as log events.

    스크립트가 {"progress": N, ...} 형식의 JSON을 출력하면
    pct_start ~ pct_end 범위로 매핑하여 진행률을 업데이트합니다.
    """
    script = SCRIPTS_DIR / args[0]
    cmd = [sys.executable, str(script)] + args[1:]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(SCRIPTS_DIR),
        env=env,
    )
    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip()

        # JSON 진행률 파싱 시도
        calculated_pct = pct_start
        stage_text = args[0]
        log_text = line
        try:
            if line.startswith("{"):
                data = json.loads(line)
                if "progress" in data:
                    script_pct = data.get("progress", 0)
                    # 스크립트 진행률(0-100)을 pct_start ~ pct_end 범위로 매핑
                    calculated_pct = pct_start + int((script_pct / 100) * (pct_end - pct_start))
                    stage_text = data.get("stage", args[0])
                    current = data.get("current", "")
                    total = data.get("total", "")
                    if current and total:
                        stage_text = f"{stage_text} ({current}/{total})"
                if data.get("stage"):
                    log_text = json.dumps(data, ensure_ascii=False)
                elif data.get("warning"):
                    log_text = f"경고: {data.get('warning')}"
                elif data.get("error"):
                    log_text = f"오류: {data.get('error')}"
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        emit(calculated_pct, stage_text, log_text)
    await proc.wait()
    return proc.returncode


def _format_script_failure(script_name: str, return_code: int) -> str:
    """사람이 읽을 수 있는 subprocess 실패 메시지를 만든다."""
    if return_code < 0:
        return f"{script_name} 실패 (signal {-return_code})"
    if return_code > 128:
        return f"{script_name} 실패 (signal {return_code - 128})"
    return f"{script_name} 실패 (exit code {return_code})"


def activate_snapshot(
    snapshot: str,
    source_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
) -> dict:
    """Write active_index.json and return the new content."""
    content = {
        "snapshot": snapshot,
        "source_id": source_id or "",
        "dataset_id": dataset_id or "",
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
