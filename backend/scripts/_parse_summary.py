import csv
from pathlib import Path

f = Path("data/staged/manifest/extraction_summary_batch002_local.csv")
rows = list(csv.DictReader(f.open(encoding="utf-16")))

print(f"Total rows: {len(rows)}")
print()

for r in rows:
    status = r.get("extraction_status", "")
    if status != "success":
        doc_id = r.get("document_id", "")
        ext = r.get("extension", "")
        src = Path(r.get("source_path", "")).name
        error = r.get("error", "")
        method = r.get("extraction_method", "")
        print(f"STATUS : {status}")
        print(f"DOC_ID : {doc_id}")
        print(f"EXT    : {ext}")
        print(f"FILE   : {src}")
        print(f"METHOD : {method}")
        print(f"ERROR  : {error}")
        print()
