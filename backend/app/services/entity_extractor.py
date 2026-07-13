# LLM 기반 문서 속성(엔티티) 자동 추출 서비스
"""
Entity Extractor Service
- 문서 청크에서 제목, 기관, 연도, 목차, 주제 등을 LLM으로 추출
- Claude, Ollama, OpenAI, Gemini 지원

Usage:
    from app.services.entity_extractor import EntityExtractor, get_llm

    llm = get_llm(provider="ollama", model="gemma3:4b")
    extractor = EntityExtractor(llm)
    attrs = extractor.extract(source_id="doc_001", chunks=[{"text": "..."}])
    print(attrs.title, attrs.organization, attrs.topics)
"""

from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DocAttributes:
    """LLM이 청크에서 추출하는 문서 속성"""
    source_id: str
    title: str = ""
    organization: str = ""
    year: Optional[int] = None
    doc_type: str = ""
    purpose: str = ""
    sections: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# 구조화 출력 강제 프롬프트 (JSON only)
_EXTRACT_PROMPT = """다음은 한 문서의 대표 청크 발췌이다. 메타 속성을 추출하라.
반드시 JSON 객체만 출력하라. 설명, 마크다운, 코드펜스 금지.

[문서 발췌]
{context}

[추출 스키마]
{{
  "title": "문서 제목(문자열)",
  "organization": "발행 기관(문자열, 없으면 빈 문자열)",
  "year": 발행연도(정수, 없으면 null),
  "doc_type": "문서 종류(문자열)",
  "purpose": "문서 생성 목적(1문장)",
  "sections": ["목차/장절 제목 배열"],
  "topics": ["핵심 주제 키워드 배열(최대 5)"]
}}"""


class BaseLLM(ABC):
    """LLM 호출 공통 인터페이스"""
    @abstractmethod
    def complete(self, prompt: str) -> str:
        """프롬프트 → 응답 문자열"""
        raise NotImplementedError


class ClaudeLLM(BaseLLM):
    """Anthropic Claude API"""
    def __init__(self, model: str = "claude-sonnet-4-20250514", temperature: float = 0.0):
        self.model = model
        self.temperature = temperature

    def complete(self, prompt: str) -> str:
        try:
            from anthropic import Anthropic
            client = Anthropic()
            resp = client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in resp.content if b.type == "text")
        except ImportError:
            raise ImportError("anthropic 패키지가 설치되지 않았습니다: pip install anthropic")


class OllamaLLM(BaseLLM):
    """온프레미스 Ollama LLM"""
    def __init__(self, model: str = "gemma3:4b",
                 url: Optional[str] = None, temperature: float = 0.0):
        self.model = model
        self.url = url or settings.ollama_host
        self.temperature = temperature

    def complete(self, prompt: str) -> str:
        import requests
        resp = requests.post(
            f"{self.url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": self.temperature}
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")


class OpenAILLM(BaseLLM):
    """OpenAI API"""
    def __init__(self, model: str = "gpt-4o", temperature: float = 0.0):
        self.model = model
        self.temperature = temperature

    def complete(self, prompt: str) -> str:
        try:
            from openai import OpenAI
            client = OpenAI()
            resp = client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content or ""
        except ImportError:
            raise ImportError("openai 패키지가 설치되지 않았습니다: pip install openai")


class GeminiLLM(BaseLLM):
    """Google Gemini API"""
    def __init__(self, model: str = "gemini-2.0-flash", temperature: float = 0.0):
        self.model = model
        self.temperature = temperature

    def complete(self, prompt: str) -> str:
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config={"temperature": self.temperature}
            )
            return response.text or ""
        except ImportError:
            raise ImportError("google-generativeai 패키지가 설치되지 않았습니다")


class FakeLLM(BaseLLM):
    """테스트용 LLM — 고정 응답 반환"""
    def __init__(self, canned_response: Optional[str] = None):
        self.canned_response = canned_response or json.dumps({
            "title": "테스트 문서",
            "organization": "테스트 기관",
            "year": 2024,
            "doc_type": "보고서",
            "purpose": "테스트 목적",
            "sections": ["개요", "본론", "결론"],
            "topics": ["테스트", "문서", "추출"]
        }, ensure_ascii=False)

    def complete(self, prompt: str) -> str:
        return self.canned_response


