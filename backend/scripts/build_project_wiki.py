#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project Wiki Generator

Generates structured markdown wiki pages for consulting projects by:
1. Querying the RAG API per project + category to collect evidence snippets
2. Calling Ollama directly to generate a structured wiki summary
3. Saving markdown files to data/wiki/projects/

Usage:
    python backend/scripts/build_project_wiki.py
    python backend/scripts/build_project_wiki.py --project k-water
    python backend/scripts/build_project_wiki.py --all
    python backend/scripts/build_project_wiki.py --list
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WIKI_DIR = PROJECT_ROOT / "data" / "wiki" / "projects"
INVENTORY_PATH = PROJECT_ROOT / "data" / "staged" / "project_inventory.json"

RAG_API_BASE = "http://192.168.0.207:8080"
OLLAMA_BASE = "http://192.168.0.207:11434"
OLLAMA_MODEL = "gemma3:4b"   # fast; fallback to gemma4:latest if missing

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

CATEGORY_KO = {
    "rfp": "제안요청서 (RFP)",
    "proposal": "제안서",
    "kickoff": "착수보고",
    "final_report": "최종보고",
    "presentation": "발표자료",
}

CATEGORY_QUERY_SUFFIX = {
    "rfp": "RFP 제안요청서 요구사항 과업범위",
    "proposal": "제안서 추진전략 방법론",
    "kickoff": "착수보고 추진계획 WBS 일정",
    "final_report": "최종보고 결과 로드맵 성과",
    "presentation": "발표 슬라이드 요약 방향",
}

# Target projects: folder_name → wiki metadata
TARGET_PROJECTS: dict[str, dict] = {
    "202212. k-water 데이터허브플랫폼_ISP": {
        "slug": "k-water-isp",
        "display_name": "k-water 데이터허브플랫폼 ISP",
        "organization": "한국수자원공사 (k-water)",
        "year": "2022",
        "project_type": "ISP (정보화전략계획)",
        "search_name": "k-water 데이터허브 플랫폼 ISP 정보화전략계획",
    },
    "202603. AX기반의 차세대 업무 시스템 구축을 위한 ISMP": {
        "slug": "ax-ismp",
        "display_name": "AX기반 차세대 업무시스템 구축 ISMP",
        "organization": "위즐리앤컴퍼니 (내부)",
        "year": "2026",
        "project_type": "ISMP (정보화전략마스터플랜)",
        "search_name": "AX기반 차세대 업무시스템 ISMP 구축",
    },
    "202312. 법무부_디지털플랫폼 교육강화, 환경개선 로드맵 연구사업": {
        "slug": "moj-digital-platform",
        "display_name": "법무부 디지털플랫폼 교육강화 로드맵",
        "organization": "법무부",
        "year": "2023",
        "project_type": "연구사업 (로드맵)",
        "search_name": "법무부 디지털플랫폼 교육강화 환경개선 로드맵",
    },
}


def _http_post(url: str, payload: dict, timeout: int = 60) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return json.loads(r.read())


