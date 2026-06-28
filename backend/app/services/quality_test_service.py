# Publish 전 품질 테스트 서비스 - 동적 쿼리 생성 및 검색 품질 검증
"""
Snapshot Publish 전 검색 품질을 검증하는 서비스.

주요 기능:
  - generate_test_queries(): 데이터셋 메타데이터 기반 동적 테스트 쿼리 생성
  - run_quality_test(): FAISS 검색 테스트 실행 및 점수 계산
  - evaluate_search_quality(): 종합 품질 평가

사용 예시:
    from app.services.quality_test_service import run_quality_test

    report = await run_quality_test(
        snapshot_id="snapshot_20260627_rag_source_V1",
        test_queries=[{"query": "정보화전략계획", "category": "제안서"}],
    )
    if report["can_activate"]:
        # 활성화 진행
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session


# 기본 테스트 쿼리 (폴백용)
DEFAULT_TEST_QUERIES = [
    {"query": "정보화전략계획 ISP 수립 방법론", "category": "제안서"},
    {"query": "제안요청서 핵심 요구사항", "category": "RFP"},
    {"query": "클라우드 마이그레이션 전략", "category": "제안서"},
    {"query": "프로젝트 추진 일정 및 인력 구성", "category": "산출물"},
    {"query": "기대효과 및 성과지표", "category": "제안서"},
    {"query": "정보시스템 현황 분석", "category": "RFP"},
    {"query": "데이터 통합 아키텍처", "category": "제안서"},
    {"query": "보안 요구사항 및 대응 방안", "category": "제안서"},
]

# 품질 임계값
MIN_QUALITY_SCORE = 0.40
MIN_RESPONSE_RATE = 0.60
MIN_RESULT_COUNT = 1


def generate_test_queries(
    db: Session,
    source_id: str,
    count: int = 10,
) -> list[dict[str, Any]]:
    """
    데이터셋 메타데이터 기반 동적 테스트 쿼리 생성.

    Args:
        db: 데이터베이스 세션
        source_id: Document Source ID
        count: 생성할 쿼리 수

    Returns:
        테스트 쿼리 목록
    """
    from app.models.document_metadata import DocumentMetadata

    queries = []

    try:
        # 1. 상위 기관명 추출
        orgs = db.query(
            DocumentMetadata.organization_name,
            func.count().label("cnt")
        ).filter(
            DocumentMetadata.source_id == source_id,
            DocumentMetadata.organization_name.isnot(None),
            DocumentMetadata.organization_name != "",
        ).group_by(
            DocumentMetadata.organization_name
        ).order_by(
            func.count().desc()
        ).limit(3).all()

        for org, _ in orgs:
            if org and org.strip():
                queries.append({
                    "query": f"{org} 관련 제안서",
                    "category": "organization",
                    "source": "dynamic",
                })

        # 2. 상위 프로젝트명 추출
        projects = db.query(
            DocumentMetadata.project_name,
            func.count().label("cnt")
        ).filter(
            DocumentMetadata.source_id == source_id,
            DocumentMetadata.project_name.isnot(None),
            DocumentMetadata.project_name != "",
        ).group_by(
            DocumentMetadata.project_name
        ).order_by(
            func.count().desc()
        ).limit(3).all()

        for proj, _ in projects:
            if proj and proj.strip():
                # 프로젝트명에서 핵심 키워드 추출
                keywords = proj.split()[:3]
                if keywords:
                    queries.append({
                        "query": " ".join(keywords) + " 사업",
                        "category": "project",
                        "source": "dynamic",
                    })

        # 3. 문서 카테고리별 쿼리 추가
        categories = db.query(
            DocumentMetadata.category,
            func.count().label("cnt")
        ).filter(
            DocumentMetadata.source_id == source_id,
            DocumentMetadata.category.isnot(None),
        ).group_by(
            DocumentMetadata.category
        ).order_by(
            func.count().desc()
        ).limit(3).all()

        category_queries = {
            "RFP": "제안요청서 요구사항",
            "제안서": "정보화전략계획 방법론",
            "산출물": "프로젝트 산출물 현황",
            "proposal": "제안서 핵심 내용",
            "deliverable": "산출물 목록",
        }

        for cat, _ in categories:
            if cat and cat in category_queries:
                queries.append({
                    "query": category_queries[cat],
                    "category": cat,
                    "source": "dynamic",
                })

    except Exception:
        pass

    # 4. 기본 쿼리로 부족분 채우기
    if len(queries) < count:
        for dq in DEFAULT_TEST_QUERIES:
            if len(queries) >= count:
                break
            # 중복 방지
            if not any(q["query"] == dq["query"] for q in queries):
                queries.append({**dq, "source": "default"})

    return queries[:count]


async def run_quality_test(
    snapshot_id: str,
    test_queries: list[dict[str, Any]],
    top_k: int = 5,
    min_score: float = 0.3,
) -> dict[str, Any]:
    """
    FAISS 검색 테스트 실행 및 점수 계산.

    Args:
        snapshot_id: 테스트할 Snapshot ID ("active"이면 활성 snapshot 사용)
        test_queries: 테스트 쿼리 목록
        top_k: 각 쿼리당 검색할 문서 수
        min_score: 성공으로 간주할 최소 유사도 점수

    Returns:
        품질 테스트 결과
    """
    from app.services.rag_runtime import run_rag_query, get_active_snapshot

    # "active" 전달 시 실제 활성 snapshot ID로 변환
    resolved_snapshot = snapshot_id
    if snapshot_id == "active":
        resolved_snapshot = get_active_snapshot()
        if not resolved_snapshot:
            resolved_snapshot = None  # run_rag_query가 기본값 사용

    results = []
    total_score = 0.0
    response_count = 0
    passed_count = 0

    for q in test_queries:
        query_text = q.get("query", "")
        if not query_text:
            continue

        try:
            # RAG 검색 실행 (LLM 답변 생성 없이 검색만)
            payload = run_rag_query(
                query=query_text,
                original_query=query_text,
                top_k=top_k,
                top_docs=3,
                answer_provider="none",
                answer_model="",
                snapshot=resolved_snapshot,
                mode="general",
                category=q.get("category"),
                organization=None,
                year=None,
                max_chunks_per_doc=3,
            )

            docs = payload.get("documents", [])
            # best_score 또는 score 키 지원
            top_score = docs[0].get("best_score", docs[0].get("score", 0)) if docs else 0
            result_count = len(docs)

            # 성공 판정
            passed = result_count >= MIN_RESULT_COUNT and top_score >= min_score

            results.append({
                "query": query_text,
                "category": q.get("category"),
                "source": q.get("source", "unknown"),
                "result_count": result_count,
                "top_score": round(top_score, 4),
                "passed": passed,
                "top_document": docs[0].get("file_name") if docs else None,
            })

            if result_count > 0:
                response_count += 1
                total_score += top_score

            if passed:
                passed_count += 1

        except Exception as e:
            results.append({
                "query": query_text,
                "category": q.get("category"),
                "error": str(e),
                "passed": False,
            })

    # 종합 점수 계산
    query_count = len(test_queries)
    overall_score = (total_score / query_count) if query_count > 0 else 0
    response_rate = (response_count / query_count) if query_count > 0 else 0
    pass_rate = (passed_count / query_count) if query_count > 0 else 0

    # 활성화 가능 여부 판정
    can_activate = (
        overall_score >= MIN_QUALITY_SCORE
        and response_rate >= MIN_RESPONSE_RATE
    )

    return {
        "snapshot_id": resolved_snapshot or snapshot_id,
        "test_count": query_count,
        "overall_score": round(overall_score, 4),
        "response_rate": round(response_rate, 4),
        "pass_rate": round(pass_rate, 4),
        "passed_count": passed_count,
        "response_count": response_count,
        "can_activate": can_activate,
        "thresholds": {
            "min_quality_score": MIN_QUALITY_SCORE,
            "min_response_rate": MIN_RESPONSE_RATE,
            "min_score_per_query": min_score,
        },
        "results": results,
        "tested_at": datetime.now().isoformat(),
    }


def evaluate_search_quality(
    test_report: dict[str, Any]
) -> dict[str, Any]:
    """
    테스트 결과를 분석하여 개선 권고사항 생성.

    Args:
        test_report: run_quality_test() 결과

    Returns:
        분석 결과 및 권고사항
    """
    recommendations = []
    severity = "info"

    overall_score = test_report.get("overall_score", 0)
    response_rate = test_report.get("response_rate", 0)
    pass_rate = test_report.get("pass_rate", 0)

    # 품질 점수 분석
    if overall_score < MIN_QUALITY_SCORE * 0.5:
        recommendations.append({
            "issue": "매우 낮은 유사도 점수",
            "detail": f"평균 유사도 {overall_score:.1%}는 기준 {MIN_QUALITY_SCORE:.0%}의 절반 미만입니다.",
            "action": "임베딩 모델을 한국어 최적화 모델(bge-m3)로 교체하거나, 인덱스를 재생성하세요.",
        })
        severity = "critical"
    elif overall_score < MIN_QUALITY_SCORE:
        recommendations.append({
            "issue": "낮은 유사도 점수",
            "detail": f"평균 유사도 {overall_score:.1%}는 기준 {MIN_QUALITY_SCORE:.0%} 미만입니다.",
            "action": "청크 크기를 조정하거나, 문서 품질을 점검하세요.",
        })
        severity = "warning"

    # 응답률 분석
    if response_rate < MIN_RESPONSE_RATE:
        recommendations.append({
            "issue": "낮은 응답률",
            "detail": f"응답률 {response_rate:.1%}는 기준 {MIN_RESPONSE_RATE:.0%} 미만입니다.",
            "action": "인덱싱된 문서 수를 확인하고, 누락된 문서를 추가하세요.",
        })
        if severity != "critical":
            severity = "warning"

    # 통과율 분석
    if pass_rate < 0.5:
        recommendations.append({
            "issue": "낮은 테스트 통과율",
            "detail": f"통과율 {pass_rate:.1%}입니다. 절반 이상의 쿼리가 품질 기준을 충족하지 못했습니다.",
            "action": "실패한 쿼리 유형을 분석하여 해당 카테고리 문서를 보강하세요.",
        })

    # 성공 시
    if not recommendations:
        recommendations.append({
            "issue": "품질 기준 충족",
            "detail": f"모든 지표가 기준을 충족합니다. (점수: {overall_score:.1%}, 응답률: {response_rate:.1%})",
            "action": "Publish를 진행해도 좋습니다.",
        })
        severity = "success"

    return {
        "severity": severity,
        "can_activate": test_report.get("can_activate", False),
        "summary": {
            "overall_score": overall_score,
            "response_rate": response_rate,
            "pass_rate": pass_rate,
        },
        "recommendations": recommendations,
    }
