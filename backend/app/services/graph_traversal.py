# 그래프 탐색 서비스: 문서 간 관계 기반 복합 쿼리 처리
# -*- coding: utf-8 -*-
"""
Graph traversal service for document relationship queries.

Provides:
- get_related_documents: 문서의 관련 문서 체인 조회 (동일 프로젝트 내)
- expand_with_graph: FAISS 결과에 그래프 컨텍스트 추가
- parse_compound_query: 복합 쿼리 파싱 (프로젝트/기관 + 문서유형)

Knowledge Graph 확장:
- query_by_organization: 기관명으로 프로젝트 검색 (동의어 지원)
- query_by_technology: 기술 키워드로 프로젝트 검색
- query_by_methodology: 방법론으로 프로젝트 검색
- query_similar_projects: 유사 프로젝트 검색 (다중 조건)
- query_project_documents: 프로젝트의 문서 체인 조회
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GRAPH_DIR = PROJECT_ROOT / "data" / "indexes" / "graph"

# 그래프 캐시 (mtime 기반 무효화)
_cache: dict = {"nodes": [], "edges": [], "mtime": 0.0, "by_id": {}, "by_project": {}}


def _load_graph() -> None:
    """그래프 데이터 로드 (캐시)."""
    nodes_path = GRAPH_DIR / "graph_nodes.jsonl"
    edges_path = GRAPH_DIR / "graph_edges.jsonl"
    if not nodes_path.exists():
        _cache["nodes"] = []
        _cache["edges"] = []
        _cache["mtime"] = 0.0
        _cache["by_id"] = {}
        _cache["by_project"] = {}
        return

    mtime = nodes_path.stat().st_mtime
    if mtime == _cache["mtime"]:
        return

    nodes = [json.loads(l) for l in nodes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    edges = []
    if edges_path.exists():
        edges = [json.loads(l) for l in edges_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    _cache["nodes"] = nodes
    _cache["edges"] = edges
    _cache["mtime"] = mtime

    # 인덱스 빌드
    _cache["by_id"] = {n["id"]: n for n in nodes}
    _cache["by_project"] = {}
    for n in nodes:
        if n.get("type") == "document":
            proj = n.get("project_name", "")
            if proj not in _cache["by_project"]:
                _cache["by_project"][proj] = []
            _cache["by_project"][proj].append(n)


def get_related_documents(
    project_name: str,
    current_doc_id: Optional[str] = None,
    category_filter: Optional[str] = None,
) -> list[dict]:
    """
    동일 프로젝트 내 관련 문서 목록 조회.

    Args:
        project_name: 프로젝트명
        current_doc_id: 현재 문서 ID (제외)
        category_filter: 특정 카테고리만 필터링 (예: "kickoff", "proposal")

    Returns:
        관련 문서 리스트 [{document_id, category, label, source_path, sequence_order}]
    """
    _load_graph()

    docs = _cache["by_project"].get(project_name, [])
    if not docs:
        return []

    # 카테고리 순서 (sequence edge 기반)
    category_order = {"rfp": 0, "proposal": 1, "kickoff": 2, "presentation": 3, "final_report": 4}

    result = []
    for doc in docs:
        doc_id = doc.get("document_id", "")
        if current_doc_id and doc_id == current_doc_id:
            continue

        cat = doc.get("category", "")
        if category_filter and cat != category_filter:
            continue

        result.append({
            "document_id": doc_id,
            "category": cat,
            "label": doc.get("label", ""),
            "source_path": doc.get("source_path", ""),
            "sequence_order": category_order.get(cat, 99),
        })

    result.sort(key=lambda x: x["sequence_order"])
    return result


def get_document_chain(project_name: str) -> list[dict]:
    """
    프로젝트의 문서 체인 조회 (RFP → 제안서 → 착수 → 발표 → 최종).

    Returns:
        [{category, documents: [{document_id, label, source_path}]}]
    """
    _load_graph()

    docs = _cache["by_project"].get(project_name, [])
    if not docs:
        return []

    category_order = ["rfp", "proposal", "kickoff", "presentation", "final_report"]
    by_category: dict[str, list[dict]] = {cat: [] for cat in category_order}

    for doc in docs:
        cat = doc.get("category", "")
        if cat in by_category:
            by_category[cat].append({
                "document_id": doc.get("document_id", ""),
                "label": doc.get("label", ""),
                "source_path": doc.get("source_path", ""),
            })

    chain = []
    for cat in category_order:
        if by_category[cat]:
            chain.append({"category": cat, "documents": by_category[cat]})

    return chain


def expand_with_graph(faiss_results: list[dict]) -> dict:
    """
    FAISS 검색 결과에 그래프 컨텍스트 추가.

    Args:
        faiss_results: FAISS 검색 결과 문서 리스트

    Returns:
        {
            documents: [...],  # 원본 + 그래프 정보 추가
            graph_context: [{project_name, chain: [...]}]
        }
    """
    _load_graph()

    # 검색 결과에서 프로젝트 추출
    found_projects: set[str] = set()
    for doc in faiss_results:
        proj = doc.get("project_name", "")
        if proj:
            found_projects.add(proj)

    # 각 프로젝트의 문서 체인 조회
    graph_context = []
    for proj in found_projects:
        chain = get_document_chain(proj)
        if chain:
            graph_context.append({"project_name": proj, "chain": chain})

    # 문서에 관련 문서 정보 추가
    enriched_docs = []
    for doc in faiss_results:
        proj = doc.get("project_name", "")
        doc_id = doc.get("document_id", "")
        related = get_related_documents(proj, current_doc_id=doc_id) if proj else []
        enriched_doc = {**doc, "related_documents": related[:5]}  # 최대 5개
        enriched_docs.append(enriched_doc)

    return {"documents": enriched_docs, "graph_context": graph_context}


# ── 복합 쿼리 파싱 ────────────────────────────────────────────────────────────

# 기관명 패턴
_ORG_PATTERNS = [
    r"(K-water|한국수자원공사|수자원공사|수공)",
    r"(기상청|기상산업진흥원)",
    r"(행정안전부|행안부)",
    r"(보건복지부|복지부)",
    r"(국토교통부|국토부)",
    r"(환경부)",
    r"(과학기술정보통신부|과기정통부)",
]

# 문서 유형 패턴
_DOC_TYPE_PATTERNS = {
    "rfp": r"(RFP|제안요청서|과업지시서)",
    "proposal": r"(제안서|proposal)",
    "kickoff": r"(착수보고|착수|kickoff)",
    "interim": r"(중간보고|interim)",
    "final_report": r"(최종보고|결과보고|final)",
    "presentation": r"(발표|PT|프레젠테이션)",
}

# 프로젝트 유형 패턴
_PROJECT_TYPE_PATTERNS = {
    "isp": r"(ISP|정보화전략계획)",
    "ismp": r"(ISMP|정보시스템마스터플랜)",
    "ai": r"(AI|인공지능)",
    "ax": r"(AX|AI전환)",
    "dx": r"(DX|디지털전환)",
    "oda": r"(ODA|공적개발원조)",
}


def parse_compound_query(query: str) -> dict:
    """
    복합 쿼리 파싱.

    예시 입력:
    - "K-water ISP 제안서의 착수보고서"
    - "기상청 AI 프로젝트 최종보고"

    Returns:
        {
            organization: "K-water" | None,
            project_type: "isp" | None,
            source_doc_type: "proposal" | None,  # "~의" 앞
            target_doc_type: "kickoff" | None,   # "~의" 뒤 (찾고자 하는 문서)
            keywords: ["ISP", ...]
        }
    """
    result = {
        "organization": None,
        "project_type": None,
        "source_doc_type": None,
        "target_doc_type": None,
        "keywords": [],
    }

    # 기관명 추출
    for pattern in _ORG_PATTERNS:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            result["organization"] = match.group(1)
            break

    # 프로젝트 유형 추출
    for ptype, pattern in _PROJECT_TYPE_PATTERNS.items():
        if re.search(pattern, query, re.IGNORECASE):
            result["project_type"] = ptype
            break

    # "A의 B" 패턴 파싱 (A=source, B=target)
    relation_match = re.search(r"(.+?)의\s+(.+)", query)
    if relation_match:
        source_part = relation_match.group(1)
        target_part = relation_match.group(2)

        # source 문서 유형
        for dtype, pattern in _DOC_TYPE_PATTERNS.items():
            if re.search(pattern, source_part, re.IGNORECASE):
                result["source_doc_type"] = dtype
                break

        # target 문서 유형
        for dtype, pattern in _DOC_TYPE_PATTERNS.items():
            if re.search(pattern, target_part, re.IGNORECASE):
                result["target_doc_type"] = dtype
                break
    else:
        # 관계 패턴 없으면 전체에서 문서 유형 추출
        for dtype, pattern in _DOC_TYPE_PATTERNS.items():
            if re.search(pattern, query, re.IGNORECASE):
                result["target_doc_type"] = dtype
                break

    return result


def search_with_graph(
    parsed_query: dict,
    faiss_results: list[dict],
) -> list[dict]:
    """
    파싱된 복합 쿼리와 FAISS 결과를 결합하여 그래프 기반 검색 수행.

    1. FAISS 결과에서 조건에 맞는 프로젝트 필터링
    2. 그래프에서 해당 프로젝트의 target_doc_type 문서 조회
    3. 결과 반환

    Args:
        parsed_query: parse_compound_query() 결과
        faiss_results: FAISS 검색 결과

    Returns:
        그래프 기반 검색 결과 문서 리스트
    """
    _load_graph()

    org_filter = parsed_query.get("organization")
    source_type = parsed_query.get("source_doc_type")
    target_type = parsed_query.get("target_doc_type")

    # FAISS 결과에서 프로젝트 추출
    candidate_projects: set[str] = set()
    for doc in faiss_results:
        proj = doc.get("project_name", "")
        doc_org = doc.get("organization", "")
        doc_cat = doc.get("category", "")

        # 기관 필터
        if org_filter and org_filter.lower() not in doc_org.lower():
            continue

        # source 문서 유형 필터 (A의 B에서 A)
        if source_type and doc_cat != source_type:
            continue

        if proj:
            candidate_projects.add(proj)

    # 각 프로젝트에서 target 문서 유형 조회
    result_docs = []
    for proj in candidate_projects:
        if target_type:
            related = get_related_documents(proj, category_filter=target_type)
        else:
            related = get_related_documents(proj)

        for rel in related:
            # 그래프 노드에서 추가 정보 조회
            doc_node = _cache["by_id"].get(f"doc:{rel['document_id']}", {})
            result_docs.append({
                "document_id": rel["document_id"],
                "category": rel["category"],
                "label": rel["label"],
                "source_path": rel["source_path"],
                "project_name": proj,
                "graph_source": True,  # 그래프에서 찾은 결과임을 표시
            })

    return result_docs


# ── 유사 프로젝트 검색 (개선방안 5) ────────────────────────────────────────────────


def find_similar_projects(project_name: str, top_k: int = 5) -> list[dict]:
    """
    유사 프로젝트 검색 (그래프 기반).

    Args:
        project_name: 기준 프로젝트명
        top_k: 반환할 최대 유사 프로젝트 수

    Returns:
        [{project_name, organization, year, similarity_reason, weight}]
    """
    _load_graph()

    proj_id = f"project:{project_name}"
    proj_node = _cache["by_id"].get(proj_id)
    if not proj_node:
        return []

    # similar_project 엣지 조회
    similar_edges = [
        e for e in _cache["edges"]
        if e.get("relation") == "similar_project"
        and (e["source"] == proj_id or e["target"] == proj_id)
    ]

    results = []
    for edge in similar_edges:
        other_id = edge["target"] if edge["source"] == proj_id else edge["source"]
        other_node = _cache["by_id"].get(other_id, {})
        if other_node.get("type") != "project":
            continue

        results.append({
            "project_name": other_node.get("label", ""),
            "organization": other_node.get("organization", ""),
            "year": other_node.get("year", ""),
            "similarity_reason": edge.get("label", ""),
            "weight": edge.get("weight", 0),
        })

    # weight 기준 정렬
    results.sort(key=lambda x: x["weight"], reverse=True)
    return results[:top_k]


def get_project_info(project_name: str) -> dict:
    """
    프로젝트 정보 조회.

    Returns:
        {
            "project_name": str,
            "organization": str,
            "year": str,
            "doc_count": int,
            "categories": [str],
            "similar_projects": [{...}],
            "document_chain": [{category, documents}]
        }
    """
    _load_graph()

    proj_id = f"project:{project_name}"
    proj_node = _cache["by_id"].get(proj_id)
    if not proj_node:
        return {}

    # 문서 체인
    chain = get_document_chain(project_name)

    # 유사 프로젝트
    similar = find_similar_projects(project_name, top_k=5)

    # 카테고리 목록
    docs = _cache["by_project"].get(project_name, [])
    categories = list(set(d.get("category", "") for d in docs if d.get("category")))

    return {
        "project_name": project_name,
        "organization": proj_node.get("organization", ""),
        "year": proj_node.get("year", ""),
        "doc_count": proj_node.get("doc_count", len(docs)),
        "categories": categories,
        "similar_projects": similar,
        "document_chain": chain,
    }


# ── Knowledge Graph 확장 쿼리 ────────────────────────────────────────────────────


def query_by_organization(org_name: str, category_filter: Optional[str] = None) -> dict:
    """
    기관명으로 프로젝트 및 문서 검색 (동의어 지원).

    질문 예시: "한국수자원공사와 관련된 과거 수행사업은?"

    Args:
        org_name: 기관명 (동의어 자동 확장)
        category_filter: 문서 카테고리 필터 (proposal, final_report 등)

    Returns:
        {
            "organization": 정규화된 기관명,
            "synonyms": [동의어 목록],
            "projects": [{project_name, year, doc_count, documents}],
            "total_projects": int,
            "total_documents": int
        }
    """
    from app.services.knowledge_graph import normalize_organization, get_organization_synonyms

    _load_graph()

    canonical = normalize_organization(org_name)
    synonyms = get_organization_synonyms(org_name)
    org_id = f"org:{canonical}"

    # 발주 엣지를 통해 프로젝트 조회
    projects = []
    for edge in _cache["edges"]:
        if edge.get("relation") == "발주" and edge["source"] == org_id:
            proj_id = edge["target"]
            proj_node = _cache["by_id"].get(proj_id)
            if proj_node and proj_node.get("type") == "project":
                proj_name = proj_node.get("label", "")
                docs = _cache["by_project"].get(proj_name, [])

                # 카테고리 필터 적용
                if category_filter:
                    docs = [d for d in docs if d.get("category") == category_filter]

                if docs or not category_filter:
                    projects.append({
                        "project_name": proj_name,
                        "year": proj_node.get("year", ""),
                        "doc_count": len(docs),
                        "documents": [
                            {
                                "document_id": d.get("document_id"),
                                "label": d.get("label"),
                                "category": d.get("category"),
                                "source_path": d.get("source_path"),
                            }
                            for d in docs[:10]
                        ],
                    })

    # 연도 기준 정렬
    projects.sort(key=lambda x: x.get("year", "") or "", reverse=True)

    total_docs = sum(p["doc_count"] for p in projects)

    return {
        "organization": canonical,
        "synonyms": synonyms,
        "projects": projects,
        "total_projects": len(projects),
        "total_documents": total_docs,
    }


def query_by_methodology(method_name: str) -> dict:
    """
    방법론으로 프로젝트 검색.

    질문 예시: "ISP 방법론이 적용된 사업들은?"

    Args:
        method_name: 방법론명 (ISP, ISMP, EA 등)

    Returns:
        {
            "methodology": 정규화된 방법론명,
            "synonyms": [동의어 목록],
            "projects": [{project_name, organization, year}]
        }
    """
    from app.services.knowledge_graph import normalize_methodology, METHODOLOGY_SYNONYMS

    _load_graph()

    canonical = normalize_methodology(method_name)
    synonyms = METHODOLOGY_SYNONYMS.get(canonical, [])
    method_id = f"method:{canonical}"

    projects = []
    for edge in _cache["edges"]:
        if edge.get("relation") == "사용방법론" and edge["target"] == method_id:
            proj_id = edge["source"]
            proj_node = _cache["by_id"].get(proj_id)
            if proj_node and proj_node.get("type") == "project":
                projects.append({
                    "project_name": proj_node.get("label", ""),
                    "organization": proj_node.get("organization", ""),
                    "year": proj_node.get("year", ""),
                    "doc_count": proj_node.get("doc_count", 0),
                })

    projects.sort(key=lambda x: x.get("year", "") or "", reverse=True)

    return {
        "methodology": canonical,
        "synonyms": synonyms,
        "projects": projects,
        "total_projects": len(projects),
    }


def query_by_technologies(tech_names: list[str], match_all: bool = True) -> dict:
    """
    기술 키워드로 프로젝트 검색.

    질문 예시: "AI OCR, RAG, 클라우드, 빅데이터가 포함된 제안서는?"

    Args:
        tech_names: 기술 키워드 목록
        match_all: True면 모든 기술 포함 (AND), False면 하나라도 포함 (OR)

    Returns:
        {
            "technologies": [정규화된 기술명],
            "match_mode": "AND" | "OR",
            "projects": [{project_name, matched_techs, documents}]
        }
    """
    from app.services.knowledge_graph import normalize_technology

    _load_graph()

    normalized_techs = [normalize_technology(t) for t in tech_names]
    tech_ids = [f"tech:{t}" for t in normalized_techs]

    # 프로젝트별 적용 기술 수집
    proj_techs: dict[str, set[str]] = {}
    for edge in _cache["edges"]:
        if edge.get("relation") == "적용기술" and edge["target"] in tech_ids:
            proj_id = edge["source"]
            if proj_id not in proj_techs:
                proj_techs[proj_id] = set()
            proj_techs[proj_id].add(edge["target"].replace("tech:", ""))

    # 조건에 맞는 프로젝트 필터링
    projects = []
    for proj_id, techs in proj_techs.items():
        if match_all:
            if not set(normalized_techs).issubset(techs):
                continue
        # OR 모드는 이미 하나라도 있으면 포함됨

        proj_node = _cache["by_id"].get(proj_id)
        if not proj_node or proj_node.get("type") != "project":
            continue

        proj_name = proj_node.get("label", "")
        docs = _cache["by_project"].get(proj_name, [])

        # 제안서만 필터링 (질문 맥락)
        proposal_docs = [d for d in docs if d.get("category") == "proposal"]

        projects.append({
            "project_name": proj_name,
            "organization": proj_node.get("organization", ""),
            "matched_techs": list(techs),
            "match_count": len(techs),
            "documents": [
                {
                    "document_id": d.get("document_id"),
                    "label": d.get("label"),
                    "category": d.get("category"),
                }
                for d in proposal_docs[:5]
            ],
        })

    # 매칭 기술 수 기준 정렬
    projects.sort(key=lambda x: x["match_count"], reverse=True)

    return {
        "technologies": normalized_techs,
        "match_mode": "AND" if match_all else "OR",
        "projects": projects,
        "total_projects": len(projects),
    }


def query_similar_to_organization(org_name: str, top_k: int = 5) -> dict:
    """
    특정 기관의 사업과 유사한 프로젝트 검색.

    질문 예시: "경기주택도시공사 사업과 유사한 회사 문서는?"

    유사도 기준:
    - 동일 기관 유형 (공사, 공단 등)
    - 유사 기술 스택
    - 유사 도메인

    Args:
        org_name: 기관명
        top_k: 반환할 유사 프로젝트 수

    Returns:
        {
            "source_organization": 기관명,
            "source_projects": [{프로젝트 정보}],
            "similar_projects": [{프로젝트, 유사도_이유, 점수}]
        }
    """
    from app.services.knowledge_graph import normalize_organization

    _load_graph()

    canonical = normalize_organization(org_name)
    org_id = f"org:{canonical}"

    # 해당 기관의 프로젝트 조회
    source_projects = []
    source_techs: set[str] = set()
    source_domains: set[str] = set()

    for edge in _cache["edges"]:
        if edge.get("relation") == "발주" and edge["source"] == org_id:
            proj_id = edge["target"]
            proj_node = _cache["by_id"].get(proj_id)
            if proj_node:
                source_projects.append({
                    "project_name": proj_node.get("label"),
                    "year": proj_node.get("year"),
                })

                # 해당 프로젝트의 기술/도메인 수집
                for e2 in _cache["edges"]:
                    if e2["source"] == proj_id:
                        if e2.get("relation") == "적용기술":
                            source_techs.add(e2["target"])
                        elif e2.get("relation") == "관련도메인":
                            source_domains.add(e2["target"])

    # 다른 기관의 프로젝트 중 유사한 것 찾기
    similar_candidates = []

    for node in _cache["nodes"]:
        if node.get("type") != "project":
            continue
        proj_id = node["id"]

        # 같은 기관의 프로젝트는 제외
        is_same_org = False
        for edge in _cache["edges"]:
            if edge.get("relation") == "발주" and edge["target"] == proj_id:
                if edge["source"] == org_id:
                    is_same_org = True
                    break
        if is_same_org:
            continue

        # 기술/도메인 유사도 계산
        proj_techs: set[str] = set()
        proj_domains: set[str] = set()
        proj_org = ""

        for edge in _cache["edges"]:
            if edge["source"] == proj_id:
                if edge.get("relation") == "적용기술":
                    proj_techs.add(edge["target"])
                elif edge.get("relation") == "관련도메인":
                    proj_domains.add(edge["target"])
            elif edge["target"] == proj_id and edge.get("relation") == "발주":
                proj_org = edge["source"].replace("org:", "")

        tech_overlap = len(source_techs & proj_techs)
        domain_overlap = len(source_domains & proj_domains)
        score = tech_overlap * 0.6 + domain_overlap * 0.4

        if score > 0:
            reasons = []
            if tech_overlap > 0:
                common_techs = [t.replace("tech:", "") for t in (source_techs & proj_techs)]
                reasons.append(f"공통기술: {', '.join(common_techs[:3])}")
            if domain_overlap > 0:
                common_domains = [d.replace("domain:", "") for d in (source_domains & proj_domains)]
                reasons.append(f"공통도메인: {', '.join(common_domains[:2])}")

            similar_candidates.append({
                "project_name": node.get("label"),
                "organization": proj_org,
                "year": node.get("year", ""),
                "similarity_reason": "; ".join(reasons),
                "score": score,
            })

    # 점수순 정렬
    similar_candidates.sort(key=lambda x: x["score"], reverse=True)

    return {
        "source_organization": canonical,
        "source_projects": source_projects,
        "similar_projects": similar_candidates[:top_k],
    }


def query_project_document_chain(org_name: str, project_name: Optional[str] = None) -> dict:
    """
    특정 기관의 제안서, 완료보고서, 발표자료 연결 조회.

    질문 예시: "특정 기관의 제안서, 완료보고서, 발표자료는 어떻게 연결되는가?"

    Args:
        org_name: 기관명
        project_name: 특정 프로젝트명 (없으면 전체)

    Returns:
        {
            "organization": 기관명,
            "projects": [{
                "project_name": str,
                "document_chain": [{category, seq, documents}]
            }]
        }
    """
    from app.services.knowledge_graph import normalize_organization

    _load_graph()

    canonical = normalize_organization(org_name)
    org_id = f"org:{canonical}"

    result_projects = []

    for edge in _cache["edges"]:
        if edge.get("relation") == "발주" and edge["source"] == org_id:
            proj_id = edge["target"]
            proj_node = _cache["by_id"].get(proj_id)
            if not proj_node:
                continue

            proj_name = proj_node.get("label", "")

            # 특정 프로젝트 필터
            if project_name and proj_name != project_name:
                continue

            chain = get_document_chain(proj_name)

            result_projects.append({
                "project_name": proj_name,
                "year": proj_node.get("year", ""),
                "document_chain": chain,
            })

    return {
        "organization": canonical,
        "projects": result_projects,
    }


def get_graph_statistics() -> dict:
    """
    Knowledge Graph 전체 통계.

    Returns:
        노드/엣지 타입별 카운트
    """
    _load_graph()

    node_types: dict[str, int] = {}
    edge_types: dict[str, int] = {}

    for node in _cache["nodes"]:
        ntype = node.get("type", "unknown")
        node_types[ntype] = node_types.get(ntype, 0) + 1

    for edge in _cache["edges"]:
        rel = edge.get("relation", "unknown")
        edge_types[rel] = edge_types.get(rel, 0) + 1

    return {
        "total_nodes": len(_cache["nodes"]),
        "total_edges": len(_cache["edges"]),
        "node_types": node_types,
        "edge_types": edge_types,
    }
