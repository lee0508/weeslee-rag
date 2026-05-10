import json
from pathlib import Path
from collections import defaultdict

# All docs from batch-002 manifest — get list of folders already used
batch002 = Path("data/staged/manifest/snapshot_2026-05-06_batch-002-top10-v1_batch-002-top10-v1_20260506_092154.jsonl")
used_folders = set()
for line in batch002.read_text(encoding="utf-8").splitlines():
    if line.strip():
        r = json.loads(line)
        used_folders.add(r["folder_name"])

print(f"batch-002 used folders ({len(used_folders)}):")
for f in sorted(used_folders):
    print(f"  {f}")
print()

# Check source inventory for all available folders
inventory = Path("data/staged/source_inventory.jsonl")
if not inventory.exists():
    # Try CSV
    import csv
    inv_csv = Path("data/staged/source_inventory.csv")
    if inv_csv.exists():
        rows = list(csv.DictReader(inv_csv.open(encoding="utf-8-sig")))
        folder_counts = defaultdict(int)
        for r in rows:
            folder_counts[r.get("folder_name", r.get("project_folder", ""))] += 1
        print(f"All folders in inventory ({len(folder_counts)}):")
        for f, cnt in sorted(folder_counts.items()):
            mark = "✓" if f in used_folders else " "
            print(f"  [{mark}] {f} ({cnt} files)")
    else:
        print("No inventory file found.")
        import glob
        files = glob.glob("data/staged/*.jsonl") + glob.glob("data/staged/*.csv")
        print("Available staged files:", files)
