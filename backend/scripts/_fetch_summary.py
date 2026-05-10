import os
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.0.207", username="weeslee", password=os.environ["DEPLOY_PASSWORD"])

# Read extraction summary CSV
_, stdout, _ = ssh.exec_command(
    "cat '/data/weeslee/weeslee-rag/data/staged/manifest/"
    "snapshot_2026-05-06_batch-002-top10-v1_batch-002-top10-v1_20260506_092154_extraction_summary.csv'"
)
import sys
sys.stdout.buffer.write(stdout.read())
ssh.close()
