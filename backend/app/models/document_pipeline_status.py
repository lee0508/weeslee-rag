# 문서 파이프라인 상태 추적 모델 (10단계 Dataset Builder용)
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class StepStatus(str, Enum):
    """각 단계의 처리 상태"""
    NOT_STARTED = "not_started"      # 아직 시작 안 함
    PENDING = "pending"               # 대기 중 (이전 단계 미완료)
    IN_PROGRESS = "in_progress"       # 진행 중
    COMPLETED = "completed"           # 완료
    FAILED = "failed"                 # 실패
    SKIPPED = "skipped"               # 건너뜀
    REVIEW_REQUIRED = "review_required"  # 검수 필요 (Step 3 전용)
    REJECTED = "rejected"             # 반려됨 (Step 3 전용)


class Step1SourceScanStatus(BaseModel):
    """Step 1: Source Scan 상태"""
    status: StepStatus = StepStatus.NOT_STARTED
    scanned_at: Optional[datetime] = None
    document_id: Optional[str] = None  # DOC-20260604-000001
    source_id: Optional[str] = None    # 01_rfp, 02_01_strategy
    category_id: Optional[str] = None  # category 식별자
    snapshot_id: Optional[str] = None  # snapshot_20260604_1430
    file_count: int = 1
    error_message: Optional[str] = None


class Step2MetadataAutoStatus(BaseModel):
    """Step 2: Metadata Auto 상태"""
    status: StepStatus = StepStatus.PENDING
    extracted_at: Optional[datetime] = None
    project_name: Optional[str] = None
    project_name_confidence: Optional[float] = None
    organization: Optional[str] = None
    organization_confidence: Optional[float] = None
    document_type: Optional[str] = None  # rfp, proposal, deliverable
    document_type_confidence: Optional[float] = None
    year: Optional[int] = None
    collection_candidates: List[str] = Field(default_factory=list)
    avg_confidence: Optional[float] = None
    error_message: Optional[str] = None


class Step3MetadataReviewStatus(BaseModel):
    """Step 3: Metadata Review 상태"""
    status: StepStatus = StepStatus.PENDING
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None  # 관리자 ID
    review_status: Optional[str] = None  # registered, metadata_suggested, review_required, metadata_reviewed, ready_for_processing
    final_project_name: Optional[str] = None
    final_organization: Optional[str] = None
    final_document_type: Optional[str] = None
    final_collection_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    include_in_rag: bool = True
    include_in_graph: bool = True
    include_in_wiki: bool = True
    rejection_reason: Optional[str] = None
    error_message: Optional[str] = None


class Step4OCRParserStatus(BaseModel):
    """Step 4: OCR/Parser 상태"""
    status: StepStatus = StepStatus.PENDING
    processed_at: Optional[datetime] = None
    ocr_engine: Optional[str] = None  # olmOCR, Tesseract, EasyOCR
    total_pages: Optional[int] = None
    extracted_chars: Optional[int] = None
    ocr_quality_score: Optional[float] = None  # 0.0 ~ 1.0
    failed_pages: List[int] = Field(default_factory=list)
    output_files: List[str] = Field(default_factory=list)  # full_text.md, pages.jsonl
    error_message: Optional[str] = None


class Step5ChunkBuildStatus(BaseModel):
    """Step 5: Chunk Build 상태"""
    status: StepStatus = StepStatus.PENDING
    processed_at: Optional[datetime] = None
    chunk_method: Optional[str] = None  # recursive, sentence, semantic, heading, slide
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    total_chunks: int = 0
    text_chunks: int = 0
    table_chunks: int = 0
    slide_chunks: int = 0
    avg_chunk_size: Optional[int] = None
    output_file: Optional[str] = None  # chunks.jsonl
    error_message: Optional[str] = None


class Step6EmbeddingBuildStatus(BaseModel):
    """Step 6: Embedding Build 상태"""
    status: StepStatus = StepStatus.PENDING
    processed_at: Optional[datetime] = None
    embedding_model: Optional[str] = None  # nomic-embed-text, bge-m3
    embedding_dimension: Optional[int] = None
    batch_size: Optional[int] = None
    total_embeddings: int = 0
    failed_embeddings: int = 0
    avg_time_per_embedding: Optional[float] = None  # seconds
    output_file: Optional[str] = None  # embeddings.jsonl
    error_message: Optional[str] = None


class Step7FAISSBuildStatus(BaseModel):
    """Step 7: FAISS Build 상태"""
    status: StepStatus = StepStatus.PENDING
    processed_at: Optional[datetime] = None
    collections_built: List[str] = Field(default_factory=list)  # ["col_all", "col_rfp"]
    total_vectors: int = 0
    index_type: Optional[str] = None  # flat, ivf, hnsw
    index_files: List[str] = Field(default_factory=list)  # index.faiss, index_meta.jsonl
    snapshot_id: Optional[str] = None
    error_message: Optional[str] = None


