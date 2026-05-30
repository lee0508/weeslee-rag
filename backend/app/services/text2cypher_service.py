# 자연어 질문을 Cypher 쿼리로 변환하는 서비스
# -*- coding: utf-8 -*-
"""
Text2Cypher Service - LLM을 사용하여 자연어 질문을 Cypher 쿼리로 변환.

Phase 4에서 구현된 기능.
- Graph Schema 기반 쿼리 생성
- Cypher Guard로 읽기 전용 검증
- 쿼리 로그 저장
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.models.graph_schema import generate_schema_text
from app.services.cypher_guard import validate_cypher, sanitize_cypher, ValidationResult
from app.services.ollama import OllamaService


# 로그 저장 경로
PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOGS_DIR = PROJECT_ROOT / "data" / "logs" / "text2cypher"


@dataclass
class Text2CypherResult:
    """Text2Cypher 결과."""
    success: bool
    question: str
    cypher: Optional[str] = None
    validation: Optional[ValidationResult] = None
    error: Optional[str] = None
    model: str = ""
    generation_time_ms: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class CypherExecutionResult:
    """Cypher 실행 결과."""
    success: bool
    cypher: str
    results: list[dict] = field(default_factory=list)
    row_count: int = 0
    execution_time_ms: int = 0
    error: Optional[str] = None


class Text2CypherService:
    """Text2Cypher 서비스."""

    def __init__(self, ollama_service: Optional[OllamaService] = None):
        self.ollama = ollama_service or OllamaService()
        self._ensure_logs_dir()

    def _ensure_logs_dir(self) -> None:
        """로그 디렉토리 생성."""
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

    def _get_system_prompt(self) -> str:
        """Text2Cypher용 시스템 프롬프트 생성."""
        schema_text = generate_schema_text()

        return f"""You are a Cypher query generator for a Neo4j graph database.
Your task is to convert natural language questions into valid Cypher queries.

IMPORTANT RULES:
1. ONLY generate READ-ONLY queries (MATCH, RETURN, WHERE, ORDER BY, LIMIT)
2. NEVER use CREATE, MERGE, DELETE, SET, REMOVE, DROP, or any write operations
3. Follow the graph schema exactly - only use defined node types and relationships
4. Return ONLY the Cypher query, no explanations or markdown
5. If the question cannot be answered with the schema, return "NO_QUERY_POSSIBLE"

{schema_text}

