# -*- coding: utf-8 -*-
"""
Metadata confidence scoring — organization + project_name extraction.

Provides:
  enrich_confidence(folder_name, project_name) → dict with:
    organization, organization_confidence, project_confidence
"""
from __future__ import annotations

import re

# ── Known organization aliases → canonical Korean names ──────────────────────

_ORG_ALIASES: dict[str, str] = {
    "k-water":  "한국수자원공사",
    "kwater":   "한국수자원공사",
    "수자원공사": "한국수자원공사",
    "농정원":   "농림수산식품교육문화정보원",
    "lh":       "한국토지주택공사",
    "sh":       "서울주택도시공사",
    "koica":    "한국국제협력단",
    "kisa":     "한국인터넷진흥원",
    "nipa":     "정보통신산업진흥원",
    "nia":      "한국지능정보사회진흥원",
}

# ── Korean organization type suffixes (most specific first) ──────────────────

_ORG_SUFFIXES = (
    "연구원", "위원회", "관리원", "진흥원", "개발원",
    "공사", "공단", "재단", "협회",
    "센터", "청", "처", "원", "부",
)

# ── Project-type keywords that are NOT organization names ────────────────────

_PROJECT_KW = re.compile(
    r"ISP|ISMP|ODA|구축|시스템|서비스|플랫폼|개발|계획|전략|용역|수립"
    r"|정보화|빅데이터|디지털|AI|AX|ICT|기반|차세대|통합|고도화",
    re.IGNORECASE,
)

_DATE_PREFIX = re.compile(r"^\d+\.\s*")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _score_project(folder_name: str, project_name: str) -> float:
    """Return 0.0–1.0 confidence that project_name was cleanly extracted."""
    if not project_name:
        return 0.0
    score = 0.0
    if _DATE_PREFIX.match(folder_name):
        score += 0.35
    if len(project_name) >= 10:
        score += 0.30
    elif len(project_name) >= 5:
        score += 0.20
    if _PROJECT_KW.search(project_name):
        score += 0.20
    if re.match(r"^[가-힣a-zA-Z]", project_name):
        score += 0.15
    return round(min(score, 1.0), 3)


def _extract_org(project_name: str) -> tuple[str, float]:
    """
    Return (org_name, confidence) extracted from a cleaned project_name.
    confidence=0.0 when extraction is not possible.
    """
    if not project_name:
        return "", 0.0

    # 1. Alias table match (case-insensitive prefix)
    lower = project_name.lower()
    for alias, canonical in _ORG_ALIASES.items():
        if lower.startswith(alias.lower()):
            return canonical, 0.85

    # 2. Korean org-suffix scan across tokens
    tokens = project_name.split()
    for i, token in enumerate(tokens):
        for suffix in _ORG_SUFFIXES:
            if token.endswith(suffix) and len(token) > len(suffix):
                # Merge with preceding token if it is not a project keyword
                parts = [token]
                if i > 0 and not _PROJECT_KW.search(tokens[i - 1]):
                    parts.insert(0, tokens[i - 1])
                org = " ".join(parts).strip(".,:")
                return org, 0.90

    # 3. First-word heuristic — only when multiple tokens exist
    first = tokens[0] if tokens else ""
    if first and not _PROJECT_KW.search(first) and len(first) >= 2 and len(tokens) > 1:
        return first, 0.55

    return "", 0.0


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_confidence(folder_name: str, project_name: str) -> dict:
    """
    Return confidence metadata dict to merge into the document metadata JSON.

    Keys:
      organization             — extracted org name, empty string if unknown
      organization_confidence  — 0.0 (not found) to 0.95 (high confidence)
      project_confidence       — 0.0 to 1.0 based on parse quality
    """
    org_name, org_conf = _extract_org(project_name)
    proj_conf = _score_project(folder_name, project_name)
    return {
        "organization":            org_name,
        "organization_confidence": org_conf,
        "project_confidence":      proj_conf,
    }
