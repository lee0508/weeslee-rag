# PDF 문서 추출기 - OCR 지원 (pytesseract + easyocr fallback)
# 작업일: 2026-07-08 - DB 시스템 설정 연동 추가, structured_txt 우선 참조 추가
# 작업일: 2026-07-14 - PyMuPDF 기반 페이지별 렌더링으로 대형 PDF 처리 안정화
# 작업일: 2026-07-14 - pdf-ocr 프로젝트 품질 향상 기법 적용 (이미지 전처리, 품질 분석)
"""
PDF Extractor with OCR support (pytesseract + easyocr fallback)
표 추출 개선: Camelot/Tabula 병행 사용으로 구조화된 표 추출 지원
[2026-07-08] structured_txt 우선 사용 지원 - 수동 추출 파일이 있으면 먼저 사용
[2026-07-14] PyMuPDF 기반 페이지별 렌더링 - 대형 PDF 메모리/타임아웃 문제 해결
[2026-07-14] pdf-ocr 프로젝트 기법 적용: 이미지 전처리, 품질 분석, 적응형 OCR
"""
import os
import shutil
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import pdfplumber
import logging

# OpenCV for image preprocessing (optional)
try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False
    cv2 = None

# PyMuPDF for efficient page-by-page rendering
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    fitz = None

from app.extractors.base import BaseExtractor, ExtractionResult
from app.services.ocr_config import OCRConfig

# [2026-07-08] structured 파일 우선 사용 지원
try:
    from app.services.structured_content_resolver import StructuredContentResolver
    HAS_STRUCTURED_RESOLVER = True
except ImportError:
    HAS_STRUCTURED_RESOLVER = False
    StructuredContentResolver = None


def _get_db_ocr_setting(key: str, default):
    """DB에서 OCR 설정 조회. 실패 시 default 반환."""
    try:
        from app.services.system_settings_service import get_system_setting
        return get_system_setting("ocr", key, default)
    except Exception:
        return default

logger = logging.getLogger(__name__)


# ================================================
# [2026-07-14] pdf-ocr 프로젝트 이미지 전처리 기법 이식
# ================================================

# 품질 분석 상수 (pdf-ocr에서 이식)
QUALITY_SHARPNESS_HIGH = 800
QUALITY_SHARPNESS_MEDIUM = 400
QUALITY_SHARPNESS_LOW = 200
QUALITY_CONTRAST_HIGH = 0.35
QUALITY_CONTRAST_MEDIUM = 0.20


def _analyze_image_quality(image) -> Dict[str, Any]:
    """
    [2026-07-14] 이미지 품질 분석 (pdf-ocr 프로젝트 방식).
    선명도, 대비 측정 후 전처리 전략 결정.
    """
    import numpy as np

    if not HAS_OPENCV or cv2 is None:
        return {
            "type": "unknown",
            "sharpness": 0,
            "contrast": 0,
            "preprocessing": {},
            "suggest_enhancement": False,
        }

    # PIL Image -> numpy array
    if hasattr(image, "convert"):
        img_array = np.array(image.convert("L"))
    else:
        img_array = image

    # Grayscale 변환
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array

    # 1. 선명도 측정 (Laplacian 분산)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    sharpness = float(laplacian.var())

    # 2. 대비 측정 (히스토그램 표준편차)
    contrast = float(gray.std() / 255.0)

    # 품질 판정
    if sharpness > QUALITY_SHARPNESS_HIGH and contrast > QUALITY_CONTRAST_HIGH:
        quality_type = "high"
        suggest_enhancement = False
    elif sharpness > QUALITY_SHARPNESS_MEDIUM:
        quality_type = "medium"
        suggest_enhancement = True
    elif sharpness > QUALITY_SHARPNESS_LOW:
        quality_type = "low"
        suggest_enhancement = True
    else:
        quality_type = "very_low"
        suggest_enhancement = True

    return {
        "type": quality_type,
        "sharpness": sharpness,
        "contrast": contrast,
        "suggest_enhancement": suggest_enhancement,
    }


