from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.services.source_build_validation import build_source_validation_report


DATA_DIR = PROJECT_ROOT / "data"
SOURCE_ROOT = DATA_DIR / "source"
JOB_ROOT = DATA_DIR / "jobs"

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

try:
    _bind = SessionLocal.kw.get("bind")
    if _bind is not None:
        _bind.echo = False
except Exception:
    pass


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _format_ts(value: Optional[str]) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def _latest_source_dirs(limit: int = 20) -> list[Path]:
    if not SOURCE_ROOT.exists():
        return []
    dirs = [item for item in SOURCE_ROOT.iterdir() if item.is_dir() and item.name.startswith("src_")]
    dirs.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return dirs[:limit]


def _resolve_source_id(source_id: Optional[str]) -> Optional[str]:
    if source_id:
        return source_id
    candidates = _latest_source_dirs(limit=1)
    if not candidates:
        return None
    return candidates[0].name


def _job_source_id(job: dict[str, Any]) -> str:
    return str(
        job.get("source_id")
        or (job.get("last_event") or {}).get("source_id")
        or (job.get("result") or {}).get("source_id")
        or ""
    ).strip()


def _job_started_at(job: dict[str, Any]) -> str:
    return str(
        job.get("started_at")
        or job.get("created_at")
        or job.get("persisted_at")
        or ""
    )


