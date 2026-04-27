"""
PromptoRAG FastAPI Application
"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import init_db
from app.api.health import router as health_router
from app.api.collections import router as collections_router
from app.api.documents import router as documents_router
from app.api.ocr import router as ocr_router
from app.api.knowledge_sources import router as knowledge_sources_router
from app.api.rag import router as rag_router


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    print(f"Starting {settings.app_name}...")
    print(f"Environment: {settings.app_env}")
    print(f"Debug: {settings.debug}")

    # Initialize database tables when credentials are available.
    # The RAG query UI can still start without DB-backed admin features.
    try:
        init_db()
        print("Database initialized")
    except Exception as exc:
        print(f"Database initialization skipped: {exc}")

    yield

    # Shutdown
    print("Shutting down...")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="RAG-based document generation system for consulting documents",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router, tags=["Health"])
app.include_router(collections_router, prefix="/api/admin", tags=["Collections"])
app.include_router(documents_router, prefix="/api/admin", tags=["Documents"])
app.include_router(ocr_router, prefix="/api", tags=["OCR"])
app.include_router(knowledge_sources_router, prefix="/api", tags=["Knowledge Sources"])
app.include_router(rag_router, prefix="/api", tags=["RAG"])

# Serve the assistant UI under the requested path pattern:
# /weeslee-rag/frontend/rag-assistant.html
if FRONTEND_DIR.exists():
    app.mount(
        "/weeslee-rag/frontend",
        StaticFiles(directory=str(FRONTEND_DIR), html=True),
        name="weeslee-rag-frontend",
    )


@app.get("/weeslee-rag")
async def weeslee_rag_root():
    return RedirectResponse(url="/weeslee-rag/frontend/rag-assistant.html")


@app.get("/weeslee-rag/")
async def weeslee_rag_root_slash():
    return RedirectResponse(url="/weeslee-rag/frontend/rag-assistant.html")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "running"
    }
