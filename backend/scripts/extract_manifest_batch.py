"""
Extract text for a curated manifest batch and save results under data/staged.

This script is designed for the phase 1 PoC workflow:
- Read a manifest CSV
- Extract text for supported formats
- Save extracted text into data/staged/text
- Save extraction metadata into data/staged/metadata
- Save a batch summary CSV

Legacy binary Office formats and plain text files are recorded as skipped so
they do not enter the chunking and FAISS stages with unclear extractor output.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from html import escape
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.extractors.extractor import DocumentExtractor  # noqa: E402
from app.extractors.pdf_extractor import _is_tesseract_available  # noqa: E402
from app.services.metadata_enricher import enrich_confidence  # noqa: E402


SUPPORTED_FOR_PHASE1 = {".pdf", ".hwp", ".hwpx", ".docx", ".pptx", ".xlsx"}
UNSUPPORTED_FOR_PHASE1 = {".doc", ".ppt", ".xls", ".txt"}
EXTRACTED_TEXT_DIR = PROJECT_ROOT / "data" / "extracted_text"


def _detect_ocr() -> bool:
    """Check tesseract availability and print status. Returns True if available."""
    available = _is_tesseract_available()
    status = "available" if available else "NOT available (install tesseract-ocr + pytesseract)"
    print(json.dumps({"ocr_status": status, "tesseract_available": available}))
    return available

_DATE_PREFIX = re.compile(r"^\d+\.\s*")


def enrich_project_metadata(folder_name: str) -> dict:
    """Extract project_name, folder_year, org, and confidence scores from folder_name."""
    project_name = _DATE_PREFIX.sub("", folder_name).strip()
    year_match = re.match(r"^(\d{4})", folder_name)
    folder_year = year_match.group(1) if year_match else ""
    confidence = enrich_confidence(folder_name, project_name)
    return {
        "project_name": project_name,
        "folder_year": folder_year,
        "folder_name": folder_name,
        **confidence,
    }


@dataclass
class ExtractionRow:
    document_id: str
    category: str
    source_path: str
    extension: str
    extraction_status: str
    extraction_method: str
    output_text_path: str
    output_metadata_path: str
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract manifest batch")
    parser.add_argument("--manifest-csv", required=True)
    parser.add_argument("--text-dir", default="data/staged/text")
    parser.add_argument("--metadata-dir", default="data/staged/metadata")
    parser.add_argument("--summary-csv", default="")
    parser.add_argument("--use-ocr", action="store_true",
                        help="Enable Tesseract OCR for scanned PDFs")
    parser.add_argument("--auto-ocr", action="store_true",
                        help="Auto-enable OCR if tesseract is available (overrides --use-ocr detection)")
    parser.add_argument("--ocr-dpi", type=int, default=300, help="OCR DPI for image conversion")
    parser.add_argument("--ocr-lang", default="kor+eng", help="OCR language for tesseract")
    parser.add_argument("--ocr-min-text-length", type=int, default=50, help="Minimum text threshold to treat PDF as text-based")
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def resolve_input_path(row: dict[str, str]) -> Path:
    snapshot_path = (row.get("snapshot_path") or "").strip()
    if snapshot_path:
        snapshot_candidate = Path(snapshot_path)
        if not snapshot_candidate.is_absolute():
            snapshot_candidate = PROJECT_ROOT / snapshot_candidate
        if snapshot_candidate.exists():
            return snapshot_candidate

    source_path = (row.get("source_path") or "").strip()
    if source_path:
        return Path(source_path)

    return Path("")


def build_output_paths(text_dir: Path, metadata_dir: Path, document_id: str) -> tuple[Path, Path]:
    return text_dir / f"{document_id}.txt", metadata_dir / f"{document_id}.json"


def _preferred_value(row: dict[str, str], key: str, fallback: str = "") -> str:
    value = (row.get(key) or "").strip()
    return value or fallback


def _derived_output_dir(document_id: str) -> Path:
    path = EXTRACTED_TEXT_DIR / str(document_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_derived_outputs(document_id: str, content: str, metadata: dict) -> None:
    derived_dir = _derived_output_dir(document_id)
    (derived_dir / "raw_text.txt").write_text(content, encoding="utf-8")
    (derived_dir / "document.md").write_text(content, encoding="utf-8")
    html = (
        "<html><head><meta charset=\"UTF-8\"></head><body>"
        f"<pre>{escape(content)}</pre></body></html>"
    )
    (derived_dir / "document.html").write_text(html, encoding="utf-8")
    (derived_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _existing_outputs_are_current(input_path: Path, text_path: Path, metadata_path: Path) -> bool:
    if not text_path.is_file() or not metadata_path.is_file():
        return False
    if not input_path.is_file():
        return True
    output_mtime = min(text_path.stat().st_mtime, metadata_path.stat().st_mtime)
    return output_mtime >= input_path.stat().st_mtime


def _merge_existing_metadata(metadata_path: Path, row: dict[str, str], input_path: Path, source_path: Path, extension: str) -> dict:
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        metadata = {}
    metadata.update({
        "document_id": row.get("document_id", metadata.get("document_id", "")),
        "source_id": row.get("source_id", metadata.get("source_id", "")),
        "dataset_id": row.get("dataset_id", metadata.get("dataset_id", "")),
        "source_name": row.get("source_name", metadata.get("source_name", "")),
        "category": row.get("category", metadata.get("category", "")),
        "collection_name": row.get("collection_name", metadata.get("collection_name", "weeslee_rag_main")),
        "document_group": row.get("document_group", metadata.get("document_group", "")),
        "document_category": row.get("document_category", metadata.get("document_category", "")),
        "document_type": row.get("document_type", metadata.get("document_type", "")),
        "proposal_section": row.get("proposal_section", metadata.get("proposal_section", "")),
        "deliverable_section": row.get("deliverable_section", metadata.get("deliverable_section", "")),
        "collection_key": row.get("collection_key", metadata.get("collection_key", "")),
        "source_path": str(source_path),
        "input_path": str(input_path),
        "snapshot_path": row.get("snapshot_path", metadata.get("snapshot_path", "")),
        "relative_path": row.get("relative_path", metadata.get("relative_path", "")),
        "extension": extension,
        "project_name": row.get("project_name", metadata.get("project_name", "")),
        "organization": row.get("organization", metadata.get("organization", "")),
        "folder_year": row.get("project_year", metadata.get("folder_year", "")),
        "folder_name": row.get("folder_name", metadata.get("folder_name", "")),
        "root_group": row.get("root_group", metadata.get("root_group", "")),
        "root_group_key": row.get("root_group_key", metadata.get("root_group_key", "")),
        "sub_group": row.get("sub_group", metadata.get("sub_group", "")),
        "sub_group_key": row.get("sub_group_key", metadata.get("sub_group_key", "")),
        "section_label": row.get("section_label", metadata.get("section_label", "")),
    })
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


async def run_batch(args: argparse.Namespace) -> int:
    manifest_csv = Path(args.manifest_csv).resolve()
    text_dir = Path(args.text_dir).resolve()
    metadata_dir = Path(args.metadata_dir).resolve()
    summary_csv = (
        Path(args.summary_csv).resolve()
        if args.summary_csv
        else manifest_csv.with_name(f"{manifest_csv.stem}_extraction_summary.csv")
    )

    ensure_dir(text_dir)
    ensure_dir(metadata_dir)
    ensure_dir(summary_csv.parent)

    # OCR: --use-ocr explicit OR --auto-ocr with tesseract detected
    use_ocr = args.use_ocr or (args.auto_ocr and _detect_ocr())
    if not args.use_ocr and not args.auto_ocr:
        _detect_ocr()  # print status even when OCR not requested

    extractor = DocumentExtractor(
        use_ocr=use_ocr,
        ocr_dpi=args.ocr_dpi,
        ocr_language=args.ocr_lang,
        ocr_min_text_length=args.ocr_min_text_length,
    )
    results: list[ExtractionRow] = []

    # 전체 문서 수 파악을 위해 먼저 CSV를 읽음
    with manifest_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        all_rows = list(csv.DictReader(handle))
    total_docs = len(all_rows)

    for idx, row in enumerate(all_rows):
        # 진행률 출력 (JSON 형식으로 파싱 가능하게)
        progress_pct = int((idx / max(total_docs, 1)) * 100)
        print(json.dumps({"progress": progress_pct, "current": idx + 1, "total": total_docs, "stage": "텍스트 추출"}), flush=True)

        document_id = row["document_id"]
        input_path = resolve_input_path(row)
        source_path = Path(row["source_path"])
        extension = input_path.suffix.lower() or source_path.suffix.lower()
        category = row.get("category", "")
        text_path, metadata_path = build_output_paths(text_dir, metadata_dir, document_id)

        if _existing_outputs_are_current(input_path, text_path, metadata_path):
            metadata = _merge_existing_metadata(metadata_path, row, input_path, source_path, extension)
            content = text_path.read_text(encoding="utf-8")
            _write_derived_outputs(document_id, content, metadata)
            results.append(
                ExtractionRow(
                    document_id=document_id,
                    category=category,
                    source_path=str(input_path),
                    extension=extension,
                    extraction_status="skipped_existing",
                    extraction_method=metadata.get("extraction_method", "existing"),
                    output_text_path=str(text_path),
                    output_metadata_path=str(metadata_path),
                    error="",
                )
            )
            continue

        if extension in UNSUPPORTED_FOR_PHASE1:
            results.append(
                ExtractionRow(
                    document_id=document_id,
                    category=category,
                    source_path=str(source_path),
                    extension=extension,
                    extraction_status="skipped_unsupported",
                    extraction_method="",
                    output_text_path="",
                    output_metadata_path="",
                    error=f"Unsupported format (no extractor): {extension}",
                )
            )
            continue

        if extension not in SUPPORTED_FOR_PHASE1:
            results.append(
                ExtractionRow(
                    document_id=document_id,
                    category=category,
                    source_path=str(source_path),
                    extension=extension,
                    extraction_status="skipped_unknown",
                    extraction_method="",
                    output_text_path="",
                    output_metadata_path="",
                    error=f"Unknown extension: {extension}",
                )
            )
            continue

        result = await extractor.extract(str(input_path))

        if result.get("success"):
            content = result.get("content", "")
            project_meta = enrich_project_metadata(row.get("folder_name", ""))
            res_meta = result.get("metadata", {})
            project_name = _preferred_value(row, "project_name", project_meta["project_name"])
            organization = _preferred_value(row, "organization", project_meta["organization"])
            folder_year = _preferred_value(row, "project_year", project_meta["folder_year"])
            metadata = {
                "document_id": document_id,
                "source_id": row.get("source_id", ""),
                "dataset_id": row.get("dataset_id", ""),
                "source_name": row.get("source_name", ""),
                "category": category,
                "collection_name": row.get("collection_name", "weeslee_rag_main"),
                "document_group": row.get("document_group", ""),
                "document_category": row.get("document_category", ""),
                "document_type": row.get("document_type", ""),
                "proposal_section": row.get("proposal_section", ""),
                "deliverable_section": row.get("deliverable_section", ""),
                "collection_key": row.get("collection_key", ""),
                "source_path": str(source_path),
                "input_path": str(input_path),
                "snapshot_path": row.get("snapshot_path", ""),
                "relative_path": row.get("relative_path", ""),
                "extension": extension,
                "project_name": project_name,
                "project_confidence": project_meta["project_confidence"],
                "organization": organization,
                "organization_confidence": project_meta["organization_confidence"],
                "folder_year": folder_year,
                "folder_name": row.get("folder_name", project_meta["folder_name"]),
                "root_group": row.get("root_group", ""),
                "root_group_key": row.get("root_group_key", ""),
                "sub_group": row.get("sub_group", ""),
                "sub_group_key": row.get("sub_group_key", ""),
                "section_label": row.get("section_label", ""),
                "extraction_method": result.get("method", ""),
                "is_scanned": res_meta.get("is_scanned", False),
                "content_length": len(content),
                "page_count": res_meta.get("pages", 0),
                "metadata_confidence": {
                    "project_name": project_meta["project_confidence"],
                    "organization": project_meta["organization_confidence"],
                },
                "extracted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "result": result,
            }
            text_path.write_text(content, encoding="utf-8")
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _write_derived_outputs(document_id, content, metadata)
            results.append(
                ExtractionRow(
                    document_id=document_id,
                    category=category,
                    source_path=str(input_path),
                    extension=extension,
                    extraction_status="success",
                    extraction_method=result.get("method", ""),
                    output_text_path=str(text_path),
                    output_metadata_path=str(metadata_path),
                    error="",
                )
            )
        else:
            # Distinguish scanned-PDF-no-OCR from genuine extraction failures
            is_scan_no_ocr = result.get("method") == "scanned_ocr_disabled"
            results.append(
                ExtractionRow(
                    document_id=document_id,
                    category=category,
                    source_path=str(input_path),
                    extension=extension,
                    extraction_status="skipped_scan_no_ocr" if is_scan_no_ocr else "failed",
                    extraction_method=result.get("method", ""),
                    output_text_path="",
                    output_metadata_path="",
                    error=result.get("error", "Unknown extraction error"),
                )
            )

    with summary_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(results[0]).keys()) if results else [])
        if results:
            writer.writeheader()
            for row in results:
                writer.writerow(asdict(row))

    counters: dict[str, int] = {}
    for row in results:
        counters[row.extraction_status] = counters.get(row.extraction_status, 0) + 1

    print(
        json.dumps(
            {
                "manifest_csv": str(manifest_csv),
                "summary_csv": str(summary_csv),
                "text_dir": str(text_dir),
                "metadata_dir": str(metadata_dir),
                "counts": counters,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(run_batch(args))


if __name__ == "__main__":
    raise SystemExit(main())
