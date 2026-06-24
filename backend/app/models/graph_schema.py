# Graph RAG 노드 및 관계 스키마 정의
# -*- coding: utf-8 -*-
"""
Graph RAG 데이터 모델 정의.

Phase 2에서 정의된 노드와 관계 유형을 Pydantic 모델로 구현하고,
Text2Cypher가 사용할 schema text를 자동 생성한다.

노드 유형:
- Organization: 발주기관
- Project: 프로젝트/사업
- Document: 문서
- Keyword: 키워드
- Category: 문서 카테고리
- Technology: 기술
- Person: 담당자

관계 유형:
- ORDERED: 기관 → 프로젝트 발주
- HAS_DOCUMENT: 프로젝트 → 문서 소유
- HAS_KEYWORD: 문서/프로젝트 → 키워드
- USES_TECH: 프로젝트 → 기술 사용
- SIMILAR_TO: 문서 ↔ 문서 유사
- SAME_PROJECT: 문서 ↔ 문서 동일 사업
- SAME_ORGANIZATION: 프로젝트 ↔ 프로젝트 동일 기관
- BELONGS_TO: 문서 → 카테고리
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── 노드 유형 Enum ─────────────────────────────────────────────────────────────

class NodeType(str, Enum):
    """Graph 노드 유형."""
    ORGANIZATION = "Organization"
    ORGANIZATION_TYPE = "OrganizationType"  # 공공기관, 공기업, 연구기관 등
    PROJECT = "Project"
    PROJECT_TYPE = "ProjectType"  # ISP수립, 시스템구축, 플랫폼고도화 등
    DOCUMENT = "Document"
    DOCUMENT_SECTION = "DocumentSection"  # 전략및방법론, 기술및기능 등
    DOCUMENT_KEYWORD = "DocumentKeyword"  # 보안, 의사소통관리 등
    KEYWORD = "Keyword"
    CATEGORY = "Category"
    TECHNOLOGY = "Technology"
    METHODOLOGY = "Methodology"  # ISP, ISMP, EA 등
    DOMAIN = "Domain"  # 수자원, 스마트시티 등
    PERSON = "Person"


class RelationType(str, Enum):
    """Graph 관계 유형."""
    ORDERED = "ORDERED"
    HAS_DOCUMENT = "HAS_DOCUMENT"
    HAS_KEYWORD = "HAS_KEYWORD"
    USES_TECH = "USES_TECH"
    SIMILAR_TO = "SIMILAR_TO"
    SAME_PROJECT = "SAME_PROJECT"
    SAME_ORGANIZATION = "SAME_ORGANIZATION"
    BELONGS_TO = "BELONGS_TO"
    # 확장 관계 유형
    BELONGS_TO_TYPE = "BELONGS_TO_TYPE"  # 기관 → 기관유형
    HAS_PROJECT_TYPE = "HAS_PROJECT_TYPE"  # 프로젝트 → 사업유형
    HAS_SECTION = "HAS_SECTION"  # 문서 → 문서섹션
    HAS_DOC_KEYWORD = "HAS_DOC_KEYWORD"  # 문서 → 문서키워드
    USES_METHODOLOGY = "USES_METHODOLOGY"  # 프로젝트 → 방법론
    RELATED_DOMAIN = "RELATED_DOMAIN"  # 프로젝트 → 도메인
    SIMILAR_PROJECT = "SIMILAR_PROJECT"  # 프로젝트 ↔ 프로젝트 유사


# ── 노드 모델 ─────────────────────────────────────────────────────────────────

class BaseNode(BaseModel):
    """모든 노드의 기본 클래스."""
    id: str = Field(..., description="노드 고유 ID")
    name: str = Field(..., description="노드 이름 (영문 또는 한글)")
    name_ko: Optional[str] = Field(None, description="한글 이름")
    created_at: datetime = Field(default_factory=datetime.now)
    properties: dict[str, Any] = Field(default_factory=dict)


class OrganizationNode(BaseNode):
    """발주기관 노드."""
    node_type: NodeType = NodeType.ORGANIZATION
    abbreviation: Optional[str] = Field(None, description="약어 (예: NIA, LH)")
    synonyms: list[str] = Field(default_factory=list, description="동의어 목록")
    sector: Optional[str] = Field(None, description="분야 (공공/민간)")


class ProjectNode(BaseNode):
    """프로젝트/사업 노드."""
    node_type: NodeType = NodeType.PROJECT
    year: Optional[int] = Field(None, description="사업 연도")
    organization_id: Optional[str] = Field(None, description="발주기관 ID")
    status: Optional[str] = Field(None, description="진행 상태")
    budget: Optional[float] = Field(None, description="사업 예산")
    domain: Optional[str] = Field(None, description="도메인/분야")


class DocumentNode(BaseNode):
    """문서 노드."""
    node_type: NodeType = NodeType.DOCUMENT
    file_name: str = Field(..., description="파일명")
    source_path: str = Field(..., description="원본 경로")
    category: Optional[str] = Field(None, description="문서 카테고리 (rfp/proposal/etc)")
    project_id: Optional[str] = Field(None, description="프로젝트 ID")
    page_count: Optional[int] = Field(None, description="페이지 수")
    file_size: Optional[int] = Field(None, description="파일 크기 (bytes)")


class KeywordNode(BaseNode):
    """키워드 노드."""
    node_type: NodeType = NodeType.KEYWORD
    frequency: int = Field(default=1, description="출현 빈도")
    is_technical: bool = Field(default=False, description="기술 용어 여부")


class CategoryNode(BaseNode):
    """문서 카테고리 노드."""
    node_type: NodeType = NodeType.CATEGORY
    description: Optional[str] = Field(None, description="카테고리 설명")
    color: Optional[str] = Field(None, description="UI 표시 색상")


class TechnologyNode(BaseNode):
    """기술 노드."""
    node_type: NodeType = NodeType.TECHNOLOGY
    parent_tech: Optional[str] = Field(None, description="상위 기술")
    synonyms: list[str] = Field(default_factory=list, description="동의어 목록")


class PersonNode(BaseNode):
    """담당자 노드."""
    node_type: NodeType = NodeType.PERSON
    role: Optional[str] = Field(None, description="역할 (PM, PL, etc)")
    organization_id: Optional[str] = Field(None, description="소속 기관 ID")


# ── 관계 모델 ─────────────────────────────────────────────────────────────────

class BaseRelation(BaseModel):
    """모든 관계의 기본 클래스."""
    source_id: str = Field(..., description="시작 노드 ID")
    target_id: str = Field(..., description="끝 노드 ID")
    relation_type: RelationType
    weight: float = Field(default=1.0, description="관계 가중치")
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class OrderedRelation(BaseRelation):
    """발주 관계: Organization → Project."""
    relation_type: RelationType = RelationType.ORDERED
    contract_date: Optional[datetime] = Field(None, description="계약일")
    contract_amount: Optional[float] = Field(None, description="계약 금액")


class HasDocumentRelation(BaseRelation):
    """문서 소유 관계: Project → Document."""
    relation_type: RelationType = RelationType.HAS_DOCUMENT
    document_role: Optional[str] = Field(None, description="문서 역할 (입찰/제안/산출물)")


class HasKeywordRelation(BaseRelation):
    """키워드 관계: Document/Project → Keyword."""
    relation_type: RelationType = RelationType.HAS_KEYWORD
    score: float = Field(default=1.0, description="키워드 관련도 점수")


class UsesTechRelation(BaseRelation):
    """기술 사용 관계: Project → Technology."""
    relation_type: RelationType = RelationType.USES_TECH
    usage_type: Optional[str] = Field(None, description="사용 유형 (주요/보조)")


class SimilarToRelation(BaseRelation):
    """유사 관계: Document ↔ Document."""
    relation_type: RelationType = RelationType.SIMILAR_TO
    similarity_score: float = Field(..., description="유사도 점수 (0~1)")
    similarity_type: Optional[str] = Field(None, description="유사도 유형 (semantic/keyword)")


class SameProjectRelation(BaseRelation):
    """동일 사업 관계: Document ↔ Document."""
    relation_type: RelationType = RelationType.SAME_PROJECT
    project_id: str = Field(..., description="공통 프로젝트 ID")


class SameOrganizationRelation(BaseRelation):
    """동일 기관 관계: Project ↔ Project."""
    relation_type: RelationType = RelationType.SAME_ORGANIZATION
    organization_id: str = Field(..., description="공통 기관 ID")


class BelongsToRelation(BaseRelation):
    """카테고리 소속 관계: Document → Category."""
    relation_type: RelationType = RelationType.BELONGS_TO


# ── 관계 규칙 정의 ─────────────────────────────────────────────────────────────

RELATION_RULES: dict[RelationType, dict[str, NodeType | list[NodeType]]] = {
    RelationType.ORDERED: {
        "source": NodeType.ORGANIZATION,
        "target": NodeType.PROJECT,
    },
    RelationType.HAS_DOCUMENT: {
        "source": NodeType.PROJECT,
        "target": NodeType.DOCUMENT,
    },
    RelationType.HAS_KEYWORD: {
        "source": [NodeType.DOCUMENT, NodeType.PROJECT],
        "target": NodeType.KEYWORD,
    },
    RelationType.USES_TECH: {
        "source": NodeType.PROJECT,
        "target": NodeType.TECHNOLOGY,
    },
    RelationType.SIMILAR_TO: {
        "source": NodeType.DOCUMENT,
        "target": NodeType.DOCUMENT,
    },
    RelationType.SAME_PROJECT: {
        "source": NodeType.DOCUMENT,
        "target": NodeType.DOCUMENT,
    },
    RelationType.SAME_ORGANIZATION: {
        "source": NodeType.PROJECT,
        "target": NodeType.PROJECT,
    },
    RelationType.BELONGS_TO: {
        "source": NodeType.DOCUMENT,
        "target": NodeType.CATEGORY,
    },
}


# ── Text2Cypher용 Schema Text 생성 ─────────────────────────────────────────────

def generate_schema_text(
    node_types: list[NodeType] | None = None,
    relation_types: list[RelationType] | None = None,
) -> str:
    """Text2Cypher가 참조할 Graph Schema를 텍스트로 생성한다.

    Args:
        node_types: 포함할 노드 유형 (None이면 전체)
        relation_types: 포함할 관계 유형 (None이면 전체)

    Returns:
        Schema 설명 텍스트
    """
    if node_types is None:
        node_types = list(NodeType)
    if relation_types is None:
        relation_types = list(RelationType)

    lines = ["# Graph Schema for Text2Cypher", ""]

    # 노드 정의
    lines.append("## Node Types")
    node_descriptions = {
        NodeType.ORGANIZATION: "발주기관. 속성: name(이름), abbreviation(약어), sector(분야), synonyms(동의어)",
        NodeType.ORGANIZATION_TYPE: "기관유형. 속성: name(이름 - 공공기관/공기업/연구기관/건강보험/민간기업), member_count(소속기관수)",
        NodeType.PROJECT: "프로젝트/사업. 속성: name(이름), year(연도), status(상태), budget(예산), domain(도메인)",
        NodeType.PROJECT_TYPE: "사업유형. 속성: name(이름 - ISP수립/ISMP수립/시스템구축/시스템개선/플랫폼고도화/로드맵수립/연구용역/운영유지보수)",
        NodeType.DOCUMENT: "문서. 속성: name(이름), file_name(파일명), source_path(경로), category(카테고리)",
        NodeType.DOCUMENT_SECTION: "문서섹션. 속성: name(이름 - 전략및방법론/기술및기능/프로젝트관리/환경분석/현황분석/목표모델/이행계획), section_type(proposal/deliverable)",
        NodeType.DOCUMENT_KEYWORD: "문서키워드. 속성: name(이름 - 보안/의사소통관리/품질관리/위험관리/선진사례/데이터관리)",
        NodeType.KEYWORD: "키워드. 속성: name(이름), frequency(빈도), is_technical(기술용어여부)",
        NodeType.CATEGORY: "문서 카테고리. 속성: name(이름 - rfp/proposal/deliverable), description(설명)",
        NodeType.TECHNOLOGY: "기술. 속성: name(이름 - AI/빅데이터/클라우드/IoT/디지털트윈 등), parent_tech(상위기술), synonyms(동의어)",
        NodeType.METHODOLOGY: "방법론. 속성: name(이름 - ISP/ISMP/EA/BPR/PI/DX/애자일 등), synonyms(동의어)",
        NodeType.DOMAIN: "도메인. 속성: name(이름 - 수자원/스마트시티/교통/보건의료 등), synonyms(동의어)",
        NodeType.PERSON: "담당자. 속성: name(이름), role(역할)",
    }
    for nt in node_types:
        desc = node_descriptions.get(nt, "")
        lines.append(f"- {nt.value}: {desc}")

    lines.append("")

    # 관계 정의
    lines.append("## Relation Types")
    relation_descriptions = {
        RelationType.ORDERED: "(Organization)-[:ORDERED]->(Project) - 기관이 프로젝트를 발주함",
        RelationType.HAS_DOCUMENT: "(Project)-[:HAS_DOCUMENT]->(Document) - 프로젝트가 문서를 소유함",
        RelationType.HAS_KEYWORD: "(Document|Project)-[:HAS_KEYWORD]->(Keyword) - 키워드를 가짐",
        RelationType.USES_TECH: "(Project)-[:USES_TECH]->(Technology) - 기술을 사용함",
        RelationType.SIMILAR_TO: "(Document)-[:SIMILAR_TO {similarity_score}]->(Document) - 문서 간 유사",
        RelationType.SAME_PROJECT: "(Document)-[:SAME_PROJECT {project_id}]->(Document) - 동일 사업 문서",
        RelationType.SAME_ORGANIZATION: "(Project)-[:SAME_ORGANIZATION {organization_id}]->(Project) - 동일 기관 프로젝트",
        RelationType.BELONGS_TO: "(Document)-[:BELONGS_TO]->(Category) - 카테고리에 속함",
        # 확장 관계
        RelationType.BELONGS_TO_TYPE: "(Organization)-[:BELONGS_TO_TYPE]->(OrganizationType) - 기관이 기관유형에 속함",
        RelationType.HAS_PROJECT_TYPE: "(Project)-[:HAS_PROJECT_TYPE]->(ProjectType) - 프로젝트의 사업유형",
        RelationType.HAS_SECTION: "(Document)-[:HAS_SECTION]->(DocumentSection) - 문서가 특정 섹션에 해당함",
        RelationType.HAS_DOC_KEYWORD: "(Document)-[:HAS_DOC_KEYWORD]->(DocumentKeyword) - 문서가 특정 키워드 관련됨",
        RelationType.USES_METHODOLOGY: "(Project)-[:USES_METHODOLOGY]->(Methodology) - 프로젝트가 방법론을 사용함",
        RelationType.RELATED_DOMAIN: "(Project)-[:RELATED_DOMAIN]->(Domain) - 프로젝트가 도메인과 관련됨",
        RelationType.SIMILAR_PROJECT: "(Project)-[:SIMILAR_PROJECT {reason, weight}]->(Project) - 유사 프로젝트",
    }
    for rt in relation_types:
        desc = relation_descriptions.get(rt, "")
        lines.append(f"- {desc}")

    lines.append("")

    # 예시 쿼리
    lines.append("## Example Queries")
    lines.append("### 기본 검색")
    lines.append("- 특정 기관이 발주한 프로젝트: MATCH (o:Organization {name: '기관명'})-[:ORDERED]->(p:Project) RETURN p")
    lines.append("- 특정 연도 프로젝트: MATCH (p:Project {year: 2024}) RETURN p")
    lines.append("- 프로젝트의 모든 문서: MATCH (p:Project {name: '프로젝트명'})-[:HAS_DOCUMENT]->(d:Document) RETURN d")
    lines.append("- 유사 문서 검색: MATCH (d1:Document {name: '문서명'})-[:SIMILAR_TO]->(d2:Document) RETURN d2")
    lines.append("- 동일 사업 문서: MATCH (d1:Document)-[:SAME_PROJECT]->(d2:Document) WHERE d1.name = '문서명' RETURN d2")
    lines.append("- 키워드로 문서 검색: MATCH (d:Document)-[:HAS_KEYWORD]->(k:Keyword {name: '키워드'}) RETURN d")
    lines.append("")
    lines.append("### 확장 검색 (질문 리스트 Q1~Q7 지원)")
    lines.append("- Q1 보안 관련 제안서: MATCH (d:Document {category: 'proposal'})-[:HAS_DOC_KEYWORD]->(dk:DocumentKeyword {name: '보안'}) RETURN d")
    lines.append("- Q2 프로젝트관리 의사소통 문서: MATCH (d:Document)-[:HAS_SECTION]->(s:DocumentSection {name: '프로젝트관리'}), (d)-[:HAS_DOC_KEYWORD]->(dk:DocumentKeyword {name: '의사소통관리'}) RETURN d")
    lines.append("- Q3 업무시스템 개선 사업 제안서: MATCH (p:Project)-[:HAS_PROJECT_TYPE]->(pt:ProjectType {name: '시스템개선'}), (p)-[:HAS_DOCUMENT]->(d:Document {category: 'proposal'}) RETURN d")
    lines.append("- Q4 시스템개선 사업 현황분석 산출물: MATCH (p:Project)-[:HAS_PROJECT_TYPE]->(pt:ProjectType {name: '시스템개선'}), (p)-[:HAS_DOCUMENT]->(d:Document {category: 'deliverable'})-[:HAS_SECTION]->(s:DocumentSection {name: '현황분석'}) RETURN d")
    lines.append("- Q5 연구기관 고객 프로젝트: MATCH (o:Organization)-[:BELONGS_TO_TYPE]->(ot:OrganizationType {name: '연구기관'}), (o)-[:ORDERED]->(p:Project) RETURN p")
    lines.append("- Q6 플랫폼 고도화 사업 제안서: MATCH (p:Project)-[:HAS_PROJECT_TYPE]->(pt:ProjectType {name: '플랫폼고도화'}), (p)-[:HAS_DOCUMENT]->(d:Document {category: 'proposal'}) RETURN d")
    lines.append("- Q7 공공기관 AI 선진사례: MATCH (o:Organization)-[:BELONGS_TO_TYPE]->(ot:OrganizationType {name: '공공기관'}), (o)-[:ORDERED]->(p:Project)-[:USES_TECH]->(t:Technology {name: 'AI'}), (p)-[:HAS_DOCUMENT]->(d:Document)-[:HAS_DOC_KEYWORD]->(dk:DocumentKeyword {name: '선진사례'}) RETURN d")

    return "\n".join(lines)


def generate_schema_json(
    node_types: list[NodeType] | None = None,
    relation_types: list[RelationType] | None = None,
) -> dict:
    """Text2Cypher가 참조할 Graph Schema를 JSON으로 생성한다."""
    if node_types is None:
        node_types = list(NodeType)
    if relation_types is None:
        relation_types = list(RelationType)

    node_schemas = {
        NodeType.ORGANIZATION: {
            "properties": ["name", "name_ko", "abbreviation", "synonyms", "sector"],
            "description": "발주기관",
        },
        NodeType.PROJECT: {
            "properties": ["name", "name_ko", "year", "status", "budget", "domain", "organization_id"],
            "description": "프로젝트/사업",
        },
        NodeType.DOCUMENT: {
            "properties": ["name", "name_ko", "file_name", "source_path", "category", "project_id", "page_count", "file_size"],
            "description": "문서",
        },
        NodeType.KEYWORD: {
            "properties": ["name", "frequency", "is_technical"],
            "description": "키워드",
        },
        NodeType.CATEGORY: {
            "properties": ["name", "description", "color"],
            "description": "문서 카테고리",
        },
        NodeType.TECHNOLOGY: {
            "properties": ["name", "parent_tech", "synonyms"],
            "description": "기술",
        },
        NodeType.PERSON: {
            "properties": ["name", "role", "organization_id"],
            "description": "담당자",
        },
    }

    return {
        "nodes": {
            nt.value: node_schemas.get(nt, {})
            for nt in node_types
        },
        "relations": {
            rt.value: {
                "source": RELATION_RULES[rt]["source"].value if isinstance(RELATION_RULES[rt]["source"], NodeType) else [n.value for n in RELATION_RULES[rt]["source"]],
                "target": RELATION_RULES[rt]["target"].value if isinstance(RELATION_RULES[rt]["target"], NodeType) else [n.value for n in RELATION_RULES[rt]["target"]],
            }
            for rt in relation_types
        },
    }


def generate_cypher_constraints() -> str:
    """Neo4j 제약 조건 생성 Cypher 쿼리."""
    lines = ["// Graph Schema Constraints", ""]

    for nt in NodeType:
        lines.append(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{nt.value}) REQUIRE n.id IS UNIQUE;")

    lines.append("")
    lines.append("// Indexes for common queries")
    lines.append("CREATE INDEX IF NOT EXISTS FOR (n:Organization) ON (n.name);")
    lines.append("CREATE INDEX IF NOT EXISTS FOR (n:Project) ON (n.name);")
    lines.append("CREATE INDEX IF NOT EXISTS FOR (n:Project) ON (n.year);")
    lines.append("CREATE INDEX IF NOT EXISTS FOR (n:Document) ON (n.category);")
    lines.append("CREATE INDEX IF NOT EXISTS FOR (n:Keyword) ON (n.name);")

    return "\n".join(lines)
