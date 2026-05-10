#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Push batch-004 files to server via SFTP, then run extract → chunk → FAISS pipeline.

Usage:
    python backend/scripts/push_batch004.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path, PurePosixPath

import os

import paramiko

MANIFEST_JSONL = Path("data/staged/manifest/snapshot_2026-05-07_batch-004-full-v1_manifest.jsonl")
SNAPSHOT_NAME  = "snapshot_2026-05-07_batch-004-full-v1"

SERVER_HOST = "192.168.0.207"
SERVER_USER = "weeslee"
SERVER_PASS = os.environ["DEPLOY_PASSWORD"]
PROJECT_DIR = "/data/weeslee/weeslee-rag"
PYTHON      = f"{PROJECT_DIR}/.venv/bin/python3"
SCRIPTS     = f"{PROJECT_DIR}/backend/scripts"
MANIFEST_DIR_REMOTE = f"{PROJECT_DIR}/data/staged/manifest"

PHASE1_EXTS = {".pdf", ".pptx", ".docx", ".xlsx"}


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


def push_files(ssh: paramiko.SSHClient, sftp: paramiko.SFTPClient, rows: list[dict]) -> tuple[int, int, int]:
    copied = skipped = failed = 0
    total = len(rows)

    for i, row in enumerate(rows, 1):
        ext = row["extension"].lower()
        if ext not in PHASE1_EXTS:
            skipped += 1
            continue

        source = Path(row["source_path"])
        snap_relative = row["snapshot_path"].replace("data/raw/", "", 1)
        dest_remote = f"{PROJECT_DIR}/data/raw/{snap_relative}"

        if not source.exists():
            print(f"[{i:3d}/{total}] MISS  {source.name}", file=sys.stderr)
            failed += 1
            continue

        # Check if already on server
        try:
            sftp.stat(dest_remote)
            skipped += 1
            print(f"[{i:3d}/{total}] SKIP  {source.name}")
            continue
        except FileNotFoundError:
            pass

        try:
            _sftp_mkdirs(sftp, str(PurePosixPath(dest_remote).parent))
            sftp.put(str(source), dest_remote)
            size_kb = source.stat().st_size // 1024
            print(f"[{i:3d}/{total}] OK    {source.name}  ({size_kb:,} KB)")
            copied += 1
        except Exception as exc:
            print(f"[{i:3d}/{total}] FAIL  {source.name}  {exc}", file=sys.stderr)
            failed += 1

    return copied, skipped, failed


def upload_manifest(sftp: paramiko.SFTPClient) -> None:
    remote = f"{MANIFEST_DIR_REMOTE}/{MANIFEST_JSONL.name}"
    sftp.put(str(MANIFEST_JSONL), remote)
    print(f"Uploaded manifest → {remote}")

    # Also create CSV on server (convert JSONL → CSV)
    pass  # done via server-side command below


