# HWP 문서 추출기 - 구조화된 표 및 BinData OCR 보충
# 작업일: 2026-07-08 - DB 시스템 설정 연동 추가
"""
HWP extractor with unconditional structured-table and BinData OCR supplements.
"""
import io
import os
import sys
import zlib
import shutil
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.extractors.base import BaseExtractor, ExtractionResult
from app.core.locale_env import build_utf8_locale_env
from app.extractors.preconverted_txt_fallback import load_preconverted_artifacts


def _get_db_ocr_setting(key: str, default):
    """DB에서 OCR 설정 조회. 실패 시 default 반환."""
    try:
        from app.services.system_settings_service import get_system_setting
        return get_system_setting("ocr", key, default)
    except Exception:
        return default

logger = logging.getLogger(__name__)

# [2026-07-08] structured 파일 fallback 지원
try:
    from app.services.structured_content_resolver import StructuredContentResolver
    HAS_STRUCTURED_RESOLVER = True
except ImportError:
    HAS_STRUCTURED_RESOLVER = False
    StructuredContentResolver = None

try:
    from app.services.text_quality_checker import text_quality_checker
    HAS_QUALITY_CHECKER = True
except ImportError:
    HAS_QUALITY_CHECKER = False
    text_quality_checker = None


def _hwp5txt_path() -> str:
    """Return the hwp5txt path inside the active virtualenv when possible."""
    bin_dir = Path(sys.executable).parent
    for name in ("hwp5txt", "hwp5txt.exe"):
        candidate = bin_dir / name
        if candidate.exists():
            return str(candidate)
    return "hwp5txt"


def _hwp5proc_path() -> str:
    """Return the hwp5proc path inside the active virtualenv when possible."""
    bin_dir = Path(sys.executable).parent
    for name in ("hwp5proc", "hwp5proc.exe"):
        candidate = bin_dir / name
        if candidate.exists():
            return str(candidate)
    return "hwp5proc"


def _libreoffice_path() -> str:
    """Return the local soffice path or rely on PATH."""
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return "soffice"


def _detect_hwp_container(file_path: str) -> str:
    """Detect the actual container by signature, not only file extension."""
    try:
        with open(file_path, "rb") as fp:
            header = fp.read(8)
    except OSError:
        return "unknown"

    if header.startswith(b"PK\x03\x04"):
        return "hwpx"
    if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "hwp"
    return "unknown"


def _is_table_extractor_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("app.services.table_extractor") is not None
    except Exception:
        return False


