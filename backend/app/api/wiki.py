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
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/wiki", tags=["Wiki"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
WIKI_DIR = DATA_DIR / "wiki" / "projects"
_BUILD_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "build_project_wiki.py"
_INVENTORY_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "build_project_inventory.py"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,79}$")


def _get_wiki_dir(source_id: Optional[str] = None) -> Path:
    """source_id별 Wiki 디렉토리 반환."""
    if source_id:
        return DATA_DIR / "wiki" / source_id / "projects"
    return WIKI_DIR


def _slugify(name: str) -> str:
    # 한글도 허용하는 slug 생성
    slug = re.sub(r"[^\w가-힣]+", "-", name.lower()).strip("-")
    # 연속된 하이픈 제거
    slug = re.sub(r"-+", "-", slug)
    return slug or "unknown"


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
async def list_wiki_projects(source_id: Optional[str] = None):
    """사용 가능한 프로젝트 위키 목록."""
    wiki_dir = _get_wiki_dir(source_id)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for md_file in sorted(wiki_dir.glob("*.md")):
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
    return {"pages": pages, "count": len(pages), "source_id": source_id or "default"}


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
async def get_wiki_project(slug: str, source_id: Optional[str] = None):
    """특정 프로젝트 위키 마크다운과 메타데이터."""
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug format")

    wiki_dir = _get_wiki_dir(source_id)
    path = wiki_dir / f"{slug}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Wiki not found: {slug}")

    result = _read_wiki(path)
    result["source_id"] = source_id or "default"
    return result


@router.post("/build")
async def build_wiki(
    slug: Optional[str] = None,
    source_id: Optional[str] = None,
    snapshot: Optional[str] = None,
    from_inventory: bool = False,
    max_projects: int = 0,
):
    """build_project_wiki.py 실행하여 위키 재생성.

    Args:
        slug: 특정 프로젝트 slug (선택)
        source_id: Document Source ID (선택). 지정 시 해당 source의 inventory 사용
        from_inventory: True면 inventory의 모든 프로젝트 처리 (TARGET_PROJECTS 무시)
        max_projects: 처리할 최대 프로젝트 수 (0=무제한)
    """
    if not _BUILD_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="build_project_wiki.py not found")

    # source_id 지정 시 먼저 inventory 생성
    if source_id and _INVENTORY_SCRIPT.exists():
        inv_cmd = [sys.executable, str(_INVENTORY_SCRIPT), "--source-id", source_id]
        if snapshot:
            inv_cmd += ["--from-chunks", "--snapshot", snapshot]
        try:
            await asyncio.to_thread(
                subprocess.run,
                inv_cmd,
                capture_output=True,
                timeout=60,
                cwd=str(PROJECT_ROOT),
            )
        except Exception:
            pass  # inventory 생성 실패해도 계속 진행

    cmd = [sys.executable, str(_BUILD_SCRIPT)]
    if slug:
        cmd += ["--project", slug]
    elif source_id:
        cmd += ["--source-id", source_id]
    elif from_inventory:
        cmd += ["--from-inventory"]
    else:
        cmd += ["--all"]

    if max_projects > 0:
        cmd += ["--max-projects", str(max_projects)]
    if snapshot:
        cmd += ["--snapshot", snapshot]

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,  # source_id 모드는 더 오래 걸릴 수 있음
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Wiki build timed out (600s)")

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or "Build failed")

    # List generated files
    wiki_dir = _get_wiki_dir(source_id)
    generated = [p.stem for p in wiki_dir.glob("*.md")]
    return {
        "success": True,
        "source_id": source_id or "default",
        "generated": generated,
        "count": len(generated),
        "stdout": proc.stdout.strip()[-2000:],
    }


# ────────────────────────────────────────────────────────────────────────────
# Wiki 통계 및 카테고리별 생성 API
# ────────────────────────────────────────────────────────────────────────────

WIKI_ORG_DIR = PROJECT_ROOT / "data" / "wiki" / "organizations"
WIKI_TECH_DIR = PROJECT_ROOT / "data" / "wiki" / "technologies"


def _get_wiki_type_dir(wiki_type: str, source_id: Optional[str] = None) -> Path:
    """Wiki 유형별 저장 경로를 반환한다."""
    if wiki_type == "project":
        return _get_wiki_dir(source_id)
    if source_id:
        return DATA_DIR / "wiki" / source_id / f"{wiki_type}s"
    if wiki_type == "organization":
        return WIKI_ORG_DIR
    if wiki_type == "technology":
        return WIKI_TECH_DIR
    return _get_wiki_dir(source_id)


@router.get("/stats")
async def get_wiki_stats(source_id: Optional[str] = None):
    """Wiki 현황 통계."""
    project_wiki_dir = _get_wiki_type_dir("project", source_id)
    org_wiki_dir = _get_wiki_type_dir("organization", source_id)
    tech_wiki_dir = _get_wiki_type_dir("technology", source_id)
    project_wiki_dir.mkdir(parents=True, exist_ok=True)
    org_wiki_dir.mkdir(parents=True, exist_ok=True)
    tech_wiki_dir.mkdir(parents=True, exist_ok=True)

    project_count = len(list(project_wiki_dir.glob("*.md")))
    org_count = len(list(org_wiki_dir.glob("*.md")))
    tech_count = len(list(tech_wiki_dir.glob("*.md")))

    return {
        "source_id": source_id or "default",
        "project_count": project_count,
        "organization_count": org_count,
        "technology_count": tech_count,
        "total": project_count + org_count + tech_count,
    }


