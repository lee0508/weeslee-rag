"""
Build per-category FAISS sub-indexes from a combined chunks JSONL.

Usage (after combined index is built):
    python build_category_indexes.py \
        --combined-chunks data/staged/chunks/snapshot_2026-05-06_combined-v1_chunks.jsonl \
        --output-dir data/indexes/faiss \
        --snapshot snapshot_2026-05-06_combined-v1 \
        --embedding-provider ollama \
        --ollama-model nomic-embed-text \
        --categories rfp proposal deliverable

Produces per-category indexes:
    snapshot_2026-05-06_combined-v1_rfp_ollama.index
    snapshot_2026-05-06_combined-v1_proposal_ollama.index
    snapshot_2026-05-06_combined-v1_deliverable_ollama.index

These are used by the API when a category filter is specified,
providing true pre-filter (sub-index) semantics instead of post-filter.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"

# 기본 카테고리 (--categories 미지정 시 사용)
DEFAULT_CATEGORIES = ["rfp", "proposal", "deliverable"]

# 한글 카테고리 → 영문 카테고리 매핑 (기본 매핑)
DEFAULT_CATEGORY_MAP = {
    "RFP": "rfp",
    "rfp": "rfp",
    "제안요청서": "rfp",
    "제안서": "proposal",
    "proposal": "proposal",
    "산출물": "deliverable",
    "deliverable": "deliverable",
    "최종보고서": "deliverable",
}


def normalize_category_key(raw_cat: str, target_keys: list[str]) -> str:
    """카테고리 값을 대상 키 중 하나로 정규화.

    1. 기본 매핑에 있으면 사용
    2. 번호 접두사 제거 후 소문자 비교
    3. target_keys 중 부분 일치하는 것 사용
    4. 없으면 소문자화된 원본 반환
    """
    if not raw_cat:
        return ""

    # 1. 기본 매핑 확인
    if raw_cat in DEFAULT_CATEGORY_MAP:
        return DEFAULT_CATEGORY_MAP[raw_cat]

    # 2. 소문자 변환 후 확인
    lower = raw_cat.lower().strip()
    if lower in DEFAULT_CATEGORY_MAP:
        return DEFAULT_CATEGORY_MAP[lower]

    # 3. 번호 접두사 제거 (예: "01. RFP" → "RFP")
    stripped = re.sub(r"^\d+\.\s*", "", lower).strip()
    if stripped in DEFAULT_CATEGORY_MAP:
        return DEFAULT_CATEGORY_MAP[stripped]

    # 4. target_keys 중 부분 일치
    for key in target_keys:
        if key in stripped or stripped in key:
            return key

    # 5. 원본 소문자 반환
    return stripped or lower


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build per-category FAISS sub-indexes")
    parser.add_argument("--combined-chunks", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--embedding-provider", choices=["hashing", "ollama"], default="ollama")
    parser.add_argument("--ollama-model", default="nomic-embed-text")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/embeddings")
    parser.add_argument("--categories", nargs="+", default=DEFAULT_CATEGORIES,
                        help="Category keys to build indexes for (dynamic from Document Source)")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    args = parse_args()
    combined_path = Path(args.combined_chunks).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading chunks from {combined_path}")
    all_chunks = load_jsonl(combined_path)
    print(f"Total chunks: {len(all_chunks)}")

    # 동적 카테고리 키 목록
    target_keys = args.categories
    print(f"Target categories: {target_keys}")

    by_category: dict[str, list[dict]] = {}
    for chunk in all_chunks:
        raw_cat = chunk.get("category", "")
        # 한글/영문 카테고리를 대상 키로 정규화
        cat = normalize_category_key(raw_cat, target_keys)
        by_category.setdefault(cat, []).append(chunk)

    print("Chunks per category:")
    for cat, chunks in sorted(by_category.items()):
        print(f"  {cat}: {len(chunks)}")
    print()

    build_script = SCRIPTS_DIR / "build_faiss_index.py"
    python = sys.executable

    import subprocess

    total_cats = len(args.categories)
    for cat_idx, cat in enumerate(args.categories):
        # 진행률 출력 (JSON 형식)
        progress_pct = int((cat_idx / max(total_cats, 1)) * 100)
        print(json.dumps({"progress": progress_pct, "current": cat_idx + 1, "total": total_cats, "stage": "카테고리 인덱스"}), flush=True)

        chunks = by_category.get(cat, [])
        if not chunks:
            print(f"SKIP {cat}: no chunks found")
            continue

        print(f"Building index for category={cat} ({len(chunks)} chunks)...")
        index_out = output_dir / f"{args.snapshot}_{cat}_ollama.index"
        meta_out = output_dir / f"{args.snapshot}_{cat}_ollama_metadata.jsonl"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as tmp:
            for chunk in chunks:
                tmp.write(json.dumps(chunk, ensure_ascii=False) + "\n")
            tmp_path = tmp.name

        cmd = [
            python,
            str(build_script),
            "--chunks-jsonl", tmp_path,
            "--output-index", str(index_out),
            "--output-metadata", str(meta_out),
            "--snapshot-id", args.snapshot,
            "--embedding-provider", args.embedding_provider,
            "--ollama-model", args.ollama_model,
            "--ollama-url", args.ollama_url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        Path(tmp_path).unlink(missing_ok=True)

        if result.returncode != 0:
            print(f"  ERROR: {result.stderr.strip()[-300:]}")
            print(f"  STDOUT: {result.stdout.strip()[-200:]}")
        else:
            # stdout contains progress lines + final JSON manifest; extract the JSON part
            stdout = result.stdout.strip()
            json_start = stdout.rfind("\n{")
            json_text = stdout[json_start + 1:] if json_start != -1 else stdout
            manifest = json.loads(json_text)
            print(f"  OK: {manifest['vector_count']} vectors, {manifest['document_count']} docs")

    print("\nDone. Per-category indexes built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
