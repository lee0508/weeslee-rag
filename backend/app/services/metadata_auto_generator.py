# 문서 메타데이터 자동 생성 서비스
# 작업일: 2026-07-08 - DB 시스템 설정 연동 추가
"""
metadata_auto_generator.py

문서에서 자동으로 메타데이터를 추출한다.
1단계: 규칙 기반 추출 (파일명, 키워드)
2단계: LLM 기반 추출 (Ollama)
"""

import re
import asyncio
from typing import Dict, List, Any

from app.services.ollama_metadata_keyword_enricher import OllamaMetadataKeywordEnricher


def _get_ollama_host() -> str:
    """DB 설정 우선, 없으면 기본값 반환."""
    try:
        from app.services.system_settings_service import get_endpoint_setting
        return get_endpoint_setting("ollama_host", "http://localhost:11434")
    except Exception:
        return "http://localhost:11434"


class MetadataAutoGenerator:
    """문서 메타데이터 자동 생성기."""

    # 문서 유형 키워드 매핑
    DOC_TYPE_KEYWORDS = {
        "rfp": ["RFP", "제안요청서", "제안요청", "입찰공고", "공고문"],
        "proposal": ["제안서", "기술제안", "사업제안", "입찰제안"],
        "kickoff_report": ["착수보고", "착수회의", "Kick-off", "킥오프"],
        "interim_report": ["중간보고", "중간성과", "진행보고"],
        "final_report": ["최종보고", "결과보고", "최종성과", "완료보고"],
        "completion_report": ["완료보고", "준공보고", "사업완료"],
        "presentation": ["발표자료", "프레젠테이션", "PT자료", ".pptx", ".ppt"],
        "temporary_material": ["임시", "초안", "draft", "검토용"],
    }

    # 기술 태그 키워드
    TECH_KEYWORDS = {
        "AI": ["AI", "인공지능", "머신러닝", "딥러닝", "Machine Learning"],
        "LLM": ["LLM", "대규모언어모델", "GPT", "ChatGPT", "Claude"],
        "RAG": ["RAG", "검색증강생성", "Retrieval"],
        "클라우드": ["클라우드", "AWS", "GCP", "Azure", "Cloud"],
        "데이터플랫폼": ["데이터플랫폼", "데이터허브", "데이터레이크"],
        "디지털트윈": ["디지털트윈", "Digital Twin", "DT"],
        "빅데이터": ["빅데이터", "Big Data", "데이터분석"],
        "IoT": ["IoT", "사물인터넷", "센서"],
        "블록체인": ["블록체인", "Blockchain"],
    }

    # 업무 태그 키워드
    BUSINESS_KEYWORDS = {
        "ISP": ["ISP", "정보화전략계획", "정보전략계획"],
        "ISMP": ["ISMP", "정보시스템마스터플랜"],
        "EA": ["EA", "전사아키텍처", "Enterprise Architecture"],
        "PMO": ["PMO", "프로젝트관리", "사업관리"],
        "컨설팅": ["컨설팅", "Consulting", "자문"],
        "SI": ["SI", "시스템통합", "시스템구축"],
        "운영": ["운영", "유지보수", "O&M"],
    }

    # 공공기관 키워드
    ORG_KEYWORDS = [
        "한국수자원공사", "K-water", "수공",
        "한국전력공사", "KEPCO", "한전",
        "한국토지주택공사", "LH", "토지주택",
        "한국도로공사", "도공",
        "한국철도공사", "코레일", "KORAIL",
        "국토교통부", "국토부",
        "과학기술정보통신부", "과기부",
        "행정안전부", "행안부",
        "환경부",
        "농림축산식품부", "농림부",
        "보건복지부", "복지부",
        "경기주택도시공사", "GH",
        "인천국제공항공사", "인천공항",
        "서울시", "경기도", "인천시", "부산시",
    ]

    def __init__(self, ollama_host: str = None):
        # DB 설정 우선, 없으면 하드코딩 fallback
        self.ollama_host = ollama_host or _get_ollama_host()
        self.enricher = OllamaMetadataKeywordEnricher(base_url=self.ollama_host)

    def extract_metadata(self, file_name: str, file_content: str = "") -> Dict[str, Any]:
        """
        파일명과 내용에서 메타데이터를 자동 추출한다.

        Args:
            file_name: 파일명
            file_content: 파일 본문 (선택)

        Returns:
            추출된 메타데이터 딕셔너리
        """
        combined_text = f"{file_name} {file_content}"

        result = {
            "document_type": self._extract_document_type(file_name, file_content),
            "project_name": self._extract_project_name(file_name),
            "organization": self._extract_organization(combined_text),
            "project_year": self._extract_year(combined_text),
            "business_domain": self._extract_business_domain(combined_text),
            "technology_tags": self._extract_tech_tags(combined_text),
            "business_tags": self._extract_business_tags(combined_text),
            "deliverable_tags": [],
            "summary": "",
            "reuse_level": "medium",
            "confidence": 0.0,
            "reason": "",
        }

        # 신뢰도 계산
        result["confidence"] = self._calculate_confidence(result)
        result["reason"] = self._generate_reason(result, file_name)

        return result

    def _extract_document_type(self, file_name: str, content: str = "") -> str:
        """문서 유형을 추출한다."""
        combined = f"{file_name} {content[:1000]}"

        for doc_type, keywords in self.DOC_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in combined.lower():
                    return doc_type

        # 확장자 기반 판단
        if file_name.lower().endswith(('.pptx', '.ppt')):
            return "presentation"

        return "unknown"

    def _extract_project_name(self, file_name: str) -> str:
        """파일 경로에서 사업명을 추출한다."""
        # 경로에서 폴더명 추출 시도
        path_parts = file_name.replace("\\", "/").split("/")

        for part in path_parts:
            # "202XXX. 사업명" 또는 "2024. 사업명" 형태 찾기 (연도+월 or 연도만)
            if re.match(r'^20\d{2,4}[\.\s]', part):
                return part

        return ""

    def _extract_organization(self, text: str) -> str:
        """발주기관을 추출한다."""
        text_lower = text.lower()
        for org in self.ORG_KEYWORDS:
            if org.lower() in text_lower:
                return org
        return ""

    def _extract_year(self, text: str) -> str:
        """수행연도를 추출한다."""
        # 폴더명 패턴: "202XXX." 또는 "202X년" 형태에서 연도 추출
        folder_match = re.search(r'(20[12][0-9])[0-9]{0,2}\.', text)
        if folder_match:
            return folder_match.group(1)

        # 연도 패턴: "2020년" ~ "2030년"
        year_match = re.search(r'(202[0-9]|203[0-9])년?', text)
        if year_match:
            return year_match.group(1)

        return ""

    def _extract_business_domain(self, text: str) -> str:
        """사업분야를 추출한다."""
        domains = []
        for tag, keywords in self.BUSINESS_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text.lower():
                    domains.append(tag)
                    break
        return ", ".join(domains[:3]) if domains else ""

    def _extract_tech_tags(self, text: str) -> List[str]:
        """기술 태그를 추출한다."""
        tags = []
        for tag, keywords in self.TECH_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text.lower():
                    tags.append(tag)
                    break
        return tags[:5]

    def _extract_business_tags(self, text: str) -> List[str]:
        """업무 태그를 추출한다."""
        tags = []
        for tag, keywords in self.BUSINESS_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text.lower():
                    tags.append(tag)
                    break
        return tags[:5]

    def _calculate_confidence(self, result: Dict) -> float:
        """신뢰도를 계산한다."""
        score = 0.0

        # 문서 유형이 있으면 +0.3
        if result.get("document_type") != "unknown":
            score += 0.3

        # 사업명이 있으면 +0.2
        if result.get("project_name"):
            score += 0.2

        # 발주기관이 있으면 +0.2
        if result.get("organization"):
            score += 0.2

        # 기술 태그가 있으면 +0.15
        if result.get("technology_tags"):
            score += 0.15

        # 업무 태그가 있으면 +0.15
        if result.get("business_tags"):
            score += 0.15

        return round(min(score, 1.0), 2)

    def _generate_reason(self, result: Dict, file_name: str) -> str:
        """분류 판단 근거를 생성한다."""
        reasons = []

        doc_type = result.get("document_type", "unknown")
        if doc_type != "unknown":
            reasons.append(f"파일명/내용에서 '{doc_type}' 관련 키워드를 발견하여 분류")

        if result.get("organization"):
            reasons.append(f"발주기관 '{result['organization']}' 감지")

        if result.get("technology_tags"):
            reasons.append(f"기술 키워드: {', '.join(result['technology_tags'][:3])}")

        if not reasons:
            reasons.append("규칙 기반 자동 추출 (키워드 미발견)")

        return "; ".join(reasons)

    async def extract_with_llm(
        self,
        file_name: str,
        file_content: str,
        model: str = "gemma4:latest"
    ) -> Dict[str, Any]:
        """
        LLM을 사용하여 메타데이터를 추출한다.

        Args:
            file_name: 파일명
            file_content: 파일 본문 (처음 2000자)
            model: Ollama 모델명

        Returns:
            LLM이 추출한 메타데이터
        """
        # 먼저 규칙 기반 추출
        rule_result = self.extract_metadata(file_name, file_content)

        try:
            llm_result = await asyncio.to_thread(
                self.enricher.enrich_metadata,
                file_name=file_name,
                file_content=file_content[:3000],
                rule_result=rule_result,
                model=model,
            )
            if llm_result:
                merged = {**rule_result}
                for key, value in llm_result.items():
                    if key.endswith("_tags") and value:
                        base_values = rule_result.get(key) or []
                        merged[key] = list(dict.fromkeys([*base_values, *value]))[:8]
                    elif key == "confidence":
                        merged[key] = max(rule_result.get("confidence", 0.0), float(value or 0.0))
                    elif key == "reason":
                        merged[key] = value or "LLM 기반 추출 + 규칙 기반 보정"
                    elif value not in ("", None, []):
                        merged[key] = value
                if not merged.get("reason"):
                    merged["reason"] = "LLM 기반 추출 + 규칙 기반 보정"
                return merged

        except Exception as e:
            rule_result["reason"] += f"; LLM 호출 실패: {str(e)[:50]}"

        return rule_result


# 싱글톤 인스턴스
metadata_auto_generator = MetadataAutoGenerator()
