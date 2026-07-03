# Cypher 쿼리 보안 검증 서비스
# -*- coding: utf-8 -*-
"""
Cypher Guard - 읽기 전용 쿼리만 허용하는 보안 검증 서비스.

Phase 5에서 정의된 금지/허용 키워드를 기반으로 Cypher 쿼리를 검증한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CypherValidationResult(Enum):
    """검증 결과 유형."""
    VALID = "valid"
    BLOCKED_KEYWORD = "blocked_keyword"
    SYNTAX_ERROR = "syntax_error"
    EMPTY_QUERY = "empty_query"


@dataclass
class ValidationResult:
    """검증 결과."""
    is_valid: bool
    result_type: CypherValidationResult
    message: str
    blocked_keyword: Optional[str] = None
    sanitized_query: Optional[str] = None


# 금지 키워드 (대소문자 무시)
BLOCKED_KEYWORDS = [
    "CREATE",
    "MERGE",
    "DELETE",
    "DETACH DELETE",
    "SET",
    "REMOVE",
    "DROP",
    "LOAD CSV",
    "CALL DBMS",
    "CALL APOC",
    "CALL DB.",
    "CALL GDS.",
    "FOREACH",
    "UNWIND",  # 데이터 수정에 사용될 수 있음
]

# 허용 키워드
ALLOWED_KEYWORDS = [
    "MATCH",
    "OPTIONAL MATCH",
    "WHERE",
    "WITH",
    "RETURN",
    "ORDER BY",
    "LIMIT",
    "SKIP",
    "DISTINCT",
    "AS",
    "AND",
    "OR",
    "NOT",
    "IN",
    "IS NULL",
    "IS NOT NULL",
    "CONTAINS",
    "STARTS WITH",
    "ENDS WITH",
    "COUNT",
    "SUM",
    "AVG",
    "MIN",
    "MAX",
    "COLLECT",
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "UNION",
    "UNION ALL",
]

# 위험한 패턴 (정규식)
DANGEROUS_PATTERNS = [
    r"//.*$",  # 주석 (숨겨진 명령 방지)
    r"/\*.*?\*/",  # 블록 주석
    r";\s*\w",  # 세미콜론 후 새 명령 (다중 쿼리)
]


def validate_cypher(query: str) -> ValidationResult:
    """
    Cypher 쿼리를 검증하여 읽기 전용인지 확인한다.

    Args:
        query: 검증할 Cypher 쿼리

    Returns:
        ValidationResult: 검증 결과
    """
    if not query or not query.strip():
        return ValidationResult(
            is_valid=False,
            result_type=CypherValidationResult.EMPTY_QUERY,
            message="쿼리가 비어 있습니다.",
        )

    # 쿼리 정규화
    normalized = query.strip().upper()

    # 금지 키워드 검사
    for keyword in BLOCKED_KEYWORDS:
        # 단어 경계로 검사 (부분 일치 방지)
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, normalized, re.IGNORECASE):
            return ValidationResult(
                is_valid=False,
                result_type=CypherValidationResult.BLOCKED_KEYWORD,
                message=f"금지된 키워드 '{keyword}'가 포함되어 있습니다. 읽기 전용 쿼리만 허용됩니다.",
                blocked_keyword=keyword,
            )

    # 위험한 패턴 검사
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, query, re.MULTILINE | re.DOTALL):
            return ValidationResult(
                is_valid=False,
                result_type=CypherValidationResult.SYNTAX_ERROR,
                message="보안상 허용되지 않는 패턴이 포함되어 있습니다.",
            )

    # 다중 쿼리 검사 (세미콜론으로 구분된 여러 쿼리)
    statements = [s.strip() for s in query.split(";") if s.strip()]
    if len(statements) > 1:
        return ValidationResult(
            is_valid=False,
            result_type=CypherValidationResult.SYNTAX_ERROR,
            message="다중 쿼리는 허용되지 않습니다. 하나의 쿼리만 실행 가능합니다.",
        )

    # MATCH 또는 RETURN이 있어야 함 (기본적인 읽기 쿼리)
    if not re.search(r"\b(MATCH|RETURN)\b", normalized):
        return ValidationResult(
            is_valid=False,
            result_type=CypherValidationResult.SYNTAX_ERROR,
            message="유효한 읽기 쿼리가 아닙니다. MATCH 또는 RETURN이 필요합니다.",
        )

    # 쿼리 정제 (앞뒤 공백, 세미콜론 제거)
    sanitized = query.strip().rstrip(";").strip()

    return ValidationResult(
        is_valid=True,
        result_type=CypherValidationResult.VALID,
        message="유효한 읽기 전용 쿼리입니다.",
        sanitized_query=sanitized,
    )


def sanitize_cypher(query: str) -> str:
    """
    Cypher 쿼리를 정제한다 (공백, 세미콜론 정리).

    Args:
        query: 정제할 Cypher 쿼리

    Returns:
        정제된 쿼리
    """
    if not query:
        return ""

    # 여러 줄의 공백을 단일 공백으로
    sanitized = re.sub(r"\s+", " ", query.strip())
    # 세미콜론 제거
    sanitized = sanitized.rstrip(";").strip()

    return sanitized


def extract_return_fields(query: str) -> list[str]:
    """
    Cypher 쿼리에서 RETURN 절의 필드를 추출한다.

    Args:
        query: Cypher 쿼리

    Returns:
        반환 필드 목록
    """
    # RETURN 절 찾기
    match = re.search(r"\bRETURN\s+(.+?)(?:\s+ORDER\s+BY|\s+LIMIT|\s+SKIP|$)", query, re.IGNORECASE | re.DOTALL)
    if not match:
        return []

    return_clause = match.group(1)

    # AS 별칭 추출 또는 원래 필드명
    fields = []
    for part in return_clause.split(","):
        part = part.strip()
        # AS 별칭이 있으면 별칭 사용
        as_match = re.search(r"\bAS\s+(\w+)\s*$", part, re.IGNORECASE)
        if as_match:
            fields.append(as_match.group(1))
        else:
            # 함수나 속성 접근 정리
            clean = re.sub(r"[^a-zA-Z0-9_.]", "", part.split(".")[-1])
            if clean:
                fields.append(clean)

    return fields
