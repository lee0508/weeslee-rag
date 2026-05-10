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
result = []
for r in rows:
    if r["document_id"] in failed_ids:
        result.append({
            "document_id": r["document_id"],
            "filename": Path(r["source_path"]).name,
            "extension": r["extension"],
            "category": r["category"],
            "folder_name": r["folder_name"],
            "size_mb": round(r["size_bytes"] / 1024 / 1024, 1),
        })

out = Path("data/staged/manifest/_failed_docs_batch002.json")
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Written to {out}")
