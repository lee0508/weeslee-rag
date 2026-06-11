-- Migration: Add missing fields to document_metadata for unified schema
-- Date: 2026-06-11
-- Description: SQLite documents 테이블과 스키마 통일을 위해 누락된 필드 추가

-- 파일 정보 필드 추가
ALTER TABLE document_metadata
ADD COLUMN file_name VARCHAR(500) NULL COMMENT 'Original filename' AFTER file_path;

ALTER TABLE document_metadata
ADD COLUMN file_type VARCHAR(50) NULL COMMENT 'File extension type (pdf, hwp, docx, etc)' AFTER file_name;

ALTER TABLE document_metadata
ADD COLUMN file_size BIGINT NULL COMMENT 'File size in bytes' AFTER file_type;

-- 처리 상태 필드 추가
ALTER TABLE document_metadata
ADD COLUMN status VARCHAR(50) DEFAULT 'registered' COMMENT 'Processing status: registered, text_extracted, chunked, embedded, faiss_indexed, rag_ready' AFTER year;

-- 사업 도메인 및 재사용 수준 추가
ALTER TABLE document_metadata
ADD COLUMN business_domain VARCHAR(200) NULL COMMENT 'Business domain category' AFTER organization_confidence;

ALTER TABLE document_metadata
ADD COLUMN reuse_level VARCHAR(20) DEFAULT 'medium' COMMENT 'Reuse level: high, medium, low' AFTER business_domain;

-- 문서 요약 추가
ALTER TABLE document_metadata
ADD COLUMN summary TEXT NULL COMMENT 'Document summary' AFTER reuse_level;

-- FAISS 관련 필드 추가
ALTER TABLE document_metadata
ADD COLUMN faiss_snapshot VARCHAR(100) NULL COMMENT 'FAISS snapshot name' AFTER include_in_wiki;

ALTER TABLE document_metadata
ADD COLUMN chunk_count INT DEFAULT 0 COMMENT 'Number of chunks' AFTER faiss_snapshot;

-- 신뢰도 필드 추가 (document_type, business_domain용)
ALTER TABLE document_metadata
ADD COLUMN document_type_confidence FLOAT NULL COMMENT 'Document type confidence 0.0-1.0' AFTER document_type;

-- 인덱스 추가
CREATE INDEX idx_status ON document_metadata (status);
CREATE INDEX idx_file_name ON document_metadata (file_name);
CREATE INDEX idx_document_type ON document_metadata (document_type);
