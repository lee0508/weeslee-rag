# -*- coding: utf-8 -*-
"""
Project Wiki API.

GET  /api/wiki/projects          — 사용 가능한 위키 목록
GET  /api/wiki/projects/{slug}   — 위키 마크다운 + 메타데이터
POST /api/wiki/build             — build_project_wiki.py 실행 (재생성)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/wiki", tags=["Wiki"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
WIKI_DIR = DATA_DIR / "wiki" / "projects"
_BUILD_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "build_project_wiki.py"
_INVENTORY_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "build_project_inventory.py"

# slug 검증: 영문 소문자, 숫자, 하이픈만 허용 (한글 slug는 ASCII 변환 필요)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,79}$")


# ============================================================
# 공통 유틸리티 함수 (Wiki 파이프라인 산출물 계약)
# ============================================================

def _make_ascii_slug(name: str, existing: set[str]) -> str:
    """한글 이름을 URL-safe한 ASCII slug로 변환한다.

    기준 4(b) 방식: 영문/숫자 토큰은 유지하고, 한글은 짧은 해시로 대체.
    한글 원문은 index.json의 project_name에 그대로 보관하므로 손실 없음.
    조회용 _SLUG_RE(^[a-z0-9][a-z0-9\\-]{0,79}$)를 항상 통과하는 것이 목표.
    """
    # 1) 영문/숫자 토큰만 추출 (예: "2024년 AI 바우처" → "2024-ai")
    tokens = re.findall(r"[a-zA-Z0-9]+", name.lower())
    base = "-".join(tokens)[:40]

    # 2) 한글 부분의 고유성 보장을 위해 원문 전체의 md5 앞 8자리를 붙임
    h = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    slug = f"{base}-{h}" if base else f"w-{h}"

    # 3) 혹시 모를 중복 충돌 방지 (같은 빌드 내에서)
    n = 2
    final = slug
    while final in existing:
        final = f"{slug}-{n}"
        n += 1
    existing.add(final)
    return final


def _write_wiki_index(
    source_id: str,
    entries: list[dict],
    dataset_id: str | None = None,
    snapshot_id: str | None = None,
) -> None:
    """Wiki 빌드 산출물 계약의 나머지 절반(index.json, build_info.json)을 작성한다.

    entries의 각 항목은 반드시 아래 키를 포함해야 한다 (wiki_search.py 계약):
      - wiki_type      : "project" | "organization" | "technology"
      - project_folder : 1차 검색(디렉토리명) 매칭 대상 문자열
      - project_name   : 한글 원문 이름 (사용자에게 표시)
      - wiki_file      : 저장된 마크다운 파일명 (예: "2024-ai-3fa2b1c9.md")
      - document_ids   : 이 Wiki의 근거가 된 문서 ID 목록 (역추적성)
    """
    source_dir = DATA_DIR / "wiki" / source_id
    source_dir.mkdir(parents=True, exist_ok=True)

    # ── index.json 원자적 쓰기 ──
    # 임시 파일에 먼저 쓰고 os.replace로 교체 → 빌드 중 크래시가 나도
    # 검색 API는 항상 "완전한 이전 버전" 아니면 "완전한 새 버전"만 본다.
    index_tmp = source_dir / "index.json.tmp"
    index_tmp.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(index_tmp, source_dir / "index.json")

    # ── build_info.json 작성 ──
    # /wiki/status API와 스냅샷 정합성 추적(SnapshotManager 연계)에 사용
    build_info = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "entry_count": len(entries),
        "by_type": {
            t: sum(1 for e in entries if e.get("wiki_type") == t)
            for t in ("project", "organization", "technology")
        },
    }
    info_tmp = source_dir / "build_info.json.tmp"
    info_tmp.write_text(
        json.dumps(build_info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(info_tmp, source_dir / "build_info.json")


def _load_existing_index(source_id: str, exclude_type: str | None = None) -> list[dict]:
    """기존 index.json을 로드하고, exclude_type에 해당하는 항목은 제외한다."""
    index_path = DATA_DIR / "wiki" / source_id / "index.json"
    if not index_path.exists():
        return []
    try:
        entries = json.loads(index_path.read_text(encoding="utf-8"))
        if exclude_type:
            return [e for e in entries if e.get("wiki_type") != exclude_type]
        return entries
    except Exception:
        return []


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
    model: Optional[str] = None,
):
    """build_project_wiki.py 실행하여 위키 재생성.

    Args:
        slug: 특정 프로젝트 slug (선택)
        source_id: Document Source ID (선택). 지정 시 해당 source의 inventory 사용
        from_inventory: True면 inventory의 모든 프로젝트 처리 (TARGET_PROJECTS 무시)
        max_projects: 처리할 최대 프로젝트 수 (0=무제한)
        model: LLM 모델명 (선택, 예: gemma3:12b)
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
    # [2026-07-08] model 파라미터 전달
    if model:
        cmd += ["--model", model]

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,  # [2026-07-08] 600→1800초로 증가 (admin_llm_wiki.py와 동일)
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Wiki build timed out (1800s)")

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
        if wiki_type == "technology":
            return DATA_DIR / "wiki" / source_id / "technologies"
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
async def generate_wiki_by_organization(
    source_id: Optional[str] = None,
    snapshot: Optional[str] = None
):
    """발주기관별 Wiki 생성 — 산출물 계약 준수 버전.

    변경점:
      1. source_id 필수 권장 (검색 가능한 경로에만 저장)
      2. limit=1000 하드캡 제거 → 페이지네이션 루프
      3. document_ids 수집 → index.json에 기록 (역추적성)
      4. ASCII slug + 한글 원문 분리
      5. 빌드 완료 시 index.json / build_info.json 갱신
    """
    from app.services.metadata_db import metadata_db_service

    # source_id가 없으면 "default"로 설정 (검색 가능하도록)
    effective_source_id = source_id or "src_default"

    wiki_dir = _get_wiki_type_dir("organization", effective_source_id)
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # ── 전체 문서 로드: 하드캡 대신 페이지네이션 ──
    documents: list[dict] = []
    offset = 0
    while True:
        batch = metadata_db_service.list_documents(
            limit=1000, offset=offset, source_id=source_id
        )
        if not batch:
            break
        documents.extend(batch)
        offset += len(batch)
        if offset >= 10000:  # 안전 상한
            break

    # 발주기관명 기준으로 그룹핑
    org_docs: dict[str, list] = {}
    for doc in documents:
        org = (doc.get("organization") or "").strip() or "미분류"
        org_docs.setdefault(org, []).append(doc)

    generated: list[str] = []
    index_entries: list[dict] = []
    used_slugs: set[str] = set()

    for org_name, docs in org_docs.items():
        if org_name == "미분류" and len(docs) < 3:
            continue

        # 한글 기관명 → ASCII slug. 원문은 index.json에 보관.
        slug = _make_ascii_slug(org_name, used_slugs)

        # 마크다운 생성
        md_content = _generate_org_wiki_markdown(org_name, docs)

        wiki_path = wiki_dir / f"{slug}.md"
        wiki_path.write_text(md_content, encoding="utf-8")
        generated.append(slug)

        # ── index.json 항목: wiki_search.py가 요구하는 계약 필드 전부 ──
        index_entries.append({
            "wiki_type": "organization",
            "project_folder": org_name,       # 1차 검색 매칭 대상 = 기관명 원문
            "project_name": org_name,         # 표시용 한글 원문
            "wiki_file": f"{slug}.md",
            "document_ids": [d["id"] for d in docs if d.get("id")],  # 근거 역추적
        })

    # ── 기존 index.json과 병합: organization 타입만 교체 ──
    existing_entries = _load_existing_index(effective_source_id, exclude_type="organization")

    _write_wiki_index(
        effective_source_id,
        existing_entries + index_entries,
        snapshot_id=snapshot,
    )

    return {
        "success": True,
        "generated": generated,
        "count": len(generated),
        "source_id": effective_source_id,
    }


