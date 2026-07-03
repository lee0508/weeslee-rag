# Dataset Builder Step 9: Wiki Build API
"""
Step 9는 프로젝트, 조직, 기술별 Wiki 문서를 자동 생성합니다.
"""
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import require_admin_token
from app.core.database import get_db


router = APIRouter(
    prefix="/admin/dataset-builder/step9",
    tags=["Admin - Dataset Builder Step 9"],
    dependencies=[Depends(require_admin_token)],
)


# ── Request/Response Models ─────────────────────────────────────────────────


class WikiBuildRequest(BaseModel):
    """Wiki 빌드 실행 요청"""
    source_id: Optional[str] = None  # None이면 모든 문서 대상
    wiki_type: str = "project"  # project, organization, technology
    slug: Optional[str] = None  # 특정 프로젝트/조직/기술만 생성
    from_inventory: bool = False  # inventory 기반 생성
    max_wikis: int = 0  # 최대 생성 수 (0=무제한)


class WikiBuildResponse(BaseModel):
    """Wiki 빌드 실행 응답"""
    success: bool
    message: str
    generated_count: int = 0
    generated_wikis: List[str] = []
    processing_time: float  # seconds
    output: str = ""


class Step9StatusResponse(BaseModel):
    """Step 9 상태 응답"""
    project_wikis: int
    organization_wikis: int
    technology_wikis: int
    total_wikis: int


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.post("/build", response_model=WikiBuildResponse)
async def build_wiki(
    request: WikiBuildRequest,
    db: Session = Depends(get_db)
):
    """
    Wiki 문서를 생성합니다.

    wiki.py의 /api/wiki/build 또는 generate 엔드포인트를 호출합니다.
    """
    import subprocess
    import sys
    import json

    start_time = datetime.now()

    try:
        project_root = Path(__file__).resolve().parents[3]

        # wiki_type에 따라 다른 엔드포인트 호출
        if request.wiki_type == "project":
            # build_wiki_from_db.py 스크립트 실행 (DB 기반 Wiki 생성)
            build_script = project_root / "backend" / "scripts" / "build_wiki_from_db.py"

            if not build_script.exists():
                raise HTTPException(
                    status_code=500,
                    detail=f"build_wiki_from_db.py not found at {build_script}"
                )

            # source_id 필수
            if not request.source_id:
                raise HTTPException(
                    status_code=400,
                    detail="source_id is required for DB-based wiki generation"
                )

            cmd = [sys.executable, str(build_script), "--source-id", request.source_id]

            if request.max_wikis > 0:
                cmd += ["--max-wikis", str(request.max_wikis)]

            # 스크립트 실행
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                cwd=str(project_root),
            )

            if proc.returncode != 0:
                return WikiBuildResponse(
                    success=False,
                    message="Wiki build failed",
                    processing_time=(datetime.now() - start_time).total_seconds(),
                    output=proc.stderr.strip() or "Build script failed"
                )

            # build_info.json에서 결과 읽기
            build_info_path = project_root / "data" / "wiki" / request.source_id / "build_info.json"
            generated_count = 0
            generated_wikis = []

            if build_info_path.exists():
                try:
                    build_info = json.loads(build_info_path.read_text(encoding="utf-8"))
                    generated_count = build_info.get("wiki_count", 0)
                    generated_wikis = build_info.get("generated_wikis", [])
                except Exception:
                    pass

            end_time = datetime.now()
            processing_time = (end_time - start_time).total_seconds()

            return WikiBuildResponse(
                success=True,
                message=f"Wiki build completed: {generated_count} wikis generated",
                generated_count=generated_count,
                generated_wikis=generated_wikis[:20],  # 최대 20개만 반환
                processing_time=processing_time,
                output=proc.stdout.strip()[-500:]
            )

        elif request.wiki_type == "organization":
            # organization wiki 생성은 API 직접 호출
            from app.api.wiki import generate_wiki_by_organization

            result = await generate_wiki_by_organization()

            end_time = datetime.now()
            processing_time = (end_time - start_time).total_seconds()

            return WikiBuildResponse(
                success=result.get("success", False),
                message=f"Organization wikis generated: {result.get('count', 0)}",
                generated_count=result.get("count", 0),
                generated_wikis=result.get("generated", [])[:20],
                processing_time=processing_time,
                output=f"Generated {result.get('count', 0)} organization wikis"
            )

        elif request.wiki_type == "technology":
            # technology wiki 생성은 API 직접 호출
            from app.api.wiki import generate_wiki_by_technology

            result = await generate_wiki_by_technology()

            end_time = datetime.now()
            processing_time = (end_time - start_time).total_seconds()

            return WikiBuildResponse(
                success=result.get("success", False),
                message=f"Technology wikis generated: {result.get('count', 0)}",
                generated_count=result.get("count", 0),
                generated_wikis=result.get("generated", [])[:20],
                processing_time=processing_time,
                output=f"Generated {result.get('count', 0)} technology wikis"
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid wiki_type: {request.wiki_type}. Use 'project', 'organization', or 'technology'."
            )

    except subprocess.TimeoutExpired:
        return WikiBuildResponse(
            success=False,
            message="Wiki build timed out (600s)",
            processing_time=600.0,
            output="Timeout after 600 seconds"
        )
    except HTTPException:
        raise
    except Exception as e:
        return WikiBuildResponse(
            success=False,
            message=f"Wiki build failed: {str(e)}",
            processing_time=(datetime.now() - start_time).total_seconds(),
            output=str(e)
        )


