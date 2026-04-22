# -*- coding: utf-8 -*-
"""
Knowledge Sources API endpoints
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.knowledge_source import knowledge_source_service


router = APIRouter(prefix="/knowledge-sources", tags=["Knowledge Sources"])


class FolderInfo(BaseModel):
    name: str
    path: str
    full_path: str
    modified: str


class FileInfo(BaseModel):
    name: str
    path: str
    relative_path: str
    extension: str
    type: str
    size: int
    modified: str


class ScanSummary(BaseModel):
    total_files: int
    total_folders: int
    by_type: dict


class ScanResult(BaseModel):
    path: str
    full_path: str
    files: List[dict]
    folders: List[dict]
    summary: ScanSummary


class StatsResponse(BaseModel):
    root_path: str
    accessible: bool
    total_files: int
    total_folders: int
    total_size: int
    total_size_human: str
    by_type: dict


@router.get("/status")
async def get_status():
    """Check if knowledge source is accessible"""
    accessible = knowledge_source_service.is_accessible()
    return {
        "accessible": accessible,
        "root_path": knowledge_source_service.get_root_path()
    }


@router.get("/folders", response_model=List[FolderInfo])
async def list_folders(
    subpath: str = Query("", description="Subpath relative to root")
):
    """
    List folders in the knowledge source

    - **subpath**: Relative path within the knowledge source
    """
    if not knowledge_source_service.is_accessible():
        raise HTTPException(
            status_code=503,
            detail="Knowledge source is not accessible"
        )

    folders = knowledge_source_service.list_folders(subpath)
    return folders


@router.get("/scan", response_model=ScanResult)
async def scan_folder(
    subpath: str = Query("", description="Subpath to scan"),
    recursive: bool = Query(False, description="Scan subdirectories"),
    max_depth: int = Query(3, ge=1, le=10, description="Maximum recursion depth")
):
    """
    Scan a folder for supported documents

    - **subpath**: Relative path to scan
    - **recursive**: Whether to scan subdirectories
    - **max_depth**: Maximum depth for recursive scanning
    """
    if not knowledge_source_service.is_accessible():
        raise HTTPException(
            status_code=503,
            detail="Knowledge source is not accessible"
        )

    result = knowledge_source_service.scan_folder(subpath, recursive, max_depth)
    return result


@router.get("/search", response_model=List[FileInfo])
async def search_files(
    q: str = Query(..., min_length=2, description="Search query"),
    subpath: str = Query("", description="Subpath to search in"),
    extensions: Optional[str] = Query(None, description="Comma-separated extensions (e.g., .pdf,.docx)"),
    max_results: int = Query(100, ge=1, le=500, description="Maximum results")
):
    """
    Search for files by name

    - **q**: Search query (case-insensitive)
    - **subpath**: Limit search to this subpath
    - **extensions**: Filter by file extensions
    - **max_results**: Maximum number of results
    """
    if not knowledge_source_service.is_accessible():
        raise HTTPException(
            status_code=503,
            detail="Knowledge source is not accessible"
        )

    ext_list = None
    if extensions:
        ext_list = [ext.strip().lower() for ext in extensions.split(",")]
        # Ensure extensions start with dot
        ext_list = [ext if ext.startswith(".") else f".{ext}" for ext in ext_list]

    results = knowledge_source_service.search_files(q, subpath, ext_list, max_results)
    return results


@router.get("/file")
async def get_file_info(
    path: str = Query(..., description="Relative path to the file")
):
    """
    Get detailed information about a specific file

    - **path**: Relative path to the file
    """
    if not knowledge_source_service.is_accessible():
        raise HTTPException(
            status_code=503,
            detail="Knowledge source is not accessible"
        )

    info = knowledge_source_service.get_file_info(path)

    if not info:
        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    if not info.get("accessible", True):
        raise HTTPException(
            status_code=403,
            detail=f"Cannot access file: {info.get('error', 'Unknown error')}"
        )

    return info


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """
    Get statistics about the knowledge source

    Note: This may take a while for large directories
    """
    if not knowledge_source_service.is_accessible():
        return StatsResponse(
            root_path=knowledge_source_service.get_root_path(),
            accessible=False,
            total_files=0,
            total_folders=0,
            total_size=0,
            total_size_human="0 B",
            by_type={}
        )

    stats = knowledge_source_service.get_stats()
    return stats


@router.get("/supported-types")
async def get_supported_types():
    """Get list of supported file types"""
    return {
        "extensions": knowledge_source_service.SUPPORTED_EXTENSIONS
    }
