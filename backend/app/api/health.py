"""
Health check endpoints
"""
import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

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

    chunk_count = 0
    if faiss_meta and faiss_meta.exists():
        try:
            chunk_count = sum(
                1 for line in faiss_meta.read_text(encoding="utf-8").splitlines() if line.strip()
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
    }

    return results
