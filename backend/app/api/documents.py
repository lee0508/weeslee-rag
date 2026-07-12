# 문서 상세 조회와 파생 파일 다운로드를 제공하는 API
"""
Document management API endpoints.
"""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.collection import Collection
from app.models.document import Document, DocumentStatus, FileType, ProcessingLog
from app.services.metadata_db import metadata_db_service
from app.services.processed_text_store import processed_text_store

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
EXTRACTED_TEXT_DIR = DATA_DIR / "extracted_text"
STAGED_TEXT_DIR = DATA_DIR / "staged" / "text"
STAGED_METADATA_DIR = DATA_DIR / "staged" / "metadata"
SUMMARIES_DIR = DATA_DIR / "summaries"

_MIME = {
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".hwp": "application/x-hwp",
    ".hwpx": "application/x-hwpx",
}


class DocumentResponse(BaseModel):
    id: int
    collection_id: int
    filename: str
    file_type: str
    file_size: Optional[int]
    status: str
    error_message: Optional[str]
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    total: int
    items: list[DocumentResponse]


class ProcessingStatusResponse(BaseModel):
    id: int
    filename: str
    status: str
    progress: int
    message: Optional[str]


class DocumentEditRequest(BaseModel):
    markdown: Optional[str] = None
    summary: Optional[str] = None


def _settings_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    relative = path_value[2:] if path_value.startswith("./") else path_value
    return (PROJECT_ROOT / "backend" / relative).resolve()


def _upload_metadata_dir() -> Path:
    return _settings_path(settings.upload_dir) / "metadata"


def get_file_type(filename: str) -> Optional[FileType]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    type_map = {
        "ppt": FileType.PPT,
        "pptx": FileType.PPTX,
        "doc": FileType.DOC,
        "docx": FileType.DOCX,
        "hwp": FileType.HWP,
        "hwpx": FileType.HWPX,
        "pdf": FileType.PDF,
        "xlsx": FileType.XLSX,
    }
    return type_map.get(ext)


def _read_text(path: Path) -> Optional[str]:
    if not path or not path.is_file():
        return None
    encodings = ("utf-8", "utf-8-sig", "cp949")
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _find_metadata_file(document_id: int) -> Optional[Path]:
    patterns = (f"{document_id}_*_meta.json", f"{document_id}.json")
    for base_dir in (_upload_metadata_dir(), STAGED_METADATA_DIR):
        if not base_dir.exists():
            continue
        for pattern in patterns:
            matches = sorted(base_dir.glob(pattern))
            if matches:
                return matches[0]
    return None


def _load_metadata_payload(document_id: int) -> dict[str, Any]:
    file_path = _find_metadata_file(document_id)
    if not file_path:
        return {}
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _content_path(document_id: int, name: str) -> Path:
    return EXTRACTED_TEXT_DIR / str(document_id) / name


def _summary_path(document_id: int) -> Path:
    return SUMMARIES_DIR / str(document_id) / "summary.md"


def _raw_text_path(document_id: int) -> Path:
    return EXTRACTED_TEXT_DIR / str(document_id) / "raw_text.txt"


def _text_path(document_id: int) -> Path:
    return STAGED_TEXT_DIR / f"{document_id}.txt"


def _processed_text_path(document_id: int, format: str = "txt", source_id: str = "") -> Path:
    """처리된 텍스트 파일 경로 반환.

    source_id가 있으면 Source별 Step 2 추출 경로를 우선 사용한다.
    """
    file_name = "full_text.md" if format == "md" else "full_text.txt"

    source_path = _source_document_file(source_id, document_id, file_name)
    if source_path:
        return source_path

    # 2. 기존 전역 경로
    canonical = DATA_DIR / "documents" / str(document_id) / "ocr" / file_name
    if canonical.is_file():
        return canonical
    return DATA_DIR / "processed_text" / str(document_id) / file_name


