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


def resolve_scan_root(source: Mapping[str, object], scan_path: str = "") -> Path:
    """
    Document Source에서 실제 스캔 루트 경로를 계산한다.

    Args:
        source: Document Source 설정 (mount_path, root_subpath 등)
        scan_path: 선택적 하위 경로 또는 절대 경로
            - 절대 경로인 경우: 해당 경로를 직접 사용 (예: /mnt/w2_project/01. 국내사업폴더)
            - 상대 경로인 경우: mount_path/root_subpath + scan_path를 합침 (예: 01. RFP)
            - 빈 문자열: 기본 동작 (mount_path + root_subpath)

    Returns:
        계산된 스캔 루트 경로
    """
    scan_path = (scan_path or "").strip()

    # 절대 경로인 경우 해당 경로를 직접 사용
    if scan_path and (scan_path.startswith("/") or (len(scan_path) > 1 and scan_path[1] == ":")):
        return Path(scan_path)

    # 기본 스캔 루트 계산
    base_root = resolve_scan_path(
        str(source.get("mount_path") or ""),
        str(source.get("root_subpath") or ""),
        str(source.get("source_uri") or ""),
    )

    # scan_path가 있으면 추가
    if scan_path:
        return Path(base_root) / scan_path

    return Path(base_root)
