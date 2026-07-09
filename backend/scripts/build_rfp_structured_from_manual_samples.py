from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from app.services.metadata_auto_generator_enhanced import metadata_auto_generator_enhanced
from app.services.rfp_pattern_analyzer import rfp_pattern_analyzer


KEY_VALUE_RE = re.compile(r"^(?P<key>[^:]+):\s*(?P<value>.+?)\s*$")
PAGE_RANGE_RE = re.compile(r"page\s+(\d+)(?:\s*-\s*(\d+))?", re.IGNORECASE)
NUMBER_PREFIX_RE = re.compile(r"^\d+\.\s*")
LOOSE_NUMBER_PREFIX_RE = re.compile(r"^\d+\s+")

CONTROL_MARKER_ALIASES = {
    "년도": "년월",
    "년월": "년월",
    "기관명": "기관명",
    "주관기관": "주관기관",
    "사업명": "사업명",
    "제목": "제목",
}
SECTION_MARKER_PREFIXES = ("표지내용", "표지 내용", "목차", "목차 내용")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert manually curated RFP structure markdown samples into structured_txt/json outputs.",
    )
    parser.add_argument(
        "--sample-md",
        nargs="+",
        default=["docs/2026-07-07_Lee_RFP_문서_구조화_샘플.md"],
        help="One or more markdown sample files containing manual structure entries.",
    )
    parser.add_argument(
        "--source-root",
        default=r"C:\xampp\htdocs\weeslee-mnt",
        help="Base root used to compute relative paths.",
    )
    parser.add_argument(
        "--output-txt-root",
        default=r"C:\xampp\htdocs\weeslee-mnt\structured_txt",
        help="structured_txt output root.",
    )
    parser.add_argument(
        "--output-json-root",
        default=r"C:\xampp\htdocs\weeslee-mnt\structured_json",
        help="structured_json output root.",
    )
    parser.add_argument(
        "--manifest-path",
        default="docs/rfp_manual_structured_manifest.json",
        help="Manifest json output path.",
    )
    return parser.parse_args()


def split_entries(raw_text: str) -> list[str]:
    lines = str(raw_text or "").splitlines()
    entries: list[str] = []
    current: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        normalized = normalize_line(line)
        if normalized.startswith("경로명:") and current:
            entry = "\n".join(current).strip()
            if entry and "파일명:" in entry:
                entries.append(entry)
            current = [line]
            continue
        if normalized.startswith("======"):
            continue
        current.append(line)

    if current:
        entry = "\n".join(current).strip()
        if entry and "파일명:" in entry:
            entries.append(entry)

    return entries


def normalize_line(line: str) -> str:
    return str(line or "").replace("\u3000", " ").strip()


def strip_number_prefix(line: str) -> str:
    normalized = normalize_line(line)
    normalized = NUMBER_PREFIX_RE.sub("", normalized)
    normalized = LOOSE_NUMBER_PREFIX_RE.sub("", normalized)
    return normalized.strip()


def normalize_relpath(source_path: str, file_name: str, source_root: Path) -> str:
    source_path_obj = Path(str(source_path or "").strip())
    file_name_obj = Path(str(file_name or "").strip())
    try:
        rel_dir = source_path_obj.relative_to(source_root).as_posix()
        return f"{rel_dir}/{file_name_obj.name}".strip("/")
    except Exception:
        joined = source_path_obj / file_name_obj.name if source_path_obj else file_name_obj
        return joined.as_posix().replace("\\", "/").strip("/")


def parse_page_range(text: str) -> list[int]:
    matched = PAGE_RANGE_RE.search(str(text or ""))
    if not matched:
        return []
    start = int(matched.group(1))
    end = int(matched.group(2) or matched.group(1))
    if end < start:
        start, end = end, start
    return [start, end]


def canonical_section_name(value: str) -> str:
    text = normalize_line(value)
    text = strip_number_prefix(text)
    text = re.sub(r"\s*-\s*page\s+\d+(\s*-\s*\d+)?\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\-\s*", "", text).strip()
    return text


