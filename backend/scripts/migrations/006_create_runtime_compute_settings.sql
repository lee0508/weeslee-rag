CREATE TABLE IF NOT EXISTS runtime_compute_settings (
    id VARCHAR(100) PRIMARY KEY,
    gpu_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    cuda_visible_devices VARCHAR(50) NULL,
    ollama_use_gpu BOOLEAN NOT NULL DEFAULT TRUE,
    ocr_use_gpu BOOLEAN NOT NULL DEFAULT TRUE,
    chunk_use_gpu BOOLEAN NOT NULL DEFAULT TRUE,
    embedding_use_gpu BOOLEAN NOT NULL DEFAULT TRUE,
    faiss_use_gpu BOOLEAN NOT NULL DEFAULT TRUE,
    created_at VARCHAR(40) NULL,
    updated_at VARCHAR(40) NULL
);
