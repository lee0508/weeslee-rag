"""
OCR Service using olmOCR
Converts scanned PDFs and images to markdown/text
"""
import os
import tempfile
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx

from app.core.config import settings


class OCRService:
    """Service for OCR processing using olmOCR"""

    def __init__(self, workspace_dir: Optional[str] = None):
        """
        Initialize OCR service

        Args:
            workspace_dir: Directory for OCR processing workspace
        """
        self.workspace_dir = workspace_dir or os.path.join(
            settings.upload_dir, "ocr_workspace"
        )
        os.makedirs(self.workspace_dir, exist_ok=True)

    async def process_pdf(
        self,
        pdf_path: str,
        output_format: str = "markdown"
    ) -> Dict[str, Any]:
        """
        Process a PDF file using olmOCR

        Args:
            pdf_path: Path to the PDF file
            output_format: Output format ('markdown' or 'text')

        Returns:
            Dictionary with extracted content and metadata
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Create a unique workspace for this file
        file_name = Path(pdf_path).stem
        work_dir = os.path.join(self.workspace_dir, file_name)
        os.makedirs(work_dir, exist_ok=True)

        try:
            # Run olmocr command
            cmd = [
                "olmocr",
                work_dir,
                "--markdown" if output_format == "markdown" else "--text",
                "--pdfs", pdf_path
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return {
                    "success": False,
                    "error": stderr.decode("utf-8"),
                    "content": None
                }

            # Read the output file
            output_ext = ".md" if output_format == "markdown" else ".txt"
            output_file = os.path.join(work_dir, f"{file_name}{output_ext}")

            content = ""
            if os.path.exists(output_file):
                with open(output_file, "r", encoding="utf-8") as f:
                    content = f.read()

            return {
                "success": True,
                "content": content,
                "format": output_format,
                "source_file": pdf_path,
                "output_file": output_file
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "content": None
            }

    async def process_image(
        self,
        image_path: str,
        output_format: str = "markdown"
    ) -> Dict[str, Any]:
        """
        Process an image file using olmOCR

        Args:
            image_path: Path to the image file (PNG, JPEG)
            output_format: Output format ('markdown' or 'text')

        Returns:
            Dictionary with extracted content and metadata
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # Create a unique workspace for this file
        file_name = Path(image_path).stem
        work_dir = os.path.join(self.workspace_dir, file_name)
        os.makedirs(work_dir, exist_ok=True)

        try:
            # For images, we need to specify the input differently
            cmd = [
                "olmocr",
                work_dir,
                "--markdown" if output_format == "markdown" else "--text",
                "--images", image_path
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return {
                    "success": False,
                    "error": stderr.decode("utf-8"),
                    "content": None
                }

            # Read the output file
            output_ext = ".md" if output_format == "markdown" else ".txt"
            output_file = os.path.join(work_dir, f"{file_name}{output_ext}")

            content = ""
            if os.path.exists(output_file):
                with open(output_file, "r", encoding="utf-8") as f:
                    content = f.read()

            return {
                "success": True,
                "content": content,
                "format": output_format,
                "source_file": image_path,
                "output_file": output_file
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "content": None
            }

    async def process_batch(
        self,
        file_paths: List[str],
        output_format: str = "markdown"
    ) -> List[Dict[str, Any]]:
        """
        Process multiple files in batch

        Args:
            file_paths: List of file paths (PDFs or images)
            output_format: Output format ('markdown' or 'text')

        Returns:
            List of results for each file
        """
        results = []

        for file_path in file_paths:
            ext = Path(file_path).suffix.lower()

            if ext == ".pdf":
                result = await self.process_pdf(file_path, output_format)
            elif ext in [".png", ".jpg", ".jpeg"]:
                result = await self.process_image(file_path, output_format)
            else:
                result = {
                    "success": False,
                    "error": f"Unsupported file format: {ext}",
                    "content": None,
                    "source_file": file_path
                }

            results.append(result)

        return results

    def is_scanned_pdf(self, pdf_path: str) -> bool:
        """
        Check if a PDF is scanned (image-based) or text-based

        Args:
            pdf_path: Path to the PDF file

        Returns:
            True if the PDF appears to be scanned, False otherwise
        """
        try:
            import pdfplumber

            with pdfplumber.open(pdf_path) as pdf:
                # Check first few pages
                for i, page in enumerate(pdf.pages[:3]):
                    text = page.extract_text()
                    if text and len(text.strip()) > 50:
                        # Has substantial text, likely not scanned
                        return False

                # No text found, likely scanned
                return True

        except Exception:
            # If we can't determine, assume it might be scanned
            return True

    async def smart_extract(
        self,
        file_path: str,
        output_format: str = "markdown"
    ) -> Dict[str, Any]:
        """
        Smart extraction that uses OCR only when needed

        Args:
            file_path: Path to the file
            output_format: Output format

        Returns:
            Extracted content with metadata
        """
        ext = Path(file_path).suffix.lower()

        if ext == ".pdf":
            # Check if OCR is needed
            if self.is_scanned_pdf(file_path):
                return await self.process_pdf(file_path, output_format)
            else:
                # Use regular text extraction
                try:
                    import pdfplumber

                    content = ""
                    with pdfplumber.open(file_path) as pdf:
                        for page in pdf.pages:
                            text = page.extract_text()
                            if text:
                                content += text + "\n\n"

                    return {
                        "success": True,
                        "content": content,
                        "format": "text",
                        "source_file": file_path,
                        "method": "pdfplumber"
                    }
                except Exception as e:
                    # Fall back to OCR
                    return await self.process_pdf(file_path, output_format)

        elif ext in [".png", ".jpg", ".jpeg"]:
            return await self.process_image(file_path, output_format)

        else:
            return {
                "success": False,
                "error": f"Unsupported file format: {ext}",
                "content": None
            }

    def cleanup_workspace(self, file_name: Optional[str] = None):
        """
        Clean up workspace directory

        Args:
            file_name: Specific file workspace to clean, or None for all
        """
        import shutil

        if file_name:
            work_dir = os.path.join(self.workspace_dir, file_name)
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir)
        else:
            if os.path.exists(self.workspace_dir):
                shutil.rmtree(self.workspace_dir)
                os.makedirs(self.workspace_dir, exist_ok=True)


# Singleton instance
ocr_service = OCRService()
