"""
Build chunk JSONL files from extraction summary outputs.

Phase 1 purpose:
- Read the extraction summary CSV
- Load extracted text and metadata for successful rows
- Split each document into section-aware chunks
- Save a unified JSONL chunk file for embedding and FAISS indexing

Phase 2 enhancements:
- Extract page/slide structure from OCR text
- Map chunks to page numbers
- Support section-level metadata extraction
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

# 프로젝트 모듈 임포트를 위한 경로 설정
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.document_structure_extractor import (
    DocumentStructureExtractor,
    DocumentStructure,
    ExtractedPage,
)


HEADING_PATTERNS = [
    re.compile(r"^\s*[0-9]+\.\s+.+$"),
    re.compile(r"^\s*[0-9]+\)\s+.+$"),
    re.compile(r"^\s*[IVX]+\.\s+.+$", re.IGNORECASE),
    re.compile(r"^\s*[가-힣A-Za-z]+\.\s+.+$"),
    re.compile(r"^\s*\[[^\]]+\]\s*.+$"),
]

CHUNKABLE_EXTRACTION_STATUSES = {"success", "skipped_existing"}


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
    # Phase 2: 페이지/슬라이드 정보
    page_no: Optional[int] = None
    slide_no: Optional[int] = None
    start_char: int = 0


# 싱글톤 DocumentStructureExtractor
_structure_extractor: Optional[DocumentStructureExtractor] = None


def get_structure_extractor() -> DocumentStructureExtractor:
    """DocumentStructureExtractor 싱글톤 반환."""
    global _structure_extractor
    if _structure_extractor is None:
        _structure_extractor = DocumentStructureExtractor()
    return _structure_extractor


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
    extension = metadata.get("extension", "").lower().lstrip(".")
    folder_path = metadata.get("relative_path", metadata.get("source_path", ""))

    # Phase 2: 문서 구조 추출 (페이지/섹션)
    extractor = get_structure_extractor()
    try:
        doc_id_int = int(document_id) if str(document_id).isdigit() else hash(document_id) % 1000000
    except (ValueError, TypeError):
        doc_id_int = hash(str(document_id)) % 1000000

    doc_structure = extractor.extract_structure(
        text=text,
        document_id=doc_id_int,
        folder_path=folder_path,
        document_category=metadata.get("document_category"),
        file_type=extension,
    )

    rows: list[ChunkRow] = []
    chunk_index = 0
    current_char_pos = 0  # 현재 문자 위치 추적

    for heading, section_text in sections:
        section_start = current_char_pos

        for chunk_text in chunk_section(section_text, max_chars, overlap_chars, min_chars):
            chunk_len = len(chunk_text)
            chunk_start = current_char_pos
            chunk_end = chunk_start + chunk_len

            # Phase 2: 청크가 속하는 페이지 찾기
            page_no = None
            slide_no = None
            for page in doc_structure.pages:
                if page.start_char <= chunk_start < page.end_char:
                    page_no = page.page_no
                    slide_no = page.slide_no
                    break

            # 못 찾으면 마지막 페이지
            if page_no is None and doc_structure.pages:
                page_no = doc_structure.pages[-1].page_no
                slide_no = doc_structure.pages[-1].slide_no

            rows.append(
                ChunkRow(
                    chunk_id=f"{document_id}-chunk-{chunk_index:04d}",
                    document_id=document_id,
                    category=metadata.get("category", ""),
                    source_path=metadata.get("source_path", ""),
                    input_path=metadata.get("input_path", metadata.get("source_path", "")),
                    extension=metadata.get("extension", ""),
                    chunk_index=chunk_index,
                    char_count=chunk_len,
                    section_heading=heading,
                    text=chunk_text,
                    page_no=page_no,
                    slide_no=slide_no,
                    start_char=chunk_start,
                    metadata={
                        "document_id": document_id,
                        "source_id": metadata.get("source_id", ""),
                        "source_name": metadata.get("source_name", ""),
                        "category": metadata.get("category", ""),
                        "collection_name": metadata.get("collection_name", "weeslee_rag_main"),
                        "document_group": metadata.get("document_group", metadata.get("category", "")),
                        "document_category": metadata.get("document_category", metadata.get("section_label", "")),
                        "document_type": metadata.get("document_type", ""),
                        "extension": metadata.get("extension", ""),
                        "section_heading": heading,
                        "project_name": metadata.get("project_name", ""),
                        "project_confidence": metadata.get("project_confidence", 0.0),
                        "organization": metadata.get("organization", ""),
                        "organization_confidence": metadata.get("organization_confidence", 0.0),
                        "organization_client": metadata.get("organization_client", ""),
                        "source_root": metadata.get("source_root", ""),
                        "source_path": metadata.get("source_path", ""),
                        "original_source_path": metadata.get("original_source_path", metadata.get("source_path", "")),
                        "input_path": metadata.get("input_path", metadata.get("source_path", "")),
                        "relative_path": metadata.get("relative_path", ""),
                        "folder_year": metadata.get("folder_year", ""),
                        "folder_name": metadata.get("folder_name", ""),
                        "root_group": metadata.get("root_group", ""),
                        "root_group_key": metadata.get("root_group_key", ""),
                        "sub_group": metadata.get("sub_group", ""),
                        "sub_group_key": metadata.get("sub_group_key", ""),
                        "proposal_section": metadata.get("proposal_section", ""),
                        "deliverable_section": metadata.get("deliverable_section", ""),
                        "section_label": metadata.get("section_label", ""),
                        "collection_key": metadata.get("collection_key", ""),
                        "search_keywords": metadata.get("search_keywords", []),
                        "extraction_method": metadata.get("extraction_method", ""),
                        "is_scanned": metadata.get("is_scanned", False),
                        "content_length": metadata.get("content_length", 0),
                        "page_count": metadata.get("page_count", doc_structure.total_pages),
                        "metadata_confidence": metadata.get("metadata_confidence", {}),
                        # 관리·보고용 보강 필드
                        "file_name": metadata.get("file_name", Path(metadata.get("source_path", "")).name),
                        "created_at": metadata.get("extracted_at", ""),
                        # Phase 2: 페이지/슬라이드 정보
                        "page_no": page_no or 0,
                        "slide_no": slide_no,
                        "start_char": chunk_start,
                        "total_pages": doc_structure.total_pages,
                    },
                )
            )
            chunk_index += 1
            current_char_pos = chunk_end

    return rows


def main() -> int:
    args = parse_args()
    summary_csv = Path(args.summary_csv).resolve()
    output_jsonl = Path(args.output_jsonl).resolve()
    output_csv = Path(args.output_csv).resolve() if args.output_csv else output_jsonl.with_suffix(".csv")

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    all_rows: list[ChunkRow] = []

    # 전체 문서 수 파악을 위해 먼저 CSV를 읽음
    with summary_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    total_docs = len([r for r in csv_rows if r.get("extraction_status") in CHUNKABLE_EXTRACTION_STATUSES])

    for idx, row in enumerate(csv_rows):
        if row.get("extraction_status") not in CHUNKABLE_EXTRACTION_STATUSES:
            continue

        # 진행률 출력 (JSON 형식으로 파싱 가능하게)
        progress_pct = int((idx / max(len(csv_rows), 1)) * 100)
        print(json.dumps({"progress": progress_pct, "current": idx + 1, "total": total_docs, "stage": "청킹"}), flush=True)

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
                # Phase 2: 페이지/슬라이드 정보
                "page_no",
                "slide_no",
                "start_char",
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
                    # Phase 2: 페이지/슬라이드 정보
                    "page_no": row.page_no or "",
                    "slide_no": row.slide_no or "",
                    "start_char": row.start_char,
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
