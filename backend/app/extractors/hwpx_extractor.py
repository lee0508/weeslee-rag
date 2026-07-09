"""
HWPX Extractor
"""
import os
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional
from xml.etree import ElementTree as ET

from app.extractors.base import BaseExtractor, ExtractionResult
from app.extractors.preconverted_txt_fallback import load_preconverted_artifacts

# [2026-07-08] structured 파일 우선 사용 지원
try:
    from app.services.structured_content_resolver import StructuredContentResolver
    HAS_STRUCTURED_RESOLVER = True
except ImportError:
    HAS_STRUCTURED_RESOLVER = False
    StructuredContentResolver = None


class HwpxExtractor(BaseExtractor):
    """Extracts text from HWPX files"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".hwpx"]

    def _read_text_file(self, zf: zipfile.ZipFile, candidates: List[str]) -> Optional[str]:
        for name in candidates:
            try:
                raw = zf.read(name)
            except KeyError:
                continue

            for encoding in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
                try:
                    text = raw.decode(encoding)
                    if text.strip():
                        return text
                except UnicodeDecodeError:
                    continue
        return None

    def _extract_from_xml(self, xml_bytes: bytes) -> str:
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return ""

        parts: List[str] = []
        for text in root.itertext():
            value = text.strip()
            if value:
                parts.append(value)
        return " ".join(parts)

    async def extract(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            return ExtractionResult(
                success=False,
                error=f"File not found: {file_path}"
            ).to_dict()

        copied_artifact_result = load_preconverted_artifacts(file_path)
        if copied_artifact_result:
            return ExtractionResult(
                success=True,
                content=copied_artifact_result["text"],
                metadata={
                    "source": file_path,
                    "filename": Path(file_path).name,
                    "used_paths": copied_artifact_result["paths"],
                    "copied_artifact_paths": copied_artifact_result["paths"],
                    "copied_artifact_types": copied_artifact_result["types"],
                },
                method="copied_artifact_priority"
            ).to_dict()

        # [2026-07-08] structured_txt 우선 사용 - 수동 추출 파일이 있으면 먼저 사용
        structured_result = self._try_structured_txt(file_path)
        if structured_result:
            return structured_result

        try:
            content_parts: List[str] = []
            metadata: Dict[str, Any] = {
                "source": file_path,
                "filename": Path(file_path).name,
                "preview_available": False,
                "sections": 0,
            }

            with zipfile.ZipFile(file_path) as zf:
                preview_text = self._read_text_file(
                    zf,
                    [
                        "Preview/PrvText.txt",
                        "preview/PrvText.txt",
                    ]
                )

                if preview_text:
                    metadata["preview_available"] = True
                    content_parts.append(preview_text.strip())

                section_names = sorted(
                    [name for name in zf.namelist() if name.startswith("Contents/section") and name.endswith(".xml")]
                )

                metadata["sections"] = len(section_names)

                for index, name in enumerate(section_names, 1):
                    try:
                        xml_bytes = zf.read(name)
                    except KeyError:
                        continue

                    section_text = self._extract_from_xml(xml_bytes)
                    if section_text:
                        content_parts.append(f"--- Section {index} ({name}) ---\n{section_text}")

            content = "\n\n".join(part for part in content_parts if part.strip())

            if not content.strip():
                return ExtractionResult(
                    success=False,
                    error="No text content found in HWPX file"
                ).to_dict()

            metadata["content_length"] = len(content)

            return ExtractionResult(
                success=True,
                content=content,
                metadata=metadata,
                method="hwpx-zip"
            ).to_dict()

        except Exception as e:
            return ExtractionResult(
                success=False,
                error=str(e),
                method="hwpx-zip"
            ).to_dict()

    def _try_structured_txt(self, file_path: str) -> Optional[Dict[str, Any]]:
        """수동 추출 파일이 있으면 우선 사용"""
        if not HAS_STRUCTURED_RESOLVER or not StructuredContentResolver:
            return None

        try:
            file_name = Path(file_path).name
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
        except Exception:
            return None
