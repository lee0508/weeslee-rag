# ISP/ISMP 제안서 섹션별 초안을 FAISS 검색 결과 기반으로 생성하는 스크립트
"""
사용법:
  python generate_proposal_draft.py \\
    --index-path ../../data/indexes/faiss/snapshot_ollama.index \\
    --metadata-path ../../data/indexes/faiss/snapshot_ollama_metadata.jsonl \\
    --chunks-jsonl ../../data/staged/chunks/snapshot_chunks.jsonl \\
    --project-name "차세대 행정업무시스템 ISMP" \\
    --organization "행정안전부" \\
    --output-json result.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import faiss  # type: ignore
except Exception as exc:
    raise SystemExit("faiss-cpu가 필요합니다.") from exc

from build_faiss_index import hashing_embedding, ollama_embedding

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

# 표준 제안서 섹션 정의: (key, 제목, 검색 쿼리 템플릿)
SECTION_TEMPLATES: list[tuple[str, str, str]] = [
    ("overview",    "사업 개요",           "{project_name} 사업 개요 목적 배경"),
    ("current",     "현황 및 문제점",       "{organization} {project_name} 현황 문제점 개선사항"),
    ("strategy",    "추진 전략 및 방법론",   "{project_name} 추진 전략 방법론 접근방법"),
    ("schedule",    "추진 일정",            "{project_name} 추진 일정 단계별 계획"),
    ("track",       "유사 수행 실적",        "{organization} 유사 사업 수행실적 ISP ISMP"),
    ("effect",      "기대 효과",            "{project_name} 기대 효과 성과지표"),
]


@dataclass
class ProposalSection:
    key: str
    title: str
    query: str
    evidence: list[str] = field(default_factory=list)
    draft: str = ""


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="제안서 초안 생성")
    p.add_argument("--index-path",    required=True)
    p.add_argument("--metadata-path", required=True)
    p.add_argument("--chunks-jsonl",  required=True)
    p.add_argument("--project-name",  required=True)
    p.add_argument("--organization",  default="")
    p.add_argument("--category",      default="proposal", help="검색 범위 카테고리")
    p.add_argument("--sections",      default="overview,current,strategy,schedule,track,effect",
                   help="생성할 섹션 key 목록 (쉼표 구분)")
    p.add_argument("--top-k",         type=int, default=15)
    p.add_argument("--top-docs",      type=int, default=4)
    p.add_argument("--embedding-provider", choices=["hashing", "ollama"], default="ollama")
    p.add_argument("--ollama-embed-url",   default="http://127.0.0.1:11434/api/embeddings")
    p.add_argument("--ollama-embed-model", default="")
    p.add_argument("--answer-model",  default="gemma4:latest")
    p.add_argument("--ollama-generate-url", default="http://127.0.0.1:11434/api/generate")
    p.add_argument("--env-file",      default=str(DEFAULT_ENV_FILE))
    p.add_argument("--output-json",   default="")
    return p.parse_args()


def apply_env_defaults(args: argparse.Namespace) -> None:
    if not args.ollama_embed_model:
        args.ollama_embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    host = os.getenv("OLLAMA_HOST", "").strip()
    if host:
        if args.ollama_embed_url == "http://127.0.0.1:11434/api/embeddings":
            args.ollama_embed_url = host.rstrip("/") + "/api/embeddings"
        if args.ollama_generate_url == "http://127.0.0.1:11434/api/generate":
            args.ollama_generate_url = host.rstrip("/") + "/api/generate"
    if not args.answer_model:
        args.answer_model = os.getenv("ANSWER_MODEL", "").strip() or os.getenv("OLLAMA_MODEL", "").strip() or "gemma4:latest"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.open("r", encoding="utf-8"):
        if line.strip():
            rows.append(json.loads(line))
    return rows


def embed(query: str, args: argparse.Namespace) -> np.ndarray:
    if args.embedding_provider == "ollama":
        return ollama_embedding(query, args.ollama_embed_model, args.ollama_embed_url).astype(np.float32)
    return hashing_embedding(query, 768).astype(np.float32)


def search_chunks(
    query: str,
    args: argparse.Namespace,
    index: faiss.Index,
    meta_rows: list[dict],
    chunk_map: dict[str, str],
    category_filter: str,
) -> list[str]:
    """FAISS에서 청크를 검색하고 근거 텍스트 목록을 반환합니다."""
    vec = embed(query, args).reshape(1, -1)
    k = min(args.top_k, index.ntotal)
    distances, indices = index.search(vec, k)

    snippets: list[str] = []
    seen_docs: set[str] = set()
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0 or idx >= len(meta_rows):
            continue
        row = meta_rows[idx]
        if category_filter and row.get("category", "") != category_filter:
            continue
        doc_id = row.get("document_id", "")
        if doc_id in seen_docs:
            continue
        seen_docs.add(doc_id)
        chunk_id = row.get("chunk_id", "")
        text = chunk_map.get(chunk_id, "").strip()
        if text:
            snippets.append(text[:500])
        if len(seen_docs) >= args.top_docs:
            break
    return snippets


def build_section_prompt(
    project_name: str,
    organization: str,
    section: ProposalSection,
) -> str:
    org_line = f"발주기관: {organization}\n" if organization else ""
    evidence_block = "\n".join(
        f"[참고 {i+1}] {ev}" for i, ev in enumerate(section.evidence[:4])
    )
    return (
        "당신은 공공 IT 컨설팅 제안서 전문 작성자입니다.\n"
        "아래 사업 정보와 참고 문서를 바탕으로 제안서의 한 섹션을 작성하세요.\n"
        "한국어로 작성하며, 전문적이고 구체적인 내용으로 500자 이내로 작성하세요.\n\n"
        f"사업명: {project_name}\n"
        f"{org_line}"
        f"섹션: {section.title}\n\n"
        "참고 문서:\n"
        f"{evidence_block}\n\n"
        f"위 참고 내용을 바탕으로 '{section.title}' 섹션을 작성하세요."
    )


def call_ollama(prompt: str, model: str, url: str) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8")).get("response", "").strip()
    except Exception as exc:
        return f"[생성 오류: {exc}]"


def main() -> None:
    args = parse_args()
    load_env_file(Path(args.env_file))
    apply_env_defaults(args)

    # 요청된 섹션 필터링
    requested_keys = {k.strip() for k in args.sections.split(",")}
    sections = [
        ProposalSection(
            key=key,
            title=title,
            query=tmpl.format(project_name=args.project_name, organization=args.organization or args.project_name),
        )
        for key, title, tmpl in SECTION_TEMPLATES
        if key in requested_keys
    ]

    # FAISS 인덱스 + 메타데이터 로드
    index = faiss.read_index(args.index_path)
    meta_rows = load_jsonl(Path(args.metadata_path))

    # 청크 텍스트 맵 구성
    chunk_map: dict[str, str] = {}
    for row in load_jsonl(Path(args.chunks_jsonl)):
        cid = row.get("chunk_id", "")
        if cid:
            chunk_map[cid] = row.get("text", "")

    # 섹션별 검색 → 생성
    for sec in sections:
        sec.evidence = search_chunks(
            sec.query, args, index, meta_rows, chunk_map,
            category_filter=args.category,
        )
        if sec.evidence:
            prompt = build_section_prompt(args.project_name, args.organization, sec)
            sec.draft = call_ollama(prompt, args.answer_model, args.ollama_generate_url)
        else:
            # 카테고리 미필터 재시도
            sec.evidence = search_chunks(
                sec.query, args, index, meta_rows, chunk_map, category_filter="",
            )
            if sec.evidence:
                prompt = build_section_prompt(args.project_name, args.organization, sec)
                sec.draft = call_ollama(prompt, args.answer_model, args.ollama_generate_url)
            else:
                sec.draft = f"[{sec.title} 관련 참고 문서를 찾지 못했습니다.]"

    result = {
        "project_name": args.project_name,
        "organization": args.organization,
        "sections": [
            {
                "key":   s.key,
                "title": s.title,
                "draft": s.draft,
                "evidence_count": len(s.evidence),
            }
            for s in sections
        ],
    }

    out = args.output_json or f"proposal_draft_{re.sub(r'[^\\w]', '_', args.project_name)}.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
