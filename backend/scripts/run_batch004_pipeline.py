#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch-004 전체 파이프라인 실행 스크립트.

1. manifest JSONL → CSV 변환 (서버에서)
2. extract_manifest_batch.py 실행
3. build_chunk_batch.py 실행
4. combined-v2 청크와 병합 → combined-v3 chunks
5. build_faiss_index.py (combined-v3 전체) 실행
6. build_category_indexes.py 실행
7. active_index.json 업데이트

Usage:
    python backend/scripts/run_batch004_pipeline.py [--skip-push] [--push-only]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path, PurePosixPath

import os

import paramiko

MANIFEST_JSONL = Path("data/staged/manifest/snapshot_2026-05-07_batch-004-full-v1_manifest.jsonl")
SNAPSHOT_B4  = "snapshot_2026-05-07_batch-004-full-v1"
COMBINED_OLD = "snapshot_2026-05-06_combined-v2"
COMBINED_NEW = "snapshot_2026-05-07_combined-v3"

SERVER_HOST = "192.168.0.207"
SERVER_USER = "weeslee"
SERVER_PASS = os.environ["DEPLOY_PASSWORD"]
PROJECT_DIR = "/data/weeslee/weeslee-rag"
PYTHON      = f"{PROJECT_DIR}/.venv/bin/python3"
SCRIPTS     = f"{PROJECT_DIR}/backend/scripts"
DATA_DIR    = f"{PROJECT_DIR}/data"
MANIFEST_REMOTE = f"{DATA_DIR}/staged/manifest"
CHUNKS_DIR  = f"{DATA_DIR}/staged/chunks"
FAISS_DIR   = f"{DATA_DIR}/indexes/faiss"
TEXT_DIR    = f"{DATA_DIR}/staged/text"
META_DIR    = f"{DATA_DIR}/staged/metadata"

PHASE1_EXTS = {".pdf", ".pptx", ".docx", ".xlsx"}


# ── SFTP helpers ──────────────────────────────────────────────────────────────

def _sftp_mkdirs(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    parts = PurePosixPath(remote_path).parts
    current = ""
    for part in parts:
        current = str(PurePosixPath(current) / part) if current else part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def _load_manifest() -> list[dict]:
    rows = []
    for line in MANIFEST_JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


# ── Remote helpers ────────────────────────────────────────────────────────────

def _run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 10) -> str:
    _, stdout, _ = ssh.exec_command(cmd)
    stdout.channel.settimeout(timeout)
    try:
        return stdout.read().decode("utf-8", "replace").strip()
    except Exception:
        return "(timeout)"


def _poll_log(ssh: paramiko.SSHClient, log_path: str, done_tokens: list[str],
              interval: int = 30, max_polls: int = 60) -> bool:
    for i in range(max_polls):
        time.sleep(interval)
        tail = _run(ssh, f"tail -4 {log_path} 2>&1", timeout=10)
        sys.stdout.buffer.write(f"  [{i+1:2d}/{max_polls}] {tail[:120]}\n".encode("utf-8"))
        sys.stdout.flush()
        if any(tok.lower() in tail.lower() for tok in done_tokens):
            return True
    return False


# ── Push phase ────────────────────────────────────────────────────────────────

def push_files(ssh: paramiko.SSHClient, sftp: paramiko.SFTPClient, rows: list[dict]) -> tuple[int, int, int]:
    phase1 = [r for r in rows if r["extension"].lower() in PHASE1_EXTS]
    total = len(phase1)
    copied = skipped = failed = 0

    for i, row in enumerate(phase1, 1):
        source = Path(row["source_path"])
        snap_relative = row["snapshot_path"].replace("data/raw/", "", 1)
        dest = f"{PROJECT_DIR}/data/raw/{snap_relative}"

        if not source.exists():
            sys.stdout.buffer.write(f"[{i:3d}/{total}] MISS  {source.name}\n".encode("utf-8"))
            failed += 1
            continue

        try:
            sftp.stat(dest)
            sys.stdout.buffer.write(f"[{i:3d}/{total}] SKIP  {source.name}\n".encode("utf-8"))
            skipped += 1
            continue
        except FileNotFoundError:
            pass

        try:
            _sftp_mkdirs(sftp, str(PurePosixPath(dest).parent))
            sftp.put(str(source), dest)
            size_kb = source.stat().st_size // 1024
            sys.stdout.buffer.write(f"[{i:3d}/{total}] OK    {source.name}  ({size_kb:,} KB)\n".encode("utf-8"))
            sys.stdout.flush()
            copied += 1
        except Exception as exc:
            sys.stdout.buffer.write(f"[{i:3d}/{total}] FAIL  {source.name}  {exc}\n".encode("utf-8"))
            failed += 1

    return copied, skipped, failed


