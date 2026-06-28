"""
PDF Extractor with OCR support (pytesseract + easyocr fallback)
"""
import os
from typing import Dict, Any, List, Optional
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


def _is_easyocr_available() -> bool:
    """Return True if easyocr is installed."""
    try:
        import easyocr
        return True
    except ImportError:
        return False


# EasyOCR reader 캐싱 (초기화 비용 절감)
_easyocr_reader: Optional[Any] = None


def _get_easyocr_reader():
    """EasyOCR reader 싱글톤 반환."""
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        # GPU 사용 가능하면 GPU, 아니면 CPU
        try:
            import torch
            use_gpu = torch.cuda.is_available()
        except ImportError:
            use_gpu = False
        _easyocr_reader = easyocr.Reader(['ko', 'en'], gpu=use_gpu, verbose=False)
    return _easyocr_reader


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

    def _has_cid_encoding_issue(self, text: str) -> bool:
        """CID 폰트 인코딩 문제가 있는지 확인 (유니코드 매핑 없는 임베디드 폰트)"""
        import re
        if not text:
            return False
        cid_pattern = r'\(cid:\d+\)'
        cid_matches = re.findall(cid_pattern, text)
        # 텍스트 1000자당 10개 이상의 CID 패턴이 있으면 문제로 판단
        text_length = len(text)
        if text_length == 0:
            return False
        cid_ratio = len(cid_matches) / (text_length / 1000.0)
        return cid_ratio > 10

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

            full_content = "\n\n".join(content_parts)

            # CID 인코딩 문제 감지
            import re
            cid_pattern = r'\(cid:\d+\)'
            cid_matches = re.findall(cid_pattern, full_content)
            cid_count = len(cid_matches)
            cid_detected = self._has_cid_encoding_issue(full_content)

            if cid_detected:
                # CID 정보를 메타데이터에 기록하고 실패 반환
                return ExtractionResult(
                    success=False,
                    error="CID font encoding detected (no Unicode mapping)",
                    method="pdfplumber_cid_detected",
                    metadata={
                        **metadata,
                        "cid_detected": True,
                        "cid_count": cid_count,
                        "cid_ratio": cid_count / len(full_content) if len(full_content) > 0 else 0,
                    }
                )

            return ExtractionResult(
                success=True,
                content=full_content,
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

    def _extract_with_easyocr(self, pdf_path: str) -> ExtractionResult:
        """Convert pages to images and run EasyOCR (Korean + English)."""
        try:
            import numpy as np
            from pdf2image import convert_from_path

            reader = _get_easyocr_reader()
            images = convert_from_path(pdf_path, dpi=200)
            parts = []

            for i, img in enumerate(images, start=1):
                img_np = np.array(img)
                results = reader.readtext(img_np)
                # 결과에서 텍스트만 추출하고 줄바꿈으로 연결
                page_text = "\n".join([r[1] for r in results])
                if page_text.strip():
                    parts.append(f"--- Page {i} ---\n{page_text.strip()}")

            if not parts:
                return ExtractionResult(
                    success=False,
                    error="EasyOCR produced no text",
                    method="easyocr",
                )
            return ExtractionResult(
                success=True,
                content="\n\n".join(parts),
                metadata={
                    "source": pdf_path,
                    "filename": Path(pdf_path).name,
                    "pages": len(images),
                    "ocr_engine": "easyocr",
                    "ocr_lang": "ko+en",
                },
                method="easyocr",
            )
        except Exception as e:
            return ExtractionResult(success=False, error=str(e), method="easyocr")

    async def extract(self, file_path: str) -> Dict[str, Any]:
        import time
        start_time = time.time()

        if not os.path.exists(file_path):
            return ExtractionResult(
                success=False, error=f"File not found: {file_path}"
            ).to_dict()

        is_scanned = self._is_scanned_pdf(file_path)

        # 1단계: pdfplumber로 텍스트 추출 시도 (텍스트 기반 PDF)
        if not is_scanned:
            result = self._extract_with_pdfplumber(file_path)
            if result.success and result.content.strip():
                result.metadata["is_scanned"] = False
                result.metadata["processing_time_sec"] = round(time.time() - start_time, 2)
                return result.to_dict()

        # OCR 비활성화된 경우
        if not self.use_ocr:
            return ExtractionResult(
                success=False,
                error="PDF is scanned but OCR is disabled",
                method="scanned_ocr_disabled",
                metadata={"is_scanned": True},
            ).to_dict()

        # 2단계: EasyOCR 우선 시도 (품질 최우선)
        if _is_easyocr_available():
            ocr_start = time.time()
            result = self._extract_with_easyocr(file_path)
            easyocr_time = round(time.time() - ocr_start, 2)
            if result.success and result.content.strip():
                result.metadata["is_scanned"] = True
                result.metadata["ocr_time_sec"] = easyocr_time
                result.metadata["processing_time_sec"] = round(time.time() - start_time, 2)
                result.metadata["initial_method"] = "pdfplumber"
                result.metadata["selected_method"] = "easyocr"
                result.metadata["fallback_reason"] = "scanned_pdf or cid_detected"
                return result.to_dict()
            easyocr_error = result.error
        else:
            easyocr_error = "easyocr not available"

        # 3단계: tesseract fallback (EasyOCR 실패 시)
        if _is_tesseract_available():
            ocr_start = time.time()
            result = self._extract_with_tesseract(file_path)
            tesseract_time = round(time.time() - ocr_start, 2)
            if result.success and result.content.strip():
                result.metadata["is_scanned"] = True
                result.metadata["ocr_time_sec"] = tesseract_time
                result.metadata["initial_method"] = "pdfplumber"
                result.metadata["selected_method"] = "tesseract"
                result.metadata["fallback_reason"] = f"easyocr failed: {easyocr_error}"
                result.metadata["processing_time_sec"] = round(time.time() - start_time, 2)
                return result.to_dict()
            tesseract_error = result.error
        else:
            tesseract_error = "tesseract not available"

        # 모든 OCR 실패
        return ExtractionResult(
            success=False,
            error=f"All OCR methods failed. easyocr: {easyocr_error}, tesseract: {tesseract_error}",
            method="ocr_all_failed",
            metadata={"is_scanned": True, "processing_time_sec": round(time.time() - start_time, 2)},
        ).to_dict()


pdf_extractor = PDFExtractor()
