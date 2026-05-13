"""
Assemble document-level recommendations and an optional generated answer
from a FAISS chunk index.

Phase 1 scope:
- Search top-k chunks
- Aggregate hits by document
- Apply lightweight reranking
- Produce document-level recommendation reasons
- Optionally call Ollama/OpenAI/Gemini/OpenRouter for a draft answer
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import faiss  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "faiss is not installed. Install `faiss-cpu` in the target environment before using this script."
    ) from exc

from build_faiss_index import hashing_embedding, ollama_embedding


TERM_PATTERN = re.compile(r"[0-9A-Za-z가-힣_]+")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


@dataclass
class SearchHit:
    rank: int
    score: float
    chunk_id: str
    document_id: str
    category: str
    section_heading: str
    source_path: str
    input_path: str
    chunk_text: str
    organization: str = ""
    folder_year: str = ""


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble a RAG response from FAISS results")
    parser.add_argument("--index-path", required=True)
    parser.add_argument("--metadata-path", required=True)
    parser.add_argument("--chunks-jsonl", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--top-docs", type=int, default=5)
    parser.add_argument("--embedding-provider", choices=["hashing", "ollama"], default="ollama")
    parser.add_argument("--embedding-dim", type=int, default=768)
    parser.add_argument("--ollama-embed-url", default="http://127.0.0.1:11434/api/embeddings")
    parser.add_argument("--ollama-embed-model", default="")
    parser.add_argument("--answer-provider", choices=["ollama", "openai", "gemini", "openrouter", "none"], default="ollama")
    parser.add_argument("--answer-model", default="")
    parser.add_argument("--ollama-generate-url", default="http://127.0.0.1:11434/api/generate")
    parser.add_argument("--openai-url", default="https://api.openai.com/v1/chat/completions")
    parser.add_argument(
        "--gemini-url",
        default="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    )
    parser.add_argument("--openrouter-url", default="https://openrouter.ai/api/v1/chat/completions")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument(
        "--category",
        default="",
        help="Filter results to this category (rfp, proposal, kickoff, final_report, presentation). Empty = no filter.",
    )
    parser.add_argument(
        "--max-chunks-per-doc",
        type=int,
        default=3,
        dest="max_chunks_per_doc",
        help="Max FAISS hits per document (0 = unlimited). Prevents a single large doc from dominating.",
    )
    parser.add_argument(
        "--mode",
        choices=["general", "bid_project", "rfp_analysis", "graph_rag"],
        default="general",
        help="Search mode. graph_rag runs like general but the API layer appends graph context.",
    )
    parser.add_argument(
        "--original-query",
        default="",
        dest="original_query",
        help="Original (unexpanded) query for display and lexical matching.",
    )
    parser.add_argument(
        "--organization",
        default="",
        help="발주기관명 필터 (부분 일치). 예: 행정안전부",
    )
    parser.add_argument(
        "--year",
        default="",
        help="연도 필터 (폴더 연도 기준). 예: 2023",
    )
    return parser.parse_args()


def apply_env_defaults(args: argparse.Namespace) -> None:
    if not args.ollama_embed_model:
        args.ollama_embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    if args.ollama_embed_url == "http://127.0.0.1:11434/api/embeddings":
        host = os.getenv("OLLAMA_HOST", "").strip()
        if host:
            args.ollama_embed_url = host.rstrip("/") + "/api/embeddings"

    if args.ollama_generate_url == "http://127.0.0.1:11434/api/generate":
        host = os.getenv("OLLAMA_HOST", "").strip()
        if host:
            args.ollama_generate_url = host.rstrip("/") + "/api/generate"

    if args.answer_model:
        return

    if args.answer_provider == "ollama":
        args.answer_model = os.getenv("ANSWER_MODEL", "").strip() or os.getenv("OLLAMA_MODEL", "").strip()
    elif args.answer_provider == "openai":
        args.answer_model = os.getenv("OPENAI_MODEL", "").strip() or "gpt-4.1-mini"
    elif args.answer_provider == "gemini":
        args.answer_model = os.getenv("GEMINI_MODEL", "").strip() or "gemini-2.5-flash"
    elif args.answer_provider == "openrouter":
        args.answer_model = os.getenv("OPENROUTER_MODEL", "").strip() or "openai/gpt-4.1-mini"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def query_vector(args: argparse.Namespace) -> np.ndarray:
    if args.embedding_provider == "ollama":
        return ollama_embedding(args.query, args.ollama_embed_model, args.ollama_embed_url).astype(np.float32)
    return hashing_embedding(args.query, args.embedding_dim).astype(np.float32)


def query_terms(text: str) -> list[str]:
    return [term for term in TERM_PATTERN.findall(text.lower()) if len(term) >= 2]


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def shorten(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit] + "..."


def detect_category_intents(query: str) -> set[str]:
    lowered = query.lower()
    intents: set[str] = set()
    mapping = {
        "proposal": ["proposal", "제안서", "입찰", "제안"],
        "rfp": ["rfp", "제안요청서", "과업지시서", "입찰공고"],
        "kickoff": ["kickoff", "착수", "착수계"],
        "final_report": ["final", "final_report", "최종", "종료", "최종보고"],
        "presentation": ["presentation", "발표", "pt"],
    }
    for category, keywords in mapping.items():
        if any(keyword in lowered for keyword in keywords):
            intents.add(category)
    return intents


def lexical_match_score(query: str, terms: list[str], texts: list[str]) -> float:
    corpus = " ".join(texts).lower()
    score = 0.0
    for term in terms:
        if term in corpus:
            score += 1.0
    compact_query = compact_text(query)
    compact_corpus = compact_text(corpus)
    if compact_query and compact_query in compact_corpus:
        score += 2.5
    return score


_DATE_PREFIX = re.compile(r"^\d{4,8}[.\s]+")

# ── Bid-project scoring ───────────────────────────────────────────────────────

_BID_KEYWORDS: dict[str, float] = {
    "isp": 1.0, "ismp": 1.0, "정보화전략계획": 1.0, "정보시스템마스터플랜": 0.8,
    "ai": 0.8, "인공지능": 0.8, "gpt": 0.8, "llm": 0.8, "생성형ai": 0.8, "생성형": 0.6,
    "ax": 0.7, "디지털전환": 0.7, "dx": 0.7, "ai전환": 0.8,
    "플랫폼": 0.5, "고도화": 0.5, "혁신": 0.4, "스마트": 0.3,
    "oda": 0.6, "공적개발원조": 0.6,
    "erp": 0.6, "bpr": 0.6, "클라우드": 0.5, "보안": 0.4,
    "빅데이터": 0.5, "블록체인": 0.5,
}

_BID_CATEGORY_PRIORITY: dict[str, float] = {
    "proposal": 4.0,
    "final_report": 2.5,
    "presentation": 2.0,
    "rfp": 1.5,
    "kickoff": 0.5,
}

# RFP analysis: surface the original RFP and kickoff docs first so the user
# can understand what was asked before looking at how it was answered.
_RFP_CATEGORY_PRIORITY: dict[str, float] = {
    "rfp": 4.5,
    "kickoff": 3.0,
    "proposal": 2.0,
    "presentation": 1.0,
    "final_report": 0.5,
}


def bid_keyword_score(project_name: str, sections: list[str], snippets: list[str], source_path: str) -> float:
    text = " ".join([project_name, source_path] + sections + snippets).lower()
    total = sum(w for kw, w in _BID_KEYWORDS.items() if kw in text)
    return min(total, 3.0)


def extract_project_name(source_path: str) -> str:
    """Extract project folder name from a source_path like 'W:\\...\\202212. k-water ISP\\...'."""
    parts = source_path.replace("\\", "/").split("/")
    for part in parts:
        if _DATE_PREFIX.match(part):
            return _DATE_PREFIX.sub("", part).strip()
    return ""


def project_match_score(query: str, project_name: str) -> float:
    """Bonus when query terms overlap with the project name extracted from source_path."""
    if not project_name:
        return 0.0
    project_terms = set(query_terms(project_name))
    query_term_set = set(query_terms(query))
    overlap = len(project_terms & query_term_set)
    return min(overlap * 0.4, 1.5)


def category_priority_score(category: str, intents: set[str]) -> float:
    priorities = {
        "proposal": 2.5,
        "rfp": 2.0,
        "kickoff": 1.0,
        "presentation": 0.5,
        "final_report": -1.5,
    }
    bonus = priorities.get(category, 0.0)
    if "proposal" in intents and category == "proposal":
        bonus += 1.5
    if "rfp" in intents and category == "rfp":
        bonus += 2.0
    if "final_report" in intents and category == "final_report":
        bonus += 2.0
    return bonus


def filter_by_category(hits: list[SearchHit], category: str) -> list[SearchHit]:
    if not category:
        return hits
    return [h for h in hits if h.category == category]


def filter_by_metadata(hits: list[SearchHit], organization: str, year: str) -> list[SearchHit]:
    """발주기관(부분 일치) 및 연도(정확 일치) 필터."""
    if organization:
        org_lower = organization.lower()
        hits = [h for h in hits if org_lower in h.organization.lower()]
    if year:
        hits = [h for h in hits if h.folder_year == year]
    return hits


def limit_chunks_per_doc(hits: list[SearchHit], max_per_doc: int) -> list[SearchHit]:
    if max_per_doc <= 0:
        return hits
    seen: dict[str, int] = {}
    result = []
    for hit in hits:
        count = seen.get(hit.document_id, 0)
        if count < max_per_doc:
            result.append(hit)
            seen[hit.document_id] = count + 1
    return result


def build_hits(index_path: Path, metadata_path: Path, chunks_path: Path, args: argparse.Namespace) -> list[SearchHit]:
    index = faiss.read_index(str(index_path))
    metadata_rows = load_jsonl(metadata_path)
    chunk_rows = {row["chunk_id"]: row for row in load_jsonl(chunks_path)}
    vector = query_vector(args)
    scores, ids = index.search(np.array([vector], dtype=np.float32), args.top_k)

    hits: list[SearchHit] = []
    for rank, (idx, score) in enumerate(zip(ids[0], scores[0]), start=1):
        if idx < 0 or idx >= len(metadata_rows):
            continue
        row = metadata_rows[idx]
        chunk = chunk_rows.get(row.get("chunk_id", ""), {})
        hits.append(
            SearchHit(
                rank=rank,
                score=float(score),
                chunk_id=row.get("chunk_id", ""),
                document_id=row.get("document_id", ""),
                category=row.get("category", ""),
                section_heading=row.get("section_heading", ""),
                source_path=row.get("source_path", ""),
                input_path=row.get("input_path", ""),
                chunk_text=chunk.get("text", ""),
                organization=row.get("organization", ""),
                folder_year=row.get("folder_year", ""),
            )
        )
    return hits


def reason_list(query: str, group: dict) -> list[str]:
    reasons: list[str] = []
    if group["hit_count"] >= 3:
        reasons.append(f"상위 검색 결과에서 {group['hit_count']}개 chunk가 반복적으로 발견됨")
    reasons.append(f"최고 유사도 점수 {group['best_score']:.4f}")

    terms = query_terms(query)
    matched_terms = set()
    for text in group["sections"] + group["snippets"] + [group["source_path"]]:
        lowered = text.lower()
        for term in terms:
            if term in lowered:
                matched_terms.add(term)
    if matched_terms:
        reasons.append("질의 핵심어와 일치: " + ", ".join(sorted(matched_terms)[:5]))
    if group.get("category_intent_match"):
        reasons.append(f"질의 의도와 문서 유형 일치: {group['category']}")
    if group.get("source_path_match"):
        reasons.append("파일명/경로에 질의 핵심 문자열이 포함됨")
    reasons.append(f"문서 유형: {group['category'] or 'unknown'}")
    return reasons


def aggregate_hits(query: str, hits: list[SearchHit], top_docs: int, mode: str = "general") -> list[dict]:
    grouped: dict[str, dict] = {}
    intents = detect_category_intents(query)
    term_list = query_terms(query)
    compact_query = compact_text(query)
    is_bid = (mode == "bid_project")

    for hit in hits:
        group = grouped.setdefault(
            hit.document_id,
            {
                "document_id": hit.document_id,
                "category": hit.category,
                "source_path": hit.source_path,
                "input_path": hit.input_path,
                "best_score": hit.score,
                "score_sum": 0.0,
                "hit_count": 0,
                "sections": [],
                "snippets": [],
                "source_path_match": False,
                "category_intent_match": False,
            },
        )
        group["best_score"] = max(group["best_score"], hit.score)
        group["score_sum"] += hit.score
        group["hit_count"] += 1
        if hit.section_heading and hit.section_heading not in group["sections"]:
            group["sections"].append(hit.section_heading)
        snippet = shorten(hit.chunk_text)
        if snippet and snippet not in group["snippets"]:
            group["snippets"].append(snippet)
        if compact_query and compact_query in compact_text(hit.source_path):
            group["source_path_match"] = True
        if intents and hit.category in intents:
            group["category_intent_match"] = True

    for group in grouped.values():
        project_name = extract_project_name(group["source_path"])
        group["project_name"] = project_name
        lexical = lexical_match_score(
            query,
            term_list,
            [group["source_path"], *group["sections"], *group["snippets"]],
        )
        category_bonus = 2.0 if group["category_intent_match"] else 0.0
        path_bonus = 2.5 if group["source_path_match"] else 0.0
        hit_bonus = min(group["hit_count"], 5) * 0.15

        if is_bid:
            type_bonus = _BID_CATEGORY_PRIORITY.get(group["category"], 0.0)
            kw_bonus = bid_keyword_score(
                project_name, group["sections"], group["snippets"], group["source_path"]
            )
        elif mode == "rfp_analysis":
            type_bonus = _RFP_CATEGORY_PRIORITY.get(group["category"], 0.0)
            kw_bonus = 0.0
        else:
            type_bonus = category_priority_score(group["category"], intents)
            kw_bonus = 0.0

        project_bonus = project_match_score(query, project_name)
        group["ranking_score"] = (
            (group["best_score"] * 5.0)
            + lexical + category_bonus + path_bonus
            + hit_bonus + type_bonus + project_bonus + kw_bonus
        )

    ranked = sorted(
        grouped.values(),
        key=lambda item: (item["ranking_score"], item["best_score"], item["hit_count"], item["score_sum"]),
        reverse=True,
    )

    results = []
    for rank, group in enumerate(ranked[:top_docs], start=1):
        results.append(
            {
                "rank": rank,
                "document_id": group["document_id"],
                "category": group["category"],
                "project_name": group.get("project_name", ""),
                "source_path": group["source_path"],
                "input_path": group["input_path"],
                "best_score": group["best_score"],
                "ranking_score": group["ranking_score"],
                "hit_count": group["hit_count"],
                "section_headings": group["sections"][:5],
                "evidence_snippets": group["snippets"][:3],
                "reasons": reason_list(query, group),
            }
        )
    return results


def build_prompt(query: str, documents: list[dict]) -> str:
    lines = [
        "당신은 공공/민간 입찰 RFP 분석과 컨설팅 제안서 작성을 지원하는 전문가다.",
        "아래 검색 결과를 바탕으로 사용자의 질의와 가장 관련 있는 과거 문서를 추천하라.",
        "과장하지 말고 근거 중심으로 3개 이하 문서를 추천하라.",
        "출력 형식:",
        "1. 추천 문서",
        "2. 추천 이유",
        "3. 제안서 작성에 바로 활용할 포인트",
        "",
        f"질의: {query}",
        "",
        "검색 결과:",
    ]
    for doc in documents:
        lines.append(f"- 문서ID: {doc['document_id']}")
        lines.append(
            f"  유형: {doc['category']}, 최고점수: {doc['best_score']:.4f}, "
            f"랭킹점수: {doc['ranking_score']:.4f}, 히트수: {doc['hit_count']}"
        )
        if doc["section_headings"]:
            lines.append("  관련 섹션: " + " | ".join(doc["section_headings"][:3]))
        for snippet in doc["evidence_snippets"][:2]:
            lines.append("  근거: " + snippet)
        lines.append("  추천사유: " + " / ".join(doc["reasons"]))
    return "\n".join(lines)


def post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code} calling {url}: {body}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc


def generate_with_ollama(prompt: str, model: str, url: str) -> str:
    data = post_json(
        url,
        {"model": model, "prompt": prompt, "stream": False},
        {"Content-Type": "application/json"},
    )
    return data.get("response", "").strip()


def generate_with_openai(prompt: str, model: str, url: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    data = post_json(
        url,
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        },
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    choices = data.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "").strip()


def generate_with_gemini(prompt: str, model: str, url_template: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    url = url_template.format(model=model) + f"?key={api_key}"
    data = post_json(
        url,
        {"contents": [{"parts": [{"text": prompt}]}]},
        {"Content-Type": "application/json"},
    )
    candidates = data.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [part.get("text", "") for part in parts if part.get("text")]
    return "\n".join(texts).strip()


def generate_with_openrouter(prompt: str, model: str, url: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    data = post_json(
        url,
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        },
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    choices = data.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "").strip()


def generate_answer(prompt: str, args: argparse.Namespace) -> str:
    if not args.answer_model or args.answer_provider == "none":
        return ""
    if args.answer_provider == "ollama":
        return generate_with_ollama(prompt, args.answer_model, args.ollama_generate_url)
    if args.answer_provider == "openai":
        return generate_with_openai(prompt, args.answer_model, args.openai_url)
    if args.answer_provider == "gemini":
        return generate_with_gemini(prompt, args.answer_model, args.gemini_url)
    if args.answer_provider == "openrouter":
        return generate_with_openrouter(prompt, args.answer_model, args.openrouter_url)
    raise RuntimeError(f"Unsupported answer provider: {args.answer_provider}")


def write_markdown(path: Path, query: str, documents: list[dict], answer: str) -> None:
    lines = ["# RAG Response", "", f"- query: `{query}`", ""]
    if answer:
        lines.extend(["## Draft Answer", "", answer, ""])
    lines.extend(["## Recommended Documents", ""])
    for doc in documents:
        lines.append(f"### {doc['rank']}. {doc['document_id']} ({doc['category']})")
        lines.append(f"- best_score: `{doc['best_score']:.4f}`")
        lines.append(f"- ranking_score: `{doc['ranking_score']:.4f}`")
        lines.append(f"- hit_count: `{doc['hit_count']}`")
        lines.append(f"- source_path: `{doc['source_path']}`")
        if doc["section_headings"]:
            lines.append("- section_headings: " + " | ".join(doc["section_headings"]))
        for reason in doc["reasons"]:
            lines.append(f"- reason: {reason}")
        for snippet in doc["evidence_snippets"]:
            lines.append(f"- evidence: {snippet}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    apply_env_defaults(args)

    index_path = Path(args.index_path).resolve()
    metadata_path = Path(args.metadata_path).resolve()
    chunks_path = Path(args.chunks_jsonl).resolve()

    hits = build_hits(index_path, metadata_path, chunks_path, args)
    hits = filter_by_category(hits, args.category)
    hits = filter_by_metadata(hits, args.organization, args.year)
    hits = limit_chunks_per_doc(hits, args.max_chunks_per_doc)
    documents = aggregate_hits(args.query, hits, args.top_docs, args.mode)
    display_query = args.original_query or args.query
    prompt = build_prompt(display_query, documents)
    answer = generate_answer(prompt, args)

    payload = {
        "query": display_query,
        "expanded_query": args.query if args.original_query else None,
        "mode": args.mode,
        "top_k": args.top_k,
        "top_docs": args.top_docs,
        "category_filter": args.category or None,
        "max_chunks_per_doc": args.max_chunks_per_doc,
        "embedding_provider": args.embedding_provider,
        "answer_provider": args.answer_provider,
        "answer_model": args.answer_model,
        "documents": documents,
        "draft_answer": answer,
        # 하위호환 alias — 외부 소비자 및 보고서 스키마용
        "results": [
            {
                "rank": doc["rank"],
                "score": doc["best_score"],
                "file_name": Path(doc["source_path"]).name,
                "project_name": doc.get("project_name", ""),
                "category": doc.get("category", ""),
                "snippet": (doc.get("evidence_snippets") or [""])[0],
                "reason": "; ".join(doc.get("reasons", [])),
                "source_path": doc.get("source_path", ""),
            }
            for doc in documents
        ],
        "answer": answer,
    }

    if args.output_json:
        output_json = Path(args.output_json).resolve()
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.output_md:
        output_md = Path(args.output_md).resolve()
        output_md.parent.mkdir(parents=True, exist_ok=True)
        write_markdown(output_md, args.query, documents, answer)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
