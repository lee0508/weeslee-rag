# Document UID 생성 유틸리티
"""
source_id + relative_path 기반 문서 고유 식별자 생성 및 변경 감지 유틸리티.
Reference: docs/2026-06-12_Claude_QA_V1_Followup_ToLee.md
"""
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


def make_document_uid(source_id: str, relative_path: str) -> str:
    """
    source_id + relative_path 기반 문서 고유 식별자 생성.

    Args:
        source_id: Document Source ID (e.g., "rag_source")
        relative_path: mount_path + root_subpath 기준 상대 경로

    Returns:
        SHA1 해시 문자열 (40자)
    """
    key = f"{source_id}:{relative_path}".strip()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def calculate_file_checksum(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """
    파일 전체 내용 기준 SHA256 체크섬 계산.

    Args:
        file_path: 파일 경로
        chunk_size: 읽기 단위 (기본 1MB)

    Returns:
        SHA256 해시 문자열 (64자)
    """
    h = hashlib.sha256()

    with file_path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)

    return h.hexdigest()


def detect_file_change(
    old_size: Optional[int],
    old_modified_at: Optional[datetime],
    old_checksum: Optional[str],
    current_size: int,
    current_modified_at: datetime,
    file_path: Optional[Path] = None,
) -> Tuple[str, Optional[str]]:
    """
    파일 변경 여부 감지 (2단계 방식).

    1차: file_size + modified_at 빠른 비교
    2차: 변경 의심 시 checksum 계산

    Args:
        old_size: 이전 파일 크기
        old_modified_at: 이전 수정 시간
        old_checksum: 이전 체크섬
        current_size: 현재 파일 크기
        current_modified_at: 현재 수정 시간
        file_path: 체크섬 계산을 위한 파일 경로 (선택)

    Returns:
        (status, new_checksum)
        status: "new", "changed", "maybe_changed", "unchanged"
        new_checksum: 계산된 경우 새 체크섬
    """
    # 신규 파일
    if old_size is None:
        new_checksum = None
        if file_path and file_path.exists():
            new_checksum = calculate_file_checksum(file_path)
        return "new", new_checksum

    # 1차: 파일 크기 변경
    if old_size != current_size:
        new_checksum = None
        if file_path and file_path.exists():
            new_checksum = calculate_file_checksum(file_path)
        return "changed", new_checksum

    # 2차: 수정 시간 변경
    if old_modified_at != current_modified_at:
        # 정밀 확인 필요
        if file_path and file_path.exists() and old_checksum:
            new_checksum = calculate_file_checksum(file_path)
            if old_checksum != new_checksum:
                return "changed", new_checksum
            else:
                return "unchanged", new_checksum
        return "maybe_changed", None

    # 동일
    return "unchanged", None


def resolve_source_and_relative_path(
    file_path: str,
    source_roots: dict,
) -> Tuple[Optional[str], Optional[str]]:
    """
    절대 경로에서 source_id와 relative_path를 역산.

    Args:
        file_path: 절대 파일 경로
        source_roots: {source_id: Path(scan_root)} 딕셔너리

    Returns:
        (source_id, relative_path) 또는 (None, None)
    """
    p = Path(file_path)

    for source_id, root in source_roots.items():
        try:
            rel = p.relative_to(root).as_posix()
            return source_id, rel
        except ValueError:
            continue

    return None, None
