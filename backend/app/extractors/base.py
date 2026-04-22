"""
Base extractor class for document processing
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pathlib import Path


class BaseExtractor(ABC):
    """Abstract base class for document extractors"""

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """List of supported file extensions (e.g., ['.pdf', '.docx'])"""
        pass

    @abstractmethod
    async def extract(self, file_path: str) -> Dict[str, Any]:
        """
        Extract text content from a file

        Args:
            file_path: Path to the file

        Returns:
            Dictionary containing:
                - success: bool
                - content: str (extracted text)
                - metadata: dict (file metadata)
                - error: str (if failed)
        """
        pass

    def can_handle(self, file_path: str) -> bool:
        """Check if this extractor can handle the given file"""
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions


class ExtractionResult:
    """Container for extraction results"""

    def __init__(
        self,
        success: bool,
        content: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        method: str = "unknown"
    ):
        self.success = success
        self.content = content
        self.metadata = metadata or {}
        self.error = error
        self.method = method

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "content": self.content,
            "metadata": self.metadata,
            "error": self.error,
            "method": self.method
        }
