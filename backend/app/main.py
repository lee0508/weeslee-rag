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
from app.core.locale_env import normalize_process_locale_env
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
from app.api.wiki_search import router as wiki_search_router
from app.api.benchmark import router as benchmark_router
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
from app.api.admin_dataset_builder_settings import router as admin_dataset_builder_settings_router
from app.api.admin_dataset_builder_simple import router as admin_dataset_builder_router
from app.api.admin_dataset_builder_step4 import (
    router as admin_dataset_builder_step4_router,
    sse_router as admin_dataset_builder_step4_sse_router,
)
from app.api.admin_dataset_builder_step5 import router as admin_dataset_builder_step5_router
from app.api.admin_dataset_builder_step6 import router as admin_dataset_builder_step6_router
from app.api.admin_dataset_builder_step7 import router as admin_dataset_builder_step7_router
from app.api.admin_dataset_builder_step8 import router as admin_dataset_builder_step8_router
from app.api.admin_dataset_builder_step9 import router as admin_dataset_builder_step9_router
from app.api.admin_dataset_builder_step10 import router as admin_dataset_builder_step10_router
from app.api.snapshot_admin import router as snapshot_admin_router
from app.api.admin_knowledge_graph import router as admin_knowledge_graph_router
from app.api.admin_llm_wiki import router as admin_llm_wiki_router
from app.api.admin_publish import router as admin_publish_router
from app.api.admin_search_scopes import router as admin_search_scopes_router
from app.api.admin_system_settings import router as admin_system_settings_router
from app.api.install import router as install_router
from app.api.qa_services import router as qa_services_router
from app.api.system_runtime import router as system_runtime_router
from app.api.user_auth import router as user_auth_router, init_user_auth_tables
from app.api.chat_sessions import router as chat_sessions_router, init_chat_tables
from app.api.pptx_slide_search import router as pptx_slide_search_router
try:
    from app.api.vectorization import router as vectorization_router
    _vectorization_available = True
