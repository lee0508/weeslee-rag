# HWP(구형 바이너리) 파일에서 텍스트를 추출하는 extractor (품질 점검 + PDF 변환 fallback)
"""
HWP 파일 텍스트 추출기.

처리 순서 (OCR 개선방안 기준):
  1. hwp5txt로 직접 추출 시도
  2. 품질 점검 (korean_ratio, garbage_ratio, text_length)
  3. 품질 낮으면 → PDF 변환 후 재추출
  4. 그래도 품질 낮으면 → OCR 실행

사용 방법:
  - use_pdf_fallback=True: PDF 변환 fallback 활성화
  - use_ocr_fallback=True: OCR fallback 활성화
"""
import os
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.extractors.base import BaseExtractor, ExtractionResult

# 품질 점검 모듈 (선택적 import)
try:
    from app.services.text_quality_checker import text_quality_checker, QualityCheckResult
    HAS_QUALITY_CHECKER = True
except ImportError:
    HAS_QUALITY_CHECKER = False
    text_quality_checker = None


def _hwp5txt_path() -> str:
    """venv bin 디렉토리에서 hwp5txt 경로를 반환한다."""
    bin_dir = Path(sys.executable).parent
    candidate = bin_dir / "hwp5txt"
    if candidate.exists():
        return str(candidate)
    # Windows용
    candidate_exe = bin_dir / "hwp5txt.exe"
    if candidate_exe.exists():
        return str(candidate_exe)
    return "hwp5txt"


def _libreoffice_path() -> str:
    """LibreOffice soffice 경로를 반환한다."""
    # Windows
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # Linux/Mac
    return "soffice"


