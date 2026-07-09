"""Shared OCR configuration helpers for Step 4 text extraction."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RenderConfig:
    """PDF/image render settings for OCR input generation."""

    dpi: int = 300
    fmt: str = "jpeg"
    jpeg_quality: int = 95
    grayscale: bool = True
    thread_count: int = 4
    page_batch_size: Optional[int] = 15
    output_folder: Optional[str] = None
    use_pdftocairo: bool = False

    def to_convert_kwargs(
        self,
        *,
        first_page: Optional[int] = None,
        last_page: Optional[int] = None,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "dpi": self.dpi,
            "fmt": self.fmt,
            "grayscale": self.grayscale,
            "thread_count": self.thread_count,
            "use_pdftocairo": self.use_pdftocairo,
        }
        if self.fmt == "jpeg":
            kwargs["jpegopt"] = {"quality": self.jpeg_quality, "optimize": True}
        if self.output_folder:
            kwargs["output_folder"] = self.output_folder
        if first_page is not None:
            kwargs["first_page"] = first_page
        if last_page is not None:
            kwargs["last_page"] = last_page
        return kwargs


@dataclass
class TesseractConfig:
    """pytesseract runtime settings."""

    lang: str = "kor+eng"
    oem: int = 1
    psm: int = 3
    preserve_interword_spaces: bool = True
    char_whitelist: str = ""
    timeout: int = 120

    def to_config_string(self) -> str:
        parts = [f"--oem {self.oem}", f"--psm {self.psm}"]
        if self.preserve_interword_spaces:
            parts.append("-c preserve_interword_spaces=1")
        if self.char_whitelist:
            parts.append(f"-c tessedit_char_whitelist={self.char_whitelist}")
        return " ".join(parts)


@dataclass
class EasyOCRConfig:
    """EasyOCR reader and readtext settings."""

    lang_list: List[str] = field(default_factory=lambda: ["ko", "en"])
    gpu: bool = True
    detail: int = 1
    paragraph: bool = True
    batch_size: int = 8
    decoder: str = "beamsearch"
    beam_width: int = 5
    text_threshold: float = 0.7
    low_text: float = 0.4
    link_threshold: float = 0.4
    contrast_ths: float = 0.1
    adjust_contrast: float = 0.5
    mag_ratio: float = 1.5
    canvas_size: int = 2560

    def reader_kwargs(self) -> Dict[str, Any]:
        return {
            "lang_list": self.lang_list,
            "gpu": self.gpu,
        }

    def readtext_kwargs(self) -> Dict[str, Any]:
        return {
            "detail": self.detail,
            "paragraph": self.paragraph,
            "batch_size": self.batch_size,
            "decoder": self.decoder,
            "beamWidth": self.beam_width,
            "text_threshold": self.text_threshold,
            "low_text": self.low_text,
            "link_threshold": self.link_threshold,
            "contrast_ths": self.contrast_ths,
            "adjust_contrast": self.adjust_contrast,
            "mag_ratio": self.mag_ratio,
            "canvas_size": self.canvas_size,
        }


@dataclass
class DetectionConfig:
    """Scan detection and OCR fallback thresholds."""

    scanned_min_chars: int = 50
    scanned_check_pages: int = 3
    quality_threshold: float = 0.6
    cid_ratio_threshold: float = 10.0


@dataclass
class OCRConfig:
    """Top-level OCR config grouped by render and engine settings."""

    primary_engine: str = "easyocr"
    fallback_engine: str = "tesseract"
    render: RenderConfig = field(default_factory=RenderConfig)
    tesseract: TesseractConfig = field(default_factory=TesseractConfig)
    easyocr: EasyOCRConfig = field(default_factory=EasyOCRConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)

    @classmethod
    def for_korean_docs(cls, use_gpu: bool = True, dpi: int = 300) -> "OCRConfig":
        cfg = cls()
        cfg.render.dpi = dpi
        cfg.easyocr.gpu = use_gpu
        cfg.primary_engine = "easyocr" if use_gpu else "tesseract"
        return cfg

    @classmethod
    def from_step4_config(
        cls,
        step4: Dict[str, Any],
        *,
        use_gpu: bool = True,
    ) -> "OCRConfig":
        cfg = cls.for_korean_docs(use_gpu=use_gpu)
        cfg.primary_engine = str(step4.get("ocr_engine") or cfg.primary_engine).lower()
        cfg.render.dpi = max(72, int(step4.get("ocr_dpi") or cfg.render.dpi))
        lang = str(step4.get("ocr_language") or cfg.tesseract.lang)
        cfg.tesseract.lang = lang
        cfg.easyocr.lang_list = cls._map_lang_to_easyocr(lang)
        cfg.detection.scanned_min_chars = max(
            0,
            int(step4.get("ocr_min_text_length") or cfg.detection.scanned_min_chars),
        )
        return cfg

    @staticmethod
    def _map_lang_to_easyocr(tess_lang: str) -> List[str]:
        table = {"kor": "ko", "eng": "en", "jpn": "ja", "chi_sim": "ch_sim"}
        out: List[str] = []
        for part in str(tess_lang or "").split("+"):
            token = part.strip()
            if not token:
                continue
            mapped = table.get(token, token)
            if mapped not in out:
                out.append(mapped)
        return out or ["ko", "en"]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
