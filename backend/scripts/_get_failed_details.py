import json
from pathlib import Path

jsonl = Path("data/staged/manifest/snapshot_2026-05-06_batch-002-top10-v1_batch-002-top10-v1_20260506_092154.jsonl")
failed_ids = {
    "DOC-20260506-000005",
    "DOC-20260506-000007",
    "DOC-20260506-000038",
    "DOC-20260506-000045",
    "DOC-20260506-000048",
}

rows = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
for r in rows:
    if r["document_id"] in failed_ids:
        print(f"DOC_ID   : {r['document_id']}")
        print(f"FILE     : {Path(r['source_path']).name}")
        print(f"EXT      : {r['extension']}")
        print(f"CATEGORY : {r['category']}")
        print(f"FOLDER   : {r['folder_name']}")
        print(f"SIZE_MB  : {r['size_bytes'] / 1024 / 1024:.1f}")
        print()