# ── Pipeline steps ────────────────────────────────────────────────────────────

def step_jsonl_to_csv(ssh: paramiko.SSHClient) -> str:
    """Convert manifest JSONL to CSV on server. Returns CSV path."""
    csv_remote = f"{MANIFEST_REMOTE}/{SNAPSHOT_B4}_manifest.csv"
    cmd = (
        f"python3 -c \""
        f"import json, csv; from pathlib import Path; "
        f"src=Path('{MANIFEST_REMOTE}/{SNAPSHOT_B4}_manifest.jsonl'); "
        f"rows=[json.loads(l) for l in src.read_text(encoding='utf-8').splitlines() if l.strip()]; "
        f"fields=['document_id','category','source_path','snapshot_path','extension','sha256','folder_name']; "
        f"dst=Path('{csv_remote}'); "
        f"f=dst.open('w',encoding='utf-8-sig',newline=''); "
        f"w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); "
        f"w.writeheader(); w.writerows(rows); f.close(); "
        f"print(f'CSV written: {{len(rows)}} rows')"
        f"\""
    )
    out = _run(ssh, cmd, timeout=30)
    sys.stdout.buffer.write(f"JSONL→CSV: {out}\n".encode("utf-8"))
    return csv_remote


def step_extract(ssh: paramiko.SSHClient, csv_remote: str) -> str:
    """Run extraction. Returns extraction summary CSV path."""
    log = "/tmp/extract_batch004.log"
    summary_csv = csv_remote.replace("_manifest.csv", "_manifest_extraction_summary.csv")
    cmd = (
        f"cd {PROJECT_DIR} && "
        f"nohup {PYTHON} {SCRIPTS}/extract_manifest_batch.py"
        f" --manifest-csv {csv_remote}"
        f" --text-dir {TEXT_DIR}"
        f" --metadata-dir {META_DIR}"
        f" --auto-ocr"
        f" < /dev/null > {log} 2>&1 & echo STARTED"
    )
    out = _run(ssh, cmd, timeout=10)
    sys.stdout.buffer.write(f"Extraction started: {out}\n".encode("utf-8"))
    sys.stdout.buffer.write(f"Polling log: {log}\n".encode("utf-8"))

    done = _poll_log(ssh, log, ["Extraction complete", "Done.", "saved summary"], interval=30, max_polls=40)
    if not done:
        sys.stdout.buffer.write(b"Extraction timeout (20 min). Proceeding anyway.\n")
    return summary_csv


def step_chunk(ssh: paramiko.SSHClient, summary_csv: str) -> str:
    """Run chunking. Returns chunks JSONL path."""
    log = "/tmp/chunk_batch004.log"
    chunks_jsonl = f"{CHUNKS_DIR}/{SNAPSHOT_B4}_chunks.jsonl"
    chunks_csv = f"{CHUNKS_DIR}/{SNAPSHOT_B4}_chunks.csv"
    cmd = (
        f"cd {PROJECT_DIR} && "
        f"nohup {PYTHON} {SCRIPTS}/build_chunk_batch.py"
        f" --summary-csv {summary_csv}"
        f" --output-jsonl {chunks_jsonl}"
        f" --output-csv {chunks_csv}"
        f" < /dev/null > {log} 2>&1 & echo STARTED"
    )
    out = _run(ssh, cmd, timeout=10)
    sys.stdout.buffer.write(f"Chunking started: {out}\n".encode("utf-8"))

    done = _poll_log(ssh, log, ["chunks written", "Done.", "complete", "Wrote"], interval=15, max_polls=20)
    if not done:
        sys.stdout.buffer.write(b"Chunking timeout. Proceeding anyway.\n")
    return chunks_jsonl


