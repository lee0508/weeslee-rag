import csv
from pathlib import Path
from collections import Counter

f = Path("data/staged/manifest/phase1_representative_docs_batch003.csv")
rows = list(csv.DictReader(f.open(encoding="utf-8-sig")))

selected = [r for r in rows if r.get("selection_status") not in ("not_found", "")]
not_found = [r for r in rows if r.get("selection_status") == "not_found"]

exts = Counter(Path(r["selected_path"]).suffix.lower() for r in selected if r["selected_path"])
cats = Counter(r["category"] for r in selected)
sizes = [Path(r["selected_path"]).stat().st_size for r in selected if r["selected_path"] and Path(r["selected_path"]).exists()]
total_mb = sum(sizes) / 1024 / 1024

print(f"Total rows     : {len(rows)}")
print(f"Selected       : {len(selected)}")
print(f"Not found      : {len(not_found)}")
print(f"Total size     : {total_mb:.1f} MB")
print(f"Categories     : {dict(cats)}")
print(f"Extensions     : {dict(exts)}")
print()
if not_found:
    print("NOT FOUND:")
    for r in not_found:
        print(f"  [{r['phase1_rank']}] {r['folder_name']} / {r['category']}")
print()
print("First 5 selected:")
for r in selected[:5]:
    print(f"  {Path(r['selected_path']).name}  [{r['category']}]")
