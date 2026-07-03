# Dataset Builder용 공통 문서 쿼리 필터 - 반복되는 DB 필터 로직 통합
"""
Dataset Builder Step 4~10에서 반복 사용되는 문서 쿼리 필터.

주요 기능:
  - rag_ready_filter(): RAG 포함 대상 문서 필터
  - source_filter(): source_id 기반 필터
  - build_document_query(): 문서 조회 쿼리 빌더

사용 예시:
    from app.services.dataset_document_query import rag_ready_filter, build_document_query

    # 필터만 사용
    query = db.query(DocumentMetadata).filter(*rag_ready_filter())

    # 전체 쿼리 빌더 사용
    documents = build_document_query(db, source_id="rag_source").all()
"""
from __future__ import annotations

from typing import Optional, List, Any

from sqlalchemy.orm import Session, Query

from app.models.document_metadata import DocumentMetadata, MetaStatus


def rag_ready_filter() -> tuple:
    """
    RAG 인덱싱 대상 문서 필터 조건 반환.

    조건:
    - meta_status = METADATA_REVIEWED (검수 완료)
    - include_in_rag = True (RAG 포함)
    - is_excluded = False (제외되지 않음)
    - removed_at IS NULL (삭제되지 않음)

    Returns:
        filter 조건 튜플 (query.filter(*rag_ready_filter()) 형태로 사용)
    """
    return (
        DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
        DocumentMetadata.include_in_rag.is_(True),
        DocumentMetadata.is_excluded.is_(False),
        DocumentMetadata.removed_at.is_(None),
    )


def active_document_filter() -> tuple:
    """
    활성 문서 필터 (삭제/제외되지 않은 모든 문서).

    Returns:
        filter 조건 튜플
    """
    return (
        DocumentMetadata.is_excluded.is_(False),
        DocumentMetadata.removed_at.is_(None),
    )


def source_filter(source_id: Optional[str]) -> tuple:
    """
    source_id 기반 필터.

    Args:
        source_id: Document Source ID (None이면 빈 튜플 반환)

    Returns:
        filter 조건 튜플
    """
    if source_id:
        return (DocumentMetadata.source_id == source_id,)
    return ()


def status_filter(status: str) -> tuple:
    """
    메타 상태 필터.

    Args:
        status: MetaStatus 값 (예: "REGISTERED", "METADATA_REVIEWED")

    Returns:
        filter 조건 튜플
    """
    return (DocumentMetadata.meta_status == status,)


def document_id_filter(document_ids: Optional[List[int]]) -> tuple:
    """
    document_id 목록 필터.

    Args:
        document_ids: 문서 ID 목록 (None이면 빈 튜플 반환)

    Returns:
        filter 조건 튜플
    """
    if document_ids:
        return (DocumentMetadata.document_id.in_(document_ids),)
    return ()


def category_filter(category: Optional[str]) -> tuple:
    """
    카테고리 필터.

    Args:
        category: 문서 카테고리 (None이면 빈 튜플 반환)

    Returns:
        filter 조건 튜플
    """
    if category:
        return (DocumentMetadata.category == category,)
    return ()


def build_document_query(
    db: Session,
    source_id: Optional[str] = None,
    document_ids: Optional[List[int]] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    rag_ready_only: bool = True,
    include_excluded: bool = False,
) -> Query:
    """
    문서 조회 쿼리 빌더.

    Args:
        db: 데이터베이스 세션
        source_id: Document Source ID
        document_ids: 특정 문서 ID 목록
        status: 메타 상태 필터 (None이면 rag_ready_only에 따라 결정)
        category: 카테고리 필터
        rag_ready_only: True면 RAG 대상만, False면 모든 활성 문서
        include_excluded: True면 제외된 문서도 포함

    Returns:
        SQLAlchemy Query 객체
    """
    query = db.query(DocumentMetadata)

    # 기본 필터
    if rag_ready_only:
        query = query.filter(*rag_ready_filter())
    elif not include_excluded:
        query = query.filter(*active_document_filter())

    # 추가 필터
    if source_id:
        query = query.filter(*source_filter(source_id))

    if document_ids:
        query = query.filter(*document_id_filter(document_ids))

    if status:
        query = query.filter(*status_filter(status))

    if category:
        query = query.filter(*category_filter(category))

    return query


def count_documents_by_status(
    db: Session,
    source_id: Optional[str] = None,
) -> dict[str, int]:
    """
    상태별 문서 수 집계.

    Args:
        db: 데이터베이스 세션
        source_id: Document Source ID (None이면 전체)

    Returns:
        상태별 문서 수 딕셔너리
    """
    from sqlalchemy import func

    query = db.query(
        DocumentMetadata.meta_status,
        func.count().label("count")
    ).filter(
        *active_document_filter()
    )

    if source_id:
        query = query.filter(*source_filter(source_id))

    query = query.group_by(DocumentMetadata.meta_status)

    result = {row[0]: row[1] for row in query.all()}

    # 표준 상태 키 보장
    for status in [s.value for s in MetaStatus]:
        if status not in result:
            result[status] = 0

    return result


def count_rag_ready_documents(
    db: Session,
    source_id: Optional[str] = None,
) -> int:
    """
    RAG 대상 문서 수 반환.

    Args:
        db: 데이터베이스 세션
        source_id: Document Source ID

    Returns:
        RAG 대상 문서 수
    """
    from sqlalchemy import func

    query = db.query(func.count(DocumentMetadata.id)).filter(
        *rag_ready_filter()
    )

    if source_id:
        query = query.filter(*source_filter(source_id))

    return query.scalar() or 0


def get_source_statistics(
    db: Session,
    source_id: str,
) -> dict[str, Any]:
    """
    특정 source_id의 문서 통계 반환.

    Args:
        db: 데이터베이스 세션
        source_id: Document Source ID

    Returns:
        통계 딕셔너리
    """
    from sqlalchemy import func

    base_query = db.query(DocumentMetadata).filter(
        *source_filter(source_id),
        *active_document_filter(),
    )

    total = base_query.count()
    rag_ready = base_query.filter(*rag_ready_filter()).count()

    # 카테고리별 집계
    category_counts = db.query(
        DocumentMetadata.category,
        func.count().label("count")
    ).filter(
        *source_filter(source_id),
        *active_document_filter(),
    ).group_by(
        DocumentMetadata.category
    ).all()

    # 파일 확장자별 집계
    # file_path에서 확장자 추출은 DB에 따라 다르므로 Python에서 처리
    documents = base_query.all()
    ext_counts: dict[str, int] = {}
    for doc in documents:
        if doc.file_path:
            ext = doc.file_path.rsplit(".", 1)[-1].lower() if "." in doc.file_path else "unknown"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

    return {
        "source_id": source_id,
        "total_documents": total,
        "rag_ready_documents": rag_ready,
        "rag_ready_ratio": round(rag_ready / total, 3) if total > 0 else 0,
        "by_category": {row[0] or "unknown": row[1] for row in category_counts},
        "by_extension": ext_counts,
        "status_counts": count_documents_by_status(db, source_id),
    }
