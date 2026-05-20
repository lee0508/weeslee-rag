"""
metadata_auto_generator.py

weeslee-rag 문서 자동 메타데이터 / 태그 생성 서비스

역할:
1. 파일명 기반 문서 유형 추정
2. 본문 키워드 기반 태그 추천
3. LLM 기반 메타데이터 보완
4. 관리자 검수용 suggestion 생성
"""

import re
from typing import Dict, List, Any


class MetadataAutoGenerator:
    """
    문서 자동 메타데이터 생성 클래스
    """

    def __init__(self):
        """
        자동 분류에 사용할 기본 키워드 사전을 초기화한다.
        """

        self.document_type_rules = {
            "rfp": ["RFP", "제안요청서", "과업지시서", "입찰공고"],
            "proposal": ["제안서", "기술제안서", "사업수행계획서"],
            "kickoff_report": ["착수보고서", "착수계", "착수 발표"],
            "interim_report": ["중간보고서", "중간보고"],
            "final_report": ["최종보고서", "결과보고서"],
            "completion_report": ["완료보고서", "준공보고서"],
            "presentation": ["발표자료", "보고회", "PPT"],
            "temporary_material": ["임시", "초안", "draft", "작업본", "test"]
        }

        self.technology_keywords = [
            "AI", "LLM", "RAG", "OCR", "VectorDB", "FAISS", "Chroma",
            "클라우드", "빅데이터", "데이터 플랫폼", "디지털 트윈",
            "IoT", "API", "대시보드", "보안", "DW", "데이터레이크"
        ]

        self.business_keywords = [
            "ISP", "ISMP", "정보화전략계획", "시스템 구축",
            "시스템 고도화", "데이터 플랫폼", "공공기관",
            "행정", "의료", "교육", "물관리", "에너지"
        ]

        self.deliverable_keywords = [
            "제안서", "착수보고서", "중간보고서", "최종보고서",
            "완료보고서", "결과보고서", "발표자료", "요구사항정의서",
            "목표모델", "이행계획", "아키텍처"
        ]

    def generate(self, file_name: str, text: str) -> Dict[str, Any]:
        """
        파일명과 본문 텍스트를 기반으로 자동 메타데이터를 생성한다.

        Parameters
        ----------
        file_name : str
            원본 파일명
        text : str
            추출된 문서 본문

        Returns
        -------
        Dict[str, Any]
            자동 생성된 메타데이터와 태그
        """

        combined_text = f"{file_name}\n{text[:5000]}"

        document_type, type_reason = self.detect_document_type(combined_text)

        technology_tags = self.extract_keywords(combined_text, self.technology_keywords)
        business_tags = self.extract_keywords(combined_text, self.business_keywords)
        deliverable_tags = self.extract_keywords(combined_text, self.deliverable_keywords)

        project_name = self.extract_project_name(combined_text)
        organization = self.extract_organization(combined_text)
        project_year = self.extract_year(combined_text)

        summary = self.create_simple_summary(text)

        confidence = self.calculate_confidence(
            document_type=document_type,
            project_name=project_name,
            organization=organization,
            technology_tags=technology_tags,
            business_tags=business_tags
        )

        return {
            "document_type": document_type,
            "project_name": project_name,
            "organization": organization,
            "project_year": project_year,
            "business_domain": " / ".join(business_tags[:3]),
            "technology_tags": technology_tags,
            "business_tags": business_tags,
            "deliverable_tags": deliverable_tags,
            "summary": summary,
            "reuse_level": self.estimate_reuse_level(document_type, deliverable_tags),
            "confidence": confidence,
            "reason": type_reason,
            "status": "auto_suggested"
        }

    def detect_document_type(self, text: str):
        """
        문서 유형을 자동 추정한다.
        """

        for doc_type, keywords in self.document_type_rules.items():
            for keyword in keywords:
                if keyword.lower() in text.lower():
                    return doc_type, f"'{keyword}' 키워드를 기준으로 {doc_type} 유형으로 판단했습니다."

        return "unknown", "문서 유형을 명확히 판단할 수 없어 unknown으로 분류했습니다."

    def extract_keywords(self, text: str, keyword_list: List[str]) -> List[str]:
        """
        본문에 포함된 키워드를 태그로 추출한다.
        """

        result = []

        for keyword in keyword_list:
            if keyword.lower() in text.lower():
                result.append(keyword)

        return list(dict.fromkeys(result))

    def extract_project_name(self, text: str) -> str:
        """
        사업명을 추정한다.

        우선 '사업명', '용역명', '과업명' 주변 문장을 찾는다.
        """

        patterns = [
            r"사업명\s*[:：]\s*(.+)",
            r"용역명\s*[:：]\s*(.+)",
            r"과업명\s*[:：]\s*(.+)"
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()[:200]

        return ""

    def extract_organization(self, text: str) -> str:
        """
        발주기관을 추정한다.
        """

        patterns = [
            r"발주기관\s*[:：]\s*(.+)",
            r"수요기관\s*[:：]\s*(.+)",
            r"기관명\s*[:：]\s*(.+)"
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()[:100]

        return ""

    def extract_year(self, text: str) -> str:
        """
        문서에서 연도를 추출한다.
        """

        match = re.search(r"(20[0-9]{2})", text)

        if match:
            return match.group(1)

        return ""

    def create_simple_summary(self, text: str) -> str:
        """
        간단 요약문을 생성한다.
        실제 운영에서는 LLM 요약으로 대체 가능하다.
        """

        clean_text = re.sub(r"\s+", " ", text).strip()

        return clean_text[:300]

    def estimate_reuse_level(self, document_type: str, deliverable_tags: List[str]) -> str:
        """
        문서 유형을 기준으로 재사용 가능성을 추정한다.
        """

        high_reuse_types = [
            "proposal",
            "final_report",
            "completion_report",
            "presentation"
        ]

        if document_type in high_reuse_types:
            return "high"

        if deliverable_tags:
            return "medium"

        return "low"

    def calculate_confidence(
        self,
        document_type: str,
        project_name: str,
        organization: str,
        technology_tags: List[str],
        business_tags: List[str]
    ) -> float:
        """
        자동 추출 신뢰도를 계산한다.
        """

        score = 0.0

        if document_type != "unknown":
            score += 0.3

        if project_name:
            score += 0.2

        if organization:
            score += 0.2

        if technology_tags:
            score += 0.15

        if business_tags:
            score += 0.15

        return round(score, 2)
