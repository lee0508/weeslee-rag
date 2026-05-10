#!/bin/bash
# Auto-finish batch-004 pipeline on server.
# Waits for FAISS build to complete, then runs category indexes, activates, restarts.

PROJECT="/data/weeslee/weeslee-rag"
PYTHON="$PROJECT/.venv/bin/python3"
SCRIPTS="$PROJECT/backend/scripts"
FAISS_DIR="$PROJECT/data/indexes/faiss"
CHUNKS="$PROJECT/data/staged/chunks"
COMBINED_NEW="snapshot_2026-05-07_combined-v3"
V3_CHUNKS="$CHUNKS/${COMBINED_NEW}_chunks.jsonl"
LOG_MAIN="/tmp/autofinish_batch004.log"

exec > "$LOG_MAIN" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] autofinish started"

# ── Step 1: Wait for FAISS build to complete ────────────────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for FAISS build..."
FAISS_LOG="/tmp/faiss_${COMBINED_NEW}.log"
MAX_WAIT=7200  # 2 hours max
ELAPSED=0
while true; do
    if ! pgrep -f "build_faiss_index.py" > /dev/null 2>&1; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAISS process not running — checking output..."
        break
    fi
    if grep -q "Index saved\|Done\.\|vectors written" "$FAISS_LOG" 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAISS done (done token found)"
        break
    fi
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAISS wait timeout (${MAX_WAIT}s). Proceeding anyway."
        break
    fi
    sleep 30
    ELAPSED=$((ELAPSED + 30))
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Still waiting... ${ELAPSED}s elapsed"
done

FAISS_LOG_TAIL=$(tail -5 "$FAISS_LOG" 2>/dev/null || echo "NO LOG")
echo "[FAISS log tail] $FAISS_LOG_TAIL"

# ── Step 2: Build category sub-indexes ─────────────────────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Building category indexes..."
CAT_LOG="/tmp/categories_combined_v3.log"
cd "$PROJECT/backend"
"$PYTHON" "$SCRIPTS/build_category_indexes.py" \
    --combined-chunks "$V3_CHUNKS" \
    --output-dir "$FAISS_DIR" \
    --snapshot "$COMBINED_NEW" \
    --embedding-provider ollama \
    --ollama-model nomic-embed-text \
    > "$CAT_LOG" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Category indexes done. Exit: $?"
tail -5 "$CAT_LOG"

# ── Step 3: Read manifest and write active_index.json ──────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Writing active_index.json..."
MANIFEST_FILE="$FAISS_DIR/${COMBINED_NEW}_ollama.manifest.json"
python3 - <<'PYEOF'
import json, os
from datetime import datetime

FAISS_DIR = "/data/weeslee/weeslee-rag/data/indexes/faiss"
COMBINED_NEW = "snapshot_2026-05-07_combined-v3"
manifest_file = f"{FAISS_DIR}/{COMBINED_NEW}_ollama.manifest.json"

try:
    mf = json.loads(open(manifest_file).read())
    vectors = mf["vector_count"]
    docs    = mf["document_count"]
except Exception as e:
    print(f"WARNING: could not read manifest: {e}")
    vectors, docs = 0, 0

active = {
    "active_snapshot": COMBINED_NEW,
    "index_file": f"{COMBINED_NEW}_ollama.index",
    "metadata_file": f"{COMBINED_NEW}_ollama_metadata.jsonl",
    "embedding_provider": "ollama",
    "vector_count": vectors,
    "document_count": docs,
    "activated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
}
out_path = f"{FAISS_DIR}/active_index.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(active, f, ensure_ascii=False, indent=2)
print(f"active_index.json written: vectors={vectors}, docs={docs}")
PYEOF

# ── Step 4: Restart FastAPI ─────────────────────────────────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restarting FastAPI..."
pkill -9 -f "uvicorn app.main:app" 2>/dev/null
sleep 4
cd "$PROJECT/backend"
nohup "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8080 \
    >> /tmp/weeslee_fastapi.log 2>&1 </dev/null &
echo "[$(date '+%Y-%m-%d %H:%M:%S')] FastAPI restarted (PID $!)"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === autofinish complete ==="