@router.post("/generate/by-organization")
async def generate_wiki_by_organization(source_id: Optional[str] = None):
    """발주기관별 Wiki 생성."""
    from app.services.metadata_db import metadata_db_service

    wiki_dir = _get_wiki_type_dir("organization", source_id)
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # SQLite에서 발주기관별 문서 집계
    documents = metadata_db_service.list_documents(limit=1000, source_id=source_id)
    org_docs: dict[str, list] = {}

    for doc in documents:
        org = doc.get("organization", "").strip()
        if not org:
            org = "미분류"
        if org not in org_docs:
            org_docs[org] = []
        org_docs[org].append(doc)

    generated = []
    for org_name, docs in org_docs.items():
        if org_name == "미분류" and len(docs) < 3:
            continue

        slug = _slugify(org_name) or "unknown"
        md_content = _generate_org_wiki_markdown(org_name, docs)

        wiki_path = wiki_dir / f"{slug}.md"
        wiki_path.write_text(md_content, encoding="utf-8")
        generated.append(slug)

    return {
        "success": True,
        "generated": generated,
        "count": len(generated),
        "source_id": source_id or "default",
    }


@router.post("/generate/by-project")
async def generate_wiki_by_project(source_id: Optional[str] = None, snapshot: Optional[str] = None):
    """사업별 Wiki 생성 (기존 build 함수 호출)."""
    return await build_wiki(slug=None, source_id=source_id, snapshot=snapshot)


@router.post("/generate/by-technology")
async def generate_wiki_by_technology(source_id: Optional[str] = None):
    """기술별 Wiki 생성."""
    from app.services.metadata_db import metadata_db_service

    wiki_dir = _get_wiki_type_dir("technology", source_id)
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # SQLite에서 기술 태그별 문서 집계
    documents = metadata_db_service.list_documents(limit=1000, source_id=source_id)
    tech_docs: dict[str, list] = {}

    for doc in documents:
        # suggestion에서 technology_tags 조회
        suggestion = metadata_db_service.get_suggestion(doc["id"])
        if not suggestion:
            continue

        tech_tags_raw = suggestion.get("technology_tags", "[]")
        if isinstance(tech_tags_raw, str):
            try:
                tech_tags = json.loads(tech_tags_raw)
            except json.JSONDecodeError:
                tech_tags = []
        else:
            tech_tags = tech_tags_raw or []

        for tag in tech_tags:
            tag = tag.strip()
            if not tag:
                continue
            if tag not in tech_docs:
                tech_docs[tag] = []
            tech_docs[tag].append(doc)

    generated = []
    for tech_name, docs in tech_docs.items():
        if len(docs) < 2:
            continue

        slug = _slugify(tech_name) or "tech"
        md_content = _generate_tech_wiki_markdown(tech_name, docs)

        wiki_path = wiki_dir / f"{slug}.md"
        wiki_path.write_text(md_content, encoding="utf-8")
        generated.append(slug)

    return {
        "success": True,
        "generated": generated,
        "count": len(generated),
        "source_id": source_id or "default",
    }


def _generate_org_wiki_markdown(org_name: str, docs: list) -> str:
    """발주기관 Wiki 마크다운 생성."""
    from datetime import datetime

    lines = [
        f"# {org_name}",
        "",
        f"> 발주기관 Wiki - 자동 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 개요",
        "",
        f"**{org_name}** 관련 프로젝트 문서 {len(docs)}건이 등록되어 있습니다.",
        "",
        "## 문서 목록",
        "",
        "| 문서명 | 유형 | 사업명 | 연도 |",
        "|--------|------|--------|------|",
    ]

    for doc in docs[:50]:
        file_name = doc.get("file_name", "").split("\\")[-1].split("/")[-1]
        doc_type = doc.get("document_type", "unknown")
        project_name = doc.get("project_name", "")[:30]
        year = doc.get("project_year", "")
        lines.append(f"| {file_name[:40]} | {doc_type} | {project_name} | {year} |")

    if len(docs) > 50:
        lines.append(f"| ... 외 {len(docs) - 50}건 | | | |")

    lines.extend([
        "",
        "---",
        f"*자동 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ])

    return "\n".join(lines)


def _generate_tech_wiki_markdown(tech_name: str, docs: list) -> str:
    """기술 키워드 Wiki 마크다운 생성."""
    from datetime import datetime

    lines = [
        f"# {tech_name}",
        "",
        f"> 기술 키워드 Wiki - 자동 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 개요",
        "",
        f"**{tech_name}** 관련 프로젝트 문서 {len(docs)}건이 등록되어 있습니다.",
        "",
        "## 관련 문서",
        "",
        "| 문서명 | 유형 | 발주기관 | 연도 |",
        "|--------|------|----------|------|",
    ]

    for doc in docs[:50]:
        file_name = doc.get("file_name", "").split("\\")[-1].split("/")[-1]
        doc_type = doc.get("document_type", "unknown")
        org = doc.get("organization", "")[:20]
        year = doc.get("project_year", "")
        lines.append(f"| {file_name[:40]} | {doc_type} | {org} | {year} |")

    if len(docs) > 50:
        lines.append(f"| ... 외 {len(docs) - 50}건 | | | |")

    lines.extend([
        "",
        "---",
        f"*자동 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ])

    return "\n".join(lines)
