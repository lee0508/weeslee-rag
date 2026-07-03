# LLM Wiki 관리 API - Dataset Builder에서 분리된 독립 메뉴용
"""
LLM Wiki 메뉴용 API 엔드포인트.
- Wiki 생성
- Wiki 미리보기
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import json
import asyncio
import subprocess
import sys
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_admin_token
from app.core.database import get_db


router = APIRouter(
    prefix="/admin/llm-wiki",
    tags=["Admin - LLM Wiki"],
    dependencies=[Depends(require_admin_token)],
)


# ── Request/Response Models ─────────────────────────────────────────────────


class WikiBuildRequest(BaseModel):
    """Wiki 빌드 요청"""
    source_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    wiki_type: str = Field("project", description="project | organization | technology")
    slug: Optional[str] = Field(None, description="특정 항목만 생성")
    from_inventory: bool = Field(False, description="inventory 기반 생성")
    max_wikis: int = Field(0, description="최대 생성 수 (0=무제한)")
    model: str = Field("gemma3:12b", description="LLM 모델")


class WikiBuildResponse(BaseModel):
    """Wiki 빌드 응답"""
    success: bool
    message: str
    generated_count: int = 0
    generated_wikis: List[str] = []
    processing_time: float = 0.0
    output: str = ""


class WikiStatusResponse(BaseModel):
    """Wiki 상태 응답"""
    status: str  # empty, building, ready
    project_wikis: int = 0
    organization_wikis: int = 0
    technology_wikis: int = 0
    total_wikis: int = 0
    last_built_at: Optional[str] = None
    running_job_id: Optional[str] = None
    message: Optional[str] = None


class WikiPageInfo(BaseModel):
    """Wiki 페이지 정보"""
    slug: str
    title: str
    wiki_type: str
    file_name: str
    size_bytes: int
    created_at: Optional[str] = None
    content_preview: str = ""


class WikiPreviewResponse(BaseModel):
    """Wiki 미리보기 응답"""
    success: bool
    total_count: int = 0
    pages: List[WikiPageInfo] = []
    type_counts: Dict[str, int] = {}


class WikiContentResponse(BaseModel):
    """Wiki 내용 응답"""
    success: bool
    slug: str
    title: str = ""
    content: str = ""
    metadata: Dict[str, Any] = {}


class WikiListItem(BaseModel):
    wiki_id: str
    wiki_type: str
    slug: str
    title: str
    created_at: Optional[str] = None
    size_bytes: int = 0
    document_count: Optional[int] = None


class WikiListResponse(BaseModel):
    success: bool
    wikis: List[WikiListItem] = []


# ── Helper Functions ────────────────────────────────────────────────────────


def _get_project_root() -> Path:
    """프로젝트 루트 경로 반환"""
    return Path(__file__).resolve().parents[3]


def _get_wiki_dir(source_id: Optional[str], wiki_type: str) -> Path:
    """Wiki 디렉토리 경로 반환"""
    project_root = _get_project_root()

    if source_id:
        base_dir = project_root / "data" / "wiki" / source_id
    else:
        base_dir = project_root / "data" / "wiki"

    if wiki_type == "project":
        return base_dir / "projects"
    elif wiki_type == "organization":
        return base_dir / "organizations"
    elif wiki_type == "technology":
        return base_dir / "technologies"
    else:
        return base_dir / "projects"


def _count_wikis(source_id: Optional[str]) -> Dict[str, int]:
    """Wiki 타입별 개수 반환"""
    counts = {"project": 0, "organization": 0, "technology": 0}

    for wiki_type in counts.keys():
        wiki_dir = _get_wiki_dir(source_id, wiki_type)
        if wiki_dir.exists():
            counts[wiki_type] = len(list(wiki_dir.glob("*.md")))

    return counts


_WIKI_BUILD_JOBS: Dict[str, Dict[str, Any]] = {}
_WIKI_JOB_LOCK = threading.Lock()


def _wiki_job_scope(source_id: Optional[str], wiki_type: str) -> str:
    return f"{source_id or 'all'}::{wiki_type}"


def _update_wiki_job(job_id: str, **updates) -> None:
    with _WIKI_JOB_LOCK:
        job = _WIKI_BUILD_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)


def _get_running_wiki_job(source_id: Optional[str], wiki_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _WIKI_JOB_LOCK:
        for job in _WIKI_BUILD_JOBS.values():
            if job.get("status") != "running":
                continue
            if source_id is not None and job.get("source_id") != source_id:
                continue
            if wiki_type is not None and job.get("wiki_type") != wiki_type:
                continue
            return dict(job)
    return None


def _get_latest_wiki_job(source_id: Optional[str], wiki_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    latest_job: Optional[Dict[str, Any]] = None
    latest_started_at = ""
    with _WIKI_JOB_LOCK:
        for job in _WIKI_BUILD_JOBS.values():
            if source_id is not None and job.get("source_id") != source_id:
                continue
            if wiki_type is not None and job.get("wiki_type") != wiki_type:
                continue
            started_at = str(job.get("started_at") or "")
            if not latest_job or started_at > latest_started_at:
                latest_job = dict(job)
                latest_started_at = started_at
    return latest_job


def _get_latest_wiki_mtime(source_id: Optional[str]) -> Optional[str]:
    latest_ts: Optional[float] = None
    for wiki_type in ["project", "organization", "technology"]:
        wiki_dir = _get_wiki_dir(source_id, wiki_type)
        if not wiki_dir.exists():
            continue
        for md_file in wiki_dir.glob("*.md"):
            try:
                mtime = md_file.stat().st_mtime
            except OSError:
                continue
            if latest_ts is None or mtime > latest_ts:
                latest_ts = mtime
    if latest_ts is None:
        return None
    return datetime.fromtimestamp(latest_ts).isoformat(timespec="seconds")


def _run_wiki_build_job(job_id: str, request_data: Dict[str, Any]) -> None:
    source_id = request_data.get("source_id")
    wiki_type = request_data.get("wiki_type", "project")
    start_time = datetime.now()

    try:
        project_root = _get_project_root()

        if wiki_type == "project":
            build_script = project_root / "backend" / "scripts" / "build_project_wiki.py"
            if not build_script.exists():
                raise FileNotFoundError(f"build_project_wiki.py not found at {build_script}")

            cmd = [sys.executable, str(build_script)]
            if request_data.get("slug"):
                cmd += ["--project", str(request_data["slug"])]
            elif source_id:
                cmd += ["--source-id", str(source_id)]
            elif request_data.get("from_inventory"):
                cmd += ["--from-inventory"]
            else:
                cmd += ["--all"]

            max_wikis = int(request_data.get("max_wikis") or 0)
            if max_wikis > 0:
                cmd += ["--max-projects", str(max_wikis)]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
                cwd=str(project_root),
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or "Build script failed")

            wiki_dir = _get_wiki_dir(source_id, "project")
            generated = [p.stem for p in wiki_dir.glob("*.md")] if wiki_dir.exists() else []
            _update_wiki_job(
                job_id,
                status="completed",
                success=True,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                generated_count=len(generated),
                generated_wikis=generated[:20],
                message=f"Wiki build completed: {len(generated)} pages",
                output=(proc.stdout or "").strip()[-2000:],
                processing_time=(datetime.now() - start_time).total_seconds(),
            )
            return

        if wiki_type == "organization":
            from app.api.wiki import generate_wiki_by_organization

            result = asyncio.run(generate_wiki_by_organization(source_id=source_id))
            _update_wiki_job(
                job_id,
                status="completed",
                success=bool(result.get("success", False)),
                finished_at=datetime.now().isoformat(timespec="seconds"),
                generated_count=int(result.get("count", 0) or 0),
                generated_wikis=(result.get("generated", []) or [])[:20],
                message=f"Wiki build completed: {int(result.get('count', 0) or 0)} pages",
                output=json.dumps(result, ensure_ascii=False)[-2000:],
                processing_time=(datetime.now() - start_time).total_seconds(),
            )
            return

        if wiki_type == "technology":
            from app.api.wiki import generate_wiki_by_technology

            result = asyncio.run(generate_wiki_by_technology(source_id=source_id))
            _update_wiki_job(
                job_id,
                status="completed",
                success=bool(result.get("success", False)),
                finished_at=datetime.now().isoformat(timespec="seconds"),
                generated_count=int(result.get("count", 0) or 0),
                generated_wikis=(result.get("generated", []) or [])[:20],
                message=f"Wiki build completed: {int(result.get('count', 0) or 0)} pages",
                output=json.dumps(result, ensure_ascii=False)[-2000:],
                processing_time=(datetime.now() - start_time).total_seconds(),
            )
            return

        raise ValueError(f"Invalid wiki_type: {wiki_type}")
    except subprocess.TimeoutExpired:
        _update_wiki_job(
            job_id,
            status="failed",
            success=False,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            message="Wiki build timed out (1800s)",
            processing_time=(datetime.now() - start_time).total_seconds(),
        )
    except Exception as e:
        _update_wiki_job(
            job_id,
            status="failed",
            success=False,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            message=str(e),
            processing_time=(datetime.now() - start_time).total_seconds(),
        )


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.post("/build", response_model=WikiBuildResponse)
async def build_wiki(
    request: WikiBuildRequest,
    db: Session = Depends(get_db)
):
    """
    LLM Wiki를 생성합니다.
    """
    try:
        if request.wiki_type not in {"project", "organization", "technology"}:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid wiki_type: {request.wiki_type}"
            )

        running_job = _get_running_wiki_job(request.source_id, request.wiki_type)
        if running_job:
            return WikiBuildResponse(
                success=True,
                message=f"이미 Wiki build가 실행 중입니다. job_id={running_job['job_id']}",
                processing_time=0.0,
                output="already_running"
            )

        job_id = f"wiki_{uuid.uuid4().hex[:12]}"
        request_data = request.model_dump()
        request_data["job_id"] = job_id
        request_data["scope"] = _wiki_job_scope(request.source_id, request.wiki_type)

        with _WIKI_JOB_LOCK:
            _WIKI_BUILD_JOBS[job_id] = {
                "job_id": job_id,
                "scope": request_data["scope"],
                "source_id": request.source_id,
                "wiki_type": request.wiki_type,
                "status": "running",
                "success": None,
                "message": "Wiki build started",
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": None,
                "generated_count": 0,
                "generated_wikis": [],
                "output": "",
                "processing_time": 0.0,
            }

        thread = threading.Thread(
            target=_run_wiki_build_job,
            args=(job_id, request_data),
            daemon=True,
        )
        thread.start()

        return WikiBuildResponse(
            success=True,
            message=f"Wiki build started. job_id={job_id}",
            generated_count=0,
            generated_wikis=[],
            processing_time=0.0,
            output="started_async"
        )
    except HTTPException:
        raise
    except Exception as e:
        return WikiBuildResponse(
            success=False,
            message=f"Wiki build failed: {str(e)}",
            processing_time=0.0
        )


@router.get("/status", response_model=WikiStatusResponse)
async def get_wiki_status(source_id: Optional[str] = None, wiki_type: Optional[str] = None):
    """
    LLM Wiki 상태를 조회합니다.
    """
    try:
        counts = _count_wikis(source_id)
        total = sum(counts.values())
        latest_job = _get_latest_wiki_job(source_id, wiki_type)
        status = "ready" if total > 0 else "empty"
        message = None
        running_job_id = None

        if latest_job:
            if latest_job.get("status") == "running":
                status = "building"
                running_job_id = latest_job.get("job_id")
                message = latest_job.get("message")
            elif latest_job.get("status") == "failed":
                status = "error"
                message = latest_job.get("message") or "Wiki build failed"
            elif latest_job.get("status") == "completed":
                status = "ready" if total > 0 else "empty"
                message = latest_job.get("message")

        return WikiStatusResponse(
            status=status,
            project_wikis=counts["project"],
            organization_wikis=counts["organization"],
            technology_wikis=counts["technology"],
            total_wikis=total,
            last_built_at=_get_latest_wiki_mtime(source_id),
            running_job_id=running_job_id,
            message=message,
        )

    except Exception:
        return WikiStatusResponse(status="error")


@router.get("/preview", response_model=WikiPreviewResponse)
async def get_wiki_preview(
    source_id: Optional[str] = None,
    wiki_type: Optional[str] = None,
    limit: int = 50
):
    """
    Wiki 목록 미리보기를 반환합니다.
    """
    try:
        pages: List[WikiPageInfo] = []
        type_counts = _count_wikis(source_id)

        wiki_types = [wiki_type] if wiki_type else ["project", "organization", "technology"]

        for wt in wiki_types:
            wiki_dir = _get_wiki_dir(source_id, wt)
            if not wiki_dir.exists():
                continue

            for md_file in sorted(wiki_dir.glob("*.md"))[:limit // len(wiki_types)]:
                try:
                    content = md_file.read_text(encoding="utf-8")
                    lines = content.split("\n")

                    # 제목 추출 (첫 번째 # 헤더)
                    title = md_file.stem
                    for line in lines:
                        if line.startswith("# "):
                            title = line[2:].strip()
                            break

                    pages.append(WikiPageInfo(
                        slug=md_file.stem,
                        title=title,
                        wiki_type=wt,
                        file_name=md_file.name,
                        size_bytes=md_file.stat().st_size,
                        content_preview=content[:300] + "..." if len(content) > 300 else content
                    ))
                except Exception:
                    continue

        return WikiPreviewResponse(
            success=True,
            total_count=sum(type_counts.values()),
            pages=pages[:limit],
            type_counts=type_counts
        )

    except Exception:
        return WikiPreviewResponse(success=False)


@router.get("/list", response_model=WikiListResponse)
async def get_wiki_list(
    source_id: Optional[str] = None,
    wiki_type: Optional[str] = None,
    limit: int = 50,
):
    """관리자 표용 Wiki 목록을 반환한다."""
    preview = await get_wiki_preview(source_id=source_id, wiki_type=wiki_type, limit=limit)
    if not preview.success:
        return WikiListResponse(success=False, wikis=[])

    items = [
        WikiListItem(
            wiki_id=f"{page.wiki_type}:{page.slug}",
            wiki_type=page.wiki_type,
            slug=page.slug,
            title=page.title,
            created_at=page.created_at,
            size_bytes=page.size_bytes,
            document_count=None,
        )
        for page in preview.pages
    ]
    return WikiListResponse(success=True, wikis=items)


@router.get("/content/{wiki_type}/{slug}", response_model=WikiContentResponse)
async def get_wiki_content(
    wiki_type: str,
    slug: str,
    source_id: Optional[str] = None
):
    """
    특정 Wiki 내용을 조회합니다.
    """
    try:
        wiki_dir = _get_wiki_dir(source_id, wiki_type)
        wiki_file = wiki_dir / f"{slug}.md"

        if not wiki_file.exists():
            raise HTTPException(status_code=404, detail=f"Wiki not found: {slug}")

        content = wiki_file.read_text(encoding="utf-8")
        lines = content.split("\n")

        # 제목 추출
        title = slug
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break

        return WikiContentResponse(
            success=True,
            slug=slug,
            title=title,
            content=content
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_wiki_stats(source_id: Optional[str] = None):
    """
    Wiki 통계를 조회합니다.
    """
    try:
        counts = _count_wikis(source_id)
        total_size = 0

        for wiki_type in ["project", "organization", "technology"]:
            wiki_dir = _get_wiki_dir(source_id, wiki_type)
            if wiki_dir.exists():
                for md_file in wiki_dir.glob("*.md"):
                    total_size += md_file.stat().st_size

        return {
            "success": True,
            "source_id": source_id or "all",
            "project_wikis": counts["project"],
            "organization_wikis": counts["organization"],
            "technology_wikis": counts["technology"],
            "total_wikis": sum(counts.values()),
            "total_size_bytes": total_size,
            "avg_size_bytes": total_size // max(sum(counts.values()), 1)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.delete("/clear")
async def clear_wikis(
    wiki_type: Optional[str] = None,
    source_id: Optional[str] = None
):
    """
    Wiki를 삭제합니다.
    """
    try:
        deleted_count = 0
        wiki_types = [wiki_type] if wiki_type else ["project", "organization", "technology"]

        for wt in wiki_types:
            wiki_dir = _get_wiki_dir(source_id, wt)
            if wiki_dir.exists():
                for md_file in wiki_dir.glob("*.md"):
                    md_file.unlink()
                    deleted_count += 1

        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": f"{deleted_count}개 Wiki 삭제됨"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear wikis: {str(e)}")