def strip_page_suffix(value: str) -> str:
    return re.sub(r"\s*-\s*page\s+\d+(\s*-\s*\d+)?\s*$", "", normalize_line(value), flags=re.IGNORECASE).strip()


def parse_cover_fields(lines: list[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for raw_line in lines:
        line = strip_number_prefix(raw_line)
        if not line:
            continue
        if any(line.startswith(prefix) for prefix in SECTION_MARKER_PREFIXES):
            continue
        matched = KEY_VALUE_RE.match(line)
        if not matched:
            continue
        key = normalize_line(matched.group("key"))
        value = normalize_line(matched.group("value"))
        normalized_key = CONTROL_MARKER_ALIASES.get(key, key)
        fields[normalized_key] = value
    return fields


def parse_manual_entry(entry_text: str, source_root: Path) -> dict[str, Any]:
    original_lines = [str(line).rstrip() for line in str(entry_text or "").splitlines()]
    lines = [normalize_line(line) for line in original_lines]
    lines = [line for line in lines if line]

    source_path = ""
    file_name = ""
    cover_lines: list[str] = []
    toc_lines: list[str] = []
    section_rows: list[dict[str, Any]] = []
    current_mode = "body"
    current_top: dict[str, Any] | None = None

    for line in lines:
        if line.startswith("경로명:"):
            source_path = normalize_line(line.split(":", 1)[1])
            continue
        if line.startswith("파일명:"):
            file_name = normalize_line(line.split(":", 1)[1])
            continue

        normalized = line.replace("  ", " ")
        if "표지 내용" in normalized or "표지내용" in normalized:
            current_mode = "cover"
            continue
        if normalized.startswith("목차"):
            current_mode = "toc"
            toc_lines.append(line)
            continue

        if current_mode == "cover":
            if not line.startswith("-") and "page" in line.lower() and ":" not in line and not re.match(r"^\d+\.", line):
                current_mode = "body"
            else:
                cover_lines.append(line)
                continue

        if current_mode == "toc":
            if line.startswith("사업") or line.startswith("현황") or line.startswith("주요") or line.startswith("제안") or line.startswith("안내") or line.startswith("["):
                current_mode = "body"
            else:
                toc_lines.append(line)
                continue

        raw_name = canonical_section_name(line)
        if not raw_name:
            continue
        page_range = parse_page_range(line)
        is_subsection = line.lstrip().startswith("-")
        line_without_page = strip_page_suffix(line)
        if not is_subsection and " - " in line_without_page:
            prefix, detail = [canonical_section_name(part) for part in line_without_page.split(" - ", 1)]
            if current_top is not None and prefix == str(current_top.get("section_name") or "") and detail:
                current_top["subsections"].append({
                    "section_name": detail,
                    "parent_section": current_top["section_name"],
                    "slide_range": page_range,
                    "slide_numbers": list(range(page_range[0], page_range[-1] + 1)) if page_range else [],
                    "slide_label": f"페이지 {page_range[0]}~{page_range[-1]}" if len(page_range) == 2 and page_range[0] != page_range[-1] else (f"페이지 {page_range[0]}" if page_range else "페이지 미상"),
                    "subsections": [],
                    "content_items": [detail],
                    "keywords": [detail],
                })
                continue
        if not is_subsection:
            if current_top is not None and raw_name == str(current_top.get("section_name") or ""):
                continue
            current_top = {
                "section_name": raw_name,
                "page_range": page_range,
                "slide_range": page_range,
                "slide_numbers": list(range(page_range[0], page_range[-1] + 1)) if page_range else [],
                "slide_label": f"페이지 {page_range[0]}~{page_range[-1]}" if len(page_range) == 2 and page_range[0] != page_range[-1] else (f"페이지 {page_range[0]}" if page_range else "페이지 미상"),
                "keywords": [],
                "subsections": [],
            }
            section_rows.append(current_top)
        elif current_top is not None:
            current_top["subsections"].append({
                "section_name": raw_name,
                "parent_section": current_top["section_name"],
                "slide_range": page_range,
                "slide_numbers": list(range(page_range[0], page_range[-1] + 1)) if page_range else [],
                "slide_label": f"페이지 {page_range[0]}~{page_range[-1]}" if len(page_range) == 2 and page_range[0] != page_range[-1] else (f"페이지 {page_range[0]}" if page_range else "페이지 미상"),
                "subsections": [],
                "content_items": [raw_name],
                "keywords": [raw_name],
            })

    relative_path = normalize_relpath(source_path, file_name, source_root)
    cover_fields = parse_cover_fields(cover_lines)
    toc_titles = [
        canonical_section_name(line)
        for line in toc_lines
        if canonical_section_name(line) and canonical_section_name(line) not in {"목차", "목차 내용"}
    ]
    cover_page = {
        "title": cover_fields.get("제목") or cover_fields.get("사업명") or "",
        "organization": cover_fields.get("주관기관") or cover_fields.get("기관명") or "",
        "project_name": cover_fields.get("사업명") or "",
        "date": cover_fields.get("년월") or "",
        "document_type": "제안요청서" if file_name.upper().startswith("RFP_") else "",
        "confidence": 0.9 if cover_fields else 0.4,
    }

    total_slides = 0
    for sec in section_rows:
        for slide_range in [sec.get("slide_range")] + [sub.get("slide_range") for sub in sec.get("subsections") or []]:
            values = list(slide_range or [])
            if values:
                total_slides = max(total_slides, int(values[-1]))

    json_payload = {
        "file_name": file_name,
        "source_path": source_path,
        "relative_path": relative_path,
        "section_group": Path(relative_path).parts[1] if len(Path(relative_path).parts) >= 2 else "01. RFP",
        "document_type": Path(file_name).suffix.lower().lstrip("."),
        "total_slides": total_slides,
        "structure_mode": "manual_rfp_sample",
        "sections": [],
        "cover_page": cover_page,
        "toc": {
            "sections": [{"level": 1, "title": title, "page": None} for title in toc_titles[:20]],
            "section_titles": toc_titles[:20],
            "keywords": toc_titles[:20],
            "confidence": 0.9 if toc_titles else 0.0,
        },
        "detected_sections": [],
        "document_summary": "",
        "page_types": [],
        "manual_sample": {
            "original_lines": [line for line in original_lines if normalize_line(line)],
            "cover_lines": cover_lines,
            "toc_lines": toc_lines,
        },
    }

    detected_sections: list[str] = []
    for sec_index, sec in enumerate(section_rows, start=1):
        sec_name = str(sec.get("section_name") or f"섹션 {sec_index}")
        detected_sections.append(sec_name)
        keywords = [sec_name] + [str(sub.get("section_name") or "") for sub in sec.get("subsections") or []]
        json_payload["sections"].append({
            "section_id": str(sec_index),
            "section_name": sec_name,
            "slide_range": sec.get("slide_range") or [],
            "slide_numbers": sec.get("slide_numbers") or [],
            "slide_label": sec.get("slide_label") or "페이지 미상",
            "keywords": [word for word in keywords if word][:15],
            "subsections": [
                {
                    "section_id": f"{sec_index}.{sub_index}",
                    "section_name": str(sub.get("section_name") or ""),
                    "parent_section": sec_name,
                    "slide_range": sub.get("slide_range") or [],
                    "slide_numbers": sub.get("slide_numbers") or [],
                    "slide_label": sub.get("slide_label") or "페이지 미상",
                    "subsections": [],
                    "content_items": sub.get("content_items") or [str(sub.get("section_name") or "")],
                    "keywords": sub.get("keywords") or [str(sub.get("section_name") or "")],
                }
                for sub_index, sub in enumerate(sec.get("subsections") or [], start=1)
            ],
        })
    json_payload["detected_sections"] = detected_sections[:30]

    rendered_text = render_structured_txt_from_payload(json_payload)
    json_payload["pattern_metadata"] = rfp_pattern_analyzer.extract_metadata_enhanced(
        filename=file_name,
        text_content=rendered_text,
        relative_path=relative_path,
    )
    json_payload["metadata_auto"] = metadata_auto_generator_enhanced.extract_metadata(
        file_name=file_name,
        file_content=rendered_text,
        relative_path=relative_path,
        use_rfp_patterns=True,
    )
    json_payload["document_summary"] = (
        json_payload["metadata_auto"].get("summary")
        or json_payload["pattern_metadata"].get("summary")
        or cover_page.get("title")
        or file_name
    )
    json_payload["page_types"] = (
        ["cover"] if cover_lines else []
        + (["toc"] if toc_titles else [])
        + ["content"] * max(len(section_rows), 0)
    )
    return json_payload


def render_structured_txt_from_payload(payload: dict[str, Any]) -> str:
    manual_sample = payload.get("manual_sample") or {}
    original_lines = [
        str(line).rstrip()
        for line in (manual_sample.get("original_lines") or [])
        if str(line).strip()
    ]
    if original_lines:
        return "\n".join(original_lines).strip() + "\n"

    lines: list[str] = []
    lines.append(f"경로명: {payload.get('source_path') or ''}")
    lines.append(f"파일명: {payload.get('file_name') or ''}")

    cover_page = payload.get("cover_page") or {}
    cover_lines = manual_sample.get("cover_lines") or []
    if cover_lines:
        lines.append("표지 내용")
        lines.extend(str(line) for line in cover_lines if str(line).strip())

    toc = payload.get("toc") or {}
    toc_titles = toc.get("section_titles") or []
    if toc_titles:
        lines.append("목차")
        for title in toc_titles:
            lines.append(f"- {title}")

    for section in payload.get("sections") or []:
        slide_label = section.get("slide_label") or ""
        title = section.get("section_name") or ""
        lines.append(f"{title} - {slide_label}".strip(" -"))
        for subsection in section.get("subsections") or []:
            sub_title = subsection.get("section_name") or ""
            sub_label = subsection.get("slide_label") or ""
            lines.append(f" - {sub_title} - {sub_label}".strip())

    return "\n".join(lines).strip() + "\n"


def write_outputs(
    payload: dict[str, Any],
    *,
    output_txt_root: Path,
    output_json_root: Path,
) -> dict[str, Any]:
    relative_path = Path(str(payload.get("relative_path") or payload.get("file_name") or "unknown"))
    txt_path = output_txt_root / relative_path.with_suffix(".txt")
    json_path = output_json_root / relative_path.with_suffix(".json")
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    txt_payload = render_structured_txt_from_payload(payload)
    txt_path.write_text(txt_payload, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "file_name": payload.get("file_name"),
        "relative_path": str(relative_path.as_posix()),
        "txt_output": str(txt_path),
        "json_output": str(json_path),
        "section_count": len(payload.get("sections") or []),
        "detected_sections": payload.get("detected_sections") or [],
        "cover_title": (payload.get("cover_page") or {}).get("title"),
        "organization": (payload.get("cover_page") or {}).get("organization"),
    }


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root).expanduser().resolve()
    output_txt_root = Path(args.output_txt_root).expanduser().resolve()
    output_json_root = Path(args.output_json_root).expanduser().resolve()
    manifest_path = Path(args.manifest_path).expanduser().resolve()

    rows: list[dict[str, Any]] = []
    sample_paths = [Path(path).expanduser().resolve() for path in args.sample_md]
    for sample_path in sample_paths:
        if not sample_path.exists():
            raise FileNotFoundError(f"샘플 markdown 파일이 없습니다: {sample_path}")
        raw_text = sample_path.read_text(encoding="utf-8")
        for entry in split_entries(raw_text):
            payload = parse_manual_entry(entry, source_root)
            row = write_outputs(
                payload,
                output_txt_root=output_txt_root,
                output_json_root=output_json_root,
            )
            row["sample_md"] = str(sample_path)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))

    summary = {
        "sample_md_files": [str(path) for path in sample_paths],
        "source_root": str(source_root),
        "output_txt_root": str(output_txt_root),
        "output_json_root": str(output_json_root),
        "processed_count": len(rows),
        "rows": rows,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest_path": str(manifest_path), "processed_count": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
