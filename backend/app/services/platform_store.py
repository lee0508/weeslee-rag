# 플랫폼 설정(Client/DocumentSource/Template)을 JSON 파일로 저장/조회하는 공통 저장소
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "platform_config"
_LOCK = threading.Lock()
_STORE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


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


def list_records(store_name: str) -> list[dict]:
    with _LOCK:
        return _load(store_name)


def get_record(store_name: str, id_field: str, id_value: str) -> dict | None:
    with _LOCK:
        return next((r for r in _load(store_name) if r.get(id_field) == id_value), None)


def create_record(store_name: str, data: dict, id_field: str = "id") -> dict:
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


def update_record(
    store_name: str, id_field: str, id_value: str, updates: dict
) -> dict | None:
    with _LOCK:
        records = _load(store_name)
        for i, r in enumerate(records):
            if r.get(id_field) == id_value:
                records[i] = {**r, **updates, "updated_at": _now()}
                _save(store_name, records)
                return records[i]
    return None


def delete_record(store_name: str, id_field: str, id_value: str) -> bool:
    with _LOCK:
        records = _load(store_name)
        new_records = [r for r in records if r.get(id_field) != id_value]
        if len(new_records) == len(records):
            return False
        _save(store_name, new_records)
        return True


def seed_if_empty(store_name: str, defaults: list[dict], id_field: str = "id") -> None:
    """저장소가 비어 있을 때만 기본 데이터를 삽입한다."""
    with _LOCK:
        if _load(store_name):
            return
        now = _now()
        seeded = [{**d, "created_at": now, "updated_at": now} for d in defaults]
        _save(store_name, seeded)
