# Dataset Builder 의존 서비스 관리 모듈
"""
OCR 서버, Ollama 등 데이터셋 빌드에 필요한 서비스들의 상태 확인 및 재시작.
"""
import asyncio
import logging
import subprocess
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


# 서비스 설정
SERVICES = {
    "ocr": ServiceConfig(
        name="OCR Server",
        health_url="http://127.0.0.1:5000/health",
        start_cmd="cd /data/weeslee/pdf-ocr && source venv/bin/activate && nohup python python/advanced_ocr_server.py > /tmp/ocr_server.log 2>&1 &",
        stop_cmd="pkill -f 'advanced_ocr_server.py'",
        port=5000,
        timeout=10.0,
    ),
    "ollama": ServiceConfig(
        name="Ollama",
        health_url="http://127.0.0.1:11434/api/tags",
        start_cmd="systemctl start ollama",
        stop_cmd="systemctl stop ollama",
        port=11434,
        timeout=5.0,
    ),
}


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


def restart_service_sync(service_key: str) -> dict:
    """서비스 동기 재시작 (subprocess 사용)."""
    if service_key not in SERVICES:
        return {"success": False, "message": f"알 수 없는 서비스: {service_key}"}

    config = SERVICES[service_key]
    logger.info(f"[ServiceManager] {config.name} 재시작 시작")

    try:
        # 1. 서비스 중지
        subprocess.run(
            config.stop_cmd,
            shell=True,
            timeout=10,
            capture_output=True,
        )
        logger.info(f"[ServiceManager] {config.name} 중지 완료")

        # 2. 잠시 대기
        import time
        time.sleep(2)

        # 3. 서비스 시작
        subprocess.Popen(
            config.start_cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(f"[ServiceManager] {config.name} 시작 명령 실행")

        # 4. 시작 대기 (최대 30초)
        for _ in range(15):
            time.sleep(2)
            try:
                import requests
                resp = requests.get(config.health_url, timeout=3)
                if resp.status_code == 200:
                    logger.info(f"[ServiceManager] {config.name} 정상 시작 확인")
                    return {
                        "success": True,
                        "service": config.name,
                        "message": "서비스 재시작 완료",
                    }
            except Exception:
                continue

        return {
            "success": False,
            "service": config.name,
            "message": "서비스 시작 후 응답 없음",
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


async def ensure_services_ready() -> dict:
    """
    데이터셋 빌드에 필요한 모든 서비스가 준비되었는지 확인.
    필요시 자동 재시작.
    """
    results = {"actions": [], "all_ready": True}

    for key, config in SERVICES.items():
        health = await check_service_health(key)

        if health.get("status") == "healthy":
            results["actions"].append({
                "service": config.name,
                "action": "none",
                "status": "already_healthy",
            })
        else:
            # 서비스 재시작 시도
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
