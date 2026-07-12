# FAISS Snapshot 관리 서비스 - 버전 관리, 파일 생성, 활성화
"""
FAISS Snapshot 생명주기 관리.

주요 기능:
  - generate_snapshot_id(): Snapshot ID 자동 생성
  - get_next_version(): 동일 source_id의 다음 버전 번호
  - create_snapshot_files(): Snapshot 파일 생성 (index, metadata, manifest)
  - list_snapshots(): 저장된 Snapshot 목록 조회
  - get_snapshot_info(): 특정 Snapshot 상세 정보
  - delete_snapshot(): Snapshot 삭제
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(settings.data_dir).expanduser().resolve()
FAISS_DIR = Path(settings.faiss_index_dir).expanduser().resolve()
ACTIVE_INDEX_PATH = DATA_DIR / "active_index.json"
SNAPSHOT_DIR = DATA_DIR / "snapshots"


def get_operational_faiss_dir() -> Path:
    """운영 FAISS 인덱스 디렉토리 반환 (data/indexes/faiss/)."""
    return FAISS_DIR


def copy_index_to_operational_path(
    source_index_path: Path,
    source_metadata_path: Path,
    snapshot_id: str,
) -> tuple[Path, Path]:
    """
    step7_index에서 생성된 인덱스 파일을 운영 경로(data/indexes/faiss/)로 복사.

    Args:
        source_index_path: step7_index 내 인덱스 파일 경로
        source_metadata_path: step7_index 내 메타데이터 파일 경로
        snapshot_id: 스냅샷 ID

    Returns:
        (운영 인덱스 경로, 운영 메타데이터 경로) 튜플
    """
    import shutil

    FAISS_DIR.mkdir(parents=True, exist_ok=True)

    dest_index = FAISS_DIR / f"{snapshot_id}_ollama.index"
    dest_metadata = FAISS_DIR / f"{snapshot_id}_ollama_metadata.jsonl"

    # 파일 복사
    if source_index_path.exists():
        shutil.copy2(source_index_path, dest_index)

    if source_metadata_path.exists():
        shutil.copy2(source_metadata_path, dest_metadata)

    return dest_index, dest_metadata


def generate_snapshot_id(
    source_id: str = "rag_source",
    version: Optional[int] = None,
    date_str: Optional[str] = None,
) -> str:
    """
    Snapshot ID 생성.

    형식: snapshot_YYYYMMDD_{source_id}_V{N}
    예: snapshot_20260627_rag_source_V1

    Args:
        source_id: Document Source ID
        version: 버전 번호 (None이면 자동 증가)
        date_str: 날짜 문자열 (None이면 오늘)

    Returns:
        생성된 Snapshot ID
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    if version is None:
        version = get_next_version(source_id, date_str)

    return f"snapshot_{date_str}_{source_id}_V{version}"


