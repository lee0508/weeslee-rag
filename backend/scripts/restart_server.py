"""
SSH to the production server, pull latest code, and restart FastAPI (uvicorn).

Server details are read from environment variables first; falls back to defaults
that match the existing internal deployment setup.

Usage:
    python backend/scripts/restart_server.py
"""
from __future__ import annotations

import os
import subprocess
import sys

SERVER_HOST = os.environ.get("DEPLOY_HOST", "192.168.0.207")
SERVER_USER = os.environ.get("DEPLOY_USER", "weeslee")
SERVER_PASSWORD = os.environ.get("DEPLOY_PASSWORD", "***REMOVED***")
PROJECT_DIR = os.environ.get("DEPLOY_PROJECT", "/data/weeslee/weeslee-rag")
PYTHON = os.environ.get("DEPLOY_PYTHON", f"{PROJECT_DIR}/.venv/bin/python3")

RESTART_CMD = (
    f"cd {PROJECT_DIR}/backend && git -C {PROJECT_DIR} pull origin main 2>&1 && "
    f"pkill -f 'uvicorn app.main:app' 2>/dev/null; sleep 2; "
    f"nohup {PYTHON} -m uvicorn app.main:app --host 0.0.0.0 --port 8080 "
    f"> /tmp/weeslee_fastapi.log 2>&1 & echo RESTARTED"
)


def validate_local() -> bool:
    """Syntax check key backend files. Skips if venv packages are missing locally."""
    import ast
    files = [
        "backend/app/api/rag.py",
        "backend/app/services/query_expander.py",
        "backend/scripts/assemble_rag_response.py",
        "backend/scripts/build_chunk_batch.py",
    ]
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for rel in files:
        path = os.path.join(root, rel)
        try:
            ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError as exc:
            print(f"[validate] SYNTAX ERROR in {rel}: {exc}")
            return False
    print("[validate] syntax OK")
    return True


def git_push() -> bool:
    result = subprocess.run(
        ["git", "push", "origin", "main"],
        capture_output=True, text=True,
    )
    msg = (result.stdout + result.stderr).strip()
    print("[git push]", msg or "no output")
    return result.returncode == 0


def restart_remote() -> bool:
    try:
        import paramiko  # type: ignore
    except ImportError:
        print("[restart] paramiko not installed — skipping server restart")
        return False

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(SERVER_HOST, username=SERVER_USER, password=SERVER_PASSWORD, timeout=15)
        _, stdout, _ = ssh.exec_command(RESTART_CMD)
        out = stdout.read().decode().strip()
        print("[restart]", out or "(no output)")
        return "RESTARTED" in out
    except Exception as exc:
        print("[restart] ERROR:", exc)
        return False
    finally:
        ssh.close()


def main() -> int:
    print("=== Deploy ===")

    if not validate_local():
        print("Local validation failed - aborting deploy.")
        return 1

    if not git_push():
        print("git push failed - server not restarted.")
        return 1

    if not restart_remote():
        print("Server restart may have failed. Check /tmp/weeslee_fastapi.log on server.")
        return 1

    print("=== Done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
