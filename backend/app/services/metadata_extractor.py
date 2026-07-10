# -*- coding: utf-8 -*-
"""
Document Metadata Extraction Service
Uses LLM to extract title, summary, keywords, and category from documents
"""
import json
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

from app.services.ollama import ollama_service


@dataclass
class DocumentMetadata:
    """Extracted document metadata"""
    title: str
    summary: str
    keywords: List[str]
    category: str
    language: str
    document_type: str
    organization: Optional[str] = None
    project_name: Optional[str] = None
    year: Optional[int] = None
    confidence_score: float = 0.0
    extracted_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


class MetadataExtractorService:
    """Service for extracting metadata from documents using LLM"""

    # Document categories for Korean consulting documents
    CATEGORIES = [
        "ISP",           # 정보화전략계획
        "ISMP",          # 정보시스템마스터플랜
        "BPR",           # 업무재설계
        "EA",            # 전사아키텍처
        "ODA",           # 공적개발원조
        "정책연구",       # Policy research
        "제안서",         # Proposal
        "보고서",         # Report
        "사업계획",       # Business plan
        "기타"           # Other
    ]

    # Document types
    DOCUMENT_TYPES = [
        "제안서",         # Proposal
        "착수보고서",     # Kick-off report
        "중간보고서",     # Interim report
        "최종보고서",     # Final report
        "산출물",         # Deliverable
        "회의록",         # Meeting minutes
        "기타"           # Other
    ]

    METADATA_EXTRACTION_PROMPT = """당신은 문서 분석 전문가입니다. 아래 문서 내용을 분석하여 메타데이터를 JSON 형식으로 추출해주세요.

문서 내용:
{content}

다음 정보를 추출해주세요:
1. title: 문서의 제목 (문서 내용에서 추론)
2. summary: 문서 요약 (2-3문장, 핵심 내용 포함)
3. keywords: 주요 키워드 (5-10개, 배열 형식)
4. category: 문서 카테고리 (다음 중 하나: {categories})
5. document_type: 문서 유형 (다음 중 하나: {document_types})
6. organization: 관련 기관/조직명 (있으면 추출, 없으면 null)
7. project_name: 프로젝트명 (있으면 추출, 없으면 null)
8. year: 관련 연도 (있으면 추출, 없으면 null)
9. language: 주요 언어 ("ko" 또는 "en")
10. confidence_score: 추출 신뢰도 (0.0 ~ 1.0)

반드시 아래 JSON 형식으로만 응답하세요:
```json
{{
    "title": "문서 제목",
    "summary": "문서 요약",
    "keywords": ["키워드1", "키워드2", "키워드3"],
    "category": "카테고리",
    "document_type": "문서유형",
    "organization": "기관명 또는 null",
    "project_name": "프로젝트명 또는 null",
    "year": 2024,
    "language": "ko",
    "confidence_score": 0.85
}}
```
"""

    TITLE_EXTRACTION_PROMPT = """문서의 첫 부분을 보고 문서 제목을 추출해주세요.

문서 시작 부분:
{content}

문서 제목만 출력하세요 (따옴표나 설명 없이):"""

    SUMMARY_PROMPT = """아래 문서 내용을 2-3문장으로 요약해주세요.

문서 내용:
{content}

요약:"""

    KEYWORD_PROMPT = """아래 문서에서 핵심 키워드 5-10개를 추출해주세요.

문서 내용:
{content}

키워드를 쉼표로 구분하여 나열해주세요:"""

    def __init__(self, max_content_length: int = 8000):
        """
        Initialize metadata extractor

        Args:
            max_content_length: Maximum content length to send to LLM
        """
        self.max_content_length = max_content_length

    def _truncate_content(self, content: str) -> str:
        """Truncate content to fit within LLM context"""
        if len(content) <= self.max_content_length:
            return content

        # Take beginning and end portions
        half = self.max_content_length // 2
        return content[:half] + "\n\n...[중략]...\n\n" + content[-half:]

    def _clean_json_response(self, response: str) -> str:
        """Extract JSON from LLM response"""
        # Try to find JSON block
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            return json_match.group(1).strip()

        # Try to find raw JSON
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json_match.group(0).strip()

        return response.strip()

    def _apply_document_hints(self, metadata: DocumentMetadata, content: str, filename: Optional[str]) -> DocumentMetadata:
        """Apply deterministic overrides for HWPX RFP-style documents."""
        lines = [line.strip().strip("<>") for line in content.splitlines() if line.strip()]

        title_hint = None
        for line in lines[:30]:
            candidate = re.sub(r"\s+", " ", line).strip()
            if len(candidate) < 8 or len(candidate) > 120:
                continue
            if "제안요청서" in candidate or "RFP" in candidate or "ISMP" in candidate:
                title_hint = candidate
                break
        if title_hint:
            metadata.title = title_hint

        lowered = content.lower()
        if "제안요청서" in content or "rfp" in lowered:
            metadata.category = "RFP"
            metadata.document_type = "RFP"
        elif "제안서" in content or "proposal" in lowered:
            metadata.document_type = "제안서"

        extra_terms = [
            "RFP",
            "제안요청서",
            "ISMP",
            "차세대",
            "업무시스템",
            "프로젝트",
            "일정관리",
            "보안요구사항",
            "산출물",
            "지적재산권",
        ]
        for term in extra_terms:
            if term in content and term not in metadata.keywords:
                metadata.keywords.append(term)
        metadata.keywords = metadata.keywords[:10]

        if metadata.confidence_score < 0.6:
            metadata.confidence_score = 0.6
        return metadata

    def _extract_title_hint(self, content: str, filename: Optional[str] = None) -> Optional[str]:
        """Extract a reliable title hint from document text."""
        lines = [line.strip().strip("<>") for line in content.splitlines() if line.strip()]
        for line in lines[:30]:
            candidate = re.sub(r"\s+", " ", line).strip()
            if len(candidate) < 8 or len(candidate) > 120:
                continue
            if "제안요청서" in candidate or "RFP" in candidate or "ISMP" in candidate:
                return candidate
        if filename:
            return filename.rsplit(".", 1)[0]
        return None

    def _apply_rules(self, metadata: DocumentMetadata, content: str, filename: Optional[str]) -> DocumentMetadata:
        """Apply deterministic overrides for strong RFP/proposal signals."""
        title_hint = self._extract_title_hint(content, filename)
        if title_hint and ("제안요청서" in title_hint or "RFP" in title_hint or "ISMP" in title_hint):
            metadata.title = title_hint

        text = content.lower()
        if "제안요청서" in content or "rfp" in text:
            metadata.category = "RFP"
            metadata.document_type = "RFP"
        elif "제안서" in content or "proposal" in text:
            metadata.document_type = "제안서"

        extra_terms = [
            "RFP",
            "제안요청서",
            "ISMP",
            "차세대",
            "업무시스템",
            "프로젝트",
            "일정관리",
            "보안요구사항",
            "산출물",
            "지적재산권",
        ]
        for term in extra_terms:
            if term in content and term not in metadata.keywords:
                metadata.keywords.append(term)
        metadata.keywords = metadata.keywords[:10]

        if metadata.confidence_score < 0.6 and (metadata.title != (filename or "")):
            metadata.confidence_score = 0.6
        return metadata

    async def extract_metadata(
        self,
        content: str,
        filename: Optional[str] = None
    ) -> DocumentMetadata:
        """
        Extract metadata from document content using LLM

        Args:
            content: Document text content
            filename: Optional filename for hints

        Returns:
            DocumentMetadata object
        """
        truncated_content = self._truncate_content(content)

        prompt = self.METADATA_EXTRACTION_PROMPT.format(
            content=truncated_content,
            categories=", ".join(self.CATEGORIES),
            document_types=", ".join(self.DOCUMENT_TYPES)
        )

        try:
            response = await ollama_service.generate(
                prompt=prompt,
                temperature=0.3,  # Lower temperature for more consistent extraction
                max_tokens=2000
            )

            json_str = self._clean_json_response(response)
            data = json.loads(json_str)

            # Validate and clean extracted data
            metadata = DocumentMetadata(
                title=data.get('title', filename or '제목 없음'),
                summary=data.get('summary', ''),
                keywords=data.get('keywords', [])[:10],  # Limit to 10 keywords
                category=data.get('category', '기타'),
                document_type=data.get('document_type', '기타'),
                organization=data.get('organization'),
                project_name=data.get('project_name'),
                year=data.get('year'),
                language=data.get('language', 'ko'),
                confidence_score=min(1.0, max(0.0, float(data.get('confidence_score', 0.5)))),
                extracted_at=datetime.utcnow().isoformat()
            )

            metadata = self._apply_document_hints(metadata, truncated_content, filename)

            # Validate category
            if metadata.category not in self.CATEGORIES and metadata.category != "RFP":
                metadata.category = '기타'

            # Validate document type
            if metadata.document_type not in self.DOCUMENT_TYPES and metadata.document_type != "RFP":
                metadata.document_type = '기타'

            return metadata

        except json.JSONDecodeError:
            # Fall back to simpler extraction methods
            return await self._fallback_extraction(content, filename)
        except Exception as e:
            print(f"Metadata extraction error: {e}")
            return self._create_default_metadata(filename)

    async def _fallback_extraction(
        self,
        content: str,
        filename: Optional[str] = None
    ) -> DocumentMetadata:
        """Fallback extraction using simpler prompts"""
        truncated = self._truncate_content(content)

        # Extract title
        title = filename or "제목 없음"
        try:
            title_response = await ollama_service.generate(
                prompt=self.TITLE_EXTRACTION_PROMPT.format(content=truncated[:2000]),
                temperature=0.1,
                max_tokens=100
            )
            title = title_response.strip() or title
        except Exception:
            pass

        # Extract summary
        summary = ""
        try:
            summary_response = await ollama_service.generate(
                prompt=self.SUMMARY_PROMPT.format(content=truncated),
                temperature=0.3,
                max_tokens=300
            )
            summary = summary_response.strip()
        except Exception:
            pass

        # Extract keywords
        keywords = []
        try:
            keyword_response = await ollama_service.generate(
                prompt=self.KEYWORD_PROMPT.format(content=truncated),
                temperature=0.3,
                max_tokens=200
            )
            keywords = [k.strip() for k in keyword_response.split(',')][:10]
        except Exception:
            pass

        # Infer category from filename or content
        category = self._infer_category(filename, content)

        return DocumentMetadata(
            title=title,
            summary=summary,
            keywords=keywords,
            category=category,
            document_type='기타',
            language='ko',
            confidence_score=0.5,
            extracted_at=datetime.utcnow().isoformat()
        )

    def _infer_category(
        self,
        filename: Optional[str],
        content: str
    ) -> str:
        """Infer category from filename and content"""
        text_to_check = (filename or "") + " " + content[:2000]
        text_lower = text_to_check.lower()

        # Check for category keywords
        category_keywords = {
            'ISP': ['isp', '정보화전략계획', '정보화전략', 'information strategy'],
            'ISMP': ['ismp', '정보시스템마스터플랜', '마스터플랜', 'master plan'],
            'BPR': ['bpr', '업무재설계', '프로세스재설계', 'business process'],
            'EA': ['ea', '전사아키텍처', 'enterprise architecture'],
            'ODA': ['oda', '공적개발원조', '개발협력', 'official development'],
            '정책연구': ['정책연구', '정책', 'policy', '연구용역'],
            '제안서': ['제안서', '제안요청', 'rfp', 'proposal'],
        }

        for category, keywords in category_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return category

        return '기타'

    def _create_default_metadata(
        self,
        filename: Optional[str] = None
    ) -> DocumentMetadata:
        """Create default metadata when extraction fails"""
        return DocumentMetadata(
            title=filename or "제목 없음",
            summary="메타데이터 추출 실패",
            keywords=[],
            category='기타',
            document_type='기타',
            language='ko',
            confidence_score=0.0,
            extracted_at=datetime.utcnow().isoformat()
        )

    async def extract_title(self, content: str) -> str:
        """Extract just the title from document"""
        prompt = self.TITLE_EXTRACTION_PROMPT.format(content=content[:2000])

        try:
            response = await ollama_service.generate(
                prompt=prompt,
                temperature=0.1,
                max_tokens=100
            )
            return response.strip()
        except Exception:
            return ""

    async def extract_summary(self, content: str, max_length: int = 500) -> str:
        """Extract summary from document"""
        truncated = self._truncate_content(content)
        prompt = self.SUMMARY_PROMPT.format(content=truncated)

        try:
            response = await ollama_service.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=max_length
            )
            return response.strip()
        except Exception:
            return ""

    async def extract_keywords(self, content: str, max_keywords: int = 10) -> List[str]:
        """Extract keywords from document"""
        truncated = self._truncate_content(content)
        prompt = self.KEYWORD_PROMPT.format(content=truncated)

        try:
            response = await ollama_service.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=200
            )
            keywords = [k.strip() for k in response.split(',')]
            return keywords[:max_keywords]
        except Exception:
            return []