def get_next_version(source_id: str, date_str: Optional[str] = None) -> int:
    """
    동일 source_id의 다음 버전 번호 반환.

    Args:
        source_id: Document Source ID
        date_str: 날짜 문자열 (None이면 오늘)

    Returns:
        다음 버전 번호 (기존 없으면 1)
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    prefix = f"snapshot_{date_str}_{source_id}_V"
    existing_versions = []

    if FAISS_DIR.exists():
        for f in FAISS_DIR.glob(f"{prefix}*_ollama.index"):
            try:
                stem = f.stem.replace("_ollama", "")
                v_part = stem.split("_V")[-1]
                existing_versions.append(int(v_part))
            except (ValueError, IndexError):
                continue

    return max(existing_versions, default=0) + 1


def create_snapshot_manifest(
    snapshot_id: str,
    source_id: str,
    dataset_id: str,
    vector_count: int,
    document_count: int,
    embedding_dim: int = 1024,
    embedding_provider: str = "ollama",
    embedding_model: str = "bge-m3",
    chunks_jsonl: Optional[str] = None,
) -> dict[str, Any]:
    """
    Snapshot manifest 파일 생성.

    Args:
        snapshot_id: Snapshot ID
        source_id: Document Source ID
        dataset_id: Dataset ID
        vector_count: 벡터 수
        document_count: 문서 수
        embedding_dim: 임베딩 차원
        embedding_provider: 임베딩 제공자
        embedding_model: 임베딩 모델명
        chunks_jsonl: 청크 JSONL 파일 경로

    Returns:
        생성된 manifest 딕셔너리
    """
    FAISS_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {
        "snapshot_id": snapshot_id,
        "source_id": source_id,
        "dataset_id": dataset_id,
        "created_at": datetime.now().isoformat(),
        "vector_count": vector_count,
        "document_count": document_count,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "chunks_jsonl": str(chunks_jsonl) if chunks_jsonl else None,
        "output_index": str(FAISS_DIR / f"{snapshot_id}_ollama.index"),
        "output_metadata": str(FAISS_DIR / f"{snapshot_id}_ollama_metadata.jsonl"),
    }

    manifest_path = FAISS_DIR / f"{snapshot_id}_ollama.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return manifest


def list_snapshots(
    source_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    저장된 Snapshot 목록 반환.

    Args:
        source_id: 필터링할 Source ID (None이면 전체)
        limit: 최대 반환 수

    Returns:
        Snapshot 정보 목록 (최신순)
    """
    snapshots = []

    if not FAISS_DIR.exists():
        return snapshots

    for manifest_file in sorted(FAISS_DIR.glob("*_ollama.manifest.json"), reverse=True):
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            snap_id = manifest.get("snapshot_id", manifest_file.stem.replace("_ollama.manifest", ""))

            if source_id and source_id not in snap_id:
                continue

            index_file = FAISS_DIR / f"{snap_id}_ollama.index"
            meta_file = FAISS_DIR / f"{snap_id}_ollama_metadata.jsonl"

            snapshots.append({
                "snapshot_id": snap_id,
                "source_id": manifest.get("source_id", ""),
                "dataset_id": manifest.get("dataset_id", ""),
                "created_at": manifest.get("created_at"),
                "vector_count": manifest.get("vector_count", 0),
                "document_count": manifest.get("document_count", 0),
                "embedding_model": manifest.get("embedding_model", "unknown"),
                "index_exists": index_file.exists(),
                "metadata_exists": meta_file.exists(),
                "index_size_mb": round(index_file.stat().st_size / 1024 / 1024, 2) if index_file.exists() else 0,
                "is_active": _is_active_snapshot(snap_id),
            })

            if len(snapshots) >= limit:
                break

        except Exception:
            continue

    return snapshots


def get_snapshot_info(snapshot_id: str) -> Optional[dict[str, Any]]:
    """
    특정 Snapshot 상세 정보 반환.

    Args:
        snapshot_id: Snapshot ID

    Returns:
        Snapshot 정보 딕셔너리 (없으면 None)
    """
    manifest_path = FAISS_DIR / f"{snapshot_id}_ollama.manifest.json"
    index_path = FAISS_DIR / f"{snapshot_id}_ollama.index"
    meta_path = FAISS_DIR / f"{snapshot_id}_ollama_metadata.jsonl"

    if not manifest_path.exists() and not index_path.exists():
        return None

    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    chunk_count = 0
    if meta_path.exists():
        try:
            chunk_count = sum(1 for line in meta_path.read_text(encoding="utf-8").splitlines() if line.strip())
        except Exception:
            pass

    return {
        "snapshot_id": snapshot_id,
        "source_id": manifest.get("source_id", ""),
        "dataset_id": manifest.get("dataset_id", ""),
        "created_at": manifest.get("created_at"),
        "vector_count": manifest.get("vector_count", chunk_count),
        "document_count": manifest.get("document_count", 0),
        "embedding_provider": manifest.get("embedding_provider", "ollama"),
        "embedding_model": manifest.get("embedding_model", "unknown"),
        "embedding_dim": manifest.get("embedding_dim", 0),
        "index_exists": index_path.exists(),
        "index_size_mb": round(index_path.stat().st_size / 1024 / 1024, 2) if index_path.exists() else 0,
        "metadata_exists": meta_path.exists(),
        "metadata_count": chunk_count,
        "manifest_exists": manifest_path.exists(),
        "is_active": _is_active_snapshot(snapshot_id),
        "files": {
            "index": str(index_path) if index_path.exists() else None,
            "metadata": str(meta_path) if meta_path.exists() else None,
            "manifest": str(manifest_path) if manifest_path.exists() else None,
        }
    }


