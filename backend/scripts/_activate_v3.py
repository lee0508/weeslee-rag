"""Activate snapshot_2026-05-07_combined-v3 and restart uvicorn."""
import json
import os
import paramiko
from datetime import datetime

PROJECT = "/data/weeslee/weeslee-rag"
FAISS_DIR = f"{PROJECT}/data/indexes/faiss"
PYTHON = f"{PROJECT}/.venv/bin/python3"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.0.207", username="weeslee", password=os.environ["DEPLOY_PASSWORD"])
sftp = ssh.open_sftp()

# 1. manifest 확인
_, o, _ = ssh.exec_command(f"cat {FAISS_DIR}/snapshot_2026-05-07_combined-v3_ollama.manifest.json")
manifest = json.loads(o.read().decode())
print(f"[manifest] vectors={manifest['vector_count']}, docs={manifest['document_count']}")

# 2. active_index.json 생성
active = {
    "active_snapshot": "snapshot_2026-05-07_combined-v3",
    "index_file": "snapshot_2026-05-07_combined-v3_ollama.index",
    "metadata_file": "snapshot_2026-05-07_combined-v3_ollama_metadata.jsonl",
    "embedding_provider": manifest["embedding_provider"],
    "vector_count": manifest["vector_count"],
    "document_count": manifest["document_count"],
    "activated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
}
content = json.dumps(active, ensure_ascii=False, indent=2).encode("utf-8")
with sftp.open(f"{FAISS_DIR}/active_index.json", "wb") as f:
    f.write(content)
print("[active_index.json] uploaded")

# 3. 확인
_, o, _ = ssh.exec_command(f"cat {FAISS_DIR}/active_index.json")
print(o.read().decode().strip())

# 4. uvicorn 재시작
restart = (
    f"pkill -9 -f 'uvicorn app.main:app' 2>/dev/null; sleep 3; "
    f"cd {PROJECT}/backend && "
    f"nohup {PYTHON} -m uvicorn app.main:app --host 0.0.0.0 --port 8080 "
    f">> /tmp/weeslee_fastapi.log 2>&1 </dev/null & echo RESTARTED"
)
_, o, _ = ssh.exec_command(restart)
o.channel.settimeout(8)
try:
    out = o.read().decode().strip()
except Exception:
    out = "STARTED (timeout)"
print(f"[restart] {out}")

sftp.close()
ssh.close()
