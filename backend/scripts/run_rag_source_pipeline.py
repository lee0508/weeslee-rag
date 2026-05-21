# 00. RAG 소스 전체 파일을 OCR, 청킹, FAISS까지 순차 처리하는 서버 배치 스크립트
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.rag_source_pipeline import build_manifest  # noqa: E402
from app.services.faiss_job_runner import activate_snapshot  # noqa: E402

SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"
DATA_DIR = PROJECT_ROOT / "data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full 00. RAG source pipeline")
    parser.add_argument("--snapshot", required=True, help="Snapshot name, for example snapshot_20260521_rag_source")
    parser.add_argument("--source-id", default="rag_source", help="Document source id")
    parser.add_argument("--limit", type=int, default=0, help="Optional max document count for test runs")
    parser.add_argument("--manifest-only", action="store_true", help="Only build manifest files")
    parser.add_argument("--overwrite-manifest", action="store_true", help="Rebuild manifest even if it already exists")
    parser.add_argument("--embedding-provider", default="ollama", choices=["ollama", "hashing"])
    parser.add_argument("--activate", action="store_true", help="Activate snapshot after successful build")
    return parser.parse_args()


def _run_step(args: list[str]) -> None:
    cmd = [sys.executable, str(SCRIPTS_DIR / args[0]), *args[1:]]
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def main() -> int:
    args = parse_args()
    manifest = build_manifest(
        snapshot_name=args.snapshot,
        source_id=args.source_id,
        limit=args.limit,
        overwrite=args.overwrite_manifest,
    )
    print(json.dumps({"stage": "manifest", **manifest}, ensure_ascii=False, indent=2))

    if args.manifest_only:
        return 0

    manifest_csv = manifest["manifest_csv"]
    summary_csv = str(DATA_DIR / "staged" / "manifest" / f"{args.snapshot}_manifest_extraction_summary.csv")
    text_dir = str(DATA_DIR / "staged" / "text")
    metadata_dir = str(DATA_DIR / "staged" / "metadata")
    chunks_jsonl = str(DATA_DIR / "staged" / "chunks" / f"{args.snapshot}_chunks.jsonl")
    index_path = str(DATA_DIR / "indexes" / "faiss" / f"{args.snapshot}_ollama.index")
    meta_path = str(DATA_DIR / "indexes" / "faiss" / f"{args.snapshot}_ollama_metadata.jsonl")
    graph_dir = DATA_DIR / "indexes" / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    _run_step([
        "extract_manifest_batch.py",
        "--manifest-csv", manifest_csv,
        "--text-dir", text_dir,
        "--metadata-dir", metadata_dir,
        "--summary-csv", summary_csv,
        "--use-ocr",
    ])
    _run_step([
        "build_chunk_batch.py",
        "--summary-csv", summary_csv,
        "--output-jsonl", chunks_jsonl,
    ])
    _run_step([
        "build_faiss_index.py",
        "--chunks-jsonl", chunks_jsonl,
        "--output-index", index_path,
        "--output-metadata", meta_path,
        "--embedding-provider", args.embedding_provider,
    ])
    _run_step([
        "build_category_indexes.py",
        "--combined-chunks", chunks_jsonl,
        "--output-dir", str(DATA_DIR / "indexes" / "faiss"),
        "--snapshot", args.snapshot,
        "--embedding-provider", args.embedding_provider,
    ])
    _run_step([
        "build_graph_jsonl.py",
        "--snapshot", args.snapshot,
    ])

    if args.activate:
        print(json.dumps({"stage": "activate", "result": activate_snapshot(args.snapshot)}, ensure_ascii=False, indent=2))

    print(json.dumps({
        "stage": "completed",
        "snapshot": args.snapshot,
        "manifest_csv": manifest_csv,
        "summary_csv": summary_csv,
        "chunks_jsonl": chunks_jsonl,
        "index_path": index_path,
        "metadata_path": meta_path,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
