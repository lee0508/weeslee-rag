"""
PDF Extractor with OCR support (pytesseract + pdf2image backend)
"""
import os
from typing import Dict, Any, List
from pathlib import Path
import pdfplumber

from app.extractors.base import BaseExtractor, ExtractionResult


def _is_tesseract_available() -> bool:
    """Return True if pytesseract and tesseract-ocr are both installed."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


class PDFExtractor(BaseExtractor):
    """Extracts text from PDF files with pytesseract OCR fallback for scanned pages"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

    def __init__(self, use_ocr: bool = True, ocr_threshold: int = 50):
        self.use_ocr = use_ocr
        self.ocr_threshold = ocr_threshold

    def _is_scanned_pdf(self, pdf_path: str) -> bool:
        """Return True if first 3 pages yield less than ocr_threshold chars each."""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages[:3]:
                    text = page.extract_text()
                    if text and len(text.strip()) > self.ocr_threshold:
                        return False
                return True
        except Exception:
            return True

    def _extract_with_pdfplumber(self, pdf_path: str) -> ExtractionResult:
        try:
            content_parts = []
            metadata: Dict[str, Any] = {
                "pages": 0,
                "source": pdf_path,
                "filename": Path(pdf_path).name,
            }
            with pdfplumber.open(pdf_path) as pdf:
                metadata["pages"] = len(pdf.pages)
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        content_parts.append(f"--- Page {i + 1} ---\n{text}")
            return ExtractionResult(
                success=True,
                content="\n\n".join(content_parts),
                metadata=metadata,
                method="pdfplumber",
            )
        except Exception as e:
            return ExtractionResult(success=False, error=str(e), method="pdfplumber")

    def _extract_with_tesseract(self, pdf_path: str) -> ExtractionResult:
        """Convert pages to images and run tesseract OCR (kor+eng)."""
        try:
            import pytesseract
            from pdf2image import convert_from_path

            images = convert_from_path(pdf_path, dpi=200)
            parts = []
            for i, img in enumerate(images, start=1):
                text = pytesseract.image_to_string(img, lang="kor+eng")
                if text.strip():
                    parts.append(f"--- Page {i} ---\n{text.strip()}")

            if not parts:
                return ExtractionResult(
                    success=False,
                    error="Tesseract produced no text",
                    method="tesseract",
                )
            return ExtractionResult(
                success=True,
                content="\n\n".join(parts),
                metadata={
                    "source": pdf_path,
                    "filename": Path(pdf_path).name,
                    "pages": len(images),
                    "ocr_lang": "kor+eng",
                },
                method="tesseract",
            )
        except Exception as e:
            return ExtractionResult(success=False, error=str(e), method="tesseract")

    async def extract(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            return ExtractionResult(
                success=False, error=f"File not found: {file_path}"
            ).to_dict()

        is_scanned = self._is_scanned_pdf(file_path)

        if not is_scanned:
            result = self._extract_with_pdfplumber(file_path)
            if result.success and result.content.strip():
                result.metadata["is_scanned"] = False
                return result.to_dict()

        if self.use_ocr:
            result = self._extract_with_tesseract(file_path)
            result.metadata["is_scanned"] = True
            return result.to_dict()

        return ExtractionResult(
            success=False,
            error="PDF is scanned but OCR is disabled (install tesseract-ocr and pass --use-ocr)",
            method="scanned_ocr_disabled",
            metadata={"is_scanned": True},
        ).to_dict()


pdf_extractor = PDFExtractor()
