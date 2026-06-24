# RAG 질의와 생성 경로를 분리해 제공하는 API
# -*- coding: utf-8 -*-
"""
RAG query API endpoints.
"""

from __future__ import annotations

import json
import importlib
import re
import subprocess
import tempfile
import sys
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings


router = APIRouter(prefix="/rag", tags=["RAG"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROPOSAL_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "generate_proposal_draft.py"
ACTIVE_INDEX_PATH = PROJECT_ROOT / "data" / "active_index.json"
WIKI_PROJECT_DIR = PROJECT_ROOT / "data" / "wiki" / "projects"
EXTRACTED_TEXT_DIR = PROJECT_ROOT / "data" / "extracted_text"
SUMMARIES_DIR = PROJECT_ROOT / "data" / "summaries"


def _rag_runtime():
    return importlib.import_module("app.services.rag_runtime")


def _active_snapshot() -> str:
    if ACTIVE_INDEX_PATH.exists():
        try:
            data = json.loads(ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
            snap = data.get("snapshot", "")
            if snap:
                return snap
        except Exception:
            pass
    return settings.faiss_snapshot


def _index_paths(snapshot: str, category: Optional[str] = None) -> tuple[Path, Path]:
    return _rag_runtime().default_index_paths(snapshot, category)


def _default_chunks_path() -> Path:
    return _rag_runtime().default_chunks_path(_active_snapshot())


def _search_wiki_projects(query: str, top_k: int) -> list[dict]:
    if not WIKI_PROJECT_DIR.exists():
        return []

    query_lower = query.lower()
    query_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]+", query_lower))
    results = []

    for md_path in sorted(WIKI_PROJECT_DIR.glob("*.md")):
        try:
            raw = md_path.read_text(encoding="utf-8")
        except Exception:
            continue

        lines = raw.splitlines()
        title = next((line[2:].strip() for line in lines if line.startswith("# ")), md_path.stem)
        title_lower = title.lower()
        body_lower = raw.lower()

        score = 0.0
        if query_lower in title_lower:
            score += 5.0
        if query_lower in body_lower:
            score += 2.0

        title_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]+", title_lower))
        score += float(len(query_tokens & title_tokens))
        if score <= 0:
            continue

        snippet = next(
            (
                line.strip()
                for line in lines
                if line.strip()
                and not line.startswith("#")
                and query_lower in line.lower()
            ),
            "",
        )
        if not snippet:
            snippet = next(
                (line.strip() for line in lines if line.strip() and not line.startswith("#")),
                "",
            )

        results.append(
            {
                "document_id": title,
                "source": str(md_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "category": "wiki",
                "content": snippet[:240],
                "score": round(score, 3),
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:top_k]


def _enrich_with_graph_context(payload: dict, original_query: str = "") -> dict:
    from app.services.graph_traversal import (
        expand_with_graph,
        parse_compound_query,
        search_with_graph,
    )

    documents = payload.get("documents", [])
    if not documents:
        payload["graph_context"] = []
        return payload

    enriched = expand_with_graph(documents)
    payload["documents"] = enriched["documents"]
    payload["graph_context"] = enriched["graph_context"]

    if original_query:
        parsed = parse_compound_query(original_query)
        if parsed.get("target_doc_type") and parsed.get("source_doc_type"):
            graph_results = search_with_graph(parsed, documents)
            if graph_results:
                payload["graph_search_results"] = graph_results
                payload["parsed_query"] = parsed

    return payload


class RagQueryRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = 20
    top_docs: int = 5
    answer_provider: str = "ollama"
    answer_model: str = "gemma4:latest"
    index_path: Optional[str] = None
    metadata_path: Optional[str] = None
    chunks_jsonl: Optional[str] = None
    category: Optional[str] = None
    organization: Optional[str] = None
    year: Optional[str] = None
    max_chunks_per_doc: int = 3
    mode: str = "auto"


class RagAnswerResponse(BaseModel):
    success: bool
    draft_answer: str = ""
    effective_mode: str = "general"
    document_count: int = 0
    error: Optional[str] = None


def _resolve_query_request(request: RagQueryRequest) -> tuple[str, str, Optional[dict]]:
    from app.services.query_expander import (
        detect_mode_with_reason,
        expand_bid_query,
        expand_rfp_query,
    )

    effective_mode = request.mode
    mode_detection = None
    if request.mode == "auto":
        mode_detection = detect_mode_with_reason(request.query)
        effective_mode = mode_detection["mode"]

    if effective_mode == "bid_project":
        effective_query = expand_bid_query(request.query)
    elif effective_mode == "rfp_analysis":
        effective_query = expand_rfp_query(request.query)
    elif effective_mode == "graph_rag":
        effective_query = request.query
    else:
        effective_query = expand_bid_query(request.query)

    return effective_mode, effective_query, mode_detection


def _run_query(request: RagQueryRequest, answer_provider: str, answer_model: str) -> tuple[dict, str, Optional[dict]]:
    snapshot = _active_snapshot()
    default_index, default_meta = _index_paths(snapshot, request.category)
    effective_mode, effective_query, mode_detection = _resolve_query_request(request)

    payload = _rag_runtime().run_rag_query(
        query=effective_query,
        original_query=request.query,
        top_k=request.top_k,
        top_docs=request.top_docs,
        answer_provider=answer_provider,
        answer_model=answer_model,
        category=request.category,
        organization=request.organization,
        year=request.year,
        max_chunks_per_doc=request.max_chunks_per_doc,
        mode=effective_mode,
        index_path=request.index_path or str(default_index),
        metadata_path=request.metadata_path or str(default_meta),
        chunks_jsonl=request.chunks_jsonl or str(_default_chunks_path()),
    )
    payload["success"] = True
    if mode_detection:
        payload["mode_detection"] = mode_detection
    payload["effective_mode"] = effective_mode

    if effective_mode in ("bid_project", "rfp_analysis"):
        from app.services.reranker import rerank

        payload["documents"] = rerank(
            request.query,
            payload.get("documents", []),
            effective_mode,
        )

    if effective_mode == "graph_rag":
        payload = _enrich_with_graph_context(payload, request.query)

    payload = _standardize_rag_payload(
        payload,
        snapshot=snapshot,
        max_chunks_per_doc=request.max_chunks_per_doc,
    )
    return payload, effective_mode, mode_detection


@router.post("/query")
async def query_rag(request: RagQueryRequest):
    try:
        payload, _, _ = _run_query(
            request,
            request.answer_provider,
            request.answer_model,
        )
        return payload
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# 유사 파일 검색 API
# 작성 목적:
#   rag-assistant.html 의 Knowledge Search 탭에서 검색어와 유사하거나
#   동일한 문서를 찾고, 각 문서의 본문 일부(evidence snippets)를 보여 주기 위한
#   전용 API입니다.
#
# 기존 /rag/query 도 같은 역할을 할 수 있지만, 화면 기능이 "답변 생성"이 아니라
# "유사 파일 검색 + 미리보기"이므로 별도 엔드포인트를 두면 프론트와 백엔드 역할이
# 명확해집니다.
# ─────────────────────────────────────────────────────────────────────────────

class SimilarFilesRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = 30
    top_docs: int = 8
    category: Optional[str] = None
    organization: Optional[str] = None
    year: Optional[str] = None
    max_chunks_per_doc: int = 3
    mode: str = "auto"


def _normalize_snippet(text: str, max_len: int = 500) -> str:
    """
    검색된 chunk 본문을 화면 미리보기용으로 정리합니다.
    - 줄바꿈/탭/연속 공백 제거
    - 너무 긴 내용은 max_len 기준으로 잘라서 반환
    """
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) > max_len:
        return cleaned[:max_len].rstrip() + "..."
    return cleaned


def _match_label(best_score: float) -> str:
    """
    FAISS/embedding 점수는 프로젝트마다 scale이 다를 수 있으므로
    화면 표시용으로만 참고합니다.
    """
    try:
        score = float(best_score or 0)
    except Exception:
        score = 0.0

    if score >= 0.85:
        return "동일 가능성 높음"
    if score >= 0.70:
        return "매우 유사"
    if score >= 0.50:
        return "유사"
    return "관련"


def _snapshot_source_id(snapshot: str) -> str:
    match = re.match(r"^snapshot_\d{8}_(.+?)(?:_v\d+)?$", snapshot or "")
    if match:
        return match.group(1)
    return ""


def _safe_score(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _snippet_text(snippet: Any) -> str:
    if isinstance(snippet, dict):
        return str(snippet.get("text") or snippet.get("content") or "").strip()
    return str(snippet or "").strip()


def _document_group(doc: dict) -> str:
    existing = str(doc.get("document_group") or "").strip()
    if existing:
        return existing

    category = str(doc.get("category") or "").lower()
    root_group = str(doc.get("root_group") or "")
    path = str(doc.get("relative_path") or doc.get("source_path") or "")
    haystack = f"{category} {root_group} {path}".lower()

    if "rfp" in haystack or "제안요청" in haystack:
        return "rfp"
    if "proposal" in haystack or "제안서" in haystack:
        return "proposal"
    if "deliverable" in haystack or "산출물" in haystack:
        return "deliverable"
    return category or "unknown"


def _document_type_label(document_group: str, doc: dict) -> str:
    existing = str(doc.get("document_type") or "").strip()
    if existing:
        return existing
    if document_group == "rfp":
        return "RFP"
    if document_group == "proposal":
        return "제안서"
    if document_group == "deliverable":
        return "산출물"
    return document_group or "문서"


def _sub_group_key(doc: dict) -> str:
    existing = str(doc.get("sub_group_key") or "").strip()
    if existing:
        return existing
    values = [
        doc.get("document_group"),
        doc.get("proposal_section"),
        doc.get("deliverable_section"),
        doc.get("section_label"),
        doc.get("sub_group"),
    ]
    parts = [
        re.sub(r"[^0-9a-zA-Z가-힣]+", "_", str(value).strip()).strip("_").lower()
        for value in values
        if str(value or "").strip()
    ]
    return "_".join(parts)


def _file_name(doc: dict) -> str:
    return (
        str(doc.get("file_name") or "").strip()
        or Path(str(doc.get("source_path") or doc.get("original_source_path") or "")).name
        or str(doc.get("document_id") or "")
    )


def _format_available(document_id: str, doc: dict) -> dict:
    if not document_id:
        return {
            "ocr_available": False,
            "markdown_available": False,
            "html_available": False,
            "summary_available": False,
            "text_available": False,
        }

    extracted_dir = EXTRACTED_TEXT_DIR / document_id
    text_available = bool(
        doc.get("text_available")
        or (extracted_dir / "raw_text.txt").exists()
        or (extracted_dir / "document.txt").exists()
    )
    markdown_available = bool(doc.get("markdown_available") or (extracted_dir / "document.md").exists())
    html_available = bool(doc.get("html_available") or (extracted_dir / "document.html").exists())
    summary_available = bool(doc.get("summary_available") or (SUMMARIES_DIR / document_id / "summary.md").exists())

    return {
        "ocr_available": bool(doc.get("ocr_available") or text_available),
        "markdown_available": markdown_available,
        "html_available": html_available,
        "summary_available": summary_available,
        "text_available": text_available,
    }


def _structured_evidence(doc: dict, max_chunks_per_doc: int) -> tuple[list[dict], list[str]]:
    raw_snippets = (
        doc.get("evidence_chunks")
        or doc.get("evidence_snippets")
        or doc.get("content_snippets")
        or doc.get("snippets")
        or []
    )
    if not isinstance(raw_snippets, list):
        raw_snippets = [raw_snippets]

    best_score = _safe_score(doc.get("best_score", doc.get("score", 0)))
    evidence = []
    content = []
    for idx, snippet in enumerate(raw_snippets[:max_chunks_per_doc], start=1):
        text = _normalize_snippet(_snippet_text(snippet))
        if not text:
            continue

        if isinstance(snippet, dict):
            chunk_id = str(snippet.get("chunk_id") or "").strip()
            page = snippet.get("page")
            score = _safe_score(snippet.get("score"), best_score)
        else:
            chunk_id = ""
            page = None
            score = best_score

        evidence.append(
            {
                "chunk_id": chunk_id or f"chunk_{idx:05d}",
                "text": text,
                "page": page,
                "score": score,
            }
        )
        content.append(text)

    return evidence, content


def _relation_summary(doc: dict, document_group: str) -> list[str]:
    existing = doc.get("relation_summary")
    if isinstance(existing, list) and existing:
        return [str(item) for item in existing if str(item or "").strip()]

    summary = []
    project_name = str(doc.get("project_name") or "").strip()
    section = str(
        doc.get("proposal_section")
        or doc.get("deliverable_section")
        or doc.get("section_label")
        or doc.get("sub_group")
        or ""
    ).strip()

    if project_name:
        summary.append(f"이 문서는 '{project_name}' 프로젝트 검색 결과와 연결되어 있습니다.")
    if document_group == "proposal" and section:
        summary.append(f"제안서의 '{section}' 섹션 근거가 검색어와 매칭되었습니다.")
    elif document_group == "rfp":
        summary.append("RFP 문서가 요구사항 근거 자료로 검색되었습니다.")
    elif document_group == "deliverable" and section:
        summary.append(f"산출물의 '{section}' 영역이 검색 근거로 사용되었습니다.")

    related = doc.get("related_documents") or []
    if related:
        summary.append(f"GraphRAG 기준 관련 문서 {len(related)}건과 연결되어 있습니다.")
    return summary


def _standardize_rag_document(doc: dict, rank: int, source_id: str, max_chunks_per_doc: int) -> dict:
    document_id = str(doc.get("document_id") or doc.get("id") or "").strip()
    file_name = _file_name(doc)
    original_path = (
        doc.get("original_path")
        or doc.get("original_source_path")
        or doc.get("relative_path")
        or doc.get("source_path")
        or ""
    )
    document_group = _document_group(doc)
    normalized = dict(doc)
    normalized["rank"] = doc.get("rank") or rank
    normalized["source_id"] = str(doc.get("source_id") or source_id or "")
    normalized["document_id"] = document_id
    normalized["file_name"] = file_name
    normalized["original_path"] = str(original_path)
    normalized["source_path"] = str(doc.get("source_path") or original_path or "")
    normalized["project_name"] = str(doc.get("project_name") or doc.get("title") or "")
    normalized["organization_name"] = str(
        doc.get("organization_name")
        or doc.get("organization")
        or ""
    )
    normalized["organization"] = normalized["organization_name"]
    normalized["document_group"] = document_group
    normalized["proposal_section"] = doc.get("proposal_section") or None
    normalized["deliverable_section"] = doc.get("deliverable_section") or None
    normalized["document_type"] = _document_type_label(document_group, doc)
    normalized["file_ext"] = Path(file_name).suffix.lstrip(".").lower()
    normalized["score"] = _safe_score(doc.get("score", doc.get("best_score", 0)))
    normalized["best_score"] = _safe_score(doc.get("best_score", normalized["score"]))
    normalized["ranking_score"] = _safe_score(doc.get("ranking_score", normalized["best_score"]))
    normalized["match_label"] = doc.get("match_label") or _match_label(normalized["best_score"])

    normalized["sub_group_key"] = _sub_group_key(normalized)
    if not normalized.get("category"):
        normalized["category"] = normalized["sub_group_key"] or document_group

    evidence, content = _structured_evidence(doc, max_chunks_per_doc)
    normalized["evidence_snippets"] = evidence
    normalized["content_snippets"] = content
    normalized.update(_format_available(document_id, doc))
    normalized["graph_available"] = bool(doc.get("graph_available") or doc.get("related_documents") or document_id)
    normalized["wiki_available"] = bool(doc.get("wiki_available"))
    normalized["relation_summary"] = _relation_summary(normalized, document_group)
    return normalized


def _standardize_rag_payload(payload: dict, snapshot: str, max_chunks_per_doc: int) -> dict:
    source_id = str(payload.get("source_id") or _snapshot_source_id(snapshot))
    documents = [
        _standardize_rag_document(doc, idx, source_id, max_chunks_per_doc)
        for idx, doc in enumerate(payload.get("documents", []) or [], start=1)
    ]
    payload["source_id"] = source_id
    payload["snapshot"] = snapshot
    payload["answer"] = payload.get("draft_answer", "")
    payload["documents"] = documents
    payload["results"] = documents
    payload["document_count"] = len(documents)
    return payload


def _to_similar_file_doc(doc: dict, rank: int, max_chunks_per_doc: int) -> dict:
    """
    run_rag_query()가 반환한 문서 객체를 프론트엔드 표시용 구조로 변환합니다.

    기대 입력 필드:
      - document_id
      - project_name
      - category
      - source_path
      - input_path
      - best_score
      - ranking_score
      - hit_count
      - evidence_snippets
      - reasons
    """
    snippets = (
        doc.get("evidence_snippets")
        or doc.get("content_snippets")
        or doc.get("snippets")
        or []
    )

    content_snippets = [
        _normalize_snippet(_snippet_text(snippet))
        for snippet in snippets[:max_chunks_per_doc]
        if _snippet_text(snippet)
    ]

    best_score = doc.get("best_score", doc.get("score", 0))
    ranking_score = doc.get("ranking_score", best_score)

    standard_doc = _standardize_rag_document(
        doc,
        rank,
        str(doc.get("source_id") or ""),
        max_chunks_per_doc,
    )
    standard_doc.update({
        "rank": rank,
        "match_label": _match_label(best_score),
        "input_path": doc.get("input_path") or "",
        "best_score": best_score,
        "ranking_score": ranking_score,
        "hit_count": doc.get("hit_count", len(content_snippets)),
        "reasons": doc.get("reasons", []),
        "content_snippets": content_snippets,
    })
    return standard_doc


@router.post("/similar-files")
async def similar_files(request: SimilarFilesRequest):
    """
    검색어와 유사한 파일 목록과 본문 일부를 반환합니다.

    사용 예:
      POST /api/rag/similar-files
      {
        "query": "경기주택도시공사 정보화전략계획 ISP",
        "top_k": 30,
        "top_docs": 8,
        "category": "proposal",
        "max_chunks_per_doc": 3
      }

    프론트엔드에서는 documents[].content_snippets 또는
    documents[].evidence_snippets 를 화면에 표시하면 됩니다.
    """
    try:
        # 기존 RAG 검색 로직을 재사용합니다.
        # answer_provider="none"으로 강제하여 Ollama 답변 생성 없이 검색만 수행합니다.
        rag_request = RagQueryRequest(
            query=request.query,
            top_k=request.top_k,
            top_docs=request.top_docs,
            answer_provider="none",
            answer_model="",
            category=request.category,
            organization=request.organization,
            year=request.year,
            max_chunks_per_doc=request.max_chunks_per_doc,
            mode=request.mode,
        )

        payload, effective_mode, mode_detection = _run_query(
            rag_request,
            answer_provider="none",
            answer_model="",
        )

        raw_documents = payload.get("documents", []) or []

        documents = [
            _to_similar_file_doc(doc, idx, request.max_chunks_per_doc)
            for idx, doc in enumerate(raw_documents[:request.top_docs], start=1)
        ]

        return {
            "success": True,
            "query": request.query,
            "effective_mode": effective_mode,
            "mode_detection": mode_detection,
            "source_id": payload.get("source_id"),
            "snapshot": payload.get("snapshot"),
            "document_count": len(documents),
            "documents": documents,
            "graph_context": payload.get("graph_context", []),
        }

    except Exception as exc:
        return {
            "success": False,
            "query": request.query,
            "error": str(exc),
            "documents": [],
        }


@router.post("/answer", response_model=RagAnswerResponse)
async def answer_rag(request: RagQueryRequest):
    try:
        provider = request.answer_provider or "ollama"
        model = request.answer_model or "gemma4:latest"
        payload, effective_mode, _ = _run_query(request, provider, model)
        return RagAnswerResponse(
            success=True,
            draft_answer=payload.get("draft_answer", ""),
            effective_mode=effective_mode,
            document_count=len(payload.get("documents", []) or []),
        )
    except Exception as exc:
        return RagAnswerResponse(success=False, error=str(exc))


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: str = "general"
    top_k: int = 10


@router.post("/search")
async def search_documents(request: SearchRequest):
    from app.services.query_expander import expand_bid_query, expand_rfp_query

    if request.mode == "wiki":
        return {
            "results": _search_wiki_projects(request.query, request.top_k),
            "query": request.query,
            "mode": request.mode,
        }

    snapshot = _active_snapshot()
    default_index, default_meta = _index_paths(snapshot, None)
    index_path = str(default_index)
    metadata_path = str(default_meta)
    chunks_jsonl = str(_default_chunks_path())

    if request.mode == "bid":
        effective_query = expand_bid_query(request.query)
        rag_mode = "bid_project"
    elif request.mode == "rfp":
        effective_query = expand_rfp_query(request.query)
        rag_mode = "rfp_analysis"
    elif request.mode == "graph":
        effective_query = request.query
        rag_mode = "graph_rag"
    else:
        effective_query = expand_bid_query(request.query)
        rag_mode = "general"

    try:
        payload = _rag_runtime().run_rag_query(
            query=effective_query,
            original_query=request.query,
            top_k=request.top_k,
            top_docs=5,
            answer_provider="none",
            answer_model="",
            category=None,
            organization=None,
            year=None,
            max_chunks_per_doc=3,
            mode=rag_mode,
            index_path=index_path,
            metadata_path=metadata_path,
            chunks_jsonl=chunks_jsonl,
        )
    except Exception as exc:
        return {"results": [], "error": str(exc)}

    results = []
    for doc in payload.get("documents", []):
        for snippet in doc.get("evidence_snippets", [])[:2]:
            snippet_text = _snippet_text(snippet)
            if not snippet_text:
                continue
            results.append(
                {
                    "document_id": doc.get("project_name") or doc.get("source_path", "")[:50],
                    "source": doc.get("source_path", ""),
                    "category": doc.get("category", "unknown"),
                    "content": snippet_text,
                    "score": doc.get("score", 0),
                }
            )
    return {"results": results[: request.top_k], "query": request.query, "mode": request.mode}


class ProposalRequest(BaseModel):
    project_name: str = Field(..., min_length=2)
    organization: str = ""
    category: str = "proposal"
    sections: List[str] = ["overview", "current", "strategy", "schedule", "track", "effect"]
    top_k: int = 15
    top_docs: int = 4
    answer_model: str = "gemma4:latest"
    index_path: Optional[str] = None
    metadata_path: Optional[str] = None
    chunks_jsonl: Optional[str] = None


@router.post("/proposal")
async def generate_proposal(request: ProposalRequest):
    snapshot = _active_snapshot()
    default_index, default_meta = _index_paths(snapshot, None)
    index_path = request.index_path or str(default_index)
    metadata_path = request.metadata_path or str(default_meta)
    chunks_jsonl = request.chunks_jsonl or str(_default_chunks_path())

    with tempfile.TemporaryDirectory() as temp_dir:
        output_json = Path(temp_dir) / "proposal_draft.json"
        cmd = [
            sys.executable,
            str(PROPOSAL_SCRIPT),
            "--index-path",
            index_path,
            "--metadata-path",
            metadata_path,
            "--chunks-jsonl",
            chunks_jsonl,
            "--project-name",
            request.project_name,
            "--organization",
            request.organization,
            "--category",
            request.category,
            "--sections",
            ",".join(request.sections),
            "--top-k",
            str(request.top_k),
            "--top-docs",
            str(request.top_docs),
            "--answer-model",
            request.answer_model,
            "--embedding-provider",
            "ollama",
            "--output-json",
            str(output_json),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT / "backend" / "scripts"))
        if proc.returncode != 0:
            return {
                "success": False,
                "error": proc.stderr.strip() or "Proposal generation failed",
                "stdout": proc.stdout,
            }
        payload = json.loads(output_json.read_text(encoding="utf-8"))
        payload["success"] = True
        return payload