except ImportError:
    vectorization_router = None
    _vectorization_available = False
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
APP_LOCALE = normalize_process_locale_env(prefer_korean=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    print(f"Starting {settings.app_name}...")
    print(f"Environment: {settings.app_env}")
    print(f"Debug: {settings.debug}")
    print(f"Locale: {APP_LOCALE}")

    # Initialize database tables when credentials are available.
    # The RAG query UI can still start without DB-backed admin features.
    try:
        init_db()
        print("Database initialized")
        init_user_auth_tables()
        print("User auth tables initialized")
        # 채팅 세션 테이블 초기화 (Phase B)
        init_chat_tables()
        print("Chat session tables initialized")
    except Exception as exc:
        print(f"Database initialization skipped: {exc}")

    # 서버 재시작 시 중단된 Job 상태 정리
    try:
        from app.services.dataset_builder_lock import mark_stale_jobs_interrupted
        updated_count = mark_stale_jobs_interrupted()
        if updated_count > 0:
            print(f"Interrupted jobs marked: {updated_count}")
    except Exception as exc:
        print(f"Interrupted job cleanup skipped: {exc}")

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
app.include_router(wiki_search_router, prefix="/api", tags=["Wiki Search"])
app.include_router(benchmark_router, prefix="/api", tags=["Benchmark"])
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
app.include_router(admin_dataset_builder_settings_router, prefix="/api", tags=["Admin - Dataset Builder Settings"])
app.include_router(admin_dataset_builder_router, prefix="/api", tags=["Admin - Dataset Builder"])
app.include_router(admin_dataset_builder_step4_router, prefix="/api", tags=["Admin - Dataset Builder Step 4"])
app.include_router(admin_dataset_builder_step4_sse_router, prefix="/api", tags=["Admin - Dataset Builder Step 4 SSE"])
app.include_router(admin_dataset_builder_step5_router, prefix="/api", tags=["Admin - Dataset Builder Step 5"])
app.include_router(admin_dataset_builder_step6_router, prefix="/api", tags=["Admin - Dataset Builder Step 6"])
app.include_router(admin_dataset_builder_step7_router, prefix="/api", tags=["Admin - Dataset Builder Step 7"])
app.include_router(admin_dataset_builder_step8_router, prefix="/api", tags=["Admin - Dataset Builder Step 8"])
app.include_router(admin_dataset_builder_step9_router, prefix="/api", tags=["Admin - Dataset Builder Step 9"])
app.include_router(admin_dataset_builder_step10_router, prefix="/api", tags=["Admin - Dataset Builder Step 10"])
app.include_router(snapshot_admin_router, prefix="/api/admin", tags=["Admin - Snapshot"])
app.include_router(admin_knowledge_graph_router, prefix="/api", tags=["Admin - Knowledge Graph"])
app.include_router(admin_llm_wiki_router, prefix="/api", tags=["Admin - LLM Wiki"])
app.include_router(admin_publish_router, prefix="/api", tags=["Admin - Publish"])
app.include_router(admin_search_scopes_router, prefix="/api", tags=["Admin - Search Scopes"])
app.include_router(admin_system_settings_router, prefix="/api", tags=["Admin - System Settings"])
app.include_router(install_router, prefix="/api", tags=["Install"])
app.include_router(qa_services_router, prefix="/api", tags=["QA Services"])
app.include_router(system_runtime_router, prefix="/api", tags=["System Runtime"])
app.include_router(user_auth_router, prefix="/api", tags=["User Auth"])
app.include_router(chat_sessions_router, prefix="/api", tags=["Chat Sessions"])
app.include_router(pptx_slide_search_router, tags=["PPTX Slide Search"])
if _ocr_results_available and ocr_results_router is not None:
    app.include_router(ocr_results_router, prefix="/api", tags=["OCR Results"])
if _collections_available and collections_router is not None:
    app.include_router(collections_router, prefix="/api", tags=["Collections"])
if _vectorization_available and vectorization_router is not None:
    app.include_router(vectorization_router, prefix="/api", tags=["Vectorization"])

# [2026-07-08] /weeslee-rag/api prefix 지원 (프론트엔드 호환성)
app.include_router(auth_router, prefix="/weeslee-rag/api", tags=["Auth"])
app.include_router(health_router, prefix="/weeslee-rag/api", tags=["Health"])
app.include_router(admin_router, prefix="/weeslee-rag/api", tags=["Admin"])
app.include_router(admin_public_router, prefix="/weeslee-rag/api", tags=["Admin Public"])
app.include_router(ocr_router, prefix="/weeslee-rag/api", tags=["OCR"])
app.include_router(knowledge_sources_router, prefix="/weeslee-rag/api", tags=["Knowledge Sources"])
app.include_router(rag_router, prefix="/weeslee-rag/api", tags=["RAG"])
app.include_router(files_router, prefix="/weeslee-rag/api", tags=["Files"])
app.include_router(documents_router, prefix="/weeslee-rag/api", tags=["Documents"])
app.include_router(faiss_admin_router, prefix="/weeslee-rag/api", tags=["FAISS Admin"])
app.include_router(faiss_sse_router, prefix="/weeslee-rag/api", tags=["FAISS Admin SSE"])
app.include_router(graph_router, prefix="/weeslee-rag/api", tags=["Graph"])
app.include_router(wiki_router, prefix="/weeslee-rag/api", tags=["Wiki"])
app.include_router(wiki_search_router, prefix="/weeslee-rag/api", tags=["Wiki Search"])
app.include_router(benchmark_router, prefix="/weeslee-rag/api", tags=["Benchmark"])
app.include_router(review_router, prefix="/weeslee-rag/api", tags=["Review"])
app.include_router(clients_router, prefix="/weeslee-rag/api", tags=["Platform - Clients"])
app.include_router(document_sources_router, prefix="/weeslee-rag/api", tags=["Platform - Document Sources"])
app.include_router(mounts_router, prefix="/weeslee-rag/api", tags=["Platform - Mounts"])
app.include_router(templates_router, prefix="/weeslee-rag/api", tags=["Platform - Templates"])
app.include_router(rag_source_admin_router, prefix="/weeslee-rag/api", tags=["RAG Source Admin"])
app.include_router(tags_router, prefix="/weeslee-rag/api", tags=["Platform - Tags"])
app.include_router(keywords_router, prefix="/weeslee-rag/api", tags=["Platform - Keywords"])
app.include_router(query_logs_router, prefix="/weeslee-rag/api", tags=["Admin Query Logs"])
app.include_router(admin_metadata_review_router, prefix="/weeslee-rag/api", tags=["Admin - Metadata Review"])
app.include_router(admin_dataset_builder_settings_router, prefix="/weeslee-rag/api", tags=["Admin - Dataset Builder Settings"])
app.include_router(admin_dataset_builder_router, prefix="/weeslee-rag/api", tags=["Admin - Dataset Builder"])
app.include_router(admin_dataset_builder_step4_router, prefix="/weeslee-rag/api", tags=["Admin - Dataset Builder Step 4"])
app.include_router(admin_dataset_builder_step4_sse_router, prefix="/weeslee-rag/api", tags=["Admin - Dataset Builder Step 4 SSE"])
app.include_router(admin_dataset_builder_step5_router, prefix="/weeslee-rag/api", tags=["Admin - Dataset Builder Step 5"])
app.include_router(admin_dataset_builder_step6_router, prefix="/weeslee-rag/api", tags=["Admin - Dataset Builder Step 6"])
app.include_router(admin_dataset_builder_step7_router, prefix="/weeslee-rag/api", tags=["Admin - Dataset Builder Step 7"])
app.include_router(admin_dataset_builder_step8_router, prefix="/weeslee-rag/api", tags=["Admin - Dataset Builder Step 8"])
app.include_router(admin_dataset_builder_step9_router, prefix="/weeslee-rag/api", tags=["Admin - Dataset Builder Step 9"])
app.include_router(admin_dataset_builder_step10_router, prefix="/weeslee-rag/api", tags=["Admin - Dataset Builder Step 10"])
app.include_router(snapshot_admin_router, prefix="/weeslee-rag/api/admin", tags=["Admin - Snapshot"])
app.include_router(admin_knowledge_graph_router, prefix="/weeslee-rag/api", tags=["Admin - Knowledge Graph"])
app.include_router(admin_llm_wiki_router, prefix="/weeslee-rag/api", tags=["Admin - LLM Wiki"])
app.include_router(admin_publish_router, prefix="/weeslee-rag/api", tags=["Admin - Publish"])
app.include_router(admin_search_scopes_router, prefix="/weeslee-rag/api", tags=["Admin - Search Scopes"])
app.include_router(admin_system_settings_router, prefix="/weeslee-rag/api", tags=["Admin - System Settings"])
app.include_router(install_router, prefix="/weeslee-rag/api", tags=["Install"])
app.include_router(qa_services_router, prefix="/weeslee-rag/api", tags=["QA Services"])
app.include_router(system_runtime_router, prefix="/weeslee-rag/api", tags=["System Runtime"])
app.include_router(user_auth_router, prefix="/weeslee-rag/api", tags=["User Auth"])
app.include_router(chat_sessions_router, prefix="/weeslee-rag/api", tags=["Chat Sessions"])
app.include_router(pptx_slide_search_router, prefix="/weeslee-rag", tags=["PPTX Slide Search"])
if _ocr_results_available and ocr_results_router is not None:
    app.include_router(ocr_results_router, prefix="/weeslee-rag/api", tags=["OCR Results"])
if _collections_available and collections_router is not None:
    app.include_router(collections_router, prefix="/weeslee-rag/api", tags=["Collections"])
if _vectorization_available and vectorization_router is not None:
    app.include_router(vectorization_router, prefix="/weeslee-rag/api", tags=["Vectorization"])

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
