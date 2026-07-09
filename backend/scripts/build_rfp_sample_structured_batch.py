from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.extractors.extractor import DocumentExtractor
from app.services.metadata_auto_generator_enhanced import metadata_auto_generator_enhanced
from app.services.processed_text_store import ProcessedTextStore, ProcessingResult
from app.services.rfp_pattern_analyzer import rfp_pattern_analyzer
from app.services.semantic_structure_service import (
    build_pptx_structure,
    build_text_semantic_structure,
    infer_semantic_tags,
)


SUPPORTED_EXTENSIONS = {".hwp", ".hwpx", ".pdf", ".ppt", ".pptx", ".doc", ".docx"}


def _calculate_quality_score(text_length: int) -> float:
    if text_length < 100:
        return 0.3
    if text_length < 500:
        return 0.6
    return 1.0


async def parse_document_local(
    *,
    document_id: int,
    file_path: str,
    force: bool,
    metadata_ctx: dict[str, Any],
    store: ProcessedTextStore,
    parse_config: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "success": False,
        "document_id": document_id,
        "error": None,
        "text_length": 0,
        "warning": None,
        "parser_type": None,
        "processing_time_ms": 0,
        "ocr_use_gpu": False,
    }

    if not force and store.exists(str(document_id)):
        result["success"] = True
        result["error"] = "already_processed"
        return result

    path_obj = Path(file_path)
    if not path_obj.exists():
        result["error"] = f"File not found: {file_path}"
        return result

    processing_result = ProcessingResult(
        document_id=str(document_id),
        file_name=path_obj.name,
        source_path=str(path_obj),
        file_extension=path_obj.suffix.lower(),
        source_id=str(metadata_ctx.get("source_id") or ""),
        dataset_id=str(metadata_ctx.get("dataset_id") or ""),
        document_uid=str(metadata_ctx.get("document_uid") or ""),
        relative_path=str(metadata_ctx.get("relative_path") or ""),
        project_name=str(metadata_ctx.get("project_name") or ""),
        organization=str(metadata_ctx.get("organization") or ""),
        status="processing",
    )

    started_at = datetime.now()
    extractor = DocumentExtractor(
        use_ocr=True,
        ocr_use_gpu=False,
        ocr_dpi=int(parse_config.get("ocr_dpi") or 300),
        ocr_language=str(parse_config.get("ocr_language") or "kor+eng"),
        ocr_min_text_length=int(parse_config.get("ocr_min_text_length") or 50),
        ocr_engine=str(parse_config.get("ocr_engine") or "tesseract"),
    )

    try:
        extract_result = await extractor.extract(str(path_obj))
        text = str(extract_result.get("content") or "")
        processing_result.full_text = text
        processing_result.full_text_md = f"# {path_obj.name}\n\n{text}" if text else ""
        processing_result.parser_type = str(extract_result.get("method") or "unknown")
        processing_result.ocr_engine = str(parse_config.get("ocr_engine") or "")
        result["parser_type"] = processing_result.parser_type

        metadata = extract_result.get("metadata") or {}
        processing_result.quality = dict(metadata.get("quality") or {})
        processing_result.ocr_required = bool(
            metadata.get("is_scanned") or metadata.get("ocr_required")
        )

        extracted_pages = extract_result.get("pages")
        if isinstance(extracted_pages, list) and extracted_pages:
            processing_result.pages = [
                {
                    "page_num": page.get("page_num") or page.get("page_number") or index,
                    "text": page.get("text") or page.get("content") or "",
                    "char_count": len(str(page.get("text") or page.get("content") or "")),
                }
                for index, page in enumerate(extracted_pages, start=1)
            ]

        if path_obj.suffix.lower() == ".pptx":
            structured_data = build_pptx_structure(str(path_obj), processing_result.relative_path or path_obj.name)
            if text.strip():
                text_structure = build_text_semantic_structure(
                    text,
                    document_id=document_id,
                    file_name=path_obj.name,
                    relative_path=processing_result.relative_path or path_obj.name,
                    file_type=path_obj.suffix.lower(),
                )
                structured_data["cover_page"] = text_structure.get("cover_page", {})
                structured_data["toc"] = text_structure.get("toc", {})
                structured_data["detected_sections"] = text_structure.get("detected_sections", [])
                structured_data["document_summary"] = text_structure.get("document_summary", "")
                structured_data["page_types"] = text_structure.get("page_types", [])
            structured_data["semantic_tags"] = infer_semantic_tags(structured_data)
            processing_result.structured_data = structured_data
        elif text.strip():
            processing_result.structured_data = build_text_semantic_structure(
                text,
                document_id=document_id,
                file_name=path_obj.name,
                relative_path=processing_result.relative_path or path_obj.name,
                file_type=path_obj.suffix.lower(),
            )

        processing_result.text_length = len(processing_result.full_text or "")
        processing_result.processing_time_ms = int((datetime.now() - started_at).total_seconds() * 1000)
        result["processing_time_ms"] = processing_result.processing_time_ms
        result["text_length"] = processing_result.text_length

        quality_score = _calculate_quality_score(processing_result.text_length)
        processing_result.quality = {
            **(processing_result.quality or {}),
            "quality_score": quality_score,
            "text_length": processing_result.text_length,
            "recommendation": "excellent" if quality_score > 0.8 else ("acceptable" if quality_score > 0.5 else "review_required"),
            "rag_ready": quality_score >= 0.7 and processing_result.text_length >= 500,
        }

        if not processing_result.full_text.strip():
            processing_result.status = "failed"
            processing_result.error_message = extract_result.get("error") or "Extracted text is empty"
            store.save_result(processing_result)
            result["error"] = processing_result.error_message
            return result

        if not extract_result.get("success", False):
            result["warning"] = extract_result.get("error") or "Extraction completed with warning"

        processing_result.status = "done"
        if store.save_result(processing_result):
            store.save_run_config(
                str(document_id),
                {
                    "source_id": processing_result.source_id,
                    "dataset_id": processing_result.dataset_id,
                    "document_uid": processing_result.document_uid,
                    "relative_path": processing_result.relative_path,
                    "snapshot_id": "",
                    "ocr": {
                        "engine": str(parse_config.get("ocr_engine") or processing_result.ocr_engine or ""),
                        "dpi": int(parse_config.get("ocr_dpi") or 300),
                        "language": str(parse_config.get("ocr_language") or "kor+eng"),
                        "min_text_length": int(parse_config.get("ocr_min_text_length") or 50),
                        "parser_type": processing_result.parser_type,
                    },
                },
            )
            result["success"] = True
            if result["warning"]:
                result["error"] = result["warning"]
            return result

        result["error"] = "Failed to save result"
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build structured_txt and structured_json samples from RFP source files.",
    )
    parser.add_argument(
        "--input-dir",
        default=r"C:\xampp\htdocs\weeslee-mnt\00. RAG 소스\01. RFP",
        help="RFP source folder path",
    )
    parser.add_argument(
        "--source-root",
        default=r"C:\xampp\htdocs\weeslee-mnt",
        help="Base root used to compute relative paths",
    )
    parser.add_argument(
        "--output-txt-root",
        default=r"C:\xampp\htdocs\weeslee-mnt\structured_txt",
        help="structured_txt output root",
    )
    parser.add_argument(
        "--output-json-root",
        default=r"C:\xampp\htdocs\weeslee-mnt\structured_json",
        help="structured_json output root",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Number of files to process. Use 0 to process all files in the input folder.",
    )
    parser.add_argument(
        "--manifest-path",
        default="docs/rfp_sample_structured_manifest.json",
        help="Manifest output path",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run parser even when processed_text_store already has cached data",
    )
    return parser.parse_args()


