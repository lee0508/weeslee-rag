# Structured 콘텐츠 리졸버 - structured_txt/json 파일 로드 및 메타데이터 추출
# 작업일: 2026-07-08 - DB 시스템 설정 연동 추가
from __future__ import annotations

import json
import platform
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.extractors.preconverted_txt_fallback import load_preconverted_artifacts


def _get_db_setting(category: str, key: str, default):
    """DB 설정 조회 헬퍼. 실패 시 default 반환."""
    try:
        from app.services.system_settings_service import get_system_setting
        return get_system_setting(category, key, default)
    except Exception:
        return default


def _get_structured_txt_root() -> str:
    """DB에서 structured_txt_root 경로 조회. 플랫폼별 자동 선택."""
    if platform.system() == "Windows":
        fallback = r"C:\xampp\htdocs\weeslee-mnt\structured_txt"
    else:
        fallback = "/data/weeslee/weeslee-mnt/structured_txt"
    return _get_db_setting("path", "structured_txt_root", fallback)


def _get_structured_json_root() -> str:
    """DB에서 structured_json_root 경로 조회. 플랫폼별 자동 선택."""
    if platform.system() == "Windows":
        fallback = r"C:\xampp\htdocs\weeslee-mnt\structured_json"
    else:
        fallback = "/data/weeslee/weeslee-mnt/structured_json"
    return _get_db_setting("path", "structured_json_root", fallback)


