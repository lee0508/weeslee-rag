import json
from pathlib import Path

SNAPSHOT_ID = "snapshot_20260708_src_20260709_072604_1a2872_V1"
SOURCE_ID = "src_20260709_072604_1a2872"


def main() -> None:
    snapshot_path = Path(f"data/snapshots/{SNAPSHOT_ID}.json")
    if not snapshot_path.exists():
        print(json.dumps({"error": "snapshot_missing", "path": str(snapshot_path)}, ensure_ascii=False))
        return

    snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    docs_path = Path(f"data/source/{SOURCE_ID}/documents.jsonl")
    if not docs_path.exists():
        print(
            json.dumps(
                {
                    "error": "documents_jsonl_missing",
                    "path": str(docs_path),
                    "snapshot": {
                        "snapshot_id": snapshot_data.get("snapshot_id"),
                        "source_id": (snapshot_data.get("dataset") or {}).get("source_id"),
                        "dataset_id": (snapshot_data.get("dataset") or {}).get("dataset_id"),
                    },
                },
                ensure_ascii=False,
            )
        )
        return

    pptx_rows = []
    for line in docs_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("extension") or "").lower() == ".pptx":
            pptx_rows.append(
                {
                    "document_id": row.get("document_id"),
                    "file_name": row.get("file_name"),
                    "relative_path": row.get("relative_path"),
                    "project_name": row.get("project_name"),
                    "category": row.get("category") or row.get("document_group"),
                }
            )

    print(
        json.dumps(
            {
                "snapshot_id": snapshot_data.get("snapshot_id"),
                "source_id": (snapshot_data.get("dataset") or {}).get("source_id"),
                "dataset_id": (snapshot_data.get("dataset") or {}).get("dataset_id"),
                "document_count": (snapshot_data.get("dataset") or {}).get("document_count"),
                "chunk_count": (snapshot_data.get("rag_build") or {}).get("chunk_count"),
                "pptx_count": len(pptx_rows),
                "pptx_samples": pptx_rows[:10],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
