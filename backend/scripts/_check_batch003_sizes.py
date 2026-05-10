import json
from pathlib import Path

manifest = Path("data/staged/manifest/snapshot_2026-05-06_batch-003-top10-v1_manifest.jsonl")
rows = [json.loads(l) for l in manifest.read_text(encoding="utf-8").splitlines() if l.strip()]

rows.sort(key=lambda r: r["size_bytes"], reverse=True)
print(f"{'MB':>8}  {'Category':<14}  {'Folder':<50}  File")
print("-" * 120)
for r in rows:
    mb = r["size_bytes"] / 1024 / 1024
    fname = Path(r["source_path"]).name
    folder = r["folder_name"][:48]
    print(f"{mb:8.1f}  {r['category']:<14}  {folder:<50}  {fname}")
