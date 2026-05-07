# -*- coding: utf-8 -*-
"""
Answer Review persistence API.

POST /api/rag/reviews        — RAG 응답 저장
GET  /api/rag/reviews        — 저장된 리뷰 목록 (최신순)
GET  /api/rag/reviews/{id}   — 특정 리뷰 상세
DELETE /api/rag/reviews/{id} — 리뷰 삭제
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/rag/reviews", tags=["Review"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REVIEWS_DIR = PROJECT_ROOT / "data" / "reviews"
REVIEWS_FILE = REVIEWS_DIR / "reviews.jsonl"

_REVIEWS_CACHE: Optional[list] = None
_REVIEWS_MTIME: float = 0.0


class ReviewSaveRequest(BaseModel):
    query: str
    mode: str = "general"
    answer: str = ""
    documents: List[dict] = []
    snapshot: str = ""
    tag: str = ""
    note: str = ""


def _ensure_dir() -> None:
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    if not REVIEWS_FILE.exists():
        REVIEWS_FILE.write_text("", encoding="utf-8")


def _load_reviews() -> list:
    global _REVIEWS_CACHE, _REVIEWS_MTIME
    _ensure_dir()
    if not REVIEWS_FILE.exists():
        return []
    mtime = REVIEWS_FILE.stat().st_mtime
    if _REVIEWS_CACHE is not None and mtime == _REVIEWS_MTIME:
        return _REVIEWS_CACHE
    records = []
    for line in REVIEWS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    _REVIEWS_CACHE = records
    _REVIEWS_MTIME = mtime
    return records


def _invalidate_cache() -> None:
    global _REVIEWS_CACHE
    _REVIEWS_CACHE = None


def _append_review(record: dict) -> None:
    _ensure_dir()
    with REVIEWS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _invalidate_cache()


def _rewrite_reviews(records: list) -> None:
    _ensure_dir()
    REVIEWS_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    _invalidate_cache()


@router.post("")
async def save_review(req: ReviewSaveRequest):
    """RAG 응답을 저장합니다."""
    record = {
        "id": str(uuid.uuid4()),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "query": req.query,
        "mode": req.mode,
        "answer": req.answer,
        "doc_count": len(req.documents),
        "documents": [
            {
                "document_id": d.get("document_id", ""),
                "category": d.get("category", ""),
                "score": d.get("score", d.get("best_score", 0.0)),
            }
            for d in req.documents[:10]
        ],
        "snapshot": req.snapshot,
        "tag": req.tag,
        "note": req.note,
    }
    _append_review(record)
    return {"id": record["id"], "saved_at": record["saved_at"]}


@router.get("")
async def list_reviews(limit: int = 50, tag: Optional[str] = None):
    """저장된 리뷰 목록을 최신순으로 반환합니다."""
    reviews = _load_reviews()
    # Sort newest first
    reviews = sorted(reviews, key=lambda r: r.get("saved_at", ""), reverse=True)
    if tag:
        reviews = [r for r in reviews if r.get("tag", "") == tag]
    return {"reviews": reviews[:limit], "total": len(reviews)}


@router.get("/{review_id}")
async def get_review(review_id: str):
    """특정 리뷰 상세 정보를 반환합니다."""
    reviews = _load_reviews()
    record = next((r for r in reviews if r.get("id") == review_id), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"Review not found: {review_id}")
    return record


@router.delete("/{review_id}")
async def delete_review(review_id: str):
    """특정 리뷰를 삭제합니다."""
    reviews = _load_reviews()
    new_reviews = [r for r in reviews if r.get("id") != review_id]
    if len(new_reviews) == len(reviews):
        raise HTTPException(status_code=404, detail=f"Review not found: {review_id}")
    _rewrite_reviews(new_reviews)
    return {"deleted": review_id}