class HwpExtractor(BaseExtractor):
    """
    HWP 바이너리 형식(.hwp) 텍스트 추출기.

    품질 점검 및 PDF 변환 fallback 지원.
    """

    def __init__(
        self,
        use_pdf_fallback: bool = True,
        use_ocr_fallback: bool = True,
        quality_threshold: float = 0.6,
    ):
        """
        초기화.

        Args:
            use_pdf_fallback: 품질 낮을 때 PDF 변환 시도
            use_ocr_fallback: PDF에서도 품질 낮을 때 OCR 시도
            quality_threshold: 품질 점수 임계값 (이하일 때 fallback)
        """
        self.use_pdf_fallback = use_pdf_fallback
        self.use_ocr_fallback = use_ocr_fallback
        self.quality_threshold = quality_threshold

    @property
    def supported_extensions(self) -> List[str]:
        return [".hwp"]

    async def extract(self, file_path: str) -> Dict[str, Any]:
        """
        HWP 파일에서 텍스트 추출.

        처리 순서:
          1. hwp5txt 직접 추출
          2. 품질 점검
          3. 필요 시 PDF 변환 fallback
          4. 필요 시 OCR fallback
        """
        if not os.path.exists(file_path):
            return ExtractionResult(
                success=False,
                error=f"File not found: {file_path}"
            ).to_dict()

        metadata = {
            "source": file_path,
            "filename": Path(file_path).name,
            "extraction_attempts": [],
        }

        # 1단계: hwp5txt 직접 추출 시도
        direct_result = self._extract_with_hwp5txt(file_path)
        metadata["extraction_attempts"].append({
            "method": "hwp5txt",
            "success": direct_result.success,
            "text_length": len(direct_result.content) if direct_result.content else 0,
        })

        if direct_result.success and direct_result.content:
            # 품질 점검
            quality = self._check_quality(direct_result.content)
            metadata["quality"] = quality

            if quality.get("quality_score", 0) >= self.quality_threshold:
                # 품질 양호 → 직접 추출 결과 사용
                direct_result.metadata.update(metadata)
                direct_result.metadata["final_method"] = "hwp5txt_direct"
                return direct_result.to_dict()

            # 품질 낮음 → fallback 필요
            metadata["quality_decision"] = quality.get("decision", "unknown")

        # 2단계: PDF 변환 fallback
        if self.use_pdf_fallback:
            pdf_result = await self._extract_with_pdf_conversion(file_path)
            metadata["extraction_attempts"].append({
                "method": "pdf_conversion",
                "success": pdf_result.success if pdf_result else False,
                "text_length": len(pdf_result.content) if pdf_result and pdf_result.content else 0,
            })

            if pdf_result and pdf_result.success and pdf_result.content:
                # PDF 변환 결과 품질 점검
                pdf_quality = self._check_quality(pdf_result.content)
                metadata["pdf_quality"] = pdf_quality

                if pdf_quality.get("quality_score", 0) >= self.quality_threshold:
                    pdf_result.metadata.update(metadata)
                    pdf_result.metadata["final_method"] = "pdf_conversion"
                    pdf_result.metadata["pdf_converted"] = True
                    return pdf_result.to_dict()

        # 3단계: OCR fallback (PDF 변환 후 OCR)
        if self.use_ocr_fallback:
            ocr_result = await self._extract_with_ocr(file_path)
            metadata["extraction_attempts"].append({
                "method": "ocr",
                "success": ocr_result.success if ocr_result else False,
                "text_length": len(ocr_result.content) if ocr_result and ocr_result.content else 0,
            })

            if ocr_result and ocr_result.success and ocr_result.content:
                ocr_result.metadata.update(metadata)
                ocr_result.metadata["final_method"] = "ocr"
                ocr_result.metadata["ocr_required"] = True
                return ocr_result.to_dict()

        # 모든 방법 실패 → 가장 좋은 결과 반환
        if direct_result.success and direct_result.content:
            direct_result.metadata.update(metadata)
            direct_result.metadata["final_method"] = "hwp5txt_fallback"
            direct_result.metadata["quality_warning"] = "품질이 낮지만 대체 방법 없음"
            return direct_result.to_dict()

        # 완전 실패
        return ExtractionResult(
            success=False,
            error="모든 추출 방법 실패",
            metadata=metadata,
            method="hwp_all_failed"
        ).to_dict()

    def _extract_with_hwp5txt(self, file_path: str) -> ExtractionResult:
        """hwp5txt로 직접 추출."""
        try:
            result = subprocess.run(
                [_hwp5txt_path(), file_path],
                capture_output=True,
                timeout=60,
            )
            text = result.stdout.decode("utf-8", errors="replace").strip()

            if not text:
                stderr = result.stderr.decode("utf-8", errors="replace")
                return ExtractionResult(
                    success=False,
                    error=f"hwp5txt returned empty output. stderr: {stderr[:200]}",
                    method="hwp5txt"
                )

            return ExtractionResult(
                success=True,
                content=text,
                metadata={
                    "source": file_path,
                    "filename": Path(file_path).name,
                    "content_length": len(text),
                },
                method="hwp5txt"
            )

        except subprocess.TimeoutExpired:
            return ExtractionResult(
                success=False,
                error="hwp5txt timed out (>60s)",
                method="hwp5txt"
            )
        except FileNotFoundError:
            return ExtractionResult(
                success=False,
                error="hwp5txt not found. pyhwp 패키지가 설치되어 있는지 확인하세요.",
                method="hwp5txt"
            )
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=str(e),
                method="hwp5txt"
            )

    async def _extract_with_pdf_conversion(self, file_path: str) -> Optional[ExtractionResult]:
        """HWP → PDF 변환 후 텍스트 추출."""
        try:
            # 임시 디렉토리에 PDF 생성
            with tempfile.TemporaryDirectory() as tmpdir:
                # LibreOffice로 PDF 변환
                cmd = [
                    _libreoffice_path(),
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", tmpdir,
                    file_path
                ]

                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=120,
                )

                if process.returncode != 0:
                    return None

                # 변환된 PDF 찾기
                pdf_files = list(Path(tmpdir).glob("*.pdf"))
                if not pdf_files:
                    return None

                pdf_path = pdf_files[0]

                # PDF에서 텍스트 추출
                import pdfplumber
                content_parts = []

                with pdfplumber.open(str(pdf_path)) as pdf:
                    for i, page in enumerate(pdf.pages):
                        text = page.extract_text()
                        if text:
                            content_parts.append(f"--- Page {i + 1} ---\n{text}")

                content = "\n\n".join(content_parts)

                if not content.strip():
                    return None

                return ExtractionResult(
                    success=True,
                    content=content,
                    metadata={
                        "source": file_path,
                        "filename": Path(file_path).name,
                        "content_length": len(content),
                        "pages": len(content_parts),
                    },
                    method="hwp_pdf_conversion"
                )

        except Exception as e:
            print(f"[WARN] PDF conversion failed for {file_path}: {e}")
            return None

    async def _extract_with_ocr(self, file_path: str) -> Optional[ExtractionResult]:
        """HWP → PDF → OCR 추출."""
        try:
            # PDF 변환
            with tempfile.TemporaryDirectory() as tmpdir:
                cmd = [
                    _libreoffice_path(),
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", tmpdir,
                    file_path
                ]

                subprocess.run(cmd, capture_output=True, timeout=120)

                pdf_files = list(Path(tmpdir).glob("*.pdf"))
                if not pdf_files:
                    return None

                pdf_path = pdf_files[0]

                # Tesseract OCR
                try:
                    import pytesseract
                    from pdf2image import convert_from_path

                    images = convert_from_path(str(pdf_path), dpi=200)
                    parts = []

                    for i, img in enumerate(images, start=1):
                        text = pytesseract.image_to_string(img, lang="kor+eng")
                        if text.strip():
                            parts.append(f"--- Page {i} ---\n{text.strip()}")

                    if not parts:
                        return None

                    content = "\n\n".join(parts)

                    return ExtractionResult(
                        success=True,
                        content=content,
                        metadata={
                            "source": file_path,
                            "filename": Path(file_path).name,
                            "content_length": len(content),
                            "pages": len(parts),
                            "ocr_lang": "kor+eng",
                        },
                        method="hwp_ocr"
                    )

                except ImportError:
                    return None

        except Exception as e:
            print(f"[WARN] OCR extraction failed for {file_path}: {e}")
            return None

    def _check_quality(self, text: str) -> dict:
        """텍스트 품질 점검."""
        if not HAS_QUALITY_CHECKER or not text_quality_checker:
            # 품질 점검 모듈 없으면 기본 점검
            text_len = len(text)
            korean_count = sum(1 for c in text if '가' <= c <= '힣')
            korean_ratio = korean_count / len(text.replace(' ', '')) if text.replace(' ', '') else 0

            return {
                "text_length": text_len,
                "korean_ratio": round(korean_ratio, 4),
                "quality_score": 0.7 if text_len > 100 and korean_ratio > 0.2 else 0.4,
                "decision": "use_direct_text" if text_len > 100 else "need_fallback",
            }

        result = text_quality_checker.check(text)
        return result.to_dict()


# 싱글톤 인스턴스
hwp_extractor = HwpExtractor()
