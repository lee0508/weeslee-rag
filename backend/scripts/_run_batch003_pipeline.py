"""
Push batch-003 manifest/CSV to server, then run extract → chunk → faiss pipeline.
Each step is run via nohup; progress is polled via log files.
"""
import json
import os
import time
import paramiko
from pathlib import Path

SNAPSHOT = "snapshot_2026-05-06_batch-003-top10-v1"
PROJECT = "/data/weeslee/weeslee-rag"
PYTHON = f"{PROJECT}/.venv/bin/python3"
SCRIPTS = f"{PROJECT}/backend/scripts"
MANIFEST_DIR = f"{PROJECT}/data/staged/manifest"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.0.207", username="weeslee", password=os.environ["DEPLOY_PASSWORD"])
sftp = ssh.open_sftp()

# 1. Upload manifest JSONL
local_jsonl = Path(f"data/staged/manifest/{SNAPSHOT}_manifest.jsonl")
remote_jsonl = f"{MANIFEST_DIR}/{SNAPSHOT}_manifest.jsonl"
sftp.put(str(local_jsonl), remote_jsonl)
print(f"Uploaded manifest JSONL → {remote_jsonl}")

# 2. Convert JSONL to CSV on server
conv_cmd = f"""python3 -c "
import json, csv
from pathlib import Path
src = Path('{remote_jsonl}')
rows = [json.loads(l) for l in src.read_text(encoding='utf-8').splitlines() if l.strip()]
supported = {{'.pdf', '.pptx', '.docx', '.xlsx', '.hwpx'}}
phase1 = [r for r in rows if r['extension'].lower() in supported]
dst = src.with_suffix('.csv')
fields = ['document_id','category','source_path','snapshot_path','extension','sha256','folder_name']
import csv
with dst.open('w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
    w.writeheader()
    w.writerows(phase1)
print(f'Written {{len(phase1)}} rows to {{dst.name}}')
"
"""
_, stdout, stderr = ssh.exec_command(conv_cmd)
print("CSV conversion:", stdout.read().decode().strip())

CSV_PATH = f"{MANIFEST_DIR}/{SNAPSHOT}_manifest.csv"

# 3. Run extraction
extract_cmd = (
    f"cd {PROJECT} && "
    f"nohup {PYTHON} {SCRIPTS}/extract_manifest_batch.py"
    f" --manifest-csv {CSV_PATH}"
    f" --text-dir {PROJECT}/data/staged/text"
    f" --metadata-dir {PROJECT}/data/staged/metadata"
    f" < /dev/null > /tmp/extract_batch003.log 2>&1 & echo STARTED"
)
_, stdout, _ = ssh.exec_command(extract_cmd, get_pty=False)
stdout.channel.settimeout(5)
try:
    print("Extraction:", stdout.read().decode().strip())
except Exception:
    print("Extraction: STARTED (timeout reading stdout)")
stdout.channel.close()

print("Waiting 60s for extraction to complete...")
time.sleep(60)

# Poll extraction log
_, stdout, _ = ssh.exec_command("tail -5 /tmp/extract_batch003.log")
log = stdout.read().decode()
print("Extraction log:", log)

sftp.close()
ssh.close()
print("Done. Check /tmp/extract_batch003.log on server for extraction results.")
