from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.services.dataset_context import get_source_dataset_context
from app.services.processed_text_store import get_processed_text_store
from app.services.source_build_validation import build_source_validation_report
from app.services.source_data_paths import get_source_paths


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


@dataclass
class WatchdogCheckResult:
    name: str
    status: str
    detail: str
    payload: Optional[dict[str, Any]] = None


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _format_age(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _latest_mtime(paths: list[Path]) -> Optional[float]:
    mtimes: list[float] = []
    for path in paths:
        try:
            if path.exists():
                mtimes.append(path.stat().st_mtime)
        except Exception:
            continue
    return max(mtimes) if mtimes else None


def _job_source_id(job: dict[str, Any]) -> str:
    return str(
        job.get("source_id")
        or (job.get("last_event") or {}).get("source_id")
        or (job.get("result") or {}).get("source_id")
        or ""
    ).strip()


def _load_job_dir(job_dir_name: str) -> list[tuple[Path, dict[str, Any]]]:
    job_dir = JOB_ROOT / job_dir_name
    if not job_dir.exists():
        return []
    rows: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(job_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = _safe_read_json(path)
        if payload:
            rows.append((path, payload))
    return rows


def _source_job_files(source_id: str) -> list[tuple[Path, dict[str, Any]]]:
    rows: list[tuple[Path, dict[str, Any]]] = []
    for job_dir in ("step4_parse", "step5_chunk", "step6_embed"):
        for path, payload in _load_job_dir(job_dir):
            if _job_source_id(payload) == source_id:
                rows.append((path, payload))
    result_file = JOB_ROOT / f"complete_build_{source_id}.json"
    if result_file.exists():
        rows.append((result_file, _safe_read_json(result_file)))
    rows.sort(key=lambda item: item[0].stat().st_mtime if item[0].exists() else 0, reverse=True)
    return rows


def _flatten_document_strings(doc: dict[str, Any]) -> str:
    values = [
        doc.get("document_id"),
        doc.get("project_name"),
        doc.get("organization"),
        doc.get("title"),
        doc.get("file_name"),
        doc.get("relative_path"),
        doc.get("source"),
        doc.get("content"),
        doc.get("snippet"),
        doc.get("text"),
    ]
    return " ".join(str(v or "") for v in values).lower()


def _resolve_text_exists(source_id: str, document_id: Any) -> bool:
    document_id = str(document_id or "").strip()
    if not document_id:
        return False
    source_paths = get_source_paths(source_id)
    if source_paths.document_full_text(document_id).exists():
        return True
    if (source_paths.document_dir(document_id) / "full_text.md").exists():
        return True
    store = get_processed_text_store(source_id)
    return bool(store.get_text(document_id, format="txt") or store.get_text(document_id, format="md"))


class WeesleeWatchdog:
    def __init__(
        self,
        *,
        source_id: str,
        dataset_id: Optional[str],
        api_base: str,
        stall_seconds: int,
        timeout_seconds: int,
        question_config_path: Optional[Path],
    ) -> None:
        self.source_id = source_id
        self.dataset_id = dataset_id or get_source_dataset_context(source_id).get("dataset_id")
        self.api_base = api_base.rstrip("/")
        self.stall_seconds = stall_seconds
        self.timeout_seconds = timeout_seconds
        self.question_config_path = question_config_path
        self.source_paths = get_source_paths(source_id)

    def _build_report(self) -> dict[str, Any]:
        db = SessionLocal()
        try:
            return build_source_validation_report(self.source_id, db)
        except Exception as exc:
            return self._fallback_report(exc)
        finally:
            db.close()

    def _fallback_report(self, exc: Exception) -> dict[str, Any]:
        stages: dict[str, dict[str, Any]] = {}
        stage_dir_summary = self._stage_dir_summary()

        def _state_for_dir(name: str) -> str:
            info = stage_dir_summary.get(name) or {}
            if bool(info.get("exists")) and int(info.get("file_count") or 0) > 0:
                return "ready"
            return "missing"

        stages["metadata"] = {"state": _state_for_dir("step4_metadata")}
        stages["ocr"] = {"state": _state_for_dir("step2_extract")}
        stages["chunk"] = {"state": _state_for_dir("step5_chunk") if "step5_chunk" in stage_dir_summary else _state_for_dir("step3_chunk")}
        stages["embedding"] = {"state": _state_for_dir("step6_embed") if "step6_embed" in stage_dir_summary else _state_for_dir("step6_embedding")}
        stages["faiss"] = {"state": _state_for_dir("step7_faiss") if "step7_faiss" in stage_dir_summary else _state_for_dir("active")}
        stages["graph"] = {"state": _state_for_dir("step8_graph")}
        stages["wiki"] = {"state": _state_for_dir("step9_wiki")}

        return {
            "source_id": self.source_id,
            "dataset_id": self.dataset_id,
            "dataset_status": "db_unavailable",
            "document_count": 0,
            "sample_documents": [],
            "stages": stages,
            "watchdog_note": f"database unavailable: {exc}",
        }

    def _latest_activity(self) -> dict[str, Any]:
        watched_paths = [
            self.source_paths.base_dir,
            self.source_paths.documents_jsonl,
            self.source_paths.extract_summary_json,
            self.source_paths.step2_dir,
            self.source_paths.step3_dir,
            self.source_paths.step4_dir,
            self.source_paths.step5_dir,
            self.source_paths.step6_dir,
            self.source_paths.active_dir,
            self.source_paths.latest_snapshot_json,
            self.source_paths.snapshots_json,
            self.source_paths.faiss_index,
            self.source_paths.faiss_metadata_jsonl,
            self.source_paths.active_faiss_index,
            self.source_paths.active_metadata_jsonl,
            self.source_paths.active_chunks_jsonl,
            self.source_paths.base_dir / "build_result.json",
        ]
        latest_source_mtime = _latest_mtime(watched_paths)

        job_rows = _source_job_files(self.source_id)
        job_paths = [path for path, _payload in job_rows]
        latest_job_mtime = _latest_mtime(job_paths)

        candidates = [value for value in (latest_source_mtime, latest_job_mtime) if value is not None]
        latest_any = max(candidates) if candidates else None
        age_seconds = time.time() - latest_any if latest_any is not None else None

        return {
            "latest_source_mtime": latest_source_mtime,
            "latest_job_mtime": latest_job_mtime,
            "latest_any_mtime": latest_any,
            "age_seconds": age_seconds,
            "job_files": [
                {
                    "path": str(path.relative_to(PROJECT_ROOT)),
                    "status": str(payload.get("status") or ""),
                    "stage": str(payload.get("stage") or (payload.get("last_event") or {}).get("stage") or ""),
                }
                for path, payload in job_rows[:10]
            ],
        }

    def _stage_dir_summary(self) -> dict[str, Any]:
        steps = {}
        for name in (
            "step1_scan",
            "step2_extract",
            "step3_chunk",
            "step4_metadata",
            "step5_tag_keyword",
            "step6_embedding",
            "active",
        ):
            path = self.source_paths.base_dir / name
            steps[name] = {
                "exists": path.exists(),
                "file_count": sum(1 for _ in path.rglob("*") if _.is_file()) if path.exists() else 0,
            }

        extra_steps = {
            "step5_chunk": self.source_paths.base_dir / "step5_chunk",
            "step6_embed": self.source_paths.base_dir / "step6_embed",
            "step7_faiss": self.source_paths.base_dir / "step7_faiss",
            "step8_graph": self.source_paths.base_dir / "step8_graph",
            "step9_wiki": self.source_paths.base_dir / "step9_wiki",
            "step10_activate": self.source_paths.base_dir / "step10_activate",
        }
        for name, path in extra_steps.items():
            steps[name] = {
                "exists": path.exists(),
                "file_count": sum(1 for _ in path.rglob("*") if _.is_file()) if path.exists() else 0,
            }
        return steps

    def _run_stage_checks(self, report: dict[str, Any], activity: dict[str, Any]) -> list[WatchdogCheckResult]:
        checks: list[WatchdogCheckResult] = []
        stages = report.get("stages") or {}
        dataset_status = str(report.get("dataset_status") or "")
        document_count = int(report.get("document_count") or 0)

        if not self.source_paths.base_dir.exists():
            checks.append(
                WatchdogCheckResult(
                    name="source_dir",
                    status="fail",
                    detail=f"source dir missing: {self.source_paths.base_dir}",
                )
            )
            return checks

        checks.append(
            WatchdogCheckResult(
                name="dataset_context",
                status="pass" if self.dataset_id else "warn",
                detail=f"dataset_id={self.dataset_id or '-'} | dataset_status={dataset_status or '-'} | documents={document_count}",
            )
        )

        incomplete = []
        for key in ("metadata", "ocr", "chunk", "embedding", "faiss", "graph", "wiki"):
            state = str((stages.get(key) or {}).get("state") or "missing")
            if state not in {"ready", "empty"}:
                incomplete.append(f"{key}:{state}")

        if incomplete:
            checks.append(
                WatchdogCheckResult(
                    name="pipeline_progress",
                    status="warn",
                    detail="incomplete stages=" + ", ".join(incomplete),
                    payload={"stages": stages},
                )
            )
        else:
            checks.append(
                WatchdogCheckResult(
                    name="pipeline_progress",
                    status="pass",
                    detail="all tracked stages ready",
                    payload={"stages": stages},
                )
            )

        age_seconds = activity.get("age_seconds")
        if incomplete and age_seconds is not None and age_seconds >= self.stall_seconds:
            checks.append(
                WatchdogCheckResult(
                    name="stall_detection",
                    status="fail",
                    detail=f"no source/job activity for {_format_age(age_seconds)} while stages incomplete",
                    payload=activity,
                )
            )
        else:
            checks.append(
                WatchdogCheckResult(
                    name="stall_detection",
                    status="pass",
                    detail=f"latest activity age={_format_age(age_seconds)}",
                    payload=activity,
                )
            )

        return checks

    def _run_job_checks(self) -> list[WatchdogCheckResult]:
        rows = _source_job_files(self.source_id)
        if not rows:
            return [WatchdogCheckResult(name="jobs", status="warn", detail="no source job files found")]

        failed_jobs = []
        running_jobs = []
        for path, payload in rows:
            status = str(payload.get("status") or "").lower()
            last_event = payload.get("last_event") or {}
            if status in {"failed", "error"}:
                failed_jobs.append((path, payload))
            if status in {"running", "processing"}:
                running_jobs.append((path, payload))
            result = payload.get("result") or {}
            if isinstance(result, dict):
                for step_key in ("step5", "step6", "step7"):
                    step_status = str((result.get(step_key) or {}).get("status") or "").lower()
                    if step_status == "error":
                        failed_jobs.append((path, payload))
                        break
            if str(last_event.get("level") or "").lower() == "error":
                failed_jobs.append((path, payload))

        if failed_jobs:
            path, payload = failed_jobs[0]
            return [
                WatchdogCheckResult(
                    name="jobs",
                    status="fail",
                    detail=f"failed job detected: {path.name} status={payload.get('status')}",
                    payload=payload,
                )
            ]

        if running_jobs:
            path, payload = running_jobs[0]
            created_at = str(payload.get("created_at") or "")
            age_detail = created_at or path.name
            return [
                WatchdogCheckResult(
                    name="jobs",
                    status="pass",
                    detail=f"running job detected: {path.name} started={age_detail}",
                    payload=payload,
                )
            ]

        return [
            WatchdogCheckResult(
                name="jobs",
                status="pass",
                detail=f"job files found={len(rows)} and no failure status",
            )
        ]

    def _load_question_config(self) -> list[dict[str, Any]]:
        if not self.question_config_path:
            return []
        payload = json.loads(self.question_config_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            checks = payload.get("checks") or []
        elif isinstance(payload, list):
            checks = payload
        else:
            checks = []
        return [item for item in checks if isinstance(item, dict)]

    def _call_rag_query(self, check: dict[str, Any]) -> dict[str, Any]:
        endpoint = f"{self.api_base}/rag/query"
        body = {
            "query": check["query"],
            "top_k": int(check.get("top_k", 20)),
            "top_docs": int(check.get("top_docs", 5)),
            "answer_provider": str(check.get("answer_provider") or "none"),
            "answer_model": "",
            "mode": check.get("mode", "auto"),
            "snapshot_ids": check.get("snapshot_ids") or [],
            "document_group": check.get("document_group"),
            "document_category": check.get("document_category"),
            "section_type": check.get("section_type"),
            "organization": check.get("organization"),
            "year": check.get("year"),
        }
        response = requests.post(endpoint, json=body, timeout=int(check.get("timeout_seconds", 60)))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("unexpected rag/query response")
        return payload

    def _run_question_checks(self, report: dict[str, Any]) -> list[WatchdogCheckResult]:
        question_checks = self._load_question_config()
        if not question_checks:
            return [WatchdogCheckResult(name="question_validation", status="warn", detail="question config not provided")]

        faiss_state = str(((report.get("stages") or {}).get("faiss") or {}).get("state") or "")
        if faiss_state != "ready":
            return [
                WatchdogCheckResult(
                    name="question_validation",
                    status="warn",
                    detail=f"faiss state is {faiss_state or '-'} so search validation skipped",
                )
            ]

        results: list[WatchdogCheckResult] = []
        for index, check in enumerate(question_checks, start=1):
            query = str(check.get("query") or "").strip()
            if not query:
                results.append(
                    WatchdogCheckResult(
                        name=f"question_{index}",
                        status="warn",
                        detail="empty query skipped",
                    )
                )
                continue

            try:
                payload = self._call_rag_query(check)
                documents = payload.get("documents") or payload.get("results") or []
                min_documents = int(check.get("min_documents", 1))
                if len(documents) < min_documents:
                    results.append(
                        WatchdogCheckResult(
                            name=f"question_{index}",
                            status="fail",
                            detail=f"query='{query}' returned {len(documents)} docs < {min_documents}",
                            payload=payload,
                        )
                    )
                    continue

                expected_terms = [str(item).strip().lower() for item in check.get("expected_terms") or [] if str(item).strip()]
                matched_docs = documents
                if expected_terms:
                    matched_docs = [
                        doc for doc in documents
                        if all(term in _flatten_document_strings(doc) for term in expected_terms)
                    ]
                    if not matched_docs:
                        results.append(
                            WatchdogCheckResult(
                                name=f"question_{index}",
                                status="fail",
                                detail=f"query='{query}' returned docs but expected terms not found: {expected_terms}",
                                payload=payload,
                            )
                        )
                        continue

                if bool(check.get("require_original_text", True)):
                    text_ready = False
                    for doc in matched_docs:
                        if _resolve_text_exists(self.source_id, doc.get("document_id")):
                            text_ready = True
                            break
                    if not text_ready:
                        results.append(
                            WatchdogCheckResult(
                                name=f"question_{index}",
                                status="fail",
                                detail=f"query='{query}' matched docs but no original text artifact found",
                                payload=payload,
                            )
                        )
                        continue

                results.append(
                    WatchdogCheckResult(
                        name=f"question_{index}",
                        status="pass",
                        detail=f"query='{query}' docs={len(documents)} matched={len(matched_docs)}",
                        payload={
                            "documents": documents[:3],
                            "resolved_snapshot_ids": payload.get("resolved_snapshot_ids"),
                            "retrieval_diagnostics": payload.get("retrieval_diagnostics"),
                        },
                    )
                )
            except Exception as exc:
                results.append(
                    WatchdogCheckResult(
                        name=f"question_{index}",
                        status="fail",
                        detail=f"query='{query}' validation error: {exc}",
                    )
                )

        return results

    def run_once(self) -> dict[str, Any]:
        report = self._build_report()
        activity = self._latest_activity()
        stage_dirs = self._stage_dir_summary()

        checks: list[WatchdogCheckResult] = []
        checks.extend(self._run_stage_checks(report, activity))
        checks.extend(self._run_job_checks())
        checks.extend(self._run_question_checks(report))

        has_fail = any(item.status == "fail" for item in checks)
        has_warn = any(item.status == "warn" for item in checks)
        overall = "fail" if has_fail else "warn" if has_warn else "pass"

        return {
            "generated_at": _now_iso(),
            "source_id": self.source_id,
            "dataset_id": self.dataset_id,
            "overall_status": overall,
            "stage_dirs": stage_dirs,
            "activity": activity,
            "validation": report,
            "checks": [
                {
                    "name": item.name,
                    "status": item.status,
                    "detail": item.detail,
                    "payload": item.payload,
                }
                for item in checks
            ],
        }


def _render_console(result: dict[str, Any]) -> str:
    lines = [
        f"[weeslee-rag watchdog] {result.get('generated_at')}",
        f"source_id      : {result.get('source_id')}",
        f"dataset_id     : {result.get('dataset_id') or '-'}",
        f"overall_status : {result.get('overall_status')}",
        "",
        "checks",
    ]
    for item in result.get("checks") or []:
        lines.append(f"- [{str(item.get('status')).upper():<4}] {item.get('name')}: {item.get('detail')}")

    activity = result.get("activity") or {}
    lines.extend(
        [
            "",
            "activity",
            f"- latest_age : {_format_age(activity.get('age_seconds'))}",
            f"- job_files  : {len(activity.get('job_files') or [])}",
        ]
    )

    stage_dirs = result.get("stage_dirs") or {}
    if stage_dirs:
        lines.append("")
        lines.append("stage dirs")
        for key, info in stage_dirs.items():
            lines.append(f"- {key:<14} exists={bool(info.get('exists'))} files={int(info.get('file_count') or 0)}")

    return "\n".join(lines)


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def main() -> int:
    parser = argparse.ArgumentParser(description="weeslee-rag build/search watchdog")
    parser.add_argument("--source-id", required=True, help="target source_id")
    parser.add_argument("--dataset-id", help="expected dataset_id")
    parser.add_argument("--api-base", default="http://127.0.0.1:8080/api", help="local API base for query validation")
    parser.add_argument("--question-config", help="JSON config path for search validation")
    parser.add_argument("--stall-seconds", type=int, default=300, help="fail if no activity longer than this while incomplete")
    parser.add_argument("--timeout-seconds", type=int, default=14400, help="reserved timeout window for long build")
    parser.add_argument("--watch", action="store_true", help="watch mode")
    parser.add_argument("--interval", type=float, default=10.0, help="watch interval seconds")
    parser.add_argument("--json", action="store_true", help="print JSON result")
    parser.add_argument("--output", help="optional JSON output path")
    args = parser.parse_args()

    watchdog = WeesleeWatchdog(
        source_id=args.source_id,
        dataset_id=args.dataset_id,
        api_base=args.api_base,
        stall_seconds=args.stall_seconds,
        timeout_seconds=args.timeout_seconds,
        question_config_path=Path(args.question_config) if args.question_config else None,
    )

    def render_once() -> int:
        result = watchdog.run_once()
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(_render_console(result))
        return 1 if result.get("overall_status") == "fail" else 0

    if not args.watch:
        return render_once()

    while True:
        _clear_screen()
        try:
            render_once()
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"watchdog error: {exc}")
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
