"""Switch FAISS_SNAPSHOT in server .env and restart uvicorn."""
import json
import os
import paramiko
import time

PROJECT = "/data/weeslee/weeslee-rag"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.0.207", username="weeslee", password=os.environ["DEPLOY_PASSWORD"])

# Get vector count
MANIFEST = f"{PROJECT}/data/indexes/faiss/snapshot_2026-05-06_combined-v1_ollama.manifest.json"
_, o, _ = ssh.exec_command(f"cat {MANIFEST}")
manifest = json.loads(o.read().decode())
print(f"Index: {manifest['vector_count']} vectors, {manifest['document_count']} documents")
print(f"Embedding: {manifest['embedding_provider']}, dim={manifest['embedding_dim']}")

# Update .env
_, o, e = ssh.exec_command(
    f"sed -i 's/FAISS_SNAPSHOT=.*/FAISS_SNAPSHOT=snapshot_2026-05-06_combined-v1/' {PROJECT}/.env "
    f"&& grep FAISS_SNAPSHOT {PROJECT}/.env"
)
print("ENV update:", o.read().decode().strip())

# Restart uvicorn
ssh.exec_command("lsof -ti:8080 2>/dev/null | xargs kill -9 2>/dev/null")
time.sleep(2)
restart_cmd = (
    f"cd {PROJECT}/backend && "
    f"nohup {PROJECT}/.venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8080 "
    f"< /dev/null > /tmp/uvicorn.log 2>&1 & echo STARTED"
)
_, stdout, _ = ssh.exec_command(restart_cmd, get_pty=False)
stdout.channel.settimeout(5)
try:
    stdout.read()
except Exception:
    pass
stdout.channel.close()
time.sleep(4)

_, o, _ = ssh.exec_command("curl -s http://localhost:8080/health")
print("Health:", o.read().decode().strip())
ssh.close()
