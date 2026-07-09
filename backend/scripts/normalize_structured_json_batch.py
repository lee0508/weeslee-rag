from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ORDER_PREFIX_RE = re.compile(r"^\s*\d+\.\s*")


def strip_order_prefix(value: str) -> str:
    return ORDER_PREFIX_RE.sub("", str(value or "")).strip()


def parse_relative_path(relative_path: str) -> tuple[str, str, str]:
    parts = [part for part in str(relative_path or "").replace("\\", "/").split("/") if part]
    source_root = parts[0] if len(parts) >= 1 else ""
    document_group = strip_order_prefix(parts[1]) if len(parts) >= 2 else ""
    section_type = strip_order_prefix(parts[2]) if len(parts) >= 3 else ""
    return source_root, document_group, section_type


def project_name_from_filename(file_name: str, section_type: str) -> str:
    stem = re.sub(r"\.(pptx|pdf|hwpx|hwp|docx)$", "", str(file_name or ""), flags=re.IGNORECASE)
    if section_type and stem.startswith(section_type + "_"):
        return stem[len(section_type) + 1 :].strip()
    if "_" in stem:
        return stem.split("_", 1)[1].strip()
    return stem.strip()


def normalize_keywords(values: object, limit: int = 20) -> list[str]:
    rows = values if isinstance(values, list) else []
    result: list[str] = []
    for row in rows:
        token = str(row or "").strip()
        if len(token) < 2:
            continue
        if token not in result:
            result.append(token)
        if len(result) >= limit:
            break
    return result


def iter_chunks(section: dict, heading_path: list[str]) -> list[dict]:
    chunks: list[dict] = []
    section_name = str(section.get("section_name") or "").strip()
    current_path = [*heading_path, section_name] if section_name else list(heading_path)
    text_items = [str(item or "").strip() for item in (section.get("content_items") or []) if str(item or "").strip()]
    text = "\n".join(text_items).strip()
    slide_range = section.get("slide_range") or []
    slide_numbers = section.get("slide_numbers") or []
    if text:
        chunks.append(
            {
                "section_id": str(section.get("section_id") or ""),
                "section_name": section_name,
                "heading_path": current_path,
                "text": text,
                "slide_range": slide_range,
                "slide_numbers": slide_numbers,
                "keywords": normalize_keywords(section.get("keywords")),
            }
        )

    for child in section.get("subsections") or []:
        if isinstance(child, dict) and "content_items" in child:
            chunks.extend(iter_chunks(child, current_path))
    return chunks


def normalize_document(path: Path) -> tuple[dict, list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    relative_path = str(payload.get("relative_path") or "")
    file_name = str(payload.get("file_name") or path.name)
    source_root, document_group, section_type = parse_relative_path(relative_path)
    project_name = project_name_from_filename(file_name, section_type)

    doc = {
        "file_name": file_name,
        "source_path": str(payload.get("source_path") or ""),
        "relative_path": relative_path,
        "source_root": source_root,
        "document_group": document_group,
        "section_type": section_type,
        "section_group_raw": str(payload.get("section_group") or ""),
        "project_name": project_name,
        "document_type": str(payload.get("document_type") or ""),
        "total_slides": int(payload.get("total_slides") or 0),
        "structure_mode": str(payload.get("structure_mode") or ""),
        "top_keywords": normalize_keywords(
            [kw for section in (payload.get("sections") or []) for kw in (section.get("keywords") or [])],
            limit=30,
        ),
    }

    chunks: list[dict] = []
    base_path = [document_group, section_type, project_name]
    for section in payload.get("sections") or []:
        if isinstance(section, dict):
            chunks.extend(iter_chunks(section, base_path))
    return doc, chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize structured_json files into metadata/chunk JSONL.")
    parser.add_argument("--input-root", required=True, help="structured_json root path")
    parser.add_argument("--output-dir", required=True, help="output directory for normalized jsonl files")
    parser.add_argument("--limit", type=int, default=0, help="max files to process (0=all)")
    args = parser.parse_args()

    input_root = Path(args.input_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = output_dir / "normalized_documents.jsonl"
    chunks_path = output_dir / "normalized_chunks.jsonl"
    summary_path = output_dir / "summary.json"

    files = sorted(input_root.rglob("*.json"))
    if args.limit > 0:
        files = files[: args.limit]

    document_count = 0
    chunk_count = 0
    groups: dict[str, int] = {}
    sections: dict[str, int] = {}

    with metadata_path.open("w", encoding="utf-8") as doc_handle, chunks_path.open("w", encoding="utf-8") as chunk_handle:
        for path in files:
            try:
                doc, chunks = normalize_document(path)
            except Exception as exc:
                print(json.dumps({"warning": f"{path}: {exc}"}, ensure_ascii=False))
                continue

            doc_handle.write(json.dumps(doc, ensure_ascii=False) + "\n")
            for idx, chunk in enumerate(chunks, start=1):
                row = {
                    "chunk_id": f"{doc['project_name']}::{idx:04d}",
                    "file_name": doc["file_name"],
                    "relative_path": doc["relative_path"],
                    "document_group": doc["document_group"],
                    "section_type": doc["section_type"],
                    "project_name": doc["project_name"],
                    **chunk,
                }
                chunk_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                chunk_count += 1

            document_count += 1
            groups[doc["document_group"]] = groups.get(doc["document_group"], 0) + 1
            sections[doc["section_type"]] = sections.get(doc["section_type"], 0) + 1

    summary = {
        "input_root": str(input_root),
        "output_dir": str(output_dir),
        "document_count": document_count,
        "chunk_count": chunk_count,
        "document_groups": groups,
        "section_types": sections,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
