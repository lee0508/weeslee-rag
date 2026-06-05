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
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.ocr import router as ocr_router
from app.api.knowledge_sources import router as knowledge_sources_router
from app.api.rag import router as rag_router
from app.api.admin import router as admin_router, public_router as admin_public_router
from app.api.files import router as files_router
from app.api.faiss_admin import router as faiss_admin_router, sse_router as faiss_sse_router
from app.api.graph import router as graph_router
from app.api.wiki import router as wiki_router
from app.api.review import router as review_router
from app.api.documents import router as documents_router
from app.api.clients import router as clients_router
from app.api.document_sources import router as document_sources_router
from app.api.mounts import router as mounts_router
from app.api.templates import router as templates_router
from app.api.rag_source_admin import router as rag_source_admin_router
from app.api.tags import router as tags_router
from app.api.keywords import router as keywords_router
from app.api.query_logs import router as query_logs_router
from app.api.admin_metadata_review import router as admin_metadata_review_router
from app.api.admin_dataset_builder_simple import router as admin_dataset_builder_router
try:
    from app.api.ocr_results import router as ocr_results_router
    _ocr_results_available = True
except ImportError:
    ocr_results_router = None
    _ocr_results_available = False
try:
    from app.api.collections import router as collections_router
    _collections_available = True
except ImportError:
    collections_router = None
    _collections_available = False


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
app.include_router(auth_router, prefix="/api", tags=["Auth"])
app.include_router(health_router, prefix="/api", tags=["Health"])
app.include_router(admin_router, prefix="/api", tags=["Admin"])
app.include_router(admin_public_router, prefix="/api", tags=["Admin Public"])
app.include_router(ocr_router, prefix="/api", tags=["OCR"])
app.include_router(knowledge_sources_router, prefix="/api", tags=["Knowledge Sources"])
app.include_router(rag_router, prefix="/api", tags=["RAG"])
app.include_router(files_router, prefix="/api", tags=["Files"])
app.include_router(documents_router, prefix="/api", tags=["Documents"])
app.include_router(faiss_admin_router, prefix="/api", tags=["FAISS Admin"])
app.include_router(faiss_sse_router, prefix="/api", tags=["FAISS Admin SSE"])
app.include_router(graph_router, prefix="/api", tags=["Graph"])
app.include_router(wiki_router, prefix="/api", tags=["Wiki"])
app.include_router(review_router, prefix="/api", tags=["Review"])
app.include_router(clients_router, prefix="/api", tags=["Platform - Clients"])
app.include_router(document_sources_router, prefix="/api", tags=["Platform - Document Sources"])
app.include_router(mounts_router, prefix="/api", tags=["Platform - Mounts"])
app.include_router(templates_router, prefix="/api", tags=["Platform - Templates"])
app.include_router(rag_source_admin_router, prefix="/api", tags=["RAG Source Admin"])
app.include_router(tags_router, prefix="/api", tags=["Platform - Tags"])
app.include_router(keywords_router, prefix="/api", tags=["Platform - Keywords"])
app.include_router(query_logs_router, prefix="/api", tags=["Admin Query Logs"])
app.include_router(admin_metadata_review_router, prefix="/api", tags=["Admin - Metadata Review"])
app.include_router(admin_dataset_builder_router, prefix="/api", tags=["Admin - Dataset Builder"])
if _ocr_results_available and ocr_results_router is not None:
    app.include_router(ocr_results_router, prefix="/api", tags=["OCR Results"])
if _collections_available and collections_router is not None:
    app.include_router(collections_router, prefix="/api", tags=["Collections"])

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
