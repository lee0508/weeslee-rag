# ProcessedTextStore 확장 메서드
"""
청크와 임베딩 저장/로드 기능 추가
"""
import json
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


def _extract_id_contract_from_chunks(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    keys = ["source_id", "dataset_id", "document_uid", "relative_path", "snapshot_id"]
    contract: Dict[str, Any] = {key: "" for key in keys}

    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        for key in keys:
            if contract[key]:
                continue
            value = chunk.get(key)
            if value is None or str(value).strip() == "":
                value = meta.get(key)
            if value is not None and str(value).strip():
                contract[key] = value

    return contract


def _group_chunks_by_page(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    page_map: Dict[str, Dict[str, Any]] = {}

    for chunk in chunks:
        page_no = chunk.get("page_number")
        if page_no is None:
            page_key = "unpaged"
            page_label = None
        else:
            page_key = str(page_no)
            page_label = page_no

        if page_key not in page_map:
            page_map[page_key] = {
                "page_number": page_label,
                "chunks_count": 0,
                "char_count": 0,
                "chunks": [],
            }

        page_entry = page_map[page_key]
        page_entry["chunks"].append(chunk)
        page_entry["chunks_count"] += 1
        page_entry["char_count"] += len(str(chunk.get("content") or ""))

    def _sort_key(item: Dict[str, Any]) -> tuple[int, int]:
        page_no = item.get("page_number")
        if page_no is None:
            return (1, 999999)
        try:
            return (0, int(page_no))
        except Exception:
            return (0, 999998)

    return sorted(page_map.values(), key=_sort_key)


def save_chunks(self, document_id: int, chunks: List[Dict[str, Any]]) -> bool:
    """
    문서의 청크 저장

    Args:
        document_id: 문서 ID
        chunks: 청크 목록 (dict 형태)

    Returns:
        저장 성공 여부
    """
    try:
        doc_dir = self._doc_dir(str(document_id))
        chunks_file = doc_dir / "chunks.json"
        chunk_file_path = doc_dir / "chunk_file.json"
        chunk_pages_path = doc_dir / "chunk_pages.json"
        page_groups = _group_chunks_by_page(chunks)
        id_contract = _extract_id_contract_from_chunks(chunks)
        payload = {
            "document_id": document_id,
            **id_contract,
            "chunks_count": len(chunks),
            "pages_count": len(page_groups),
            "chunks": chunks,
            "created_at": datetime.now().isoformat()
        }

        with open(chunks_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        with open(chunk_file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        with open(chunk_pages_path, "w", encoding="utf-8") as f:
            json.dump({
                "document_id": document_id,
                **id_contract,
                "pages_count": len(page_groups),
                "pages": page_groups,
                "created_at": payload["created_at"],
            }, f, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        print(f"Error saving chunks for document {document_id}: {e}")
        return False


def load_chunks(self, document_id: int) -> List[Dict[str, Any]]:
    """
    문서의 청크 로드

    Args:
        document_id: 문서 ID

    Returns:
        청크 목록
    """
    try:
        doc_dir = self._doc_dir(str(document_id))
        chunks_file = doc_dir / "chunks.json"

        if not chunks_file.exists():
            return []

        with open(chunks_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("chunks", [])
    except Exception as e:
        print(f"Error loading chunks for document {document_id}: {e}")
        return []


def load_chunk_file(self, document_id: int) -> Optional[Dict[str, Any]]:
    """문서 단위 청크 JSON 로드."""
    try:
        doc_dir = self._doc_dir(str(document_id))
        chunk_file = doc_dir / "chunk_file.json"
        if not chunk_file.exists():
            return None
        with open(chunk_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading chunk file for document {document_id}: {e}")
        return None


def load_chunk_pages(self, document_id: int) -> List[Dict[str, Any]]:
    """페이지 단위 청크 JSON 로드."""
    try:
        doc_dir = self._doc_dir(str(document_id))
        chunk_pages_file = doc_dir / "chunk_pages.json"
        if not chunk_pages_file.exists():
            return []
        with open(chunk_pages_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("pages", [])
    except Exception as e:
        print(f"Error loading chunk pages for document {document_id}: {e}")
        return []


def save_embeddings(
    self,
    document_id: int,
    embeddings: List[List[float]],
    model: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    문서의 임베딩 저장 (pickle 형식)

    Args:
        document_id: 문서 ID
        embeddings: 임베딩 벡터 목록
        model: 사용한 임베딩 모델명

    Returns:
        저장 성공 여부
    """
    try:
        doc_dir = self._doc_dir(str(document_id))
        embeddings_file = doc_dir / "embeddings.pkl"
        metadata_file = doc_dir / "embeddings_metadata.json"

        # 임베딩 저장 (pickle)
        with open(embeddings_file, "wb") as f:
            pickle.dump(embeddings, f)

        # 메타데이터 저장
        metadata = {
            "document_id": document_id,
            "embeddings_count": len(embeddings),
            "embedding_dim": len(embeddings[0]) if embeddings and len(embeddings[0]) > 0 else 0,
            "model": model,
            "source_id": str((metadata or {}).get("source_id") or ""),
            "dataset_id": str((metadata or {}).get("dataset_id") or ""),
            "document_uid": str((metadata or {}).get("document_uid") or ""),
            "relative_path": str((metadata or {}).get("relative_path") or ""),
            "snapshot_id": str((metadata or {}).get("snapshot_id") or ""),
            "created_at": datetime.now().isoformat()
        }

        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        print(f"Error saving embeddings for document {document_id}: {e}")
        return False


def load_embeddings(self, document_id: int) -> List[List[float]]:
    """
    문서의 임베딩 로드

    Args:
        document_id: 문서 ID

    Returns:
        임베딩 벡터 목록
    """
    try:
        doc_dir = self._doc_dir(str(document_id))
        embeddings_file = doc_dir / "embeddings.pkl"

        if not embeddings_file.exists():
            return []

        with open(embeddings_file, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        print(f"Error loading embeddings for document {document_id}: {e}")
        return []


def load_embedding_metadata(self, document_id: int) -> Optional[Dict[str, Any]]:
    """
    임베딩 메타데이터 로드

    Args:
        document_id: 문서 ID

    Returns:
        메타데이터 딕셔너리
    """
    try:
        doc_dir = self._doc_dir(str(document_id))
        metadata_file = doc_dir / "embeddings_metadata.json"

        if not metadata_file.exists():
            return None

        with open(metadata_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading embedding metadata for document {document_id}: {e}")
        return None


def chunks_exist(self, document_id: int) -> bool:
    """청크 존재 여부 확인"""
    doc_dir = self._doc_dir(str(document_id))
    return (doc_dir / "chunks.json").exists()


def embeddings_exist(self, document_id: int) -> bool:
    """임베딩 존재 여부 확인"""
    doc_dir = self._doc_dir(str(document_id))
    return (doc_dir / "embeddings.pkl").exists()


# ProcessedTextStore 클래스에 메서드 추가
def add_extensions_to_store(store_class):
    """ProcessedTextStore 클래스에 확장 메서드 추가"""
    store_class.save_chunks = save_chunks
    store_class.load_chunks = load_chunks
    store_class.load_chunk_file = load_chunk_file
    store_class.load_chunk_pages = load_chunk_pages
    store_class.save_embeddings = save_embeddings
    store_class.load_embeddings = load_embeddings
    store_class.load_embedding_metadata = load_embedding_metadata
    store_class.chunks_exist = chunks_exist
    store_class.embeddings_exist = embeddings_exist
    return store_class


# 모듈 로드 시 자동으로 확장 메서드 추가
try:
    from app.services.processed_text_store import ProcessedTextStore
    add_extensions_to_store(ProcessedTextStore)
except ImportError:
    pass
