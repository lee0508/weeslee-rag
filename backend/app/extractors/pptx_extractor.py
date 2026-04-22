"""
PPTX Extractor
"""
import os
from typing import Dict, Any, List
from pathlib import Path
from pptx import Presentation

from app.extractors.base import BaseExtractor, ExtractionResult


class PptxExtractor(BaseExtractor):
    """Extracts text from PPTX files"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".pptx", ".ppt"]

    async def extract(self, file_path: str) -> Dict[str, Any]:
        """
        Extract text from PPTX file

        Args:
            file_path: Path to PPTX file

        Returns:
            Extraction result dictionary
        """
        if not os.path.exists(file_path):
            return ExtractionResult(
                success=False,
                error=f"File not found: {file_path}"
            ).to_dict()

        try:
            prs = Presentation(file_path)
            content_parts = []

            for slide_num, slide in enumerate(prs.slides, 1):
                slide_text = [f"--- Slide {slide_num} ---"]

                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_text.append(shape.text)

                    # Extract table content
                    if shape.has_table:
                        table = shape.table
                        for row in table.rows:
                            row_text = [cell.text.strip() for cell in row.cells]
                            slide_text.append(" | ".join(row_text))

                content_parts.append("\n".join(slide_text))

            content = "\n\n".join(content_parts)

            metadata = {
                "source": file_path,
                "filename": Path(file_path).name,
                "slides": len(prs.slides)
            }

            return ExtractionResult(
                success=True,
                content=content,
                metadata=metadata,
                method="python-pptx"
            ).to_dict()

        except Exception as e:
            return ExtractionResult(
                success=False,
                error=str(e),
                method="python-pptx"
            ).to_dict()


# Singleton instance
pptx_extractor = PptxExtractor()
