"""Upload _server_autofinish.sh to server and run it via nohup."""
import os
import paramiko
from pathlib import Path

PROJECT = "/data/weeslee/weeslee-rag"
LOCAL_SH = Path("backend/scripts/_server_autofinish.sh")
REMOTE_SH = f"{PROJECT}/backend/scripts/_server_autofinish.sh"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.0.207", username="weeslee", password=os.environ["DEPLOY_PASSWORD"])
sftp = ssh.open_sftp()

# Upload
sftp.put(str(LOCAL_SH), REMOTE_SH)
print(f"Uploaded: {REMOTE_SH}")
sftp.close()

# chmod + nohup 실행
_, o, e = ssh.exec_command(f"chmod +x {REMOTE_SH}")
o.read(); e.read()

run_cmd = f"nohup bash {REMOTE_SH} </dev/null >> /tmp/autofinish_batch004.log 2>&1 & echo PID=$!"
_, o, _ = ssh.exec_command(run_cmd)
o.channel.settimeout(8)
try:
    out = o.read().decode().strip()
except Exception:
    out = "STARTED"
print(f"Server autofinish started: {out}")
print(f"Log: /tmp/autofinish_batch004.log")

# 현재 서버 프로세스 확인
_, o, _ = ssh.exec_command("ps aux | grep -E 'build_faiss|autofinish' | grep -v grep")
procs = o.read().decode().strip()
print(f"\nRunning processes:\n{procs}")

ssh.close()
