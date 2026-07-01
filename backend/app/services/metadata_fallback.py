# Metadata Fallback 체인 유틸리티 - final → ocr → scan 우선순위 적용
# -*- coding: utf-8 -*-
"""
Metadata Fallback Service

FAISS, Graph, Wiki가 공통으로 사용하는 메타데이터 값 해결 유틸리티.
final_* → ocr_* → scan_* 순서로 우선순위를 적용하여 가장 신뢰도 높은 값을 반환한다.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, List
from dataclasses import dataclass


# Fallback 대상 필드 목록
FALLBACK_FIELDS = [
    "project_name",
    "organization",
    "year",
    "document_category",
]


@dataclass
class ResolvedMetadata:
    """Fallback 체인을 통해 해결된 메타데이터."""
    project_name: Optional[str] = None
    organization: Optional[str] = None
    year: Optional[str] = None
    document_category: Optional[str] = None
    document_group: Optional[str] = None

    # 원본 소스 추적 (디버깅용)
    project_name_source: Optional[str] = None
    organization_source: Optional[str] = None
    year_source: Optional[str] = None
    document_category_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        return {
            "project_name": self.project_name,
            "organization": self.organization,
            "year": self.year,
            "document_category": self.document_category,
            "document_group": self.document_group,
            "_sources": {
                "project_name": self.project_name_source,
                "organization": self.organization_source,
                "year": self.year_source,
                "document_category": self.document_category_source,
            }
        }


def get_effective_value(
    meta: Dict[str, Any],
    field: str,
    prefixes: List[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """
    Fallback 체인을 적용하여 유효한 값을 반환한다.

    Args:
        meta: 메타데이터 딕셔너리
        field: 기본 필드명 (project_name, organization 등)
        prefixes: 우선순위 순서 접두사 목록 (기본: ["final_", "ocr_", "scan_"])

    Returns:
        (값, 소스 접두사) 튜플. 값이 없으면 (None, None).
    """
    if prefixes is None:
        prefixes = ["final_", "ocr_", "scan_"]

    for prefix in prefixes:
        key = f"{prefix}{field}"
        value = meta.get(key)
        if value is not None and str(value).strip():
            return str(value).strip(), prefix

    # prefix 없는 기본 필드 확인
    value = meta.get(field)
    if value is not None and str(value).strip():
        return str(value).strip(), "base"

    return None, None


def get_review_final_value(
    meta: Dict[str, Any],
    field: str,
    review_prefixes: Optional[List[str]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Step 3 승인 시 final_*로 승격할 값을 고른다.

    검수 화면의 기본값(project_name, organization, year)을 우선 사용하고,
    값이 비어 있으면 OCR, Scan 순으로 fallback 한다.
    """
    if review_prefixes is None:
        review_prefixes = ["ocr_", "scan_"]

    value = meta.get(field)
    if value is not None and str(value).strip():
        return str(value).strip(), "base"

    for prefix in review_prefixes:
        key = f"{prefix}{field}"
        value = meta.get(key)
        if value is not None and str(value).strip():
            return str(value).strip(), prefix

    return None, None


def resolve_metadata(meta: Dict[str, Any]) -> ResolvedMetadata:
    """
    메타데이터 딕셔너리에서 Fallback 체인을 적용하여 유효 값을 해결한다.

    Args:
        meta: 메타데이터 딕셔너리 (DocumentMetadata.to_dict() 또는 FAISS 메타데이터)

    Returns:
        ResolvedMetadata 객체
    """
    project_name, pn_source = get_effective_value(meta, "project_name")
    organization, org_source = get_effective_value(meta, "organization")
    year, year_source = get_effective_value(meta, "year")
    document_category, dc_source = get_effective_value(meta, "document_category")

    # document_group은 별도 필드로 존재
    document_group = meta.get("document_group") or meta.get("category")

    return ResolvedMetadata(
        project_name=project_name,
        organization=organization,
        year=year,
        document_category=document_category,
        document_group=document_group,
        project_name_source=pn_source,
        organization_source=org_source,
        year_source=year_source,
        document_category_source=dc_source,
    )


