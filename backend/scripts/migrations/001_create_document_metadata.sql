-- Migration: Create document_metadata table for Dataset Builder Step 3
-- Date: 2026-06-05
-- Description: Stores operational metadata separate from basic document info

CREATE TABLE IF NOT EXISTS document_metadata (
    id INT AUTO_INCREMENT PRIMARY KEY,
    document_id INT NOT NULL UNIQUE,

    -- Step 1: Source Scan
    source_id VARCHAR(100) NULL COMMENT 'RAG Source ID',
    file_path VARCHAR(1000) NULL COMMENT 'Full file path on source mount',
    category_id VARCHAR(100) NULL COMMENT 'Category from source folder structure',

    -- Step 2: Metadata Auto-generation
    project_name VARCHAR(500) NULL COMMENT 'Extracted project name',
    project_name_confidence FLOAT NULL COMMENT 'Confidence score 0.0-1.0',
    organization VARCHAR(500) NULL COMMENT 'Client organization name',
    organization_confidence FLOAT NULL COMMENT 'Confidence score 0.0-1.0',
    document_type VARCHAR(100) NULL COMMENT 'RFP, 제안서, ISP보고서 etc',
    year INT NULL COMMENT 'Project year',

    -- Step 3: Metadata Review
    meta_status VARCHAR(50) NOT NULL DEFAULT 'registered' COMMENT 'registered, metadata_suggested, review_required, metadata_reviewed, rejected',
    reviewed_by VARCHAR(100) NULL COMMENT 'Admin username who reviewed',
    reviewed_at DATETIME NULL COMMENT 'Review timestamp',
    rejection_reason TEXT NULL COMMENT 'Reason for rejection',

    -- Collections
    collection_candidates JSON NULL COMMENT 'Auto-suggested collection IDs',
    final_collections JSON NULL COMMENT 'Admin-confirmed collection IDs',

    -- Tags & Keywords
    tags JSON NULL COMMENT 'Document tags',
    keywords JSON NULL COMMENT 'Extracted keywords',

    -- Include flags for downstream steps
    include_in_rag BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Include in FAISS index',
    include_in_graph BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Include in Graph build',
    include_in_wiki BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Include in Wiki build',

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_document_id (document_id),
    INDEX idx_source_id (source_id),
    INDEX idx_meta_status (meta_status),

    -- Foreign key
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
