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

            # Validate category
            if metadata.category not in self.CATEGORIES:
                metadata.category = '기타'

            # Validate document type
            if metadata.document_type not in self.DOCUMENT_TYPES:
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
