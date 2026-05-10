"""Check server Ollama status and restart FAISS build if needed."""
import os
import paramiko
import time

PROJECT = "/data/weeslee/weeslee-rag"
PYTHON = f"{PROJECT}/.venv/bin/python3"
SCRIPTS = f"{PROJECT}/backend/scripts"
CHUNKS_DIR = f"{PROJECT}/data/staged/chunks"
FAISS_DIR = f"{PROJECT}/data/indexes/faiss"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.0.207", username="weeslee", password=os.environ["DEPLOY_PASSWORD"])

# Check Ollama
_, o, _ = ssh.exec_command("systemctl is-active ollama 2>/dev/null; ps aux | grep 'ollama serve' | grep -v grep | wc -l")
print("Ollama:", o.read().decode().strip())

# Test embed
_, o, _ = ssh.exec_command('curl -s -X POST http://localhost:11434/api/embeddings -d \'{"model":"nomic-embed-text","prompt":"test"}\' | python3 -c "import sys,json; d=json.load(sys.stdin); print(\'OK dim=%d\' % len(d.get(\'embedding\',[])))" 2>&1')
embed_result = o.read().decode().strip()
print("Embed test:", embed_result)

# Restart Ollama if needed
if "OK" not in embed_result:
    print("Restarting Ollama...")
    _, o, _ = ssh.exec_command("systemctl restart ollama 2>/dev/null || (pkill ollama; sleep 3; nohup ollama serve > /tmp/ollama.log 2>&1 &)")
    o.read()
    time.sleep(5)
    _, o, _ = ssh.exec_command('curl -s -X POST http://localhost:11434/api/embeddings -d \'{"model":"nomic-embed-text","prompt":"test"}\' | python3 -c "import sys,json; d=json.load(sys.stdin); print(\'OK dim=%d\' % len(d.get(\'embedding\',[])))" 2>&1')
    print("After restart:", o.read().decode().strip())

# Start FAISS build
COMBINED_CHUNKS = f"{CHUNKS_DIR}/snapshot_2026-05-06_combined-v1_chunks.jsonl"
INDEX_OUT = f"{FAISS_DIR}/snapshot_2026-05-06_combined-v1_ollama.index"
META_OUT = f"{FAISS_DIR}/snapshot_2026-05-06_combined-v1_ollama_metadata.jsonl"

faiss_cmd = (
    f"cd {PROJECT} && "
    f"nohup {PYTHON} {SCRIPTS}/build_faiss_index.py"
    f" --chunks-jsonl {COMBINED_CHUNKS}"
    f" --output-index {INDEX_OUT}"
    f" --output-metadata {META_OUT}"
    f" --embedding-provider ollama"
    f" --ollama-model nomic-embed-text"
    f" < /dev/null > /tmp/faiss_combined.log 2>&1 & echo STARTED"
)
_, stdout, _ = ssh.exec_command(faiss_cmd, get_pty=False)
stdout.channel.settimeout(5)
try:
    print("FAISS build:", stdout.read().decode().strip())
except Exception:
    print("FAISS build: STARTED (timeout)")
stdout.channel.close()

time.sleep(10)
_, o, _ = ssh.exec_command("ps aux | grep build_faiss | grep -v grep | wc -l; tail -3 /tmp/faiss_combined.log")
print("Process check:", o.read().decode().strip())
ssh.close()
