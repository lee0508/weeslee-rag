"""
PDF Extractor with OCR support
"""
import os
from typing import Dict, Any, List
from pathlib import Path
import pdfplumber

from app.extractors.base import BaseExtractor, ExtractionResult
from app.services.ocr import ocr_service


class PDFExtractor(BaseExtractor):
    """Extracts text from PDF files with OCR fallback"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

    def __init__(self, use_ocr: bool = True, ocr_threshold: int = 50):
        """
        Initialize PDF extractor

        Args:
            use_ocr: Whether to use OCR for scanned PDFs
            ocr_threshold: Minimum characters per page to consider it text-based
        """
        self.use_ocr = use_ocr
        self.ocr_threshold = ocr_threshold

    def _is_scanned_pdf(self, pdf_path: str) -> bool:
        """Check if PDF is scanned (image-based)"""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages[:3]:  # Check first 3 pages
                    text = page.extract_text()
                    if text and len(text.strip()) > self.ocr_threshold:
                        return False
                return True
        except Exception:
            return True

    def _extract_with_pdfplumber(self, pdf_path: str) -> ExtractionResult:
        """Extract text using pdfplumber"""
        try:
            content_parts = []
            metadata = {
                "pages": 0,
                "source": pdf_path,
                "filename": Path(pdf_path).name
            }

            with pdfplumber.open(pdf_path) as pdf:
                metadata["pages"] = len(pdf.pages)

                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        content_parts.append(f"--- Page {i + 1} ---\n{text}")

            content = "\n\n".join(content_parts)

            return ExtractionResult(
                success=True,
                content=content,
                metadata=metadata,
                method="pdfplumber"
            )

        except Exception as e:
            return ExtractionResult(
                success=False,
                error=str(e),
                method="pdfplumber"
            )

    async def _extract_with_ocr(self, pdf_path: str) -> ExtractionResult:
        """Extract text using olmOCR"""
        try:
            result = await ocr_service.process_pdf(pdf_path, output_format="markdown")

            if result["success"]:
                return ExtractionResult(
                    success=True,
                    content=result["content"],
                    metadata={
                        "source": pdf_path,
                        "filename": Path(pdf_path).name,
                        "ocr_output": result.get("output_file")
                    },
                    method="olmocr"
                )
            else:
                return ExtractionResult(
                    success=False,
                    error=result.get("error", "OCR processing failed"),
                    method="olmocr"
                )

        except Exception as e:
            return ExtractionResult(
                success=False,
                error=str(e),
                method="olmocr"
            )

    async def extract(self, file_path: str) -> Dict[str, Any]:
        """
        Extract text from PDF, using OCR if needed

        Args:
            file_path: Path to PDF file

        Returns:
            Extraction result dictionary
        """
        if not os.path.exists(file_path):
            return ExtractionResult(
                success=False,
                error=f"File not found: {file_path}"
            ).to_dict()

        # First try regular extraction
        if not self._is_scanned_pdf(file_path):
            result = self._extract_with_pdfplumber(file_path)
            if result.success and result.content.strip():
                return result.to_dict()

        # Fall back to OCR if enabled
        if self.use_ocr:
            result = await self._extract_with_ocr(file_path)
            return result.to_dict()

        return ExtractionResult(
            success=False,
            error="PDF appears to be scanned but OCR is disabled"
        ).to_dict()


# Singleton instance
pdf_extractor = PDFExtractor()
