"""
Platform config store.

`clients` and `document_sources` use MySQL as the primary store.
Other low-frequency template/tag/keyword stores remain JSON-backed.
Legacy JSON files are imported once when a DB-backed table is empty.
"""
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.database import SessionLocal
from app.models.platform_config import PlatformClient, PlatformDocumentSource, PlatformLlmSettings
from sqlalchemy.exc import SQLAlchemyError

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "platform_config"
_LOCK = threading.Lock()
_STORE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DB_STORE_MODELS = {
    "clients": (PlatformClient, "client_id"),
    "document_sources": (PlatformDocumentSource, "source_id"),
    "llm_settings": (PlatformLlmSettings, "id"),
}


def _store_path(store_name: str) -> Path:
    if not _STORE_NAME_RE.match(store_name):
        raise ValueError(f"Invalid store name: {store_name!r}")
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return _CONFIG_DIR / f"{store_name}.json"


def _load(store_name: str) -> list[dict]:
    path = _store_path(store_name)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save(store_name: str, records: list[dict]) -> None:
    _store_path(store_name).write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_db_store(store_name: str) -> bool:
    return store_name in _DB_STORE_MODELS


def _serialize_model(obj) -> dict:
    return {
        column.name: getattr(obj, column.name)
        for column in obj.__table__.columns
    }


def _normalize_db_payload(model_cls, data: dict, *, include_updated_at: bool = False) -> dict:
    column_names = {column.name for column in model_cls.__table__.columns}
    payload = {key: value for key, value in data.items() if key in column_names}
    now = _now()
    if "created_at" in column_names and not payload.get("created_at"):
        payload["created_at"] = now
    if include_updated_at and "updated_at" in column_names:
        payload["updated_at"] = now
    elif "updated_at" in column_names and not payload.get("updated_at"):
        payload["updated_at"] = now
    return payload


def _import_json_into_db(store_name: str) -> None:
    model_cls, id_field = _DB_STORE_MODELS[store_name]
    legacy_records = _load(store_name)
    if not legacy_records:
        return

    db = SessionLocal()
    try:
        if db.query(model_cls).count() > 0:
            return
        for record in legacy_records:
            payload = _normalize_db_payload(model_cls, record)
            if not payload.get(id_field):
                payload[id_field] = str(uuid.uuid4())
            db.add(model_cls(**payload))
        db.commit()
    finally:
        db.close()


def list_records(store_name: str) -> list[dict]:
    if not _is_db_store(store_name):
        with _LOCK:
            return _load(store_name)

    model_cls, id_field = _DB_STORE_MODELS[store_name]
    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(model_cls)
                .order_by(getattr(model_cls, "created_at"), getattr(model_cls, id_field))
                .all()
            )
            return [_serialize_model(row) for row in rows]
        finally:
            db.close()
    except SQLAlchemyError:
        with _LOCK:
            return _load(store_name)


def get_record(store_name: str, id_field: str, id_value: str) -> dict | None:
    if not _is_db_store(store_name):
        with _LOCK:
            return next((r for r in _load(store_name) if r.get(id_field) == id_value), None)

    model_cls, model_id_field = _DB_STORE_MODELS[store_name]
    if model_id_field != id_field:
        raise ValueError(f"Unsupported id field for {store_name}: {id_field}")
    try:
        db = SessionLocal()
        try:
            row = db.query(model_cls).filter(getattr(model_cls, id_field) == id_value).first()
            return _serialize_model(row) if row else None
        finally:
            db.close()
    except SQLAlchemyError:
        with _LOCK:
            return next((r for r in _load(store_name) if r.get(id_field) == id_value), None)


def create_record(store_name: str, data: dict, id_field: str = "id") -> dict:
    if not _is_db_store(store_name):
        with _LOCK:
            records = _load(store_name)
            if id_field not in data or not data[id_field]:
                data[id_field] = str(uuid.uuid4())
            now = _now()
            data.setdefault("created_at", now)
            data.setdefault("updated_at", now)
            records.append(data)
            _save(store_name, records)
            return data

    model_cls, model_id_field = _DB_STORE_MODELS[store_name]
    if model_id_field != id_field:
        raise ValueError(f"Unsupported id field for {store_name}: {id_field}")

    payload = dict(data)
    if not payload.get(id_field):
        payload[id_field] = str(uuid.uuid4())
    payload = _normalize_db_payload(model_cls, payload)

    try:
        db = SessionLocal()
        try:
            row = model_cls(**payload)
            db.add(row)
            db.commit()
            db.refresh(row)
            return _serialize_model(row)
        finally:
            db.close()
    except SQLAlchemyError:
        with _LOCK:
            records = _load(store_name)
            now = _now()
            payload.setdefault("created_at", now)
            payload.setdefault("updated_at", now)
            records.append(payload)
            _save(store_name, records)
            return payload


