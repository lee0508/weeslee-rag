"""
Resume batch-004 pipeline from Step 3 (chunking already done: 27,095 chunks).

Steps:
  3. Merge v2(7066) + batch-004(27095) → combined-v3 chunks
  4. build_faiss_index.py  → combined-v3 FAISS
  5. build_category_indexes.py → 5 sub-indexes
  6. Activate + restart
"""
import json
import os
import sys
import time
import paramiko
from datetime import datetime

PROJECT  = "/data/weeslee/weeslee-rag"
PYTHON   = f"{PROJECT}/.venv/bin/python3"
SCRIPTS  = f"{PROJECT}/backend/scripts"
CHUNKS   = f"{PROJECT}/data/staged/chunks"
FAISS    = f"{PROJECT}/data/indexes/faiss"

SNAPSHOT_B4  = "snapshot_2026-05-07_batch-004-full-v1"
COMBINED_OLD = "snapshot_2026-05-06_combined-v2"
COMBINED_NEW = "snapshot_2026-05-07_combined-v3"
B4_CHUNKS    = f"{CHUNKS}/{SNAPSHOT_B4}_chunks.jsonl"
V2_CHUNKS    = f"{CHUNKS}/{COMBINED_OLD}_chunks.jsonl"
V3_CHUNKS    = f"{CHUNKS}/{COMBINED_NEW}_chunks.jsonl"


def run(ssh, cmd, timeout=15):
    _, o, _ = ssh.exec_command(cmd)
    o.channel.settimeout(timeout)
    try:
        return o.read().decode("utf-8", "replace").strip()
    except Exception:
        return "(timeout)"


def poll(ssh, log, done_tokens, interval=45, max_polls=80):
    for i in range(max_polls):
        time.sleep(interval)
        tail = run(ssh, f"tail -5 {log} 2>&1", timeout=10)
        elapsed = (i + 1) * interval
        sys.stdout.write(f"  [{elapsed:5d}s] {tail[:120]}\n")
        sys.stdout.flush()
        if any(t.lower() in tail.lower() for t in done_tokens):
            return True
    return False


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("192.168.0.207", username="weeslee", password=os.environ["DEPLOY_PASSWORD"])

    # ── Step 3: merge v2 + batch-004 → combined-v3 ──────────────────────────
    print("\n[Step 3] Merging v2(7066) + batch-004(27095) → combined-v3...")
    out3 = run(ssh, f"cat {V2_CHUNKS} {B4_CHUNKS} > {V3_CHUNKS} && wc -l {V3_CHUNKS}", timeout=60)
    print(f"  {out3}")

    # ── Step 4: build FAISS (combined-v3) ────────────────────────────────────
    print(f"\n[Step 4] Building FAISS index (combined-v3, ~34k vectors)...")
    log4 = f"/tmp/faiss_{COMBINED_NEW}.log"
    index_out    = f"{FAISS}/{COMBINED_NEW}_ollama.index"
    meta_out     = f"{FAISS}/{COMBINED_NEW}_ollama_metadata.jsonl"
    manifest_out = f"{FAISS}/{COMBINED_NEW}_ollama.manifest.json"
    cmd4 = (
        f"cd {PROJECT}/backend && "
        f"nohup {PYTHON} {SCRIPTS}/build_faiss_index.py"
        f" --chunks-jsonl {V3_CHUNKS}"
        f" --output-index {index_out}"
        f" --output-metadata {meta_out}"
        f" --output-manifest {manifest_out}"
        f" --embedding-provider ollama"
        f" --ollama-model nomic-embed-text"
        f" --ollama-url http://127.0.0.1:11434/api/embeddings"
        f" < /dev/null > {log4} 2>&1 & echo STARTED"
    )
    print(f"  {run(ssh, cmd4, timeout=10)}")
    print(f"  Log: {log4}  (polling every 45s, max 60min)")
    done4 = poll(ssh, log4, ["Index saved", "Done", "vectors written", "complete"], interval=45, max_polls=80)
    tail4 = run(ssh, f"tail -8 {log4}")
    print(f"  Final:\n{tail4}")
    if not done4:
        print("  WARNING: FAISS build timed out — check log on server.")

    # ── Step 5: category sub-indexes ─────────────────────────────────────────
    print(f"\n[Step 5] Building category sub-indexes...")
    log5 = "/tmp/categories_combined_v3.log"
    cmd5 = (
        f"cd {PROJECT}/backend && "
        f"nohup {PYTHON} {SCRIPTS}/build_category_indexes.py"
        f" --combined-chunks {V3_CHUNKS}"
        f" --output-dir {FAISS}"
        f" --snapshot {COMBINED_NEW}"
        f" --embedding-provider ollama"
        f" --ollama-model nomic-embed-text"
        f" --ollama-url http://127.0.0.1:11434/api/embeddings"
        f" < /dev/null > {log5} 2>&1 & echo STARTED"
    )
    print(f"  {run(ssh, cmd5, timeout=10)}")
    done5 = poll(ssh, log5, ["Done.", "Per-category indexes built", "complete"], interval=45, max_polls=60)
    tail5 = run(ssh, f"tail -8 {log5}")
    print(f"  Final:\n{tail5}")

    # ── Step 6: read new manifest ─────────────────────────────────────────────
    print(f"\n[Step 6] Reading new manifest...")
    raw = run(ssh, f"cat {manifest_out} 2>/dev/null || echo NOT_FOUND", timeout=10)
    try:
        mf = json.loads(raw)
        vectors = mf["vector_count"]
        docs    = mf["document_count"]
        print(f"  vectors={vectors}, docs={docs}")
    except Exception:
        vectors, docs = 0, 0
        print(f"  Could not read manifest: {raw[:120]}")

    # ── Step 7: activate ─────────────────────────────────────────────────────
    print(f"\n[Step 7] Activating combined-v3...")
    active = {
        "active_snapshot": COMBINED_NEW,
        "index_file": f"{COMBINED_NEW}_ollama.index",
        "metadata_file": f"{COMBINED_NEW}_ollama_metadata.jsonl",
        "embedding_provider": "ollama",
        "vector_count": vectors,
        "document_count": docs,
        "activated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    sftp = ssh.open_sftp()
    content = json.dumps(active, ensure_ascii=False, indent=2).encode("utf-8")
    with sftp.open(f"{FAISS}/active_index.json", "wb") as f:
        f.write(content)
    sftp.close()
    print(f"  active_index.json updated")
    print(f"  {json.dumps(active, ensure_ascii=False)}")

    # ── Step 8: restart FastAPI ───────────────────────────────────────────────
    print(f"\n[Step 8] Restarting FastAPI...")
    restart = (
        f"pkill -9 -f 'uvicorn app.main:app' 2>/dev/null; sleep 3; "
        f"cd {PROJECT}/backend && "
        f"nohup {PYTHON} -m uvicorn app.main:app --host 0.0.0.0 --port 8080 "
        f">> /tmp/weeslee_fastapi.log 2>&1 </dev/null & echo RESTARTED"
    )
    out8 = run(ssh, restart, timeout=12)
    print(f"  {out8 or 'RESTARTED'}")

    print(f"\n{'='*60}")
    print(f"Pipeline complete!")
    print(f"  Snapshot : {COMBINED_NEW}")
    print(f"  Vectors  : {vectors}")
    print(f"  Docs     : {docs}")
    print(f"{'='*60}")
    ssh.close()


if __name__ == "__main__":
    main()