def step_merge_chunks(ssh: paramiko.SSHClient, batch004_chunks: str) -> str:
    """Merge existing combined-v2 chunks + batch004 chunks → combined-v3."""
    combined_v2 = f"{CHUNKS_DIR}/{COMBINED_OLD}_chunks.jsonl"
    combined_v3 = f"{CHUNKS_DIR}/{COMBINED_NEW}_chunks.jsonl"

    cmd = (
        f"cat {combined_v2} {batch004_chunks} > {combined_v3} && "
        f"wc -l {combined_v3}"
    )
    out = _run(ssh, cmd, timeout=30)
    sys.stdout.buffer.write(f"Merge chunks: {out}\n".encode("utf-8"))
    return combined_v3


def step_build_faiss(ssh: paramiko.SSHClient, chunks_jsonl: str, snapshot: str) -> None:
    """Build FAISS index from chunks."""
    log = f"/tmp/faiss_{snapshot}.log"
    index_out = f"{FAISS_DIR}/{snapshot}_ollama.index"
    meta_out  = f"{FAISS_DIR}/{snapshot}_ollama_metadata.jsonl"
    manifest_out = f"{FAISS_DIR}/{snapshot}_ollama.manifest.json"

    cmd = (
        f"cd {PROJECT_DIR}/backend && "
        f"nohup {PYTHON} {SCRIPTS}/build_faiss_index.py"
        f" --chunks-jsonl {chunks_jsonl}"
        f" --output-index {index_out}"
        f" --output-metadata {meta_out}"
        f" --output-manifest {manifest_out}"
        f" --embedding-provider ollama"
        f" --ollama-model nomic-embed-text"
        f" --ollama-url http://127.0.0.1:11434/api/embeddings"
        f" < /dev/null > {log} 2>&1 & echo STARTED"
    )
    out = _run(ssh, cmd, timeout=10)
    sys.stdout.buffer.write(f"FAISS build started ({snapshot}): {out}\n".encode("utf-8"))
    sys.stdout.buffer.write(f"Log: {log}\n".encode("utf-8"))

    # FAISS takes longer — 45 sec intervals
    done = _poll_log(ssh, log, ["Index saved", "Done.", "complete", "vectors"], interval=45, max_polls=80)
    if not done:
        sys.stdout.buffer.write(b"FAISS timeout. Check log manually.\n")


def step_build_categories(ssh: paramiko.SSHClient, combined_v3_chunks: str) -> None:
    """Build per-category sub-indexes for combined-v3."""
    log = "/tmp/categories_combined_v3.log"
    cmd = (
        f"cd {PROJECT_DIR}/backend && "
        f"nohup {PYTHON} {SCRIPTS}/build_category_indexes.py"
        f" --combined-chunks {combined_v3_chunks}"
        f" --output-dir {FAISS_DIR}"
        f" --snapshot {COMBINED_NEW}"
        f" --embedding-provider ollama"
        f" --ollama-model nomic-embed-text"
        f" --ollama-url http://127.0.0.1:11434/api/embeddings"
        f" < /dev/null > {log} 2>&1 & echo STARTED"
    )
    out = _run(ssh, cmd, timeout=10)
    sys.stdout.buffer.write(f"Category indexes started: {out}\n".encode("utf-8"))

    done = _poll_log(ssh, log, ["Done", "complete", "category"], interval=45, max_polls=80)
    if not done:
        sys.stdout.buffer.write(b"Category index timeout. Check log manually.\n")


