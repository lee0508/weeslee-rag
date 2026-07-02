"""
Database connection and session management
"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.core.config import settings

def _build_engine(database_url: str):
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=settings.debug,
    )


# Create SQLAlchemy engine
engine = _build_engine(settings.database_url)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


CLIENTS_TABLE_EXTRA_COLUMNS = {
    "ocr_mode": "VARCHAR(30) NULL DEFAULT 'auto'",
    "ocr_language": "VARCHAR(50) NULL DEFAULT 'kor+eng'",
    "ocr_dpi": "INT NULL DEFAULT 300",
    "ocr_engine": "VARCHAR(50) NULL DEFAULT 'tesseract'",
    "ocr_supported_extensions": "TEXT NULL",
    "ocr_min_text_length": "INT NULL DEFAULT 50",
    "ocr_image_preprocess": "VARCHAR(50) NULL DEFAULT 'none'",
    "ocr_hwp_extractor": "VARCHAR(50) NULL DEFAULT 'pyhwp'",
    "ocr_table_extract": "TINYINT(1) NULL DEFAULT 1",
    "ocr_max_file_size_mb": "INT NULL DEFAULT 100",
}

CLIENTS_TABLE_DEFAULT_BACKFILL = {
    "ocr_mode": "auto",
    "ocr_language": "kor+eng",
    "ocr_dpi": 300,
    "ocr_engine": "tesseract",
    "ocr_supported_extensions": ".pdf, .docx, .hwp, .hwpx, .pptx, .xlsx",
    "ocr_min_text_length": 50,
    "ocr_image_preprocess": "none",
    "ocr_hwp_extractor": "pyhwp",
    "ocr_table_extract": 1,
    "ocr_max_file_size_mb": 100,
}


def configure_database(database_url: str | None = None) -> None:
    """Rebind the shared engine/sessionmaker after install-time config changes."""
    global engine

    next_engine = _build_engine(database_url or settings.database_url)
    SessionLocal.configure(bind=next_engine)

    try:
        engine.dispose()
    except Exception:
        pass

    engine = next_engine


def get_db() -> Generator[Session, None, None]:
    """
    Dependency to get database session.
    Usage in FastAPI:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Initialize database tables.
    Call this on application startup.
    """
    # Import all models to register them with Base
    from app.models import (  # noqa: F401
        collection,
        dataset_build_settings,
        document,
        document_metadata,
        document_structure,
        execution,
        graph_schema,
        platform_config,
        prompt,
    )

    Base.metadata.create_all(bind=engine)
    _ensure_platform_client_columns()


def _ensure_platform_client_columns() -> None:
    """Backfill newly added clients table columns on existing MySQL installs."""
    inspector = inspect(engine)
    try:
        tables = set(inspector.get_table_names())
    except Exception:
        return

    if "clients" not in tables:
        return

    try:
        existing_columns = {col["name"] for col in inspector.get_columns("clients")}
    except Exception:
        return

    missing = {
        name: ddl for name, ddl in CLIENTS_TABLE_EXTRA_COLUMNS.items()
        if name not in existing_columns
    }
    if not missing:
        return

    with engine.begin() as conn:
        for column_name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE clients ADD COLUMN {column_name} {ddl}"))
        for column_name, default_value in CLIENTS_TABLE_DEFAULT_BACKFILL.items():
            if column_name in missing or column_name in existing_columns:
                conn.execute(
                    text(
                        f"UPDATE clients SET {column_name} = :default_value "
                        f"WHERE {column_name} IS NULL"
                    ),
                    {"default_value": default_value},
                )