# Singleton instance
metadata_extractor_service = MetadataExtractorService()


def get_metadata_extractor() -> MetadataExtractorService:
    """Dependency to get metadata extractor service"""
    return metadata_extractor_service


# ── Rule-Based Extractor (ocr_* 필드 전용) ─────────────────────────────────

# 분석 대상 텍스트 길이 제한
# HWP/HWPX 제안요청서는 발주기관 표기가 뒤쪽에 나오는 경우가 있어 범위를 조금 넓힌다.
_ANALYSIS_LIMIT = 20000


class RuleBasedMetadataExtractor:
    """
    OCR 추출 텍스트에서 정규식 패턴으로 메타데이터를 추출한다.
    LLM 없이 동작하며 Step 4 파싱 완료 직후 ocr_* 필드를 채운다.
    신뢰도가 낮은 항목은 이후 LLM 보완 대상이 된다.
    """

    # [2026-07-10] 목차/섹션명 블록리스트 - project_name 오탐 방지
    # OCR 텍스트에서 "개요 4", "범위 1" 같은 목차 항목이 사업명으로 잘못 추출되는 문제 해결
    _PROJECT_NAME_BLOCKLIST_PATTERNS = re.compile(
        r'^(?:'
        r'개요|범위|배경|목차|목표|필요성|기대효과|추진방향|추진체계|추진전략|'
        r'일정|예산|조직|인력|방법론|산출물|보안|품질|위험|이슈|'
        r'현황|분석|설계|구축|운영|유지보수|'
        r'제\s*\d+\s*장|제\s*\d+\s*절|제\s*\d+\s*조|'
        r'\d+\.\s*개요|\d+\.\s*범위|\d+\.\s*배경|\d+\.\s*목차|'
        r'[IVX]+\.\s|[①②③④⑤⑥⑦⑧⑨⑩]|'
        r'부록|별첨|참고|첨부'
        r')'
        r'(?:\s*\d+)?$',  # "개요 4", "범위 1" 형태 매칭
        re.IGNORECASE
    )

    # 너무 짧거나 숫자로만 구성된 사업명 필터링
    _PROJECT_NAME_MIN_LENGTH = 8  # 최소 8자 이상 (의미 있는 사업명)

    _ORG_NAME_PATTERN = re.compile(
        r"("
        r"[가-힣A-Za-z0-9·&-]{2,20}"
        r"(?:\s+[가-힣A-Za-z0-9·&-]{2,20}){0,2}"
        r"(?:부|청|처|공사|공단|연구원|연구소|재단|위원회|센터|병원|대학교|대학|학교|진흥원|협회|본부|관리원|교육원|평가원)"
        r")(?=[은는이가의와과을를에로도및,.:;)\]\\s]|$)"
    )
    _ORG_SUFFIXES = (
        "부", "청", "처", "공사", "공단", "연구원", "연구소", "재단", "위원회",
        "센터", "병원", "대학교", "대학", "학교", "진흥원", "협회", "본부",
        "관리원", "교육원", "평가원",
    )

    def _clean_line_value(self, value: str, max_len: int = 200) -> Optional[str]:
        value = re.sub(r"^[\s\-•·□ㅇ○▷▶()]+", "", str(value or ""))
        value = re.sub(r"\s+", " ", value).strip(" :：|/\t()[]{}<>")
        if not value:
            return None
        return value[:max_len]

    def _extract_labeled_value(self, text: str, labels: list[str], min_len: int = 3, max_len: int = 100) -> Optional[str]:
        label_group = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{label_group})\s*[:：]?\s*([^\n\r]{{{min_len},{max_len}}})", text)
        if not match:
            return None
        return self._clean_line_value(match.group(1), max_len=max_len)

    def _extract_org_candidate(self, value: str) -> Optional[str]:
        cleaned = self._clean_line_value(value)
        if not cleaned:
            return None
        cleaned = re.sub(r"^(?:차세대|통합|지능형|디지털|스마트|클라우드)\s+", "", cleaned)

        for candidate in self._extract_org_candidates_from_line(cleaned):
            return candidate
        return None

    def _strip_trailing_particle(self, token: str) -> str:
        return re.sub(r"(은|는|이|가|의|와|과|을|를|에|로|도|만|부터|까지)$", "", token)

    def _extract_org_candidates_from_line(self, line: str) -> list[str]:
        normalized = re.sub(r"[\"'“”‘’`·•□ㅇ○▷▶,:;<>\\[\\]{}()/]", " ", line or "")
        raw_tokens = [self._clean_line_value(tok, max_len=40) for tok in normalized.split()]
        tokens = [tok for tok in raw_tokens if tok]
        candidates: list[str] = []

        for start in range(len(tokens)):
            for width in range(1, 4):
                part = [self._strip_trailing_particle(tok) for tok in tokens[start:start + width]]
                if len(part) != width:
                    continue
                candidate = self._clean_line_value(" ".join(part), max_len=80)
                if not candidate:
                    continue
                if self._is_org_shape(candidate):
                    candidates.append(candidate)

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped

    def _is_org_shape(self, candidate: str) -> bool:
        parts = [part for part in (candidate or "").split() if part]
        if not 1 <= len(parts) <= 3:
            return False
        if not candidate.endswith(self._ORG_SUFFIXES):
            return False
        for part in parts:
            if not re.fullmatch(r"[가-힣A-Za-z0-9·&-]{2,20}", part):
                return False
        return True

    def _is_valid_project_name(self, name: Optional[str]) -> bool:
        """
        [2026-07-10] 사업명 유효성 검증.
        목차명("개요 4", "범위 1")이나 너무 짧은 값을 필터링한다.
        """
        if not name:
            return False

        # 공백 제거 후 길이 검사
        stripped = name.strip()
        if len(stripped) < self._PROJECT_NAME_MIN_LENGTH:
            return False

        # 숫자로만 구성된 경우 제외
        if stripped.isdigit():
            return False

        # 목차/섹션명 패턴 검사
        if self._PROJECT_NAME_BLOCKLIST_PATTERNS.match(stripped):
            return False

        # 숫자 + 공백 + 한글 1~2자 패턴 ("4 개요", "1 범위" 등) 제외
        if re.match(r'^\d+\s+[가-힣]{1,4}$', stripped):
            return False

        # 한글 1~4자 + 공백 + 숫자 패턴 ("개요 4", "범위 1" 등) 제외
        if re.match(r'^[가-힣]{1,4}\s+\d+$', stripped):
            return False

        return True

    def extract_project_name(self, text: str) -> tuple[Optional[str], float]:
        """레이블 기반 → 키워드 패턴 순으로 사업명을 추출한다."""
        head = text[:_ANALYSIS_LIMIT]

        labeled_name = self._extract_labeled_value(
            head,
            ["사업명", "용역사업명", "용역명", "과업명", "프로젝트명", "사업", "과업"],
            min_len=5,
            max_len=100,
        )
        # [2026-07-10] 목차명 필터링 적용
        if labeled_name and self._is_valid_project_name(labeled_name):
            return labeled_name, 0.88

        keyword_match = re.search(
            r'([가-힣A-Za-z0-9\s]{5,60}(?:정보화|시스템|플랫폼|인프라|데이터|서비스)?'
            r'(?:사업|구축|고도화|개발|운영|도입|혁신|전환))',
            head
        )
        if keyword_match:
            name = self._clean_line_value(keyword_match.group(1))
            # [2026-07-10] 목차명 필터링 적용
            if name and self._is_valid_project_name(name):
                return name[:200], 0.60

        return None, 0.0

    # 발주기관이 아닌 흔한 false positive 단어 목록
    _ORG_BLOCKLIST = frozenset({
        # 제안/요청 관련 업무 용어
        '제안요청', '승인요청', '변경요청', '처리요청', '요청처리',
        '민원신청', '신청처리', '접수처리',
        # 부서/조직 일반 표현 (특정 기관명 아님)
        '업무부', '유관부처', '관련부처', '업무관련부', '담당부서',
        '추진부서', '지원부서', '수행부서', '처리부서',
        '발주처', '발주기관', '주관기관', '수요기관', '담당기관', '제출처', '문의처',
        # 날짜/기간 표현 (로부터, 이후 등)
        '계약일로부', '계약체결일로부', '착수일로부', '추진과제로부',
        '세부추진과제로부', '사고로부', '이행여부',
        # 업무 상태 표현
        '처리결과', '업무처리', '대응지원', '지원사업', '비상대처',
        # IT/기술 용어 (접미사 오탐)
        '아키텍처',
        '세부',
        '첨부',
        '정부',
        '외부', '내부', '일부', '내·외부', '연락처', '공사',
        # 정치/행정 일반 표현 (발주기관 아님)
        '윤석열정부', '연방정부', '전자정부', '디지털정부',
        # 기타 명확한 오탐
        '베이비부', '공고에 따름', '스토킹처',
        # 정치인 이름 포함 표현 / 일반 행정 용어
        '이재명정부', '중앙부처', '고객상담상담센터',
    })

    # 날짜/기간/업무처리 패턴 차단
    _ORG_SUFFIX_BLOCKLIST = re.compile(r'로부$|요청$|신청$|처리$|여부$|결과$|에 따름$')
    _ORG_TEXT_BLOCKLIST = (
        "공사이행보증서",
        "제출된 공사",
        "발생할 경우",
        "요청에 의해",
        "추진하여야",
        "확인을 위한",
        "계약상대자",
        "제안업체",
        "공동수급체",
        "하도급",
        "입찰공고문",
        "필요시",
        "관련 법령",
        "누출할 경우",
        "사업 수행과정",
        "수행과정",
        "입찰 및",
        "평가위원회",
        "심의위원회",
        "위하여",
        "대하여",
        "이후",
        "경우",
        "변경함으로써",
    )
    _ORG_END_BLOCKLIST = ("여부", "세부", "첨부")
    _ORG_NORMALIZE_MAP = {
        "IITP": "정보통신기획평가원",
        "K-water": "한국수자원공사",
        "KOFIH": "한국국제보건의료재단",
        "NIA": "한국지능정보사회진흥원",
    }
    _ORG_PARENT_UNIT_SUFFIXES = ("위원회", "본부", "실", "국", "과", "센터")

    def _is_valid_org_candidate(self, candidate: Optional[str]) -> bool:
        if not candidate:
            return False
        if len(candidate) < 2:
            return False
        if candidate in self._ORG_BLOCKLIST:
            return False
        if self._ORG_SUFFIX_BLOCKLIST.search(candidate):
            return False
        if any(token in candidate for token in self._ORG_TEXT_BLOCKLIST):
            return False
        if candidate.endswith(self._ORG_END_BLOCKLIST):
            return False
        if candidate.endswith("부") and len(candidate) <= 2:
            return False
        if candidate in {"학교", "공단", "범정부", "디지털혁신본부", "경영기획본부", "모든 성과물 공사"}:
            return False
        if candidate.endswith("공단") and candidate.count(" ") >= 1:
            return False
        if candidate.count(" ") >= 1 and any(token in candidate for token in ["위하여", "대하여", "이후", "경우"]):
            return False
        if "지식재산권" in candidate:
            return False
        if candidate.endswith(("부", "청", "처")) and candidate.count(" ") >= 1:
            return False
        if len(candidate) >= 18 and candidate.count(" ") >= 2:
            return False
        return True

    def _normalize_org_candidate(self, candidate: str) -> str:
        parts = [part for part in (candidate or "").split() if part]
        if len(parts) == 2 and parts[0].endswith(("부", "청", "처")) and parts[1].endswith(self._ORG_PARENT_UNIT_SUFFIXES):
            return parts[0]
        return candidate

    def _score_org_candidate(self, candidate: str, line: str) -> float:
        score = 0.55
        candidate_idx = line.find(candidate)
        prefix = line[:candidate_idx] if candidate_idx >= 0 else line

        if re.search(r"(발주기관|주관기관|수요기관|발주처|담당기관)\s*[:：(]?\s*$", prefix):
            score = 0.92
        elif re.search(r"(수행기관|문의처|제출처|장소)\s*[:：(]?\s*$", prefix):
            score = 0.82
        elif any(label in line for label in ["계약", "평가", "사업"]):
            score = 0.65

        if candidate in ("조달청",) and any(token in line for token in ["입찰참가자격", "국가종합전자조달시스템", "조달청 입찰", "조달청 제안평가", "조달청 규정", "평가기관 : 조달청", "평가는 조달청", "조달청 평가"]):
            score -= 0.35

        if any(marker in line for marker in [f"{candidate}에서", f"{candidate}은", f"{candidate}는"]):
            if any(token in line for token in ["평가위원회", "구성", "주관", "요청", "협의"]):
                score += 0.18

        if candidate == "법무부" and any(token in line for token in ["법무부장관", "법무부 장관", "법무부 관련 수행사업"]):
            score += 0.22

        if any(token in line for token in ["고시", "지침", "시행령", "시행규칙", "하도급"]):
            score -= 0.25

        if any(token in line for token in ["계약예규", "예규", "별표"]):
            score -= 0.30

        if candidate == "조달청" and any(token in line for token in ["규정에 따름", "자료가 사본", "입찰참가자격등록증", "제안서평가 세부기준"]):
            score -= 0.40

        if candidate.endswith("부") and any(token in line for token in ["고시", "지침"]):
            score -= 0.15

        if candidate.endswith(("부", "청", "처")) and any(token in line for token in ["계약예규", "예규", "고시", "지침"]):
            score -= 0.20

        if candidate.endswith(("협회", "공단")) and any(token in line for token in ["관리․감독", "관리감독", "이행실적확인서", "경력증명서"]):
            score -= 0.22

        if candidate.startswith(("한국", "국가", "국립")):
            score += 0.03

        return max(0.2, min(score, 0.95))

    def _collect_org_candidates(self, text: str) -> list[tuple[str, float]]:
        candidates: list[tuple[str, float]] = []

        for raw_line in text.splitlines():
            line = self._clean_line_value(raw_line, max_len=200)
            if not line:
                continue

            for alias, canonical in self._ORG_NORMALIZE_MAP.items():
                if alias in line and self._is_org_shape(canonical):
                    candidates.append((canonical, 0.86))

            for candidate in self._extract_org_candidates_from_line(line):
                candidate = self._normalize_org_candidate(candidate)
                if not self._is_valid_org_candidate(candidate):
                    continue
                candidates.append((candidate[:200], self._score_org_candidate(candidate, line)))

        return candidates

    def extract_organization(self, text: str) -> tuple[Optional[str], float]:
        """레이블 기반 → 기관명 패턴 순으로 발주기관을 추출한다."""
        head = text[:_ANALYSIS_LIMIT]

        labeled_patterns = [
            r"(?:발주기관|주관기관|수요기관|발주처|담당기관)(?![가-힣A-Za-z0-9])\s*\(\s*([^)]+?)\s*\)",
            r"(?:발주기관|주관기관|수요기관|발주처|담당기관|수행기관|문의처|제출처)(?![가-힣A-Za-z0-9])\s*[:：]?\s*([^\n\r]{2,80})",
        ]
        for pattern in labeled_patterns:
            match = re.search(pattern, head)
            if not match:
                continue
            org = self._extract_org_candidate(match.group(1))
            if self._is_valid_org_candidate(org):
                return org[:200], 0.90

        candidates = self._collect_org_candidates(head)
        if candidates:
            score_by_org: dict[str, float] = {}
            freq_by_org: dict[str, int] = {}

            for org, score in candidates:
                freq_by_org[org] = freq_by_org.get(org, 0) + 1
                boosted = min(score + (freq_by_org[org] - 1) * 0.03, 0.95)
                prev = score_by_org.get(org, 0.0)
                if boosted > prev:
                    score_by_org[org] = boosted

            best_org = max(
                score_by_org.keys(),
                key=lambda org: (score_by_org[org], freq_by_org.get(org, 0), len(org)),
            )
            best_score = score_by_org[best_org]
            if best_score < 0.50:
                return None, 0.0
            return best_org[:200], best_score

        return None, 0.0

    def extract_year(self, text: str) -> tuple[Optional[int], float]:
        """문서 앞부분의 최빈 20XX 연도를 추출한다."""
        head = text[:_ANALYSIS_LIMIT]
        years = re.findall(r'\b(20[012]\d)(?:년도)?\b', head)
        if not years:
            return None, 0.0

        year_counts: dict[int, int] = {}
        for y in years:
            y_int = int(y)
            year_counts[y_int] = year_counts.get(y_int, 0) + 1

        best_year = max(year_counts, key=lambda y: year_counts[y])
        confidence = min(0.5 + year_counts[best_year] * 0.1, 0.90)
        return best_year, confidence

    def extract_document_type(self, text: str) -> tuple[Optional[str], float]:
        """RFP / 제안서 / 산출물 3가지로 문서 유형을 분류한다."""
        head = text[:_ANALYSIS_LIMIT]

        patterns = [
            (r'제안요청서|제안\s*요청\s*서|RFP\b|입찰공고|입찰참가자격|제안서\s*평가|평가항목|상세\s*요구사항', 'RFP', 0.92),
            (r'기술제안서|제안서\b|사업제안서|수행제안서|제안발표|수행방안|추진전략|제안개요', '제안서', 0.88),
            (r'착수보고서|중간보고서|최종보고서|완료보고서|결과보고서|현황분석|환경분석|목표모델|이행계획|ISP\b|ISMP\b|정보화전략계획', '산출물', 0.86),
        ]

        for pattern, doc_type, confidence in patterns:
            if re.search(pattern, head):
                return doc_type, confidence

        proposal_signals = re.findall(r'전략및방법론|기술및기능|프로젝트관리|프로젝트지원', head)
        if len(proposal_signals) >= 2:
            return "제안서", 0.82

        deliverable_signals = re.findall(r'환경분석|현황분석|목표모델|이행계획', head)
        if len(deliverable_signals) >= 2:
            return "산출물", 0.80

        return None, 0.0

    def extract_all(self, text: str) -> dict:
        """
        모든 필드를 추출하여 ocr_* 형식의 dict로 반환한다.
        ocr_confidence는 추출된 필드의 신뢰도 평균.
        """
        project_name, pn_conf = self.extract_project_name(text)
        organization, org_conf = self.extract_organization(text)
        year, yr_conf = self.extract_year(text)
        document_type, dt_conf = self.extract_document_type(text)

        confs = [c for c in [pn_conf, org_conf, yr_conf, dt_conf] if c > 0]
        avg_confidence = round(sum(confs) / len(confs), 3) if confs else None

        return {
            "ocr_project_name": project_name,
            "ocr_organization": organization,
            "ocr_year": year,
            "ocr_document_category": document_type,
            "ocr_confidence": avg_confidence,
        }


# Singleton
rule_based_extractor = RuleBasedMetadataExtractor()
