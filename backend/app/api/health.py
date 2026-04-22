"""
Health check endpoints
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.services.vectordb import get_vectordb, VectorDBService
from app.services.ollama import get_ollama, OllamaService

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check"""
    return {"status": "healthy"}


@router.get("/health/db")
async def db_health(db: Session = Depends(get_db)):
    """Database connection health check"""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}


@router.get("/health/ollama")
async def ollama_health(ollama: OllamaService = Depends(get_ollama)):
    """Ollama connection health check"""
    result = await ollama.check_connection()
    if result["connected"]:
        models = [m.get("name", "unknown") for m in result.get("models", [])]
        return {
            "status": "healthy",
            "ollama": "connected",
            "models": models[:5]  # First 5 models
        }
    return {
        "status": "unhealthy",
        "ollama": "disconnected",
        "error": result.get("error", "Unknown error")
    }


@router.get("/health/vectordb")
async def vectordb_health(vectordb: VectorDBService = Depends(get_vectordb)):
    """ChromaDB health check"""
    try:
        collections = vectordb.list_collections()
        return {
            "status": "healthy",
            "vectordb": "connected",
            "collections_count": len(collections)
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "vectordb": "disconnected",
            "error": str(e)
        }


@router.get("/health/all")
async def full_health_check(
    db: Session = Depends(get_db),
    ollama: OllamaService = Depends(get_ollama),
    vectordb: VectorDBService = Depends(get_vectordb)
):
    """Full system health check"""
    results = {
        "status": "healthy",
        "components": {}
    }

    # Database check
    try:
        db.execute(text("SELECT 1"))
        results["components"]["database"] = {"status": "healthy"}
    except Exception as e:
        results["status"] = "degraded"
        results["components"]["database"] = {"status": "unhealthy", "error": str(e)}

    # Ollama check
    ollama_result = await ollama.check_connection()
    if ollama_result["connected"]:
        results["components"]["ollama"] = {
            "status": "healthy",
            "model_count": len(ollama_result.get("models", []))
        }
    else:
        results["status"] = "degraded"
        results["components"]["ollama"] = {
            "status": "unhealthy",
            "error": ollama_result.get("error", "Unknown")
        }

    # VectorDB check
    try:
        collections = vectordb.list_collections()
        results["components"]["vectordb"] = {
            "status": "healthy",
            "collections_count": len(collections)
        }
    except Exception as e:
        results["status"] = "degraded"
        results["components"]["vectordb"] = {"status": "unhealthy", "error": str(e)}

    return results
