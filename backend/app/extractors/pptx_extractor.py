# PPTX 파일에서 텍스트를 추출하는 extractor (품질 점검 + OCR 보완)
"""
PPTX 파일 텍스트 추출기.

처리 순서 (OCR 개선방안 기준):
  1. python-pptx로 직접 추출 시도
  2. 품질 점검 (korean_ratio, text_length)
  3. 품질 낮으면 → PDF 변환 후 OCR 보완

사용 방법:
  - use_ocr_supplement=True: 품질 낮을 때 OCR 보완 활성화
"""
import os
import subprocess
import tempfile
from typing import Dict, Any, List, Optional
from pathlib import Path
from pptx import Presentation

from app.extractors.base import BaseExtractor, ExtractionResult

# 품질 점검 모듈 (선택적 import)
try:
    from app.services.text_quality_checker import text_quality_checker
    HAS_QUALITY_CHECKER = True
except ImportError:
    HAS_QUALITY_CHECKER = False
    text_quality_checker = None


def _libreoffice_path() -> str:
    """LibreOffice soffice 경로를 반환한다."""
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "soffice"


class PptxExtractor(BaseExtractor):
    """
    PPTX 파일 텍스트 추출기.

    품질 점검 및 OCR 보완 지원.
    """

    def __init__(
        self,
        use_ocr_supplement: bool = True,
        quality_threshold: float = 0.5,
    ):
        """
        초기화.

        Args:
            use_ocr_supplement: 품질 낮을 때 OCR 보완 시도
            quality_threshold: 품질 점수 임계값 (이하일 때 OCR 보완)
        """
        self.use_ocr_supplement = use_ocr_supplement
        self.quality_threshold = quality_threshold

    @property
    def supported_extensions(self) -> List[str]:
        return [".pptx"]

    async def extract(self, file_path: str) -> Dict[str, Any]:
        """
        PPTX 파일에서 텍스트 추출.

        처리 순서:
          1. python-pptx 직접 추출
          2. 품질 점검
          3. 필요 시 OCR 보완
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

        # 1단계: python-pptx 직접 추출
        direct_result = self._extract_with_pptx(file_path)
        metadata["extraction_attempts"].append({
            "method": "python-pptx",
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
                direct_result.metadata["final_method"] = "python-pptx_direct"
                return direct_result.to_dict()

            # 품질 낮음 → OCR 보완 필요
            metadata["quality_decision"] = quality.get("decision", "unknown")

        # 2단계: OCR 보완 (직접 추출 + OCR 결과 병합)
        if self.use_ocr_supplement:
            ocr_result = await self._extract_with_ocr(file_path)
            metadata["extraction_attempts"].append({
                "method": "ocr_supplement",
                "success": ocr_result.success if ocr_result else False,
                "text_length": len(ocr_result.content) if ocr_result and ocr_result.content else 0,
            })

            if ocr_result and ocr_result.success and ocr_result.content:
                # OCR 결과와 직접 추출 결과 병합
                if direct_result.success and direct_result.content:
                    merged_content = self._merge_content(
                        direct_result.content,
                        ocr_result.content
                    )
                    merged_quality = self._check_quality(merged_content)
                    metadata["merged_quality"] = merged_quality

                    if merged_quality.get("quality_score", 0) > quality.get("quality_score", 0):
                        # 병합 결과가 더 좋으면 병합 결과 사용
                        return ExtractionResult(
                            success=True,
                            content=merged_content,
                            metadata={
                                **metadata,
                                "final_method": "pptx_merged",
                                "ocr_supplemented": True,
                            },
                            method="pptx_merged"
                        ).to_dict()
                else:
                    # 직접 추출 실패, OCR만 사용
                    ocr_result.metadata.update(metadata)
                    ocr_result.metadata["final_method"] = "ocr_only"
                    ocr_result.metadata["ocr_required"] = True
                    return ocr_result.to_dict()

        # 직접 추출 결과 반환 (품질이 낮더라도)
        if direct_result.success and direct_result.content:
            direct_result.metadata.update(metadata)
            direct_result.metadata["final_method"] = "python-pptx_fallback"
            direct_result.metadata["quality_warning"] = "품질이 낮지만 대체 방법 없음"
            return direct_result.to_dict()

        # 완전 실패
        return ExtractionResult(
            success=False,
            error="모든 추출 방법 실패",
            metadata=metadata,
            method="pptx_all_failed"
        ).to_dict()

    def _extract_with_pptx(self, file_path: str) -> ExtractionResult:
        """python-pptx로 직접 추출."""
        try:
            prs = Presentation(file_path)
            content_parts = []
            slide_count = 0

            for slide_num, slide in enumerate(prs.slides, 1):
                slide_count += 1
                slide_text = [f"--- Slide {slide_num} ---"]

                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_text.append(shape.text)

                    # 표 내용 추출
                    if shape.has_table:
                        table = shape.table
                        for row in table.rows:
                            row_text = [cell.text.strip() for cell in row.cells]
                            slide_text.append(" | ".join(row_text))

                content_parts.append("\n".join(slide_text))

            content = "\n\n".join(content_parts)

            return ExtractionResult(
                success=True,
                content=content,
                metadata={
                    "source": file_path,
                    "filename": Path(file_path).name,
                    "slides": slide_count,
                    "content_length": len(content),
                },
                method="python-pptx"
            )

        except Exception as e:
            return ExtractionResult(
                success=False,
                error=str(e),
                method="python-pptx"
            )

    async def _extract_with_ocr(self, file_path: str) -> Optional[ExtractionResult]:
        """PPTX → PDF → OCR 추출."""
        try:
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
                            parts.append(f"--- Slide {i} ---\n{text.strip()}")

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
                            "slides": len(parts),
                            "ocr_lang": "kor+eng",
                        },
                        method="pptx_ocr"
                    )

                except ImportError:
                    return None

        except Exception as e:
            print(f"[WARN] OCR extraction failed for {file_path}: {e}")
            return None

    def _merge_content(self, direct_text: str, ocr_text: str) -> str:
        """
        직접 추출 텍스트와 OCR 텍스트를 병합.

        전략: 슬라이드별로 더 긴 텍스트 선택
        """
        def parse_slides(text: str) -> dict:
            """슬라이드별로 텍스트 분리."""
            slides = {}
            current_slide = 0
            current_text = []

            for line in text.split('\n'):
                if line.startswith('--- Slide '):
                    if current_slide > 0:
                        slides[current_slide] = '\n'.join(current_text)
                    try:
                        current_slide = int(line.split('--- Slide ')[1].split(' ')[0])
                    except (ValueError, IndexError):
                        current_slide += 1
                    current_text = []
                else:
                    current_text.append(line)

            if current_slide > 0:
                slides[current_slide] = '\n'.join(current_text)

            return slides

        direct_slides = parse_slides(direct_text)
        ocr_slides = parse_slides(ocr_text)

        # 모든 슬라이드 번호
        all_slides = sorted(set(direct_slides.keys()) | set(ocr_slides.keys()))

        merged_parts = []
        for slide_num in all_slides:
            direct_content = direct_slides.get(slide_num, "")
            ocr_content = ocr_slides.get(slide_num, "")

            # 더 긴 텍스트 선택 (빈 줄 제외 비교)
            direct_clean = direct_content.replace('\n', '').replace(' ', '')
            ocr_clean = ocr_content.replace('\n', '').replace(' ', '')

            if len(ocr_clean) > len(direct_clean) * 1.2:
                # OCR이 20% 이상 길면 OCR 사용
                selected = ocr_content
            else:
                # 그 외에는 직접 추출 사용 (구조 보존)
                selected = direct_content

            merged_parts.append(f"--- Slide {slide_num} ---\n{selected}")

        return "\n\n".join(merged_parts)

    def _check_quality(self, text: str) -> dict:
        """텍스트 품질 점검."""
        if not HAS_QUALITY_CHECKER or not text_quality_checker:
            text_len = len(text)
            korean_count = sum(1 for c in text if '가' <= c <= '힣')
            korean_ratio = korean_count / len(text.replace(' ', '')) if text.replace(' ', '') else 0

            return {
                "text_length": text_len,
                "korean_ratio": round(korean_ratio, 4),
                "quality_score": 0.7 if text_len > 100 and korean_ratio > 0.1 else 0.4,
                "decision": "use_direct_text" if text_len > 100 else "need_fallback",
            }

        result = text_quality_checker.check(text)
        return result.to_dict()


# 싱글톤 인스턴스
pptx_extractor = PptxExtractor()
