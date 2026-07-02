-- Dataset Builder 단계별 설정을 저장하는 테이블
-- source_id별로 각 빌드 단계의 설정을 JSON 형식으로 저장

CREATE TABLE IF NOT EXISTS dataset_build_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source_id VARCHAR(100) NOT NULL,
    dataset_id VARCHAR(150) NULL,

    -- Step 3: 메타데이터 추출 설정
    step3_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    step3_config JSON NULL COMMENT '{"extraction_rules": {...}, "category_mapping": {...}}',

    -- Step 4: OCR/파싱 설정
    step4_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    step4_config JSON NULL COMMENT '{"ocr_engine": "tesseract", "ocr_dpi": 300, "ocr_language": "kor+eng", ...}',

    -- Step 5: Tag/Keyword 생성 설정
    step5_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    step5_config JSON NULL COMMENT '{"llm_model": "claude-3-5-sonnet", "max_tags": 10, "max_keywords": 20, ...}',

    -- Step 6: 청킹/임베딩 설정
    step6_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    step6_config JSON NULL COMMENT '{"chunk_size": 512, "chunk_overlap": 50, "embedding_model": "ollama/nomic-embed-text", ...}',

    -- Step 7: Knowledge Graph 설정
    step7_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    step7_config JSON NULL COMMENT '{"ontology_id": "default", "graph_mode": "basic", ...}',

    -- Step 8: LLM Wiki 설정
    step8_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    step8_config JSON NULL COMMENT '{"llm_model": "claude-3-5-sonnet", "max_articles": 30, ...}',

    -- Step 10: FAISS 인덱스 설정
    step10_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    step10_config JSON NULL COMMENT '{"index_type": "Flat", "use_gpu": true, "gpu_devices": "0", ...}',

    created_at VARCHAR(40) NULL,
    updated_at VARCHAR(40) NULL,

    UNIQUE KEY idx_dataset_build_settings_source (source_id),
    KEY idx_dataset_build_settings_dataset (dataset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