@router.get("/status", response_model=Step9StatusResponse)
async def get_step9_status(source_id: Optional[str] = None):
    """
    Step 9 Wiki 빌드 상태를 조회합니다.
    """
    try:
        from app.api.wiki import get_wiki_stats

        stats = await get_wiki_stats()

        return Step9StatusResponse(
            project_wikis=stats.get("project_count", 0),
            organization_wikis=stats.get("organization_count", 0),
            technology_wikis=stats.get("technology_count", 0),
            total_wikis=stats.get("total", 0)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.get("/stats")
async def get_step9_stats(source_id: Optional[str] = None):
    """
    Step 9 Wiki 통계를 조회합니다.
    """
    try:
        from app.api.wiki import list_wiki_projects

        result = await list_wiki_projects(source_id=source_id)

        # 페이지별 크기 통계
        total_size = 0
        pages = result.get("pages", [])

        for page in pages:
            total_size += page.get("size_bytes", 0)

        avg_size = total_size / len(pages) if pages else 0

        return {
            "success": True,
            "source_id": source_id or "all",
            "total_wikis": result.get("count", 0),
            "total_size_bytes": total_size,
            "avg_size_bytes": int(avg_size),
            "pages_preview": pages[:10]  # 최대 10개만 미리보기
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.get("/list")
async def list_wikis(
    source_id: Optional[str] = None,
    wiki_type: str = "project"
):
    """
    생성된 Wiki 목록을 조회합니다.
    """
    try:
        if wiki_type == "project":
            from app.api.wiki import list_wiki_projects
            return await list_wiki_projects(source_id=source_id)
        else:
            # organization, technology는 별도 디렉토리에서 조회
            project_root = Path(__file__).resolve().parents[3]

            if wiki_type == "organization":
                wiki_dir = project_root / "data" / "wiki" / "organizations"
            elif wiki_type == "technology":
                wiki_dir = project_root / "data" / "wiki" / "technologies"
            else:
                raise HTTPException(status_code=400, detail=f"Invalid wiki_type: {wiki_type}")

            if not wiki_dir.exists():
                return {"pages": [], "count": 0, "wiki_type": wiki_type}

            pages = []
            for md_file in sorted(wiki_dir.glob("*.md")):
                pages.append({
                    "slug": md_file.stem,
                    "file_name": md_file.name,
                    "size_bytes": md_file.stat().st_size
                })

            return {
                "pages": pages,
                "count": len(pages),
                "wiki_type": wiki_type
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list wikis: {str(e)}")
