# 통합 문서 추출기 - 모든 지원 형식 및 OCR 지원
# 작업일: 2026-07-08 - DB 시스템 설정 연동 추가
"""
Unified Document Extractor
Handles all supported document formats with OCR support
"""
import os
from typing import Dict, Any, List, Optional
from pathlib import Path

from app.extractors.base import BaseExtractor, ExtractionResult


def _get_db_ocr_setting(key: str, default):
    """DB에서 OCR 설정 조회. 실패 시 default 반환."""
    try:
        from app.services.system_settings_service import get_system_setting
        return get_system_setting("ocr", key, default)
    except Exception:
        return default
from app.extractors.pdf_extractor import PDFExtractor
from app.extractors.docx_extractor import DocxExtractor
from app.extractors.pptx_extractor import PptxExtractor
from app.extractors.xlsx_extractor import XlsxExtractor
from app.extractors.hwpx_extractor import HwpxExtractor
from app.extractors.hwp_extractor import HwpExtractor


class DocumentExtractor:
    """
    Unified document extractor that routes to appropriate extractors
    based on file type
    """

    def __init__(
        self,
        use_ocr: bool = True,
        ocr_use_gpu: Optional[bool] = None,
        ocr_dpi: int = None,
        ocr_language: str = None,
        ocr_min_text_length: int = 50,
        ocr_engine: str = None,
    ):
        """
        Initialize document extractor

        Args:
            use_ocr: Whether to enable OCR for scanned documents
        """
        self.use_ocr = use_ocr
        self.ocr_use_gpu = ocr_use_gpu
        self.extractors: List[BaseExtractor] = [
            PDFExtractor(
                use_ocr=use_ocr,
                ocr_use_gpu=ocr_use_gpu,
                ocr_dpi=ocr_dpi,
                ocr_language=ocr_language,
                ocr_threshold=ocr_min_text_length,
                ocr_engine=ocr_engine,
            ),
            DocxExtractor(),
            PptxExtractor(
                ocr_engine=ocr_engine,
                ocr_use_gpu=ocr_use_gpu,
                ocr_dpi=ocr_dpi,
                ocr_language=ocr_language,
            ),
            XlsxExtractor(),
            HwpxExtractor(),
            HwpExtractor(
                ocr_engine=ocr_engine,
                ocr_use_gpu=ocr_use_gpu,
                ocr_dpi=ocr_dpi,
                ocr_language=ocr_language,
            ),
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