def build_document_id(file_path: Path, index: int) -> int:
    digest = hashlib.sha1(str(file_path).encode("utf-8")).hexdigest()[:10]
    value = int(digest, 16) % 900000000
    return 100000000 + value + index


def list_sample_files(input_dir: Path, limit: int) -> list[Path]:
    files = [
        path for path in sorted(input_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if limit > 0:
        return files[:limit]
    return files


def as_posix_relative(file_path: Path, source_root: Path) -> str:
    try:
        return file_path.relative_to(source_root).as_posix()
    except ValueError:
        return file_path.name


def render_structured_txt(structured_data: dict[str, Any], full_text: str = "") -> str:
    lines: list[str] = []
    file_name = str(structured_data.get("file_name") or "")
    source_path = str(structured_data.get("source_path") or "")
    relative_path = str(structured_data.get("relative_path") or "")
    section_group = str(structured_data.get("section_group") or "")
    total_slides = int(structured_data.get("total_slides") or 0)

    lines.extend(
        [
            "======",
            f"파일명: {file_name}",
            f"경로명: {source_path}",
            f"상대경로: {relative_path}",
            f"섹션분류: {section_group}",
            f"총슬라이드수: {total_slides}",
            "",
        ]
    )

    for top_index, section in enumerate(structured_data.get("sections") or [], start=1):
        section_name = str(section.get("section_name") or f"섹션 {top_index}")
        lines.append(f"## {top_index}. {section_name}")
        lines.append("")

        for sub_index, subsection in enumerate(section.get("subsections") or [], start=1):
            subsection_name = str(subsection.get("section_name") or f"하위섹션 {sub_index}")
            slide_label = str(subsection.get("slide_label") or "")
            if slide_label:
                lines.append(f"### {top_index}.{sub_index} {subsection_name} ({slide_label})")
            else:
                lines.append(f"### {top_index}.{sub_index} {subsection_name}")

            for item in subsection.get("content_items") or []:
                text = str(item or "").strip()
                if text:
                    lines.append(f"- {text}")
            lines.append("")

    if not structured_data.get("sections") and full_text.strip():
        lines.append("## 본문")
        lines.append("")
        for raw_line in full_text.splitlines():
            text = str(raw_line or "").strip()
            if text:
                lines.append(f"- {text}")

    return "\n".join(lines).strip() + "\n"


def enrich_structured_json(
    *,
    structured_data: dict[str, Any],
    file_name: str,
    relative_path: str,
    full_text: str,
    parser_type: str,
    quality: dict[str, Any],
) -> dict[str, Any]:
    pattern_metadata = rfp_pattern_analyzer.extract_metadata_enhanced(
        filename=file_name,
        text_content=full_text,
        relative_path=relative_path,
    )
    metadata_auto = metadata_auto_generator_enhanced.extract_metadata(
        file_name=file_name,
        file_content=full_text,
        relative_path=relative_path,
        use_rfp_patterns=True,
    )

    payload = dict(structured_data or {})
    payload["source_path"] = payload.get("source_path") or ""
    payload["relative_path"] = payload.get("relative_path") or relative_path
    payload["pattern_metadata"] = pattern_metadata
    payload["metadata_auto"] = metadata_auto
    payload["parser_metadata"] = {
        "parser_type": parser_type,
        "quality": quality or {},
        "text_length": len(full_text or ""),
    }
    return payload


async def process_one(
    *,
    file_path: Path,
    source_root: Path,
    output_txt_root: Path,
    output_json_root: Path,
    force: bool,
    index: int,
    store: ProcessedTextStore,
) -> dict[str, Any]:
    document_id = build_document_id(file_path, index)
    relative_path = as_posix_relative(file_path, source_root)
    file_name = file_path.name
    file_ext = file_path.suffix.lower()

    metadata_ctx = {
        "relative_path": relative_path,
        "source_id": "manual_rfp_sample",
        "dataset_id": "manual_rfp_sample",
        "document_uid": f"manual_{document_id}",
        "project_name": "",
        "organization": "",
    }

    parse_config = {
        "ocr_dpi": 300,
        "ocr_language": "kor+eng",
        "ocr_min_text_length": 50,
        "ocr_engine": "tesseract",
    }

    result = await parse_document_local(
        document_id=document_id,
        file_path=str(file_path),
        force=force,
        metadata_ctx=metadata_ctx,
        parse_config=parse_config,
        store=store,
    )

    processing_result = store.get_result(str(document_id))
    if not processing_result:
        return {
            "success": False,
            "document_id": document_id,
            "file_name": file_name,
            "relative_path": relative_path,
            "error": result.get("error") or "Processing result not found",
        }

    full_text = processing_result.full_text or ""
    structured_data = processing_result.structured_data or {}
    json_payload = enrich_structured_json(
        structured_data=structured_data,
        file_name=file_name,
        relative_path=relative_path,
        full_text=full_text,
        parser_type=processing_result.parser_type,
        quality=processing_result.quality or {},
    )
    txt_payload = render_structured_txt(json_payload, full_text)

    txt_rel = Path(relative_path).with_suffix(".txt")
    json_rel = Path(relative_path).with_suffix(".json")
    txt_path = output_txt_root / txt_rel
    json_path = output_json_root / json_rel
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(txt_payload, encoding="utf-8")
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "success": bool(result.get("success")),
        "document_id": document_id,
        "file_name": file_name,
        "relative_path": relative_path,
        "parser_type": processing_result.parser_type,
        "text_length": len(full_text),
        "structure_mode": json_payload.get("structure_mode"),
        "top_section_count": len(json_payload.get("sections") or []),
        "pattern_document_type": (json_payload.get("pattern_metadata") or {}).get("document_type"),
        "pattern_project_type": (json_payload.get("pattern_metadata") or {}).get("project_type"),
        "pattern_organization": (json_payload.get("pattern_metadata") or {}).get("organization"),
        "txt_output": str(txt_path),
        "json_output": str(json_path),
        "error": result.get("error"),
        "warning": result.get("warning"),
    }


async def async_main(args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir).expanduser().resolve()
    source_root = Path(args.source_root).expanduser().resolve()
    output_txt_root = Path(args.output_txt_root).expanduser().resolve()
    output_json_root = Path(args.output_json_root).expanduser().resolve()
    manifest_path = Path(args.manifest_path).expanduser().resolve()

    if not input_dir.exists():
        raise FileNotFoundError(f"입력 폴더가 없습니다: {input_dir}")

    files = list_sample_files(input_dir, args.limit)
    store = ProcessedTextStore()
    rows: list[dict[str, Any]] = []

    for index, file_path in enumerate(files, start=1):
        row = await process_one(
            file_path=file_path,
            source_root=source_root,
            output_txt_root=output_txt_root,
            output_json_root=output_json_root,
            force=args.force,
            index=index,
            store=store,
        )
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    summary = {
        "input_dir": str(input_dir),
        "source_root": str(source_root),
        "output_txt_root": str(output_txt_root),
        "output_json_root": str(output_json_root),
        "limit": args.limit,
        "processed_count": len(rows),
        "success_count": sum(1 for row in rows if row.get("success")),
        "failure_count": sum(1 for row in rows if not row.get("success")),
        "rows": rows,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest_path": str(manifest_path)}, ensure_ascii=False))
    return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