def run_pipeline(ssh: paramiko.SSHClient) -> None:
    csv_remote = f"{MANIFEST_DIR_REMOTE}/{SNAPSHOT_NAME}_manifest.csv"

    # Step A: Convert JSONL to CSV on server
    conv_cmd = (
        f"python3 -c \""
        f"import json, csv; from pathlib import Path; "
        f"src=Path('{MANIFEST_DIR_REMOTE}/{SNAPSHOT_NAME}_manifest.jsonl'); "
        f"rows=[json.loads(l) for l in src.read_text(encoding='utf-8').splitlines() if l.strip()]; "
        f"fields=['document_id','category','source_path','snapshot_path','extension','sha256','folder_name']; "
        f"dst=src.with_suffix('.csv'); "
        f"f=dst.open('w',encoding='utf-8-sig',newline=''); "
        f"w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); "
        f"w.writeheader(); w.writerows(rows); f.close(); "
        f"print(f'CSV: {{len(rows)}} rows → {{dst.name}}')"
        f"\""
    )
    _, stdout, _ = ssh.exec_command(conv_cmd)
    print("CSV:", stdout.read().decode("utf-8", "replace").strip())

    # Step B: Run extraction
    extract_log = "/tmp/extract_batch004.log"
    extract_cmd = (
        f"cd {PROJECT_DIR} && "
        f"nohup {PYTHON} {SCRIPTS}/extract_manifest_batch.py"
        f" --manifest-csv {csv_remote}"
        f" --text-dir {PROJECT_DIR}/data/staged/text"
        f" --metadata-dir {PROJECT_DIR}/data/staged/metadata"
        f" < /dev/null > {extract_log} 2>&1 & echo EXTRACT_STARTED"
    )
    _, stdout, _ = ssh.exec_command(extract_cmd)
    stdout.channel.settimeout(8)
    try:
        print("Extraction:", stdout.read().decode("utf-8", "replace").strip())
    except Exception:
        print("Extraction: STARTED")

    print(f"\nExtraction running in background. Monitor: tail -f {extract_log}")
    print("Will poll every 30s for completion...")

    # Poll extraction progress
    for attempt in range(40):  # max 20 minutes
        time.sleep(30)
        _, stdout, _ = ssh.exec_command(f"tail -3 {extract_log} 2>&1")
        tail = stdout.read().decode("utf-8", "replace").strip()
        print(f"  [{attempt+1:2d}] {tail}")
        if "Extraction complete" in tail or "Done." in tail or "complete" in tail.lower():
            print("  → Extraction finished!")
            break
    else:
        print("  → Extraction polling timeout. Check log manually.")

    # Step C: Read extraction summary to see how many succeeded
    _, stdout, _ = ssh.exec_command(
        f"python3 -c \""
        f"import csv; from pathlib import Path; "
        f"p=Path('/data/weeslee/weeslee-rag/data/staged'); "
        f"csvs=list(p.glob('*batch-004*.csv')); "
        f"print('Summary files:', [f.name for f in csvs])"
        f"\""
    )
    print("Summary:", stdout.read().decode("utf-8", "replace").strip())

    # Step D: Build chunks
    chunk_log = "/tmp/chunk_batch004.log"
    chunk_cmd = (
        f"cd {PROJECT_DIR} && "
        f"nohup {PYTHON} {SCRIPTS}/build_chunk_batch.py"
        f" --snapshot {SNAPSHOT_NAME}"
        f" < /dev/null > {chunk_log} 2>&1 & echo CHUNK_STARTED"
    )
    _, stdout, _ = ssh.exec_command(chunk_cmd)
    stdout.channel.settimeout(8)
    try:
        print("Chunking:", stdout.read().decode("utf-8", "replace").strip())
    except Exception:
        print("Chunking: STARTED")

    # Poll chunking
    for attempt in range(20):  # max 10 minutes
        time.sleep(30)
        _, stdout, _ = ssh.exec_command(f"tail -3 {chunk_log} 2>&1")
        tail = stdout.read().decode("utf-8", "replace").strip()
        print(f"  chunk [{attempt+1:2d}] {tail}")
        if "Done" in tail or "complete" in tail.lower() or "chunks written" in tail.lower():
            print("  → Chunking finished!")
            break

    # Step E: Build FAISS index
    faiss_log = "/tmp/faiss_batch004.log"
    faiss_cmd = (
        f"cd {PROJECT_DIR}/backend && "
        f"nohup {PYTHON} {SCRIPTS}/build_faiss_index.py"
        f" --snapshot {SNAPSHOT_NAME}"
        f" --model ollama"
        f" < /dev/null > {faiss_log} 2>&1 & echo FAISS_STARTED"
    )
    _, stdout, _ = ssh.exec_command(faiss_cmd)
    stdout.channel.settimeout(8)
    try:
        print("FAISS:", stdout.read().decode("utf-8", "replace").strip())
    except Exception:
        print("FAISS: STARTED")

    print(f"FAISS building in background. Monitor: tail -f {faiss_log}")
    print("Pipeline launched. Run combine script after FAISS completes.")


def main() -> None:
    rows = _load_manifest()
    phase1_rows = [r for r in rows if r["extension"].lower() in PHASE1_EXTS]
    print(f"Manifest loaded: {len(rows)} total, {len(phase1_rows)} Phase1 files")
    total_mb = sum(r["size_bytes"] for r in phase1_rows) / 1024 / 1024
    print(f"Total upload size: {total_mb:.1f} MB")
    print()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {SERVER_HOST}...")
    ssh.connect(SERVER_HOST, username=SERVER_USER, password=SERVER_PASS, timeout=15)
    sftp = ssh.open_sftp()

    try:
        # 1. Upload manifest
        upload_manifest(sftp)

        # 2. Push files
        print(f"\n── Pushing {len(phase1_rows)} files ──")
        copied, skipped, failed = push_files(ssh, sftp, phase1_rows)
        print(f"\nPush complete: copied={copied}, skipped={skipped}, failed={failed}")

        # 3. Run pipeline
        print(f"\n── Running extraction pipeline ──")
        run_pipeline(ssh)

    finally:
        sftp.close()
        ssh.close()
        print("\nSSH connection closed.")


if __name__ == "__main__":
    main()