def _enhance_image_for_ocr(image) -> Tuple[Any, Dict[str, Any]]:
    """
    [2026-07-14] OCR을 위한 이미지 전처리 (pdf-ocr 프로젝트 auto_enhance_for_ocr 이식).

    처리 순서:
    1. Grayscale 변환
    2. CLAHE 대비 강화
    3. Otsu 이진화
    4. 모폴로지 노이즈 제거
    """
    import numpy as np
    from PIL import Image

    enhancement_info = {"steps_applied": [], "original_mode": None}

    if not HAS_OPENCV or cv2 is None:
        logger.debug("[OCR] OpenCV 미설치 - 전처리 건너뜀")
        return image, enhancement_info

    # PIL Image -> numpy array
    if hasattr(image, "mode"):
        enhancement_info["original_mode"] = image.mode
        img_array = np.array(image)
    else:
        img_array = image

    # 1. Grayscale 변환
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array
    enhancement_info["steps_applied"].append("grayscale")

    # 2. 배경 밝기 분석
    avg_brightness = float(np.mean(gray))
    is_dark_bg = avg_brightness < 128
    is_very_light = avg_brightness > 240

    enhancement_info["avg_brightness"] = avg_brightness
    enhancement_info["background_type"] = (
        "dark" if is_dark_bg else ("very_light" if is_very_light else "normal")
    )

    enhanced = gray.copy()

    # 3. 어두운 배경 반전
    if is_dark_bg:
        enhanced = cv2.bitwise_not(enhanced)
        enhancement_info["steps_applied"].append("invert_dark_bg")

    # 4. CLAHE 대비 강화 (밝은/어두운 배경 모두에 적용)
    if is_very_light or is_dark_bg:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(enhanced)
        enhancement_info["steps_applied"].append("clahe")

    # 5. Otsu 이진화
    threshold_value, binary = cv2.threshold(
        enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    enhancement_info["steps_applied"].append(f"otsu_threshold={threshold_value:.0f}")
    enhancement_info["otsu_threshold"] = float(threshold_value)

    # 6. 모폴로지 노이즈 제거
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    enhancement_info["steps_applied"].append("denoise_morphology")

    # numpy array -> PIL Image
    enhanced_pil = Image.fromarray(binary)

    logger.debug(
        f"[OCR] 이미지 전처리 완료: {len(enhancement_info['steps_applied'])}단계 "
        f"({', '.join(enhancement_info['steps_applied'])})"
    )

    return enhanced_pil, enhancement_info


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


# EasyOCR reader 캐싱 (CPU/GPU 모드별 분리)
_easyocr_readers: dict[str, Any] = {}


def _get_easyocr_reader(
    use_gpu_override: Optional[bool] = None,
    lang_list: Optional[List[str]] = None,
):
    """EasyOCR reader 싱글톤 반환."""
    try:
        import torch
        detected_gpu = torch.cuda.is_available()
    except ImportError:
        detected_gpu = False

    use_gpu = detected_gpu if use_gpu_override is None else bool(use_gpu_override)
    langs = tuple(lang_list or ["ko", "en"])
    cache_key = f"{'gpu' if use_gpu else 'cpu'}:{','.join(langs)}"

    if cache_key not in _easyocr_readers:
        import easyocr
        _easyocr_readers[cache_key] = easyocr.Reader(
            list(langs),
            gpu=use_gpu,
            verbose=False,
        )
    return _easyocr_readers[cache_key]


def _is_table_extractor_available() -> bool:
    """표 추출 서비스 사용 가능 여부 확인."""
    try:
        from app.services.table_extractor import get_table_extractor_service
        return True
    except ImportError:
        return False


class PDFExtractor(BaseExtractor):
    """Extracts text from PDF files with pytesseract OCR fallback for scanned pages"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

    def _try_structured_txt(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        [2026-07-08] structured_txt 우선 사용.
        1) 같은 폴더에 동일 이름의 .txt 파일이 있으면 사용
        2) 없으면 StructuredContentResolver로 structured_txt 폴더 확인
        """
        file_path_obj = Path(file_path)
        file_name = file_path_obj.name

        # 1단계: 같은 폴더에 .txt 파일 확인
        txt_path = file_path_obj.with_suffix(".txt")
        if txt_path.exists():
            try:
                # UTF-8 BOM 또는 UTF-8로 읽기
                try:
                    content = txt_path.read_text(encoding="utf-8-sig")
                except UnicodeDecodeError:
                    content = txt_path.read_text(encoding="utf-8")

                if content and len(content.strip()) > 100:
                    logger.info(f"[PDF] 같은 폴더 txt 사용: {txt_path.name}")
                    return ExtractionResult(
                        success=True,
                        content=content,
                        metadata={
                            "source": file_path,
                            "filename": file_name,
                            "used_paths": [str(txt_path)],
                        },
                        method="same_folder_txt"
                    ).to_dict()
            except Exception as e:
                logger.debug(f"[PDF] 같은 폴더 txt 읽기 실패: {e}")

        # 2단계: StructuredContentResolver로 structured_txt 폴더 확인
        if not HAS_STRUCTURED_RESOLVER or not StructuredContentResolver:
            return None
        try:
            path_str = str(file_path).replace("\\", "/")

            # relative_path 추론
            relative_path = file_name
            for marker in ["00. RAG 소스/", "01. RFP/", "02. 제안서/", "03. 산출물/"]:
                if marker in path_str:
                    idx = path_str.find(marker)
                    relative_path = path_str[idx:]
                    break

            class _FakeDoc:
                def __init__(self, rp, fn):
                    self.relative_path = rp
                    self.file_name = fn

            resolver = StructuredContentResolver({
                "use_structured_txt": True,
                "use_structured_json": True,
                "prefer_structured_content": True,
                "max_text_chars": 50000,
            })

            content = resolver.resolve_document_content(_FakeDoc(relative_path, file_name))
            combined_text = content.get("combined_text") or ""

            if combined_text and len(combined_text.strip()) > 100:
                logger.info(f"[PDF] structured_txt 우선 사용: {file_name}")
                return ExtractionResult(
                    success=True,
                    content=combined_text,
                    metadata={
                        "source": file_path,
                        "filename": file_name,
                        "used_paths": content.get("used_paths", []),
                    },
                    method="structured_txt_priority"
                ).to_dict()
            return None
        except Exception as e:
            logger.debug(f"[PDF] structured_txt 조회 실패: {e}")
            return None

    def __init__(
        self,
        use_ocr: bool = True,
        ocr_threshold: int = 50,
        ocr_use_gpu: Optional[bool] = None,
        ocr_dpi: int = None,
        ocr_language: str = None,
        extract_tables: bool = True,
        table_as_markdown: bool = True,
        ocr_engine: str = None,
    ):
        self.use_ocr = use_ocr
        self.ocr_threshold = ocr_threshold
        self.ocr_use_gpu = ocr_use_gpu
        # DB 설정 우선, 없으면 하드코딩 fallback
        self.ocr_dpi = max(72, int(ocr_dpi or _get_db_ocr_setting("ocr_dpi", 300)))
        self.ocr_language = str(ocr_language or _get_db_ocr_setting("ocr_language", "kor+eng"))
        self.extract_tables = extract_tables
        self.table_as_markdown = table_as_markdown
        self.ocr_engine = str(ocr_engine or _get_db_ocr_setting("ocr_engine", "tesseract")).lower()

    def _is_scanned_pdf(self, pdf_path: str) -> bool:
        """Return True if first 3 pages yield less than ocr_threshold chars each."""
        try:
            check_pages = self._build_ocr_config().detection.scanned_check_pages
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages[:check_pages]:
                    text = page.extract_text()
                    if text and len(text.strip()) > self.ocr_threshold:
                        return False
                return True
        except Exception:
            return True

    def _build_ocr_config(self) -> OCRConfig:
        return OCRConfig.from_step4_config(
            {
                "ocr_engine": self.ocr_engine,
                "ocr_dpi": self.ocr_dpi,
                "ocr_language": self.ocr_language,
                "ocr_min_text_length": self.ocr_threshold,
            },
            use_gpu=bool(self.ocr_use_gpu) if self.ocr_use_gpu is not None else True,
        )

    def _render_pdf_images_pymupdf(self, pdf_path: str, dpi: int = 300) -> List[Any]:
        """
        [2026-07-14] PyMuPDF 기반 페이지별 렌더링 - pdf-ocr 프로젝트 방식 적용.

        장점:
        - 페이지별 개별 렌더링으로 메모리 효율적
        - pix.samples 직접 사용으로 변환 단계 최소화
        - 대형 PDF에서도 타임아웃 없이 안정적 처리
        """
        from PIL import Image
        import numpy as np

        if not HAS_PYMUPDF or fitz is None:
            raise ImportError("PyMuPDF(fitz) is not installed")

        images = []
        pdf_doc = fitz.open(pdf_path)
        scale = dpi / 72.0

        try:
            for page_num in range(pdf_doc.page_count):
                page = pdf_doc[page_num]
                mat = fitz.Matrix(scale, scale)
                pix = page.get_pixmap(matrix=mat)

                # pix.samples 직접 사용 (메모리 최적화, pdf-ocr 방식)
                samples = pix.samples
                img_array = np.frombuffer(samples, dtype=np.uint8)
                img_array = img_array.reshape(pix.height, pix.width, pix.n if pix.n > 0 else 3)

                # PIL Image로 변환
                if pix.n == 4:
                    # RGBA -> RGB
                    pil_img = Image.fromarray(img_array, mode='RGBA').convert('RGB')
                elif pix.n == 1:
                    # Grayscale -> RGB
                    pil_img = Image.fromarray(img_array, mode='L').convert('RGB')
                else:
                    pil_img = Image.fromarray(img_array, mode='RGB')

                images.append(pil_img)

                # 메모리 해제
                pix = None
        finally:
            pdf_doc.close()

        return images

    def _render_pdf_images(self, pdf_path: str, ocr_cfg: OCRConfig) -> List[Any]:
        """PDF를 이미지로 렌더링. PyMuPDF 우선 사용, 실패 시 pdf2image fallback."""
        render_cfg = ocr_cfg.render
        dpi = render_cfg.dpi

        # [2026-07-14] PyMuPDF 우선 사용 (대형 PDF 안정성)
        if HAS_PYMUPDF:
            try:
                logger.info(f"[PDF] PyMuPDF 렌더링 시작: {Path(pdf_path).name}, DPI={dpi}")
                return self._render_pdf_images_pymupdf(pdf_path, dpi)
            except Exception as e:
                logger.warning(f"[PDF] PyMuPDF 렌더링 실패, pdf2image 폴백: {e}")

        # pdf2image fallback
        from pdf2image import convert_from_path, pdfinfo_from_path

        batch_size = render_cfg.page_batch_size
        if not batch_size or batch_size <= 0:
            return convert_from_path(pdf_path, **render_cfg.to_convert_kwargs())

        try:
            total_pages = int(pdfinfo_from_path(pdf_path).get("Pages") or 0)
        except Exception:
            total_pages = 0

        if total_pages <= 0 or total_pages <= batch_size:
            return convert_from_path(pdf_path, **render_cfg.to_convert_kwargs())

        images: List[Any] = []
        for start_page in range(1, total_pages + 1, batch_size):
            end_page = min(total_pages, start_page + batch_size - 1)
            batch = convert_from_path(
                pdf_path,
                **render_cfg.to_convert_kwargs(
                    first_page=start_page,
                    last_page=end_page,
                ),
            )
            images.extend(batch)
        return images

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

            # 표 추출 (Camelot/Tabula 사용)
            table_markdown = ""
            table_count = 0
            if self.extract_tables and _is_table_extractor_available():
                try:
                    from app.services.table_extractor import get_table_extractor_service
                    table_service = get_table_extractor_service()
                    table_result = table_service.pdf_extractor.extract_tables(pdf_path)

                    if table_result.success and table_result.tables:
                        table_count = len(table_result.tables)
                        metadata["tables_extracted"] = table_count
                        metadata["table_methods"] = table_result.methods_used

                        if self.table_as_markdown:
                            # 표를 Markdown으로 변환하여 본문 끝에 추가
                            table_parts = []
                            for table in table_result.tables:
                                table_header = f"\n\n### 표 (페이지 {table.page_number}, #{table.table_index + 1})\n"
                                table_parts.append(table_header + table.markdown)
                            table_markdown = "\n".join(table_parts)
                except Exception as e:
                    logger.warning(f"Table extraction failed for {pdf_path}: {e}")
                    metadata["table_extraction_error"] = str(e)

            # 본문 + 표 결합
            if table_markdown:
                full_content = full_content + "\n\n---\n## 추출된 표\n" + table_markdown

            return ExtractionResult(
                success=True,
                content=full_content,
                metadata=metadata,
                method="pdfplumber",
            )
        except Exception as e:
            return ExtractionResult(success=False, error=str(e), method="pdfplumber")

    def _extract_with_tesseract(self, pdf_path: str) -> ExtractionResult:
        """Convert pages to images and run tesseract OCR (kor+eng) with image preprocessing."""
        try:
            import pytesseract

            ocr_cfg = self._build_ocr_config()
            images = self._render_pdf_images(pdf_path, ocr_cfg)
            tess_cfg = ocr_cfg.tesseract
            parts = []
            enhancement_stats = []

            for i, img in enumerate(images, start=1):
                # [2026-07-14] pdf-ocr 기법: 품질 분석 후 전처리 적용
                quality_info = _analyze_image_quality(img)
                processed_img = img

                if quality_info.get("suggest_enhancement") and HAS_OPENCV:
                    processed_img, enhance_info = _enhance_image_for_ocr(img)
                    enhancement_stats.append({
                        "page": i,
                        "quality": quality_info.get("type"),
                        "steps": enhance_info.get("steps_applied", []),
                    })
                    logger.debug(
                        f"[OCR] 페이지 {i}: 품질={quality_info.get('type')}, "
                        f"전처리={','.join(enhance_info.get('steps_applied', []))}"
                    )

                text = pytesseract.image_to_string(
                    processed_img,
                    lang=tess_cfg.lang,
                    config=tess_cfg.to_config_string(),
                    timeout=tess_cfg.timeout,
                )
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
                    "ocr_lang": tess_cfg.lang,
                    "ocr_dpi": ocr_cfg.render.dpi,
                    "render_format": ocr_cfg.render.fmt,
                    "render_grayscale": ocr_cfg.render.grayscale,
                    "render_batch_size": ocr_cfg.render.page_batch_size,
                    "tesseract_config": tess_cfg.to_config_string(),
                    "image_preprocessing": True if enhancement_stats else False,
                    "preprocessing_stats": enhancement_stats[:5] if enhancement_stats else [],
                },
                method="tesseract",
            )
        except Exception as e:
            return ExtractionResult(success=False, error=str(e), method="tesseract")

    def _extract_with_easyocr(self, pdf_path: str) -> ExtractionResult:
        """Convert pages to images and run EasyOCR (Korean + English) with image preprocessing."""
        try:
            import numpy as np

            ocr_cfg = self._build_ocr_config()
            easy_cfg = ocr_cfg.easyocr
            reader = _get_easyocr_reader(self.ocr_use_gpu, easy_cfg.lang_list)
            images = self._render_pdf_images(pdf_path, ocr_cfg)
            parts = []
            enhancement_stats = []

            for i, img in enumerate(images, start=1):
                # [2026-07-14] pdf-ocr 기법: 품질 분석 후 전처리 적용
                quality_info = _analyze_image_quality(img)
                processed_img = img

                if quality_info.get("suggest_enhancement") and HAS_OPENCV:
                    processed_img, enhance_info = _enhance_image_for_ocr(img)
                    enhancement_stats.append({
                        "page": i,
                        "quality": quality_info.get("type"),
                        "steps": enhance_info.get("steps_applied", []),
                    })

                img_np = np.array(processed_img)
                results = reader.readtext(img_np, **easy_cfg.readtext_kwargs())
                # 결과에서 텍스트만 추출하고 줄바꿈으로 연결
                page_text = "\n".join(
                    [r[1] if isinstance(r, (list, tuple)) and len(r) > 1 else str(r) for r in results]
                )
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
                    "ocr_lang": "+".join(easy_cfg.lang_list),
                    "ocr_gpu": bool(easy_cfg.gpu),
                    "ocr_dpi": ocr_cfg.render.dpi,
                    "render_format": ocr_cfg.render.fmt,
                    "render_grayscale": ocr_cfg.render.grayscale,
                    "render_batch_size": ocr_cfg.render.page_batch_size,
                    "easyocr_options": easy_cfg.readtext_kwargs(),
                    "image_preprocessing": True if enhancement_stats else False,
                    "preprocessing_stats": enhancement_stats[:5] if enhancement_stats else [],
                },
                method="easyocr",
            )
        except Exception as e:
            return ExtractionResult(success=False, error=str(e), method="easyocr")

    async def _extract_with_olmocr(self, pdf_path: str) -> ExtractionResult:
        """Run olmOCR when installed, keeping fallback outside this method."""
        if shutil.which("olmocr") is None:
            return ExtractionResult(
                success=False,
                error="olmocr command not found",
                method="olmocr",
            )

        try:
            from app.services.ocr import ocr_service

            result = await ocr_service.process_pdf(pdf_path, output_format="text")
            content = str(result.get("content") or "").strip()
            if not result.get("success") or not content:
                return ExtractionResult(
                    success=False,
                    error=str(result.get("error") or "olmOCR produced no text"),
                    method="olmocr",
                )

            return ExtractionResult(
                success=True,
                content=content,
                metadata={
                    "source": pdf_path,
                    "filename": Path(pdf_path).name,
                    "ocr_engine": "olmocr",
                    "ocr_lang": self.ocr_language,
                    "ocr_dpi": self.ocr_dpi,
                },
                method="olmocr",
            )
        except Exception as e:
            return ExtractionResult(success=False, error=str(e), method="olmocr")

    async def _extract_with_preferred_ocr(self, pdf_path: str) -> ExtractionResult:
        """Try the selected OCR engine first, then degrade gracefully."""
        preferred = self.ocr_engine
        attempts: list[tuple[str, str]] = []

        async def try_olmocr() -> Optional[ExtractionResult]:
            result = await self._extract_with_olmocr(pdf_path)
            if result.success and result.content.strip():
                result.metadata.setdefault("selected_method", "olmocr")
                return result
            attempts.append(("olmocr", result.error or "olmOCR failed"))
            return None

        def try_easyocr() -> Optional[ExtractionResult]:
            if not _is_easyocr_available():
                attempts.append(("easyocr", "easyocr not available"))
                return None
            result = self._extract_with_easyocr(pdf_path)
            if result.success and result.content.strip():
                result.metadata["selected_method"] = "easyocr"
                result.metadata["ocr_engine"] = "easyocr"
                return result
            attempts.append(("easyocr", result.error or "easyocr failed"))
            return None

        def try_tesseract() -> Optional[ExtractionResult]:
            if not _is_tesseract_available():
                attempts.append(("tesseract", "tesseract not available"))
                return None
            result = self._extract_with_tesseract(pdf_path)
            if result.success and result.content.strip():
                result.metadata["selected_method"] = "tesseract"
                result.metadata["ocr_engine"] = "tesseract"
                return result
            attempts.append(("tesseract", result.error or "tesseract failed"))
            return None

        if preferred == "olmocr":
            preferred_result = await try_olmocr()
            if preferred_result:
                return preferred_result
            fallback_result = try_easyocr() or try_tesseract()
        elif preferred == "easyocr":
            preferred_result = try_easyocr()
            if preferred_result:
                return preferred_result
            fallback_result = await try_olmocr() or try_tesseract()
        else:
            preferred_result = try_tesseract()
            if preferred_result:
                return preferred_result
            fallback_result = try_easyocr() or await try_olmocr()

        if fallback_result:
            fallback_result.metadata.setdefault("fallback_reason", "; ".join(f"{name}: {error}" for name, error in attempts))
            return fallback_result

        return ExtractionResult(
            success=False,
            error="All OCR methods failed. " + ", ".join(f"{name}: {error}" for name, error in attempts),
            method="ocr_all_failed",
        )

    async def extract(self, file_path: str) -> Dict[str, Any]:
        import time
        start_time = time.time()

        if not os.path.exists(file_path):
            return ExtractionResult(
                success=False, error=f"File not found: {file_path}"
            ).to_dict()

        # [2026-07-08] structured_txt 우선 사용 - 수동 추출 파일이 있으면 먼저 사용
        structured_result = self._try_structured_txt(file_path)
        if structured_result:
            structured_result["metadata"] = structured_result.get("metadata", {})
            structured_result["metadata"]["processing_time_sec"] = round(time.time() - start_time, 2)
            return structured_result

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

        ocr_start = time.time()
        result = await self._extract_with_preferred_ocr(file_path)
        ocr_time = round(time.time() - ocr_start, 2)
        result.metadata["is_scanned"] = True
        result.metadata["ocr_time_sec"] = ocr_time
        result.metadata["processing_time_sec"] = round(time.time() - start_time, 2)
        result.metadata.setdefault("initial_method", "pdfplumber")
        result.metadata.setdefault("preferred_ocr_engine", self.ocr_engine)

        if result.success and result.content.strip():
            if result.metadata.get("selected_method") == "olmocr":
                result.metadata.setdefault("fallback_reason", "scanned_pdf or cid_detected")
            return result.to_dict()

        return result.to_dict()


pdf_extractor = PDFExtractor()
