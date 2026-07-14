# Tool Calling 실행 엔진 - Ollama/OpenAI 통합
"""
LLM의 Tool Calling 요청을 처리하고 결과를 통합합니다.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Optional

from app.services.tool_registry import get_registry

logger = logging.getLogger(__name__)


def _sanitize_error_message(error_str: str) -> str:
    """기술적 오류 메시지를 사용자 친화적 메시지로 변환합니다."""
    error_lower = error_str.lower()

    # 연결 오류
    if any(kw in error_lower for kw in ["connection", "urlopen", "timeout", "refused"]):
        return "LLM 서버 연결 실패"

    # JSON 파싱 오류
    if "json" in error_lower or "decode" in error_lower:
        return "응답 파싱 실패"

    # 파일/경로 오류
    if any(kw in error_lower for kw in ["file", "path", "directory", "no such"]):
        return "데이터 파일 접근 실패"

    # 메모리/리소스 오류
    if any(kw in error_lower for kw in ["memory", "resource", "oom"]):
        return "리소스 부족"

    # 기타: 첫 50자만 표시
    if len(error_str) > 50:
        return error_str[:47] + "..."
    return error_str


class ToolExecutor:
    """Tool Calling을 실행하고 LLM과 통합합니다."""

    def __init__(
        self,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.ollama_url = ollama_url or os.environ.get(
            "OLLAMA_HOST", "http://127.0.0.1:11434"
        )
        self.model = model or os.environ.get("OLLAMA_MODEL", "gemma3:latest")
        self.registry = get_registry()

        # 도구 모듈 로드
        self._load_tools()

    def _load_tools(self) -> None:
        """도구 모듈을 로드하여 등록합니다."""
        try:
            import app.services.tools  # noqa: F401
            logger.info(f"[ToolExecutor] 도구 로드 완료: {self.registry.list_tools()}")
        except Exception as e:
            logger.warning(f"[ToolExecutor] 도구 로드 실패: {e}")

    def execute_with_tools(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        max_tool_calls: int = 5,
    ) -> dict[str, Any]:
        """
        쿼리를 처리하고 필요한 도구를 호출합니다.

        1. LLM에 쿼리와 도구 목록 전달
        2. LLM이 도구 호출 결정
        3. 도구 실행 및 결과 수집
        4. 최종 답변 생성
        """
        tool_definitions = self.registry.get_all_definitions("ollama")

        if not tool_definitions:
            # 도구가 없으면 일반 생성
            return self._generate_without_tools(query, system_prompt)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": query})

        tool_results = []
        call_count = 0

        while call_count < max_tool_calls:
            response = self._call_ollama_with_tools(messages, tool_definitions)

            if not response:
                break

            # 도구 호출 확인
            tool_calls = response.get("message", {}).get("tool_calls", [])

            if not tool_calls:
                # 더 이상 도구 호출 없음 - 최종 답변
                return {
                    "answer": response.get("message", {}).get("content", ""),
                    "tool_results": tool_results,
                    "tool_calls_count": call_count,
                }

            # 도구 실행
            for tool_call in tool_calls:
                call_count += 1
                func = tool_call.get("function", {})
                tool_name = func.get("name", "")
                arguments = func.get("arguments", {})

                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                logger.info(f"[ToolExecutor] 도구 호출: {tool_name}({arguments})")

                result = self.registry.execute(tool_name, arguments)
                tool_results.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": result,
                })

                # 결과를 메시지에 추가
                messages.append({
                    "role": "tool",
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        # 최종 답변 생성
        final_response = self._generate_final_answer(messages)

        return {
            "answer": final_response,
            "tool_results": tool_results,
            "tool_calls_count": call_count,
        }

    def _call_ollama_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> Optional[dict]:
        """Ollama API를 호출합니다 (도구 포함)."""
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "stream": False,
            }

            req = urllib.request.Request(
                f"{self.ollama_url}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))

        except Exception as e:
            logger.exception("[ToolExecutor] Ollama 호출 실패")
            return None

    def _generate_without_tools(
        self,
        query: str,
        system_prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        """도구 없이 일반 생성을 수행합니다."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": query})

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
            }

            req = urllib.request.Request(
                f"{self.ollama_url}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "answer": data.get("message", {}).get("content", ""),
                    "tool_results": [],
                    "tool_calls_count": 0,
                }

        except Exception as e:
            logger.exception("[ToolExecutor] 생성 실패")
            # 기술적 오류 메시지를 사용자 친화적 메시지로 변환
            error_msg = _sanitize_error_message(str(e))
            return {
                "answer": f"죄송합니다. 일시적인 오류가 발생했습니다. ({error_msg})",
                "tool_results": [],
                "tool_calls_count": 0,
            }

    def _generate_final_answer(self, messages: list[dict]) -> str:
        """도구 결과를 바탕으로 최종 답변을 생성합니다."""
        try:
            # 최종 답변 생성 요청
            messages.append({
                "role": "user",
                "content": "위의 도구 실행 결과를 바탕으로 사용자 질문에 대한 최종 답변을 한국어로 작성해주세요.",
            })

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
            }

            req = urllib.request.Request(
                f"{self.ollama_url}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("message", {}).get("content", "")

        except Exception as e:
            logger.exception("[ToolExecutor] 최종 답변 생성 실패")
            error_msg = _sanitize_error_message(str(e))
            return f"도구 실행은 완료되었으나 답변 생성에 실패했습니다. ({error_msg})"


# 전역 인스턴스
_executor: Optional[ToolExecutor] = None


def get_executor() -> ToolExecutor:
    """전역 ToolExecutor를 반환합니다."""
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor


def execute_with_tools(
    query: str,
    system_prompt: Optional[str] = None,
    max_tool_calls: int = 5,
) -> dict[str, Any]:
    """편의 함수: Tool Calling을 실행합니다."""
    return get_executor().execute_with_tools(query, system_prompt, max_tool_calls)
