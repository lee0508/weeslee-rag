-- Migration: Add document_uid and tracking fields for Dataset Builder
-- Date: 2026-06-12
-- Description: source_id + relative_path 기반 문서 고유 식별자 및 추적 필드 추가
-- Reference: docs/2026-06-12_Claude_QA_V1_Followup_Order.md

-- ============================================================
-- 1. document_metadata 테이블 필드 추가
-- ============================================================

-- document_uid: sha1(source_id + ":" + relative_path) 기반 고유 식별자
ALTER TABLE document_metadata
ADD COLUMN IF NOT EXISTS document_uid VARCHAR(64) NULL COMMENT 'sha1(source_id:relative_path) 문서 고유 식별자';

-- relative_path: mount_path + root_subpath 기준 상대 경로
ALTER TABLE document_metadata
ADD COLUMN IF NOT EXISTS relative_path VARCHAR(1000) NULL COMMENT 'Document Source 기준 상대 경로';

-- file_checksum: SHA256 파일 내용 체크섬
ALTER TABLE document_metadata
ADD COLUMN IF NOT EXISTS file_checksum VARCHAR(64) NULL COMMENT 'SHA256 파일 내용 체크섬';

-- file_modified_at: 원본 파일 수정 시간
ALTER TABLE document_metadata
ADD COLUMN IF NOT EXISTS file_modified_at DATETIME NULL COMMENT '원본 파일 수정 시간';

-- is_excluded: 전체 처리 제외 여부
ALTER TABLE document_metadata
ADD COLUMN IF NOT EXISTS is_excluded TINYINT(1) NOT NULL DEFAULT 0 COMMENT '전체 처리 제외 여부';

-- exclude_reason: 제외 사유
ALTER TABLE document_metadata
ADD COLUMN IF NOT EXISTS exclude_reason VARCHAR(255) NULL COMMENT '제외 사유';

-- removed_at: 원본 파일 삭제 감지 일시
ALTER TABLE document_metadata
ADD COLUMN IF NOT EXISTS removed_at DATETIME NULL COMMENT '원본 파일 삭제 감지 일시';

-- removed_reason: 삭제/제거 사유
ALTER TABLE document_metadata
ADD COLUMN IF NOT EXISTS removed_reason VARCHAR(255) NULL COMMENT '삭제/제거 사유';

-- is_orphan: Document Source 매칭 실패 여부
ALTER TABLE document_metadata
ADD COLUMN IF NOT EXISTS is_orphan TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Document Source 매칭 실패 여부';

-- orphan_reason: orphan 사유
ALTER TABLE document_metadata
ADD COLUMN IF NOT EXISTS orphan_reason VARCHAR(255) NULL COMMENT 'orphan 사유';

-- ============================================================
-- 2. documents 테이블 필드 추가
-- ============================================================

-- document_uid
ALTER TABLE documents
ADD COLUMN IF NOT EXISTS document_uid VARCHAR(64) NULL COMMENT 'sha1(source_id:relative_path) 문서 고유 식별자';

-- source_id
ALTER TABLE documents
ADD COLUMN IF NOT EXISTS source_id VARCHAR(100) NULL COMMENT 'RAG Source ID';

-- relative_path
ALTER TABLE documents
ADD COLUMN IF NOT EXISTS relative_path VARCHAR(1000) NULL COMMENT 'Document Source 기준 상대 경로';

-- removed_at
ALTER TABLE documents
ADD COLUMN IF NOT EXISTS removed_at DATETIME NULL COMMENT '원본 파일 삭제 감지 일시';

-- ============================================================
-- 3. 인덱스 추가
-- ============================================================

-- document_metadata 인덱스
CREATE INDEX IF NOT EXISTS idx_dm_document_uid ON document_metadata (document_uid);
CREATE INDEX IF NOT EXISTS idx_dm_relative_path ON document_metadata (relative_path(255));
CREATE INDEX IF NOT EXISTS idx_dm_is_excluded ON document_metadata (is_excluded);
CREATE INDEX IF NOT EXISTS idx_dm_removed_at ON document_metadata (removed_at);
CREATE INDEX IF NOT EXISTS idx_dm_is_orphan ON document_metadata (is_orphan);

-- documents 인덱스
CREATE INDEX IF NOT EXISTS idx_docs_document_uid ON documents (document_uid);
CREATE INDEX IF NOT EXISTS idx_docs_source_id ON documents (source_id);
CREATE INDEX IF NOT EXISTS idx_docs_removed_at ON documents (removed_at);

-- ============================================================
-- 4. 복합 인덱스 (빌드 대상 필터용)
-- ============================================================

-- FAISS 빌드 대상: metadata_reviewed + include_in_rag + not excluded + not removed
CREATE INDEX IF NOT EXISTS idx_dm_faiss_target
ON document_metadata (meta_status, include_in_rag, is_excluded, removed_at);

-- Graph 빌드 대상
CREATE INDEX IF NOT EXISTS idx_dm_graph_target
ON document_metadata (meta_status, include_in_graph, is_excluded, removed_at);

-- Wiki 빌드 대상
CREATE INDEX IF NOT EXISTS idx_dm_wiki_target
ON document_metadata (meta_status, include_in_wiki, is_excluded, removed_at);
