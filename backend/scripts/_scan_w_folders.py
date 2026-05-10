"""
List all top-level project folders on W:\01. 국내사업폴더
and compare with batch-002 coverage to identify batch-003 candidates.
"""
import json
from pathlib import Path, WindowsPath
from collections import defaultdict

NATIONAL_ROOT = Path(r"W:\01. 국내사업폴더")

# Folders already covered in batch-002
batch002 = Path("data/staged/manifest/snapshot_2026-05-06_batch-002-top10-v1_batch-002-top10-v1_20260506_092154.jsonl")
used_folders = set()
for line in batch002.read_text(encoding="utf-8").splitlines():
    if line.strip():
        r = json.loads(line)
        used_folders.add(r["folder_name"])

if not NATIONAL_ROOT.exists():
    print(f"ERROR: {NATIONAL_ROOT} not accessible")
    raise SystemExit(1)

# Scan top-level folders
folders = sorted([d for d in NATIONAL_ROOT.iterdir() if d.is_dir()], key=lambda x: x.name)
print(f"Total project folders on W:\\01. 국내사업폴더: {len(folders)}")
print(f"batch-002 covered: {len(used_folders)}")
print(f"batch-003 candidates: {len(folders) - len(used_folders)}")
print()

batch003_candidates = []
for folder in folders:
    name = folder.name
    in_002 = name in used_folders
    mark = "✓ [002]" if in_002 else "→ [003]"

    # Quick file count for Phase1-supported formats
    supported_exts = {".pdf", ".pptx", ".docx", ".xlsx", ".hwpx"}
    try:
        files = [f for f in folder.rglob("*") if f.suffix.lower() in supported_exts and f.is_file()]
        file_count = len(files)
        total_mb = sum(f.stat().st_size for f in files) / 1024 / 1024
    except PermissionError:
        file_count = -1
        total_mb = 0

    print(f"{mark}  {name}  ({file_count} files, {total_mb:.0f} MB)")
    if not in_002:
        batch003_candidates.append({
            "folder_name": name,
            "folder_path": str(folder),
            "phase1_file_count": file_count,
            "size_mb": round(total_mb, 1),
        })

out = Path("data/staged/batch003_candidates.json")
out.write_text(json.dumps(batch003_candidates, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nSaved {len(batch003_candidates)} candidates → {out}")
