"""
Build per-category FAISS sub-indexes from a combined chunks JSONL.

Usage (after combined index is built):
    python build_category_indexes.py \
        --combined-chunks data/staged/chunks/snapshot_2026-05-06_combined-v1_chunks.jsonl \
        --output-dir data/indexes/faiss \
        --snapshot snapshot_2026-05-06_combined-v1 \
        --embedding-provider ollama \
        --ollama-model nomic-embed-text

Produces per-category indexes:
    snapshot_2026-05-06_combined-v1_rfp_ollama.index
    snapshot_2026-05-06_combined-v1_proposal_ollama.index
    snapshot_2026-05-06_combined-v1_kickoff_ollama.index
    snapshot_2026-05-06_combined-v1_final_report_ollama.index
    snapshot_2026-05-06_combined-v1_presentation_ollama.index

These are used by the API when a category filter is specified,
providing true pre-filter (sub-index) semantics instead of post-filter.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"

CATEGORIES = ["rfp", "proposal", "kickoff", "final_report", "presentation"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build per-category FAISS sub-indexes")
    parser.add_argument("--combined-chunks", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--embedding-provider", choices=["hashing", "ollama"], default="ollama")
    parser.add_argument("--ollama-model", default="nomic-embed-text")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/embeddings")
    parser.add_argument("--categories", nargs="+", default=CATEGORIES)
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

    by_category: dict[str, list[dict]] = {}
    for chunk in all_chunks:
        cat = chunk.get("category", "")
        by_category.setdefault(cat, []).append(chunk)

    print("Chunks per category:")
    for cat, chunks in sorted(by_category.items()):
        print(f"  {cat}: {len(chunks)}")
    print()

    build_script = SCRIPTS_DIR / "build_faiss_index.py"
    python = sys.executable

    import subprocess

    for cat in args.categories:
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