class Step8GraphBuildStatus(BaseModel):
    """Step 8: Graph Build 상태"""
    status: StepStatus = StepStatus.PENDING
    processed_at: Optional[datetime] = None
    graph_storage: str = "json"  # json, neo4j
    nodes_created: int = 0
    edges_created: int = 0
    node_types: Dict[str, int] = Field(default_factory=dict)  # {"Project": 1, "Document": 1, "Organization": 1}
    output_files: List[str] = Field(default_factory=list)  # graph_nodes.jsonl, graph_edges.jsonl
    error_message: Optional[str] = None


class Step9WikiBuildStatus(BaseModel):
    """Step 9: Wiki Build 상태"""
    status: StepStatus = StepStatus.PENDING
    processed_at: Optional[datetime] = None
    wiki_model: Optional[str] = None  # gemma3:12b, qwen3:8b
    grouping_by: Optional[str] = None  # project, organization, domain, technology
    wiki_files_created: List[str] = Field(default_factory=list)
    wiki_count: int = 0
    avg_generation_time: Optional[float] = None  # seconds
    error_message: Optional[str] = None


class Step10SearchQualityStatus(BaseModel):
    """Step 10: Search Quality / Activate 상태"""
    status: StepStatus = StepStatus.PENDING
    quality_checked_at: Optional[datetime] = None
    quality_test_passed: bool = False
    quality_score: Optional[float] = None  # 0.0 ~ 1.0
    test_queries_count: Optional[int] = None
    activated_at: Optional[datetime] = None
    active_snapshot_id: Optional[str] = None
    active_collections: List[str] = Field(default_factory=list)
    rollback_available: bool = False
    previous_snapshot_id: Optional[str] = None
    error_message: Optional[str] = None


class DocumentPipelineStatus(BaseModel):
    """문서 전체 파이프라인 상태 (10단계)"""
    document_id: str
    filename: str
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None  # pdf, hwp, hwpx, docx, pptx, xlsx

    # 10단계 상태
    step1_source_scan: Step1SourceScanStatus = Field(default_factory=Step1SourceScanStatus)
    step2_metadata_auto: Step2MetadataAutoStatus = Field(default_factory=Step2MetadataAutoStatus)
    step3_metadata_review: Step3MetadataReviewStatus = Field(default_factory=Step3MetadataReviewStatus)
    step4_ocr_parser: Step4OCRParserStatus = Field(default_factory=Step4OCRParserStatus)
    step5_chunk_build: Step5ChunkBuildStatus = Field(default_factory=Step5ChunkBuildStatus)
    step6_embedding_build: Step6EmbeddingBuildStatus = Field(default_factory=Step6EmbeddingBuildStatus)
    step7_faiss_build: Step7FAISSBuildStatus = Field(default_factory=Step7FAISSBuildStatus)
    step8_graph_build: Step8GraphBuildStatus = Field(default_factory=Step8GraphBuildStatus)
    step9_wiki_build: Step9WikiBuildStatus = Field(default_factory=Step9WikiBuildStatus)
    step10_search_quality: Step10SearchQualityStatus = Field(default_factory=Step10SearchQualityStatus)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class DatasetStatusSummary(BaseModel):
    """전체 데이터셋 상태 요약 (admin.html Dataset Builder용)"""

    # 전체 문서 통계
    total_documents: int = 0

    # Step별 통계
    step1_completed: int = 0
    step1_failed: int = 0

    step2_completed: int = 0
    step2_pending: int = 0
    step2_avg_confidence: Optional[float] = None

    step3_reviewed: int = 0
    step3_review_required: int = 0
    step3_rejected: int = 0

    step4_completed: int = 0
    step4_in_progress: int = 0
    step4_failed: int = 0
    step4_avg_quality: Optional[float] = None

    step5_completed: int = 0
    step5_total_chunks: int = 0
    step5_avg_chunks_per_doc: Optional[float] = None

    step6_completed: int = 0
    step6_total_embeddings: int = 0
    step6_failed_embeddings: int = 0
    step6_embedding_model: Optional[str] = None

    step7_collections_built: int = 0
    step7_total_vectors: int = 0
    step7_snapshot_id: Optional[str] = None

    step8_nodes_created: int = 0
    step8_edges_created: int = 0
    step8_graph_storage: str = "json"

    step9_wiki_count: int = 0
    step9_wiki_model: Optional[str] = None

    step10_quality_passed: bool = False
    step10_quality_score: Optional[float] = None
    step10_active_snapshot: Optional[str] = None
    step10_active_collections: List[str] = Field(default_factory=list)

    # 마지막 업데이트 시간
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
