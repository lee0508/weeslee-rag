# 문서 구조 추출 서비스 - 섹션, 페이지 정보 추출
# -*- coding: utf-8 -*-
"""
Document Structure Extractor Service

OCR/Parser 결과에서 문서 구조(섹션, 페이지)를 추출한다.

기능:
1. 페이지 경계 감지 및 페이지 번호 추출
2. 목차/섹션 구조 추출
3. 핵심 섹션 판별 (entity_mappings 기반)
4. 청크-페이지 매핑
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 헬퍼 함수 (순환 참조 방지를 위해 로컬 정의)
def generate_section_id(document_id: int, section_index: int) -> str:
    """섹션 ID 생성."""
    return f"{document_id}-section-{section_index:02d}"


def generate_page_id(document_id: int, page_no: int) -> str:
    """페이지 ID 생성."""
    return f"{document_id}-page-{page_no:04d}"


# entity_mappings.json 경로
_CONFIG_DIR = Path(__file__).resolve().parents[3] / "data" / "config"
_ENTITY_MAPPINGS_PATH = _CONFIG_DIR / "entity_mappings.json"
logger = logging.getLogger(__name__)


@dataclass
class ExtractedPage:
    """추출된 페이지 정보."""
    page_no: int
    slide_no: Optional[int] = None
    page_title: Optional[str] = None
    page_type: Optional[str] = None  # cover, toc, content, appendix
    text_content: str = ""
    char_count: int = 0
    has_table: bool = False
    has_image: bool = False
    has_chart: bool = False
    start_char: int = 0
    end_char: int = 0


@dataclass
class ExtractedSection:
    """추출된 섹션 정보."""
    section_index: int
    section_title: str
    section_type: Optional[str] = None  # tech_func, proj_mgmt 등
    section_label: Optional[str] = None  # 기술및기능, 프로젝트관리 등
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    page_count: int = 0
    is_key_section: bool = False
    extraction_confidence: float = 0.0
    extraction_method: str = "heading"  # toc, heading, folder


@dataclass
class DocumentStructure:
    """문서 구조 추출 결과."""
    document_id: int
    total_pages: int
    pages: List[ExtractedPage] = field(default_factory=list)
    sections: List[ExtractedSection] = field(default_factory=list)
    toc_detected: bool = False
    extraction_method: str = "auto"


class DocumentStructureExtractor:
    """문서 구조 추출기."""

    # 페이지 구분 패턴
    PAGE_BREAK_PATTERNS = [
        re.compile(r'\n-{3,}\s*페이지?\s*(\d+)\s*-{3,}\n', re.IGNORECASE),
        re.compile(r'\n={3,}\s*(\d+)\s*={3,}\n'),
        re.compile(r'\[Page\s*(\d+)\]', re.IGNORECASE),
        re.compile(r'--- Page (\d+) ---', re.IGNORECASE),
        re.compile(r'\n\s*(\d+)\s*페이지\s*\n'),
        re.compile(r'\f'),  # Form feed (PDF 페이지 구분)
    ]

    # 슬라이드 번호 패턴 (PPT)
    SLIDE_PATTERNS = [
        re.compile(r'슬라이드\s*(\d+)', re.IGNORECASE),
        re.compile(r'Slide\s*(\d+)', re.IGNORECASE),
        re.compile(r'\[(\d+)/\d+\]'),  # [1/50] 형식
    ]

    # 목차 패턴
    TOC_PATTERNS = [
        re.compile(r'^목\s*차$', re.MULTILINE),
        re.compile(r'^table\s+of\s+contents?$', re.IGNORECASE | re.MULTILINE),
        re.compile(r'^contents?$', re.IGNORECASE | re.MULTILINE),
        re.compile(r'^차\s*례$', re.MULTILINE),
    ]

    # 섹션 헤딩 패턴
    HEADING_PATTERNS = [
        # 숫자 기반 (1. 제목, 1.1 제목)
        re.compile(r'^(\d+\.(?:\d+\.)*)\s*(.{2,80})$', re.MULTILINE),
        # 로마 숫자 (I. 제목)
        re.compile(r'^([IVX]+\.)\s*(.{2,80})$', re.MULTILINE),
        # 한글 번호 (가. 제목)
        re.compile(r'^([가-힣]\.)\s*(.{2,80})$', re.MULTILINE),
        # 대괄호 (【제목】)
        re.compile(r'^【(.{2,50})】$', re.MULTILINE),
        # 볼드 마커
        re.compile(r'^\*\*(.{2,80})\*\*$', re.MULTILINE),
    ]

    # 페이지 유형 판별 패턴
    COVER_PATTERNS = [
        re.compile(r'제안서|proposal|표지|cover', re.IGNORECASE),
    ]
    APPENDIX_PATTERNS = [
        re.compile(r'부록|appendix|별첨|참고자료', re.IGNORECASE),
    ]

    def __init__(self, entity_mappings_path: Optional[Path] = None):
        """
        Args:
            entity_mappings_path: entity_mappings.json 경로
        """
        self._mappings_path = entity_mappings_path or _ENTITY_MAPPINGS_PATH
        self._entity_mappings: Optional[Dict] = None
        self._section_mappings: Dict[str, str] = {}  # 섹션명 -> 섹션유형

    def _load_entity_mappings(self) -> Dict:
        """entity_mappings.json 로드."""
        if self._entity_mappings is not None:
            return self._entity_mappings

        if self._mappings_path.exists():
            try:
                self._entity_mappings = json.loads(
                    self._mappings_path.read_text(encoding="utf-8")
                )
                # 섹션 매핑 빌드
                self._build_section_mappings()
            except Exception as exc:
                logger.warning("entity_mappings load failed: %s", exc)
                self._entity_mappings = {}
        else:
            logger.warning("entity_mappings missing: %s", self._mappings_path)
            self._entity_mappings = {}

        return self._entity_mappings

    def _build_section_mappings(self) -> None:
        """섹션 매핑 빌드."""
        mappings = self._entity_mappings or {}
        sections = mappings.get("document_sections", {})

        for category, section_list in sections.items():
            for section_info in section_list:
                if isinstance(section_info, dict):
                    name = section_info.get("name", "")
                    aliases = section_info.get("aliases", [])
                    section_type = section_info.get("type", category)

                    self._section_mappings[name.lower()] = section_type
                    for alias in aliases:
                        self._section_mappings[alias.lower()] = section_type
                elif isinstance(section_info, str):
                    self._section_mappings[section_info.lower()] = category

    def _extract_pages_from_text(self, text: str) -> List[ExtractedPage]:
        """텍스트에서 페이지 추출."""
        pages: List[ExtractedPage] = []

        page_breaks: List[Tuple[int, int, int]] = []  # (start, end, page_no)

        for pattern in self.PAGE_BREAK_PATTERNS:
            for match in pattern.finditer(text):
                try:
                    page_no = int(match.group(1)) if match.lastindex else 0
                except (ValueError, IndexError):
                    page_no = 0
                page_breaks.append((match.start(), match.end(), page_no))

        if not page_breaks:
            # 페이지 구분자가 없으면 전체를 1페이지로 처리
            pages.append(ExtractedPage(
                page_no=1,
                text_content=text,
                char_count=len(text),
                start_char=0,
                end_char=len(text),
            ))
            return pages

        page_breaks.sort(key=lambda x: (x[0], x[1]))

        first_start = page_breaks[0][0]
        if first_start > 0:
            lead_text = text[:first_start].strip()
            if lead_text:
                pages.append(ExtractedPage(
                    page_no=1,
                    text_content=lead_text,
                    char_count=len(lead_text),
                    start_char=0,
                    end_char=first_start,
                ))

        inferred_page_no = pages[-1].page_no if pages else 0
        for i, (start, end, marker_page_no) in enumerate(page_breaks):
            next_start = page_breaks[i + 1][0] if i + 1 < len(page_breaks) else len(text)
            page_text = text[end:next_start].strip()
            if not page_text:
                continue
            actual_page_no = marker_page_no if marker_page_no > 0 else inferred_page_no + 1
            actual_page_no = max(actual_page_no, inferred_page_no + 1)
            pages.append(ExtractedPage(
                page_no=actual_page_no,
                text_content=page_text,
                char_count=len(page_text),
                start_char=end,
                end_char=next_start,
            ))
            inferred_page_no = actual_page_no

        return pages

    def _extract_page_title(self, page_text: str) -> Optional[str]:
        """페이지 제목 추출."""
        lines = page_text.strip().split('\n')[:5]

        for line in lines:
            line = line.strip()
            if 4 <= len(line) <= 120:
                # 제목으로 보이는 라인
                if not re.match(r'^[\d\.\-\s]+$', line) and "...." not in line and "|" not in line:
                    return line

        return None

    def _detect_page_type(self, page_text: str, page_no: int) -> str:
        """페이지 유형 감지."""
        text_lower = page_text.lower()

        if page_no == 1:
            for pattern in self.COVER_PATTERNS:
                if pattern.search(text_lower):
                    return "cover"

        for pattern in self.APPENDIX_PATTERNS:
            if pattern.search(text_lower):
                return "appendix"

        for pattern in self.TOC_PATTERNS:
            if pattern.search(text_lower):
                return "toc"

        return "content"

    def _detect_content_features(self, page_text: str) -> Tuple[bool, bool, bool]:
        """콘텐츠 특징 감지 (표, 이미지, 차트)."""
        has_table = bool(
            re.search(r'\|.+\|.+\|', page_text)
            or re.search(r'^\s*\S+\s{2,}\S+\s{2,}\S+', page_text, re.MULTILINE)
            or re.search(r'^[\-\+=]{4,}$', page_text, re.MULTILINE)
        )
        has_image = bool(re.search(r'\[이미지\]|\[그림\]|\[Image\]|\[Figure\]', page_text, re.IGNORECASE))
        has_chart = bool(re.search(r'\[차트\]|\[Chart\]|\[그래프\]|\[Graph\]', page_text, re.IGNORECASE))

        return has_table, has_image, has_chart

    def _extract_sections_from_text(self, text: str) -> List[ExtractedSection]:
        """텍스트에서 섹션 추출."""
        self._load_entity_mappings()
        sections: List[ExtractedSection] = []

        # 헤딩 패턴으로 섹션 추출
        headings: List[Tuple[int, str, str]] = []  # (위치, 번호, 제목)

        for pattern in self.HEADING_PATTERNS:
            for match in pattern.finditer(text):
                if match.lastindex and match.lastindex >= 2:
                    number = match.group(1)
                    title = match.group(2).strip()
                else:
                    number = ""
                    title = match.group(1).strip() if match.lastindex else match.group(0).strip()

                # 최상위 섹션만 (1., 2. 등)
                if number and re.match(r'^\d+\.$', number):
                    headings.append((match.start(), number, title))

        # 섹션 생성
        for i, (pos, number, title) in enumerate(headings):
            section_type = self._section_mappings.get(title.lower())
            is_key = section_type is not None

            sections.append(ExtractedSection(
                section_index=i,
                section_title=f"{number} {title}",
                section_type=section_type,
                section_label=title,
                is_key_section=is_key,
                extraction_confidence=0.8 if is_key else 0.6,
                extraction_method="heading",
            ))

        return sections

    def _extract_sections_from_folder(
        self,
        folder_path: str,
        document_category: Optional[str] = None
    ) -> List[ExtractedSection]:
        """폴더 구조에서 섹션 추출."""
        self._load_entity_mappings()
        sections: List[ExtractedSection] = []

        # 폴더 경로에서 섹션 추출
        path_parts = Path(folder_path).parts

        for i, part in enumerate(path_parts):
            section_type = self._section_mappings.get(part.lower())
            if section_type:
                sections.append(ExtractedSection(
                    section_index=len(sections),
                    section_title=part,
                    section_type=section_type,
                    section_label=part,
                    is_key_section=True,
                    extraction_confidence=0.9,
                    extraction_method="folder",
                ))

        return sections

    def extract_structure(
        self,
        text: str,
        document_id: int,
        folder_path: Optional[str] = None,
        document_category: Optional[str] = None,
        file_type: Optional[str] = None,
    ) -> DocumentStructure:
        """
        문서 구조 추출.

        Args:
            text: OCR/Parser 결과 텍스트
            document_id: 문서 ID
            folder_path: 문서 폴더 경로 (섹션 추출용)
            document_category: 문서 분류
            file_type: 파일 유형 (pdf, pptx 등)

        Returns:
            DocumentStructure 객체
        """
        # 1. 페이지 추출
        pages = self._extract_pages_from_text(text)

        # 2. 페이지 정보 보강
        for page in pages:
            page.page_title = self._extract_page_title(page.text_content)
            page.page_type = self._detect_page_type(page.text_content, page.page_no)
            has_table, has_image, has_chart = self._detect_content_features(page.text_content)
            page.has_table = has_table
            page.has_image = has_image
            page.has_chart = has_chart

            # PPT인 경우 슬라이드 번호 설정
            if file_type in ("ppt", "pptx"):
                page.slide_no = page.page_no

        # 3. 섹션 추출
        sections_from_text = self._extract_sections_from_text(text)
        sections_from_folder = []
        if folder_path:
            sections_from_folder = self._extract_sections_from_folder(
                folder_path, document_category
            )

        # 섹션 병합 (폴더 기반 우선)
        sections = sections_from_folder if sections_from_folder else sections_from_text

        # 4. 목차 감지
        toc_detected = any(p.page_type == "toc" for p in pages)

        return DocumentStructure(
            document_id=document_id,
            total_pages=len(pages),
            pages=pages,
            sections=sections,
            toc_detected=toc_detected,
            extraction_method="folder" if sections_from_folder else "heading",
        )

    def map_chunks_to_pages(
        self,
        chunks: List[Dict[str, Any]],
        pages: List[ExtractedPage],
    ) -> List[Dict[str, Any]]:
        """
        청크를 페이지에 매핑.

        Args:
            chunks: 청크 목록 (char_count, start_char 등 포함)
            pages: 추출된 페이지 목록

        Returns:
            page_no가 추가된 청크 목록
        """
        if not pages:
            return chunks

        result = []
        for chunk in chunks:
            chunk_copy = dict(chunk)
            chunk_start = int(chunk.get("start_char", 0) or 0)
            chunk_end = int(chunk.get("end_char", chunk_start) or chunk_start)
            metadata = chunk.get("metadata") or {}

            explicit_page_no = (
                chunk.get("page_no")
                or chunk.get("page_number")
                or metadata.get("page_no")
                or metadata.get("page_number")
                or metadata.get("slide_no")
            )
            if explicit_page_no is not None:
                try:
                    chunk_copy["page_no"] = int(explicit_page_no)
                    chunk_copy["slide_no"] = int(metadata.get("slide_no") or chunk_copy["page_no"])
                    result.append(chunk_copy)
                    continue
                except Exception:
                    pass

            chunk_mid = chunk_start + max(0, chunk_end - chunk_start) // 2
            for page in pages:
                if page.start_char <= chunk_mid < page.end_char:
                    chunk_copy["page_no"] = page.page_no
                    chunk_copy["slide_no"] = page.slide_no
                    break
            else:
                if pages:
                    nearest = min(
                        pages,
                        key=lambda page: min(
                            abs(chunk_start - page.start_char),
                            abs(chunk_mid - page.end_char),
                        ),
                    )
                    chunk_copy["page_no"] = nearest.page_no
                    chunk_copy["slide_no"] = nearest.slide_no

            result.append(chunk_copy)

        return result


# 싱글톤 인스턴스
_extractor: Optional[DocumentStructureExtractor] = None


def get_document_structure_extractor() -> DocumentStructureExtractor:
    """DocumentStructureExtractor 싱글톤 반환."""
    global _extractor
    if _extractor is None:
        _extractor = DocumentStructureExtractor()
    return _extractor
