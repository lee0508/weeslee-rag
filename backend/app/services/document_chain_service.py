# 문서 체인 연결 서비스 - RFP 기반 제안서/산출물 연결
# -*- coding: utf-8 -*-
"""
Document Chain Service.

RFP(과업지시서)를 기준으로 제안서/산출물 문서를 연결하는 서비스.
파일명에서 프로젝트명을 정규화하여 동일 프로젝트의 문서들을 그룹화한다.

폴더 구조:
- 01. RFP/RFP_[사업명].hwp → 마스터 문서
- 02. 제안서/[섹션]_[사업명].pptx → 제안서 문서
- 03. 산출물/[단계]_[사업명].pptx → 산출물 문서

문서 체인:
RFP(마스터) ──┬── 제안서/전략및방법론
              ├── 제안서/기술및기능
              ├── 제안서/프로젝트관리
              ├── 제안서/프로젝트지원
              ├── 산출물/환경분석
              ├── 산출물/현황분석
              ├── 산출물/목표모델
              └── 산출물/이행계획
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── 파일명 접두사 패턴 ─────────────────────────────────────────────────────────

# RFP 파일 접두사
_RFP_PREFIX = re.compile(r'^RFP_')

# 제안서 섹션 접두사
_PROPOSAL_SECTION_PREFIX = re.compile(
    r'^(?:전략및방법론_|기술및기능_|프로젝트관리_|프로젝트지원_|연구과제_)'
)

# 산출물 단계 접두사
_DELIVERABLE_STAGE_PREFIX = re.compile(
    r'^(?:환경분석_|현황분석_|목표모델_|이행계획_|'
    r'착수보고서_|중간보고서_|최종보고서_|완료보고서_)'
)

# 통합 접두사 패턴 (모든 접두사 제거용)
_ALL_PREFIX_PATTERN = re.compile(
    r'^(?:RFP_|전략및방법론_|기술및기능_|프로젝트관리_|프로젝트지원_|'
    r'연구과제_|환경분석_|현황분석_|목표모델_|이행계획_|'
    r'착수보고서_|중간보고서_|최종보고서_|완료보고서_)'
)


# ── 폴더 경로 패턴 ─────────────────────────────────────────────────────────────

_RFP_FOLDER_PATTERN = re.compile(r'(?:^|/)01\.\s*RFP(?:/|$)', re.IGNORECASE)
_PROPOSAL_FOLDER_PATTERN = re.compile(r'(?:^|/)02\.\s*제안서(?:/|$)', re.IGNORECASE)
_DELIVERABLE_FOLDER_PATTERN = re.compile(r'(?:^|/)03\.\s*산출물(?:/|$)', re.IGNORECASE)


# ── 데이터 클래스 ─────────────────────────────────────────────────────────────


@dataclass
class DocumentChainInfo:
    """문서 체인 정보."""
    project_name: str  # 정규화된 프로젝트명
    document_role: str  # "rfp", "proposal", "deliverable"
    section_name: Optional[str] = None  # 제안서: "전략및방법론", 산출물: "환경분석" 등
    confidence: float = 0.0


@dataclass
class ProjectDocumentChain:
    """프로젝트 문서 체인 그룹."""
    project_name: str
    rfp_document_id: Optional[str] = None
    rfp_organization: Optional[str] = None
    rfp_year: Optional[int] = None
    proposal_document_ids: list[str] = field(default_factory=list)
    deliverable_document_ids: list[str] = field(default_factory=list)


# ── 서비스 클래스 ─────────────────────────────────────────────────────────────


class DocumentChainService:
    """문서 체인 연결 서비스."""

    @staticmethod
    def normalize_project_name(filename: str) -> Optional[str]:
        """
        파일명에서 정규화된 프로젝트명을 추출한다.

        예시:
        - "RFP_AI 기반 지능형 진로교육정보망 통합 구축을 위한 ISP.hwp"
          → "AI 기반 지능형 진로교육정보망 통합 구축을 위한 ISP"
        - "전략및방법론_AI 기반 지능형 진로교육정보망 통합 구축을 위한 ISP.pptx"
          → "AI 기반 지능형 진로교육정보망 통합 구축을 위한 ISP"
        """
        if not filename:
            return None

        # 확장자 제거
        name = filename.rsplit(".", 1)[0] if "." in filename else filename

        # 모든 접두사 제거
        name = _ALL_PREFIX_PATTERN.sub("", name)

        # 정리
        name = name.strip()

        # 최소 길이 검증
        if len(name) < 10:
            return None

        return name

    @staticmethod
    def detect_document_role(relative_path: str) -> tuple[str, float]:
        """
        상대 경로에서 문서 역할을 감지한다.

        Returns:
            (role, confidence) - role은 "rfp", "proposal", "deliverable", "unknown" 중 하나
        """
        if not relative_path:
            return "unknown", 0.0

        if _RFP_FOLDER_PATTERN.search(relative_path):
            return "rfp", 0.95
        if _PROPOSAL_FOLDER_PATTERN.search(relative_path):
            return "proposal", 0.95
        if _DELIVERABLE_FOLDER_PATTERN.search(relative_path):
            return "deliverable", 0.95

        return "unknown", 0.0

    @staticmethod
    def extract_section_name(filename: str, role: str) -> Optional[str]:
        """
        파일명에서 섹션/단계명을 추출한다.

        Args:
            filename: 파일명
            role: "proposal" 또는 "deliverable"

        Returns:
            섹션명 (예: "전략및방법론", "환경분석")
        """
        if not filename:
            return None

        name = filename.rsplit(".", 1)[0] if "." in filename else filename

        if role == "proposal":
            match = _PROPOSAL_SECTION_PREFIX.match(name)
            if match:
                # "전략및방법론_" → "전략및방법론"
                return match.group(0).rstrip("_")
        elif role == "deliverable":
            match = _DELIVERABLE_STAGE_PREFIX.match(name)
            if match:
                return match.group(0).rstrip("_")

        return None

    @classmethod
    def analyze_document(
        cls,
        filename: str,
        relative_path: str,
    ) -> Optional[DocumentChainInfo]:
        """
        문서를 분석하여 체인 정보를 반환한다.

        Args:
            filename: 파일명
            relative_path: 상대 경로 (폴더 구조 포함)

        Returns:
            DocumentChainInfo 또는 None
        """
        project_name = cls.normalize_project_name(filename)
        if not project_name:
            return None

        role, confidence = cls.detect_document_role(relative_path)
        if role == "unknown":
            return None

        section_name = cls.extract_section_name(filename, role)

        return DocumentChainInfo(
            project_name=project_name,
            document_role=role,
            section_name=section_name,
            confidence=confidence,
        )

    @classmethod
    def group_documents_by_project(
        cls,
        documents: list[dict],
    ) -> dict[str, ProjectDocumentChain]:
        """
        문서 목록을 프로젝트별로 그룹화한다.

        Args:
            documents: 문서 목록 (각 문서는 document_id, file_name, relative_path 필드 필요)

        Returns:
            프로젝트명 → ProjectDocumentChain 매핑
        """
        chains: dict[str, ProjectDocumentChain] = {}

        for doc in documents:
            doc_id = str(doc.get("document_id", ""))
            filename = doc.get("file_name", "")
            relative_path = doc.get("relative_path", "")

            chain_info = cls.analyze_document(filename, relative_path)
            if not chain_info:
                continue

            project_name = chain_info.project_name

            if project_name not in chains:
                chains[project_name] = ProjectDocumentChain(project_name=project_name)

            chain = chains[project_name]

            if chain_info.document_role == "rfp":
                chain.rfp_document_id = doc_id
                # RFP에서 추가 메타데이터 상속
                chain.rfp_organization = doc.get("ocr_organization")
                chain.rfp_year = doc.get("ocr_year")
            elif chain_info.document_role == "proposal":
                if doc_id not in chain.proposal_document_ids:
                    chain.proposal_document_ids.append(doc_id)
            elif chain_info.document_role == "deliverable":
                if doc_id not in chain.deliverable_document_ids:
                    chain.deliverable_document_ids.append(doc_id)

        return chains

    @classmethod
    def get_related_documents(
        cls,
        document_id: str,
        documents: list[dict],
    ) -> list[str]:
        """
        특정 문서와 관련된 모든 문서 ID 목록을 반환한다.

        Args:
            document_id: 대상 문서 ID
            documents: 전체 문서 목록

        Returns:
            관련 문서 ID 목록 (자기 자신 포함)
        """
        chains = cls.group_documents_by_project(documents)

        for chain in chains.values():
            all_ids = []
            if chain.rfp_document_id:
                all_ids.append(chain.rfp_document_id)
            all_ids.extend(chain.proposal_document_ids)
            all_ids.extend(chain.deliverable_document_ids)

            if document_id in all_ids:
                return all_ids

        return [document_id]

    @classmethod
    def inherit_metadata_from_rfp(
        cls,
        document: dict,
        chains: dict[str, ProjectDocumentChain],
        rfp_documents: dict[str, dict],
    ) -> dict:
        """
        RFP 마스터 문서에서 메타데이터를 상속받는다.

        Args:
            document: 대상 문서 (제안서/산출물)
            chains: 프로젝트별 문서 체인
            rfp_documents: RFP 문서 ID → 문서 데이터 매핑

        Returns:
            메타데이터가 보강된 문서
        """
        filename = document.get("file_name", "")
        project_name = cls.normalize_project_name(filename)

        if not project_name or project_name not in chains:
            return document

        chain = chains[project_name]
        if not chain.rfp_document_id:
            return document

        rfp_doc = rfp_documents.get(chain.rfp_document_id)
        if not rfp_doc:
            return document

        # 메타데이터 상속 (빈 값만 채움)
        result = document.copy()

        # 사업명: RFP 파일명 기반 프로젝트명 사용
        if not result.get("ocr_project_name"):
            result["ocr_project_name"] = project_name

        # 발주기관: RFP에서 상속
        if not result.get("ocr_organization") and rfp_doc.get("ocr_organization"):
            result["ocr_organization"] = rfp_doc["ocr_organization"]
            result["ocr_organization_source"] = "inherited_from_rfp"

        # 연도: RFP에서 상속
        if not result.get("ocr_year") and rfp_doc.get("ocr_year"):
            result["ocr_year"] = rfp_doc["ocr_year"]
            result["ocr_year_source"] = "inherited_from_rfp"

        # 체인 연결 정보 추가
        result["rfp_document_id"] = chain.rfp_document_id
        result["project_chain_name"] = project_name

        return result


# ── 싱글톤 인스턴스 ─────────────────────────────────────────────────────────────

_service_instance: Optional[DocumentChainService] = None


def get_document_chain_service() -> DocumentChainService:
    """DocumentChainService 싱글톤 인스턴스 반환."""
    global _service_instance
    if _service_instance is None:
        _service_instance = DocumentChainService()
    return _service_instance
