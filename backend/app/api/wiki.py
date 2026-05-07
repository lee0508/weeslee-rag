# -*- coding: utf-8 -*-
"""
Project Wiki API.

GET  /api/wiki/projects          — 사용 가능한 위키 목록
GET  /api/wiki/projects/{slug}   — 위키 마크다운 + 메타데이터
POST /api/wiki/build             — build_project_wiki.py 실행 (재생성)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/wiki", tags=["Wiki"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WIKI_DIR = PROJECT_ROOT / "data" / "wiki" / "projects"
_BUILD_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "build_project_wiki.py"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,79}$")


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _read_wiki(path: Path) -> dict:
    """Parse wiki markdown into structured response."""
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Extract generated_at and snapshot from footer line
    generated_at = ""
    snapshot = ""
    for line in reversed(lines):
        if "자동 생성:" in line:
            m = re.search(r"자동 생성: ([^|]+)", line)
            if m:
                generated_at = m.group(1).strip()
            m2 = re.search(r"스냅샷: `([^`]+)`", line)
            if m2:
                snapshot = m2.group(1).strip()
            break

    return {
        "slug": path.stem,
        "title": title,
        "markdown": raw,
        "generated_at": generated_at,
        "snapshot": snapshot,
        "size_bytes": len(raw.encode("utf-8")),
    }


@router.get("/projects")
async def list_wiki_projects():
    """사용 가능한 프로젝트 위키 목록."""
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    pages = []
    for md_file in sorted(WIKI_DIR.glob("*.md")):
        try:
            info = _read_wiki(md_file)
            pages.append({
                "slug": info["slug"],
                "title": info["title"],
                "generated_at": info["generated_at"],
                "snapshot": info["snapshot"],
                "size_bytes": info["size_bytes"],
            })
        except Exception:
            pass
    return {"pages": pages, "count": len(pages)}


@router.get("/match")
async def match_wiki(label: str):
    """그래프 노드 label로 위키 슬러그를 매칭합니다."""
    WIKI_DIR.mkdir(parents=True, exist_ok=True)

    def _tokens(s: str) -> set[str]:
        raw = re.findall(r"[a-zA-Z0-9]+|[가-힣]+", s)
        particles = {"의", "을", "를", "에", "이", "가", "와", "과", "도", "은", "는", "로", "으로", "위한", "위해", "의한"}
        return {t.lower() for t in raw if t.lower() not in particles}

    def _score(label_str: str, title_str: str) -> float:
        def norm(s: str) -> str:
            return re.sub(r"[\s_\-,\.()]+", "", s).lower()

        ln, tn = norm(label_str), norm(title_str)
        if ln == tn or ln in tn or tn in ln:
            return 1.0

        lt, tt = _tokens(label_str), _tokens(title_str)
        if not lt or not tt:
            return 0.0
        return len(lt & tt) / max(len(lt), len(tt))

    best_slug, best_score = None, 0.0
    for md_file in WIKI_DIR.glob("*.md"):
        try:
            info = _read_wiki(md_file)
            score = _score(label, info["title"])
            if score > best_score:
                best_score, best_slug = score, info["slug"]
        except Exception:
            pass

    if best_score >= 0.4:
        return {"slug": best_slug, "score": round(best_score, 3)}
    return {"slug": None}


@router.get("/projects/{slug}")
async def get_wiki_project(slug: str):
    """특정 프로젝트 위키 마크다운과 메타데이터."""
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug format")

    path = WIKI_DIR / f"{slug}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Wiki not found: {slug}")

    return _read_wiki(path)


@router.post("/build")
async def build_wiki(slug: Optional[str] = None):
    """build_project_wiki.py 실행하여 위키 재생성."""
    if not _BUILD_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="build_project_wiki.py not found")

    cmd = [sys.executable, str(_BUILD_SCRIPT)]
    if slug:
        cmd += ["--project", slug]
    else:
        cmd += ["--all"]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Wiki build timed out (300s)")

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or "Build failed")

    # List generated files
    generated = [p.stem for p in WIKI_DIR.glob("*.md")]
    return {
        "success": True,
        "generated": generated,
        "stdout": proc.stdout.strip()[-2000:],
    }
