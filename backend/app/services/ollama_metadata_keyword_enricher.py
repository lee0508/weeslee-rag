"""
Ollama-based metadata and keyword enrichment helpers.

규칙 기반 결과를 대체하지 않고, 부족한 메타데이터/키워드를 보강하는 용도만 담당한다.
실패 시 빈 결과를 반환하여 상위 단계가 규칙 기반으로 계속 진행되게 한다.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings


class OllamaMetadataKeywordEnricher:
    """Ollama를 사용한 메타데이터/키워드 보강 유틸리티."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 45.0,
    ) -> None:
        self.base_url = (base_url or settings.ollama_host).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout

    def enrich_metadata(
        self,
        *,
        file_name: str,
        file_content: str,
        rule_result: Dict[str, Any],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = self._build_metadata_prompt(
            file_name=file_name,
            file_content=file_content,
            rule_result=rule_result,
        )
        raw = self._generate(prompt, model=model)
        if not raw:
            return {}
        data = self._extract_json_object(raw)
        if not isinstance(data, dict):
            return {}
        return {
            "document_type": self._clean_scalar(data.get("document_type")),
            "project_name": self._clean_scalar(data.get("project_name")),
            "organization": self._clean_scalar(data.get("organization")),
            "project_year": self._clean_year(data.get("project_year")),
            "business_domain": self._clean_scalar(data.get("business_domain")),
            "technology_tags": self._clean_string_list(data.get("technology_tags"), limit=8),
            "business_tags": self._clean_string_list(data.get("business_tags"), limit=8),
            "deliverable_tags": self._clean_string_list(data.get("deliverable_tags"), limit=8),
            "summary": self._clean_scalar(data.get("summary"), max_len=400),
            "reuse_level": self._clean_reuse_level(data.get("reuse_level")),
            "confidence": self._clean_confidence(data.get("confidence")),
            "reason": self._clean_scalar(data.get("reason"), max_len=300),
        }

    def enrich_keywords(
        self,
        *,
        file_name: str,
        text_context: str,
        existing_keywords: List[str],
        document_group: str,
        section_type: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = self._build_keyword_prompt(
            file_name=file_name,
            text_context=text_context,
            existing_keywords=existing_keywords,
            document_group=document_group,
            section_type=section_type,
        )
        raw = self._generate(prompt, model=model)
        if not raw:
            return {}
        data = self._extract_json_object(raw)
        if not isinstance(data, dict):
            return {}
        return {
            "keywords": self._clean_string_list(data.get("keywords"), limit=12),
            "synonyms": self._clean_string_list(data.get("synonyms"), limit=12),
            "section_tags": self._clean_string_list(data.get("section_tags"), limit=6),
            "project_name": self._clean_scalar(data.get("project_name")),
            "organization": self._clean_scalar(data.get("organization")),
            "confidence": self._clean_confidence(data.get("confidence")),
        }

    def _generate(self, prompt: str, model: Optional[str] = None) -> str:
        payload = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
                "top_k": 20,
                "num_predict": 800,
            },
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}/api/generate", json=payload)
                response.raise_for_status()
                return response.json().get("response", "")
        except Exception:
            return ""

    def _build_metadata_prompt(
        self,
        *,
        file_name: str,
        file_content: str,
        rule_result: Dict[str, Any],
    ) -> str:
        return f"""당신은 한국 공공/컨설팅 문서 메타데이터 보강기입니다.
규칙 기반 결과를 무시하지 말고, 부족한 값만 보강하세요.

파일명:
{file_name}

규칙 기반 결과:
{json.dumps(rule_result, ensure_ascii=False)}

문서 본문:
{file_content[:3000]}

아래 JSON 객체 하나만 출력하세요.
{{
  "document_type": "rfp|proposal|kickoff_report|interim_report|final_report|completion_report|presentation|unknown",
  "project_name": "사업명 또는 빈 문자열",
  "organization": "발주기관 또는 빈 문자열",
  "project_year": "연도 또는 빈 문자열",
  "business_domain": "사업분야 또는 빈 문자열",
  "technology_tags": ["태그"],
  "business_tags": ["태그"],
  "deliverable_tags": ["태그"],
  "summary": "한 문장 요약",
  "reuse_level": "high|medium|low",
  "confidence": 0.0,
  "reason": "보강 근거"
}}"""

    def _build_keyword_prompt(
        self,
        *,
        file_name: str,
        text_context: str,
        existing_keywords: List[str],
        document_group: str,
        section_type: str,
    ) -> str:
        return f"""당신은 RAG 검색용 키워드 보강기입니다.
기존 키워드를 중복하지 말고, 질문 검색에 유용한 확장 키워드와 동의어만 제안하세요.

파일명:
{file_name}

문서 그룹:
{document_group}

섹션 유형:
{section_type}

기존 규칙 기반 키워드:
{json.dumps(existing_keywords[:20], ensure_ascii=False)}

문서 본문:
{text_context[:2500]}

아래 JSON 객체 하나만 출력하세요.
{{
  "keywords": ["검색에 직접 유용한 확장 키워드"],
  "synonyms": ["동의어 또는 질의 확장어"],
  "section_tags": ["전략및방법론|기술및기능|프로젝트관리|프로젝트지원|환경분석|현황분석|목표모델|이행계획 중 해당값"],
  "project_name": "추론 가능한 사업명 또는 빈 문자열",
  "organization": "추론 가능한 기관명 또는 빈 문자열",
  "confidence": 0.0
}}"""

    @staticmethod
    def _extract_json_object(raw: str) -> Any:
        fenced = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", raw)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass
        bare = re.search(r"(\{[\s\S]*\})", raw)
        if bare:
            try:
                return json.loads(bare.group(1))
            except json.JSONDecodeError:
                return None
        return None

    @staticmethod
    def _clean_scalar(value: Any, max_len: int = 120) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            return ""
        return text[:max_len]

    @staticmethod
    def _clean_year(value: Any) -> str:
        text = OllamaMetadataKeywordEnricher._clean_scalar(value, max_len=10)
        match = re.search(r"(20\d{2})", text)
        return match.group(1) if match else ""

    @staticmethod
    def _clean_confidence(value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, round(score, 4)))

    @staticmethod
    def _clean_reuse_level(value: Any) -> str:
        text = OllamaMetadataKeywordEnricher._clean_scalar(value, max_len=20).lower()
        if text in {"high", "medium", "low"}:
            return text
        return "medium"

    @staticmethod
    def _clean_string_list(value: Any, limit: int = 10) -> List[str]:
        if not isinstance(value, list):
            return []
        cleaned: List[str] = []
        for item in value:
            text = OllamaMetadataKeywordEnricher._clean_scalar(item, max_len=60)
            if len(text) < 2:
                continue
            if text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= limit:
                break
        return cleaned
