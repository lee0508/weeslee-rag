# RFP 문서에서 요구사항 테이블을 파싱하여 구조화된 청크로 변환하는 서비스
# -*- coding: utf-8 -*-
"""
RFP Requirement Parser Service

RFP 문서(특히 HWP→CSV 변환본)에서 요구사항 테이블을 파싱하여
요구사항 단위의 구조화된 청크를 생성한다.

기능.
1. RFP 섹션 자동 분류 (사업범위, 제안요청내용, 상세요구사항 등)
2. 요구사항 ID 패턴 인식 (CNR-001, SER-002 등)
3. 요구사항 단위 청킹 및 메타데이터 추출
4. 우선순위 기반 검색 부스팅 지원
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# RFP 표준 섹션 헤더 패턴 (공공 SW사업 제안요청서 표준 구조 기준)
SECTION_PATTERNS = [
    # (섹션 코드, 우선순위, 라벨, 헤더 정규식)
    ("business_scope", "high", "사업범위",
     re.compile(r'(주요\s*)?사업\s*범위|과업\s*(내용|범위)')),
    ("rfp_requirements", "high", "제안요청내용",
     re.compile(r'제안\s*요청\s*(내용|사항)|요구사항\s*총괄|상세\s*요구사항|요구사항\s*상세')),
    ("consulting_req", "high", "컨설팅요구사항",
     re.compile(r'컨설팅\s*요구사항')),
    ("security_req", "high", "보안요구사항",
     re.compile(r'보안\s*요구사항')),
    ("quality_req", "high", "품질요구사항",
     re.compile(r'품질\s*요구사항')),
    ("constraint_req", "high", "제약사항",
     re.compile(r'제약\s*사항')),
    ("pm_req", "high", "프로젝트관리요구사항",
     re.compile(r'프로젝트\s*관리\s*요구사항')),
    ("support_req", "high", "프로젝트지원요구사항",
     re.compile(r'프로젝트\s*지원\s*요구사항')),
    ("data_req", "high", "데이터요구사항",
     re.compile(r'데이터\s*요구사항')),
    ("overview", "medium", "사업개요",
     re.compile(r'사업\s*개요|추진\s*배경|사업\s*안내')),
    ("deliverables", "medium", "산출물",
     re.compile(r'(주요\s*)?산출물')),
    ("vendor_selection", "low", "사업자선정",
     re.compile(r'사업자\s*선정|입찰\s*방법|평가\s*방법')),
    ("proposal_guide", "low", "제안서작성안내",
     re.compile(r'제안서\s*작성\s*(안내|방법|지침)')),
    ("appendix", "low", "붙임",
     re.compile(r'붙임|별지|별첨')),
]

# 요구사항 ID 패턴
REQ_ID_PATTERN = re.compile(r'([A-Z]{2,4})[-–](\d{2,3})')

# 공공 SW 요구사항 분류 접두어 → 한글 카테고리 매핑
REQ_CATEGORY_MAP = {
    "CNR": "컨설팅",
    "CSR": "컨설팅",
    "CST": "컨설팅",
    "FUR": "기능",
    "PER": "성능",
    "SER": "보안",
    "COR": "제약사항",
    "QUR": "품질",
    "DAR": "데이터",
    "PMR": "프로젝트관리",
    "PSR": "프로젝트지원",
    "TER": "테스트",
    "SIR": "시스템장비",
    "ECR": "시스템운영",
}

# 우선순위별 검색 부스트 값
PRIORITY_BOOST = {
    "high": 1.30,
    "medium": 1.00,
    "low": 0.70,
}


@dataclass
class RfpRequirement:
    """파싱된 RFP 요구사항."""
    req_id: str                      # CNR-001
    req_category: str                # 컨설팅
    req_name: str                    # 현황분석
    definition: str = ""             # 정의
    detail: str = ""                 # 세부내용
    deliverable: str = ""            # 관련 산출물
    rfp_section: str = ""            # rfp_requirements
    section_label: str = ""          # 제안요청내용
    priority: str = "medium"         # high/medium/low
    source_block_no: int = 0         # 원본 블록 번호
    char_start: int = 0              # 원본 텍스트 시작 위치
    char_end: int = 0                # 원본 텍스트 끝 위치

    def to_chunk_text(self) -> str:
        """청크 텍스트 생성."""
        parts = [f"[{self.req_id}] {self.req_name}"]
        if self.definition:
            parts.append(f"정의: {self.definition}")
        if self.detail:
            parts.append(f"세부내용: {self.detail}")
        if self.deliverable:
            parts.append(f"산출물: {self.deliverable}")
        return "\n".join(parts)

    def to_metadata(self) -> Dict[str, Any]:
        """청크 메타데이터 생성."""
        return {
            "chunk_type": "requirement",
            "req_id": self.req_id,
            "req_category": self.req_category,
            "req_name": self.req_name,
            "priority": self.priority,
            "priority_boost": PRIORITY_BOOST.get(self.priority, 1.0),
            "section_code": self.rfp_section,
            "section_label": self.section_label,
            "has_deliverable": bool(self.deliverable),
        }


@dataclass
class RfpSection:
    """파싱된 RFP 섹션."""
    section_code: str
    section_label: str
    priority: str
    start_char: int
    end_char: int
    char_count: int
    requirement_count: int = 0


@dataclass
class RfpParseResult:
    """RFP 파싱 결과."""
    file_name: str
    total_chars: int
    sections: List[RfpSection] = field(default_factory=list)
    requirements: List[RfpRequirement] = field(default_factory=list)
    section_stats: Dict[str, int] = field(default_factory=dict)
    encoding_detected: str = "utf-8"


class RfpRequirementParser:
    """RFP 요구사항 파서."""

    def __init__(self):
        self.section_patterns = SECTION_PATTERNS
        self.req_id_pattern = REQ_ID_PATTERN

    def classify_section(self, header_text: str) -> Tuple[str, str, str]:
        """헤더 텍스트를 섹션 코드/우선순위/라벨로 분류."""
        for code, prio, label, pat in self.section_patterns:
            if pat.search(header_text):
                return code, prio, label
        return "body", "low", "본문"

    def split_blocks(self, text: str) -> List[Tuple[int, str, int, int]]:
        """
        ;[N] 마커 기준으로 블록 분리.
        반환: [(블록번호, 블록내용, 시작위치, 끝위치), ...]
        """
        parts = re.split(r';\[(\d+)\]', text)
        blocks = []
        pos = 0

        # parts[0]은 첫 마커 이전 서문
        if parts[0]:
            blocks.append((0, parts[0], 0, len(parts[0])))
            pos = len(parts[0])

        # 이후 (번호, 내용) 쌍 반복
        for i in range(1, len(parts), 2):
            num = int(parts[i])
            body = parts[i + 1] if i + 1 < len(parts) else ""
            marker_len = len(f";[{num}]")
            start = pos + marker_len
            end = start + len(body)
            blocks.append((num, body, start, end))
            pos = end

        return blocks

    def cell_rows(self, block_body: str) -> List[List[str]]:
        """블록 본문을 CSV 행(셀 리스트)으로 파싱."""
        rows = []
        for line in block_body.splitlines():
            line = line.strip()
            if not line:
                continue
            cells = re.findall(r'"([^"]*)"', line)
            if cells:
                rows.append(cells)
        return rows

    def parse_requirement_block(
        self,
        block_body: str,
        block_no: int,
        char_start: int,
        char_end: int,
        current_section: str,
        current_priority: str,
        current_label: str
    ) -> Optional[RfpRequirement]:
        """요구사항 테이블 블록에서 구조화 요구사항 추출."""
        # 요구사항 고유번호 테이블인지 확인
        if "요구사항 고유번호" not in block_body and "요구사항고유번호" not in block_body:
            return None

        # 요구사항 ID 추출
        m = self.req_id_pattern.search(block_body)
        if not m:
            return None

        req_id = f"{m.group(1)}-{m.group(2)}"
        prefix = m.group(1)

        # CSV 행 파싱
        rows = self.cell_rows(block_body)

        req = RfpRequirement(
            req_id=req_id,
            req_category=REQ_CATEGORY_MAP.get(prefix, prefix),
            req_name="",
            rfp_section=current_section,
            section_label=current_label,
            priority=current_priority,
            source_block_no=block_no,
            char_start=char_start,
            char_end=char_end,
        )

        # 각 행의 라벨 셀을 보고 값 셀을 매핑
        for cells in rows:
            if not cells:
                continue
            joined = " ".join(cells)

            if "요구사항 명칭" in joined or "요구사항명칭" in joined:
                req.req_name = cells[-1].strip()
            elif "정의" in joined and ("상세설명" in joined or "상세 설명" in joined):
                req.definition = cells[-1].strip()
            elif "세부내용" in joined or "세부 내용" in joined:
                req.detail = cells[-1].strip()
            elif "산출물" in joined and not req.deliverable:
                req.deliverable = cells[-1].strip()

        return req

    def parse_plain_text_requirements(
        self,
        text: str,
        current_section: str,
        current_priority: str,
        current_label: str
    ) -> List[RfpRequirement]:
        """일반 텍스트(TXT)에서 요구사항 추출."""
        requirements = []

        # 요구사항 ID로 시작하는 블록 찾기
        req_blocks = re.split(r'(?=\b[A-Z]{2,4}-\d{2,3}\b)', text)

        for block in req_blocks:
            if not block.strip():
                continue

            m = self.req_id_pattern.match(block.strip())
            if not m:
                continue

            req_id = f"{m.group(1)}-{m.group(2)}"
            prefix = m.group(1)

            # 요구사항명 추출 (ID 다음 줄 또는 같은 줄)
            lines = block.strip().split('\n')
            req_name = ""
            definition = ""
            detail = ""
            deliverable = ""

            for i, line in enumerate(lines):
                line = line.strip()
                if i == 0:
                    # 첫 줄에서 ID 이후 텍스트를 요구사항명으로
                    after_id = re.sub(r'^[A-Z]{2,4}-\d{2,3}\s*', '', line)
                    if after_id:
                        req_name = after_id
                elif "정의" in line or "목적" in line:
                    definition = re.sub(r'^[^\:：]+[\:：]\s*', '', line)
                elif "세부" in line or "내용" in line:
                    detail = re.sub(r'^[^\:：]+[\:：]\s*', '', line)
                elif "산출물" in line:
                    deliverable = re.sub(r'^[^\:：]+[\:：]\s*', '', line)

            if req_name or definition:
                req = RfpRequirement(
                    req_id=req_id,
                    req_category=REQ_CATEGORY_MAP.get(prefix, prefix),
                    req_name=req_name,
                    definition=definition,
                    detail=detail,
                    deliverable=deliverable,
                    rfp_section=current_section,
                    section_label=current_label,
                    priority=current_priority,
                )
                requirements.append(req)

        return requirements

    def detect_encoding(self, raw_bytes: bytes) -> str:
        """인코딩 자동 감지."""
        for enc in ('utf-8', 'cp949', 'euc-kr'):
            try:
                raw_bytes.decode(enc)
                return enc
            except UnicodeDecodeError:
                continue
        return 'cp949'

    def parse_file(self, file_path: str) -> RfpParseResult:
        """RFP 파일 파싱."""
        path = Path(file_path)
        file_name = path.name

        # 파일 읽기 및 인코딩 감지
        raw = path.read_bytes()
        encoding = self.detect_encoding(raw)

        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            text = raw.decode('cp949', errors='replace')
            encoding = 'cp949-fallback'

        return self.parse_text(text, file_name, encoding)

    def parse_text(
        self,
        text: str,
        file_name: str = "unknown",
        encoding: str = "utf-8"
    ) -> RfpParseResult:
        """RFP 텍스트 파싱."""
        result = RfpParseResult(
            file_name=file_name,
            total_chars=len(text),
            encoding_detected=encoding,
        )

        # CSV 형식인지 확인 (;[N] 블록 마커 존재)
        is_csv_format = bool(re.search(r';\[\d+\]', text))

        if is_csv_format:
            # CSV 블록 형식 파싱
            blocks = self.split_blocks(text)
            current_section = "front"
            current_priority = "low"
            current_label = "서문"

            for block_no, body, start, end in blocks:
                # 블록 시작 300자 안에서 섹션 헤더 탐지
                head = body[:300]
                code, prio, label = self.classify_section(head)

                if code != "body":
                    current_section = code
                    current_priority = prio
                    current_label = label

                # 요구사항 추출
                req = self.parse_requirement_block(
                    body, block_no, start, end,
                    current_section, current_priority, current_label
                )
                if req:
                    result.requirements.append(req)

                # 섹션 통계
                result.section_stats[current_section] = \
                    result.section_stats.get(current_section, 0) + len(body)
        else:
            # 일반 텍스트 형식 파싱
            # 섹션 헤더로 텍스트 분할
            lines = text.split('\n')
            current_section = "front"
            current_priority = "low"
            current_label = "서문"
            section_text = []

            for line in lines:
                code, prio, label = self.classify_section(line)
                if code != "body":
                    # 이전 섹션의 요구사항 추출
                    if section_text:
                        section_content = '\n'.join(section_text)
                        reqs = self.parse_plain_text_requirements(
                            section_content,
                            current_section,
                            current_priority,
                            current_label
                        )
                        result.requirements.extend(reqs)
                        result.section_stats[current_section] = \
                            result.section_stats.get(current_section, 0) + len(section_content)

                    current_section = code
                    current_priority = prio
                    current_label = label
                    section_text = [line]
                else:
                    section_text.append(line)

            # 마지막 섹션 처리
            if section_text:
                section_content = '\n'.join(section_text)
                reqs = self.parse_plain_text_requirements(
                    section_content,
                    current_section,
                    current_priority,
                    current_label
                )
                result.requirements.extend(reqs)
                result.section_stats[current_section] = \
                    result.section_stats.get(current_section, 0) + len(section_content)

        logger.info(
            f"RFP 파싱 완료: {file_name}, "
            f"요구사항 {len(result.requirements)}건, "
            f"섹션 {len(result.section_stats)}개"
        )

        return result

    def generate_chunks(
        self,
        parse_result: RfpParseResult,
        document_id: int,
        include_metadata: bool = True
    ) -> List[Dict[str, Any]]:
        """파싱 결과에서 청크 목록 생성."""
        chunks = []

        for i, req in enumerate(parse_result.requirements):
            chunk = {
                "chunk_id": f"{document_id}-req-{i:04d}",
                "document_id": document_id,
                "chunk_index": i,
                "text": req.to_chunk_text(),
                "char_count": len(req.to_chunk_text()),
            }

            if include_metadata:
                chunk["metadata"] = req.to_metadata()
                chunk["keywords"] = [
                    req.req_id,
                    req.req_category,
                    req.req_name,
                ] + (req.deliverable.split() if req.deliverable else [])

            chunks.append(chunk)

        return chunks


# 편의 함수
def parse_rfp_file(file_path: str) -> RfpParseResult:
    """RFP 파일 파싱 편의 함수."""
    parser = RfpRequirementParser()
    return parser.parse_file(file_path)


def parse_rfp_text(text: str, file_name: str = "unknown") -> RfpParseResult:
    """RFP 텍스트 파싱 편의 함수."""
    parser = RfpRequirementParser()
    return parser.parse_text(text, file_name)


def is_rfp_document(file_name: str, text: str = "") -> bool:
    """RFP 문서 여부 판별."""
    name_lower = file_name.lower()

    # 파일명 패턴
    if any(p in name_lower for p in ['rfp', '제안요청', '입찰공고']):
        return True

    # 텍스트 내용 패턴
    if text:
        rfp_indicators = [
            '제안요청서', '제안 요청서',
            '입찰공고', '입찰 공고',
            '사업자 선정', '제안서 제출',
            '요구사항 총괄', '상세 요구사항',
        ]
        return any(ind in text[:5000] for ind in rfp_indicators)

    return False
