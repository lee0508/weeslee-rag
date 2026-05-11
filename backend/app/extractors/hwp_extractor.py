# HWP(구형 바이너리) 파일에서 텍스트를 추출하는 extractor (pyhwp hwp5txt 사용)
import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any, List

from app.extractors.base import BaseExtractor, ExtractionResult


def _hwp5txt_path() -> str:
    """venv bin 디렉토리에서 hwp5txt 경로를 반환한다."""
    bin_dir = Path(sys.executable).parent
    candidate = bin_dir / "hwp5txt"
    if candidate.exists():
        return str(candidate)
    return "hwp5txt"


class HwpExtractor(BaseExtractor):
    """HWP 바이너리 형식(.hwp) 텍스트 추출기 — pyhwp hwp5txt 사용"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".hwp"]

    async def extract(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            return ExtractionResult(
                success=False,
                error=f"File not found: {file_path}"
            ).to_dict()

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
                ).to_dict()

            metadata = {
                "source": file_path,
                "filename": Path(file_path).name,
                "content_length": len(text),
            }

            return ExtractionResult(
                success=True,
                content=text,
                metadata=metadata,
                method="hwp5txt"
            ).to_dict()

        except subprocess.TimeoutExpired:
            return ExtractionResult(
                success=False,
                error="hwp5txt timed out (>60s)",
                method="hwp5txt"
            ).to_dict()
        except FileNotFoundError:
            return ExtractionResult(
                success=False,
                error="hwp5txt not found. pyhwp 패키지가 설치되어 있는지 확인하세요.",
                method="hwp5txt"
            ).to_dict()
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=str(e),
                method="hwp5txt"
            ).to_dict()
