# Dataset Builder 의존 서비스 관리 모듈
"""
OCR 서버, Ollama 등 데이터셋 빌드에 필요한 서비스들의 상태 확인 및 재시작.
"""
import asyncio
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ServiceConfig:
    name: str
    health_url: str
    start_cmd: str
    stop_cmd: str
    port: int
    timeout: float = 5.0
    verify_identity: bool = False
    port_wait_timeout: int = 60  # 포트 리슨 대기 타임아웃 (초)
    health_wait_timeout: int = 60  # 헬스체크 대기 타임아웃 (초)


# 서비스 설정
SERVICES = {
    "ocr": ServiceConfig(
        name="OCR Server",
        health_url="http://127.0.0.1:5000/health",
        start_cmd=os.getenv(
            "WEESLEE_OCR_START_CMD",
            "cd /data/weeslee/pdf-ocr && nohup venv/bin/python python/advanced_ocr_server.py > /tmp/ocr_server.log 2>&1 &",
        ),
        stop_cmd="pkill -f 'advanced_ocr_server.py'",
        port=5000,
        timeout=10.0,
        verify_identity=True,
        port_wait_timeout=90,  # OCR 서버는 GPU 초기화로 오래 걸림
        health_wait_timeout=90,
    ),
    "ollama": ServiceConfig(
        name="Ollama",
        health_url="http://127.0.0.1:11434/api/tags",
        start_cmd=os.getenv("WEESLEE_OLLAMA_START_CMD", "systemctl start ollama"),
        stop_cmd=os.getenv("WEESLEE_OLLAMA_STOP_CMD", "systemctl stop ollama"),
        port=11434,
        timeout=5.0,
        verify_identity=True,
        port_wait_timeout=60,
        health_wait_timeout=60,
    ),
}


def _run_shell_command(command: str, *, timeout: int) -> subprocess.CompletedProcess:
    """bash로 실행해 source/&& 같은 bash 문법과 stderr를 안정적으로 수집한다."""
    return subprocess.run(
        command,
        shell=True,
        executable="/bin/bash",
        timeout=timeout,
        capture_output=True,
        text=True,
    )


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

    for line in (result.stdout or "").splitlines():
        if f":{port} " not in line and not line.rstrip().endswith(f":{port}"):
            continue
        match = re.search(r"pid=(\d+)", line)
        if match:
            return int(match.group(1))
    return None


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


def _service_identity(service_key: str, config: ServiceConfig) -> Optional[str]:
    if service_key == "ollama":
        pid = _systemd_main_pid("ollama")
        return f"systemd:{pid}" if pid else None
    pid = _port_owner_pid(config.port)
    return f"port:{pid}" if pid else None


def _short_error_text(result: subprocess.CompletedProcess) -> str:
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    return stderr or stdout or f"returncode={result.returncode}"


async def check_service_health(service_key: str) -> dict:
    """서비스 헬스체크."""
    if service_key not in SERVICES:
        return {"status": "error", "message": f"알 수 없는 서비스: {service_key}"}

    config = SERVICES[service_key]
    try:
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            resp = await client.get(config.health_url)
            if resp.status_code == 200:
                return {
                    "status": "healthy",
                    "service": config.name,
                    "port": config.port,
                    "response": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200],
                }
            return {
                "status": "unhealthy",
                "service": config.name,
                "port": config.port,
                "http_status": resp.status_code,
            }
    except httpx.TimeoutException:
        return {
            "status": "timeout",
            "service": config.name,
            "port": config.port,
            "message": f"{config.timeout}초 내 응답 없음",
        }
    except httpx.ConnectError:
        return {
            "status": "disconnected",
            "service": config.name,
            "port": config.port,
            "message": "연결 실패 - 서비스가 실행되지 않음",
        }
    except Exception as exc:
        return {
            "status": "error",
            "service": config.name,
            "port": config.port,
            "message": str(exc),
        }


async def check_all_services() -> dict:
    """모든 서비스 헬스체크."""
    results = {}
    all_healthy = True

    for key in SERVICES:
        result = await check_service_health(key)
        results[key] = result
        if result.get("status") != "healthy":
            all_healthy = False

    return {
        "overall_status": "healthy" if all_healthy else "degraded",
        "services": results,
    }


def _wait_for_port_listen(port: int, timeout_sec: int = 30) -> bool:
    """포트가 LISTEN 상태가 될 때까지 대기."""
    start = time.time()
    while time.time() - start < timeout_sec:
        pid = _port_owner_pid(port)
        if pid:
            return True
        time.sleep(1)
    return False


