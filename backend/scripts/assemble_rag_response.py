"""
Assemble document-level recommendations and an optional Gemma/Ollama answer
from a FAISS chunk index.

Phase 1 scope:
- Search top-k chunks
- Aggregate hits by document
- Produce document-level recommendation reasons
- Optionally ask an Ollama generation model to draft a concise answer
"""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--ollama-embed-model", default="nomic-embed-text")
    parser.add_argument("--answer-model", default="")
    parser.add_argument("--ollama-generate-url", default="http://127.0.0.1:11434/api/generate")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    return parser.parse_args()


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


def shorten(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit] + "..."


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
    for text in group["sections"] + group["snippets"]:
        lowered = text.lower()
        for term in terms:
            if term in lowered:
                matched_terms.add(term)
    if matched_terms:
        reasons.append("질의 핵심어와 일치: " + ", ".join(sorted(matched_terms)[:5]))

    category = group["category"] or "unknown"
    reasons.append(f"문서 유형: {category}")
    return reasons


def aggregate_hits(query: str, hits: list[SearchHit], top_docs: int) -> list[dict]:
    grouped: dict[str, dict] = {}

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

    ranked = sorted(
        grouped.values(),
        key=lambda item: (item["best_score"], item["hit_count"], item["score_sum"]),
        reverse=True,
    )

    results = []
    for rank, group in enumerate(ranked[:top_docs], start=1):
        results.append(
            {
                "rank": rank,
                "document_id": group["document_id"],
                "category": group["category"],
                "source_path": group["source_path"],
                "input_path": group["input_path"],
                "best_score": group["best_score"],
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
        lines.append(f"  유형: {doc['category']}")
        lines.append(f"  최고점수: {doc['best_score']:.4f}, 히트수: {doc['hit_count']}")
        if doc["section_headings"]:
            lines.append("  관련 섹션: " + " | ".join(doc["section_headings"][:3]))
        for snippet in doc["evidence_snippets"][:2]:
            lines.append("  근거: " + snippet)
        lines.append("  추천사유: " + " / ".join(doc["reasons"]))
    return "\n".join(lines)


def generate_answer(prompt: str, model: str, url: str) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:  # pragma: no cover
        raise RuntimeError(f"Ollama generation request failed: {exc}") from exc
    return data.get("response", "").strip()


def write_markdown(path: Path, query: str, documents: list[dict], answer: str) -> None:
    lines = [f"# RAG Response", "", f"- query: `{query}`", ""]
    if answer:
        lines.extend(["## Draft Answer", "", answer, ""])
    lines.extend(["## Recommended Documents", ""])
    for doc in documents:
        lines.append(f"### {doc['rank']}. {doc['document_id']} ({doc['category']})")
        lines.append(f"- best_score: `{doc['best_score']:.4f}`")
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
    index_path = Path(args.index_path).resolve()
    metadata_path = Path(args.metadata_path).resolve()
    chunks_path = Path(args.chunks_jsonl).resolve()

    hits = build_hits(index_path, metadata_path, chunks_path, args)
    documents = aggregate_hits(args.query, hits, args.top_docs)
    prompt = build_prompt(args.query, documents)
    answer = generate_answer(prompt, args.answer_model, args.ollama_generate_url) if args.answer_model else ""

    payload = {
        "query": args.query,
        "top_k": args.top_k,
        "top_docs": args.top_docs,
        "embedding_provider": args.embedding_provider,
        "answer_model": args.answer_model,
        "documents": documents,
        "draft_answer": answer,
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
