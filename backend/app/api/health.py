"""
Health check endpoints
"""
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks

router = APIRouter()


# ── OCR 서버 헬스체크 ─────────────────────────────────────────────────────────
@router.get("/health/ocr")
async def ocr_health():
    """OCR 서버 연결 헬스체크."""
    from app.services.service_manager import check_service_health
    return await check_service_health("ocr")


# ── 서비스 통합 헬스체크 ──────────────────────────────────────────────────────
@router.get("/health/services")
async def services_health():
    """Dataset Builder 의존 서비스 전체 헬스체크."""
    from app.services.service_manager import check_all_services
    return await check_all_services()


# ── 서비스 재시작 API ─────────────────────────────────────────────────────────
@router.post("/health/services/{service_key}/restart")
async def restart_service(service_key: str):
    """특정 서비스 재시작."""
    from app.services.service_manager import restart_service as do_restart
    return await do_restart(service_key)


@router.post("/health/services/ensure-ready")
async def ensure_services_ready():
    """모든 필수 서비스가 준비되었는지 확인하고 필요시 재시작."""
    from app.services.service_manager import ensure_services_ready as do_ensure
    return await do_ensure()

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FAISS_DIR = _PROJECT_ROOT / "data" / "indexes" / "faiss"
_ACTIVE_INDEX_PATH = _PROJECT_ROOT / "data" / "active_index.json"


def _read_active_snapshot() -> str:
    """Read active snapshot name from active_index.json."""
    if _ACTIVE_INDEX_PATH.exists():
        try:
            data = json.loads(_ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
            return data.get("snapshot", "")
        except Exception:
            pass
    try:
        from app.core.config import settings
        return settings.faiss_snapshot
    except Exception:
        return ""


@router.get("/health")
async def health_check():
    """Basic health check"""
    return {"status": "healthy"}


@router.get("/health/ollama")
async def ollama_health():
    """Ollama connection health check"""
    try:
        from app.services.ollama import get_ollama
        ollama = get_ollama()
        result = await ollama.check_connection()
        if result["connected"]:
            models = [m.get("name", "unknown") for m in result.get("models", [])]
            return {"status": "healthy", "ollama": "connected", "models": models[:5]}
        return {"status": "unhealthy", "ollama": "disconnected",
                "error": result.get("error", "Unknown error")}
    except Exception as exc:
        return {"status": "unhealthy", "ollama": "disconnected", "error": str(exc)}


@router.get("/health/ollama/models")
async def ollama_models():
    """Ollama에서 사용 가능한 모델 목록을 LLM과 임베딩으로 분류하여 반환"""
    try:
        from app.services.ollama import get_ollama
        ollama = get_ollama()
        models = await ollama.list_models()

        # 임베딩 모델 패턴 (이름에 embed, bge, e5 등 포함)
        embedding_patterns = ["embed", "bge", "e5-", "gte-", "nomic"]

        llm_models = []
        embedding_models = []

        for m in models:
            name = m.get("name", "")
            model_info = {
                "name": name,
                "size": m.get("size", 0),
                "modified_at": m.get("modified_at", ""),
            }

            # 임베딩 모델인지 확인
            is_embedding = any(p in name.lower() for p in embedding_patterns)
            if is_embedding:
                embedding_models.append(model_info)
            else:
                llm_models.append(model_info)

        return {
            "status": "ok",
            "llm_models": llm_models,
            "embedding_models": embedding_models,
            "total": len(models)
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "llm_models": [],
            "embedding_models": []
        }


@router.get("/health/all")
async def full_health_check():
    """Full system health check — all components checked independently."""
    results: dict = {"status": "healthy", "components": {}}

    # ── Database (optional — graceful if not configured) ──────────────────
    try:
        from sqlalchemy import text
        from app.core.database import get_db
        db = next(get_db())
        db.execute(text("SELECT 1"))
        results["components"]["database"] = {"status": "healthy"}
    except Exception as exc:
        results["components"]["database"] = {
            "status": "unavailable",
            "error": str(exc)[:120],
        }

    # ── Ollama ────────────────────────────────────────────────────────────
    try:
        from app.services.ollama import get_ollama
        ollama = get_ollama()
        ollama_result = await ollama.check_connection()
        if ollama_result["connected"]:
            results["components"]["ollama"] = {
                "status": "healthy",
                "model_count": len(ollama_result.get("models", [])),
                "models": [m.get("name", "") for m in ollama_result.get("models", [])][:5],
            }
        else:
            results["status"] = "degraded"
            results["components"]["ollama"] = {
                "status": "unhealthy",
                "error": ollama_result.get("error", "Unknown"),
            }
    except Exception as exc:
        results["status"] = "degraded"
        results["components"]["ollama"] = {"status": "unhealthy", "error": str(exc)[:120]}

    # ── FAISS active index ────────────────────────────────────────────────
    snapshot = _read_active_snapshot()
    faiss_index = _FAISS_DIR / f"{snapshot}_ollama.index" if snapshot else None
    faiss_meta  = _FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl" if snapshot else None

    # 카테고리별 인덱스 fallback (메인 인덱스 없을 때)
    _CATEGORY_SUFFIXES = ("rfp", "proposal", "deliverable")
    available_categories = []
    if snapshot and (not faiss_index or not faiss_index.exists()):
        for cat in _CATEGORY_SUFFIXES:
            cat_index = _FAISS_DIR / f"{snapshot}_{cat}_ollama.index"
            cat_meta = _FAISS_DIR / f"{snapshot}_{cat}_ollama_metadata.jsonl"
            if cat_index.exists() and cat_meta.exists():
                available_categories.append(cat)
                # 첫 번째 카테고리 인덱스를 fallback으로 사용
                if faiss_index is None or not faiss_index.exists():
                    faiss_index = cat_index
                    faiss_meta = cat_meta

    chunk_count = 0
    if faiss_meta and faiss_meta.exists():
        try:
            chunk_count = sum(
                1 for line in faiss_meta.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        except Exception:
            pass

    # 카테고리별 인덱스가 있으면 전체 청크 수 합산
    if available_categories:
        chunk_count = 0
        for cat in available_categories:
            cat_meta = _FAISS_DIR / f"{snapshot}_{cat}_ollama_metadata.jsonl"
            if cat_meta.exists():
                try:
                    chunk_count += sum(
                        1 for line in cat_meta.read_text(encoding="utf-8").splitlines() if line.strip()
                    )
                except Exception:
                    pass

    faiss_ok = bool(faiss_index and faiss_index.exists())
    if not faiss_ok:
        results["status"] = "degraded"

    results["components"]["faiss"] = {
        "status":       "healthy" if faiss_ok else "unhealthy",
        "snapshot":     snapshot or "(none)",
        "index_exists": faiss_ok,
        "chunk_count":  chunk_count,
        "available_categories": available_categories if available_categories else None,
    }

    return results
