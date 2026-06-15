# Snapshot Manifest 모델 - Dataset과 Snapshot의 통합 버전 관리
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class SnapshotStatus(str, Enum):
    """Snapshot 상태"""
    DRAFT = "draft"              # 빌드 중 또는 빌드 완료 직후
    VALIDATED = "validated"      # 품질 검증 통과
    ACTIVE = "active"            # 현재 서비스 중
    ARCHIVED = "archived"        # 이전 버전으로 보관


class DatasetInfo(BaseModel):
    """Dataset 정보 - 어떤 문서들을 대상으로 할 것인가?"""
    dataset_id: str = Field(..., description="Dataset 식별자 (예: dataset_rag_source_20260615)")
    source_id: str = Field(..., description="원본 문서 위치 식별자")

    document_count: int = Field(0, description="포함된 문서 수")
    scan_completed_at: Optional[datetime] = Field(None, description="스캔 완료 시간")

    # 문서 필터링 조건
    include_filters: Dict[str, Any] = Field(default_factory=dict, description="포함 조건")
    exclude_filters: Dict[str, Any] = Field(default_factory=dict, description="제외 조건")

    # 메타데이터 상태
    metadata_extracted_count: int = Field(0, description="메타데이터 추출 완료 문서 수")
    metadata_reviewed_count: int = Field(0, description="메타데이터 검수 완료 문서 수")


class MetadataBuildInfo(BaseModel):
    """메타데이터 빌드 정보"""
    metadata_version_id: Optional[str] = Field(None, description="메타데이터 버전 ID")
    built_at: Optional[datetime] = None
    document_count: int = 0
    avg_confidence: Optional[float] = None


class TagKeywordBuildInfo(BaseModel):
    """Tag/Keyword 빌드 정보"""
    tag_keyword_build_id: Optional[str] = Field(None, description="Tag/Keyword 빌드 ID")
    built_at: Optional[datetime] = None
    tag_count: int = 0
    keyword_count: int = 0
    output_path: Optional[str] = None


class RAGBuildInfo(BaseModel):
    """RAG/FAISS 빌드 정보"""
    rag_build_id: Optional[str] = Field(None, description="RAG 빌드 ID")
    faiss_index_id: Optional[str] = Field(None, description="FAISS 인덱스 ID")

    built_at: Optional[datetime] = None
    embedding_model: str = "ollama/bge-m3"
    chunk_size: int = 512
    chunk_overlap: int = 50

    chunk_count: int = 0
    vector_count: int = 0

    index_file: Optional[str] = None
    metadata_file: Optional[str] = None


class OntologyInfo(BaseModel):
    """온톨로지 정보"""
    ontology_id: Optional[str] = Field(None, description="온톨로지 버전 ID")
    version: str = "v1"

    node_types: List[str] = Field(default_factory=list)
    edge_types: List[str] = Field(default_factory=list)

    schema_file: Optional[str] = None


class GraphBuildInfo(BaseModel):
    """Knowledge Graph 빌드 정보"""
    graph_build_id: Optional[str] = Field(None, description="Knowledge Graph 빌드 ID")
    ontology_id: Optional[str] = Field(None, description="사용된 온톨로지 ID")

    built_at: Optional[datetime] = None
    node_count: int = 0
    edge_count: int = 0

    nodes_file: Optional[str] = None
    edges_file: Optional[str] = None
    summary_file: Optional[str] = None


class WikiBuildInfo(BaseModel):
    """LLM Wiki 빌드 정보"""
    wiki_build_id: Optional[str] = Field(None, description="Wiki 빌드 ID")

    built_at: Optional[datetime] = None
    llm_model: str = "claude-3-5-sonnet"

    article_count: int = 0
    total_tokens_used: int = 0

    output_dir: Optional[str] = None


