import csv
import re
from html import unescape
from io import StringIO
from pathlib import Path
from typing import Any, Optional, Tuple


SOURCE_TO_COPY_ROOTS = (
    ("/mnt/w2_project/", "/data/weeslee/weeslee-mnt/"),
)

COPIED_TREE_ROOTS = (
    "/data/weeslee/weeslee-mnt/",
    "C:/xampp/htdocs/weeslee-mnt/",
)

TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "cp949", "euc-kr")
ARTIFACT_EXTENSIONS = (".txt", ".html", ".csv")
RELATIVE_PREFIXES = (
    "00. RAG 소스/",
    "01. RFP/",
    "02. 제안서/",
    "03. 산출물/",
)


def _normalize_path(file_path: str) -> str:
    return str(file_path or "").replace("\\", "/").strip()


def _candidate_base_paths(file_path: str) -> list[Path]:
    normalized = _normalize_path(file_path)
    if not normalized:
        return []

    candidates: list[Path] = []

    for source_root, copy_root in SOURCE_TO_COPY_ROOTS:
        if normalized.startswith(source_root):
            relative_path = normalized[len(source_root):]
            candidates.append(Path(copy_root + relative_path))
            break

    if any(normalized.startswith(root) for root in COPIED_TREE_ROOTS):
        candidates.append(Path(normalized))

    if any(normalized.startswith(prefix) for prefix in RELATIVE_PREFIXES):
        for root in COPIED_TREE_ROOTS:
            candidates.append(Path(root) / normalized)

    if not candidates and "/" not in normalized and "\\" not in normalized:
        candidates.append(Path(normalized))

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        unique_candidates.append(candidate)
    return unique_candidates


def _candidate_txt_paths(file_path: str) -> list[Path]:
    return _candidate_artifact_paths(file_path, ".txt")


def _candidate_artifact_paths(file_path: str, extension: str) -> list[Path]:
    normalized = str(file_path).replace("\\", "/")
    candidates: list[Path] = []

    for base_path in _candidate_base_paths(normalized):
        candidates.append(base_path.with_suffix(extension))

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        unique_candidates.append(candidate)
    return unique_candidates


def _read_text(candidate: Path) -> str:
    for encoding in TEXT_ENCODINGS:
        try:
            return candidate.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError:
            break
    return ""


def _normalize_compare_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip().lower()


def _html_to_text(raw_text: str) -> str:
    text = str(raw_text or "")
    if not text.strip():
        return ""

    text = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", text)
    text = re.sub(r"(?i)</(td|th)>\s*<(td|th)\b[^>]*>", " | ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(tr|p|div|li|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?i)<t[dh]\b[^>]*>", "", text)
    text = re.sub(r"(?i)<tr\b[^>]*>", "", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _csv_to_text(raw_text: str) -> str:
    text = str(raw_text or "")
    if not text.strip():
        return ""

    rows: list[str] = []
    try:
        reader = csv.reader(StringIO(text))
        for row in reader:
            cells = [str(cell or "").strip() for cell in row if str(cell or "").strip()]
            if not cells:
                continue
            rows.append(" | ".join(cells))
    except Exception:
        rows = [line.strip() for line in text.splitlines() if line.strip()]

    return "\n".join(rows).strip()


def _transform_artifact_text(extension: str, raw_text: str) -> str:
    if extension == ".html":
        return _html_to_text(raw_text)
    if extension == ".csv":
        return _csv_to_text(raw_text)
    return str(raw_text or "").strip()


def load_preconverted_artifacts(file_path: str) -> Optional[dict[str, Any]]:
    parts: list[str] = []
    compare_texts: list[str] = []
    used_paths: list[str] = []
    artifact_types: list[str] = []

    for extension in ARTIFACT_EXTENSIONS:
        for candidate in _candidate_artifact_paths(file_path, extension):
            if not candidate.is_file():
                continue

            raw_text = _read_text(candidate)
            transformed = _transform_artifact_text(extension, raw_text)
            normalized = _normalize_compare_text(transformed)
            if len(normalized) < 20:
                continue

            if any(
                normalized in existing or existing in normalized
                for existing in compare_texts
                if len(existing) >= 50
            ):
                used_paths.append(str(candidate))
                artifact_types.append(extension.lstrip("."))
                continue

            parts.append(transformed.strip())
            compare_texts.append(normalized)
            used_paths.append(str(candidate))
            artifact_types.append(extension.lstrip("."))
            break

    if not parts:
        return None

    return {
        "text": "\n\n".join(part for part in parts if part).strip(),
        "paths": used_paths,
        "types": artifact_types,
    }


def load_preconverted_txt(file_path: str) -> Optional[Tuple[str, str]]:
    for candidate in _candidate_txt_paths(file_path):
        if not candidate.is_file():
            continue

        text = _read_text(candidate)
        if text.strip():
            return text.strip(), str(candidate)

    return None
