-- Migration: Metadata 삼중 구조 필드 추가 (scan_* / ocr_* / final_*)
-- Date: 2026-06-19
-- Description: document_metadata 테이블에 출처별 metadata 필드 추가
--   dataset_id  : 빌드 실행 컨텍스트 키
--   scan_*      : Step 1 폴더 구조 기반 추출값
--   ocr_*       : Step 4 OCR 텍스트 기반 추출값
--   final_*     : Step 3 관리자 검수 확정값
-- 기존 project_name, organization, year, document_type 필드는 호환성 유지를 위해 보존.
-- final_* 필드와 동기화하여 사용한다.

-- ==========================================
-- 빌드 실행 컨텍스트 키
-- ==========================================
ALTER TABLE document_metadata
ADD COLUMN dataset_id VARCHAR(128) NULL COMMENT '빌드 실행 컨텍스트 키 (dataset_id)' AFTER source_id;

-- ==========================================
-- 1차 metadata: Step 1 폴더 구조 기반 (scan_*)
-- ==========================================
ALTER TABLE document_metadata
ADD COLUMN scan_project_name VARCHAR(255) NULL COMMENT 'Step 1: 파일명/폴더 기반 사업명' AFTER summary;

ALTER TABLE document_metadata
ADD COLUMN scan_organization VARCHAR(255) NULL COMMENT 'Step 1: 파일명/폴더 기반 발주기관' AFTER scan_project_name;

ALTER TABLE document_metadata
ADD COLUMN scan_year VARCHAR(20) NULL COMMENT 'Step 1: 파일명/폴더 기반 사업연도' AFTER scan_organization;

ALTER TABLE document_metadata
ADD COLUMN scan_document_category VARCHAR(100) NULL COMMENT 'Step 1: 폴더 구조 기반 문서분류' AFTER scan_year;

-- ==========================================
-- 2차 metadata: Step 4 OCR 텍스트 기반 (ocr_*)
-- ==========================================
ALTER TABLE document_metadata
ADD COLUMN ocr_project_name VARCHAR(255) NULL COMMENT 'Step 4: OCR 텍스트 기반 사업명' AFTER scan_document_category;

ALTER TABLE document_metadata
ADD COLUMN ocr_organization VARCHAR(255) NULL COMMENT 'Step 4: OCR 텍스트 기반 발주기관' AFTER ocr_project_name;

ALTER TABLE document_metadata
ADD COLUMN ocr_year VARCHAR(20) NULL COMMENT 'Step 4: OCR 텍스트 기반 사업연도' AFTER ocr_organization;

ALTER TABLE document_metadata
ADD COLUMN ocr_document_category VARCHAR(100) NULL COMMENT 'Step 4: OCR 텍스트 기반 문서분류' AFTER ocr_year;

ALTER TABLE document_metadata
ADD COLUMN ocr_confidence FLOAT NULL COMMENT 'Step 4: OCR 메타데이터 추출 평균 신뢰도 (0.0-1.0)' AFTER ocr_document_category;

ALTER TABLE document_metadata
ADD COLUMN ocr_quality_score DECIMAL(5,4) NULL COMMENT 'Step 4: OCR 텍스트 품질 점수 (0.0000-1.0000)' AFTER ocr_confidence;

ALTER TABLE document_metadata
ADD COLUMN ocr_parser_type VARCHAR(50) NULL COMMENT 'Step 4: 사용된 Parser 종류 (pdfplumber, olmocr 등)' AFTER ocr_quality_score;

ALTER TABLE document_metadata
ADD COLUMN ocr_page_count INT NULL COMMENT 'Step 4: OCR 처리 페이지 수' AFTER ocr_parser_type;

ALTER TABLE document_metadata
ADD COLUMN ocr_metadata_status VARCHAR(20) NULL DEFAULT 'pending' COMMENT 'Step 4: OCR metadata 반영 상태 (pending/success/failed)' AFTER ocr_page_count;

-- ==========================================
-- 확정 metadata: Step 3 관리자 검수 (final_*)
-- ==========================================
ALTER TABLE document_metadata
ADD COLUMN final_project_name VARCHAR(255) NULL COMMENT 'Step 3: 관리자 확정 사업명' AFTER ocr_metadata_status;

ALTER TABLE document_metadata
ADD COLUMN final_organization VARCHAR(255) NULL COMMENT 'Step 3: 관리자 확정 발주기관' AFTER final_project_name;

ALTER TABLE document_metadata
ADD COLUMN final_year VARCHAR(20) NULL COMMENT 'Step 3: 관리자 확정 사업연도' AFTER final_organization;

ALTER TABLE document_metadata
ADD COLUMN final_document_category VARCHAR(100) NULL COMMENT 'Step 3: 관리자 확정 문서분류' AFTER final_year;

ALTER TABLE document_metadata
ADD COLUMN final_confirmed_by VARCHAR(100) NULL COMMENT 'Step 3: 검수 승인자' AFTER final_document_category;

ALTER TABLE document_metadata
ADD COLUMN final_confirmed_at DATETIME NULL COMMENT 'Step 3: 검수 승인 일시' AFTER final_confirmed_by;

-- ==========================================
-- 기존 데이터 Migration: project_name / organization / year → final_*
-- ==========================================
UPDATE document_metadata
SET
    final_project_name  = project_name,
    final_organization  = organization,
    final_year          = CAST(year AS CHAR)
WHERE
    (project_name IS NOT NULL OR organization IS NOT NULL OR year IS NOT NULL)
    AND final_project_name IS NULL;

-- ==========================================
-- 조회 성능 인덱스
-- ==========================================
CREATE INDEX idx_document_metadata_source_dataset
ON document_metadata (source_id, dataset_id);

CREATE INDEX idx_document_metadata_document_dataset
ON document_metadata (document_id, dataset_id);
