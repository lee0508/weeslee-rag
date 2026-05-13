"""
Build chunk JSONL files from extraction summary outputs.

Phase 1 purpose:
- Read the extraction summary CSV
- Load extracted text and metadata for successful rows
- Split each document into section-aware chunks
- Save a unified JSONL chunk file for embedding and FAISS indexing
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


HEADING_PATTERNS = [
    re.compile(r"^\s*[0-9]+\.\s+.+$"),
    re.compile(r"^\s*[0-9]+\)\s+.+$"),
    re.compile(r"^\s*[IVX]+\.\s+.+$", re.IGNORECASE),
    re.compile(r"^\s*[가-힣A-Za-z]+\.\s+.+$"),
    re.compile(r"^\s*\[[^\]]+\]\s*.+$"),
]


@dataclass
class ChunkRow:
    chunk_id: str
    document_id: str
    category: str
    source_path: str
    input_path: str
    extension: str
    chunk_index: int
    char_count: int
    section_heading: str
    text: str
    metadata: dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build chunk batch from extraction summary")
    parser.add_argument("--summary-csv", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--output-csv", default="")
    parser.add_argument("--max-chars", type=int, default=1400)
    parser.add_argument("--overlap-chars", type=int, default=180)
    parser.add_argument("--min-chars", type=int, default=250)
    return parser.parse_args()


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_heading(line: str) -> bool:
    candidate = line.strip()
    if not candidate or len(candidate) > 120:
        return False
    return any(pattern.match(candidate) for pattern in HEADING_PATTERNS)


def split_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        if is_heading(line):
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
                current_lines = []
            current_heading = line.strip()
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    if not sections:
        return [("", text)]
    return sections


def split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def with_overlap(previous_text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or not previous_text:
        return ""
    return previous_text[-overlap_chars:].strip()


def chunk_section(
    section_text: str,
    max_chars: int,
    overlap_chars: int,
    min_chars: int,
) -> Iterable[str]:
    paragraphs = split_paragraphs(section_text)
    if not paragraphs:
        cleaned = section_text.strip()
        if cleaned:
            yield cleaned
        return

    current_parts: list[str] = []
    current_size = 0
    previous_chunk = ""

    for paragraph in paragraphs:
        paragraph_size = len(paragraph)
        projected = current_size + paragraph_size + (2 if current_parts else 0)

        if current_parts and projected > max_chars:
            chunk = "\n\n".join(current_parts).strip()
            if len(chunk) >= min_chars:
                yield chunk
                previous_chunk = chunk
            current_parts = []
            current_size = 0

            overlap = with_overlap(previous_chunk, overlap_chars)
            if overlap:
                current_parts.append(overlap)
                current_size = len(overlap)

        current_parts.append(paragraph)
        current_size += paragraph_size + (2 if current_parts else 0)

    if current_parts:
        chunk = "\n\n".join(current_parts).strip()
        if len(chunk) >= min_chars:
            yield chunk
        elif previous_chunk:
            merged = f"{previous_chunk}\n\n{chunk}".strip()
            yield merged[-max_chars:]
        elif chunk:
            yield chunk


def build_chunks_for_document(
    metadata: dict,
    text: str,
    max_chars: int,
    overlap_chars: int,
    min_chars: int,
) -> list[ChunkRow]:
    text = normalize_text(text)
    sections = split_sections(text)
    document_id = metadata["document_id"]
    rows: list[ChunkRow] = []
    chunk_index = 0

    for heading, section_text in sections:
        for chunk_text in chunk_section(section_text, max_chars, overlap_chars, min_chars):
            rows.append(
                ChunkRow(
                    chunk_id=f"{document_id}-chunk-{chunk_index:04d}",
                    document_id=document_id,
                    category=metadata.get("category", ""),
                    source_path=metadata.get("source_path", ""),
                    input_path=metadata.get("input_path", metadata.get("source_path", "")),
                    extension=metadata.get("extension", ""),
                    chunk_index=chunk_index,
                    char_count=len(chunk_text),
                    section_heading=heading,
                    text=chunk_text,
                    metadata={
                        "document_id": document_id,
                        "category": metadata.get("category", ""),
                        "extension": metadata.get("extension", ""),
                        "section_heading": heading,
                        "project_name": metadata.get("project_name", ""),
                        "project_confidence": metadata.get("project_confidence", 0.0),
                        "organization": metadata.get("organization", ""),
                        "organization_confidence": metadata.get("organization_confidence", 0.0),
                        "organization_client": metadata.get("organization_client", ""),
                        "source_path": metadata.get("source_path", ""),
                        "input_path": metadata.get("input_path", metadata.get("source_path", "")),
                        "folder_year": metadata.get("folder_year", ""),
                        "folder_name": metadata.get("folder_name", ""),
                        "extraction_method": metadata.get("extraction_method", ""),
                        "is_scanned": metadata.get("is_scanned", False),
                        "content_length": metadata.get("content_length", 0),
                        "page_count": metadata.get("page_count", 0),
                        "metadata_confidence": metadata.get("metadata_confidence", {}),
                        # 관리·보고용 보강 필드
                        "file_name": Path(metadata.get("source_path", "")).name,
                        "created_at": metadata.get("extracted_at", ""),
                        "page_no": metadata.get("page_no", 0),
                    },
                )
            )
            chunk_index += 1

    return rows


def main() -> int:
    args = parse_args()
    summary_csv = Path(args.summary_csv).resolve()
    output_jsonl = Path(args.output_jsonl).resolve()
    output_csv = Path(args.output_csv).resolve() if args.output_csv else output_jsonl.with_suffix(".csv")

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    all_rows: list[ChunkRow] = []

    with summary_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("extraction_status") != "success":
                continue

            text_path = Path(row["output_text_path"])
            metadata_path = Path(row["output_metadata_path"])
            if not text_path.exists() or not metadata_path.exists():
                continue

            text = text_path.read_text(encoding="utf-8")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata.setdefault("document_id", row["document_id"])
            metadata.setdefault("category", row.get("category", ""))
            metadata.setdefault("extension", row.get("extension", ""))
            metadata.setdefault("source_path", row.get("source_path", ""))

            all_rows.extend(
                build_chunks_for_document(
                    metadata=metadata,
                    text=text,
                    max_chars=args.max_chars,
                    overlap_chars=args.overlap_chars,
                    min_chars=args.min_chars,
                )
            )

    with output_jsonl.open("w", encoding="utf-8") as handle:
        for row in all_rows:
            handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")

    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "chunk_id",
                "document_id",
                "category",
                "extension",
                "chunk_index",
                "char_count",
                "section_heading",
                "source_path",
                "input_path",
            ],
        )
        writer.writeheader()
        for row in all_rows:
            writer.writerow(
                {
                    "chunk_id": row.chunk_id,
                    "document_id": row.document_id,
                    "category": row.category,
                    "extension": row.extension,
                    "chunk_index": row.chunk_index,
                    "char_count": row.char_count,
                    "section_heading": row.section_heading,
                    "source_path": row.source_path,
                    "input_path": row.input_path,
                }
            )

    counts_by_doc: dict[str, int] = {}
    for row in all_rows:
        counts_by_doc[row.document_id] = counts_by_doc.get(row.document_id, 0) + 1

    print(
        json.dumps(
            {
                "summary_csv": str(summary_csv),
                "output_jsonl": str(output_jsonl),
                "output_csv": str(output_csv),
                "document_count": len(counts_by_doc),
                "chunk_count": len(all_rows),
                "counts_by_document": counts_by_doc,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