def restart_service_sync(service_key: str) -> dict:
    """서비스 동기 재시작 (subprocess 사용)."""
    if service_key not in SERVICES:
        return {"success": False, "message": f"알 수 없는 서비스: {service_key}"}

    config = SERVICES[service_key]
    logger.info(f"[ServiceManager] {config.name} 재시작 시작")
    before_identity = _service_identity(service_key, config)
    was_running = before_identity is not None
    logger.info(f"[ServiceManager] {config.name} before_identity={before_identity}, was_running={was_running}")

    try:
        # 1. 서비스 중지 (이미 죽어있어도 진행)
        stop_result = _run_shell_command(
            config.stop_cmd,
            timeout=10,
        )
        # pkill은 프로세스가 없으면 returncode=1을 반환하므로, 이미 죽어있는 경우 무시
        if stop_result.returncode != 0 and was_running:
            logger.warning(f"[ServiceManager] {config.name} 중지 명령 실패 (무시하고 계속): {_short_error_text(stop_result)}")
        logger.info(f"[ServiceManager] {config.name} 중지 완료 (returncode={stop_result.returncode})")

        # 2. 포트가 해제될 때까지 대기 (최대 10초)
        for _ in range(10):
            if _port_owner_pid(config.port) is None:
                break
            time.sleep(1)
        else:
            logger.warning(f"[ServiceManager] {config.name} 포트 {config.port} 아직 사용 중")

        # 3. 서비스 시작
        start_result = _run_shell_command(
            config.start_cmd,
            timeout=15,
        )
        # nohup & 명령은 즉시 리턴하므로 returncode만으로 판단 불가
        logger.info(f"[ServiceManager] {config.name} 시작 명령 실행 (returncode={start_result.returncode})")

        # 4. 포트 리슨 대기 (config 설정값 사용)
        if not _wait_for_port_listen(config.port, timeout_sec=config.port_wait_timeout):
            return {
                "success": False,
                "service": config.name,
                "message": f"서비스 시작 후 포트 {config.port} 리슨 대기 타임아웃 ({config.port_wait_timeout}초)",
            }
        logger.info(f"[ServiceManager] {config.name} 포트 {config.port} 리슨 확인")

        # 5. 헬스체크 대기 (config 설정값 사용)
        max_attempts = config.health_wait_timeout // 2  # 2초 간격으로 체크
        for attempt in range(max_attempts):
            time.sleep(2)
            try:
                import requests
                resp = requests.get(config.health_url, timeout=3)
                if resp.status_code == 200:
                    after_identity = _service_identity(service_key, config)
                    logger.info(f"[ServiceManager] {config.name} after_identity={after_identity}")

                    # 재시작 검증: 이전에 실행 중이었고 PID가 같으면 실패
                    if (
                        config.verify_identity
                        and was_running
                        and before_identity
                        and after_identity
                        and before_identity == after_identity
                    ):
                        return {
                            "success": False,
                            "service": config.name,
                            "message": (
                                "health 응답은 정상이지만 프로세스 식별자가 바뀌지 않아 "
                                "실제 재시작이 확인되지 않았습니다."
                            ),
                            "before_identity": before_identity,
                            "after_identity": after_identity,
                        }

                    # 새로 시작한 경우(was_running=False) 또는 PID가 변경된 경우 성공
                    logger.info(f"[ServiceManager] {config.name} 정상 시작 확인")
                    return {
                        "success": True,
                        "service": config.name,
                        "message": "서비스 재시작 완료" if was_running else "서비스 시작 완료",
                        "before_identity": before_identity,
                        "after_identity": after_identity,
                        "was_running": was_running,
                    }
            except Exception as e:
                logger.debug(f"[ServiceManager] {config.name} 헬스체크 시도 {attempt+1}/{max_attempts} 실패: {e}")
                continue

        return {
            "success": False,
            "service": config.name,
            "message": f"서비스 시작 후 헬스체크 응답 없음 ({config.health_wait_timeout}초 대기)",
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "service": config.name,
            "message": "재시작 명령 타임아웃",
        }
    except Exception as exc:
        logger.error(f"[ServiceManager] {config.name} 재시작 오류: {exc}")
        return {
            "success": False,
            "service": config.name,
            "message": str(exc),
        }


