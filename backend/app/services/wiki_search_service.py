from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
WIKI_ROOT = DATA_DIR / "wiki"
DEFAULT_PROJECT_WIKI_DIR = WIKI_ROOT / "projects"
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


@dataclass
class WikiSearchResult:
    id: str
    title: str
    category: str = "project"
    organization: Optional[str] = None
    project_type: Optional[str] = None
    technologies: list[str] = field(default_factory=list)
    score: float = 0.0
    text_preview: str = ""
    content: str = ""


@dataclass
class WikiSearchResponse:
    success: bool
    query: str
    results: list[WikiSearchResult] = field(default_factory=list)
    error: Optional[str] = None


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text or "")}


def _score_text(query: str, title: str, content: str) -> float:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0

    title_tokens = _tokenize(title)
    content_tokens = _tokenize(content[:4000])
    overlap_title = len(query_tokens & title_tokens)
    overlap_content = len(query_tokens & content_tokens)

    score = 0.0
    if overlap_title:
        score += overlap_title * 2.0
    if overlap_content:
        score += overlap_content * 1.0

    normalized_query = re.sub(r"\s+", "", (query or "").lower())
    normalized_title = re.sub(r"\s+", "", (title or "").lower())
    if normalized_query and normalized_query in normalized_title:
        score += 3.0

    return score


def _extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def _extract_organization(markdown: str) -> Optional[str]:
    for line in markdown.splitlines():
        if "발주기관" not in line and "기관" not in line:
            continue
        cleaned = re.sub(r"^[#>\-\*\s]+", "", line).strip()
        parts = re.split(r"[:：|]", cleaned, maxsplit=1)
        if len(parts) == 2:
            value = parts[1].strip(" `")
            if value:
                return value
    return None


class WikiSearchService:
    def __init__(self, source_id: Optional[str] = None):
        self.source_id = (source_id or "").strip() or None

    def _project_dirs(self) -> list[Path]:
        dirs: list[Path] = []
        if self.source_id:
            dirs.append(WIKI_ROOT / self.source_id / "projects")
        dirs.append(DEFAULT_PROJECT_WIKI_DIR)
        return dirs

    def _iter_project_files(self):
        seen: set[Path] = set()
        for wiki_dir in self._project_dirs():
            if not wiki_dir.exists():
                continue
            for path in sorted(wiki_dir.glob("*.md")):
                if path in seen:
                    continue
                seen.add(path)
                yield path

    def search(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
        organization: Optional[str] = None,
    ) -> WikiSearchResponse:
        try:
            results: list[WikiSearchResult] = []
            org_filter = (organization or "").strip().lower()

            for path in self._iter_project_files():
                raw = path.read_text(encoding="utf-8")
                title = _extract_title(raw, path.stem)
                org_name = _extract_organization(raw)

                if category and category not in ("project", "wiki"):
                    continue
                if org_filter and org_filter not in (org_name or "").lower() and org_filter not in raw.lower():
                    continue

                score = _score_text(query, title, raw)
                if score <= 0:
                    continue

                preview = raw[:280].replace("\n", " ")
                results.append(WikiSearchResult(
                    id=path.stem,
                    title=title,
                    category="project",
                    organization=org_name,
                    score=score,
                    text_preview=preview,
                    content=raw,
                ))

            results.sort(key=lambda item: item.score, reverse=True)
            return WikiSearchResponse(
                success=True,
                query=query,
                results=results[:max(top_k, 0)],
            )
        except Exception as exc:
            return WikiSearchResponse(success=False, query=query, error=str(exc))


_services: dict[str, WikiSearchService] = {}


def get_wiki_search_service(source_id: Optional[str] = None) -> WikiSearchService:
    key = source_id or "_default_"
    if key not in _services:
        _services[key] = WikiSearchService(source_id=source_id)
    return _services[key]