def step_activate(ssh: paramiko.SSHClient, doc_count: int, chunk_count: int) -> None:
    """Update active_index.json to combined-v3."""
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    active = {
        "snapshot": COMBINED_NEW,
        "activated_at": now,
        "note": f"Combined batch-001+002+003+004+ocr-rerun, ~{chunk_count} vectors, ~{doc_count} docs, 5-category sub-indexes",
    }
    active_json = json.dumps(active, ensure_ascii=False, indent=2)
    cmd = f"echo '{active_json}' > {PROJECT_DIR}/data/active_index.json && cat {PROJECT_DIR}/data/active_index.json"
    out = _run(ssh, cmd, timeout=10)
    sys.stdout.buffer.write(f"Activated: {out}\n".encode("utf-8"))

    # Restart FastAPI to pick up new index
    restart_cmd = (
        f"pkill -9 -f 'uvicorn app.main:app' 2>/dev/null; sleep 3; "
        f"cd {PROJECT_DIR}/backend && "
        f"nohup {PYTHON} -m uvicorn app.main:app --host 0.0.0.0 --port 8080 "
        f">> /tmp/weeslee_fastapi.log 2>&1 </dev/null & echo RESTARTED"
    )
    out2 = _run(ssh, restart_cmd, timeout=12)
    sys.stdout.buffer.write(f"Server restart: {out2}\n".encode("utf-8"))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    push_only = "--push-only" in sys.argv
    skip_push = "--skip-push" in sys.argv

    rows = _load_manifest()
    phase1_rows = [r for r in rows if r["extension"].lower() in PHASE1_EXTS]
    total_mb = sum(r["size_bytes"] for r in phase1_rows) / 1024 / 1024
    sys.stdout.buffer.write(
        f"Manifest: {len(rows)} docs, {len(phase1_rows)} Phase1, {total_mb:.1f} MB\n".encode("utf-8")
    )

    sys.stdout.buffer.write(f"Connecting to {SERVER_HOST}...\n".encode("utf-8"))
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SERVER_HOST, username=SERVER_USER, password=SERVER_PASS, timeout=20)
    sftp = ssh.open_sftp()

    try:
        # Upload manifest JSONL to server
        manifest_remote = f"{MANIFEST_REMOTE}/{MANIFEST_JSONL.name}"
        sftp.put(str(MANIFEST_JSONL), manifest_remote)
        sys.stdout.buffer.write(f"Uploaded manifest → {manifest_remote}\n".encode("utf-8"))

        if not skip_push:
            sys.stdout.buffer.write("\n-- Pushing files --\n".encode("utf-8"))
            copied, skipped, failed = push_files(ssh, sftp, rows)
            sys.stdout.buffer.write(
                f"\nPush: copied={copied}, skipped={skipped}, failed={failed}\n".encode("utf-8")
            )

        if push_only:
            sys.stdout.buffer.write(b"--push-only: done.\n")
            return

        sftp.close()

        sys.stdout.buffer.write("\n-- Step 1: Convert JSONL -> CSV --\n".encode("utf-8"))
        csv_remote = step_jsonl_to_csv(ssh)

        sys.stdout.buffer.write("\n-- Step 2: Extract text --\n".encode("utf-8"))
        summary_csv = step_extract(ssh, csv_remote)

        sys.stdout.buffer.write("\n-- Step 3: Build chunks --\n".encode("utf-8"))
        batch004_chunks = step_chunk(ssh, summary_csv)

        sys.stdout.buffer.write("\n-- Step 4: Merge with combined-v2 --\n".encode("utf-8"))
        combined_v3_chunks = step_merge_chunks(ssh, batch004_chunks)

        sys.stdout.buffer.write("\n-- Step 5: Build FAISS (combined-v3) --\n".encode("utf-8"))
        step_build_faiss(ssh, combined_v3_chunks, COMBINED_NEW)

        sys.stdout.buffer.write("\n-- Step 6: Build category sub-indexes --\n".encode("utf-8"))
        step_build_categories(ssh, combined_v3_chunks)

        # Get chunk count
        chunk_count_str = _run(ssh, f"wc -l < {combined_v3_chunks} 2>&1", timeout=10)
        chunk_count = int(chunk_count_str.strip()) if chunk_count_str.strip().isdigit() else 0
        doc_count = 65 + len(phase1_rows)  # existing + new

        sys.stdout.buffer.write("\n-- Step 7: Activate combined-v3 --\n".encode("utf-8"))
        step_activate(ssh, doc_count, chunk_count)

        sys.stdout.buffer.write(
            f"\n{'='*60}\n"
            f"Pipeline complete!\n"
            f"  New snapshot : {COMBINED_NEW}\n"
            f"  Docs total   : ~{doc_count}\n"
            f"  Chunks total : ~{chunk_count}\n"
            f"{'='*60}\n".encode("utf-8")
        )

    finally:
        try:
            sftp.close()
        except Exception:
            pass
        ssh.close()


if __name__ == "__main__":
    main()