def get_llm(provider: Optional[str] = None, model: Optional[str] = None,
            temperature: float = 0.0, **kwargs) -> BaseLLM:
    """
    설정에 따라 LLM 인스턴스 반환

    Args:
        provider: ollama | openai | gemini | fake  (claude는 정책상 비활성화)
        model: 모델 이름 (기본값은 provider별로 다름)
        temperature: 생성 온도 (0.0 = 결정론적)
    """
    provider = (provider or settings.answer_provider).lower()

    if provider == "ollama":
        return OllamaLLM(
            model=model or settings.answer_model,
            temperature=temperature,
            **kwargs
        )
    elif provider == "claude":
        # Claude(Anthropic) API 기반 초안 생성은 온프레미스 정책에 따라 비활성화됨.
        # 로컬 LLM(ollama)만 사용한다.
        raise ValueError(
            "Claude(Anthropic) provider는 비활성화되었습니다. "
            "온프레미스 로컬 LLM(provider='ollama')을 사용하세요."
        )
    elif provider == "openai":
        return OpenAILLM(
            model=model or "gpt-4o",
            temperature=temperature
        )
    elif provider == "gemini":
        return GeminiLLM(
            model=model or "gemini-2.0-flash",
            temperature=temperature
        )
    elif provider == "fake":
        return FakeLLM(kwargs.get("canned_response"))
    else:
        raise ValueError(f"지원하지 않는 LLM provider: {provider}")


class EntityExtractor:
    """청크에서 문서 속성을 추출하는 추출기"""

    def __init__(self, llm: BaseLLM, head_chunk_count: int = 5):
        """
        Args:
            llm: LLM 인스턴스
            head_chunk_count: 속성 추출에 사용할 대표 청크 수 (문서 앞부분)
        """
        self.llm = llm
        self.head_chunk_count = head_chunk_count

    def extract(self, source_id: str, chunks: List[dict]) -> DocAttributes:
        """
        대표 청크에서 문서 속성을 추출한다.

        Args:
            source_id : 대상 source ID
            chunks    : 청크 리스트 [{text, metadata}, ...]
        Returns:
            DocAttributes
        """
        if not chunks:
            return DocAttributes(source_id=source_id)

        # 문서 앞부분 대표 청크 선별 (제목/목차/발행정보 집중 영역)
        head = chunks[:self.head_chunk_count]
        context = "\n\n".join(
            c.get("text", "") if isinstance(c, dict) else str(c)
            for c in head
        )

        # 컨텍스트가 너무 길면 자르기
        if len(context) > 8000:
            context = context[:8000] + "\n...(생략)"

        prompt = _EXTRACT_PROMPT.format(context=context)

        try:
            raw = self.llm.complete(prompt)
            data = self._safe_parse_json(raw)
        except Exception as e:
            logger.warning(f"LLM 호출 실패: {e}")
            data = {}

        return DocAttributes(
            source_id=source_id,
            title=data.get("title", ""),
            organization=data.get("organization", ""),
            year=data.get("year"),
            doc_type=data.get("doc_type", ""),
            purpose=data.get("purpose", ""),
            sections=data.get("sections", []) or [],
            topics=data.get("topics", []) or [],
        )

    def extract_from_text(self, source_id: str, text: str) -> DocAttributes:
        """
        텍스트에서 직접 문서 속성을 추출한다.

        Args:
            source_id: 문서 ID
            text: 문서 텍스트 (앞부분 8000자까지 사용)
        """
        # 앞부분만 사용
        context = text[:8000] if len(text) > 8000 else text
        prompt = _EXTRACT_PROMPT.format(context=context)

        try:
            raw = self.llm.complete(prompt)
            data = self._safe_parse_json(raw)
        except Exception as e:
            logger.warning(f"LLM 호출 실패: {e}")
            data = {}

        return DocAttributes(
            source_id=source_id,
            title=data.get("title", ""),
            organization=data.get("organization", ""),
            year=data.get("year"),
            doc_type=data.get("doc_type", ""),
            purpose=data.get("purpose", ""),
            sections=data.get("sections", []) or [],
            topics=data.get("topics", []) or [],
        )

    @staticmethod
    def _safe_parse_json(raw: str) -> dict:
        """LLM 응답에서 JSON을 안전하게 파싱한다"""
        # 코드펜스/앞뒤 잡텍스트 제거
        clean = raw.replace("```json", "").replace("```", "").strip()
        # 첫 { 부터 마지막 } 까지만 추출 (앞뒤 설명문 방어)
        start, end = clean.find("{"), clean.rfind("}")
        if start != -1 and end != -1:
            clean = clean[start:end + 1]
        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 파싱 실패, 빈 속성 반환: {e}")
            return {}


# 편의 함수
def extract_document_attributes(
    chunks: List[dict],
    source_id: str = "unknown",
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> DocAttributes:
    """
    청크에서 문서 속성을 추출하는 편의 함수

    Args:
        chunks: 청크 리스트 [{text, ...}, ...]
        source_id: 문서 식별자
        provider: LLM provider (기본: settings.answer_provider)
        model: LLM 모델 (기본: provider 기본값)
    """
    llm = get_llm(provider=provider, model=model)
    extractor = EntityExtractor(llm)
    return extractor.extract(source_id, chunks)
