# Wiki 계층적 검색 API
"""
Wiki 데이터 검색 API:
1차: 디렉토리명 (프로젝트 폴더)
2차: 파일명 (Wiki 마크다운 파일명)
3차: 파일 본문 내용

검색 결과는 근거 자료로 반환됩니다.
"""

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from pathlib import Path
import json
import re

router = APIRouter(prefix="/wiki", tags=["Wiki Search"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WIKI_DIR = PROJECT_ROOT / "data" / "wiki"


class WikiSearchHit(BaseModel):
    """Wiki 검색 결과 항목"""
    match_level: str = Field(..., description="매칭 레벨: directory, filename, content")
    project_folder: str = Field(..., description="프로젝트 폴더명")
    project_name: str = Field(..., description="프로젝트명")
    wiki_file: str = Field(..., description="Wiki 파일명")
    source_id: str = Field(..., description="Source ID")
    document_ids: List[int] = Field(default_factory=list, description="연관 Document IDs")
    matched_text: Optional[str] = Field(None, description="매칭된 텍스트 조각")
    score: float = Field(..., description="검색 점수 (1.0=최고)")


class WikiSearchResponse(BaseModel):
    """Wiki 검색 응답"""
    success: bool
    query: str
    total_hits: int
    hits: List[WikiSearchHit]
    search_time_ms: float


def search_wiki_directories(query: str, source_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """1차: 디렉토리명(프로젝트 폴더) 검색"""
    hits = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    wiki_sources = []
    if source_id:
        source_dir = WIKI_DIR / source_id
        if source_dir.exists():
            wiki_sources.append((source_id, source_dir))
    else:
        # 모든 source_id 디렉토리 검색
        for source_dir in WIKI_DIR.iterdir():
            if source_dir.is_dir() and source_dir.name.startswith("src_"):
                wiki_sources.append((source_dir.name, source_dir))

    for src_id, source_dir in wiki_sources:
        index_path = source_dir / "index.json"
        if not index_path.exists():
            continue

        try:
            index_data = json.loads(index_path.read_text(encoding='utf-8'))

            for project in index_data:
                project_folder = project.get("project_folder", "")
                if pattern.search(project_folder):
                    hits.append({
                        "match_level": "directory",
                        "project_folder": project_folder,
                        "project_name": project.get("project_name", project_folder),
                        "wiki_file": project.get("wiki_file", ""),
                        "source_id": src_id,
                        "document_ids": project.get("document_ids", []),
                        "matched_text": project_folder,
                        "score": 1.0  # 디렉토리명 매칭: 최고 점수
                    })
        except Exception:
            pass

    return hits


def search_wiki_filenames(query: str, source_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """2차: 파일명 검색"""
    hits = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    wiki_sources = []
    if source_id:
        source_dir = WIKI_DIR / source_id
        if source_dir.exists():
            wiki_sources.append((source_id, source_dir))
    else:
        for source_dir in WIKI_DIR.iterdir():
            if source_dir.is_dir() and source_dir.name.startswith("src_"):
                wiki_sources.append((source_dir.name, source_dir))

    for src_id, source_dir in wiki_sources:
        projects_dir = source_dir / "projects"
        if not projects_dir.exists():
            continue

        index_path = source_dir / "index.json"
        index_map = {}
        if index_path.exists():
            try:
                index_data = json.loads(index_path.read_text(encoding='utf-8'))
                for proj in index_data:
                    index_map[proj.get("wiki_file", "")] = proj
            except Exception:
                pass

        for wiki_file in projects_dir.glob("*.md"):
            if pattern.search(wiki_file.stem):
                proj_info = index_map.get(wiki_file.name, {})
                hits.append({
                    "match_level": "filename",
                    "project_folder": proj_info.get("project_folder", wiki_file.stem),
                    "project_name": proj_info.get("project_name", wiki_file.stem),
                    "wiki_file": wiki_file.name,
                    "source_id": src_id,
                    "document_ids": proj_info.get("document_ids", []),
                    "matched_text": wiki_file.stem,
                    "score": 0.8  # 파일명 매칭
                })

    return hits


def search_wiki_content(query: str, source_id: Optional[str] = None, max_snippets: int = 3) -> List[Dict[str, Any]]:
    """3차: 본문 내용 검색"""
    hits = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    wiki_sources = []
    if source_id:
        source_dir = WIKI_DIR / source_id
        if source_dir.exists():
            wiki_sources.append((source_id, source_dir))
    else:
        for source_dir in WIKI_DIR.iterdir():
            if source_dir.is_dir() and source_dir.name.startswith("src_"):
                wiki_sources.append((source_dir.name, source_dir))

    for src_id, source_dir in wiki_sources:
        projects_dir = source_dir / "projects"
        if not projects_dir.exists():
            continue

        index_path = source_dir / "index.json"
        index_map = {}
        if index_path.exists():
            try:
                index_data = json.loads(index_path.read_text(encoding='utf-8'))
                for proj in index_data:
                    index_map[proj.get("wiki_file", "")] = proj
            except Exception:
                pass

        for wiki_file in projects_dir.glob("*.md"):
            try:
                content = wiki_file.read_text(encoding='utf-8', errors='replace')

                # 매칭되는 부분 찾기
                matches = list(pattern.finditer(content))
                if not matches:
                    continue

                # 각 매칭 위치에서 스니펫 추출
                snippets = []
                for match in matches[:max_snippets]:
                    start = max(0, match.start() - 100)
                    end = min(len(content), match.end() + 100)
                    snippet = content[start:end].strip()
                    # 줄바꿈을 공백으로 변환
                    snippet = re.sub(r'\s+', ' ', snippet)
                    snippets.append(f"...{snippet}...")

                proj_info = index_map.get(wiki_file.name, {})
                hits.append({
                    "match_level": "content",
                    "project_folder": proj_info.get("project_folder", wiki_file.stem),
                    "project_name": proj_info.get("project_name", wiki_file.stem),
                    "wiki_file": wiki_file.name,
                    "source_id": src_id,
                    "document_ids": proj_info.get("document_ids", []),
                    "matched_text": " | ".join(snippets),
                    "score": 0.6  # 본문 매칭
                })

            except Exception:
                pass

    return hits


@router.get("/search", response_model=WikiSearchResponse)
async def search_wiki(
    query: str = Query(..., min_length=1, description="검색 쿼리"),
    source_id: Optional[str] = Query(None, description="특정 source_id로 제한"),
    max_hits: int = Query(20, ge=1, le=100, description="최대 결과 수")
):
    """
    Wiki 계층적 검색

    검색 우선순위:
    1. 디렉토리명 (프로젝트 폴더) - score: 1.0
    2. 파일명 (Wiki 마크다운 파일) - score: 0.8
    3. 본문 내용 - score: 0.6
    """
    import time
    start_time = time.time()

    try:
        # 계층적 검색 실행
        directory_hits = search_wiki_directories(query, source_id)
        filename_hits = search_wiki_filenames(query, source_id)
        content_hits = search_wiki_content(query, source_id)

        # 중복 제거 (우선순위: directory > filename > content)
        seen_keys = set()
        all_hits = []

        for hit in directory_hits + filename_hits + content_hits:
            key = (hit["source_id"], hit["wiki_file"])
            if key not in seen_keys:
                seen_keys.add(key)
                all_hits.append(WikiSearchHit(**hit))

        # 점수순 정렬
        all_hits.sort(key=lambda x: x.score, reverse=True)

        # 최대 개수 제한
        all_hits = all_hits[:max_hits]

        search_time_ms = (time.time() - start_time) * 1000

        return WikiSearchResponse(
            success=True,
            query=query,
            total_hits=len(all_hits),
            hits=all_hits,
            search_time_ms=search_time_ms
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Wiki search failed: {str(e)}")


@router.get("/status")
async def get_wiki_status(source_id: Optional[str] = None):
    """Wiki 인덱스 상태 조회"""
    try:
        if source_id:
            source_dirs = [WIKI_DIR / source_id] if (WIKI_DIR / source_id).exists() else []
        else:
            source_dirs = [d for d in WIKI_DIR.iterdir() if d.is_dir() and d.name.startswith("src_")]

        sources = []
        for source_dir in source_dirs:
            build_info_path = source_dir / "build_info.json"
            index_path = source_dir / "index.json"
            projects_dir = source_dir / "projects"

            wiki_count = len(list(projects_dir.glob("*.md"))) if projects_dir.exists() else 0

            source_info = {
                "source_id": source_dir.name,
                "has_build_info": build_info_path.exists(),
                "has_index": index_path.exists(),
                "wiki_count": wiki_count
            }

            if build_info_path.exists():
                try:
                    build_info = json.loads(build_info_path.read_text(encoding='utf-8'))
                    source_info["built_at"] = build_info.get("built_at")
                    source_info["dataset_id"] = build_info.get("dataset_id")
                except Exception:
                    pass

            sources.append(source_info)

        return {
            "success": True,
            "total_sources": len(sources),
            "sources": sources
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get wiki status: {str(e)}")
