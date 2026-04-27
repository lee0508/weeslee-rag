"""
HWPX Extractor
"""
import os
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Dict, Any, List, Optional
from xml.etree import ElementTree as ET

from app.extractors.base import BaseExtractor, ExtractionResult


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