class StructuredContentResolver:
    """Resolve structured text/json artifacts for metadata and keyword generation."""

    SOURCE_ROOT_NAME = "00. RAG 소스"
    TEXT_EXTENSIONS = (".txt", ".md")
    JSON_EXTENSIONS = (".json", ".txt")
    PRECONVERTED_SOURCE_EXTENSIONS = {".hwp", ".hwpx"}
    @staticmethod
    def _get_default_roots() -> Dict[str, List[str]]:
        """DB 설정에서 기본 루트 경로 조회."""
        return {
            "structured_txt_root": [_get_structured_txt_root()],
            "structured_json_root": [_get_structured_json_root()],
        }

    @property
    def DEFAULT_ROOTS(self) -> Dict[str, List[str]]:
        """하위 호환성 유지용 프로퍼티."""
        return self._get_default_roots()
    GENERIC_TITLES = {"제안요청서", "추진계획", "사업계획", "제안서"}
    CONTROL_MARKER_PREFIXES = (
        "경로명:", "파일명:", "상대경로:", "섹션분류:", "총슬라이드수:",
        "표지내용", "표지 내용", "목차", "목차 내용",
    )
    COVER_LABEL_MAP = {
        "경로명": "path",
        "파일명": "file_name",
        "제목": "title",
        "사업명": "project_name",
        "주관기관": "organization",
        "기관명": "organization",
        "발주기관": "organization",
        "년월": "year_month",
        "년도": "year_month",
        "연월": "year_month",
        "날짜": "year_month",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = dict(config or {})
        self.max_text_chars = int(self.config.get("max_text_chars") or 12000)

    def resolve_document_content(self, document: Any) -> Dict[str, Any]:
        relative_path = self._normalize_relpath(getattr(document, "relative_path", "") or "")
        file_name = str(getattr(document, "file_name", "") or "").strip()
        file_path = str(getattr(document, "file_path", "") or "").strip()

        preconverted_result = self._load_preconverted_artifact_content(
            file_path=file_path,
            relative_path=relative_path,
            file_name=file_name,
        )

        if preconverted_result:
            text_result = preconverted_result
        else:
            text_result = self._load_text_artifact(
                root_value=self.config.get("structured_txt_root"),
                enabled=bool(self.config.get("use_structured_txt", True)),
                relative_path=relative_path,
                file_name=file_name,
                extensions=self.TEXT_EXTENSIONS,
            )
        json_result = self._load_text_artifact(
            root_value=self.config.get("structured_json_root"),
            enabled=bool(self.config.get("use_structured_json", True)),
            relative_path=relative_path,
            file_name=file_name,
            extensions=self.JSON_EXTENSIONS,
        )

        json_payload = self._try_parse_json(json_result.get("content") or "")
        json_text = self._json_to_text(json_payload) if json_payload is not None else ""
        context_text = self._structured_text_to_context(text_result.get("content") or "")

        combined_parts = []
        if bool(self.config.get("prefer_structured_content", True)):
            combined_parts.extend([json_text, context_text])
        else:
            combined_parts.extend([context_text, json_text])

        combined_text = "\n".join(part.strip() for part in combined_parts if str(part or "").strip()).strip()
        if self.max_text_chars > 0:
            combined_text = combined_text[:self.max_text_chars]

        return {
            "text_content": (text_result.get("content") or "")[: self.max_text_chars],
            "context_text": context_text[: self.max_text_chars],
            "json_content": json_result.get("content") or "",
            "json_payload": json_payload,
            "json_text": json_text[: self.max_text_chars],
            "combined_text": combined_text,
            "text_path": text_result.get("path"),
            "text_paths": text_result.get("paths") or ([text_result.get("path")] if text_result.get("path") else []),
            "json_path": json_result.get("path"),
            "used_paths": [
                *[path for path in (text_result.get("paths") or []) if path],
                *([text_result.get("path")] if text_result.get("path") and not text_result.get("paths") else []),
                *([json_result.get("path")] if json_result.get("path") else []),
            ],
        }

    def get_resolution_summary(self) -> Dict[str, Any]:
        return {
            "structured_txt_roots": [
                str(path) for path in self._resolve_candidate_roots(
                    str(self.config.get("structured_txt_root") or "").strip(),
                    self.TEXT_EXTENSIONS,
                )
            ],
            "structured_json_roots": [
                str(path) for path in self._resolve_candidate_roots(
                    str(self.config.get("structured_json_root") or "").strip(),
                    self.JSON_EXTENSIONS,
                )
            ],
            "prefer_structured_content": bool(self.config.get("prefer_structured_content", True)),
            "max_text_chars": self.max_text_chars,
        }

    def extract_structured_hints(self, document: Any) -> Dict[str, Any]:
        resolved = self.resolve_document_content(document)
        json_payload = resolved.get("json_payload") if isinstance(resolved.get("json_payload"), dict) else {}
        source_text = (
            resolved.get("text_content")
            or resolved.get("json_text")
            or resolved.get("combined_text")
            or ""
        )
        lines = [str(line or "").strip() for line in str(source_text).splitlines()]
        lines = [line for line in lines if line]

        cover_fields = self._extract_cover_fields(lines)
        section_titles = self._pick_section_titles(json_payload, lines)
        path_text = cover_fields.get("path") or getattr(document, "relative_path", "") or ""
        file_name = cover_fields.get("file_name") or getattr(document, "file_name", "") or ""
        title = cover_fields.get("title") or ""
        title = "" if self._is_generic_title(title) and cover_fields.get("project_name") else title
        project_name = self._pick_first_non_empty(
            cover_fields.get("project_name"),
            self._json_hint(json_payload, "metadata_auto.project_name"),
            self._json_hint(json_payload, "pattern_metadata.project_name"),
            self._derive_project_name_from_title(title),
            self._derive_project_name_from_file_name(file_name),
        )
        organization = self._clean_organization_name(
            self._pick_first_non_empty(
                cover_fields.get("organization"),
                self._json_hint(json_payload, "metadata_auto.organization"),
                self._json_hint(json_payload, "pattern_metadata.organization"),
                self._extract_org_from_lines(lines),
            )
        )
        year = self._extract_year_value(
            self._pick_first_non_empty(
                cover_fields.get("year_month"),
                self._json_hint(json_payload, "metadata_auto.project_year"),
                self._json_hint(json_payload, "metadata_auto.year"),
                self._json_hint(json_payload, "pattern_metadata.project_year"),
                self._json_hint(json_payload, "pattern_metadata.year"),
                self._extract_year_from_lines(lines),
                title,
                file_name,
                path_text,
                "\n".join(lines[:20]),
            )
        )
        document_type = self._pick_first_non_empty(
            self._json_hint(json_payload, "metadata_auto.document_type"),
            self._json_hint(json_payload, "pattern_metadata.document_type"),
            self._classify_document_type(title=title, file_name=file_name, path_text=path_text, lines=lines),
        )
        keywords = self._extract_structured_keywords(
            title=title,
            project_name=project_name,
            file_name=file_name,
            section_titles=section_titles,
            lines=lines,
            json_payload=json_payload,
        )

        return {
            "path": path_text,
            "file_name": file_name,
            "title": title,
            "project_name": project_name,
            "organization": organization,
            "year": year,
            "document_type": document_type,
            "section_titles": section_titles[:20],
            "keywords": keywords[:30],
            "used_paths": resolved.get("used_paths") or [],
            "combined_text_length": len(resolved.get("combined_text") or ""),
        }

    def _load_text_artifact(
        self,
        *,
        root_value: Any,
        enabled: bool,
        relative_path: str,
        file_name: str,
        extensions: tuple[str, ...],
    ) -> Dict[str, Any]:
        if not enabled:
            return {"path": None, "content": ""}

        root_text = str(root_value or "").strip()
        root_paths = self._resolve_candidate_roots(root_text, extensions)
        if not root_paths:
            return {"path": None, "content": ""}

        for root_path in root_paths:
            for candidate in self._build_candidates(root_path, relative_path, file_name, extensions):
                if not candidate.exists() or not candidate.is_file():
                    continue
                try:
                    content = candidate.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    try:
                        content = candidate.read_text(encoding="cp949")
                    except Exception:
                        continue
                except Exception:
                    continue

                return {
                    "path": str(candidate),
                    "content": str(content or "").strip(),
                }

        return {"path": None, "content": ""}

    def _load_preconverted_artifact_content(
        self,
        *,
        file_path: str,
        relative_path: str,
        file_name: str,
    ) -> Optional[Dict[str, Any]]:
        source_extension = Path(file_path or file_name or "").suffix.lower()
        if source_extension not in self.PRECONVERTED_SOURCE_EXTENSIONS:
            return None

        candidates = [
            value for value in (
                file_path,
                relative_path,
                file_name,
            )
            if str(value or "").strip()
        ]

        for candidate in candidates:
            artifact_result = load_preconverted_artifacts(candidate)
            if not artifact_result:
                continue
            return {
                "path": artifact_result["paths"][0] if artifact_result.get("paths") else None,
                "paths": artifact_result.get("paths") or [],
                "content": str(artifact_result.get("text") or "").strip(),
            }

        return None

    def _build_candidates(
        self,
        root_path: Path,
        relative_path: str,
        file_name: str,
        extensions: tuple[str, ...],
    ) -> List[Path]:
        candidates: List[Path] = []
        seen: set[str] = set()

        relative_variants = self._build_relative_variants(relative_path, file_name)

        base_candidates: List[Path] = []
        for rel_value in relative_variants:
            rel = Path(rel_value)
            rel_stem = rel.stem if rel_value else ""
            base_candidates.append(root_path / rel)
            base_candidates.append(root_path / rel.with_suffix(""))
            if rel_stem:
                base_candidates.append(root_path / rel_stem)

        for base in base_candidates:
            path_key = str(base)
            if path_key not in seen:
                seen.add(path_key)
                candidates.append(base)
            for ext in extensions:
                with_ext = base.with_suffix(ext)
                path_key = str(with_ext)
                if path_key not in seen:
                    seen.add(path_key)
                    candidates.append(with_ext)

        return candidates

    def _normalize_relpath(self, value: str) -> str:
        return str(value or "").replace("\\", "/").strip().lstrip("/")

    def _resolve_candidate_roots(self, root_text: str, extensions: tuple[str, ...]) -> List[Path]:
        root_key = "structured_json_root" if extensions == self.JSON_EXTENSIONS else "structured_txt_root"
        configured_roots = [root_text] if root_text else []
        fallback_roots = self.DEFAULT_ROOTS.get(root_key, [])
        candidates: List[Path] = []
        seen: set[str] = set()

        for raw_root in [*configured_roots, *fallback_roots]:
            raw_value = str(raw_root or "").strip()
            if not raw_value:
                continue
            for candidate in self._expand_root_variants(raw_value):
                key = str(candidate)
                if key in seen or not candidate.exists() or not candidate.is_dir():
                    continue
                seen.add(key)
                candidates.append(candidate)

        return candidates

    def _expand_root_variants(self, raw_root: str) -> List[Path]:
        base = Path(raw_root)
        variants = [base]

        normalized_parts = [part for part in base.parts if str(part).strip()]
        if self.SOURCE_ROOT_NAME not in normalized_parts:
            variants.append(base / self.SOURCE_ROOT_NAME)
        else:
            stripped_parts = [part for part in normalized_parts if part != self.SOURCE_ROOT_NAME]
            if stripped_parts:
                variants.append(Path(*stripped_parts))

        return variants

    def _build_relative_variants(self, relative_path: str, file_name: str) -> List[str]:
        values: List[str] = []
        seen: set[str] = set()

        for raw_value in (relative_path, file_name):
            normalized = self._normalize_relpath(raw_value)
            if not normalized:
                continue
            for candidate in self._expand_relative_variants(normalized):
                if candidate in seen:
                    continue
                seen.add(candidate)
                values.append(candidate)

        return values

    def _expand_relative_variants(self, relative_value: str) -> List[str]:
        """
        [2026-07-08] 경로 변형 생성 개선
        - "00. RAG 소스/01. RFP/..." → ["00. RAG 소스/01. RFP/...", "01. RFP/..."]
        - "01. RFP/..." → ["01. RFP/...", "00. RAG 소스/01. RFP/..."]
        - structured 파일 경로와 document metadata의 relative_path 매칭 향상
        """
        variants = [relative_value]
        seen = {relative_value}

        # "00. RAG 소스/" prefix 처리
        if relative_value.startswith(f"{self.SOURCE_ROOT_NAME}/"):
            trimmed = relative_value[len(self.SOURCE_ROOT_NAME) + 1 :]
            if trimmed and trimmed not in seen:
                variants.append(trimmed)
                seen.add(trimmed)
        else:
            with_prefix = f"{self.SOURCE_ROOT_NAME}/{relative_value}"
            if with_prefix not in seen:
                variants.append(with_prefix)
                seen.add(with_prefix)

        # [2026-07-08] 추가: "01. RFP/", "02. 제안서/", "03. 산출물/" 직접 시작 케이스
        # structured 파일이 00. RAG 소스 없이 저장된 경우를 위한 처리
        category_prefixes = ("01. RFP", "02. 제안서", "03. 산출물")
        for prefix in category_prefixes:
            # "00. RAG 소스/01. RFP/..." → "01. RFP/..." 추가 (이미 위에서 처리)
            # "01. RFP/..." → 그대로 사용

            # relative_value 에서 category prefix 이후 부분만 추출
            if f"/{prefix}/" in relative_value or relative_value.startswith(f"{prefix}/"):
                idx = relative_value.find(f"{prefix}/")
                if idx >= 0:
                    category_path = relative_value[idx:]
                    if category_path not in seen:
                        variants.append(category_path)
                        seen.add(category_path)

        return variants

    def _try_parse_json(self, value: str) -> Optional[Any]:
        text = str(value or "").strip()
        if not text:
            return None
        if not (text.startswith("{") or text.startswith("[")):
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    def _json_to_text(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""

        parts: List[str] = []

        def add(value: Any) -> None:
            text = str(value or "").strip()
            if text:
                parts.append(text)

        cover_page = payload.get("cover_page") or {}
        add(cover_page.get("title"))
        add(cover_page.get("project_name"))
        add(cover_page.get("organization"))
        add(cover_page.get("date"))

        toc = payload.get("toc") or {}
        for title in (toc.get("section_titles") or [])[:30]:
            add(title)

        for section in (payload.get("sections") or [])[:60]:
            if not isinstance(section, dict):
                continue
            add(section.get("section_name"))
            for keyword in (section.get("keywords") or [])[:10]:
                add(keyword)
            for subsection in (section.get("subsections") or [])[:20]:
                if not isinstance(subsection, dict):
                    continue
                add(subsection.get("section_name"))
                for keyword in (subsection.get("keywords") or [])[:8]:
                    add(keyword)

        metadata_auto = payload.get("metadata_auto") or {}
        add(metadata_auto.get("project_name"))
        add(metadata_auto.get("organization"))
        add(metadata_auto.get("summary"))
        for keyword in (metadata_auto.get("keywords") or [])[:20]:
            add(keyword)

        pattern_metadata = payload.get("pattern_metadata") or {}
        for keyword in (pattern_metadata.get("keywords") or [])[:20]:
            add(keyword)

        seen: set[str] = set()
        unique_parts: List[str] = []
        for part in parts:
            if part in seen:
                continue
            seen.add(part)
            unique_parts.append(part)
        return "\n".join(unique_parts)

    def _structured_text_to_context(self, text: str) -> str:
        if not text:
            return ""

        parts: List[str] = []
        seen: set[str] = set()

        for raw_line in str(text).splitlines():
            line = self._normalize_structured_line(raw_line)
            if not line:
                continue

            if any(line.startswith(prefix) for prefix in self.CONTROL_MARKER_PREFIXES):
                continue
            if re.search(r"^[A-Za-z]:\\", line) or line.startswith("/data/"):
                continue
            if re.search(r"^(TEL|FAX|E-MAIL|EMAIL)\s*[:：]", line, flags=re.IGNORECASE):
                continue

            line = re.sub(r"^\d+\s*[.)]?\s*", "", line).strip()
            line = re.sub(r"^\-\s*", "", line).strip()
            line = re.sub(r"\s*-\s*page\s+\d+(\s*-\s*\d+)?\s*$", "", line, flags=re.IGNORECASE).strip()

            labeled = re.match(
                r"^(제목|사업명|주관기관|기관명|발주기관|년도|년월|연월|날짜)\s*[:：]\s*(.+)$",
                line,
            )
            if labeled:
                line = labeled.group(2).strip()

            if not line:
                continue
            if line in {"표지내용", "표지 내용", "목차", "목차 내용"}:
                continue
            if any(token in line for token in ("경로명:", "파일명:", "상대경로:", "섹션분류:", "총슬라이드수:")):
                continue

            if line not in seen:
                seen.add(line)
                parts.append(line)

        return "\n".join(parts)

    def _extract_cover_fields(self, lines: List[str]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for line in lines[:80]:
            normalized = self._normalize_structured_line(line)
            if any(normalized.startswith(prefix) for prefix in ("표지내용", "표지 내용", "목차", "목차 내용")):
                continue
            bracket_matched = re.match(
                r"^<(?P<label>[^<>]+)>\s*<(?P<value>[^<>]+)>$",
                normalized,
            )
            if bracket_matched:
                label = bracket_matched.group("label").strip()
                value = bracket_matched.group("value").strip()
                for raw_label, target_key in self.COVER_LABEL_MAP.items():
                    if raw_label in label and value and not result.get(target_key):
                        result[target_key] = value
                        break

            matched = re.match(r"^(?P<label>[^:]+?)\s*:\s*(?P<value>.+)$", normalized)
            if not matched:
                continue
            label = matched.group("label").strip()
            value = matched.group("value").strip()
            for raw_label, target_key in self.COVER_LABEL_MAP.items():
                if raw_label in label and value and not result.get(target_key):
                    result[target_key] = value
                    break
        return result

    def _extract_section_titles(self, lines: List[str]) -> List[str]:
        results: List[str] = []
        seen: set[str] = set()
        for line in lines:
            cleaned = self._normalize_structured_line(line)
            cleaned = re.sub(r"\s*-\s*page\s+\d+(\s*-\s*\d+)?\s*$", "", cleaned, flags=re.IGNORECASE).strip()
            cleaned = re.sub(r"^-\s*", "", cleaned).strip()
            if not cleaned or ":" in cleaned:
                continue
            if any(token in cleaned.lower() for token in ("경로명", "파일명", "표지 내용", "표지내용", "목차 내용", "년월", "년도")):
                continue
            if cleaned in {"======", "---"}:
                continue
            if cleaned.startswith("##") or cleaned.startswith("###"):
                cleaned = cleaned.lstrip("#").strip()
            if re.search(r"^(page|tel|fax|e-mail|email)\b", cleaned, flags=re.IGNORECASE):
                continue
            if cleaned in {"목차", "목차 내용"}:
                continue
            if len(cleaned) <= 1 or len(cleaned) > 80:
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            results.append(cleaned)
        return results

    def _derive_project_name_from_title(self, title: str) -> str:
        value = str(title or "").strip()
        if not value:
            return ""
        if self._is_generic_title(value):
            return ""
        value = self._normalize_project_name(value)
        value = re.sub(r"\s+(제안요청서|추진계획|용역|사업계획)$", "", value).strip()
        return value

    def _derive_project_name_from_file_name(self, file_name: str) -> str:
        value = Path(str(file_name or "")).stem.strip()
        if not value:
            return ""
        value = self._normalize_project_name(value)
        value = re.sub(r"^(RFP|제안서|전략및방법론|기술및기능|프로젝트관리|프로젝트지원)_", "", value, flags=re.IGNORECASE)
        return value.strip()

    def _extract_org_from_lines(self, lines: List[str]) -> str:
        for line in lines[:40]:
            normalized = self._normalize_structured_line(line)
            matched = re.match(
                r"^(?:주관기관|기관명|발주기관|소속)\s*:\s*(?P<value>.+)$",
                normalized,
            )
            if matched:
                cleaned = self._clean_organization_name(matched.group("value"))
                if cleaned:
                    return cleaned
            bracket_matched = re.match(
                r"^<(?:주관기관|기관명|발주기관|소속)>\s*<(?P<value>[^<>]+)>$",
                normalized,
            )
            if bracket_matched:
                cleaned = self._clean_organization_name(bracket_matched.group("value"))
                if cleaned:
                    return cleaned

        org_patterns = (
            r"(한국[가-힣A-Za-z0-9]+(?:공사|연구원|진흥원|관리원|재단|협회|센터))",
            r"([가-힣A-Za-z0-9\s]+(?:부|청|처|원|공사|공단|관리소|연구원|진흥원|관리원|재단|협회|센터))",
        )
        for line in lines[:40]:
            if "기관" not in line and "주관" not in line and "발주" not in line:
                continue
            for pattern in org_patterns:
                matched = re.search(pattern, line)
                if matched:
                    return matched.group(1).strip()

        for line in lines[:20]:
            normalized = self._normalize_structured_line(line).strip("<> ")
            if not normalized or len(normalized) > 40:
                continue
            if ":" in normalized:
                continue
            if re.search(
                r"(부|청|처|공사|공단|관리소|연구원|진흥원|관리원|재단|협회|센터)$",
                normalized,
            ):
                return normalized
        return ""

    def _extract_year_from_lines(self, lines: List[str]) -> str:
        for line in lines[:20]:
            normalized = self._normalize_structured_line(line)
            if any(label in normalized for label in ("경로명", "파일명")):
                continue
            matched = re.search(r"(20[0-3]\d)\s*[./년]\s*(\d{1,2})?", normalized)
            if matched:
                return matched.group(0)
        return ""

    def _clean_organization_name(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(r"^(주관기관|기관명|발주기관)\s*[:：]?\s*", "", text).strip()
        text = re.sub(r"^[-•·]\s*", "", text).strip()
        text = re.sub(r"\s{2,}", " ", text).strip()
        if text in {"출처", "참고", "그림", "표"}:
            return ""
        return text

    def _normalize_project_name(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(
            r"^(RFP_|제안서_|연구과제_|환경분석_|현황분석_|목표모델_|이행계획_|이행과제_|전략과제_|추진전략_|제안개요_)",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"^(연구과제|환경분석|현황분석|목표모델|이행계획|이행과제|전략과제|추진전략|제안개요)\s*[_\-:]\s*",
            "",
            text,
        )
        return text.strip(" _-")

    def _extract_year_value(self, value: str) -> Optional[int]:
        text = str(value or "").strip()
        if not text:
            return None
        matched = re.search(r"(20[0-3]\d)", text)
        if not matched:
            return None
        try:
            return int(matched.group(1))
        except Exception:
            return None

    def _classify_document_type(self, *, title: str, file_name: str, path_text: str, lines: List[str]) -> str:
        combined = " ".join([title, file_name, path_text, " ".join(lines[:30])]).lower()
        if "rfp" in combined or "제안요청서" in combined:
            return "RFP"
        if "제안서" in combined:
            return "제안서"
        if "추진계획" in combined:
            return "추진계획"
        if "보고서" in combined:
            return "보고서"
        if "isp" in combined or "정보화전략계획" in combined:
            return "ISP"
        return ""

    def _extract_structured_keywords(
        self,
        *,
        title: str,
        project_name: str,
        file_name: str,
        section_titles: List[str],
        lines: List[str],
        json_payload: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        keywords: List[str] = []
        json_keywords = self._json_list_hint(json_payload or {}, "metadata_auto.keywords")
        if not json_keywords:
            json_keywords = self._json_list_hint(json_payload or {}, "pattern_metadata.keywords")
        text_parts = [title, project_name, file_name, *section_titles[:10], *json_keywords[:20]]
        for text in text_parts:
            for token in re.split(r"[\s,()_/·‧:\-\[\]]+", str(text or "")):
                token = token.strip()
                if len(token) < 2:
                    continue
                if token.lower() in {"page", "hwp", "ppt", "pptx", "pdf", "txt", "json"}:
                    continue
                if token in {"경로명", "파일명", "표지내용", "목차", "내용", "년월", "년도"}:
                    continue
                if token not in keywords:
                    keywords.append(token)
        for line in lines[:20]:
            matched = re.search(r"(AI|ISP|ISMP|RAG|LLM|빅데이터|디지털|플랫폼|정보화전략계획|컨설팅)", line, flags=re.IGNORECASE)
            if matched:
                token = matched.group(1).strip()
                if token not in keywords:
                    keywords.append(token)
        return keywords

    def _pick_section_titles(self, payload: Dict[str, Any], lines: List[str]) -> List[str]:
        for dotted_key in (
            "metadata_auto.toc.section_titles",
            "pattern_metadata.toc.section_titles",
            "toc.section_titles",
        ):
            values = self._json_list_hint(payload, dotted_key)
            if values:
                return values[:30]
        return self._extract_section_titles(lines)

    def _pick_first_non_empty(self, *values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _json_hint(self, payload: Dict[str, Any], dotted_key: str) -> str:
        current: Any = payload
        for part in str(dotted_key or "").split("."):
            if not isinstance(current, dict):
                return ""
            current = current.get(part)
        return str(current or "").strip()

    def _json_list_hint(self, payload: Dict[str, Any], dotted_key: str) -> List[str]:
        current: Any = payload
        for part in str(dotted_key or "").split("."):
            if not isinstance(current, dict):
                return []
            current = current.get(part)
        if not isinstance(current, list):
            return []
        values: List[str] = []
        seen: set[str] = set()
        for item in current:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            values.append(text)
        return values

    def _normalize_structured_line(self, line: str) -> str:
        normalized = str(line or "").strip()
        normalized = re.sub(r"^\d+\.\s*", "", normalized).strip()
        normalized = re.sub(r"^\d+\s+", "", normalized).strip()
        normalized = re.sub(r"\s{2,}", " ", normalized).strip()
        return normalized

    def _is_generic_title(self, value: str) -> bool:
        compact = re.sub(r"\s+", "", str(value or "").strip())
        return compact in {re.sub(r"\s+", "", title) for title in self.GENERIC_TITLES}
