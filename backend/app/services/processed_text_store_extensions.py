# ProcessedTextStore 확장 메서드
"""
청크와 임베딩 저장/로드 기능 추가
"""
import json
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


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

        with open(chunks_file, "w", encoding="utf-8") as f:
            json.dump({
                "document_id": document_id,
                "chunks_count": len(chunks),
                "chunks": chunks,
                "created_at": datetime.now().isoformat()
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


def save_embeddings(
    self,
    document_id: int,
    embeddings: List[List[float]],
    model: Optional[str] = None
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
