import json
from pathlib import Path

SOURCE_ID = "src_20260709_072604_1a2872"
MAX_DOCS = 20


def load_pptx_document_ids() -> list[dict]:
    docs_path = Path(f"data/source/{SOURCE_ID}/documents.jsonl")
    rows = []
    if not docs_path.exists():
        return rows
    for line in docs_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("extension") or "").lower() != ".pptx":
            continue
        rows.append(
            {
                "document_id": str(row.get("document_id")),
                "file_name": row.get("file_name"),
                "relative_path": row.get("relative_path"),
                "project_name": row.get("project_name"),
            }
        )
    return rows


def summarize_doc(row: dict) -> dict:
    document_id = row["document_id"]
    base = Path(f"data/documents/{document_id}")
    report_path = base / "ocr" / "ocr_report.json"
    text_path = base / "ocr" / "full_text.txt"
    chunk_path = base / "chunk" / "chunks.json"

    report = {}
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            report = {}

    text = ""
    if text_path.exists():
        try:
            text = text_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""

    chunk_count = None
    if chunk_path.exists():
        try:
            chunk_data = json.loads(chunk_path.read_text(encoding="utf-8"))
            if isinstance(chunk_data, list):
                chunk_count = len(chunk_data)
            elif isinstance(chunk_data, dict):
                chunk_count = len(chunk_data.get("chunks") or [])
        except Exception:
            chunk_count = None

    preview_lines = [line.strip() for line in text.splitlines() if line.strip()][:5]

    return {
        "document_id": document_id,
        "file_name": row.get("file_name"),
        "relative_path": row.get("relative_path"),
        "project_name": row.get("project_name"),
        "ocr_report_exists": report_path.exists(),
        "full_text_exists": text_path.exists(),
        "chunk_exists": chunk_path.exists(),
        "status": report.get("status"),
        "text_length": len(text),
        "quality_score": (report.get("quality") or {}).get("quality_score"),
        "rag_ready": (report.get("quality") or {}).get("rag_ready"),
        "pages": report.get("pages"),
        "chunks_count": chunk_count,
        "preview_lines": preview_lines,
    }


def main() -> None:
    pptx_rows = load_pptx_document_ids()
    results = [summarize_doc(row) for row in pptx_rows[:MAX_DOCS]]
    total = len(pptx_rows)
    with_text = sum(1 for row in results if row["full_text_exists"] and row["text_length"] > 0)
    rag_ready = sum(1 for row in results if row["rag_ready"])
    print(
        json.dumps(
            {
                "pptx_total": total,
                "checked": len(results),
                "with_text": with_text,
                "rag_ready_count": rag_ready,
                "results": results,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
