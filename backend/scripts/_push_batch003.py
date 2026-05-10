"""Push batch-003 manifest files to server via SFTP."""
import json
import os
import sys
from pathlib import Path, PurePosixPath
import paramiko

MANIFEST = Path("data/staged/manifest/snapshot_2026-05-06_batch-003-top10-v1_manifest.jsonl")
DEST_RAW_ROOT = "/data/weeslee/weeslee-rag/data/raw"
PHASE1_SKIP_EXT = {".hwp"}

rows = [json.loads(l) for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]

targets = []
skipped_ext = []
missing_local = []

for row in rows:
    ext = row["extension"].lower()
    source = Path(row["source_path"])
    snapshot_relative = row["snapshot_path"].replace("data/raw/", "", 1).replace("\\", "/")
    dest_remote = DEST_RAW_ROOT.rstrip("/") + "/" + snapshot_relative

    if ext in PHASE1_SKIP_EXT:
        skipped_ext.append(row["source_path"])
        continue
    if not source.exists():
        missing_local.append(str(source))
        continue
    targets.append((source, dest_remote, row))

print(f"Files to transfer : {len(targets)}")
print(f"Skipped (hwp)     : {len(skipped_ext)}")
print(f"Missing locally   : {len(missing_local)}")
if missing_local:
    for p in missing_local[:5]:
        print(f"  MISSING: {p}")
print()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.0.207", username="weeslee", password=os.environ["DEPLOY_PASSWORD"])
sftp = ssh.open_sftp()


def sftp_mkdirs(sftp, remote_path):
    parts = PurePosixPath(remote_path).parts
    current = ""
    for part in parts:
        current = str(PurePosixPath(current) / part) if current else part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


copied = skipped_exist = failed = 0
failures = []

for i, (source, dest_remote, row) in enumerate(targets, 1):
    try:
        sftp.stat(dest_remote)
        skipped_exist += 1
        print(f"[{i:3d}/{len(targets)}] SKIP  {source.name}")
        continue
    except FileNotFoundError:
        pass

    try:
        sftp_mkdirs(sftp, str(PurePosixPath(dest_remote).parent))
        sftp.put(str(source), dest_remote)
        copied += 1
        size_kb = source.stat().st_size // 1024
        print(f"[{i:3d}/{len(targets)}] OK    {source.name}  ({size_kb} KB)")
    except Exception as exc:
        failed += 1
        failures.append({"source": str(source), "dest": dest_remote, "error": str(exc)})
        print(f"[{i:3d}/{len(targets)}] FAIL  {source.name}  {exc}", file=sys.stderr)

sftp.close()
ssh.close()

summary = {
    "copied": copied,
    "skipped_exist": skipped_exist,
    "skipped_ext": len(skipped_ext),
    "missing_local": len(missing_local),
    "failed": failed,
}
print()
print(json.dumps(summary, ensure_ascii=False, indent=2))
