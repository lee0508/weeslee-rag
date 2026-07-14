# 데이터 구조 분석 및 품질 진단 도구
"""
데이터 구조 분석, 품질 진단, 연계 가능성 평가를 수행하는 도구들.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.services.tool_registry import register_tool

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CHUNKS_DIR = PROJECT_ROOT / "data" / "staged" / "chunks"
METADATA_DIR = PROJECT_ROOT / "data" / "indexes" / "faiss"


@register_tool(
    name="analyze_data_structure",
    description="데이터셋의 구조를 분석합니다. 스키마, 필드 목록, 데이터 유형, 메타데이터 구성을 확인합니다.",
    parameters={
        "dataset_name": {
            "type": "string",
            "description": "분석할 데이터셋 이름 (예: 지속가능발전포털, SDGs, K-SDGs)",
        },
        "analysis_type": {
            "type": "string",
            "enum": ["schema", "fields", "relationships", "all"],
            "description": "분석 유형: schema(스키마), fields(필드목록), relationships(관계), all(전체)",
        },
    },
    required=["dataset_name"],
)
def analyze_data_structure(
    dataset_name: str,
    analysis_type: str = "all",
) -> dict[str, Any]:
    """데이터셋 구조를 분석합니다."""
    try:
        # 청크 메타데이터에서 데이터 구조 분석
        chunks_info = _analyze_chunks_structure(dataset_name)

        # 문서 메타데이터 분석
        doc_info = _analyze_document_metadata(dataset_name)

        result = {
            "dataset_name": dataset_name,
            "analysis_type": analysis_type,
            "structure": {
                "total_documents": doc_info.get("total", 0),
                "total_chunks": chunks_info.get("total_chunks", 0),
                "categories": doc_info.get("categories", []),
                "document_types": doc_info.get("document_types", []),
            },
            "schema": {
                "fields": chunks_info.get("fields", []),
                "metadata_fields": doc_info.get("metadata_fields", []),
            },
            "data_characteristics": {
                "is_structured": chunks_info.get("is_structured", False),
                "has_hierarchy": chunks_info.get("has_hierarchy", False),
                "linkable_fields": chunks_info.get("linkable_fields", []),
            },
        }

        if analysis_type == "schema":
            return {"schema": result["schema"]}
        elif analysis_type == "fields":
            return {"fields": result["schema"]["fields"]}
        elif analysis_type == "relationships":
            return {"relationships": result["data_characteristics"]}

        return result

    except Exception as e:
        logger.exception(f"[analyze_data_structure] 실패: {dataset_name}")
        return {"error": str(e), "dataset_name": dataset_name}


@register_tool(
    name="diagnose_data_quality",
    description="데이터 품질을 진단합니다. 구조화 수준, 완전성, 일관성, 연계 가능성을 평가합니다.",
    parameters={
        "dataset_name": {
            "type": "string",
            "description": "진단할 데이터셋 이름",
        },
        "criteria": {
            "type": "array",
            "items": {"type": "string"},
            "description": "진단 기준: completeness, consistency, structure_level, linkability",
        },
    },
    required=["dataset_name"],
)
def diagnose_data_quality(
    dataset_name: str,
    criteria: Optional[list[str]] = None,
) -> dict[str, Any]:
    """데이터 품질을 진단합니다."""
    if criteria is None:
        criteria = ["completeness", "consistency", "structure_level", "linkability"]

    try:
        diagnosis = {
            "dataset_name": dataset_name,
            "criteria": criteria,
            "results": {},
            "overall_score": 0.0,
            "recommendations": [],
        }

        chunks_info = _analyze_chunks_structure(dataset_name)
        doc_info = _analyze_document_metadata(dataset_name)

        scores = []

        if "completeness" in criteria:
            completeness = _evaluate_completeness(chunks_info, doc_info)
            diagnosis["results"]["completeness"] = completeness
            scores.append(completeness["score"])

        if "consistency" in criteria:
            consistency = _evaluate_consistency(chunks_info, doc_info)
            diagnosis["results"]["consistency"] = consistency
            scores.append(consistency["score"])

        if "structure_level" in criteria:
            structure = _evaluate_structure_level(chunks_info, doc_info)
            diagnosis["results"]["structure_level"] = structure
            scores.append(structure["score"])

            if structure["score"] < 0.5:
                diagnosis["recommendations"].append(
                    "데이터가 단순 게시형입니다. 목표-지표-정책과제-평가 연결 구조화가 필요합니다."
                )

        if "linkability" in criteria:
            linkability = _evaluate_linkability(chunks_info, doc_info)
            diagnosis["results"]["linkability"] = linkability
            scores.append(linkability["score"])

            if linkability["score"] < 0.5:
                diagnosis["recommendations"].append(
                    "유관기관 데이터와 연계 가능한 식별자(코드, ID)가 부족합니다."
                )

        diagnosis["overall_score"] = sum(scores) / len(scores) if scores else 0.0

        return diagnosis

    except Exception as e:
        logger.exception(f"[diagnose_data_quality] 실패: {dataset_name}")
        return {"error": str(e), "dataset_name": dataset_name}


@register_tool(
    name="analyze_data_linkage",
    description="데이터 연계 가능성을 분석합니다. 유관기관 데이터와의 연결점, 공통 식별자, API 연동 가능성을 평가합니다.",
    parameters={
        "dataset_name": {
            "type": "string",
            "description": "분석할 데이터셋 이름",
        },
        "target_systems": {
            "type": "array",
            "items": {"type": "string"},
            "description": "연계 대상 시스템 목록 (예: 통계청, 환경부, 기획재정부)",
        },
    },
    required=["dataset_name"],
)
def analyze_data_linkage(
    dataset_name: str,
    target_systems: Optional[list[str]] = None,
) -> dict[str, Any]:
    """데이터 연계 가능성을 분석합니다."""
    if target_systems is None:
        target_systems = ["통계청", "환경부", "기획재정부", "행정안전부"]

    try:
        chunks_info = _analyze_chunks_structure(dataset_name)

        linkage_analysis = {
            "dataset_name": dataset_name,
            "target_systems": target_systems,
            "linkable_identifiers": [],
            "potential_connections": [],
            "integration_recommendations": [],
        }

        # 연계 가능 식별자 탐지
        linkable_fields = chunks_info.get("linkable_fields", [])
        for field in linkable_fields:
            linkage_analysis["linkable_identifiers"].append({
                "field": field,
                "type": _infer_identifier_type(field),
                "coverage": "partial",
            })

        # 시스템별 연계 가능성
        for system in target_systems:
            connection = {
                "system": system,
                "connection_type": "api",
                "feasibility": "medium",
                "required_mappings": [],
            }

            if system == "통계청":
                connection["required_mappings"] = ["통계분류코드", "기관코드"]
            elif system == "환경부":
                connection["required_mappings"] = ["환경지표코드", "측정지점코드"]

            linkage_analysis["potential_connections"].append(connection)

        # 통합 권장사항
        linkage_analysis["integration_recommendations"] = [
            "공통 코드체계(기관코드, 지역코드) 표준화 필요",
            "API 연동을 위한 인증 키 및 엔드포인트 정의 필요",
            "데이터 갱신 주기 및 동기화 정책 수립 필요",
        ]

        return linkage_analysis

    except Exception as e:
        logger.exception(f"[analyze_data_linkage] 실패: {dataset_name}")
        return {"error": str(e), "dataset_name": dataset_name}


def _analyze_chunks_structure(dataset_name: str) -> dict[str, Any]:
    """청크 데이터에서 구조 정보를 추출합니다."""
    result = {
        "total_chunks": 0,
        "fields": [],
        "is_structured": False,
        "has_hierarchy": False,
        "linkable_fields": [],
    }

    # 청크 파일 탐색
    for chunk_file in CHUNKS_DIR.glob("*.jsonl"):
        try:
            with open(chunk_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    result["total_chunks"] += 1

                    # 필드 수집
                    for key in chunk.keys():
                        if key not in result["fields"]:
                            result["fields"].append(key)

                    # 구조화 여부 판단
                    text = chunk.get("text", "")
                    if any(marker in text for marker in ["목표:", "지표:", "과제:", "평가:"]):
                        result["is_structured"] = True

                    # 연계 가능 필드 탐지
                    metadata = chunk.get("metadata", {})
                    for key, value in metadata.items():
                        if any(id_hint in key.lower() for id_hint in ["code", "id", "코드", "번호"]):
                            if key not in result["linkable_fields"]:
                                result["linkable_fields"].append(key)

                    # 샘플링 (처음 1000개만)
                    if result["total_chunks"] >= 1000:
                        break
        except Exception:
            continue

    return result


def _analyze_document_metadata(dataset_name: str) -> dict[str, Any]:
    """문서 메타데이터를 분석합니다."""
    result = {
        "total": 0,
        "categories": [],
        "document_types": [],
        "metadata_fields": [],
    }

    # 메타데이터 파일 탐색
    for meta_file in METADATA_DIR.glob("*_metadata.jsonl"):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    meta = json.loads(line)
                    result["total"] += 1

                    # 카테고리 수집
                    category = meta.get("category", "")
                    if category and category not in result["categories"]:
                        result["categories"].append(category)

                    # 문서 유형 수집
                    doc_type = meta.get("document_type", meta.get("type", ""))
                    if doc_type and doc_type not in result["document_types"]:
                        result["document_types"].append(doc_type)

                    # 메타데이터 필드 수집
                    for key in meta.keys():
                        if key not in result["metadata_fields"]:
                            result["metadata_fields"].append(key)

                    if result["total"] >= 500:
                        break
        except Exception:
            continue

    return result


def _evaluate_completeness(chunks_info: dict, doc_info: dict) -> dict[str, Any]:
    """완전성을 평가합니다."""
    total_docs = doc_info.get("total", 0)
    total_chunks = chunks_info.get("total_chunks", 0)

    score = 0.0
    if total_docs > 0:
        avg_chunks = total_chunks / total_docs if total_docs > 0 else 0
        score = min(1.0, avg_chunks / 10)  # 문서당 10개 청크 기준

    return {
        "score": score,
        "total_documents": total_docs,
        "total_chunks": total_chunks,
        "avg_chunks_per_doc": total_chunks / total_docs if total_docs > 0 else 0,
    }


def _evaluate_consistency(chunks_info: dict, doc_info: dict) -> dict[str, Any]:
    """일관성을 평가합니다."""
    fields = chunks_info.get("fields", [])
    required_fields = ["text", "chunk_id", "document_id"]

    present = sum(1 for f in required_fields if f in fields)
    score = present / len(required_fields) if required_fields else 0.0

    return {
        "score": score,
        "required_fields": required_fields,
        "present_fields": [f for f in required_fields if f in fields],
        "missing_fields": [f for f in required_fields if f not in fields],
    }


def _evaluate_structure_level(chunks_info: dict, doc_info: dict) -> dict[str, Any]:
    """구조화 수준을 평가합니다."""
    is_structured = chunks_info.get("is_structured", False)
    has_hierarchy = chunks_info.get("has_hierarchy", False)
    categories = doc_info.get("categories", [])

    score = 0.0
    if is_structured:
        score += 0.4
    if has_hierarchy:
        score += 0.3
    if len(categories) >= 3:
        score += 0.3

    structure_type = "단순 게시형"
    if is_structured and has_hierarchy:
        structure_type = "완전 구조화"
    elif is_structured:
        structure_type = "부분 구조화"

    return {
        "score": score,
        "structure_type": structure_type,
        "is_structured": is_structured,
        "has_hierarchy": has_hierarchy,
        "category_count": len(categories),
    }


def _evaluate_linkability(chunks_info: dict, doc_info: dict) -> dict[str, Any]:
    """연계 가능성을 평가합니다."""
    linkable_fields = chunks_info.get("linkable_fields", [])

    score = min(1.0, len(linkable_fields) / 5)  # 5개 이상이면 만점

    return {
        "score": score,
        "linkable_field_count": len(linkable_fields),
        "linkable_fields": linkable_fields,
        "can_link_external": len(linkable_fields) >= 2,
    }


def _infer_identifier_type(field: str) -> str:
    """필드명에서 식별자 유형을 추론합니다."""
    field_lower = field.lower()
    if "기관" in field_lower or "org" in field_lower:
        return "기관코드"
    if "지역" in field_lower or "region" in field_lower:
        return "지역코드"
    if "지표" in field_lower or "indicator" in field_lower:
        return "지표코드"
    return "일반코드"