@router.post("/generate/by-project")
async def generate_wiki_by_project(source_id: Optional[str] = None, snapshot: Optional[str] = None):
    """사업별 Wiki 생성 (기존 build 함수 호출)."""
    return await build_wiki(slug=None, source_id=source_id, snapshot=snapshot)


@router.post("/generate/by-technology")
async def generate_wiki_by_technology(
    source_id: Optional[str] = None,
    snapshot: Optional[str] = None
):
    """기술별 Wiki 생성 — 산출물 계약 준수 버전."""
    from app.services.metadata_db import metadata_db_service

    def _normalize_technology_tags(value) -> list[str]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = []
        return [tag.strip() for tag in (value or []) if isinstance(tag, str) and tag.strip()]

    def _extract_technology_tags_from_doc(doc: dict) -> list[str]:
        tech_tags: list[str] = []
        for tag in doc.get("tags") or []:
            if not isinstance(tag, dict):
                continue
            if str(tag.get("tag_type") or "").strip().lower() != "technology":
                continue
            tag_name = str(tag.get("tag_name") or "").strip()
            if tag_name:
                tech_tags.append(tag_name)
        return list(dict.fromkeys(tech_tags))

    # source_id가 없으면 "default"로 설정 (검색 가능하도록)
    effective_source_id = source_id or "src_default"

    wiki_dir = _get_wiki_type_dir("technology", effective_source_id)
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # ── 전체 문서 로드: 페이지네이션 ──
    documents: list[dict] = []
    offset = 0
    while True:
        batch = metadata_db_service.list_documents(
            limit=1000, offset=offset, source_id=source_id
        )
        if not batch:
            break
        documents.extend(batch)
        offset += len(batch)
        if offset >= 10000:
            break

    tech_docs: dict[str, list] = {}

    for doc in documents:
        suggestion = metadata_db_service.get_suggestion(doc["id"])
        tech_tags = []
        if suggestion:
            tech_tags = _normalize_technology_tags(suggestion.get("technology_tags", []))
        if not tech_tags:
            tech_tags = _extract_technology_tags_from_doc(doc)

        for tag in tech_tags:
            tech_docs.setdefault(tag, []).append(doc)

    generated: list[str] = []
    index_entries: list[dict] = []
    used_slugs: set[str] = set()

    for tech_name, docs in tech_docs.items():
        if len(docs) < 2:
            continue

        # 한글 기술명 → ASCII slug
        slug = _make_ascii_slug(tech_name, used_slugs)
        md_content = _generate_tech_wiki_markdown(tech_name, docs)

        wiki_path = wiki_dir / f"{slug}.md"
        wiki_path.write_text(md_content, encoding="utf-8")
        generated.append(slug)

        # ── index.json 항목 ──
        index_entries.append({
            "wiki_type": "technology",
            "project_folder": tech_name,
            "project_name": tech_name,
            "wiki_file": f"{slug}.md",
            "document_ids": [d["id"] for d in docs if d.get("id")],
        })

    # ── 기존 index.json과 병합: technology 타입만 교체 ──
    existing_entries = _load_existing_index(effective_source_id, exclude_type="technology")

    _write_wiki_index(
        effective_source_id,
        existing_entries + index_entries,
        snapshot_id=snapshot,
    )

    return {
        "success": True,
        "generated": generated,
        "count": len(generated),
        "source_id": effective_source_id,
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
