# RAG 질의와 생성 경로를 분리해 제공하는 API
# -*- coding: utf-8 -*-
"""
RAG query API endpoints.
"""

from __future__ import annotations

import io
import json
import importlib
import re
import subprocess
import tempfile
import sys
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, model_validator

from app.api.rag_with_similar_files import (
    _snippet_text as _standard_snippet_text,
    _standardize_rag_document,
    _standardize_rag_payload,
)
from app.services.query_log_service import query_log_service
from app.services.search_scope_service import (
    get_search_scope_catalog,
    resolve_search_scope,
)
from app.services.snapshot_registry_service import list_snapshot_registry
from app.services.platform_store import get_record


router = APIRouter(prefix="/rag", tags=["RAG"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROPOSAL_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "generate_proposal_draft.py"
ACTIVE_INDEX_PATH = PROJECT_ROOT / "data" / "active_index.json"
WIKI_PROJECT_DIR = PROJECT_ROOT / "data" / "wiki" / "projects"

# RFP 업로드 지원 형식
_SUPPORTED_RFP_TYPES = {".pdf", ".docx", ".txt"}
_PLANNED_RFP_TYPES = {".hwpx", ".hwp"}


def _rag_runtime():
    return importlib.import_module("app.services.rag_runtime")


def _active_snapshot() -> str:
    return _rag_runtime().get_active_snapshot()


def _index_paths(snapshot: str, category: Optional[str] = None) -> tuple[Path, Path]:
    return _rag_runtime().default_index_paths(snapshot, category)


def _default_chunks_path() -> Path:
    return _rag_runtime().default_chunks_path(_active_snapshot())


def _normalize_document_group_to_category(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    mapping = {
        "rfp": "rfp",
        "제안요청서": "rfp",
        "과업지시서": "rfp",
        "proposal": "proposal",
        "제안서": "proposal",
        "deliverable": "deliverable",
        "산출물": "deliverable",
    }
    return mapping.get(normalized)


def _normalize_selected_document_ids(selected_document_ids: Optional[list[str]]) -> list[str]:
    normalized = []
    for item in selected_document_ids or []:
        value = str(item).strip()
        if value:
            normalized.append(value)
    return normalized


def _filter_documents_by_selected_ids(
    documents: list[dict], selected_document_ids: list[str]
) -> list[dict]:
    if not documents or not selected_document_ids:
        return documents

    selected_set = set(_normalize_selected_document_ids(selected_document_ids))
    if not selected_set:
        return documents

    filtered = []
    for doc in documents:
        candidates = {
            str(doc.get("document_id", "")).strip(),
            str(doc.get("file_name", "")).strip(),
            str(doc.get("source_path", "")).strip(),
            str(doc.get("original_source_path", "")).strip(),
            str(doc.get("relative_path", "")).strip(),
        }
        candidates.discard("")
        if candidates & selected_set:
            filtered.append(doc)

    return filtered


def _build_skip_reasons(skipped_snapshots: list[dict]) -> list[str]:
    reasons: list[str] = []
    for item in skipped_snapshots or []:
        snapshot_id = str(item.get("snapshot") or "").strip()
        error = str(item.get("error") or "").strip()
        if snapshot_id and error:
            reasons.append(f"{snapshot_id}: {error}")
        elif snapshot_id:
            reasons.append(snapshot_id)
        elif error:
            reasons.append(error)
    return reasons


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


def normalize_retrieval_weights(
    vector_weight: float,
    graph_weight: float,
    wiki_weight: float,
) -> dict:
    """검색 점수 계산용 가중치를 정규화한다. 합계가 0이면 vector=1로 복구한다."""
    v = max(0.0, float(vector_weight or 0.0))
    g = max(0.0, float(graph_weight or 0.0))
    w = max(0.0, float(wiki_weight or 0.0))
    total = v + g + w
    if total <= 0:
        return {"vector_weight": 1.0, "graph_weight": 0.0, "wiki_weight": 0.0}
    return {
        "vector_weight": v / total,
        "graph_weight": g / total,
        "wiki_weight": w / total,
    }


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
    # 확장 필드 — 기존 클라이언트 하위 호환성 유지 (모두 Optional 또는 기본값)
    collection: Optional[str] = None
    document_group: Optional[str] = None
    document_category: Optional[str] = None
    section_type: Optional[str] = None
    relative_path_prefix: Optional[str] = None
    search_scope: Optional[str] = None
    snapshot_ids: list[str] = Field(default_factory=list)
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    prompt_template: Optional[str] = None
    system_prompt: Optional[str] = None
    vector_weight: float = Field(1.0, ge=0.0, le=1.0)
    graph_weight: float = Field(0.0, ge=0.0, le=1.0)
    wiki_weight: float = Field(0.0, ge=0.0, le=1.0)
    selected_document_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_weights(self) -> "RagQueryRequest":
        total = self.vector_weight + self.graph_weight + self.wiki_weight
        if total <= 0:
            self.vector_weight = 1.0
            self.graph_weight = 0.0
            self.wiki_weight = 0.0
        return self


class RagAnswerResponse(BaseModel):
    success: bool
    draft_answer: str = ""
    effective_mode: str = "general"
    document_count: int = 0
    evidence_documents: list[dict] = []
    error: Optional[str] = None


def _answer_evidence_documents(documents: list[dict], limit: int = 5) -> list[dict]:
    items = []
    for doc in documents[:limit]:
        items.append(
            {
                "document_id": doc.get("document_id") or "",
                "project_name": doc.get("project_name") or "",
                "file_name": doc.get("file_name") or "",
                "category": doc.get("category") or "",
                "collection_key": doc.get("collection_key") or "",
                "document_group": doc.get("document_group") or "",
                "document_category": doc.get("document_category") or "",
                "source_root": doc.get("source_root") or "",
                "source_path": doc.get("source_path") or doc.get("source") or "",
                "original_source_path": doc.get("original_source_path") or doc.get("source_path") or doc.get("source") or "",
                "relative_path": doc.get("relative_path") or "",
                "best_score": doc.get("best_score", doc.get("score", 0)),
            }
        )
    return items


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _log_query_event(
    *,
    request: Request,
    endpoint: str,
    query_text: str,
    prompt_source: str,
    effective_mode: str,
    category: Optional[str],
    organization: Optional[str],
    year: Optional[str],
    top_k: int,
    top_docs: int,
    success: bool,
    duration_ms: int,
    payload: Optional[dict] = None,
    error_message: str = "",
    extra_json: Optional[dict] = None,
) -> None:
    documents = (payload or {}).get("documents", []) or []
    query_log_service.log_query(
        {
            "endpoint": endpoint,
            "query_text": query_text,
            "prompt_source": prompt_source,
            "effective_mode": effective_mode,
            "category_filter": category or "",
            "organization_filter": organization or "",
            "year_filter": year or "",
            "top_k": top_k,
            "top_docs": top_docs,
            "result_count": len(documents),
            "success": success,
            "error_message": error_message,
            "duration_ms": duration_ms,
            "client_ip": _client_ip(request),
            "user_agent": request.headers.get("user-agent", ""),
            "top_document_ids": [doc.get("document_id") for doc in documents[:5] if doc.get("document_id")],
            "top_categories": [doc.get("category") for doc in documents[:5] if doc.get("category")],
            "top_source_paths": [doc.get("source_path") for doc in documents[:5] if doc.get("source_path")],
            "extra_json": extra_json or {},
        }
    )


def _load_llm_settings() -> dict:
    """LLM 설정 파일에서 설정 로드."""
    settings_path = PROJECT_ROOT / "data" / "config" / "llm_settings.json"
    defaults = {"typo_dict": ""}
    if not settings_path.exists():
        return defaults
    try:
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        return {**defaults, **saved}
    except Exception:
        return defaults


def _apply_typo_correction(query: str) -> str:
    """오타 보정 사전 적용."""
    llm_settings = _load_llm_settings()
    typo_dict_str = llm_settings.get("typo_dict", "")
    if not typo_dict_str:
        return query

    corrected = query
    for line in typo_dict_str.split('\n'):
        if '→' in line:
            parts = line.split('→')
            if len(parts) == 2:
                from_text = parts[0].strip()
                to_text = parts[1].strip()
                if from_text and to_text:
                    corrected = corrected.replace(from_text, to_text)
    return corrected


def _resolve_query_request(request: RagQueryRequest) -> tuple[str, str, Optional[dict]]:
    from app.services.query_expander import (
        detect_mode_with_reason,
        expand_bid_query,
        expand_rfp_query,
    )

    # 오타 보정 적용
    corrected_query = _apply_typo_correction(request.query)

    effective_mode = request.mode
    mode_detection = None
    if request.mode == "auto":
        mode_detection = detect_mode_with_reason(corrected_query)
        effective_mode = mode_detection["mode"]

    if effective_mode == "bid_project":
        effective_query = expand_bid_query(corrected_query)
    elif effective_mode == "rfp_analysis":
        effective_query = expand_rfp_query(corrected_query)
    elif effective_mode == "graph_rag":
        effective_query = corrected_query
    else:
        effective_query = expand_bid_query(corrected_query)

    return effective_mode, effective_query, mode_detection


def _run_query(request: RagQueryRequest, answer_provider: str, answer_model: str) -> tuple[dict, str, Optional[dict]]:
    effective_mode, effective_query, mode_detection = _resolve_query_request(request)
    resolved_scope = resolve_search_scope(request.search_scope)
    effective_category = request.category or _normalize_document_group_to_category(request.document_group)

    if request.index_path or request.metadata_path or request.chunks_jsonl:
        snapshot = _active_snapshot()
        default_index, default_meta = _index_paths(snapshot, effective_category)
        payload = _rag_runtime().run_rag_query(
            query=effective_query,
            original_query=request.query,
            top_k=request.top_k,
            top_docs=request.top_docs,
            answer_provider=answer_provider,
            answer_model=answer_model,
            category=effective_category,
            organization=request.organization,
            year=request.year,
            document_group=request.document_group,
            document_category=request.document_category,
            section_type=request.section_type,
            relative_path_prefix=request.relative_path_prefix,
            max_chunks_per_doc=request.max_chunks_per_doc,
            mode=effective_mode,
            snapshot=snapshot,
            index_path=request.index_path or str(default_index),
            metadata_path=request.metadata_path or str(default_meta),
            chunks_jsonl=request.chunks_jsonl or str(_default_chunks_path()),
        )
        resolved_snapshots = payload.get("resolved_snapshots") or [snapshot]
    else:
        # request.snapshot_ids가 명시적으로 지정되면 우선 사용
        if request.snapshot_ids:
            resolved_snapshots = [
                str(value).strip()
                for value in request.snapshot_ids
                if str(value).strip()
            ]
        else:
            # search_scope에서 snapshot_ids 가져오기
            resolved_snapshots = [
                str(value).strip()
                for value in (resolved_scope.get("snapshot_ids") or [])
                if str(value).strip()
            ]
        if not resolved_snapshots:
            fallback_snapshot = _active_snapshot()
            if fallback_snapshot:
                resolved_snapshots = [fallback_snapshot]

        if len(resolved_snapshots) > 1:
            payload = _rag_runtime().run_multi_rag_query(
                query=effective_query,
                original_query=request.query,
                top_k=request.top_k,
                top_docs=request.top_docs,
                answer_provider=answer_provider,
                answer_model=answer_model,
                category=effective_category,
                organization=request.organization,
                year=request.year,
                document_group=request.document_group,
                document_category=request.document_category,
                section_type=request.section_type,
                relative_path_prefix=request.relative_path_prefix,
                max_chunks_per_doc=request.max_chunks_per_doc,
                mode=effective_mode,
                snapshots=resolved_snapshots,
            )
            snapshot = resolved_snapshots[0]
        else:
            snapshot = resolved_snapshots[0] if resolved_snapshots else _active_snapshot()
            payload = _rag_runtime().run_rag_query(
                query=effective_query,
                original_query=request.query,
                top_k=request.top_k,
                top_docs=request.top_docs,
                answer_provider=answer_provider,
                answer_model=answer_model,
                category=effective_category,
                organization=request.organization,
                year=request.year,
                document_group=request.document_group,
                document_category=request.document_category,
                section_type=request.section_type,
                relative_path_prefix=request.relative_path_prefix,
                max_chunks_per_doc=request.max_chunks_per_doc,
                mode=effective_mode,
                snapshot=snapshot,
            )

    payload["documents"] = _filter_documents_by_selected_ids(
        payload.get("documents", []) or [],
        request.selected_document_ids,
    )
    payload["success"] = True
    if mode_detection:
        payload["mode_detection"] = mode_detection
    payload["effective_mode"] = effective_mode
    if effective_category and not payload.get("category_filter"):
        payload["category_filter"] = effective_category
    # 실제 적용된 가중치를 응답에 포함
    payload["effective_weights"] = normalize_retrieval_weights(
        request.vector_weight, request.graph_weight, request.wiki_weight
    )

    if effective_mode in ("bid_project", "rfp_analysis"):
        from app.services.reranker import rerank

        payload["documents"] = rerank(
            request.query,
            payload.get("documents", []),
            effective_mode,
        )

    if effective_mode == "graph_rag":
        payload = _enrich_with_graph_context(payload, request.query)

    scope_source_ids = [
        str(value).strip()
        for value in (resolved_scope.get("source_ids") or [])
        if str(value).strip()
    ]
    if len(scope_source_ids) > 1:
        payload["source_id"] = "multi_source"
    elif scope_source_ids and not payload.get("source_id"):
        payload["source_id"] = scope_source_ids[0]

    payload = _standardize_rag_payload(
        payload,
        snapshot=snapshot,
        max_chunks_per_doc=request.max_chunks_per_doc,
    )
    payload["search_scope"] = resolved_scope.get("scope_id")
    payload["search_scope_label"] = resolved_scope.get("label")
    payload["search_scope_description"] = resolved_scope.get("description")
    payload["resolved_search_scope"] = resolved_scope.get("scope_id")
    payload["resolved_search_scope_label"] = resolved_scope.get("label")
    payload["resolved_search_scope_description"] = resolved_scope.get("description")
    payload["resolved_snapshots"] = resolved_snapshots
    payload["resolved_snapshot_ids"] = resolved_snapshots
    payload["requested_snapshot_ids"] = request.snapshot_ids
    payload["resolved_category_filter"] = payload.get("category_filter") or effective_category
    payload["resolved_source_ids"] = scope_source_ids
    payload["skipped_snapshot_ids"] = [
        str(item.get("snapshot") or "").strip()
        for item in (payload.get("skipped_snapshots") or [])
        if str(item.get("snapshot") or "").strip()
    ]
    payload["skip_reasons"] = _build_skip_reasons(payload.get("skipped_snapshots") or [])
    payload["evidence_documents"] = _answer_evidence_documents(payload.get("documents", []) or [])
    payload["retrieval_summary"] = {
        "found_documents": bool(payload.get("documents")),
        "document_count": len(payload.get("documents", []) or []),
        "resolved_search_scope": resolved_scope.get("scope_id"),
        "resolved_snapshot_count": len(resolved_snapshots),
        "skipped_snapshot_count": len(payload.get("skipped_snapshots") or []),
        "resolved_category_filter": payload.get("category_filter") or effective_category,
        "no_result_reason": (payload.get("retrieval_diagnostics") or {}).get("no_result_reason"),
        "top_source_paths": [
            doc.get("source_path") or doc.get("original_source_path") or ""
            for doc in (payload.get("documents", []) or [])[:5]
            if doc.get("source_path") or doc.get("original_source_path")
        ],
    }

    return payload, effective_mode, mode_detection


@router.post("/query")
async def query_rag(request: RagQueryRequest, http_request: Request):
    started = time.perf_counter()
    try:
        payload, _, _ = _run_query(
            request,
            request.answer_provider,
            request.answer_model,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_query_event(
            request=http_request,
            endpoint="/api/rag/query",
            query_text=request.query,
            prompt_source="user",
            effective_mode=payload.get("effective_mode", ""),
            category=request.category,
            organization=request.organization,
            year=request.year,
            top_k=request.top_k,
            top_docs=request.top_docs,
            success=True,
            duration_ms=duration_ms,
            payload=payload,
            extra_json={"has_answer": bool(payload.get("draft_answer"))},
        )
        return payload
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_query_event(
            request=http_request,
            endpoint="/api/rag/query",
            query_text=request.query,
            prompt_source="user",
            effective_mode=request.mode,
            category=request.category,
            organization=request.organization,
            year=request.year,
            top_k=request.top_k,
            top_docs=request.top_docs,
            success=False,
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        return {"success": False, "error": str(exc)}


@router.post("/answer", response_model=RagAnswerResponse)
async def answer_rag(request: RagQueryRequest, http_request: Request):
    started = time.perf_counter()
    try:
        provider = request.answer_provider or "ollama"
        model = request.answer_model or "gemma4:latest"
        payload, effective_mode, _ = _run_query(request, provider, model)
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_query_event(
            request=http_request,
            endpoint="/api/rag/answer",
            query_text=request.query,
            prompt_source="user",
            effective_mode=effective_mode,
            category=request.category,
            organization=request.organization,
            year=request.year,
            top_k=request.top_k,
            top_docs=request.top_docs,
            success=True,
            duration_ms=duration_ms,
            payload=payload,
            extra_json={"has_answer": bool(payload.get("draft_answer"))},
        )
        return RagAnswerResponse(
            success=True,
            draft_answer=payload.get("draft_answer", ""),
            effective_mode=effective_mode,
            document_count=len(payload.get("documents", []) or []),
            evidence_documents=payload.get("evidence_documents", []) or [],
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_query_event(
            request=http_request,
            endpoint="/api/rag/answer",
            query_text=request.query,
            prompt_source="user",
            effective_mode=request.mode,
            category=request.category,
            organization=request.organization,
            year=request.year,
            top_k=request.top_k,
            top_docs=request.top_docs,
            success=False,
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        return RagAnswerResponse(success=False, error=str(exc))


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: str = "general"
    top_k: int = 10
    search_scope: Optional[str] = None
    snapshot_ids: list[str] = Field(default_factory=list)


def _parse_snapshot_ids_form(raw_value: Optional[str]) -> list[str]:
    value = str(raw_value or "").strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return [item.strip() for item in value.split(",") if item.strip()]


@router.get("/search-scopes")
async def get_search_scopes():
    catalog = get_search_scope_catalog()
    return {
        "success": True,
        **catalog,
    }


@router.post("/search")
async def search_documents(request: SearchRequest, http_request: Request):
    from app.services.query_expander import expand_bid_query, expand_rfp_query
    started = time.perf_counter()

    if request.mode == "wiki":
        result = {
            "results": _search_wiki_projects(request.query, request.top_k),
            "query": request.query,
            "mode": request.mode,
        }
        duration_ms = int((time.perf_counter() - started) * 1000)
        query_log_service.log_query(
            {
                "endpoint": "/api/rag/search",
                "query_text": request.query,
                "prompt_source": "user",
                "effective_mode": request.mode,
                "top_k": request.top_k,
                "top_docs": 0,
                "result_count": len(result["results"]),
                "success": True,
                "duration_ms": duration_ms,
                "client_ip": _client_ip(http_request),
                "user_agent": http_request.headers.get("user-agent", ""),
                "top_document_ids": [item.get("document_id") for item in result["results"][:5]],
                "top_categories": [item.get("category") for item in result["results"][:5]],
                "top_source_paths": [item.get("source") for item in result["results"][:5]],
                "extra_json": {"search_mode": request.mode},
            }
        )
        return result

    resolved_scope = resolve_search_scope(request.search_scope)
    # request.snapshot_ids가 명시적으로 지정되면 우선 사용
    if request.snapshot_ids:
        resolved_snapshots = [
            str(value).strip()
            for value in request.snapshot_ids
            if str(value).strip()
        ]
    else:
        resolved_snapshots = [
            str(value).strip()
            for value in (resolved_scope.get("snapshot_ids") or [])
            if str(value).strip()
        ]
    if not resolved_snapshots:
        fallback_snapshot = _active_snapshot()
        if fallback_snapshot:
            resolved_snapshots = [fallback_snapshot]

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
        if len(resolved_snapshots) > 1:
            payload = _rag_runtime().run_multi_rag_query(
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
                snapshots=resolved_snapshots,
            )
        else:
            snapshot = resolved_snapshots[0] if resolved_snapshots else _active_snapshot()
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
                snapshot=snapshot,
            )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        query_log_service.log_query(
            {
                "endpoint": "/api/rag/search",
                "query_text": request.query,
                "prompt_source": "user",
                "effective_mode": request.mode,
                "top_k": request.top_k,
                "top_docs": 5,
                "result_count": 0,
                "success": False,
                "duration_ms": duration_ms,
                "client_ip": _client_ip(http_request),
                "user_agent": http_request.headers.get("user-agent", ""),
                "error_message": str(exc),
                "extra_json": {"search_mode": request.mode},
            }
        )
        return {"results": [], "error": str(exc)}

    results = []
    for doc in payload.get("documents", []):
        for snippet in doc.get("evidence_snippets", [])[:2]:
            results.append(
                {
                    "document_id": doc.get("project_name") or doc.get("source_path", "")[:50],
                    "project_name": doc.get("project_name") or "",
                    "file_name": doc.get("file_name") or "",
                    "source": doc.get("source_path", ""),
                    "source_path": doc.get("source_path", ""),
                    "original_source_path": doc.get("original_source_path", ""),
                    "relative_path": doc.get("relative_path", ""),
                    "category": doc.get("category", "unknown"),
                    "collection_key": doc.get("collection_key", "") or doc.get("category", ""),
                    "document_group": doc.get("document_group", "") or doc.get("collection_key", "") or doc.get("category", ""),
                    "document_category": doc.get("document_category", "") or doc.get("section_label", ""),
                    "content": snippet,
                    "score": doc.get("score", 0),
                }
            )
    output = {"results": results[: request.top_k], "query": request.query, "mode": request.mode}
    duration_ms = int((time.perf_counter() - started) * 1000)
    query_log_service.log_query(
        {
            "endpoint": "/api/rag/search",
            "query_text": request.query,
            "prompt_source": "user",
            "effective_mode": rag_mode,
            "top_k": request.top_k,
            "top_docs": 5,
            "result_count": len(output["results"]),
            "success": True,
            "duration_ms": duration_ms,
            "client_ip": _client_ip(http_request),
            "user_agent": http_request.headers.get("user-agent", ""),
            "top_document_ids": [item.get("document_id") for item in output["results"][:5]],
            "top_categories": [item.get("category") for item in output["results"][:5]],
            "top_source_paths": [item.get("source") for item in output["results"][:5]],
            "extra_json": {"search_mode": request.mode},
        }
    )
    return output


# ─────────────────────────────────────────────────────────────────────────────
# 유사 파일 검색 API
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
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) > max_len:
        return cleaned[:max_len].rstrip() + "..."
    return cleaned


def _match_label(best_score: float) -> str:
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


def _to_similar_file_doc(doc: dict, rank: int, max_chunks_per_doc: int) -> dict:
    snippets = (
        doc.get("evidence_snippets")
        or doc.get("content_snippets")
        or doc.get("snippets")
        or []
    )
    content_snippets = [
        _normalize_snippet(_standard_snippet_text(snippet))
        for snippet in snippets[:max_chunks_per_doc]
        if _standard_snippet_text(snippet)
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
async def similar_files(request: SimilarFilesRequest, http_request: Request):
    """검색어와 유사한 파일 목록과 본문 일부를 반환한다."""
    started = time.perf_counter()
    try:
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
            for idx, doc in enumerate(raw_documents[: request.top_docs], start=1)
        ]
        result = {
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
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_query_event(
            request=http_request,
            endpoint="/api/rag/similar-files",
            query_text=request.query,
            prompt_source="user",
            effective_mode=effective_mode,
            category=request.category,
            organization=request.organization,
            year=request.year,
            top_k=request.top_k,
            top_docs=request.top_docs,
            success=True,
            duration_ms=duration_ms,
            payload={"documents": documents},
        )
        return result
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_query_event(
            request=http_request,
            endpoint="/api/rag/similar-files",
            query_text=request.query,
            prompt_source="user",
            effective_mode=request.mode,
            category=request.category,
            organization=request.organization,
            year=request.year,
            top_k=request.top_k,
            top_docs=request.top_docs,
            success=False,
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        return {
            "success": False,
            "query": request.query,
            "error": str(exc),
            "documents": [],
        }


# ─────────────────────────────────────────────────────────────────────────────
# RFP 파일 업로드 검색 API
# 1차 지원: PDF, DOCX, TXT / 2차 예정: HWPX, HWP
# ─────────────────────────────────────────────────────────────────────────────

def _extract_text_from_upload(file_content: bytes, filename: str) -> str:
    """업로드된 파일에서 텍스트를 추출한다."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    if suffix == ".docx":
        import docx as _docx
        doc = _docx.Document(io.BytesIO(file_content))
        return "\n".join(para.text for para in doc.paragraphs)
    if suffix == ".txt":
        try:
            return file_content.decode("utf-8")
        except UnicodeDecodeError:
            return file_content.decode("cp949", errors="ignore")
    raise ValueError(f"지원하지 않는 파일 형식: {suffix}")


@router.post("/query-with-rfp")
async def query_with_rfp(
    http_request: Request,
    file: UploadFile = File(...),
    top_k: int = Form(20),
    top_docs: int = Form(5),
    search_scope: Optional[str] = Form(None),
    snapshot_ids: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    answer_provider: str = Form("ollama"),
    answer_model: str = Form("gemma4:latest"),
    mode: str = Form("auto"),
    max_chunks_per_doc: int = Form(3),
):
    """RFP 파일을 업로드하면 유사 문서를 검색하고 답변을 생성한다. (PDF/DOCX/TXT 지원)"""
    started = time.perf_counter()
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()

    if suffix in _PLANNED_RFP_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "HWP/HWPX는 2차 지원 예정입니다. PDF, DOCX, TXT로 변환 후 업로드해 주세요.",
                "supported_types": sorted(_SUPPORTED_RFP_TYPES),
                "planned_types": sorted(_PLANNED_RFP_TYPES),
            },
        )
    if suffix not in _SUPPORTED_RFP_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"지원하지 않는 파일 형식입니다: {suffix or '(확장자 없음)'}",
                "supported_types": sorted(_SUPPORTED_RFP_TYPES),
            },
        )

    try:
        file_content = await file.read()
        extracted_text = _extract_text_from_upload(file_content, filename)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"파일 텍스트 추출 실패: {exc}")

    if not extracted_text.strip():
        raise HTTPException(status_code=422, detail="파일에서 텍스트를 추출할 수 없습니다.")

    # 임베딩 토큰 한계를 고려해 앞 2000자를 쿼리로 사용
    query_text = extracted_text[:2000].strip()

    try:
        rag_request = RagQueryRequest(
            query=query_text,
            top_k=top_k,
            top_docs=top_docs,
            answer_provider=answer_provider,
            answer_model=answer_model,
            search_scope=search_scope,
            snapshot_ids=_parse_snapshot_ids_form(snapshot_ids),
            category=category,
            max_chunks_per_doc=max_chunks_per_doc,
            mode=mode,
        )
        payload, effective_mode, mode_detection = _run_query(
            rag_request,
            answer_provider=answer_provider,
            answer_model=answer_model,
        )
        payload["rfp_filename"] = filename
        payload["rfp_file_type"] = suffix.lstrip(".")
        payload["extracted_text_length"] = len(extracted_text)
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_query_event(
            request=http_request,
            endpoint="/api/rag/query-with-rfp",
            query_text=query_text,
            prompt_source="upload",
            effective_mode=effective_mode,
            category=category,
            organization=None,
            year=None,
            top_k=top_k,
            top_docs=top_docs,
            success=True,
            duration_ms=duration_ms,
            payload=payload,
            extra_json={
                "rfp_filename": filename,
                "rfp_file_type": suffix.lstrip("."),
                "extracted_text_length": len(extracted_text),
                "mode_detection": mode_detection or {},
            },
        )
        return payload
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_query_event(
            request=http_request,
            endpoint="/api/rag/query-with-rfp",
            query_text=query_text,
            prompt_source="upload",
            effective_mode=mode,
            category=category,
            organization=None,
            year=None,
            top_k=top_k,
            top_docs=top_docs,
            success=False,
            duration_ms=duration_ms,
            error_message=str(exc),
            extra_json={"rfp_filename": filename, "rfp_file_type": suffix.lstrip(".")},
        )
        return {
            "success": False,
            "error": str(exc),
            "rfp_filename": filename,
            "documents": [],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 제안서 초안 생성 API
# ─────────────────────────────────────────────────────────────────────────────

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


# ============================================================
# Prompt Analysis API
# ============================================================


class PromptAnalysisRequest(BaseModel):
    query: str


class PromptAnalysisResponse(BaseModel):
    success: bool
    original_query: str
    mode_detection: dict
    extracted_keywords: list
    detected_organization: Optional[str] = None
    detected_project_type: Optional[str] = None
    detected_technologies: list = []
    detected_year: Optional[str] = None
    detected_document_group: Optional[str] = None
    detected_document_category: Optional[str] = None
    suggested_filters: dict = {}
    expanded_query: str


@router.post("/analyze-prompt", response_model=PromptAnalysisResponse)
async def analyze_prompt_endpoint(request: PromptAnalysisRequest):
    """
    사용자 쿼리를 분석하여 검색 의도, 키워드, 필터 정보를 추출한다.

    - 검색 모드 감지 (general, graph_rag, rfp_analysis, bid_project)
    - 발주기관, 프로젝트 유형, 기술 키워드 추출
    - 문서 분류(RFP/제안서/산출물), 문서 카테고리 감지
    - 연도 감지
    - 필터 제안
    - 쿼리 확장
    """
    from app.services.query_expander import analyze_prompt

    try:
        result = analyze_prompt(request.query)
        return PromptAnalysisResponse(success=True, **result)
    except Exception:
        return PromptAnalysisResponse(
            success=False,
            original_query=request.query,
            mode_detection={"mode": "general", "reason": "분석 실패", "matched_keyword": None},
            extracted_keywords=[],
            expanded_query=request.query,
        )


# ============================================================
# Hybrid RAG API (Phase 7)
# ============================================================


class HybridQueryRequest(BaseModel):
    """Hybrid RAG 쿼리 요청."""
    question: str = Field(..., description="사용자 질문")
    source_id: Optional[str] = Field(None, description="Document Source ID")
    expanded_query: Optional[str] = Field(None, description="확장된 검색 질의")
    top_k: int = Field(10, ge=1, le=50, description="각 소스별 최대 결과 수")
    max_results: int = Field(20, ge=1, le=100, description="병합 후 최대 결과 수")
    category: Optional[str] = Field(None, description="문서 카테고리 필터")
    organization: Optional[str] = Field(None, description="기관명 필터")
    year: Optional[str] = Field(None, description="연도 필터")
    document_group: Optional[str] = Field(None, description="문서 그룹 필터")
    document_category: Optional[str] = Field(None, description="문서 세부 분류 필터")
    section_type: Optional[str] = Field(None, description="섹션/목차 필터")
    inferred_organization: Optional[str] = Field(None, description="질문 분석으로 추론한 기관명 힌트")
    inferred_project_type: Optional[str] = Field(None, description="질문 분석으로 추론한 프로젝트 유형 힌트")
    inferred_document_group: Optional[str] = Field(None, description="질문 분석으로 추론한 문서 그룹 힌트")
    inferred_document_category: Optional[str] = Field(None, description="질문 분석으로 추론한 문서 세부 분류 힌트")
    inferred_terms: list[str] = Field(default_factory=list, description="질문 분석으로 추출한 키워드 힌트")
    enable_graph: bool = Field(True, description="GraphRAG 활성화")
    enable_wiki: bool = Field(False, description="Wiki 검색 활성화")
    merge_strategy: str = Field("score_based", description="결과 병합 전략: score_based, faiss_first, graph_first, interleave")
    force_search_order: Optional[str] = Field(None, description="검색 순서 강제값")
    generate_answer: bool = Field(False, description="LLM 답변 생성 여부")


@router.post("/hybrid-query")
async def hybrid_query(request: HybridQueryRequest):
    """
    Hybrid RAG 쿼리 - FAISS + GraphRAG + Wiki 통합 검색.

    여러 검색 소스의 결과를 병합하여 반환한다.

    처리 단계:
    1. FAISS 벡터 검색 (병렬)
    2. GraphRAG Agent 실행 (병렬)
    3. LLM-Wiki 검색 (병렬, 옵션)
    4. 결과 병합 및 중복 제거
    5. Re-ranking
    6. 근거 정보 생성
    7. LLM 답변 생성 (옵션)

    응답 필드:
    - success: 성공 여부
    - question: 원본 질문
    - answer: LLM 생성 답변 (옵션)
    - faiss_results: FAISS 검색 결과
    - graph_results: GraphRAG 검색 결과
    - wiki_results: Wiki 검색 결과 (향후)
    - merged_documents: 병합된 문서 목록
    - graph_cypher: 생성된 Cypher 쿼리
    - graph_retry_count: Graph 쿼리 재시도 횟수
    - evidence: 근거 정보
    """
    from app.services.hybrid_rag_service import get_hybrid_rag_service, MergeStrategy

    # 병합 전략 파싱
    try:
        merge_strategy = MergeStrategy(request.merge_strategy)
    except ValueError:
        merge_strategy = MergeStrategy.SCORE_BASED

    service = get_hybrid_rag_service(
        source_id=request.source_id,
        enable_graph=request.enable_graph,
        enable_wiki=request.enable_wiki,
    )
    service.merge_strategy = merge_strategy

    response = await service.query(
        question=request.question,
        expanded_query=request.expanded_query,
        top_k=request.top_k,
        max_results=request.max_results,
        generate_answer=request.generate_answer,
        category=request.category,
        organization=request.organization,
        year=request.year,
        document_group=request.document_group,
        document_category=request.document_category,
        section_type=request.section_type,
        inferred_organization=request.inferred_organization,
        inferred_project_type=request.inferred_project_type,
        inferred_document_group=request.inferred_document_group,
        inferred_document_category=request.inferred_document_category,
        inferred_terms=request.inferred_terms,
        force_search_order=request.force_search_order,
    )

    # 시연 안정화: Hybrid가 0건이면 classic RAG 결과로 한 번 더 보정한다.
    if response.success and not response.merged_documents:
        from app.services.rag_runtime import run_rag_query

        active_snapshot = service.faiss_service.get_index_stats().get("active_snapshot")
        if active_snapshot:
            classic_payload = run_rag_query(
                query=request.expanded_query or request.question,
                original_query=request.question,
                top_k=max(request.top_k * 4, request.top_k),
                top_docs=request.max_results,
                answer_provider="none",
                answer_model="",
                category=request.category,
                organization=request.organization,
                year=request.year,
                max_chunks_per_doc=3,
                mode="search",
                snapshot=active_snapshot,
                document_group=request.document_group,
                document_category=request.document_category,
                section_type=request.section_type,
            )
            classic_docs = classic_payload.get("documents") or []
            if classic_docs:
                response.faiss_results = [
                    {
                        "document_id": doc.get("document_id"),
                        "score": doc.get("best_score", 0.0),
                        "rank": doc.get("rank", idx + 1),
                        "category": doc.get("category"),
                        "organization": doc.get("organization"),
                        "file_name": doc.get("file_name"),
                        "text_preview": (doc.get("evidence_snippets") or [""])[0],
                        "source": "faiss_classic_fallback",
                        "metadata": {
                            "source_id": doc.get("source_id") or request.source_id,
                            "snapshot_id": doc.get("snapshot") or active_snapshot,
                            "source_path": doc.get("source_path"),
                            "original_source_path": doc.get("original_source_path"),
                            "relative_path": doc.get("relative_path"),
                            "document_group": doc.get("document_group"),
                            "document_category": doc.get("document_category"),
                            "section_label": doc.get("section_label"),
                            "collection_key": doc.get("collection_key"),
                            "fallback_strategy": "classic_rag_query_route_guard",
                        },
                    }
                    for idx, doc in enumerate(classic_docs)
                ]
                response.merged_documents = [
                    {
                        "organization_type": doc.get("organization_type"),
                        "client_type": doc.get("client_type"),
                        "project_type": doc.get("project_type"),
                        "section_type": doc.get("section_type"),
                        "search_keywords": doc.get("search_keywords") or [],
                        "document_id": doc.get("document_id"),
                        "source": "faiss_classic_fallback",
                        "rank": doc.get("rank", idx + 1),
                        "score": doc.get("best_score", 0.0),
                        "ranking_score": doc.get("ranking_score", doc.get("best_score", 0.0)),
                        "faiss_score": doc.get("best_score", 0.0),
                        "graph_score": 0.0,
                        "title": doc.get("project_name"),
                        "category": doc.get("category"),
                        "organization": doc.get("organization"),
                        "file_name": doc.get("file_name"),
                        "text_preview": (doc.get("evidence_snippets") or [""])[0],
                        "chunk_id": None,
                        "source_id": doc.get("source_id") or request.source_id,
                        "dataset_id": None,
                        "snapshot_id": doc.get("snapshot") or active_snapshot,
                        "document_uid": None,
                        "relative_path": doc.get("relative_path"),
                        "source_path": doc.get("source_path"),
                        "page_no": None,
                        "slide_no": None,
                        "section_title": None,
                        "section_id": None,
                        "document_group": doc.get("document_group"),
                        "document_category": doc.get("document_category"),
                        "graph_relations": [],
                        "metadata": {
                            "source_id": doc.get("source_id") or request.source_id,
                            "snapshot_id": doc.get("snapshot") or active_snapshot,
                            "source_path": doc.get("source_path"),
                            "original_source_path": doc.get("original_source_path"),
                            "relative_path": doc.get("relative_path"),
                            "document_group": doc.get("document_group"),
                            "document_category": doc.get("document_category"),
                            "section_type": doc.get("section_type"),
                            "organization_type": doc.get("organization_type"),
                            "client_type": doc.get("client_type"),
                            "project_type": doc.get("project_type"),
                            "search_keywords": doc.get("search_keywords") or [],
                            "section_label": doc.get("section_label"),
                            "collection_key": doc.get("collection_key"),
                            "fallback_strategy": "classic_rag_query_route_guard",
                        },
                    }
                    for idx, doc in enumerate(classic_docs)
                ]
                response.faiss_count = len(response.faiss_results)
                response.merged_count = len(response.merged_documents)
                if "classic_rag_route_guard" not in response.sources_used:
                    response.sources_used.append("classic_rag_route_guard")
                response.evidence.append({
                    "type": "fallback_strategy",
                    "strategy": "classic_rag_query_route_guard",
                    "reason": "hybrid_route_empty_result_guard",
                })

    return {
        "success": response.success,
        "question": response.question,
        "answer": response.answer,
        # 프런트 하위 호환: hybrid 응답도 documents 키를 유지한다.
        "documents": response.merged_documents,

        # 개별 검색 결과
        "faiss_results": response.faiss_results,
        "graph_results": response.graph_results,
        "wiki_results": response.wiki_results,

        # 병합된 결과
        "merged_documents": response.merged_documents,

        # Graph 메타데이터
        "graph_cypher": response.graph_cypher,
        "graph_retry_count": response.graph_retry_count,
        "graph_question_type": response.graph_question_type,

        # 근거
        "evidence": response.evidence,

        # 통계
        "statistics": {
            "faiss_count": response.faiss_count,
            "graph_count": response.graph_count,
            "wiki_count": response.wiki_count,
            "merged_count": response.merged_count,
        },
        "search_order": response.search_order,
        "sources_used": response.sources_used,

        # 타이밍
        "timing": {
            "faiss_time_ms": response.faiss_time_ms,
            "graph_time_ms": response.graph_time_ms,
            "wiki_time_ms": response.wiki_time_ms,
            "merge_time_ms": response.merge_time_ms,
            "total_time_ms": response.total_time_ms,
        },

        "error": response.error,
        "source_id": request.source_id or "all",
        "merge_strategy": request.merge_strategy,
        "applied_filters": {
            "category": request.category,
            "organization": request.organization,
            "year": request.year,
            "document_group": request.document_group,
            "document_category": request.document_category,
            "section_type": request.section_type,
        },
        "applied_hints": {
            "expanded_query": request.expanded_query,
            "inferred_organization": request.inferred_organization,
            "inferred_project_type": request.inferred_project_type,
            "inferred_document_group": request.inferred_document_group,
            "inferred_document_category": request.inferred_document_category,
            "inferred_terms": request.inferred_terms,
        },
        "timestamp": response.timestamp,
        # LLM 추출 핵심 키워드 (하이라이트용)
        "extracted_keywords": response.extracted_keywords,
    }


@router.get("/hybrid-query/stats")
async def hybrid_query_stats(source_id: Optional[str] = None):
    """
    Hybrid RAG 통계 조회.

    FAISS 인덱스, Graph 데이터 상태를 반환한다.
    """
    from app.services.faiss_search_service import get_faiss_search_service
    from app.services.graph_query_service import get_graph_query_service

    faiss_service = get_faiss_search_service(source_id)
    graph_service = get_graph_query_service(source_id)

    faiss_stats = faiss_service.get_index_stats()

    # Graph 캐시는 서비스 내부에서 manifest/mtime 기준으로 자동 갱신한다.
    graph_stats = graph_service.get_graph_stats()

    wiki_project_dir = PROJECT_ROOT / "data" / "wiki" / (source_id or "") / "projects" if source_id else WIKI_PROJECT_DIR
    wiki_available = wiki_project_dir.exists() and any(wiki_project_dir.glob("*.md"))

    return {
        "source_id": source_id or "all",
        "faiss": faiss_stats,
        "graph": graph_stats,
        "hybrid_ready": faiss_stats["loaded"] or graph_stats["loaded"] or wiki_available,
        "search_modes": {
            "faiss_available": faiss_stats["loaded"],
            "graph_available": graph_stats["loaded"],
            "wiki_available": wiki_available,
        },
    }


@router.get("/sources")
async def rag_sources():
    """rag-agent-chatbot / rag-chatbot 드롭다운용 queryable source 목록."""
    rows = list_snapshot_registry()
    by_source: dict[str, dict] = {}

    for row in rows:
        source_id = str(row.get("source_id") or "").strip()
        if not source_id:
            continue
        if not row.get("queryable") and not row.get("is_active"):
            continue

        current = by_source.get(source_id)
        if current is None or (not current.get("is_active") and row.get("is_active")):
            source_record = get_record("document_sources", "source_id", source_id) or {}
            by_source[source_id] = {
                "source_id": source_id,
                "name": source_record.get("source_name") or row.get("snapshot_name") or source_id,
                "dataset_id": row.get("dataset_id") or "",
                "snapshot_id": row.get("snapshot_id") or "",
                "doc_count": int(row.get("document_count") or 0),
                "chunk_count": int(row.get("chunk_count") or 0),
                "is_active": bool(row.get("is_active")),
            }

    items = sorted(
        by_source.values(),
        key=lambda item: (bool(item.get("is_active")), str(item.get("name") or item.get("source_id") or "")),
        reverse=True,
    )
    return {"sources": items}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 10: GraphRAG 통합 제안서 초안 생성 API
# ─────────────────────────────────────────────────────────────────────────────

class ProposalWithGraphRequest(BaseModel):
    """GraphRAG + FAISS + Wiki 통합 제안서 초안 요청."""
    project_name: str = Field(..., min_length=2, description="사업명")
    organization: str = Field("", description="발주기관")
    sections: List[str] = Field(
        default=["overview", "current", "strategy", "schedule", "track", "effect"],
        description="생성할 섹션 목록"
    )
    use_graph: bool = Field(True, description="GraphRAG 검색 사용")
    use_wiki: bool = Field(True, description="Wiki 참조 사용")
    use_faiss: bool = Field(True, description="FAISS 벡터 검색 사용")
    top_k: int = Field(15, ge=1, le=50)
    top_docs: int = Field(4, ge=1, le=10)
    source_id: Optional[str] = None


@router.post("/proposal-with-graph")
async def generate_proposal_with_graph(request: ProposalWithGraphRequest):
    """
    GraphRAG, FAISS, Wiki를 통합하여 제안서 초안을 생성합니다.

    Phase 10 기능:
    1. GraphRAG로 관련 프로젝트/기관 관계 검색
    2. FAISS로 유사 문서 검색
    3. Wiki에서 기관/프로젝트 정보 조회
    4. 통합 근거로 섹션별 초안 생성
    """
    start_time = time.time()

    # 결과 컨테이너
    graph_evidence = []
    faiss_evidence = []
    wiki_evidence = []
    related_projects = []

    # 1. GraphRAG 검색 (기관-프로젝트-문서 관계)
    if request.use_graph:
        try:
            from app.services.graph_query_service import get_graph_query_service
            graph_service = get_graph_query_service(request.source_id)

            # 기관으로 관련 프로젝트 검색
            if request.organization:
                org_query = f"MATCH (o:Organization {{name: '{request.organization}'}})-[:HAS_PROJECT]->(p:Project)-[:HAS_DOCUMENT]->(d:Document) RETURN p.name as project, d.title as document, d.category as category LIMIT 10"
                graph_result = graph_service.execute_cypher(org_query)
                if graph_result.get("results"):
                    for row in graph_result["results"]:
                        related_projects.append({
                            "project": row.get("project", ""),
                            "document": row.get("document", ""),
                            "category": row.get("category", ""),
                        })
                        graph_evidence.append(f"[Graph] 프로젝트: {row.get('project', '')} - 문서: {row.get('document', '')}")

            # 유사 프로젝트 검색
            similar_query = f"MATCH (p:Project)-[:SIMILAR_TO]->(p2:Project) WHERE p.name CONTAINS '{request.project_name[:10]}' RETURN p2.name as similar_project, p2.organization as org LIMIT 5"
            similar_result = graph_service.execute_cypher(similar_query)
            if similar_result.get("results"):
                for row in similar_result["results"]:
                    graph_evidence.append(f"[Graph] 유사사업: {row.get('similar_project', '')} ({row.get('org', '')})")
        except Exception as e:
            graph_evidence.append(f"[Graph 검색 오류: {str(e)[:50]}]")

    # 2. Wiki 검색 (기관별/프로젝트별 위키)
    if request.use_wiki:
        try:
            WIKI_PROJECT_DIR.mkdir(parents=True, exist_ok=True)
            WIKI_ORG_DIR = PROJECT_ROOT / "data" / "wiki" / "organizations"
            WIKI_ORG_DIR.mkdir(parents=True, exist_ok=True)

            # 기관 Wiki 검색
            if request.organization:
                org_slug = re.sub(r"[^\w가-힣]+", "-", request.organization.lower()).strip("-")
                org_wiki_path = WIKI_ORG_DIR / f"{org_slug}.md"
                if org_wiki_path.exists():
                    wiki_content = org_wiki_path.read_text(encoding="utf-8")[:1000]
                    wiki_evidence.append(f"[Wiki-기관] {request.organization}: {wiki_content[:300]}...")

            # 프로젝트 Wiki 검색
            project_slug = re.sub(r"[^\w가-힣]+", "-", request.project_name.lower()).strip("-")
            for wiki_file in WIKI_PROJECT_DIR.glob("*.md"):
                if project_slug[:5] in wiki_file.stem or request.project_name[:5] in wiki_file.read_text(encoding="utf-8")[:200]:
                    wiki_content = wiki_file.read_text(encoding="utf-8")[:500]
                    wiki_evidence.append(f"[Wiki-프로젝트] {wiki_file.stem}: {wiki_content[:200]}...")
                    break
        except Exception as e:
            wiki_evidence.append(f"[Wiki 검색 오류: {str(e)[:50]}]")

    # 3. FAISS 검색 (기존 proposal API 활용)
    if request.use_faiss:
        try:
            # 기본 제안서 API 호출
            base_request = ProposalRequest(
                project_name=request.project_name,
                organization=request.organization,
                sections=request.sections,
                top_k=request.top_k,
                top_docs=request.top_docs,
            )
            faiss_result = await generate_proposal(base_request)
            if faiss_result.get("success") and faiss_result.get("sections"):
                for sec in faiss_result["sections"]:
                    faiss_evidence.append({
                        "section": sec["title"],
                        "draft": sec["draft"],
                        "evidence_count": sec.get("evidence_count", 0),
                    })
        except Exception as e:
            faiss_evidence.append({"error": str(e)[:100]})

    # 4. 통합 응답 구성
    elapsed = round(time.time() - start_time, 2)

    return {
        "success": True,
        "project_name": request.project_name,
        "organization": request.organization,
        "sections": faiss_evidence if faiss_evidence else [],
        "graph_evidence": graph_evidence,
        "wiki_evidence": wiki_evidence,
        "related_projects": related_projects,
        "stats": {
            "graph_count": len(graph_evidence),
            "wiki_count": len(wiki_evidence),
            "faiss_sections": len(faiss_evidence),
            "related_projects": len(related_projects),
            "elapsed_seconds": elapsed,
        },
        "sources_used": {
            "graph": request.use_graph,
            "wiki": request.use_wiki,
            "faiss": request.use_faiss,
        },
    }


@router.get("/related-projects/{organization}")
async def get_related_projects(organization: str, limit: int = 10):
    """특정 기관의 관련 프로젝트와 문서를 GraphRAG로 검색합니다."""
    try:
        from app.services.graph_query_service import get_graph_query_service
        graph_service = get_graph_query_service(None)

        # 기관-프로젝트-문서 관계 검색
        cypher = f"""
        MATCH (o:Organization)-[:HAS_PROJECT]->(p:Project)-[:HAS_DOCUMENT]->(d:Document)
        WHERE o.name CONTAINS '{organization}' OR o.name_ko CONTAINS '{organization}'
        RETURN o.name as organization, p.name as project, p.year as year,
               collect({{title: d.title, category: d.category}})[0..3] as documents
        LIMIT {limit}
        """
        result = graph_service.execute_cypher(cypher)

        return {
            "success": True,
            "organization": organization,
            "projects": result.get("results", []),
            "count": len(result.get("results", [])),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "organization": organization,
            "projects": [],
        }


@router.get("/proposal-sections")
async def get_proposal_sections():
    """사용 가능한 제안서 섹션 목록을 반환합니다."""
    return {
        "sections": [
            {"key": "overview", "title": "사업 개요", "description": "사업 개요, 목적, 배경"},
            {"key": "current", "title": "현황 및 문제점", "description": "현황 분석, 문제점, 개선사항"},
            {"key": "strategy", "title": "추진 전략 및 방법론", "description": "추진 전략, 방법론, 접근방법"},
            {"key": "schedule", "title": "추진 일정", "description": "단계별 일정, 마일스톤"},
            {"key": "track", "title": "유사 수행 실적", "description": "유사 사업 수행실적"},
            {"key": "effect", "title": "기대 효과", "description": "기대 효과, 성과지표"},
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool Calling API - LLM이 도구를 호출하여 데이터 분석/진단을 수행
# ─────────────────────────────────────────────────────────────────────────────

class ToolCallingRequest(BaseModel):
    """Tool Calling 요청 스키마."""
    query: str = Field(..., description="사용자 질문")
    enable_tools: bool = Field(True, description="도구 사용 여부")
    max_tool_calls: int = Field(5, ge=1, le=10, description="최대 도구 호출 횟수")
    model: Optional[str] = Field(None, description="사용할 LLM 모델")
    system_prompt: Optional[str] = Field(None, description="시스템 프롬프트")


@router.post("/query-with-tools")
async def query_with_tools(request: ToolCallingRequest):
    """
    Tool Calling을 사용하여 쿼리를 처리합니다.

    LLM이 필요에 따라 다음 도구를 호출할 수 있습니다:
    - analyze_data_structure: 데이터 구조 분석
    - diagnose_data_quality: 데이터 품질 진단
    - analyze_data_linkage: 데이터 연계 가능성 분석
    - search_documents: RAG 문서 검색
    - query_graph_relations: GraphRAG 관계 조회
    - calculate_statistics: 통계 계산
    - aggregate_by_field: 필드별 집계
    """
    try:
        from app.services.tool_executor import ToolExecutor

        executor = ToolExecutor(model=request.model)

        system_prompt = request.system_prompt or (
            "당신은 데이터 분석 전문가입니다. "
            "사용자의 질문에 답하기 위해 필요한 도구를 호출하고, "
            "결과를 바탕으로 전문적인 분석과 권장사항을 제공하세요. "
            "한국어로 답변하세요."
        )

        if not request.enable_tools:
            result = executor._generate_without_tools(request.query, system_prompt)
        else:
            result = executor.execute_with_tools(
                query=request.query,
                system_prompt=system_prompt,
                max_tool_calls=request.max_tool_calls,
            )

        return {
            "success": True,
            "query": request.query,
            "answer": result.get("answer", ""),
            "tool_calls_count": result.get("tool_calls_count", 0),
            "tool_results": result.get("tool_results", []),
        }

    except Exception as e:
        return {
            "success": False,
            "query": request.query,
            "error": str(e),
            "answer": "",
            "tool_calls_count": 0,
            "tool_results": [],
        }


@router.get("/tools")
async def list_available_tools():
    """사용 가능한 도구 목록을 반환합니다."""
    try:
        from app.services.tool_registry import get_registry

        registry = get_registry()

        # 도구 모듈 로드
        try:
            import app.services.tools  # noqa: F401
        except Exception:
            pass

        tools = []
        for tool_name in registry.list_tools():
            tool = registry.get(tool_name)
            if tool:
                tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                    "required": tool.required,
                })

        return {
            "success": True,
            "tools": tools,
            "total": len(tools),
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "tools": [],
            "total": 0,
        }


@router.post("/tool/{tool_name}")
async def execute_single_tool(tool_name: str, request: Request):
    """단일 도구를 직접 실행합니다."""
    try:
        from app.services.tool_registry import get_registry

        registry = get_registry()

        # 도구 모듈 로드
        try:
            import app.services.tools  # noqa: F401
        except Exception:
            pass

        body = await request.json()
        result = registry.execute(tool_name, body)

        return {
            "success": result.get("success", False),
            "tool": tool_name,
            "result": result.get("result"),
            "error": result.get("error"),
        }

    except Exception as e:
        return {
            "success": False,
            "tool": tool_name,
            "error": str(e),
        }
