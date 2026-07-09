# -*- coding: utf-8 -*-
"""
런타임 모델 설정 조회 헬퍼.

우선순위:
1. 시스템 설정 DB의 enabled client.default_embedding_model
2. 첫 번째 client.default_embedding_model
3. .env / settings 기본값
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.platform_config import PlatformClient


def _normalize_model_name(value: Optional[str]) -> str:
    model = str(value or "").strip()
    if not model:
        return ""
    if "/" in model:
        model = model.split("/", 1)[1].strip()
    return model


def get_runtime_embedding_model(fallback: Optional[str] = None) -> str:
    fallback_model = _normalize_model_name(fallback) or _normalize_model_name(settings.ollama_embed_model) or "nomic-embed-text"

    try:
        db = SessionLocal()
        try:
            active_client = (
                db.query(PlatformClient)
                .filter(PlatformClient.enabled.is_(True))
                .order_by(PlatformClient.created_at.asc(), PlatformClient.client_id.asc())
                .first()
            )
            if active_client and active_client.default_embedding_model:
                return _normalize_model_name(active_client.default_embedding_model) or fallback_model

            any_client = (
                db.query(PlatformClient)
                .order_by(PlatformClient.created_at.asc(), PlatformClient.client_id.asc())
                .first()
            )
            if any_client and any_client.default_embedding_model:
                return _normalize_model_name(any_client.default_embedding_model) or fallback_model
        finally:
            db.close()
    except SQLAlchemyError:
        pass

    return fallback_model