def _load_job_dir(job_dir_name: str) -> list[dict[str, Any]]:
    job_dir = JOB_ROOT / job_dir_name
    if not job_dir.exists():
        return []
    jobs: list[dict[str, Any]] = []
    for path in sorted(job_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = _safe_read_json(path)
        if payload:
            jobs.append(payload)
    jobs.sort(key=_job_started_at, reverse=True)
    return jobs


def _filter_jobs(jobs: Iterable[dict[str, Any]], source_id: Optional[str]) -> list[dict[str, Any]]:
    if not source_id:
        return list(jobs)
    return [job for job in jobs if _job_source_id(job) == source_id]


def _pick_job(jobs: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not jobs:
        return None
    for job in jobs:
        if str(job.get("status") or "").lower() == "running":
            return job
    return jobs[0]


def _load_process_snapshot() -> list[dict[str, Any]]:
    try:
        import psutil  # type: ignore

        rows: list[dict[str, Any]] = []
        for proc in psutil.process_iter(["pid", "name", "cmdline", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                cmdline = " ".join(info.get("cmdline") or [])
                name = str(info.get("name") or "")
                if not any(token in (name + " " + cmdline).lower() for token in ("uvicorn", "ollama", "weeslee-rag")):
                    continue
                rows.append(
                    {
                        "pid": info.get("pid"),
                        "name": name,
                        "cpu": round(float(info.get("cpu_percent") or 0.0), 1),
                        "mem": round(float(info.get("memory_percent") or 0.0), 1),
                        "cmd": cmdline or name,
                    }
                )
            except Exception:
                continue
        rows.sort(key=lambda item: (item["cpu"], item["mem"]), reverse=True)
        return rows[:8]
    except Exception:
        return []


def _build_report(source_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        report = build_source_validation_report(source_id, db)
    finally:
        db.close()

    step4_jobs = _filter_jobs(_load_job_dir("step4_parse"), source_id)
    step5_jobs = _filter_jobs(_load_job_dir("step5_chunk"), source_id)
    step6_jobs = _filter_jobs(_load_job_dir("step6_embed"), source_id)

    report["monitor"] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "step4_job": _pick_job(step4_jobs),
        "step5_job": _pick_job(step5_jobs),
        "step6_job": _pick_job(step6_jobs),
        "step4_jobs": step4_jobs[:5],
        "step5_jobs": step5_jobs[:5],
        "step6_jobs": step6_jobs[:5],
        "processes": _load_process_snapshot(),
    }
    return report


def _job_line(name: str, job: Optional[dict[str, Any]]) -> str:
    if not job:
        return f"{name:<12} 없음"
    status = str(job.get("status") or "-")
    stage = str(job.get("stage") or (job.get("last_event") or {}).get("stage") or "-")
    progress = int(job.get("progress") or (job.get("last_event") or {}).get("progress") or 0)
    started_at = _format_ts(job.get("started_at") or job.get("created_at"))
    return f"{name:<12} {status:<10} {progress:>3}% | {stage} | {started_at}"


def _render_single(report: dict[str, Any]) -> str:
    source_id = str(report.get("source_id") or "-")
    dataset_id = str(report.get("dataset_id") or "-")
    dataset_status = str(report.get("dataset_status") or "-")
    document_count = int(report.get("document_count") or 0)
    stages = report.get("stages") or {}
    monitor = report.get("monitor") or {}

    lines = [
        f"[weeslee-rag dataset monitor] {monitor.get('generated_at') or ''}",
        f"source_id      : {source_id}",
        f"dataset_id     : {dataset_id}",
        f"dataset_status : {dataset_status}",
        f"document_count : {document_count}",
        "",
        "단계 상태",
    ]

    stage_order = [
        ("metadata", "Metadata"),
        ("ocr", "OCR/Parse"),
        ("chunk", "Chunk"),
        ("embedding", "Embedding"),
        ("faiss", "FAISS"),
        ("graph", "Graph"),
        ("wiki", "Wiki"),
    ]
    for key, label in stage_order:
        item = stages.get(key) or {}
        state = str(item.get("state") or "-")
        details = []
        if key == "metadata":
            details.append(f"reviewed={item.get('reviewed_count', 0)}")
            details.append(f"final={item.get('final_metadata_count', 0)}")
        elif key == "ocr":
            details.append(f"report={item.get('ocr_report_count', 0)}")
            details.append(f"text={item.get('full_text_count', 0)}")
            details.append(f"structured={item.get('structured_data_count', 0)}")
        elif key == "chunk":
            details.append(f"file={item.get('chunk_file_count', 0)}")
            details.append(f"db={item.get('chunk_db_count', 0)}")
            details.append(f"source_docs={item.get('source_chunk_document_count', 0)}")
        elif key == "embedding":
            details.append(f"file={item.get('embedding_file_count', 0)}")
            details.append(f"meta={item.get('embedding_meta_count', 0)}")
            details.append(f"source_docs={item.get('source_embedding_document_count', 0)}")
        elif key == "faiss":
            details.append(f"snapshot={item.get('snapshot_count', 0)}")
            details.append(f"queryable={item.get('queryable_count', 0)}")
            details.append(f"active={item.get('active_count', 0)}")
        elif key == "graph":
            details.append(f"nodes={item.get('node_count', 0)}")
            details.append(f"edges={item.get('edge_count', 0)}")
            details.append(f"built_at={item.get('built_at') or '-'}")
        elif key == "wiki":
            details.append(f"project={item.get('project_count', 0)}")
            details.append(f"org={item.get('organization_count', 0)}")
            details.append(f"tech={item.get('technology_count', 0)}")
        lines.append(f"- {label:<10} {state:<8} | " + " | ".join(details))

    lines.extend(
        [
            "",
            "활성 Job",
            _job_line("Step4 Parse", monitor.get("step4_job")),
            _job_line("Step5 Chunk", monitor.get("step5_job")),
            _job_line("Step6 Embed", monitor.get("step6_job")),
        ]
    )

    snapshots = (stages.get("faiss") or {}).get("snapshots") or []
    if snapshots:
        lines.append("")
        lines.append("최근 Snapshot")
        for item in snapshots[:5]:
            lines.append(
                "- "
                + f"{item.get('snapshot_id')} | status={item.get('status')} | "
                + f"queryable={bool(item.get('queryable'))} | active={bool(item.get('is_active'))}"
            )

    sample_documents = report.get("sample_documents") or []
    if sample_documents:
        lines.append("")
        lines.append("샘플 문서")
        for item in sample_documents[:5]:
            lines.append(
                "- "
                + f"doc={item.get('document_id')} | status={item.get('status') or '-'} | "
                + f"meta={item.get('meta_status') or '-'} | path={item.get('relative_path') or '-'}"
            )

    processes = monitor.get("processes") or []
    if processes:
        lines.append("")
        lines.append("프로세스")
        for proc in processes:
            lines.append(
                "- "
                + f"pid={proc.get('pid')} | cpu={proc.get('cpu')}% | mem={proc.get('mem')}% | "
                + f"{proc.get('cmd')}"
            )

    return "\n".join(lines)


def _render_multi(source_ids: list[str]) -> str:
    rows = []
    for source_id in source_ids:
        report = _build_report(source_id)
        stages = report.get("stages") or {}
        rows.append(
            {
                "source_id": source_id,
                "dataset_status": str(report.get("dataset_status") or "-"),
                "docs": int(report.get("document_count") or 0),
                "ocr": str((stages.get("ocr") or {}).get("state") or "-"),
                "chunk": str((stages.get("chunk") or {}).get("state") or "-"),
                "embed": str((stages.get("embedding") or {}).get("state") or "-"),
                "faiss": str((stages.get("faiss") or {}).get("state") or "-"),
                "graph": str((stages.get("graph") or {}).get("state") or "-"),
                "wiki": str((stages.get("wiki") or {}).get("state") or "-"),
            }
        )

    lines = [
        f"[weeslee-rag dataset monitor] {datetime.now().isoformat(timespec='seconds')}",
        "source_id                              docs  dataset     ocr      chunk    embed    faiss    graph    wiki",
        "-" * 110,
    ]
    for row in rows:
        lines.append(
            f"{row['source_id']:<36} {row['docs']:>4}  "
            f"{row['dataset_status']:<10} {row['ocr']:<8} {row['chunk']:<8} "
            f"{row['embed']:<8} {row['faiss']:<8} {row['graph']:<8} {row['wiki']:<8}"
        )
    return "\n".join(lines)


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def main() -> int:
    parser = argparse.ArgumentParser(description="weeslee-rag 데이터셋 빌드 상태 모니터")
    parser.add_argument("--source-id", help="확인할 source_id. 생략 시 가장 최근 source 사용")
    parser.add_argument("--all-sources", action="store_true", help="최근 source_id들을 요약 표시")
    parser.add_argument("--limit", type=int, default=10, help="all-sources일 때 표시 개수")
    parser.add_argument("--watch", action="store_true", help="반복 갱신 모드")
    parser.add_argument("--interval", type=float, default=5.0, help="watch 갱신 주기(초)")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    args = parser.parse_args()

    def render_once() -> None:
        if args.all_sources:
            source_ids = [item.name for item in _latest_source_dirs(limit=max(1, args.limit))]
            payload = {"sources": source_ids} if args.json else None
            if args.json:
                reports = [_build_report(source_id) for source_id in source_ids]
                print(json.dumps(reports, ensure_ascii=False, indent=2))
            else:
                print(_render_multi(source_ids))
            return

        source_id = _resolve_source_id(args.source_id)
        if not source_id:
            raise SystemExit("data/source 아래에 source_id 폴더가 없습니다.")
        report = _build_report(source_id)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(_render_single(report))

    if not args.watch:
        render_once()
        return 0

    while True:
        _clear_screen()
        try:
            render_once()
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"monitor error: {exc}")
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
