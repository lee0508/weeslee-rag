"""
List top-level project folders on W:\01. 국내사업폴더 — no file scanning.
"""
import json
from pathlib import Path

NATIONAL_ROOT = Path(r"W:\01. 국내사업폴더")

batch002 = Path("data/staged/manifest/snapshot_2026-05-06_batch-002-top10-v1_batch-002-top10-v1_20260506_092154.jsonl")
used_folders = set()
for line in batch002.read_text(encoding="utf-8").splitlines():
    if line.strip():
        r = json.loads(line)
        used_folders.add(r["folder_name"])

if not NATIONAL_ROOT.exists():
    print(f"ERROR: {NATIONAL_ROOT} not accessible")
    raise SystemExit(1)

folders = sorted([d for d in NATIONAL_ROOT.iterdir() if d.is_dir()], key=lambda x: x.name)
print(f"Total folders: {len(folders)}")
print(f"Already in batch-002: {len(used_folders)}")
print(f"New for batch-003: {len(folders) - len(used_folders)}")
print()

batch003 = []
for folder in folders:
    name = folder.name
    mark = "002" if name in used_folders else "NEW"
    print(f"[{mark}] {name}")
    if name not in used_folders:
        batch003.append({"folder_name": name, "folder_path": str(folder)})

out = Path("data/staged/batch003_candidates.json")
out.write_text(json.dumps(batch003, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nSaved {len(batch003)} batch-003 candidates → {out}")