def update_record(
    store_name: str, id_field: str, id_value: str, updates: dict
) -> dict | None:
    if not _is_db_store(store_name):
        with _LOCK:
            records = _load(store_name)
            for i, r in enumerate(records):
                if r.get(id_field) == id_value:
                    records[i] = {**r, **updates, "updated_at": _now()}
                    _save(store_name, records)
                    return records[i]
        return None

    model_cls, model_id_field = _DB_STORE_MODELS[store_name]
    if model_id_field != id_field:
        raise ValueError(f"Unsupported id field for {store_name}: {id_field}")

    try:
        db = SessionLocal()
        try:
            row = db.query(model_cls).filter(getattr(model_cls, id_field) == id_value).first()
            if not row:
                return None
            payload = _normalize_db_payload(model_cls, updates, include_updated_at=True)
            for key, value in payload.items():
                setattr(row, key, value)
            db.commit()
            db.refresh(row)
            return _serialize_model(row)
        finally:
            db.close()
    except SQLAlchemyError:
        with _LOCK:
            records = _load(store_name)
            for i, r in enumerate(records):
                if r.get(id_field) == id_value:
                    records[i] = {**r, **updates, "updated_at": _now()}
                    _save(store_name, records)
                    return records[i]
        return None


def delete_record(store_name: str, id_field: str, id_value: str) -> bool:
    if not _is_db_store(store_name):
        with _LOCK:
            records = _load(store_name)
            new_records = [r for r in records if r.get(id_field) != id_value]
            if len(new_records) == len(records):
                return False
            _save(store_name, new_records)
            return True

    model_cls, model_id_field = _DB_STORE_MODELS[store_name]
    if model_id_field != id_field:
        raise ValueError(f"Unsupported id field for {store_name}: {id_field}")

    try:
        db = SessionLocal()
        try:
            row = db.query(model_cls).filter(getattr(model_cls, id_field) == id_value).first()
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True
        finally:
            db.close()
    except SQLAlchemyError:
        with _LOCK:
            records = _load(store_name)
            new_records = [r for r in records if r.get(id_field) != id_value]
            if len(new_records) == len(records):
                return False
            _save(store_name, new_records)
            return True


def seed_if_empty(store_name: str, defaults: list[dict], id_field: str = "id") -> None:
    """저장소가 비어 있을 때만 기본 데이터를 삽입한다."""
    if not _is_db_store(store_name):
        with _LOCK:
            if _load(store_name):
                return
            now = _now()
            seeded = [{**d, "created_at": now, "updated_at": now} for d in defaults]
            _save(store_name, seeded)
        return

    model_cls, model_id_field = _DB_STORE_MODELS[store_name]
    if model_id_field != id_field:
        raise ValueError(f"Unsupported id field for {store_name}: {id_field}")

    try:
        _import_json_into_db(store_name)

        db = SessionLocal()
        try:
            if db.query(model_cls).count() > 0:
                return
            now = _now()
            for record in defaults:
                payload = {**record, "created_at": record.get("created_at") or now, "updated_at": record.get("updated_at") or now}
                payload = _normalize_db_payload(model_cls, payload)
                if not payload.get(id_field):
                    payload[id_field] = str(uuid.uuid4())
                db.add(model_cls(**payload))
            db.commit()
        finally:
            db.close()
    except SQLAlchemyError:
        with _LOCK:
            if _load(store_name):
                return
            now = _now()
            seeded = [{**d, "created_at": d.get("created_at") or now, "updated_at": d.get("updated_at") or now} for d in defaults]
            _save(store_name, seeded)


# ─────────────────────────────────────────────────────────────────────────────
# LLM Settings 전용 함수 (client_id 기준 조회/저장)
# ─────────────────────────────────────────────────────────────────────────────

def get_llm_settings_by_client(client_id: str = "weeslee") -> dict | None:
    """client_id 기준으로 LLM Settings 조회."""
    try:
        db = SessionLocal()
        try:
            row = db.query(PlatformLlmSettings).filter(
                PlatformLlmSettings.client_id == client_id
            ).first()
            return _serialize_model(row) if row else None
        finally:
            db.close()
    except SQLAlchemyError:
        return None


def save_llm_settings_by_client(client_id: str, data: dict) -> dict:
    """client_id 기준으로 LLM Settings 저장 (upsert)."""
    try:
        db = SessionLocal()
        try:
            row = db.query(PlatformLlmSettings).filter(
                PlatformLlmSettings.client_id == client_id
            ).first()

            now = _now()
            payload = _normalize_db_payload(PlatformLlmSettings, data, include_updated_at=True)
            payload["client_id"] = client_id

            if row:
                for key, value in payload.items():
                    if key != "id":
                        setattr(row, key, value)
                db.commit()
                db.refresh(row)
                return _serialize_model(row)
            else:
                payload["created_at"] = now
                new_row = PlatformLlmSettings(**payload)
                db.add(new_row)
                db.commit()
                db.refresh(new_row)
                return _serialize_model(new_row)
        finally:
            db.close()
    except SQLAlchemyError as e:
        raise RuntimeError(f"DB 저장 실패: {e}")