def resolve_review_final_metadata(meta: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Step 3 승인 시 final_*에 저장할 값을 계산한다.
    """
    project_name, _ = get_review_final_value(meta, "project_name")
    organization, _ = get_review_final_value(meta, "organization")
    year, _ = get_review_final_value(meta, "year")
    document_category, _ = get_review_final_value(meta, "document_category")

    return {
        "final_project_name": project_name,
        "final_organization": organization,
        "final_year": year,
        "final_document_category": document_category or meta.get("document_type") or meta.get("document_group"),
    }


def merge_metadata_for_faiss(
    chunk_meta: Dict[str, Any],
    doc_meta: Dict[str, Any]
) -> Dict[str, Any]:
    """
    FAISS 인덱싱용 메타데이터를 생성한다.
    청크 메타데이터와 문서 메타데이터를 병합하고 Fallback을 적용한다.

    Args:
        chunk_meta: 청크 수준 메타데이터
        doc_meta: 문서 수준 메타데이터

    Returns:
        FAISS 저장용 병합 메타데이터
    """
    # 문서 메타데이터에서 유효 값 해결
    resolved = resolve_metadata(doc_meta)

    # 기본 청크 메타데이터 복사
    result = dict(chunk_meta)

    # 해결된 값으로 덮어쓰기
    if resolved.project_name:
        result["project_name"] = resolved.project_name
    if resolved.organization:
        result["organization"] = resolved.organization
    if resolved.year:
        result["folder_year"] = resolved.year
    if resolved.document_category:
        result["document_category"] = resolved.document_category
    if resolved.document_group:
        result["document_group"] = resolved.document_group

    return result


def merge_metadata_for_graph(
    doc_meta: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Graph 노드 생성용 메타데이터를 생성한다.
    Fallback을 적용하여 가장 신뢰도 높은 값을 사용한다.

    Args:
        doc_meta: 문서 수준 메타데이터

    Returns:
        Graph 노드 생성용 메타데이터
    """
    resolved = resolve_metadata(doc_meta)

    return {
        "document_id": doc_meta.get("document_id"),
        "document_uid": doc_meta.get("document_uid"),
        "source_id": doc_meta.get("source_id"),
        "file_name": doc_meta.get("file_name"),
        "relative_path": doc_meta.get("relative_path"),
        "project_name": resolved.project_name,
        "organization": resolved.organization,
        "year": resolved.year,
        "document_category": resolved.document_category,
        "document_group": resolved.document_group or doc_meta.get("category"),
        "summary": doc_meta.get("summary"),
        "keywords": doc_meta.get("keywords", []),
        "tags": doc_meta.get("tags", []),
        # 소스 추적 (디버깅용)
        "_resolved_sources": {
            "project_name": resolved.project_name_source,
            "organization": resolved.organization_source,
            "year": resolved.year_source,
            "document_category": resolved.document_category_source,
        }
    }


def merge_metadata_for_wiki(
    doc_meta: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Wiki 생성용 메타데이터를 생성한다.
    Fallback을 적용하여 가장 신뢰도 높은 값을 사용한다.

    Args:
        doc_meta: 문서 수준 메타데이터

    Returns:
        Wiki 생성용 메타데이터
    """
    resolved = resolve_metadata(doc_meta)

    return {
        "project_name": resolved.project_name,
        "organization": resolved.organization,
        "year": resolved.year,
        "document_category": resolved.document_category,
        "document_group": resolved.document_group,
        "summary": doc_meta.get("summary"),
        "keywords": doc_meta.get("keywords", []),
        "tags": doc_meta.get("tags", []),
        "business_domain": doc_meta.get("business_domain"),
        "reuse_level": doc_meta.get("reuse_level"),
    }


class MetadataFallbackService:
    """메타데이터 Fallback 서비스."""

    def resolve(self, meta: Dict[str, Any]) -> ResolvedMetadata:
        """메타데이터 해결."""
        return resolve_metadata(meta)

    def for_faiss(
        self,
        chunk_meta: Dict[str, Any],
        doc_meta: Dict[str, Any]
    ) -> Dict[str, Any]:
        """FAISS용 메타데이터 생성."""
        return merge_metadata_for_faiss(chunk_meta, doc_meta)

    def for_graph(self, doc_meta: Dict[str, Any]) -> Dict[str, Any]:
        """Graph용 메타데이터 생성."""
        return merge_metadata_for_graph(doc_meta)

    def for_wiki(self, doc_meta: Dict[str, Any]) -> Dict[str, Any]:
        """Wiki용 메타데이터 생성."""
        return merge_metadata_for_wiki(doc_meta)

    def get_field(
        self,
        meta: Dict[str, Any],
        field: str
    ) -> Optional[str]:
        """단일 필드 값 해결."""
        value, _ = get_effective_value(meta, field)
        return value

    def get_field_with_source(
        self,
        meta: Dict[str, Any],
        field: str
    ) -> tuple[Optional[str], Optional[str]]:
        """단일 필드 값과 소스 반환."""
        return get_effective_value(meta, field)


# 싱글톤 인스턴스
metadata_fallback_service = MetadataFallbackService()


def get_metadata_fallback_service() -> MetadataFallbackService:
    """MetadataFallbackService 싱글톤 반환."""
    return metadata_fallback_service