When generating queries:
- Use Korean property names when searching (e.g., name: '기관명')
- For organization searches, try both name and abbreviation
- For project searches, try matching by name or year
- For document searches, use category or file_name
- Always limit results (LIMIT 10 by default)
"""

    def _extract_cypher_from_response(self, response: str) -> str:
        """LLM 응답에서 Cypher 쿼리 추출."""
        # 코드 블록에서 추출
        code_block_match = re.search(r"```(?:cypher)?\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
        if code_block_match:
            return code_block_match.group(1).strip()

        # MATCH로 시작하는 쿼리 추출
        match_query = re.search(r"(MATCH\s+.+?RETURN\s+.+?)(?:\n\n|$)", response, re.DOTALL | re.IGNORECASE)
        if match_query:
            return match_query.group(1).strip()

        # RETURN으로 시작하는 쿼리 추출 (카운트 등)
        return_query = re.search(r"(RETURN\s+.+?)(?:\n\n|$)", response, re.DOTALL | re.IGNORECASE)
        if return_query:
            return return_query.group(1).strip()

        # 그 외에는 전체 응답 반환 (정제 필요)
        return response.strip()

    async def generate_cypher(
        self,
        question: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
    ) -> Text2CypherResult:
        """
        자연어 질문을 Cypher 쿼리로 변환.

        Args:
            question: 자연어 질문
            model: 사용할 LLM 모델
            temperature: 생성 온도 (낮을수록 결정적)

        Returns:
            Text2CypherResult: 변환 결과
        """
        import time
        start_time = time.time()

        try:
            # LLM에게 Cypher 생성 요청
            system_prompt = self._get_system_prompt()
            user_prompt = f"Question: {question}\n\nGenerate a Cypher query:"

            response = await self.ollama.generate(
                prompt=user_prompt,
                system=system_prompt,
                model=model,
                temperature=temperature,
                max_tokens=1024,
            )

            generation_time_ms = int((time.time() - start_time) * 1000)

            # 응답에서 Cypher 추출
            cypher = self._extract_cypher_from_response(response)

            # NO_QUERY_POSSIBLE 처리
            if "NO_QUERY_POSSIBLE" in cypher.upper():
                return Text2CypherResult(
                    success=False,
                    question=question,
                    error="해당 질문은 현재 그래프 스키마로 답변할 수 없습니다.",
                    model=model or self.ollama.default_model,
                    generation_time_ms=generation_time_ms,
                )

            # Cypher Guard로 검증
            validation = validate_cypher(cypher)

            if not validation.is_valid:
                return Text2CypherResult(
                    success=False,
                    question=question,
                    cypher=cypher,
                    validation=validation,
                    error=validation.message,
                    model=model or self.ollama.default_model,
                    generation_time_ms=generation_time_ms,
                )

            # 성공
            return Text2CypherResult(
                success=True,
                question=question,
                cypher=validation.sanitized_query or cypher,
                validation=validation,
                model=model or self.ollama.default_model,
                generation_time_ms=generation_time_ms,
            )

        except Exception as e:
            return Text2CypherResult(
                success=False,
                question=question,
                error=f"Cypher 생성 실패: {str(e)}",
                model=model or self.ollama.default_model,
                generation_time_ms=int((time.time() - start_time) * 1000),
            )

    def execute_cypher_on_jsonl(
        self,
        cypher: str,
        nodes: list[dict],
        edges: list[dict],
    ) -> CypherExecutionResult:
        """
        JSONL 기반 그래프 데이터에서 Cypher 쿼리 실행 (시뮬레이션).

        실제 Neo4j 없이 JSONL 데이터에서 쿼리를 시뮬레이션한다.
        간단한 MATCH-RETURN 패턴만 지원.

        Args:
            cypher: 실행할 Cypher 쿼리
            nodes: 노드 목록
            edges: 엣지 목록

        Returns:
            CypherExecutionResult: 실행 결과
        """
        import time
        start_time = time.time()

        try:
            # 쿼리 파싱 (매우 단순한 구현)
            cypher_upper = cypher.upper()

            results = []

            # 기관 검색 패턴
            org_match = re.search(r"Organization.*?name:\s*['\"](.+?)['\"]", cypher, re.IGNORECASE)
            if org_match:
                org_name = org_match.group(1)
                for node in nodes:
                    if node.get("type") == "organization":
                        if org_name.lower() in node.get("label", "").lower():
                            results.append(node)

            # 프로젝트 검색 패턴
            proj_match = re.search(r"Project.*?(?:name:\s*['\"](.+?)['\"]|year:\s*(\d+))", cypher, re.IGNORECASE)
            if proj_match:
                name_filter = proj_match.group(1)
                year_filter = proj_match.group(2)

                for node in nodes:
                    if node.get("type") == "project":
                        if name_filter and name_filter.lower() in node.get("label", "").lower():
                            results.append(node)
                        elif year_filter and node.get("year") == year_filter:
                            results.append(node)

            # 문서 검색 패턴
            doc_match = re.search(r"Document.*?category:\s*['\"](.+?)['\"]", cypher, re.IGNORECASE)
            if doc_match:
                category = doc_match.group(1)
                for node in nodes:
                    if node.get("type") == "document" and node.get("category", "").lower() == category.lower():
                        results.append(node)

            # LIMIT 처리
            limit_match = re.search(r"LIMIT\s+(\d+)", cypher, re.IGNORECASE)
            if limit_match:
                limit = int(limit_match.group(1))
                results = results[:limit]

            # 결과가 없으면 전체 노드에서 샘플
            if not results and "MATCH" in cypher_upper:
                # 노드 타입 추출
                type_match = re.search(r":\s*(Organization|Project|Document|Keyword|Technology)", cypher, re.IGNORECASE)
                if type_match:
                    node_type = type_match.group(1).lower()
                    results = [n for n in nodes if n.get("type") == node_type][:10]

            execution_time_ms = int((time.time() - start_time) * 1000)

            return CypherExecutionResult(
                success=True,
                cypher=cypher,
                results=results,
                row_count=len(results),
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            return CypherExecutionResult(
                success=False,
                cypher=cypher,
                error=f"쿼리 실행 실패: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def save_log(
        self,
        question: str,
        cypher: Optional[str],
        success: bool,
        error: Optional[str] = None,
        results_count: int = 0,
        execution_time_ms: int = 0,
    ) -> str:
        """
        쿼리 로그 저장.

        Args:
            question: 원본 질문
            cypher: 생성된 Cypher 쿼리
            success: 성공 여부
            error: 오류 메시지
            results_count: 결과 수
            execution_time_ms: 실행 시간

        Returns:
            로그 파일 경로
        """
        timestamp = datetime.now()
        log_entry = {
            "timestamp": timestamp.isoformat(),
            "question": question,
            "cypher": cypher,
            "success": success,
            "error": error,
            "results_count": results_count,
            "execution_time_ms": execution_time_ms,
        }

        # 일별 로그 파일
        log_file = LOGS_DIR / f"text2cypher_{timestamp.strftime('%Y%m%d')}.jsonl"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        return str(log_file)

    def get_logs(
        self,
        date: Optional[str] = None,
        limit: int = 100,
        success_only: bool = False,
        error_only: bool = False,
    ) -> list[dict]:
        """
        쿼리 로그 조회.

        Args:
            date: 날짜 (YYYYMMDD 형식, 없으면 최근)
            limit: 최대 로그 수
            success_only: 성공 로그만
            error_only: 실패 로그만

        Returns:
            로그 목록
        """
        logs = []

        if date:
            log_files = [LOGS_DIR / f"text2cypher_{date}.jsonl"]
        else:
            log_files = sorted(LOGS_DIR.glob("text2cypher_*.jsonl"), reverse=True)

        for log_file in log_files:
            if not log_file.exists():
                continue

            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)

                        # 필터 적용
                        if success_only and not entry.get("success"):
                            continue
                        if error_only and entry.get("success"):
                            continue

                        logs.append(entry)

                        if len(logs) >= limit:
                            break
                    except json.JSONDecodeError:
                        continue

            if len(logs) >= limit:
                break

        # 최신순 정렬
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return logs[:limit]


# 싱글톤 인스턴스
_service: Optional[Text2CypherService] = None


def get_text2cypher_service() -> Text2CypherService:
    """Text2Cypher 서비스 싱글톤 반환."""
    global _service
    if _service is None:
        _service = Text2CypherService()
    return _service
