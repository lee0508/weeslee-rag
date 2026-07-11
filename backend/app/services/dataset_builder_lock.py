# Dataset Builder 탭 잠금 및 진행 상태 관리 서비스
"""
Dataset Builder는 동시에 1명만 사용 가능.
빌드 진행 중이면 다른 세션에서 탭 접근 불가.
브라우저 종료 후 재접속 시 진행 상태 복원.
Stale job 감지: N분 이상 진행 없으면 stalled/interrupted 상태로 전환.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.core.config import settings

logger = logging.getLogger(__name__)

# 잠금 파일 경로
LOCK_FILE = Path(settings.data_dir) / "jobs" / "dataset_builder_lock.json"
JOBS_DIR = Path(settings.data_dir) / "jobs"

# Stale 감지 타임아웃 (분 단위)
STALE_WARNING_MINUTES = 5   # 5분 이상 변화 없음 → stalled (정지 의심)
STALE_TIMEOUT_MINUTES = 15  # 15분 이상 변화 없음 → interrupted (중단됨)


def _ensure_jobs_dir():
    """jobs 디렉토리 생성"""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_lock_status() -> Dict[str, Any]:
    """현재 잠금 상태 조회"""
    _ensure_jobs_dir()
    if not LOCK_FILE.exists():
        return {
            "locked": False,
            "session_id": None,
            "source_id": None,
            "current_step": None,
            "locked_at": None,
            "last_heartbeat": None,
            "progress": None,
        }
    try:
        data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        return {
            "locked": data.get("locked", False),
            "session_id": data.get("session_id"),
            "source_id": data.get("source_id"),
            "current_step": data.get("current_step"),
            "locked_at": data.get("locked_at"),
            "last_heartbeat": data.get("last_heartbeat"),
            "progress": data.get("progress"),
        }
    except Exception as e:
        logger.error(f"잠금 파일 읽기 오류: {e}")
        return {"locked": False, "session_id": None, "error": str(e)}


def acquire_lock(session_id: str, source_id: Optional[str] = None) -> Dict[str, Any]:
    """
    잠금 획득 시도.
    이미 다른 세션이 잠금 중이면 실패.
    같은 session_id면 갱신.
    """
    _ensure_jobs_dir()
    current = get_lock_status()

    # 이미 잠금 중이고 다른 세션이면 실패
    if current.get("locked") and current.get("session_id") != session_id:
        return {
            "success": False,
            "message": "다른 세션에서 Dataset Builder를 사용 중입니다.",
            "locked_by": current.get("session_id"),
            "locked_at": current.get("locked_at"),
            "current_step": current.get("current_step"),
            "source_id": current.get("source_id"),
        }

    # 잠금 획득 또는 갱신
    now = _utc_now_iso()
    lock_data = {
        "locked": True,
        "session_id": session_id,
        "source_id": source_id or current.get("source_id"),
        "current_step": current.get("current_step"),
        "locked_at": current.get("locked_at") or now,
        "last_heartbeat": now,
        "progress": current.get("progress"),
    }

    try:
        LOCK_FILE.write_text(json.dumps(lock_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "success": True,
            "message": "잠금 획득 성공",
            "session_id": session_id,
            "locked_at": lock_data["locked_at"],
        }
    except Exception as e:
        logger.error(f"잠금 파일 쓰기 오류: {e}")
        return {"success": False, "message": f"잠금 파일 쓰기 오류: {e}"}


def release_lock(session_id: str, force: bool = False) -> Dict[str, Any]:
    """
    잠금 해제.
    본인 세션이거나 force=True일 때만 해제.
    """
    current = get_lock_status()

    if not current.get("locked"):
        return {"success": True, "message": "이미 잠금 해제 상태입니다."}

    if not force and current.get("session_id") != session_id:
        return {
            "success": False,
            "message": "다른 세션의 잠금을 해제할 수 없습니다.",
            "locked_by": current.get("session_id"),
        }

    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
        return {"success": True, "message": "잠금 해제 완료"}
    except Exception as e:
        logger.error(f"잠금 해제 오류: {e}")
        return {"success": False, "message": f"잠금 해제 오류: {e}"}


def update_progress(
    session_id: str,
    current_step: int,
    progress: int,
    source_id: Optional[str] = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    진행 상태 업데이트 (heartbeat 역할도 수행).
    """
    current = get_lock_status()

    if not current.get("locked"):
        return {"success": False, "message": "잠금이 없습니다."}

    if current.get("session_id") != session_id:
        return {"success": False, "message": "다른 세션의 잠금입니다."}

    now = _utc_now_iso()
    lock_data = {
        "locked": True,
        "session_id": session_id,
        "source_id": source_id or current.get("source_id"),
        "current_step": current_step,
        "locked_at": current.get("locked_at"),
        "last_heartbeat": now,
        "progress": {
            "step": current_step,
            "percent": progress,
            "message": message,
            "updated_at": now,
        },
    }

    try:
        LOCK_FILE.write_text(json.dumps(lock_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"success": True, "updated_at": now}
    except Exception as e:
        logger.error(f"진행 상태 업데이트 오류: {e}")
        return {"success": False, "message": str(e)}


def get_active_jobs(source_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    진행 중인 Job 목록 조회.
    data/jobs/step{N}_*/ 폴더에서 status=running인 job 파일 검색.
    """
    _ensure_jobs_dir()
    active_jobs = []

    step_dirs = ["step4_parse", "step5_chunk", "step6_embed"]

    for step_dir in step_dirs:
        step_path = JOBS_DIR / step_dir
        if not step_path.exists():
            continue

        for job_file in step_path.glob("*.json"):
            try:
                job_data = json.loads(job_file.read_text(encoding="utf-8"))
                if job_data.get("status") == "running":
                    # source_id 필터링
                    job_source = job_data.get("last_event", {}).get("source_id")
                    if source_id and job_source != source_id:
                        continue

                    active_jobs.append({
                        "job_id": job_data.get("job_id"),
                        "step": step_dir.replace("step", "").replace("_parse", "").replace("_chunk", "").replace("_embed", ""),
                        "source_id": job_source,
                        "status": job_data.get("status"),
                        "created_at": job_data.get("created_at"),
                        "last_event": job_data.get("last_event"),
                        "file_path": str(job_file),
                    })
            except Exception as e:
                logger.warning(f"Job 파일 읽기 오류 {job_file}: {e}")

    return active_jobs


def get_resumable_state(source_id: str) -> Optional[Dict[str, Any]]:
    """
    특정 source_id의 재개 가능한 상태 조회.
    가장 최근 running 상태의 job을 찾아 반환.
    """
    active_jobs = get_active_jobs(source_id=source_id)
    if not active_jobs:
        return None

    # 가장 최근 job 반환
    active_jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    latest = active_jobs[0]

    return {
        "source_id": source_id,
        "job_id": latest.get("job_id"),
        "current_step": int(latest.get("step", 0)),
        "last_event": latest.get("last_event"),
        "can_resume": True,
        "message": f"Step {latest.get('step')}에서 중단됨. 이어서 진행 가능합니다.",
    }


def mark_stale_jobs_interrupted():
    """
    서버 시작 시 호출하여 running 상태인 job을 interrupted로 변경.
    """
    _ensure_jobs_dir()
    step_dirs = ["step4_parse", "step5_chunk", "step6_embed"]
    updated = 0

    for step_dir in step_dirs:
        step_path = JOBS_DIR / step_dir
        if not step_path.exists():
            continue

        for job_file in step_path.glob("*.json"):
            try:
                job_data = json.loads(job_file.read_text(encoding="utf-8"))
                if job_data.get("status") == "running":
                    job_data["status"] = "interrupted"
                    job_data["interrupted_at"] = _utc_now_iso()
                    job_data["interrupt_reason"] = "server_restart"
                    job_file.write_text(json.dumps(job_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    updated += 1
                    logger.info(f"Job 상태 변경: {job_file.name} -> interrupted")
            except Exception as e:
                logger.warning(f"Job 상태 변경 오류 {job_file}: {e}")

    return updated


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """ISO 형식 타임스탬프를 datetime으로 파싱 (KST → UTC 변환)."""
    if not ts:
        return None
    try:
        # 다양한 ISO 형식 처리
        ts = ts.replace("Z", "+00:00")
        if "+" not in ts and "-" not in ts[10:] and ts.count(":") >= 2:
            # naive datetime → KST(+09:00)로 가정 후 UTC로 변환
            dt = datetime.fromisoformat(ts)
            # KST offset (UTC+9)
            kst_offset = timedelta(hours=9)
            # KST를 UTC로 변환
            return (dt - kst_offset).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _get_job_last_activity(job_data: Dict[str, Any]) -> Optional[datetime]:
    """Job의 마지막 활동 시간 추출."""
    # 우선순위: persisted_at > last_event.timestamp > created_at
    candidates = [
        job_data.get("persisted_at"),
        job_data.get("last_event", {}).get("timestamp") if job_data.get("last_event") else None,
        job_data.get("created_at"),
    ]
    for ts in candidates:
        parsed = _parse_timestamp(ts)
        if parsed:
            return parsed
    return None


def check_stale_jobs(
    auto_update: bool = False,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    running 상태 Job 중 stale(오래 정지된) Job 감지.

    Args:
        auto_update: True면 stale job 상태를 자동으로 stalled/interrupted로 변경
        source_id: 특정 source_id만 필터링

    Returns:
        {
            "checked_at": "...",
            "stale_jobs": [...],
            "healthy_jobs": [...],
            "updated_count": 0
        }
    """
    _ensure_jobs_dir()
    now = datetime.now(timezone.utc)
    stale_warning_threshold = now - timedelta(minutes=STALE_WARNING_MINUTES)
    stale_timeout_threshold = now - timedelta(minutes=STALE_TIMEOUT_MINUTES)

    step_dirs = ["step4_parse", "step5_chunk", "step6_embed"]
    stale_jobs = []
    healthy_jobs = []
    updated_count = 0

    for step_dir in step_dirs:
        step_path = JOBS_DIR / step_dir
        if not step_path.exists():
            continue

        for job_file in step_path.glob("*.json"):
            try:
                job_data = json.loads(job_file.read_text(encoding="utf-8"))

                # running 상태만 체크
                if job_data.get("status") != "running":
                    continue

                # source_id 필터
                job_source = job_data.get("source_id") or job_data.get("last_event", {}).get("source_id")
                if source_id and job_source != source_id:
                    continue

                last_activity = _get_job_last_activity(job_data)
                if not last_activity:
                    continue

                # 마지막 활동 시간 계산
                idle_minutes = (now - last_activity).total_seconds() / 60

                job_info = {
                    "job_id": job_data.get("job_id"),
                    "step": step_dir,
                    "source_id": job_source,
                    "last_activity": last_activity.isoformat(),
                    "idle_minutes": round(idle_minutes, 1),
                    "current_file": job_data.get("last_event", {}).get("file_name"),
                    "progress": job_data.get("last_event", {}).get("progress"),
                    "sequence": job_data.get("last_event", {}).get("sequence"),
                    "total_documents": job_data.get("last_event", {}).get("total_documents"),
                    "file_path": str(job_file),
                }

                # 상태 판단
                if last_activity < stale_timeout_threshold:
                    # 15분 이상 → interrupted
                    job_info["stale_status"] = "interrupted"
                    job_info["stale_reason"] = f"{STALE_TIMEOUT_MINUTES}분 이상 진행 없음 (타임아웃)"
                    job_info["recommendation"] = "재시작 필요"
                    stale_jobs.append(job_info)

                    if auto_update:
                        job_data["status"] = "interrupted"
                        job_data["interrupted_at"] = _utc_now_iso()
                        job_data["interrupt_reason"] = "stale_timeout"
                        job_data["stale_detected_at"] = _utc_now_iso()
                        job_data["stale_idle_minutes"] = round(idle_minutes, 1)
                        job_file.write_text(json.dumps(job_data, ensure_ascii=False, indent=2), encoding="utf-8")
                        updated_count += 1
                        logger.warning(f"Stale job interrupted: {job_file.name} (idle {idle_minutes:.1f}분)")

                elif last_activity < stale_warning_threshold:
                    # 5분 이상 → stalled (경고)
                    job_info["stale_status"] = "stalled"
                    job_info["stale_reason"] = f"{STALE_WARNING_MINUTES}분 이상 진행 없음 (정지 의심)"
                    job_info["recommendation"] = "문제 문서 확인 필요"
                    stale_jobs.append(job_info)

                    if auto_update:
                        job_data["status"] = "stalled"
                        job_data["stalled_at"] = _utc_now_iso()
                        job_data["stale_detected_at"] = _utc_now_iso()
                        job_data["stale_idle_minutes"] = round(idle_minutes, 1)
                        job_file.write_text(json.dumps(job_data, ensure_ascii=False, indent=2), encoding="utf-8")
                        updated_count += 1
                        logger.warning(f"Stale job marked stalled: {job_file.name} (idle {idle_minutes:.1f}분)")

                else:
                    # 정상 진행 중
                    job_info["stale_status"] = "healthy"
                    healthy_jobs.append(job_info)

            except Exception as e:
                logger.warning(f"Stale check 오류 {job_file}: {e}")

    return {
        "checked_at": _utc_now_iso(),
        "thresholds": {
            "stalled_minutes": STALE_WARNING_MINUTES,
            "interrupted_minutes": STALE_TIMEOUT_MINUTES,
        },
        "stale_jobs": stale_jobs,
        "healthy_jobs": healthy_jobs,
        "stale_count": len(stale_jobs),
        "healthy_count": len(healthy_jobs),
        "updated_count": updated_count,
        "auto_update": auto_update,
    }


def get_job_health_status(source_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Job 상태 요약 조회 (UI 표시용).
    running job이 실제로 진행 중인지, stale 상태인지 판단.
    """
    stale_check = check_stale_jobs(auto_update=False, source_id=source_id)

    # 전체 상태 판단
    if stale_check["stale_count"] > 0:
        # stale job이 있으면 가장 심각한 상태 반환
        worst_status = "stalled"
        for job in stale_check["stale_jobs"]:
            if job["stale_status"] == "interrupted":
                worst_status = "interrupted"
                break

        first_stale = stale_check["stale_jobs"][0]
        return {
            "overall_status": worst_status,
            "message": first_stale["stale_reason"],
            "recommendation": first_stale["recommendation"],
            "problem_file": first_stale.get("current_file"),
            "idle_minutes": first_stale.get("idle_minutes"),
            "stale_jobs": stale_check["stale_jobs"],
            "healthy_jobs": stale_check["healthy_jobs"],
        }

    elif stale_check["healthy_count"] > 0:
        first_healthy = stale_check["healthy_jobs"][0]
        return {
            "overall_status": "running",
            "message": "정상 진행 중",
            "current_file": first_healthy.get("current_file"),
            "progress": first_healthy.get("progress"),
            "idle_minutes": first_healthy.get("idle_minutes"),
            "healthy_jobs": stale_check["healthy_jobs"],
            "stale_jobs": [],
        }

    else:
        return {
            "overall_status": "idle",
            "message": "실행 중인 Job 없음",
            "stale_jobs": [],
            "healthy_jobs": [],
        }
