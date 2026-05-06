# -*- coding: utf-8 -*-
"""
Secure file serving for RAG result source documents.

Serves files from two allowed roots:
  1. PROJECT_ROOT/data/raw/  — local snapshot copies
  2. knowledge_source_service.root_path — mapped network drive (W:\)
"""
import re
import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter(prefix="/files", tags=["Files"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RAW_DIR = (PROJECT_ROOT / "data" / "raw").resolve()

_WIN_DRIVE_RE = re.compile(r'^[A-Za-z]:[/\\](.+)$', re.DOTALL)

_MIME = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":  "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt":  "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls":  "application/vnd.ms-excel",
    ".hwp":  "application/x-hwp",
    ".hwpx": "application/x-hwpx",
}

def _try_knowledge_root(relative: str) -> Path | None:
    """Resolve a path relative to the knowledge source root (W:\ or UNC share)."""
    from app.services.knowledge_source import knowledge_source_service
    if not knowledge_source_service.is_accessible():
        return None
    root = Path(knowledge_source_service.get_root_path()).resolve()
    try:
        full = (root / relative).resolve()
        full.relative_to(root)  # path traversal check
        if full.is_file():
            return full
    except (ValueError, OSError):
        pass
    return None


def _resolve(source_path: str) -> Path | None:
    """
    Locate a source document on this server.

    Supported path formats stored in FAISS metadata:
    1. Linux absolute:  /data/weeslee/weeslee-rag/data/raw/snapshot_.../file.ext
    2. Windows drive:   W:\\01. 국내사업폴더\\...\\file.pdf
    3. UNC:             \\\\diskstation\\W2_프로젝트폴더\\...\\file.pdf
    4. Relative:        snapshot_.../file.ext  (resolved under data/raw/)
    """
    p = source_path.strip()
    if not p:
        return None

    # Linux absolute path — must be within data/raw/
    if p.startswith('/'):
        try:
            resolved = Path(p).resolve()
            if resolved.is_file():
                resolved.relative_to(_RAW_DIR)
                return resolved
        except (ValueError, OSError):
            pass

    # Windows drive-letter path: W:\path\to\file  or  C:/path/to/file
    m = _WIN_DRIVE_RE.match(p)
    if m:
        relative = m.group(1).replace('\\', '/')
        return _try_knowledge_root(relative)

    # UNC path: \\server\share\path\to\file
    if p.startswith('\\\\') or p.startswith('//'):
        stripped = p.lstrip('/\\')
        sep = '\\' if '\\' in stripped else '/'
        parts = stripped.split(sep, 2)  # [server, share, rest]
        if len(parts) >= 3:
            return _try_knowledge_root(parts[2])

    # Relative path within data/raw/
    try:
        resolved = (_RAW_DIR / p).resolve()
        if resolved.is_file():
            resolved.relative_to(_RAW_DIR)
            return resolved
    except (ValueError, OSError):
        pass

    return None


@router.get("/info")
async def file_info(path: str = Query(..., description="source_path from RAG result")):
    """Return metadata for a source document without serving the bytes."""
    resolved = _resolve(path)
    if not resolved:
        raise HTTPException(status_code=404, detail="File not found on server")
    stat = resolved.stat()
    return {
        "name": resolved.name,
        "extension": resolved.suffix.lower(),
        "size": stat.st_size,
        "accessible": True,
    }


@router.get("/download")
async def download_file(path: str = Query(..., description="source_path from RAG result")):
    """
    Serve a source document as an attachment (forced download for all formats).
    """
    resolved = _resolve(path)
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail=f"File not found on server. Verify the file was copied to data/raw/: {path}",
        )

    ext = resolved.suffix.lower()
    media_type = _MIME.get(ext) or mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    disposition = "attachment"

    # RFC 5987 encoding keeps Korean/Unicode filenames intact across browsers
    encoded_name = quote(resolved.name, safe="")
    headers = {
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_name}",
        "Cache-Control": "no-store",
    }

    return FileResponse(path=str(resolved), media_type=media_type, headers=headers)
