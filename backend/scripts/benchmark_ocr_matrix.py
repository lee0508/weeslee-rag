"""Benchmark OCR engine and DPI combinations on a single PDF page range."""
from __future__ import annotations

import argparse
import inspect
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytesseract
from pdf2image import convert_from_path

from app.core.database import SessionLocal
from app.models.document_metadata import DocumentMetadata
from app.extractors.pdf_extractor import _get_easyocr_reader

try:
    from app.services.ocr_config import OCRConfig
except ImportError:
    from dataclasses import dataclass, field

    @dataclass
    class _RenderConfig:
        dpi: int = 300
        fmt: str = "jpeg"
        jpeg_quality: int = 95
        grayscale: bool = True
        thread_count: int = 4

        def to_convert_kwargs(self, *, first_page: int | None = None, last_page: int | None = None) -> dict[str, Any]:
            kwargs: dict[str, Any] = {
                "dpi": self.dpi,
                "fmt": self.fmt,
                "grayscale": self.grayscale,
                "thread_count": self.thread_count,
            }
            if self.fmt == "jpeg":
                kwargs["jpegopt"] = {"quality": self.jpeg_quality, "optimize": True}
            if first_page is not None:
                kwargs["first_page"] = first_page
            if last_page is not None:
                kwargs["last_page"] = last_page
            return kwargs

    @dataclass
    class _TesseractConfig:
        lang: str = "kor+eng"
        oem: int = 1
        psm: int = 3
        preserve_interword_spaces: bool = True
        timeout: int = 120

        def to_config_string(self) -> str:
            parts = [f"--oem {self.oem}", f"--psm {self.psm}"]
            if self.preserve_interword_spaces:
                parts.append("-c preserve_interword_spaces=1")
            return " ".join(parts)

    @dataclass
    class _EasyOCRConfig:
        lang_list: list[str] = field(default_factory=lambda: ["ko", "en"])
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

        def readtext_kwargs(self) -> dict[str, Any]:
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
    class OCRConfig:
        render: _RenderConfig = field(default_factory=_RenderConfig)
        tesseract: _TesseractConfig = field(default_factory=_TesseractConfig)
        easyocr: _EasyOCRConfig = field(default_factory=_EasyOCRConfig)

        @classmethod
        def for_korean_docs(cls, use_gpu: bool = True, dpi: int = 300) -> "OCRConfig":
            cfg = cls()
            cfg.render.dpi = dpi
            cfg.easyocr.gpu = use_gpu
            return cfg


def _resolve_pdf_path(
    *,
    file_path: str | None,
    source_id: str | None,
    document_id: int | None,
) -> tuple[str, dict[str, Any]]:
    if file_path:
        return file_path, {"source": "file_path", "file_path": file_path}

    db = SessionLocal()
    try:
        query = db.query(
            DocumentMetadata.document_id,
            DocumentMetadata.file_name,
            DocumentMetadata.file_path,
            DocumentMetadata.source_id,
        ).filter(DocumentMetadata.file_type == "pdf")

        if document_id is not None:
            row = query.filter(DocumentMetadata.document_id == document_id).first()
        elif source_id:
            row = query.filter(DocumentMetadata.source_id == source_id).first()
        else:
            row = query.first()

        if not row or not row.file_path:
            raise SystemExit("No PDF document found for the given selector.")

        return str(row.file_path), {
            "source": "database",
            "document_id": row.document_id,
            "file_name": row.file_name,
            "source_id": row.source_id,
            "file_path": row.file_path,
        }
    finally:
        db.close()


def _run_tesseract(
    image: Any,
    cfg: OCRConfig,
) -> tuple[int, float]:
    t0 = time.perf_counter()
    text = pytesseract.image_to_string(
        image,
        lang=cfg.tesseract.lang,
        config=cfg.tesseract.to_config_string(),
        timeout=cfg.tesseract.timeout,
    )
    return len((text or "").strip()), time.perf_counter() - t0