async def restart_service(service_key: str) -> dict:
    """서비스 비동기 재시작."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, restart_service_sync, service_key)


async def ensure_services_ready(force_restart: bool = False) -> dict:
    """
    데이터셋 빌드에 필요한 모든 서비스가 준비되었는지 확인.
    force_restart=True인 경우 모든 서비스를 강제로 재시작.
    """
    results = {"actions": [], "all_ready": True, "force_restart": force_restart}

    for key, config in SERVICES.items():
        if force_restart:
            # Force 모드: 무조건 재시작
            logger.info(f"[ServiceManager] {config.name} 강제 재시작 (force_restart=True)")
            restart_result = await restart_service(key)

            if restart_result.get("success"):
                results["actions"].append({
                    "service": config.name,
                    "action": "force_restarted",
                    "status": "success",
                })
            else:
                results["actions"].append({
                    "service": config.name,
                    "action": "restart_failed",
                    "status": "error",
                    "message": restart_result.get("message"),
                })
                results["all_ready"] = False
        else:
            # 일반 모드: 헬스체크 후 필요시에만 재시작
            health = await check_service_health(key)

            if health.get("status") == "healthy":
                results["actions"].append({
                    "service": config.name,
                    "action": "none",
                    "status": "already_healthy",
                })
            else:
                logger.warning(f"[ServiceManager] {config.name} 비정상 ({health.get('status')}), 재시작 시도")
                restart_result = await restart_service(key)

                if restart_result.get("success"):
                    results["actions"].append({
                        "service": config.name,
                        "action": "restarted",
                        "status": "success",
                    })
                else:
                    results["actions"].append({
                        "service": config.name,
                        "action": "restart_failed",
                        "status": "error",
                        "message": restart_result.get("message"),
                    })
                    results["all_ready"] = False

    return results


# ── Job 상태 관리 ──────────────────────────────────────────────────────────────


def get_active_build_jobs(source_id: str = None) -> dict:
    """현재 source_id에 대해 실행 중인 빌드 Job 조회."""
    from app.services.dataset_builder_lock import get_active_jobs
    jobs = get_active_jobs(source_id=source_id)
    return {
        "active_jobs": jobs,
        "count": len(jobs),
        "has_running_jobs": len(jobs) > 0,
    }


def interrupt_active_jobs(source_id: str = None, reason: str = "force_restart") -> dict:
    """실행 중인 Job들을 interrupted 상태로 변경."""
    import json
    from pathlib import Path
    from datetime import datetime, timezone
    from app.services.dataset_builder_lock import get_active_jobs, JOBS_DIR

    jobs = get_active_jobs(source_id=source_id)
    interrupted_count = 0

    for job in jobs:
        job_file = Path(job.get("file_path", ""))
        if not job_file.exists():
            continue
        try:
            job_data = json.loads(job_file.read_text(encoding="utf-8"))
            job_data["status"] = "interrupted"
            job_data["interrupted_at"] = datetime.now(timezone.utc).isoformat()
            job_data["interrupt_reason"] = reason
            job_file.write_text(json.dumps(job_data, ensure_ascii=False, indent=2), encoding="utf-8")
            interrupted_count += 1
            logger.info(f"[ServiceManager] Job 중단: {job.get('job_id')} (reason={reason})")
        except Exception as e:
            logger.warning(f"[ServiceManager] Job 중단 오류 {job_file}: {e}")

    return {
        "interrupted_count": interrupted_count,
        "total_jobs": len(jobs),
        "reason": reason,
    }


async def prepare_build_environment(source_id: str, force_restart: bool = False) -> dict:
    """
    데이터셋 빌드 환경 준비.
    1. 기존 running Job 확인 및 처리
    2. 의존 서비스(OCR, Ollama) 확인/재시작
    """
    results = {
        "source_id": source_id,
        "force_restart": force_restart,
        "jobs": {},
        "services": {},
        "all_ready": True,
    }

    # 1. 기존 running Job 처리
    active_jobs = get_active_build_jobs(source_id=source_id)
    results["jobs"]["active_before"] = active_jobs

    if active_jobs["has_running_jobs"]:
        if force_restart:
            # Force 모드: 기존 Job 중단
            interrupt_result = interrupt_active_jobs(source_id=source_id, reason="force_restart")
            results["jobs"]["interrupted"] = interrupt_result
            logger.info(f"[ServiceManager] Force 모드: {interrupt_result['interrupted_count']}개 Job 중단")
        else:
            # 일반 모드: 기존 Job이 있으면 경고
            results["jobs"]["warning"] = f"실행 중인 Job이 {active_jobs['count']}개 있습니다."
            results["all_ready"] = False
            return results

    # 2. 의존 서비스 확인/재시작
    service_result = await ensure_services_ready(force_restart=force_restart)
    results["services"] = service_result

    if not service_result.get("all_ready"):
        results["all_ready"] = False

    return results
