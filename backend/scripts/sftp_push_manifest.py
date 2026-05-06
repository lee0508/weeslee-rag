"""
Push files listed in a manifest JSONL to a remote server via SFTP.

Reads manifest JSONL (produced by build_manifest_from_selected_csv.py),
copies each source_path to the server under dest_raw_root / relative snapshot path.

Skip logic:
- Files that already exist at the destination are skipped.
- Unsupported extensions (hwp) are skipped unless --include-hwp is passed.

Usage:
    python backend/scripts/sftp_push_manifest.py \
        --manifest-jsonl data/staged/manifest/snapshot_....jsonl \
        --host 192.168.0.207 \
        --user weeslee \
        --password "..." \
        --dest-raw-root /data/weeslee/weeslee-rag/data/raw
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath

import paramiko

PHASE1_SKIP_EXT = {".hwp"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SFTP push files from manifest to server")
    p.add_argument("--manifest-jsonl", required=True)
    p.add_argument("--host", default="192.168.0.207")
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--user", default="weeslee")
    p.add_argument("--password", default="")
    p.add_argument("--dest-raw-root", default="/data/weeslee/weeslee-rag/data/raw")
    p.add_argument("--include-hwp", action="store_true", help="Also push .hwp/.hwpx files")
    p.add_argument("--dry-run", action="store_true", help="Print plan without transferring")
    return p.parse_args()


def sftp_mkdirs(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    parts = PurePosixPath(remote_path).parts
    current = ""
    for part in parts:
        current = str(PurePosixPath(current) / part) if current else part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def main() -> int:
    args = parse_args()

    manifest_path = Path(args.manifest_jsonl)
    rows = [json.loads(l) for l in manifest_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    skip_exts = PHASE1_SKIP_EXT if not args.include_hwp else set()

    targets = []
    skipped_ext = []
    missing_local = []

    for row in rows:
        ext = row["extension"].lower()
        source = Path(row["source_path"])
        snapshot_relative = row["snapshot_path"].replace("data/raw/", "", 1).replace("\\", "/")
        dest_remote = args.dest_raw_root.rstrip("/") + "/" + snapshot_relative

        if ext in skip_exts:
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

    if args.dry_run:
        print("[dry-run] First 5 targets:")
        for src, dst, _ in targets[:5]:
            print(f"  {src.name}  ->  {dst}")
        return 0

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(args.host, port=args.port, username=args.user, password=args.password)
    sftp = ssh.open_sftp()

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
        "failures": failures[:10],
    }
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
