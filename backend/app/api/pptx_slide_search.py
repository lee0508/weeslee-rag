# PPTX 슬라이드 키워드 검색 API
"""
PPTX 파일 내 키워드가 포함된 슬라이드를 검색하는 API.
시연회 요청사항: 질문 키워드가 있는 슬라이드 번호까지 찾아주기
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(
    prefix="/api/pptx",
    tags=["PPTX Slide Search"],
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"


class SlideSearchRequest(BaseModel):
    """슬라이드 검색 요청"""
    document_id: int
    keywords: list[str]
    source_id: Optional[str] = None


class SlideMatch(BaseModel):
    """키워드 매칭된 슬라이드 정보"""
    slide_no: int
    matched_keywords: list[str]
    preview: str
    match_count: int


class SlideSearchResponse(BaseModel):
    """슬라이드 검색 응답"""
    success: bool
    document_id: int
    file_name: str
    total_slides: int
    matched_slides: list[SlideMatch]
    keywords_used: list[str]
    error: Optional[str] = None


def _find_document_text(document_id: int, source_id: str = "") -> tuple[Optional[str], str]:
    """문서 텍스트 파일 찾기. (텍스트, 파일명) 반환."""
    # 여러 경로에서 텍스트 파일 탐색
    candidates = []

    # 1. Source별 Step 2 추출 결과
    if source_id:
        source_root = DATA_DIR / "source" / str(source_id)
        candidates.extend([
            source_root / "documents" / str(document_id) / "full_text.txt",
            source_root / "step2_extract" / "documents" / str(document_id) / "full_text.txt",
        ])

    # 2. 기존 전역 경로
    candidates.extend([
        DATA_DIR / "documents" / str(document_id) / "ocr" / "full_text.txt",
        DATA_DIR / "processed_text" / str(document_id) / "full_text.txt",
        DATA_DIR / "extracted_text" / str(document_id) / "raw_text.txt",
        DATA_DIR / "staged" / "text" / f"{document_id}.txt",
    ])

    for path in candidates:
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8-sig")
                return text, path.name
            except UnicodeDecodeError:
                try:
                    text = path.read_text(encoding="utf-8")
                    return text, path.name
                except Exception:
                    continue
            except Exception:
                continue

    return None, ""


def _find_file_name(document_id: int, source_id: str = "") -> str:
    """문서 파일명 찾기."""
    # manifest에서 조회
    manifest_dir = DATA_DIR / "staged" / "manifest"
    if manifest_dir.exists():
        for manifest_file in sorted(manifest_dir.glob("*.jsonl"), reverse=True):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        meta = json.loads(line)
                        doc_id = meta.get("document_id", "")
                        # DOC-YYYYMMDD-NNNNNN 형식에서 숫자 ID 매칭
                        if doc_id.endswith(f"-{document_id:06d}"):
                            return Path(meta.get("source_path", "")).name
            except Exception:
                continue

    # FAISS 메타데이터에서 조회
    indexes_dir = DATA_DIR / "indexes" / "faiss"
    if indexes_dir.exists():
        for metadata_path in indexes_dir.glob("*_metadata.jsonl"):
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        meta = json.loads(line)
                        if str(meta.get("document_id", "")) == str(document_id):
                            return meta.get("file_name", "") or meta.get("filename", "")
            except Exception:
                continue

    return f"document_{document_id}.pptx"


def _parse_slides(text: str) -> dict[int, str]:
    """텍스트에서 슬라이드별 내용 분리. 슬라이드 번호 -> 텍스트 매핑."""
    slides: dict[int, str] = {}
    current_slide = 0
    current_content: list[str] = []

    # --- Slide N --- 패턴 (PPTX extractor 출력 형식)
    slide_pattern = re.compile(r"^---\s*Slide\s+(\d+)\s*---", re.IGNORECASE)
    # ===== [PAGE N] ===== 패턴 (페이지 인식 청킹 형식)
    page_pattern = re.compile(r"=====\s*\[PAGE\s+(\d+)\]\s*=====")

    for line in text.split("\n"):
        slide_match = slide_pattern.match(line.strip())
        page_match = page_pattern.match(line.strip())

        if slide_match or page_match:
            # 이전 슬라이드 저장
            if current_slide > 0 and current_content:
                slides[current_slide] = "\n".join(current_content)
            # 새 슬라이드 시작
            current_slide = int(slide_match.group(1) if slide_match else page_match.group(1))
            current_content = []
        else:
            current_content.append(line)

    # 마지막 슬라이드 저장
    if current_slide > 0 and current_content:
        slides[current_slide] = "\n".join(current_content)

    # 슬라이드 마커가 없으면 전체를 1페이지로 처리
    if not slides and text.strip():
        slides[1] = text

    return slides


def _search_keywords_in_slides(
    slides: dict[int, str],
    keywords: list[str],
) -> list[SlideMatch]:
    """슬라이드에서 키워드 검색."""
    results: list[SlideMatch] = []

    for slide_no, content in sorted(slides.items()):
        matched_keywords = []
        content_lower = content.lower()

        for keyword in keywords:
            keyword_lower = keyword.lower().strip()
            if not keyword_lower:
                continue
            # 정확한 단어 매칭 또는 부분 문자열 매칭
            if keyword_lower in content_lower:
                matched_keywords.append(keyword)

        if matched_keywords:
            # 미리보기 생성 (첫 번째 매칭 키워드 주변 텍스트)
            preview = _generate_preview(content, matched_keywords[0])
            results.append(SlideMatch(
                slide_no=slide_no,
                matched_keywords=matched_keywords,
                preview=preview,
                match_count=len(matched_keywords),
            ))

    # 매칭 키워드 수 기준 정렬 (많은 것이 먼저)
    results.sort(key=lambda x: (-x.match_count, x.slide_no))
    return results


def _generate_preview(content: str, keyword: str, context_chars: int = 100) -> str:
    """키워드 주변 텍스트 미리보기 생성."""
    content_lower = content.lower()
    keyword_lower = keyword.lower()
    pos = content_lower.find(keyword_lower)

    if pos < 0:
        # 매칭되지 않으면 첫 200자
        return content[:200].strip() + ("..." if len(content) > 200 else "")

    start = max(0, pos - context_chars)
    end = min(len(content), pos + len(keyword) + context_chars)

    preview = content[start:end].strip()
    if start > 0:
        preview = "..." + preview
    if end < len(content):
        preview = preview + "..."

    return preview


@router.post("/slides/search", response_model=SlideSearchResponse)
async def search_slides_by_keywords(request: SlideSearchRequest):
    """
    PPTX 문서에서 키워드가 포함된 슬라이드를 검색합니다.

    - document_id: 문서 ID
    - keywords: 검색할 키워드 목록 (예: ["AI Agent", "목표모델설계", "행정망"])
    - source_id: (선택) 소스 ID

    응답: 키워드가 매칭된 슬라이드 번호, 매칭된 키워드, 미리보기 텍스트
    """
    if not request.keywords:
        raise HTTPException(status_code=400, detail="키워드를 1개 이상 입력해주세요.")

    # 문서 텍스트 찾기
    text, _ = _find_document_text(request.document_id, request.source_id or "")
    if not text:
        raise HTTPException(
            status_code=404,
            detail=f"문서 ID {request.document_id}의 텍스트를 찾을 수 없습니다."
        )

    # 파일명 찾기
    file_name = _find_file_name(request.document_id, request.source_id or "")

    # 슬라이드 파싱
    slides = _parse_slides(text)
    if not slides:
        return SlideSearchResponse(
            success=True,
            document_id=request.document_id,
            file_name=file_name,
            total_slides=0,
            matched_slides=[],
            keywords_used=request.keywords,
            error="슬라이드 정보를 파싱할 수 없습니다.",
        )

    # 키워드 검색
    matched_slides = _search_keywords_in_slides(slides, request.keywords)

    return SlideSearchResponse(
        success=True,
        document_id=request.document_id,
        file_name=file_name,
        total_slides=len(slides),
        matched_slides=matched_slides,
        keywords_used=request.keywords,
    )


@router.get("/slides/search")
async def search_slides_get(
    document_id: int = Query(..., description="문서 ID"),
    keywords: str = Query(..., description="쉼표로 구분된 키워드 목록"),
    source_id: Optional[str] = Query(None, description="소스 ID (선택)"),
):
    """
    PPTX 문서에서 키워드가 포함된 슬라이드를 검색합니다. (GET 방식)

    - document_id: 문서 ID
    - keywords: 쉼표로 구분된 키워드 목록 (예: "AI Agent,목표모델설계,행정망")
    - source_id: (선택) 소스 ID
    """
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keyword_list:
        raise HTTPException(status_code=400, detail="키워드를 1개 이상 입력해주세요.")

    request = SlideSearchRequest(
        document_id=document_id,
        keywords=keyword_list,
        source_id=source_id,
    )
    return await search_slides_by_keywords(request)


@router.get("/documents/{document_id}/slides")
async def get_document_slides(
    document_id: int,
    source_id: Optional[str] = Query(None, description="소스 ID (선택)"),
):
    """
    PPTX 문서의 전체 슬라이드 목록을 반환합니다.

    - document_id: 문서 ID
    - source_id: (선택) 소스 ID
    """
    # 문서 텍스트 찾기
    text, _ = _find_document_text(document_id, source_id or "")
    if not text:
        raise HTTPException(
            status_code=404,
            detail=f"문서 ID {document_id}의 텍스트를 찾을 수 없습니다."
        )

    # 파일명 찾기
    file_name = _find_file_name(document_id, source_id or "")

    # 슬라이드 파싱
    slides = _parse_slides(text)

    # 슬라이드 요약 정보
    slides_info = []
    for slide_no, content in sorted(slides.items()):
        # 첫 줄을 제목으로 사용
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        title = lines[0][:100] if lines else f"슬라이드 {slide_no}"
        preview = content[:200].strip() + ("..." if len(content) > 200 else "")

        slides_info.append({
            "slide_no": slide_no,
            "title": title,
            "preview": preview,
            "char_count": len(content),
        })

    return {
        "success": True,
        "document_id": document_id,
        "file_name": file_name,
        "total_slides": len(slides),
        "slides": slides_info,
    }
