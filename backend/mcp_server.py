# -*- coding: utf-8 -*-
# PromptoRAG MCP 서버 — Claude Code/Cursor에서 문서 검색·그래프 조회 도구 제공
from __future__ import annotations

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = "http://127.0.0.1:8080/api"

mcp = FastMCP("weeslee-rag")


# 작성일: 2026-05-12 | 기능: RAG 검색으로 관련 문서 청크 반환
@mcp.tool()
def search_documents(
    query: str,
    category: str = "",
    top_k: int = 5,
    mode: str = "general",
) -> str:
    """컨설팅 문서 저장소에서 질의와 관련된 문서를 검색합니다.

    Args:
        query: 검색 질의 (한국어 권장)
        category: 문서 카테고리 필터 (rfp/proposal/kickoff/final_report/presentation). 빈 문자열이면 전체 검색.
        top_k: 반환할 최대 문서 수 (기본 5)
        mode: 검색 모드 — general(기본), bid_project(입찰), rfp_analysis(RFP분석), graph_rag(그래프연계)
    """
    payload: dict = {
        "query": query,
        "top_k": top_k * 4,
        "top_docs": top_k,
        "answer_provider": "search_only",
        "mode": mode,
    }
    if category:
        payload["category"] = category

    try:
        resp = httpx.post(f"{BASE_URL}/rag/query", json=payload, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return f"검색 실패: {exc}"

    if not data.get("success"):
        return f"검색 실패: {data.get('error', '알 수 없는 오류')}"

    docs = data.get("documents", [])
    if not docs:
        return "관련 문서를 찾지 못했습니다."

    lines = [f"## 검색 결과 ({len(docs)}건)\n쿼리: {query}\n"]
    for i, doc in enumerate(docs, 1):
        name = doc.get("document_name") or doc.get("document_id", "")
        proj = doc.get("project_name", "")
        cat = doc.get("category", "")
        score = doc.get("score", 0)
        chunk = (doc.get("chunk_text") or "")[:300]
        lines.append(
            f"### {i}. {name}\n"
            f"- 프로젝트: {proj}\n"
            f"- 카테고리: {cat}\n"
            f"- 유사도: {score:.3f}\n"
            f"- 내용 요약:\n{chunk}...\n"
        )

    if mode == "graph_rag":
        graph_ctx = data.get("graph_context", [])
        if graph_ctx:
            lines.append("\n## 관련 프로젝트 문서 체인")
            for proj_chain in graph_ctx:
                lines.append(f"\n### {proj_chain['project_name']}")
                for d in proj_chain.get("related_docs", []):
                    lines.append(f"- [{d['category']}] {d['label']}")

    return "\n".join(lines)


# 작성일: 2026-05-12 | 기능: 프로젝트명으로 문서 체인(RFP→제안→착수→발표→최종) 조회
@mcp.tool()
def get_project_chain(project_name: str) -> str:
    """특정 컨설팅 프로젝트의 전체 문서 체인을 조회합니다.

    Args:
        project_name: 프로젝트명 (list_projects 도구로 정확한 이름 확인 권장)
    """
    try:
        resp = httpx.get(
            f"{BASE_URL}/graph/project/{project_name}",
            timeout=10.0,
        )
        if resp.status_code == 404:
            return f"프로젝트를 찾을 수 없습니다: {project_name}"
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return f"조회 실패: {exc}"

    proj = data.get("project", {})
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    cat_order = ["rfp", "proposal", "kickoff", "presentation", "final_report"]
    doc_nodes = [n for n in nodes if n.get("type") == "document"]
    doc_nodes.sort(
        key=lambda n: cat_order.index(n["category"]) if n.get("category") in cat_order else 99
    )

    lines = [
        f"## 프로젝트: {proj.get('label', project_name)}",
        f"- 연도: {proj.get('year') or '미상'}",
        f"- 발주기관: {proj.get('organization') or '미상'}",
        f"- 문서 수: {proj.get('doc_count', len(doc_nodes))}",
        "",
        "### 문서 목록 (단계순)",
    ]
    for doc in doc_nodes:
        lines.append(f"- [{doc.get('category', '')}] {doc.get('label', '')}")

    seq_edges = [e for e in edges if e.get("relation") == "related_sequence"]
    if seq_edges:
        lines.append("\n### 문서 흐름")
        for e in seq_edges:
            fallback = e["source"] + " -> " + e["target"]
            lines.append(f"- {e.get('label') or fallback}")

    return "\n".join(lines)


# 작성일: 2026-05-12 | 기능: 전체 프로젝트 목록 반환
@mcp.tool()
def list_projects(limit: int = 50) -> str:
    """인덱싱된 컨설팅 프로젝트 목록을 반환합니다.

    Args:
        limit: 최대 반환 수 (기본 50)
    """
    try:
        resp = httpx.get(f"{BASE_URL}/graph/projects", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return f"조회 실패: {exc}"

    projects = data.get("projects", [])[:limit]
    if not projects:
        return "프로젝트가 없습니다. Admin > Graph View에서 Build를 먼저 실행하세요."

    lines = [f"## 컨설팅 프로젝트 목록 ({len(projects)}건)\n"]
    for p in projects:
        year = p.get("year") or "미상"
        org = p.get("organization") or ""
        count = p.get("doc_count", 0)
        org_str = f" ({org})" if org else ""
        lines.append(f"- {p['label']}{org_str} — {year}, 문서 {count}건")

    return "\n".join(lines)


# 작성일: 2026-05-12 | 기능: 문서 그래프 전체 통계 반환
@mcp.tool()
def graph_summary() -> str:
    """문서 그래프의 전체 통계 정보를 반환합니다."""
    try:
        resp = httpx.get(f"{BASE_URL}/graph/summary", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return f"조회 실패: {exc}"

    built_at = data.get("built_at") or "미상"
    source = data.get("source_type") or "미상"
    return (
        f"## 문서 그래프 현황\n"
        f"- 마지막 빌드: {built_at}\n"
        f"- 소스 타입: {source}\n"
        f"- 프로젝트 수: {data.get('project_count', 0)}\n"
        f"- 문서 수: {data.get('document_count', 0)}\n"
        f"- 엣지 수: {data.get('edge_count', 0)}\n"
        f"- 데이터 존재: {'예' if data.get('has_data') else '아니오'}"
    )


if __name__ == "__main__":
    mcp.run()
