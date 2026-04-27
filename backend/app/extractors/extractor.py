"""
Unified Document Extractor
Handles all supported document formats with OCR support
"""
import os
from typing import Dict, Any, List, Optional
from pathlib import Path

from app.extractors.base import BaseExtractor, ExtractionResult
from app.extractors.pdf_extractor import PDFExtractor
from app.extractors.docx_extractor import DocxExtractor
from app.extractors.pptx_extractor import PptxExtractor
from app.extractors.xlsx_extractor import XlsxExtractor
from app.extractors.hwpx_extractor import HwpxExtractor


class DocumentExtractor:
    """
    Unified document extractor that routes to appropriate extractors
    based on file type
    """

    def __init__(self, use_ocr: bool = True):
        """
        Initialize document extractor

        Args:
            use_ocr: Whether to enable OCR for scanned documents
        """
        self.use_ocr = use_ocr
        self.extractors: List[BaseExtractor] = [
            PDFExtractor(use_ocr=use_ocr),
            DocxExtractor(),
            PptxExtractor(),
            XlsxExtractor(),
            HwpxExtractor(),
        ]

    @property
    def supported_extensions(self) -> List[str]:
        """Get all supported file extensions"""
        extensions = []
        for extractor in self.extractors:
            extensions.extend(extractor.supported_extensions)
        return extensions

    def can_handle(self, file_path: str) -> bool:
        """Check if any extractor can handle this file"""
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions

    def get_extractor(self, file_path: str) -> Optional[BaseExtractor]:
        """Get the appropriate extractor for a file"""
        for extractor in self.extractors:
            if extractor.can_handle(file_path):
                return extractor
        return None

    async def extract(self, file_path: str) -> Dict[str, Any]:
        """
        Extract text from a document

        Args:
            file_path: Path to the document

        Returns:
            Extraction result dictionary
        """
        if not os.path.exists(file_path):
            return ExtractionResult(
                success=False,
                error=f"File not found: {file_path}"
            ).to_dict()

        extractor = self.get_extractor(file_path)

        if not extractor:
            ext = Path(file_path).suffix.lower()
            return ExtractionResult(
                success=False,
                error=f"Unsupported file format: {ext}"
            ).to_dict()

        return await extractor.extract(file_path)

    async def extract_batch(
        self,
        file_paths: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Extract text from multiple documents

        Args:
            file_paths: List of file paths

        Returns:
            List of extraction results
        """
        results = []
        for file_path in file_paths:
            result = await self.extract(file_path)
            result["source_file"] = file_path
            results.append(result)
        return results


# Singleton instance
document_extractor = DocumentExtractor()