def _source_document_file(source_id: str, document_id: int, file_name: str) -> Optional[Path]:
    """Source별 문서 산출물의 현재 및 이전 호환 경로를 찾는다."""
    if not source_id:
        return None

    source_root = DATA_DIR / "source" / str(source_id)
    candidates = (
        source_root / "documents" / str(document_id) / file_name,
        source_root / "step2_extract" / "documents" / str(document_id) / file_name,
    )
    return next((path for path in candidates if path.is_file()), None)


def _load_chunks_from_active_index(document_id: int) -> Optional[str]:
    """활성 FAISS 인덱스의 chunks.jsonl에서 document_id로 청크를 검색하여 텍스트 재구성.

    [2026-07-13] 텍스트 파일이 없을 때 fallback으로 사용.
    """
    try:
        # 활성 인덱스 디렉토리 찾기
        indexes_dir = DATA_DIR / "indexes" / "faiss"
        if not indexes_dir.exists():
            return None

        # active.json에서 활성 스냅샷 확인
        active_file = indexes_dir / "active.json"
        if active_file.exists():
            with open(active_file, "r", encoding="utf-8") as f:
                active_info = json.load(f)
                active_snapshot = active_info.get("snapshot_id", "")
                if active_snapshot:
                    chunks_path = indexes_dir / active_snapshot / "chunks.jsonl"
                    if chunks_path.exists():
                        return _extract_text_from_chunks_jsonl(chunks_path, document_id)

        # active.json이 없으면 가장 최근 스냅샷 폴더에서 찾기
        for snapshot_dir in sorted(indexes_dir.iterdir(), reverse=True):
            if snapshot_dir.is_dir() and snapshot_dir.name.startswith("snapshot_"):
                chunks_path = snapshot_dir / "chunks.jsonl"
                if chunks_path.exists():
                    result = _extract_text_from_chunks_jsonl(chunks_path, document_id)
                    if result:
                        return result

    except Exception:
        pass
    return None


