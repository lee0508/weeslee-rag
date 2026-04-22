"""
ChromaDB Vector Database Service
"""
import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import Optional, List, Dict, Any
import os

from app.core.config import settings


class VectorDBService:
    """Service for interacting with ChromaDB"""

    def __init__(self):
        self._client: Optional[chromadb.Client] = None

    @property
    def client(self) -> chromadb.Client:
        """Get or create ChromaDB client"""
        if self._client is None:
            # Ensure persist directory exists
            persist_dir = settings.chroma_persist_dir
            os.makedirs(persist_dir, exist_ok=True)

            # Create persistent client
            self._client = chromadb.PersistentClient(
                path=persist_dir,
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
        return self._client

    def get_or_create_collection(self, name: str, metadata: Optional[Dict] = None) -> chromadb.Collection:
        """Get or create a collection"""
        return self.client.get_or_create_collection(
            name=name,
            metadata=metadata or {"description": f"Collection: {name}"}
        )

    def list_collections(self) -> List[str]:
        """List all collection names"""
        collections = self.client.list_collections()
        return [col.name for col in collections]

    def get_collection(self, name: str) -> Optional[chromadb.Collection]:
        """Get a collection by name"""
        try:
            return self.client.get_collection(name=name)
        except Exception:
            return None

    def delete_collection(self, name: str) -> bool:
        """Delete a collection"""
        try:
            self.client.delete_collection(name=name)
            return True
        except Exception:
            return False

    def add_documents(
        self,
        collection_name: str,
        documents: List[str],
        embeddings: List[List[float]],
        metadatas: Optional[List[Dict]] = None,
        ids: Optional[List[str]] = None
    ) -> List[str]:
        """Add documents with embeddings to a collection"""
        collection = self.get_or_create_collection(collection_name)

        # Generate IDs if not provided
        if ids is None:
            import uuid
            ids = [str(uuid.uuid4()) for _ in documents]

        collection.add(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas or [{}] * len(documents),
            ids=ids
        )

        return ids

    def search(
        self,
        collection_name: str,
        query_embedding: List[float],
        n_results: int = 10,
        where: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Search for similar documents"""
        collection = self.get_collection(collection_name)
        if collection is None:
            return {"ids": [], "documents": [], "metadatas": [], "distances": []}

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where
        )

        return {
            "ids": results["ids"][0] if results["ids"] else [],
            "documents": results["documents"][0] if results["documents"] else [],
            "metadatas": results["metadatas"][0] if results["metadatas"] else [],
            "distances": results["distances"][0] if results["distances"] else []
        }

    def get_collection_stats(self, name: str) -> Dict[str, Any]:
        """Get collection statistics"""
        collection = self.get_collection(name)
        if collection is None:
            return {"count": 0, "exists": False}

        return {
            "count": collection.count(),
            "exists": True,
            "metadata": collection.metadata
        }

    def delete_by_ids(self, collection_name: str, ids: List[str]) -> bool:
        """Delete documents by IDs"""
        collection = self.get_collection(collection_name)
        if collection is None:
            return False

        try:
            collection.delete(ids=ids)
            return True
        except Exception:
            return False


# Singleton instance
vectordb_service = VectorDBService()


def get_vectordb() -> VectorDBService:
    """Dependency to get VectorDB service"""
    return vectordb_service