class SnapshotManifest(BaseModel):
    """
    Snapshot Manifest - 전체 산출물 상태의 통합 버전

    Snapshot = 특정 Dataset에서 생성된
               RAG Index + Knowledge Graph + LLM Wiki + Tag/Keyword + Metadata 상태의 묶음

    핵심 질문에 답변 가능:
    - 현재 사용자 검색 화면은 어떤 문서 목록을 기준으로 검색하는가? → dataset
    - 어떤 FAISS Index를 쓰는가? → rag_build.faiss_index_id
    - 어떤 Knowledge Graph를 쓰는가? → graph_build.graph_build_id
    - 어떤 LLM Wiki를 쓰는가? → wiki_build.wiki_build_id
    - 어떤 Tag/Keyword 사전을 쓰는가? → tag_keyword.tag_keyword_build_id
    - 어떤 Ontology 버전을 쓰는가? → graph_build.ontology_id
    """

    # 기본 식별 정보
    snapshot_id: str = Field(..., description="Snapshot 식별자 (예: snapshot_20260615_rag_source_v1)")
    snapshot_name: Optional[str] = Field(None, description="사람이 읽기 쉬운 이름")
    description: Optional[str] = None

    # Dataset 정보
    dataset: DatasetInfo

    # 각 빌드 정보
    metadata_build: MetadataBuildInfo = Field(default_factory=MetadataBuildInfo)
    tag_keyword: TagKeywordBuildInfo = Field(default_factory=TagKeywordBuildInfo)
    rag_build: RAGBuildInfo = Field(default_factory=RAGBuildInfo)
    graph_build: GraphBuildInfo = Field(default_factory=GraphBuildInfo)
    wiki_build: WikiBuildInfo = Field(default_factory=WikiBuildInfo)

    # 상태 관리
    status: SnapshotStatus = Field(SnapshotStatus.DRAFT, description="Snapshot 상태")
    is_active: bool = Field(False, description="현재 서비스 중 여부")

    # 버전 관리
    version: int = Field(1, description="Snapshot 버전 번호")
    parent_snapshot_id: Optional[str] = Field(None, description="부모 Snapshot ID (증분 빌드 시)")

    # 감사 정보
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    activated_at: Optional[datetime] = None
    activated_by: Optional[str] = None
    archived_at: Optional[datetime] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }

    def to_active_snapshot_json(self) -> Dict[str, Any]:
        """active_snapshot.json 형식으로 변환 (하위 호환성)"""
        return {
            # 기존 active_index.json 호환 필드
            "active_snapshot": self.rag_build.faiss_index_id or self.snapshot_id,
            "index_file": self.rag_build.index_file,
            "metadata_file": self.rag_build.metadata_file,
            "embedding_provider": self.rag_build.embedding_model.split("/")[-1] if self.rag_build.embedding_model else "ollama",
            "vector_count": self.rag_build.vector_count,
            "document_count": self.dataset.document_count,
            "chunk_count": self.rag_build.chunk_count,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,

            # 새로운 통합 필드
            "snapshot_id": self.snapshot_id,
            "dataset_id": self.dataset.dataset_id,
            "source_id": self.dataset.source_id,

            "tag_keyword_build_id": self.tag_keyword.tag_keyword_build_id,
            "graph_build_id": self.graph_build.graph_build_id,
            "ontology_id": self.graph_build.ontology_id,
            "wiki_build_id": self.wiki_build.wiki_build_id,

            "status": self.status.value,
            "is_active": self.is_active,
        }

    def get_build_summary(self) -> Dict[str, Any]:
        """빌드 상태 요약"""
        return {
            "snapshot_id": self.snapshot_id,
            "dataset_id": self.dataset.dataset_id,
            "status": self.status.value,
            "is_active": self.is_active,

            "documents": self.dataset.document_count,
            "metadata_extracted": self.dataset.metadata_extracted_count,

            "tags": self.tag_keyword.tag_count,
            "keywords": self.tag_keyword.keyword_count,

            "chunks": self.rag_build.chunk_count,
            "vectors": self.rag_build.vector_count,

            "graph_nodes": self.graph_build.node_count,
            "graph_edges": self.graph_build.edge_count,

            "wiki_articles": self.wiki_build.article_count,

            "created_at": self.created_at.isoformat() if self.created_at else None,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
        }


class ActiveSnapshotConfig(BaseModel):
    """
    활성 Snapshot 설정 - 사용자 검색 화면에서 사용하는 설정

    active_snapshot.json에 저장됨
    """

    # 현재 활성 Snapshot
    active_snapshot_id: str = Field(..., description="현재 활성 Snapshot ID")

    # 하위 호환성을 위한 FAISS 직접 참조
    faiss_index_id: Optional[str] = None
    index_file: Optional[str] = None
    metadata_file: Optional[str] = None
    embedding_provider: str = "ollama"

    # 통계
    vector_count: int = 0
    document_count: int = 0
    chunk_count: int = 0

    # Dataset 참조
    dataset_id: Optional[str] = None
    source_id: Optional[str] = None

    # 각 빌드 참조
    tag_keyword_build_id: Optional[str] = None
    graph_build_id: Optional[str] = None
    ontology_id: Optional[str] = None
    wiki_build_id: Optional[str] = None

    # 활성화 정보
    activated_at: Optional[datetime] = None
    activated_by: Optional[str] = None

    # 롤백 정보
    previous_snapshot_id: Optional[str] = None
    rollback_available: bool = False


class SnapshotHistory(BaseModel):
    """Snapshot 이력 관리"""
    source_id: str
    snapshots: List[SnapshotManifest] = Field(default_factory=list)

    def get_active_snapshot(self) -> Optional[SnapshotManifest]:
        """현재 활성 Snapshot 반환"""
        for snap in self.snapshots:
            if snap.is_active:
                return snap
        return None

    def get_latest_snapshot(self) -> Optional[SnapshotManifest]:
        """가장 최근 Snapshot 반환"""
        if not self.snapshots:
            return None
        return sorted(self.snapshots, key=lambda x: x.created_at, reverse=True)[0]

    def get_snapshot_by_id(self, snapshot_id: str) -> Optional[SnapshotManifest]:
        """ID로 Snapshot 조회"""
        for snap in self.snapshots:
            if snap.snapshot_id == snapshot_id:
                return snap
        return None