def delete_snapshot(snapshot_id: str, force: bool = False) -> dict[str, Any]:
    """
    Snapshot 삭제 (연관 데이터 모두 삭제).

    삭제 대상:
    - FAISS Index 파일 (primary, category별)
    - Snapshot manifest
    - 청크 데이터 (staged/chunks/)
    - 메타데이터 (staged/metadata/)
    - 그래프 데이터 (graph/)
    - Wiki 데이터 (wiki/)

    Args:
        snapshot_id: 삭제할 Snapshot ID
        force: 활성 Snapshot도 강제 삭제 여부

    Returns:
        삭제 결과 딕셔너리

    Raises:
        ValueError: 활성 Snapshot 삭제 시도 (force=False)
    """
    import shutil

    if _is_active_snapshot(snapshot_id) and not force:
        raise ValueError(f"활성 Snapshot은 삭제할 수 없습니다: {snapshot_id}")

    deleted_files = []
    deleted_dirs = []

    # 1. FAISS Index 파일 삭제
    faiss_patterns = [
        f"{snapshot_id}_ollama.index",
        f"{snapshot_id}_ollama_metadata.jsonl",
        f"{snapshot_id}_ollama.manifest.json",
        f"{snapshot_id}_admin_stats.json",
    ]

    for pattern in faiss_patterns:
        file_path = FAISS_DIR / pattern
        if file_path.exists():
            file_path.unlink()
            deleted_files.append(f"faiss/{pattern}")

    # 카테고리 인덱스도 삭제
    for cat_file in FAISS_DIR.glob(f"{snapshot_id}_*_ollama.*"):
        cat_file.unlink()
        deleted_files.append(f"faiss/{cat_file.name}")

    # 2. Snapshot manifest 파일 삭제
    snapshot_manifest = SNAPSHOT_DIR / f"{snapshot_id}.json"
    if snapshot_manifest.exists():
        snapshot_manifest.unlink()
        deleted_files.append(f"snapshots/{snapshot_id}.json")

    # 3. 청크 데이터 삭제 (staged/chunks/)
    staged_chunks_dir = DATA_DIR / "staged" / "chunks"
    if staged_chunks_dir.exists():
        for chunk_file in staged_chunks_dir.glob(f"{snapshot_id}*"):
            chunk_file.unlink()
            deleted_files.append(f"staged/chunks/{chunk_file.name}")

    # 4. 메타데이터 삭제 (staged/metadata/)
    staged_metadata_dir = DATA_DIR / "staged" / "metadata"
    if staged_metadata_dir.exists():
        for meta_file in staged_metadata_dir.glob(f"{snapshot_id}*"):
            meta_file.unlink()
            deleted_files.append(f"staged/metadata/{meta_file.name}")

    # 5. 텍스트 산출물 삭제 (staged/text/)
    staged_text_dir = DATA_DIR / "staged" / "text"
    if staged_text_dir.exists():
        for text_file in staged_text_dir.glob(f"{snapshot_id}*"):
            text_file.unlink()
            deleted_files.append(f"staged/text/{text_file.name}")

    # 6. manifest 삭제 (staged/manifest/)
    staged_manifest_dir = DATA_DIR / "staged" / "manifest"
    if staged_manifest_dir.exists():
        for manifest_file in staged_manifest_dir.glob(f"{snapshot_id}*"):
            manifest_file.unlink()
            deleted_files.append(f"staged/manifest/{manifest_file.name}")

    # 7. 파이프라인 상태 삭제 (staged/)
    staged_dir = DATA_DIR / "staged"
    if staged_dir.exists():
        for state_file in staged_dir.glob(f"*{snapshot_id}*"):
            if state_file.is_file():
                state_file.unlink()
                deleted_files.append(f"staged/{state_file.name}")

    # 8. 그래프 데이터 삭제 (graph/)
    graph_dir = DATA_DIR / "graph"
    if graph_dir.exists():
        for graph_file in graph_dir.glob(f"{snapshot_id}*"):
            if graph_file.is_file():
                graph_file.unlink()
                deleted_files.append(f"graph/{graph_file.name}")
            elif graph_file.is_dir():
                shutil.rmtree(graph_file)
                deleted_dirs.append(f"graph/{graph_file.name}")

    # 9. Wiki 데이터 삭제 (wiki/)
    wiki_dir = DATA_DIR / "wiki"
    if wiki_dir.exists():
        for wiki_file in wiki_dir.glob(f"{snapshot_id}*"):
            if wiki_file.is_file():
                wiki_file.unlink()
                deleted_files.append(f"wiki/{wiki_file.name}")
            elif wiki_file.is_dir():
                shutil.rmtree(wiki_file)
                deleted_dirs.append(f"wiki/{wiki_file.name}")

    # 10. source_id 기반 wiki 폴더 삭제 (src_YYYYMMDD_HHMMSS_HASH 형식)
    # snapshot_id에서 src_ 부분 추출
    if "_src_" in snapshot_id:
        src_part = snapshot_id.split("_src_")[1].rsplit("_V", 1)[0]
        src_folder_name = f"src_{src_part}"
        src_wiki_dir = wiki_dir / src_folder_name
        if src_wiki_dir.exists() and src_wiki_dir.is_dir():
            shutil.rmtree(src_wiki_dir)
            deleted_dirs.append(f"wiki/{src_folder_name}")

    # 11. DB 정리 (document_metadata.faiss_snapshot, collections.snapshot_id)
    db_updates = _cleanup_db_references(snapshot_id)

    return {
        "snapshot_id": snapshot_id,
        "deleted": True,
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
        "deleted_count": len(deleted_files) + len(deleted_dirs),
        "db_updates": db_updates,
    }