def _run_easyocr(
    image: Any,
    cfg: OCRConfig,
) -> tuple[int, int, float]:
    t0 = time.perf_counter()
    reader_sig = inspect.signature(_get_easyocr_reader)
    if len(reader_sig.parameters) >= 2:
        reader = _get_easyocr_reader(cfg.easyocr.gpu, cfg.easyocr.lang_list)
    else:
        reader = _get_easyocr_reader(cfg.easyocr.gpu)
    results = reader.readtext(np.array(image), **cfg.easyocr.readtext_kwargs())
    elapsed = time.perf_counter() - t0
    text_len = 0
    for item in results:
        if isinstance(item, (list, tuple)) and len(item) > 1:
            text_len += len(str(item[1]).strip())
        else:
            text_len += len(str(item).strip())
    return text_len, len(results), elapsed


def benchmark(args: argparse.Namespace) -> dict[str, Any]:
    pdf_path, context = _resolve_pdf_path(
        file_path=args.file_path,
        source_id=args.source_id,
        document_id=args.document_id,
    )
    if not Path(pdf_path).exists():
        raise SystemExit(f"PDF path does not exist: {pdf_path}")

    page_from = args.first_page
    page_to = args.last_page or args.first_page
    matrix: list[dict[str, Any]] = []

    for dpi in args.dpis:
        cfg = OCRConfig.for_korean_docs(use_gpu=args.use_gpu, dpi=dpi)
        render_kwargs = cfg.render.to_convert_kwargs(
            first_page=page_from,
            last_page=page_to,
        )
        render_start = time.perf_counter()
        images = convert_from_path(pdf_path, **render_kwargs)
        render_elapsed = time.perf_counter() - render_start
        if not images:
            matrix.append({
                "dpi": dpi,
                "error": "No images rendered",
            })
            continue

        image = images[0]
        size = image.size

        for engine in args.engines:
            row: dict[str, Any] = {
                "dpi": dpi,
                "engine": engine,
                "page": page_from,
                "image_size": list(size),
                "render_seconds": round(render_elapsed, 3),
                "render_format": cfg.render.fmt,
                "render_grayscale": cfg.render.grayscale,
            }
            if engine == "tesseract":
                text_len, ocr_elapsed = _run_tesseract(image, cfg)
                row.update({
                    "ocr_seconds": round(ocr_elapsed, 3),
                    "text_length": text_len,
                    "tesseract_config": cfg.tesseract.to_config_string(),
                })
            elif engine == "easyocr":
                text_len, result_count, ocr_elapsed = _run_easyocr(image, cfg)
                row.update({
                    "ocr_seconds": round(ocr_elapsed, 3),
                    "text_length": text_len,
                    "result_count": result_count,
                    "easyocr_options": cfg.easyocr.readtext_kwargs(),
                })
            else:
                row["error"] = f"Unsupported engine: {engine}"
            row["total_seconds"] = round(row.get("render_seconds", 0) + row.get("ocr_seconds", 0), 3)
            matrix.append(row)

    return {
        "context": context,
        "page_range": [page_from, page_to],
        "matrix": matrix,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark OCR matrix on a PDF sample.")
    parser.add_argument("--source-id", help="Select the first PDF under the given source_id.")
    parser.add_argument("--document-id", type=int, help="Select a specific document_id.")
    parser.add_argument("--file-path", help="Use an explicit PDF file path.")
    parser.add_argument("--first-page", type=int, default=1, help="1-based start page.")
    parser.add_argument("--last-page", type=int, help="1-based end page. Defaults to first-page.")
    parser.add_argument("--dpis", nargs="+", type=int, default=[300, 450], help="DPI values to benchmark.")
    parser.add_argument(
        "--engines",
        nargs="+",
        default=["tesseract", "easyocr"],
        help="OCR engines to benchmark.",
    )
    parser.add_argument("--use-gpu", action="store_true", default=False, help="Enable GPU for EasyOCR.")
    args = parser.parse_args()

    result = benchmark(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