def _extract_text_from_chunks_jsonl(chunks_path: Path, document_id: int) -> Optional[str]:
    """chunks.jsonl에서 특정 document_id의 청크 텍스트를 추출."""
    try:
        chunk_texts = []
        doc_id_str = str(document_id)
        with open(chunks_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if str(chunk.get("document_id", "")) == doc_id_str:
                    text = chunk.get("text", "")
                    if text:
                        chunk_texts.append(text)
        if chunk_texts:
            return "\n\n".join(chunk_texts)
    except Exception:
        pass
    return None


def _build_text(document_id: int, source_id: str = "") -> tuple[str, str, Optional[Path]]:
    """텍스트 파일 내용을 빌드한다.

    [2026-07-12] source_id 파라미터 추가 - 통합 경로 구조 지원.
    """
    # 1. Source별 Step 2 추출 결과 또는 이전 호환 경로
    source_txt = _source_document_file(source_id, document_id, "full_text.txt")
    if source_txt:
        text = _read_text(source_txt)
        if text is not None:
            return text, "source_extract", source_txt

    raw_text_path = _raw_text_path(document_id)
    raw_text = _read_text(raw_text_path)
    if raw_text is not None:
        return raw_text, "file", raw_text_path

    staged_text_path = _text_path(document_id)
    staged_text = _read_text(staged_text_path)
    if staged_text is not None:
        return staged_text, "staged_text", staged_text_path

    processed_text = processed_text_store.get_text(str(document_id), format="txt")
    if processed_text is not None:
        processed_path = _processed_text_path(document_id, "txt", source_id)
        return processed_text, "processed_text", processed_path if processed_path.exists() else None

    # [2026-07-13] fallback: 청크 데이터에서 텍스트 재구성
    chunks = processed_text_store.load_chunks(document_id)
    if chunks:
        chunk_texts = [c.get("text", "") for c in chunks if c.get("text")]
        if chunk_texts:
            reconstructed = "\n\n".join(chunk_texts)
            return reconstructed, "chunks_reconstructed", None

    # [2026-07-13] fallback 2: 활성 FAISS 인덱스의 chunks.jsonl에서 검색
    chunks_from_index = _load_chunks_from_active_index(document_id)
    if chunks_from_index:
        return chunks_from_index, "index_chunks_reconstructed", None

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Text file not found")


def _download_filename(base_name: str, suffix: str) -> str:
    stem = Path(base_name).stem or "document"
    return f"{stem}{suffix}"


def _document_from_sqlalchemy(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "file_name": document.filename,
        "file_path": document.original_path,
        "file_type": document.file_type.value if hasattr(document.file_type, "value") else str(document.file_type),
        "file_size": document.file_size,
        "status": document.status.value if hasattr(document.status, "value") else str(document.status),
        "summary": "",
        "chunk_count": document.chunk_count,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
    }


def _load_document_from_faiss_metadata(document_id: int) -> Optional[dict[str, Any]]:
    """FAISS 인덱스 메타데이터에서 문서 정보 조회.

    [2026-07-13] RAG 검색 결과의 document_id로 문서를 찾지 못할 때 fallback.
    """
    try:
        # 활성 인덱스 디렉토리 찾기
        indexes_dir = DATA_DIR / "indexes" / "faiss"
        if not indexes_dir.exists():
            return None

        # active.json에서 활성 스냅샷 확인
        active_snapshot = None
        active_file = indexes_dir / "active.json"
        if active_file.exists():
            with open(active_file, "r", encoding="utf-8") as f:
                active_info = json.load(f)
                active_snapshot = active_info.get("snapshot_id", "")

        # 메타데이터 파일 검색
        snapshot_dirs = []
        if active_snapshot:
            snapshot_dirs.append(indexes_dir / active_snapshot)
        # 최신 스냅샷부터 검색
        for d in sorted(indexes_dir.iterdir(), reverse=True):
            if d.is_dir() and d.name.startswith("snapshot_") and d not in snapshot_dirs:
                snapshot_dirs.append(d)

        doc_id_str = str(document_id)
        for snapshot_dir in snapshot_dirs:
            # metadata.jsonl 검색
            metadata_path = snapshot_dir / "metadata.jsonl"
            if metadata_path.exists():
                with open(metadata_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        meta = json.loads(line)
                        if str(meta.get("document_id", "")) == doc_id_str:
                            return {
                                "id": document_id,
                                "file_name": meta.get("filename") or meta.get("file_name", ""),
                                "file_path": meta.get("source_path") or meta.get("file_path", ""),
                                "source_path": meta.get("source_path", ""),
                                "source_id": meta.get("source_id", ""),
                                "file_type": meta.get("file_type", ""),
                                "summary": meta.get("summary", ""),
                                "chunk_count": meta.get("chunk_count", 0),
                            }

            # chunks.jsonl에서 첫 번째 청크 메타데이터 사용
            chunks_path = snapshot_dir / "chunks.jsonl"
            if chunks_path.exists():
                with open(chunks_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if str(chunk.get("document_id", "")) == doc_id_str:
                            return {
                                "id": document_id,
                                "file_name": chunk.get("filename") or chunk.get("file_name", ""),
                                "file_path": chunk.get("source_path") or chunk.get("file_path", ""),
                                "source_path": chunk.get("source_path", ""),
                                "source_id": chunk.get("source_id", ""),
                                "file_type": chunk.get("file_type", ""),
                                "summary": "",
                                "chunk_count": 0,
                            }
    except Exception:
        pass
    return None


def _resolve_document(document_id: int, db: Session) -> tuple[dict[str, Any], Optional[Document]]:
    metadata_doc = metadata_db_service.get_document(document_id)
    orm_doc = db.query(Document).filter(Document.id == document_id).first()
    if metadata_doc:
        return metadata_doc, orm_doc
    if orm_doc:
        return _document_from_sqlalchemy(orm_doc), orm_doc

    # [2026-07-13] fallback: FAISS 인덱스 메타데이터에서 조회
    faiss_doc = _load_document_from_faiss_metadata(document_id)
    if faiss_doc:
        return faiss_doc, None

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")


def _resolve_original_path(record: dict[str, Any], orm_doc: Optional[Document]) -> Optional[Path]:
    candidates = [
        record.get("file_path"),
        record.get("original_path"),
        orm_doc.original_path if orm_doc else None,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate))
        if path.is_file():
            return path
        if not path.is_absolute():
            resolved = (PROJECT_ROOT / "backend" / path).resolve()
            if resolved.is_file():
                return resolved
            resolved = (PROJECT_ROOT / path).resolve()
            if resolved.is_file():
                return resolved
        elif path.is_file():
            return path
    return None


def _build_markdown(document_id: int, record: dict[str, Any], metadata_payload: dict[str, Any]) -> tuple[str, str, Optional[Path]]:
    """마크다운 파일 내용을 빌드한다.

    [2026-07-12] 통합 경로 구조 지원 추가.
    """
    source_id = record.get("source_id") or ""

    # 1. Source별 Step 2 추출 결과 또는 이전 호환 경로
    source_md = _source_document_file(source_id, document_id, "full_text.md")
    if source_md:
        md_text = _read_text(source_md)
        if md_text is not None:
            return md_text, "source_extract", source_md

    markdown_path = _content_path(document_id, "document.md")
    markdown = _read_text(markdown_path)
    if markdown is not None:
        return markdown, "file", markdown_path

    processed_markdown = processed_text_store.get_text(str(document_id), format="md")
    if processed_markdown is not None:
        processed_path = _processed_text_path(document_id, "md", source_id)
        return processed_markdown, "processed_text_md", processed_path if processed_path.exists() else None

    try:
        raw_text, source, text_path = _build_text(document_id, source_id)
        return raw_text, f"generated_from_{source}", text_path
    except HTTPException:
        pass

    summary = record.get("summary") or metadata_payload.get("summary") or ""
    if summary:
        content = f"# {record.get('project_name') or record.get('file_name') or f'Document {document_id}'}\n\n{summary}"
        return content, "generated_from_summary", None

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Markdown not found")


def _build_html(document_id: int, record: dict[str, Any], metadata_payload: dict[str, Any]) -> tuple[str, str, Optional[Path]]:
    """HTML 파일 내용을 빌드한다.

    [2026-07-13] 통합 경로 구조 지원 추가.
    """
    source_id = record.get("source_id") or ""

    # 1. Source별 Step 2 추출 결과 또는 이전 호환 경로
    source_html = _source_document_file(source_id, document_id, "full_text.html")
    if source_html:
        html_text = _read_text(source_html)
        if html_text is not None:
            return html_text, "source_extract", source_html

    html_path = _content_path(document_id, "document.html")
    html = _read_text(html_path)
    if html is not None:
        return html, "file", html_path

    markdown, source, source_path = _build_markdown(document_id, record, metadata_payload)
    html = f"<html><body><pre>{escape(markdown)}</pre></body></html>"
    return html, f"generated_from_{source}", source_path


def _build_summary(document_id: int, record: dict[str, Any], metadata_payload: dict[str, Any]) -> tuple[str, str, Optional[Path]]:
    summary_path = _summary_path(document_id)
    summary = _read_text(summary_path)
    if summary is not None:
        return summary, "file", summary_path

    summary_text = record.get("summary") or metadata_payload.get("summary") or ""
    if summary_text:
        return summary_text, "generated_from_metadata", None

    markdown, source, source_path = _build_markdown(document_id, record, metadata_payload)
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    generated = "\n".join(lines[:3]).strip()
    if generated:
        return generated, f"generated_from_{source}", source_path

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found")


def _available_formats(document_id: int, record: dict[str, Any], orm_doc: Optional[Document], metadata_payload: dict[str, Any]) -> dict[str, bool]:
    """사용 가능한 포맷 확인.

    [2026-07-13] 통합 경로 구조 지원 추가.
    """
    original_path = _resolve_original_path(record, orm_doc)
    metadata_path = _find_metadata_file(document_id)
    summary_text = record.get("summary") or metadata_payload.get("summary")
    processed_txt_exists = processed_text_store.get_text(str(document_id), format="txt") is not None
    processed_md_exists = processed_text_store.get_text(str(document_id), format="md") is not None

    # Source별 Step 2 추출 결과와 이전 호환 경로 확인
    source_id = record.get("source_id") or ""
    source_txt_exists = _source_document_file(source_id, document_id, "full_text.txt") is not None
    source_md_exists = _source_document_file(source_id, document_id, "full_text.md") is not None
    source_html_exists = _source_document_file(source_id, document_id, "full_text.html") is not None

    return {
        "original": original_path is not None,
        "txt": source_txt_exists or _raw_text_path(document_id).is_file() or _text_path(document_id).is_file() or processed_txt_exists,
        "md": source_md_exists or _content_path(document_id, "document.md").is_file() or _raw_text_path(document_id).is_file() or _text_path(document_id).is_file() or processed_txt_exists or processed_md_exists or bool(summary_text),
        "html": source_html_exists or source_md_exists or _content_path(document_id, "document.html").is_file() or _content_path(document_id, "document.md").is_file() or _raw_text_path(document_id).is_file() or _text_path(document_id).is_file() or processed_txt_exists or processed_md_exists or bool(summary_text),
        "summary": _summary_path(document_id).is_file() or bool(summary_text),
        "json": metadata_path is not None or bool(metadata_payload),
        "docx": original_path is not None and original_path.suffix.lower() == ".docx",
        "hwpx": original_path is not None and original_path.suffix.lower() == ".hwpx",
    }


def _document_detail_payload(
    document_id: int,
    record: dict[str, Any],
    orm_doc: Optional[Document],
    include_content: bool = False,
) -> dict[str, Any]:
    metadata_payload = _load_metadata_payload(document_id)
    original_path = _resolve_original_path(record, orm_doc)
    summary_text = _read_text(_summary_path(document_id)) or record.get("summary") or metadata_payload.get("summary") or ""
    suggestion = metadata_db_service.get_suggestion(document_id)
    text_path = _text_path(document_id)
    if not text_path.is_file():
        processed_path = _processed_text_path(document_id, "txt")
        if processed_path.is_file():
            text_path = processed_path

    payload = {
        "document_id": document_id,
        "id": document_id,
        "file_name": record.get("file_name") or record.get("filename") or (original_path.name if original_path else ""),
        "file_path": record.get("file_path") or record.get("original_path") or (str(original_path) if original_path else ""),
        "file_type": record.get("file_type") or (original_path.suffix.lstrip(".") if original_path else ""),
        "file_size": record.get("file_size"),
        "status": record.get("status"),
        "meta_status": record.get("meta_status"),
        "project_name": record.get("project_name"),
        "organization": record.get("organization"),
        "project_year": record.get("project_year"),
        "business_domain": record.get("business_domain"),
        "chunk_count": record.get("chunk_count") or (orm_doc.chunk_count if orm_doc else 0),
        "summary": summary_text,
        "html_path": str(_content_path(document_id, "document.html")),
        "markdown_path": str(_content_path(document_id, "document.md")),
        "summary_path": str(_summary_path(document_id)),
        "text_path": str(text_path),
        "metadata_path": str(_find_metadata_file(document_id) or ""),
        "available_formats": _available_formats(document_id, record, orm_doc, metadata_payload),
        "metadata": metadata_payload,
        "suggestion": suggestion,
        "download_urls": {
            fmt: f"/api/documents/{document_id}/download?format={fmt}"
            for fmt in ("original", "txt", "md", "html", "summary", "json", "docx", "hwpx")
        },
    }
    if include_content:
        try:
            raw_text, _, text_path = _build_text(document_id)
        except HTTPException:
            raw_text = ""
        payload["raw_text"] = raw_text
        payload["text_path"] = str(text_path)
    return payload


def _attachment_headers(filename: str) -> dict[str, str]:
    encoded_name = quote(filename, safe="")
    return {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        "Cache-Control": "no-store",
    }


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    collection_id: Optional[int] = None,
    status: Optional[str] = None,
    file_type: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    query = db.query(Document)

    if collection_id:
        query = query.filter(Document.collection_id == collection_id)
    if status:
        query = query.filter(Document.status == status)
    if file_type:
        query = query.filter(Document.file_type == file_type)
    if search:
        query = query.filter(Document.filename.ilike(f"%{search}%"))

    total = query.count()
    items = query.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()
    return DocumentListResponse(total=total, items=items)


@router.post("/documents/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    collection_id: int = Form(...),
    auto_process: bool = Form(True),
    db: Session = Depends(get_db),
):
    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    file_type = get_file_type(file.filename)
    if not file_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Supported: ppt, pptx, doc, docx, hwp, hwpx, pdf, xlsx",
        )

    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > settings.max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {settings.max_upload_size / 1024 / 1024}MB",
        )

    upload_dir = os.path.join(settings.upload_dir, str(collection_id))
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    document = Document(
        collection_id=collection_id,
        filename=file.filename,
        original_path=file_path,
        file_type=file_type,
        file_size=file_size,
        status=DocumentStatus.PENDING,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    collection.document_count += 1
    db.commit()

    if auto_process:
        pass

    return document


@router.get("/documents/{document_id}")
async def get_document(document_id: int, db: Session = Depends(get_db)):
    record, orm_doc = _resolve_document(document_id, db)
    return _document_detail_payload(document_id, record, orm_doc)


@router.get("/documents/{document_id}/text")
async def get_document_text(document_id: int, db: Session = Depends(get_db)):
    record, orm_doc = _resolve_document(document_id, db)
    metadata_payload = _load_metadata_payload(document_id)
    source_id = record.get("source_id") or ""
    text, source, _ = _build_text(document_id, source_id)
    return {
        "document_id": document_id,
        "text": text,
        "source": source,
        "available_formats": _available_formats(document_id, record, orm_doc, metadata_payload),
    }


@router.get("/documents/{document_id}/html")
async def get_document_html(document_id: int, db: Session = Depends(get_db)):
    record, orm_doc = _resolve_document(document_id, db)
    metadata_payload = _load_metadata_payload(document_id)
    html, source, _ = _build_html(document_id, record, metadata_payload)
    return {
        "document_id": document_id,
        "html": html,
        "source": source,
        "available_formats": _available_formats(document_id, record, orm_doc, metadata_payload),
    }


@router.get("/documents/{document_id}/markdown")
async def get_document_markdown(document_id: int, db: Session = Depends(get_db)):
    record, orm_doc = _resolve_document(document_id, db)
    metadata_payload = _load_metadata_payload(document_id)
    markdown, source, _ = _build_markdown(document_id, record, metadata_payload)
    return {
        "document_id": document_id,
        "markdown": markdown,
        "source": source,
        "available_formats": _available_formats(document_id, record, orm_doc, metadata_payload),
    }


@router.get("/documents/{document_id}/summary")
async def get_document_summary(document_id: int, db: Session = Depends(get_db)):
    record, orm_doc = _resolve_document(document_id, db)
    metadata_payload = _load_metadata_payload(document_id)
    summary, source, _ = _build_summary(document_id, record, metadata_payload)
    return {
        "document_id": document_id,
        "summary": summary,
        "source": source,
        "available_formats": _available_formats(document_id, record, orm_doc, metadata_payload),
    }


@router.post("/documents/{document_id}/edit")
async def edit_document(document_id: int, payload: DocumentEditRequest, db: Session = Depends(get_db)):
    record, _ = _resolve_document(document_id, db)
    updated = []

    if payload.markdown is not None:
        _write_text(_content_path(document_id, "document.md"), payload.markdown)
        updated.append("markdown")

    if payload.summary is not None:
        _write_text(_summary_path(document_id), payload.summary)
        metadata_db_service.update_document(document_id, {"summary": payload.summary})
        updated.append("summary")

    if not updated:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No editable content provided")

    return {
        "success": True,
        "document_id": document_id,
        "updated": updated,
        "file_name": record.get("file_name") or record.get("filename") or "",
    }


@router.get("/documents/{document_id}/download")
async def download_document(document_id: int, format: str, db: Session = Depends(get_db)):
    requested = format.lower().strip()
    record, orm_doc = _resolve_document(document_id, db)
    metadata_payload = _load_metadata_payload(document_id)
    file_name = record.get("file_name") or record.get("filename") or f"document-{document_id}"
    original_path = _resolve_original_path(record, orm_doc)

    if requested == "original":
        if not original_path:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Original file not found")
        headers = _attachment_headers(original_path.name)
        media_type = _MIME.get(original_path.suffix.lower()) or mimetypes.guess_type(original_path.name)[0] or "application/octet-stream"
        return FileResponse(path=str(original_path), media_type=media_type, headers=headers)

    if requested == "txt":
        text, _, _ = _build_text(document_id, record.get("source_id") or "")
        return Response(content=text, media_type=_MIME[".txt"], headers=_attachment_headers(_download_filename(file_name, ".txt")))

    if requested == "md":
        markdown, _, _ = _build_markdown(document_id, record, metadata_payload)
        return Response(content=markdown, media_type=_MIME[".md"], headers=_attachment_headers(_download_filename(file_name, ".md")))

    if requested == "html":
        html, _, _ = _build_html(document_id, record, metadata_payload)
        return Response(content=html, media_type=_MIME[".html"], headers=_attachment_headers(_download_filename(file_name, ".html")))

    if requested == "summary":
        summary, _, _ = _build_summary(document_id, record, metadata_payload)
        return Response(content=summary, media_type=_MIME[".md"], headers=_attachment_headers(_download_filename(file_name, "-summary.md")))

    if requested == "json":
        payload = _document_detail_payload(document_id, record, orm_doc, include_content=True)
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type=_MIME[".json"],
            headers=_attachment_headers(_download_filename(file_name, ".json")),
        )

    if requested in {"docx", "hwpx"}:
        if not original_path or original_path.suffix.lower() != f".{requested}":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{requested.upper()} file not found")
        return FileResponse(
            path=str(original_path),
            media_type=_MIME[f".{requested}"],
            headers=_attachment_headers(original_path.name),
        )

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported format: {format}")


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: int, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.original_path and os.path.exists(document.original_path):
        os.remove(document.original_path)

    collection = db.query(Collection).filter(Collection.id == document.collection_id).first()
    if collection:
        collection.document_count = max(0, collection.document_count - 1)

    db.delete(document)
    db.commit()


@router.post("/documents/{document_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_document(document_id: int, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    document.status = DocumentStatus.PENDING
    document.error_message = None
    db.commit()

    return {
        "message": f"Reprocessing started for document '{document.filename}'",
        "document_id": document.id,
    }


@router.get("/documents/{document_id}/status", response_model=ProcessingStatusResponse)
async def get_document_status(document_id: int, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    latest_log = db.query(ProcessingLog).filter(
        ProcessingLog.document_id == document_id
    ).order_by(ProcessingLog.created_at.desc()).first()

    progress = 0
    message = None
    if latest_log:
        progress = latest_log.progress
        message = latest_log.message
    elif document.status == DocumentStatus.COMPLETED:
        progress = 100
        message = "Processing completed"
    elif document.status == DocumentStatus.FAILED:
        message = document.error_message

    return ProcessingStatusResponse(
        id=document.id,
        filename=document.filename,
        status=document.status.value,
        progress=progress,
        message=message,
    )