def _http_get(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return json.loads(r.read())


def get_active_snapshot() -> str:
    try:
        return _http_get(f"{RAG_API_BASE}/api/admin/stats").get("snapshot", "unknown")
    except Exception:
        return "unknown"


def query_rag_for_project(
    project_name: str, category: str, top_docs: int = 3, timeout: int = 45
) -> list[dict]:
    """Search RAG for a specific project+category and return document results."""
    query = f"{project_name} {CATEGORY_QUERY_SUFFIX.get(category, '')}"
    mode = "rfp_analysis" if category == "rfp" else "bid_project"

    payload = {
        "query": query,
        "top_k": 20,
        "top_docs": top_docs,
        "answer_provider": "none",
        "mode": mode,
        "category": category,
        "max_chunks_per_doc": 3,
    }
    try:
        result = _http_post(f"{RAG_API_BASE}/api/rag/query", payload, timeout=timeout)
        return result.get("documents", [])
    except Exception as e:
        print(f"    [WARN] RAG query failed ({category}): {e}", file=sys.stderr)
        return []


def collect_evidence(folder_name: str, meta: dict, inventory: dict) -> dict[str, list[str]]:
    """Collect evidence snippets per category via RAG API."""
    search_name = meta["search_name"]
    inv = inventory.get(folder_name, {})
    categories_in_project = list(inv.get("categories", {}).keys())

    evidence: dict[str, list[str]] = {}
    for cat in ["rfp", "proposal", "kickoff", "final_report", "presentation"]:
        if cat not in categories_in_project:
            continue
        print(f"  [{cat}] Querying RAG...", end=" ", flush=True)
        docs = query_rag_for_project(search_name, cat)
        snippets: list[str] = []
        for doc in docs:
            headings = doc.get("section_headings") or [""]
            heading = headings[0] if headings else ""
            for snippet in doc.get("evidence_snippets", []):
                text = snippet.strip()
                if text and len(text) > 30:
                    label = f"[{heading}] " if heading else ""
                    snippets.append(f"{label}{text}")
        evidence[cat] = snippets[:6]
        print(f"{len(snippets)} snippets from {len(docs)} docs")
        time.sleep(0.3)

    return evidence


def build_ollama_prompt(meta: dict, evidence: dict[str, list[str]]) -> str:
    """Build a wiki generation prompt for Ollama."""
    evidence_text = ""
    for cat, snippets in evidence.items():
        if not snippets:
            continue
        cat_label = CATEGORY_KO.get(cat, cat)
        evidence_text += f"\n### {cat_label}\n"
        for s in snippets[:4]:
            evidence_text += f"- {s[:300]}\n"

    return f"""당신은 IT 컨설팅 프로젝트 문서 전문가입니다.
아래 프로젝트 문서에서 추출한 내용을 바탕으로 프로젝트 위키 페이지의 핵심 내용을 작성하세요.

## 프로젝트 기본 정보
- 프로젝트명: {meta['display_name']}
- 발주처: {meta['organization']}
- 사업연도: {meta['year']}
- 사업유형: {meta['project_type']}

## 추출된 문서 내용
{evidence_text}

## 작성 지침
위 내용을 기반으로 아래 4개 섹션을 **한국어**로 작성하세요. 각 섹션은 3~5문장으로 간결하게 작성하세요.

**사업 개요**: 이 사업의 목적과 배경, 주요 추진 방향을 설명하세요.

**핵심 요구사항**: RFP 또는 제안 요청의 주요 기술 및 업무 요구사항을 정리하세요.

**추진 전략 및 방법론**: 위즐리앤컴퍼니의 접근 방식, 방법론, 주요 추진 전략을 설명하세요.

**주요 성과 및 산출물**: 이 프로젝트의 기대 성과, 최종 산출물, 로드맵의 핵심 내용을 정리하세요.

각 섹션 제목은 **굵은 글씨**로 표시하고, 내용만 작성하세요. 추측이나 모르는 내용은 "문서에서 확인되지 않음"으로 표시하세요."""


def call_ollama(prompt: str, model: str = OLLAMA_MODEL, timeout: int = 120) -> str:
    """Call Ollama generate API and return the response text."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 1024},
    }
    try:
        result = _http_post(f"{OLLAMA_BASE}/api/generate", payload, timeout=timeout)
        return result.get("response", "").strip()
    except Exception as e:
        return f"[Ollama 생성 실패: {e}]"


def render_wiki(
    folder_name: str, meta: dict, inventory: dict,
    evidence: dict[str, list[str]], ai_content: str, snapshot: str
) -> str:
    """Render the final wiki markdown."""
    inv = inventory.get(folder_name, {})
    cats = inv.get("categories", {})
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Document inventory table
    cat_rows = ""
    for cat in ["rfp", "proposal", "kickoff", "final_report", "presentation"]:
        count = len(cats.get(cat, []))
        if count > 0:
            doc_ids = ", ".join(cats[cat][:3])
            cat_rows += f"| {CATEGORY_KO[cat]} | {count}건 | {doc_ids} |\n"

    total_docs = sum(len(v) for v in cats.values())

    # Evidence section per category
    evidence_sections = ""
    for cat in ["rfp", "proposal", "kickoff", "final_report", "presentation"]:
        snippets = evidence.get(cat, [])
        if not snippets:
            continue
        cat_label = CATEGORY_KO[cat]
        evidence_sections += f"\n### {cat_label}\n\n"
        for s in snippets[:3]:
            evidence_sections += f"> {s[:250]}\n\n"

    return f"""# {meta['display_name']}

## 기본 정보

| 항목 | 내용 |
|------|------|
| 발주처 | {meta['organization']} |
| 사업연도 | {meta['year']} |
| 사업유형 | {meta['project_type']} |
| 보유문서 | 총 {total_docs}건 |
| 폴더명 | `{folder_name}` |

## 보유 문서 인벤토리

| 문서유형 | 건수 | 문서 ID |
|---------|------|---------|
{cat_rows}
---

## AI 생성 요약

{ai_content}

---

## 검색 근거 (RAG Evidence)

아래는 RAG 검색을 통해 수집된 핵심 문서 발췌입니다.
{evidence_sections}
---

*자동 생성: {now} | 스냅샷: `{snapshot}` | 모델: {OLLAMA_MODEL}*
"""


def load_inventory() -> dict:
    if not INVENTORY_PATH.exists():
        print(f"[ERROR] project_inventory.json not found at {INVENTORY_PATH}")
        print("Run: python -c 'import build_project_inventory'  or re-run manifest collection")
        sys.exit(1)
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def generate_wiki(folder_name: str, meta: dict, inventory: dict, snapshot: str) -> Path:
    """Generate wiki for one project. Returns the saved file path."""
    print(f"\n{'='*60}")
    print(f"Project: {meta['display_name']}")
    print(f"  Folder: {folder_name}")
    print(f"  Slug:   {meta['slug']}")

    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    out_path = WIKI_DIR / f"{meta['slug']}.md"

    # Step 1: Collect RAG evidence
    print("  Collecting evidence from RAG API...")
    evidence = collect_evidence(folder_name, meta, inventory)

    # Step 2: Generate AI summary via Ollama
    print("  Generating AI summary via Ollama...", end=" ", flush=True)
    prompt = build_ollama_prompt(meta, evidence)
    ai_content = call_ollama(prompt)
    print("done")

    # Step 3: Render and save
    content = render_wiki(folder_name, meta, inventory, evidence, ai_content, snapshot)
    out_path.write_text(content, encoding="utf-8")
    print(f"  Saved: {out_path.relative_to(PROJECT_ROOT)}")
    return out_path


def list_projects() -> None:
    inventory = load_inventory()
    print("All indexed projects:\n")
    for folder, info in sorted(inventory.items()):
        cats = info.get("categories", {})
        total = sum(len(v) for v in cats.values())
        marker = " [TARGET]" if folder in TARGET_PROJECTS else ""
        print(f"  {folder}{marker}")
        print(f"    docs: {total}  categories: {list(cats.keys())}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate project wiki pages from RAG")
    parser.add_argument("--all", action="store_true", help="Generate all target projects")
    parser.add_argument("--list", action="store_true", help="List all available projects")
    parser.add_argument("--project", default=None, help="Project slug (e.g. k-water, ax, moj)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.list:
        list_projects()
        return

    inventory = load_inventory()
    snapshot = get_active_snapshot()
    print(f"Active snapshot: {snapshot}")
    print(f"Ollama model: {OLLAMA_MODEL}")

    # Select projects to process
    slug_map = {meta["slug"].split("-")[0]: (folder, meta)
                for folder, meta in TARGET_PROJECTS.items()}
    slug_map.update({meta["slug"]: (folder, meta)
                     for folder, meta in TARGET_PROJECTS.items()})

    if args.all:
        selected = list(TARGET_PROJECTS.items())
    elif args.project:
        key = args.project.lower()
        match = slug_map.get(key)
        if not match:
            # Fuzzy match on display_name
            for folder, meta in TARGET_PROJECTS.items():
                if key in meta["display_name"].lower() or key in folder.lower():
                    match = (folder, meta)
                    break
        if not match:
            print(f"[ERROR] Project not found: {args.project}")
            print(f"Available: {[m['slug'] for m in TARGET_PROJECTS.values()]}")
            sys.exit(1)
        selected = [match]
    else:
        selected = list(TARGET_PROJECTS.items())

    generated = []
    for folder_name, meta in selected:
        try:
            out_path = generate_wiki(folder_name, meta, inventory, snapshot)
            generated.append(out_path)
        except Exception as e:
            print(f"\n[ERROR] Failed for {meta['slug']}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"Generated {len(generated)} wiki pages:")
    for p in generated:
        print(f"  {p}")


if __name__ == "__main__":
    main()