class HwpExtractor(BaseExtractor):
    """HWP extractor that always supplements table structure and embedded images."""

    def __init__(
        self,
        use_pdf_fallback: bool = True,
        use_ocr_fallback: bool = True,
        quality_threshold: float = 0.6,
        extract_tables: bool = True,
        table_as_markdown: bool = True,
        ocr_dpi: int = None,
        ocr_language: str = None,
        ocr_engine: str = None,
        ocr_use_gpu: Optional[bool] = None,
        ocr_image_min_bytes: int = 3000,
        # [2026-07-08] structured 파일 fallback 설정
        use_structured_fallback: bool = True,
        structured_txt_root: Optional[str] = None,
        structured_json_root: Optional[str] = None,
    ):
        self.use_pdf_fallback = use_pdf_fallback
        self.use_ocr_fallback = use_ocr_fallback
        self.quality_threshold = quality_threshold
        self.extract_tables = extract_tables
        self.table_as_markdown = table_as_markdown
        # DB 설정 우선, 없으면 하드코딩 fallback
        self.ocr_dpi = max(72, int(ocr_dpi or _get_db_ocr_setting("ocr_dpi", 300)))
        self.ocr_language = str(ocr_language or _get_db_ocr_setting("ocr_language", "kor+eng"))
        self.ocr_engine = str(ocr_engine or _get_db_ocr_setting("ocr_engine", "tesseract")).lower()
        self.ocr_use_gpu = ocr_use_gpu
        self.ocr_image_min_bytes = int(ocr_image_min_bytes or 3000)
        self._pdf_cache: dict[str, str] = {}
        self._pdf_tmpdirs: dict[str, str] = {}
        # [2026-07-08] structured 파일 fallback 설정
        self.use_structured_fallback = use_structured_fallback
        self.structured_txt_root = structured_txt_root
        self.structured_json_root = structured_json_root

    @property
    def supported_extensions(self) -> List[str]:
        return [".hwp"]

    async def extract(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            return ExtractionResult(
                success=False,
                error=f"File not found: {file_path}",
            ).to_dict()

        metadata: Dict[str, Any] = {
            "source": file_path,
            "filename": Path(file_path).name,
            "extraction_attempts": [],
        }
        detected_container = _detect_hwp_container(file_path)
        metadata["detected_container"] = detected_container

        try:
            if detected_container == "hwpx":
                from app.extractors.hwpx_extractor import HwpxExtractor

                hwpx_result = await HwpxExtractor().extract(file_path)
                if hwpx_result.get("success"):
                    result_metadata = hwpx_result.get("metadata") or {}
                    result_metadata.update(metadata)
                    result_metadata["final_method"] = "hwpx_magic_detected"
                    hwpx_result["metadata"] = result_metadata
                    return hwpx_result

            base_text, base_method = await self._get_base_text(file_path, metadata)

            supplements: List[Tuple[str, str]] = []
            if self.extract_tables:
                table_markdown = await self._extract_structured_tables(file_path, metadata)
                if table_markdown:
                    supplements.append(("표", table_markdown))

            if self.use_ocr_fallback:
                image_text = self._ocr_bindata_images(file_path, metadata)
                if image_text:
                    supplements.append(("이미지 OCR", image_text))

            final_text = self._merge_base_and_supplements(base_text, supplements)
            if not final_text.strip():
                return ExtractionResult(
                    success=False,
                    error="모든 추출 방법 실패",
                    metadata=metadata,
                    method="hwp_all_failed",
                ).to_dict()

            metadata["final_method"] = base_method
            metadata["supplemented_with"] = [name for name, _ in supplements]
            metadata["content_length"] = len(final_text)
            if supplements:
                metadata["ocr_engine"] = self._supplement_ocr_engine()
            return ExtractionResult(
                success=True,
                content=final_text,
                metadata=metadata,
                method=f"{base_method}+supplements" if supplements else base_method,
            ).to_dict()
        finally:
            self._cleanup_all_pdfs()

    async def _get_base_text(self, file_path: str, metadata: dict) -> Tuple[str, str]:
        copied_artifact_result = load_preconverted_artifacts(file_path)
        metadata["extraction_attempts"].append({
            "method": "copied_artifact_priority",
            "success": copied_artifact_result is not None,
            "text_length": len(copied_artifact_result["text"]) if copied_artifact_result else 0,
            "used_paths": copied_artifact_result["paths"] if copied_artifact_result else [],
            "artifact_types": copied_artifact_result["types"] if copied_artifact_result else [],
        })
        if copied_artifact_result:
            metadata["copied_artifact_paths"] = copied_artifact_result["paths"]
            metadata["copied_artifact_types"] = copied_artifact_result["types"]
            return copied_artifact_result["text"], "copied_artifact_priority"

        # [2026-07-08] structured_txt 우선 사용 - 수동 추출 파일이 있으면 먼저 사용
        if self.use_structured_fallback and HAS_STRUCTURED_RESOLVER:
            structured_result = self._extract_from_structured_files(file_path)
            metadata["extraction_attempts"].append({
                "method": "structured_txt_priority",
                "success": structured_result is not None,
                "text_length": len(structured_result) if structured_result else 0,
            })
            if structured_result:
                return structured_result, "structured_txt_priority"

        direct_result = self._extract_with_hwp5txt(file_path)
        metadata["extraction_attempts"].append({
            "method": "hwp5txt",
            "success": direct_result.success,
            "text_length": len(direct_result.content) if direct_result.content else 0,
        })
        if direct_result.success and direct_result.content:
            quality = self._check_quality(direct_result.content)
            metadata["quality"] = quality
            if quality.get("quality_score", 0) >= self.quality_threshold:
                return direct_result.content, "hwp5txt_direct"

        if self.use_pdf_fallback:
            pdf_result = await self._extract_with_pdf_conversion(file_path)
            metadata["extraction_attempts"].append({
                "method": "pdf_conversion",
                "success": pdf_result.success if pdf_result else False,
                "text_length": len(pdf_result.content) if pdf_result and pdf_result.content else 0,
            })
            if pdf_result and pdf_result.success and pdf_result.content:
                pdf_quality = self._check_quality(pdf_result.content)
                metadata["pdf_quality"] = pdf_quality
                if pdf_quality.get("quality_score", 0) >= self.quality_threshold:
                    return pdf_result.content, "pdf_conversion"

        if self.use_ocr_fallback:
            ocr_result = await self._extract_with_full_ocr(file_path)
            metadata["extraction_attempts"].append({
                "method": "full_ocr",
                "success": ocr_result.success if ocr_result else False,
                "text_length": len(ocr_result.content) if ocr_result and ocr_result.content else 0,
            })
            if ocr_result and ocr_result.success and ocr_result.content:
                return ocr_result.content, "full_ocr"

        preview_result = self._extract_with_prvtext(file_path)
        metadata["extraction_attempts"].append({
            "method": "prvtext",
            "success": preview_result.success if preview_result else False,
            "text_length": len(preview_result.content) if preview_result and preview_result.content else 0,
        })
        if preview_result and preview_result.success and preview_result.content:
            return preview_result.content, "hwp_prvtext_fallback"

        if direct_result.success and direct_result.content:
            return direct_result.content, "hwp5txt_low_quality"

        return "", "hwp_none"

    def _extract_with_hwp5txt(self, file_path: str) -> ExtractionResult:
        try:
            result = subprocess.run(
                [_hwp5txt_path(), file_path],
                capture_output=True,
                timeout=60,
                env=build_utf8_locale_env(),
            )
            text = result.stdout.decode("utf-8", errors="replace").strip()
            if not text:
                stderr = result.stderr.decode("utf-8", errors="replace")
                return ExtractionResult(
                    success=False,
                    error=f"hwp5txt returned empty output. stderr: {stderr[:200]}",
                    method="hwp5txt",
                )
            return ExtractionResult(
                success=True,
                content=text,
                metadata={
                    "source": file_path,
                    "filename": Path(file_path).name,
                    "content_length": len(text),
                },
                method="hwp5txt",
            )
        except subprocess.TimeoutExpired:
            return ExtractionResult(success=False, error="hwp5txt timed out (>60s)", method="hwp5txt")
        except FileNotFoundError:
            return ExtractionResult(
                success=False,
                error="hwp5txt not found. pyhwp 패키지가 설치되어 있는지 확인하세요.",
                method="hwp5txt",
            )
        except Exception as e:
            return ExtractionResult(success=False, error=str(e), method="hwp5txt")

    async def _extract_with_pdf_conversion(self, file_path: str) -> Optional[ExtractionResult]:
        pdf_path = await self._convert_to_pdf(file_path)
        if not pdf_path:
            return None
        try:
            import pdfplumber

            content_parts: List[str] = []
            with pdfplumber.open(pdf_path) as pdf:
                for index, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        content_parts.append(f"--- Page {index + 1} ---\n{text}")

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
                method="hwp_pdf_conversion",
            )
        except Exception as e:
            logger.warning(f"PDF text extraction failed for {file_path}: {e}")
            return None

    async def _extract_with_full_ocr(self, file_path: str) -> Optional[ExtractionResult]:
        pdf_path = await self._convert_to_pdf(file_path)
        if not pdf_path:
            return None
        try:
            from app.extractors.pdf_extractor import PDFExtractor

            pdf_result = await PDFExtractor(
                use_ocr=True,
                ocr_threshold=1,
                ocr_use_gpu=self.ocr_use_gpu,
                ocr_dpi=self.ocr_dpi,
                ocr_language=self.ocr_language,
                extract_tables=self.extract_tables,
                table_as_markdown=self.table_as_markdown,
                ocr_engine=self.ocr_engine,
            ).extract(str(pdf_path))

            if not pdf_result.get("success") or not str(pdf_result.get("content") or "").strip():
                return None

            metadata = dict(pdf_result.get("metadata") or {})
            metadata.update({
                "source": file_path,
                "filename": Path(file_path).name,
                "content_length": len(str(pdf_result.get("content") or "")),
                "ocr_lang": self.ocr_language,
                "ocr_dpi": self.ocr_dpi,
                "ocr_engine": metadata.get("ocr_engine") or metadata.get("selected_method") or self.ocr_engine,
                "pdf_converted_for_ocr": True,
            })

            return ExtractionResult(
                success=True,
                content=str(pdf_result.get("content") or ""),
                metadata=metadata,
                method=f"hwp_{pdf_result.get('method') or 'ocr'}",
            )
        except Exception as e:
            logger.warning(f"Full OCR failed for {file_path}: {e}")
            return None

    def _extract_with_prvtext(self, file_path: str) -> Optional[ExtractionResult]:
        try:
            result = subprocess.run(
                [_hwp5proc_path(), "cat", file_path, "PrvText"],
                capture_output=True,
                timeout=60,
                env=build_utf8_locale_env(),
            )
            raw = result.stdout or b""
            if not raw:
                return None
            text = raw.decode("utf-16-le", errors="ignore").replace("\x00", "").strip()
            if not text:
                return None
            return ExtractionResult(
                success=True,
                content=text,
                metadata={
                    "source": file_path,
                    "filename": Path(file_path).name,
                    "content_length": len(text),
                },
                method="hwp_prvtext",
            )
        except Exception:
            return None

    async def _extract_structured_tables(self, file_path: str, metadata: dict) -> str:
        if not (self.table_as_markdown and _is_table_extractor_available()):
            return ""

        pdf_path = await self._convert_to_pdf(file_path)
        if not pdf_path:
            return ""

        try:
            from app.services.table_extractor import get_table_extractor_service

            table_service = get_table_extractor_service()
            table_result = table_service.pdf_extractor.extract_tables(str(pdf_path))
            if not (table_result.success and table_result.tables):
                return ""

            metadata["tables_extracted"] = len(table_result.tables)
            metadata["table_methods"] = table_result.methods_used
            table_parts: List[str] = []
            for table in table_result.tables:
                table_header = f"\n### 표 (페이지 {table.page_number}, #{table.table_index + 1})\n"
                table_parts.append(table_header + table.markdown)
            return "\n".join(table_parts)
        except Exception as e:
            logger.warning(f"Structured table extraction failed for {file_path}: {e}")
            metadata["table_extraction_error"] = str(e)
            return ""

    def _ocr_bindata_images(self, file_path: str, metadata: dict) -> str:
        images = self._read_bindata_images(file_path)
        metadata["bindata_image_count"] = len(images)
        if not images:
            return ""

        texts: List[str] = []
        for _, blob in images:
            if len(blob) < self.ocr_image_min_bytes:
                continue
            text = self._ocr_image_bytes(blob)
            if text:
                texts.append(text)
        return "\n".join(texts)

    def _read_bindata_images(self, file_path: str) -> List[Tuple[str, bytes]]:
        output: List[Tuple[str, bytes]] = []
        try:
            import olefile
        except ImportError:
            logger.warning("olefile 미설치 -> HWP BinData OCR 생략")
            return output

        if not olefile.isOleFile(file_path):
            return output

        def is_image(blob: bytes) -> bool:
            return (
                blob[:4] == b"\x89PNG"
                or blob[:2] == b"\xff\xd8"
                or blob[:2] == b"BM"
                or blob[:3] == b"GIF"
                or blob[:4] == b"II*\x00"
                or blob[:4] == b"MM\x00*"
            )

        ole = olefile.OleFileIO(file_path)
        try:
            for entry in ole.listdir():
                if entry[0] != "BinData":
                    continue
                raw = ole.openstream(entry).read()
                data = None
                if is_image(raw):
                    data = raw
                else:
                    try:
                        decoded = zlib.decompress(raw, -15)
                        if is_image(decoded):
                            data = decoded
                    except Exception:
                        data = None
                if data:
                    output.append(("/".join(entry), data))
        finally:
            ole.close()
        return output

    def _ocr_image_bytes(self, blob: bytes) -> str:
        try:
            from PIL import Image
        except ImportError:
            return ""

        try:
            image = Image.open(io.BytesIO(blob))
            image.load()
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
        except Exception:
            return ""

        if self.ocr_engine in {"easyocr", "olmocr"}:
            try:
                import numpy as np
                from app.extractors.pdf_extractor import _get_easyocr_reader

                reader = _get_easyocr_reader(self.ocr_use_gpu)
                results = reader.readtext(np.array(image))
                text = "\n".join(item[1] for item in results).strip()
                if text:
                    return text
            except Exception:
                pass

        try:
            import pytesseract
            return pytesseract.image_to_string(image, lang=self.ocr_language).strip()
        except Exception:
            return ""

    def _merge_base_and_supplements(self, base_text: str, supplements: List[Tuple[str, str]]) -> str:
        base_norm = self._normalize(base_text)
        blocks = [base_text.strip()] if base_text.strip() else []

        for name, text in supplements:
            if not text.strip():
                continue
            if name == "표":
                blocks.append("\n---\n## 추출된 표\n" + text.strip())
                continue

            new_lines = []
            for line in text.splitlines():
                stripped = line.strip()
                if len(stripped) < 2:
                    continue
                if self._normalize(stripped) in base_norm:
                    continue
                new_lines.append(stripped)
            if new_lines:
                blocks.append("\n---\n## 이미지 텍스트(OCR)\n" + "\n".join(new_lines))

        return "\n\n".join(blocks)

    async def _convert_to_pdf(self, file_path: str) -> Optional[str]:
        if file_path in self._pdf_cache and Path(self._pdf_cache[file_path]).exists():
            return self._pdf_cache[file_path]

        tmpdir = tempfile.mkdtemp(prefix="hwp_pdf_")
        try:
            process = subprocess.run(
                [_libreoffice_path(), "--headless", "--convert-to", "pdf", "--outdir", tmpdir, file_path],
                capture_output=True,
                timeout=120,
                env=build_utf8_locale_env(),
            )
            if process.returncode != 0:
                shutil.rmtree(tmpdir, ignore_errors=True)
                return None
            pdf_files = list(Path(tmpdir).glob("*.pdf"))
            if not pdf_files:
                shutil.rmtree(tmpdir, ignore_errors=True)
                return None
            pdf_path = str(pdf_files[0])
            self._pdf_cache[file_path] = pdf_path
            self._pdf_tmpdirs[pdf_path] = tmpdir
            return pdf_path
        except Exception as e:
            logger.warning(f"LibreOffice PDF conversion failed for {file_path}: {e}")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None

    def _cleanup_all_pdfs(self) -> None:
        for tmpdir in list(self._pdf_tmpdirs.values()):
            if tmpdir and Path(tmpdir).exists():
                shutil.rmtree(tmpdir, ignore_errors=True)
        self._pdf_cache.clear()
        self._pdf_tmpdirs.clear()

    @staticmethod
    def _normalize(text: str) -> str:
        return text.replace(" ", "").replace("\n", "").replace("\t", "")

    def _supplement_ocr_engine(self) -> str:
        if self.ocr_engine in {"easyocr", "olmocr"}:
            return "easyocr"
        return "tesseract"

    def _check_quality(self, text: str) -> dict:
        if not HAS_QUALITY_CHECKER or not text_quality_checker:
            text_length = len(text)
            korean_count = sum(1 for char in text if "가" <= char <= "힣")
            denominator = len(text.replace(" ", "")) or 1
            korean_ratio = korean_count / denominator
            return {
                "text_length": text_length,
                "korean_ratio": round(korean_ratio, 4),
                "quality_score": 0.7 if text_length > 100 and korean_ratio > 0.2 else 0.4,
                "decision": "use_direct_text" if text_length > 100 else "need_fallback",
            }

        return text_quality_checker.check(text).to_dict()

    # [2026-07-08] structured 파일에서 텍스트 추출
    def _extract_from_structured_files(self, file_path: str) -> Optional[str]:
        """
        hwp 추출 실패 시 structured_txt/structured_json 파일에서 텍스트를 가져옵니다.
        수동 작성된 구조화 파일이 있으면 그 내용을 사용합니다.
        """
        if not HAS_STRUCTURED_RESOLVER or not StructuredContentResolver:
            return None

        try:
            # 파일 경로에서 relative_path와 file_name 추출
            file_name = Path(file_path).name

            # document 객체를 흉내내는 간단한 클래스 생성
            class _FakeDocument:
                def __init__(self, fp: str, fn: str):
                    self.file_path = fp
                    self.file_name = fn
                    # relative_path를 추론: weeslee-mnt 기준 또는 RAG 소스 기준
                    self.relative_path = self._infer_relative_path(fp)

                def _infer_relative_path(self, fp: str) -> str:
                    # 경로에서 "00. RAG 소스" 이후 부분 추출
                    path_str = str(fp).replace("\\", "/")
                    markers = ["00. RAG 소스/", "00. RAG 소스\\"]
                    for marker in markers:
                        if marker in path_str:
                            idx = path_str.find(marker)
                            return path_str[idx:]
                    # 또는 01. RFP, 02. 제안서 등으로 시작하는 부분
                    for prefix in ["01. RFP", "02. 제안서", "03. 산출물"]:
                        if prefix in path_str:
                            idx = path_str.find(prefix)
                            return path_str[idx:]
                    return Path(fp).name

            fake_doc = _FakeDocument(file_path, file_name)

            config = {
                "use_structured_txt": True,
                "use_structured_json": True,
                "prefer_structured_content": True,
                "max_text_chars": 50000,
            }
            if self.structured_txt_root:
                config["structured_txt_root"] = self.structured_txt_root
            if self.structured_json_root:
                config["structured_json_root"] = self.structured_json_root

            resolver = StructuredContentResolver(config)
            content = resolver.resolve_document_content(fake_doc)

            combined_text = content.get("combined_text") or ""
            if combined_text and len(combined_text.strip()) > 100:
                logger.info(f"[structured_fallback] {file_name}: {len(combined_text)} chars from {content.get('used_paths')}")
                return combined_text

            return None
        except Exception as e:
            logger.warning(f"[structured_fallback] Failed for {file_path}: {e}")
            return None


hwp_extractor = HwpExtractor()
