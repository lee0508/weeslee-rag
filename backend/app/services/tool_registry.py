# LLM Tool Calling을 위한 도구 레지스트리 및 실행 엔진
"""
Tool Registry - LLM이 호출할 수 있는 도구들을 정의하고 실행합니다.

주요 도구:
1. analyze_data_structure - 데이터 구조 분석 (스키마, 메타데이터)
2. diagnose_data_quality - 데이터 품질 진단 (구조화 수준, 연계 가능성)
3. calculate_statistics - 통계 및 지표 계산
4. search_documents - RAG 문서 검색
5. query_graph - GraphRAG 관계 조회
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """LLM에 전달할 도구 정의."""
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    required: list[str] = field(default_factory=list)

    def to_ollama_format(self) -> dict[str, Any]:
        """Ollama function calling 형식으로 변환."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }

    def to_openai_format(self) -> dict[str, Any]:
        """OpenAI function calling 형식으로 변환."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }


class ToolRegistry:
    """도구 등록 및 실행을 관리합니다."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """도구를 등록합니다."""
        self._tools[tool.name] = tool
        logger.info(f"[ToolRegistry] 도구 등록: {tool.name}")

    def get(self, name: str) -> Optional[ToolDefinition]:
        """도구를 이름으로 조회합니다."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """등록된 도구 이름 목록을 반환합니다."""
        return list(self._tools.keys())

    def get_all_definitions(self, format: str = "ollama") -> list[dict[str, Any]]:
        """모든 도구 정의를 LLM 형식으로 반환합니다."""
        definitions = []
        for tool in self._tools.values():
            if format == "openai":
                definitions.append(tool.to_openai_format())
            else:
                definitions.append(tool.to_ollama_format())
        return definitions

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """도구를 실행하고 결과를 반환합니다."""
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Unknown tool: {name}", "success": False}

        try:
            result = tool.handler(**arguments)
            return {"result": result, "success": True, "tool": name}
        except Exception as e:
            logger.exception(f"[ToolRegistry] 도구 실행 실패: {name}")
            return {"error": str(e), "success": False, "tool": name}


# 전역 레지스트리 인스턴스
_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """전역 레지스트리를 반환합니다."""
    return _registry


def register_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    required: Optional[list[str]] = None,
) -> Callable:
    """도구 등록 데코레이터."""
    def decorator(func: Callable) -> Callable:
        tool = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=func,
            required=required or [],
        )
        _registry.register(tool)
        return func
    return decorator
