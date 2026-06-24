from pathlib import Path
from typing import Mapping


def _split_path_parts(value: str) -> list[str]:
    normalized = (value or "").replace("\\", "/").strip()
    return [part for part in normalized.split("/") if part and part != "."]


def resolve_scan_path(mount_path: str = "", root_subpath: str = "", source_uri: str = "") -> str:
    """mount_path와 root_subpath를 중복 없이 합쳐 실제 스캔 경로를 만든다."""
    base_path = (mount_path or source_uri or "").strip()
    subpath = (root_subpath or "").strip()

    if not base_path:
        return subpath
    if not subpath:
        return base_path

    base_parts = _split_path_parts(base_path)
    sub_parts = _split_path_parts(subpath)
    overlap = 0

    for size in range(min(len(base_parts), len(sub_parts)), 0, -1):
        if base_parts[-size:] == sub_parts[:size]:
            overlap = size
            break

    if overlap >= len(sub_parts):
        return base_path

    resolved = base_path.rstrip("/\\")
    for part in sub_parts[overlap:]:
        resolved = f"{resolved}/{part}"
    return resolved


def resolve_scan_root(source: Mapping[str, object]) -> Path:
    return Path(
        resolve_scan_path(
            str(source.get("mount_path") or ""),
            str(source.get("root_subpath") or ""),
            str(source.get("source_uri") or ""),
        )
    )