def _cleanup_db_references(snapshot_id: str) -> dict[str, int]:
    """Snapshot 삭제 시 DB 참조 정리."""
    from app.core.database import SessionLocal
    from sqlalchemy import text

    db_updates = {
        "document_metadata_cleared": 0,
        "collections_cleared": 0,
    }

    try:
        db = SessionLocal()

        # document_metadata.faiss_snapshot 컬럼 NULL로 설정
        result = db.execute(
            text("UPDATE document_metadata SET faiss_snapshot = NULL WHERE faiss_snapshot = :snapshot_id"),
            {"snapshot_id": snapshot_id}
        )
        db_updates["document_metadata_cleared"] = result.rowcount

        # collections.snapshot_id 컬럼 NULL로 설정
        result = db.execute(
            text("UPDATE collections SET snapshot_id = NULL WHERE snapshot_id = :snapshot_id"),
            {"snapshot_id": snapshot_id}
        )
        db_updates["collections_cleared"] = result.rowcount

        db.commit()
    except Exception as e:
        db_updates["error"] = str(e)
        try:
            db.rollback()
        except:
            pass
    finally:
        try:
            db.close()
        except:
            pass

    return db_updates


def _is_active_snapshot(snapshot_id: str) -> bool:
    """현재 활성 Snapshot인지 확인."""
    if not ACTIVE_INDEX_PATH.exists():
        return False
    try:
        data = json.loads(ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
        active = data.get("active_snapshot") or data.get("snapshot") or ""
        return active == snapshot_id
    except Exception:
        return False


def get_active_snapshot_id() -> Optional[str]:
    """현재 활성 Snapshot ID 반환."""
    if not ACTIVE_INDEX_PATH.exists():
        return None
    try:
        data = json.loads(ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
        return data.get("active_snapshot") or data.get("snapshot")
    except Exception:
        return None


def compare_snapshots(snapshot_id_1: str, snapshot_id_2: str) -> dict[str, Any]:
    """
    두 Snapshot 비교.

    Args:
        snapshot_id_1: 첫 번째 Snapshot ID
        snapshot_id_2: 두 번째 Snapshot ID

    Returns:
        비교 결과 딕셔너리
    """
    info1 = get_snapshot_info(snapshot_id_1)
    info2 = get_snapshot_info(snapshot_id_2)

    if not info1 or not info2:
        return {
            "error": "Snapshot not found",
            "snapshot_1_exists": info1 is not None,
            "snapshot_2_exists": info2 is not None,
        }

    return {
        "snapshot_1": snapshot_id_1,
        "snapshot_2": snapshot_id_2,
        "vector_count_diff": (info2.get("vector_count", 0) or 0) - (info1.get("vector_count", 0) or 0),
        "document_count_diff": (info2.get("document_count", 0) or 0) - (info1.get("document_count", 0) or 0),
        "index_size_diff_mb": round(
            (info2.get("index_size_mb", 0) or 0) - (info1.get("index_size_mb", 0) or 0), 2
        ),
        "snapshot_1_info": info1,
        "snapshot_2_info": info2,
    }
