# -*- coding: utf-8 -*-
"""
System runtime freshness diagnostics.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["System Runtime"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GRAPH_DIR = PROJECT_ROOT / "data" / "indexes" / "graph"
WATCHED_CODE = [
    PROJECT_ROOT / "backend" / "app" / "api" / "rag.py",
    PROJECT_ROOT / "backend" / "app" / "services" / "graph_query_service.py",
    PROJECT_ROOT / "backend" / "app" / "services" / "hybrid_rag_service.py",
]
SERVICE_NAME = "weeslee-rag-api.service"
SERVICE_PORT = 8080


def _process_start_time() -> Optional[datetime]:
    """현재 서빙 프로세스 시작 시각을 UTC datetime으로 반환한다."""
    try:
        import psutil

        return datetime.fromtimestamp(
            psutil.Process(os.getpid()).create_time(),
            tz=timezone.utc,
        )
    except Exception:
        pass

    try:
        clk_tck = os.sysconf("SC_CLK_TCK")
        btime = None
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("btime "):
                    btime = int(line.split()[1])
                    break
        if btime is None:
            return None

        with open("/proc/self/stat", "r", encoding="utf-8") as handle:
            raw = handle.read()
        after = raw[raw.rfind(")") + 1 :].split()
        starttime_ticks = int(after[19])
        start_epoch = btime + (starttime_ticks / clk_tck)
        return datetime.fromtimestamp(start_epoch, tz=timezone.utc)
    except Exception:
        return None


def _newest_mtime(paths: list[Path]) -> Optional[datetime]:
    mtimes = [
        datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        for path in paths
        if path.exists()
    ]
    return max(mtimes) if mtimes else None


def _manifest_built_at(manifest_path: Path) -> Optional[datetime]:
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    raw = str(manifest.get("built_at") or "").strip()
    if not raw:
        return None
    try:
        built_at = datetime.fromisoformat(raw)
    except Exception:
        return None
    if built_at.tzinfo is None:
        # 서버 기록은 KST 기준 문자열이므로 naive 값은 KST로 간주한다.
        built_at = built_at.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return built_at.astimezone(timezone.utc)


def _active_graph_manifest(source_id: Optional[str]) -> Path:
    if source_id:
        return GRAPH_DIR / source_id / "graph_manifest.json"
    return GRAPH_DIR / "graph_manifest.json"


def _systemd_main_pid(service_name: str) -> Optional[int]:
    try:
        result = subprocess.run(
            ["systemctl", "show", "-p", "MainPID", "--value", service_name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None

    raw = (result.stdout or "").strip()
    if not raw or raw == "0":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _port_owner_pid(port: int) -> Optional[int]:
    try:
        result = subprocess.run(
            ["ss", "-lntp"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None

    for line in result.stdout.splitlines():
        if f":{port} " not in line and not line.rstrip().endswith(f":{port}"):
            continue
        match = re.search(r"pid=(\d+)", line)
        if match:
            return int(match.group(1))
    return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _evaluate_freshness(
    *,
    current_pid: int,
    process_start: Optional[datetime],
    code_mtime: Optional[datetime],
    data_built_at: Optional[datetime],
    systemd_pid: Optional[int],
    port_pid: Optional[int],
) -> dict:
    reasons: list[str] = []
    stale = False
    grace = timedelta(seconds=2)

    if process_start is None:
        reasons.append("프로세스 시작 시각을 확인할 수 없음")
    else:
        if code_mtime and code_mtime > process_start + grace:
            stale = True
            reasons.append("서빙 프로세스가 최신 코드보다 이전에 기동됨")
        if data_built_at and data_built_at > process_start + grace:
            stale = True
            reasons.append("서빙 프로세스가 최신 데이터 빌드보다 이전에 기동됨")

    if systemd_pid is not None and systemd_pid != current_pid:
        stale = True
        reasons.append("현재 응답 프로세스 PID와 systemd MainPID가 다름")

    if port_pid is not None and port_pid != current_pid:
        stale = True
        reasons.append("현재 응답 프로세스 PID와 실제 8080 점유 PID가 다름")

    if not reasons:
        reasons.append("서빙 프로세스와 최신 코드/데이터, systemd PID 상태가 일치함")

    return {
        "stale": stale,
        "reasons": reasons,
        "current_pid": current_pid,
        "process_start": _iso(process_start),
        "code_mtime": _iso(code_mtime),
        "data_built_at": _iso(data_built_at),
        "systemd_main_pid": systemd_pid,
        "port_owner_pid": port_pid,
        "pid_matches_systemd": systemd_pid == current_pid if systemd_pid is not None else None,
        "pid_matches_port_owner": port_pid == current_pid if port_pid is not None else None,
    }


@router.get("/freshness")
async def runtime_freshness(source_id: Optional[str] = None):
    """현재 HTTP 서빙 프로세스가 최신 코드/데이터를 서빙 중인지 진단한다."""
    manifest_path = _active_graph_manifest(source_id)
    report = _evaluate_freshness(
        current_pid=os.getpid(),
        process_start=_process_start_time(),
        code_mtime=_newest_mtime(WATCHED_CODE),
        data_built_at=_manifest_built_at(manifest_path),
        systemd_pid=_systemd_main_pid(SERVICE_NAME),
        port_pid=_port_owner_pid(SERVICE_PORT),
    )
    report["service_name"] = SERVICE_NAME
    report["service_port"] = SERVICE_PORT
    report["source_id"] = source_id or "all"
    report["manifest_path"] = str(manifest_path)
    report["watched_code"] = [str(path) for path in WATCHED_CODE]
    return report
