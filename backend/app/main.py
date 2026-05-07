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
from app.api.ocr import router as ocr_router
from app.api.knowledge_sources import router as knowledge_sources_router
from app.api.rag import router as rag_router
from app.api.admin import router as admin_router
from app.api.files import router as files_router
from app.api.faiss_admin import router as faiss_admin_router
from app.api.graph import router as graph_router
from app.api.wiki import router as wiki_router
from app.api.review import router as review_router


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
app.include_router(health_router, prefix="/api", tags=["Health"])
app.include_router(admin_router, prefix="/api", tags=["Admin"])
app.include_router(ocr_router, prefix="/api", tags=["OCR"])
app.include_router(knowledge_sources_router, prefix="/api", tags=["Knowledge Sources"])
app.include_router(rag_router, prefix="/api", tags=["RAG"])
app.include_router(files_router, prefix="/api", tags=["Files"])
app.include_router(faiss_admin_router, prefix="/api", tags=["FAISS Admin"])
app.include_router(graph_router, prefix="/api", tags=["Graph"])
app.include_router(wiki_router, prefix="/api", tags=["Wiki"])
app.include_router(review_router, prefix="/api", tags=["Review"])

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
