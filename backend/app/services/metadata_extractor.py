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

# 분석 대상 텍스트 길이 제한 (성능 최적화: 앞 5000자)
_ANALYSIS_LIMIT = 5000


class RuleBasedMetadataExtractor:
    """
    OCR 추출 텍스트에서 정규식 패턴으로 메타데이터를 추출한다.
    LLM 없이 동작하며 Step 4 파싱 완료 직후 ocr_* 필드를 채운다.
    신뢰도가 낮은 항목은 이후 LLM 보완 대상이 된다.
    """

    def extract_project_name(self, text: str) -> tuple[Optional[str], float]:
        """레이블 기반 → 키워드 패턴 순으로 사업명을 추출한다."""
        head = text[:_ANALYSIS_LIMIT]

        label_match = re.search(
            r'(?:사업명|과업명|프로젝트명|과업|사업)\s*[:：]\s*([^\n\r]{5,80})',
            head
        )
        if label_match:
            name = label_match.group(1).strip()
            if name:
                return name[:200], 0.85

        keyword_match = re.search(
            r'([가-힣A-Za-z0-9\s]{5,60}(?:정보화|시스템|플랫폼|인프라|데이터|서비스)?'
            r'(?:사업|구축|고도화|개발|운영|도입|혁신|전환))',
            head
        )
        if keyword_match:
            name = keyword_match.group(1).strip()
            if name:
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
        # 날짜/기간 표현 (로부터, 이후 등)
        '계약일로부', '계약체결일로부', '착수일로부', '추진과제로부',
        '세부추진과제로부', '사고로부', '이행여부',
        # 업무 상태 표현
        '처리결과', '업무처리', '대응지원', '지원사업', '비상대처',
        # IT/기술 용어 (접미사 오탐)
        '아키텍처',
        # 정치/행정 일반 표현 (발주기관 아님)
        '윤석열정부', '연방정부', '전자정부', '디지털정부',
        # 기타 명확한 오탐
        '베이비부', '공고에 따름', '스토킹처',
        # 정치인 이름 포함 표현 / 일반 행정 용어
        '이재명정부', '중앙부처', '고객상담상담센터',
    })

    # 날짜/기간/업무처리 패턴 차단
    _ORG_SUFFIX_BLOCKLIST = re.compile(r'로부$|요청$|신청$|처리$|여부$|결과$|에 따름$')

    def extract_organization(self, text: str) -> tuple[Optional[str], float]:
        """레이블 기반 → 기관명 패턴 순으로 발주기관을 추출한다."""
        head = text[:_ANALYSIS_LIMIT]

        # 레이블 기반 추출 (수신은 제거 — 제안요청서 등 비기관명 혼입 방지)
        label_match = re.search(
            r'(?:발주기관|주관기관|제출처|발주처)\s*[:：]\s*([^\n\r]{3,60})',
            head
        )
        if label_match:
            org = label_match.group(1).strip()
            if org and org not in self._ORG_BLOCKLIST and not self._ORG_SUFFIX_BLOCKLIST.search(org):
                return org[:200], 0.85

        # 패턴 기반 추출
        # 단일 '원'은 제거 (지원, 대응원 등 오탐 많음); 복합 접미사만 허용
        org_match = re.search(
            r'([가-힣]{2,15}(?:부|청|처|공사|공단|연구원|연구소|재단|위원회|센터))',
            head
        )
        if org_match:
            org = org_match.group(1).strip()
            if (
                len(org) >= 4
                and org not in self._ORG_BLOCKLIST
                and not self._ORG_SUFFIX_BLOCKLIST.search(org)
            ):
                return org[:200], 0.55

        return None, 0.0

    def extract_year(self, text: str) -> tuple[Optional[int], float]:
        """문서 앞부분의 최빈 20XX 연도를 추출한다."""
        head = text[:_ANALYSIS_LIMIT]
        years = re.findall(r'\b(20[012]\d)\b', head)
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
            (r'제안요청서|제안\s*요청\s*서|RFP\b|입찰공고', 'RFP', 0.90),
            (r'기술제안서|제안서\b|사업제안서|수행제안서', '제안서', 0.88),
            (r'최종보고서|완료보고서|결과보고서|중간보고서|ISP\b|ISMP\b|정보화전략계획', '산출물', 0.85),
        ]

        for pattern, doc_type, confidence in patterns:
            if re.search(pattern, head):
                return doc_type, confidence

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
