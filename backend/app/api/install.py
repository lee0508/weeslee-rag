"""
Initial installation API.

Creates the `.env`, prepares runtime directories, initializes the database,
and stores an installation state marker so a fresh deployment can be set up
from the browser.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from app.core.config import PROJECT_ROOT, reload_runtime_settings, settings
from app.core.database import configure_database, init_db

router = APIRouter(prefix="/install", tags=["Install"])

ENV_PATH = PROJECT_ROOT / ".env"
INSTALL_STATE_PATH = PROJECT_ROOT / "data" / "config" / "install_state.json"
PLATFORM_CONFIG_DIR = PROJECT_ROOT / "platform_config"
JSON_STORE_FILES = [
    "tags.json",
    "keywords.json",
    "collection_templates.json",
    "metadata_templates.json",
]


class InstallRequest(BaseModel):
    app_name: str = "PromptoRAG"
    app_env: str = "production"
    debug: bool = False

    admin_username: str = "admin"
    admin_password: str = Field(min_length=4)

    db_host: str
    db_port: int = 3306
    db_name: str
    db_user: str
    db_password: str = ""

    knowledge_source_mount: str = "/mnt/w2_project"
    knowledge_source_unc: str = ""
    rag_source_folder: str = "00. RAG 테스트"

    ollama_host: str = "http://localhost:11434"
    answer_model: str = "gemma4:latest"
    ollama_embed_model: str = "nomic-embed-text"
    embedding_dim: int = 768
    max_embed_chars: int = 8000

    data_dir: str = str(PROJECT_ROOT / "data")
    upload_dir: str = str(PROJECT_ROOT / "uploads")
    faiss_index_dir: str = str(PROJECT_ROOT / "data" / "indexes" / "faiss")

    force_reinstall: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_path(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return value
    return str(Path(value).expanduser())


def _is_installed() -> bool:
    # 1차: install_state.json 존재 확인
    if INSTALL_STATE_PATH.exists():
        return True
    # 2차: .env 파일이 존재하면 설치된 것으로 간주 (수동 설정 또는 파일 손실 대비)
    if ENV_PATH.exists():
        return True
    return False


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_env(payload: dict[str, Any]) -> None:
    lines = [
        f"APP_NAME={payload['app_name']}",
        f"APP_ENV={payload['app_env']}",
        f"DEBUG={'True' if payload['debug'] else 'False'}",
        f"SECRET_KEY={payload['secret_key']}",
        f"ADMIN_USERNAME={payload['admin_username']}",
        f"ADMIN_PASSWORD={payload['admin_password']}",
        f"JWT_SECRET_KEY={payload['jwt_secret_key']}",
        f"DB_HOST={payload['db_host']}",
        f"DB_PORT={payload['db_port']}",
        f"DB_NAME={payload['db_name']}",
        f"DB_USER={payload['db_user']}",
        f"DB_PASSWORD={payload['db_password']}",
        f"OLLAMA_HOST={payload['ollama_host']}",
        f"OLLAMA_MODEL={payload['answer_model']}",
        f"OLLAMA_EMBED_MODEL={payload['ollama_embed_model']}",
        f"EMBEDDING_PROVIDER=ollama",
        f"EMBEDDING_DIM={payload['embedding_dim']}",
        f"MAX_EMBED_CHARS={payload['max_embed_chars']}",
        f"ANSWER_PROVIDER=ollama",
        f"ANSWER_MODEL={payload['answer_model']}",
        f"DATA_DIR={payload['data_dir']}",
        f"UPLOAD_DIR={payload['upload_dir']}",
        f"FAISS_INDEX_DIR={payload['faiss_index_dir']}",
        f"KNOWLEDGE_SOURCE_MOUNT={payload['knowledge_source_mount']}",
        f"KNOWLEDGE_SOURCE_UNC={payload['knowledge_source_unc']}",
        f"RAG_SOURCE_FOLDER={payload['rag_source_folder']}",
    ]
    _ensure_parent(ENV_PATH)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _create_database(req: InstallRequest) -> None:
    admin_url = URL.create(
        "mysql+pymysql",
        username=req.db_user,
        password=req.db_password,
        host=req.db_host,
        port=req.db_port,
        database="mysql",
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(admin_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{req.db_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        engine.dispose()


def _create_runtime_directories(payload: dict[str, Any]) -> list[str]:
    created: list[str] = []
    root_data = Path(payload["data_dir"])
    dirs = [
        root_data,
        root_data / "config",
        root_data / "indexes",
        root_data / "indexes" / "faiss",
        root_data / "staged",
        root_data / "staged" / "manifest",
        root_data / "staged" / "text",
        root_data / "staged" / "metadata",
        root_data / "staged" / "chunks",
        root_data / "processed_text",
        root_data / "extracted_text",
        root_data / "wiki",
        root_data / "graph",
        root_data / "reviews",
        root_data / "snapshots",
        Path(payload["upload_dir"]),
        PLATFORM_CONFIG_DIR,
        PROJECT_ROOT / "logs",
    ]

    mount_path = str(payload.get("knowledge_source_mount") or "").strip()
    if mount_path and not mount_path.startswith("\\\\"):
        dirs.append(Path(mount_path))

    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
        created.append(str(directory))

    for file_name in JSON_STORE_FILES:
        path = PLATFORM_CONFIG_DIR / file_name
        if not path.exists():
            path.write_text("[]\n", encoding="utf-8")

    return created


def _write_install_state(payload: dict[str, Any], warnings: list[str]) -> None:
    INSTALL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "installed": True,
        "installed_at": _now_iso(),
        "app_name": payload["app_name"],
        "db_name": payload["db_name"],
        "admin_username": payload["admin_username"],
        "knowledge_source_mount": payload["knowledge_source_mount"],
        "ollama_host": payload["ollama_host"],
        "answer_model": payload["answer_model"],
        "embedding_model": payload["ollama_embed_model"],
        "warnings": warnings,
    }
    INSTALL_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_sql_migrations() -> list[str]:
    migrations_dir = PROJECT_ROOT / "backend" / "scripts" / "migrations"
    warnings: list[str] = []
    if not migrations_dir.exists():
        return warnings

    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as conn:
            for migration_file in sorted(migrations_dir.glob("*.sql")):
                sql = migration_file.read_text(encoding="utf-8")
                statements = [part.strip() for part in sql.split(";") if part.strip()]
                for statement in statements:
                    try:
                        conn.execute(text(statement))
                    except Exception as exc:
                        warnings.append(f"{migration_file.name}: {exc}")
                        break
    finally:
        engine.dispose()

    return warnings


def _apply_runtime_install(req: InstallRequest) -> dict[str, Any]:
    secret_key = secrets.token_urlsafe(32)
    jwt_secret_key = secrets.token_urlsafe(32)
    payload = {
        "app_name": req.app_name.strip() or "PromptoRAG",
        "app_env": req.app_env.strip() or "production",
        "debug": bool(req.debug),
        "secret_key": secret_key,
        "admin_username": req.admin_username.strip() or "admin",
        "admin_password": req.admin_password,
        "jwt_secret_key": jwt_secret_key,
        "db_host": req.db_host.strip(),
        "db_port": req.db_port,
        "db_name": req.db_name.strip(),
        "db_user": req.db_user.strip(),
        "db_password": req.db_password,
        "knowledge_source_mount": _normalize_path(req.knowledge_source_mount),
        "knowledge_source_unc": req.knowledge_source_unc.strip(),
        "rag_source_folder": req.rag_source_folder.strip() or "00. RAG 테스트",
        "ollama_host": req.ollama_host.strip(),
        "answer_model": req.answer_model.strip() or "gemma4:latest",
        "ollama_embed_model": req.ollama_embed_model.strip() or "nomic-embed-text",
        "embedding_dim": req.embedding_dim,
        "max_embed_chars": req.max_embed_chars,
        "data_dir": _normalize_path(req.data_dir),
        "upload_dir": _normalize_path(req.upload_dir),
        "faiss_index_dir": _normalize_path(req.faiss_index_dir),
    }

    _create_database(req)
    _write_env(payload)
    reload_runtime_settings()
    configure_database()
    created_dirs = _create_runtime_directories(payload)
    init_db()
    warnings = _run_sql_migrations()
    _write_install_state(payload, warnings)
    return {
        "payload": payload,
        "created_dirs": created_dirs,
        "warnings": warnings,
    }


@router.get("/status")
async def install_status():
    state = None
    env_exists = ENV_PATH.exists()
    state_exists = INSTALL_STATE_PATH.exists()

    # .env는 있지만 install_state.json이 없는 경우 자동 복구
    if env_exists and not state_exists:
        try:
            _auto_recover_install_state()
            state_exists = INSTALL_STATE_PATH.exists()
        except Exception:
            pass

    if state_exists:
        try:
            state = json.loads(INSTALL_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = {"installed": True, "state_file_error": True}

    return {
        "installed": _is_installed(),
        "env_exists": env_exists,
        "state": state,
    }


def _auto_recover_install_state() -> None:
    """
    .env 파일이 존재하지만 install_state.json이 없는 경우 자동 복구.
    """
    INSTALL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    recovered_state = {
        "installed": True,
        "installed_at": _now_iso(),
        "app_name": getattr(settings, "app_name", "PromptoRAG"),
        "db_name": getattr(settings, "db_name", "unknown"),
        "admin_username": getattr(settings, "admin_username", "admin"),
        "knowledge_source_mount": getattr(settings, "knowledge_source_mount", ""),
        "ollama_host": getattr(settings, "ollama_host", ""),
        "answer_model": getattr(settings, "answer_model", ""),
        "embedding_model": getattr(settings, "ollama_embed_model", ""),
        "warnings": [],
        "auto_recovered": True,
        "recovered_at": _now_iso(),
    }
    INSTALL_STATE_PATH.write_text(
        json.dumps(recovered_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@router.post("/apply")
async def install_apply(req: InstallRequest):
    if _is_installed() and not req.force_reinstall:
        raise HTTPException(
            status_code=409,
            detail="이미 설치된 상태입니다. 재설치가 필요하면 force_reinstall=true로 요청하세요.",
        )

    try:
        result = _apply_runtime_install(req)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"설치 실패: {exc}") from exc

    return {
        "success": True,
        "message": "설치가 완료되었습니다.",
        "installed_at": _now_iso(),
        "admin_username": result["payload"]["admin_username"],
        "db_name": result["payload"]["db_name"],
        "created_dirs": result["created_dirs"],
        "warnings": result["warnings"],
        "next_url": "/weeslee-rag/frontend/admin.html",
    }
