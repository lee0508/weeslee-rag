"""
OCR API endpoints
"""
import os
import shutil
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.services.ocr import ocr_service
from app.extractors import document_extractor


router = APIRouter(prefix="/ocr", tags=["OCR"])


class OCRResponse(BaseModel):
    success: bool
    content: Optional[str] = None
    format: Optional[str] = None
    method: Optional[str] = None
    error: Optional[str] = None


class ExtractResponse(BaseModel):
    success: bool
    content: Optional[str] = None
    metadata: Optional[dict] = None
    method: Optional[str] = None
    error: Optional[str] = None


class SupportedFormatsResponse(BaseModel):
    extensions: List[str]
    description: dict


@router.get("/formats", response_model=SupportedFormatsResponse)
async def get_supported_formats():
    """Get list of supported file formats"""
    return SupportedFormatsResponse(
        extensions=document_extractor.supported_extensions,
        description={
            ".pdf": "PDF documents (with OCR support for scanned PDFs)",
            ".docx": "Microsoft Word documents",
            ".pptx": "Microsoft PowerPoint presentations",
            ".ppt": "Microsoft PowerPoint presentations (legacy)",
            ".xlsx": "Microsoft Excel spreadsheets",
            ".xls": "Microsoft Excel spreadsheets (legacy)",
            ".png": "PNG images (OCR)",
            ".jpg": "JPEG images (OCR)",
            ".jpeg": "JPEG images (OCR)"
        }
    )


@router.post("/process-pdf", response_model=OCRResponse)
async def process_pdf_ocr(
    file: UploadFile = File(...),
    output_format: str = Query("markdown", enum=["markdown", "text"])
):
    """
    Process a PDF file using OCR

    - **file**: PDF file to process
    - **output_format**: Output format (markdown or text)
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    # Save uploaded file temporarily
    temp_path = os.path.join(settings.upload_dir, f"temp_{file.filename}")
    os.makedirs(settings.upload_dir, exist_ok=True)

    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Process with OCR
        result = await ocr_service.process_pdf(temp_path, output_format)

        return OCRResponse(
            success=result["success"],
            content=result.get("content"),
            format=result.get("format"),
            method="olmocr",
            error=result.get("error")
        )

    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/process-image", response_model=OCRResponse)
async def process_image_ocr(
    file: UploadFile = File(...),
    output_format: str = Query("markdown", enum=["markdown", "text"])
):
    """
    Process an image file using OCR

    - **file**: Image file to process (PNG, JPEG)
    - **output_format**: Output format (markdown or text)
    """
    allowed_extensions = [".png", ".jpg", ".jpeg"]
    ext = os.path.splitext(file.filename.lower())[1]

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File must be an image ({', '.join(allowed_extensions)})"
        )

    # Save uploaded file temporarily
    temp_path = os.path.join(settings.upload_dir, f"temp_{file.filename}")
    os.makedirs(settings.upload_dir, exist_ok=True)

    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Process with OCR
        result = await ocr_service.process_image(temp_path, output_format)

        return OCRResponse(
            success=result["success"],
            content=result.get("content"),
            format=result.get("format"),
            method="olmocr",
            error=result.get("error")
        )

    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/extract", response_model=ExtractResponse)
async def extract_document(
    file: UploadFile = File(...),
    use_ocr: bool = Query(True, description="Use OCR for scanned documents")
):
    """
    Extract text from any supported document format

    - **file**: Document file to process
    - **use_ocr**: Enable OCR for scanned PDFs
    """
    ext = os.path.splitext(file.filename.lower())[1]

    if ext not in document_extractor.supported_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported: {', '.join(document_extractor.supported_extensions)}"
        )

    # Save uploaded file temporarily
    temp_path = os.path.join(settings.upload_dir, f"temp_{file.filename}")
    os.makedirs(settings.upload_dir, exist_ok=True)

    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Extract using unified extractor
        result = await document_extractor.extract(temp_path)

        return ExtractResponse(
            success=result["success"],
            content=result.get("content"),
            metadata=result.get("metadata"),
            method=result.get("method"),
            error=result.get("error")
        )

    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/smart-extract", response_model=OCRResponse)
async def smart_extract(
    file: UploadFile = File(...),
    output_format: str = Query("markdown", enum=["markdown", "text"])
):
    """
    Smart extraction that automatically uses OCR when needed

    - **file**: PDF or image file to process
    - **output_format**: Output format (markdown or text)
    """
    ext = os.path.splitext(file.filename.lower())[1]
    allowed = [".pdf", ".png", ".jpg", ".jpeg"]

    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"File must be PDF or image ({', '.join(allowed)})"
        )

    # Save uploaded file temporarily
    temp_path = os.path.join(settings.upload_dir, f"temp_{file.filename}")
    os.makedirs(settings.upload_dir, exist_ok=True)

    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Use smart extraction
        result = await ocr_service.smart_extract(temp_path, output_format)

        return OCRResponse(
            success=result["success"],
            content=result.get("content"),
            format=result.get("format"),
            method=result.get("method"),
            error=result.get("error")
        )

    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.delete("/cleanup")
async def cleanup_workspace():
    """Clean up OCR workspace directory"""
    try:
        ocr_service.cleanup_workspace()
        return {"success": True, "message": "Workspace cleaned up"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
