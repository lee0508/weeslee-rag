"""
Database connection and session management
"""
from sqlalchemy import create_engine
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
        document,
        document_metadata,
        document_structure,
        execution,
        graph_schema,
        platform_config,
        prompt,
    )

    Base.metadata.create_all(bind=engine)
