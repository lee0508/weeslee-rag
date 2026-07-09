#!/usr/bin/env python3
# system_settings 테이블 생성 및 초기 데이터 삽입 마이그레이션
# 작업일: 2026-07-08
# 작성자: Claude
"""
마이그레이션 005: system_settings 테이블 생성

하드코딩된 설정값들을 DB에서 관리하기 위한 테이블.
관리자 UI의 "시스템 설정" 탭에서 수정 가능.

실행 방법:
    cd /data/weeslee/weeslee-rag/backend
    python -m scripts.migrations.005_create_system_settings
"""
import platform
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from app.core.database import engine


# 테이블 생성 SQL
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS system_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category VARCHAR(50) NOT NULL COMMENT '설정 카테고리 (path, endpoint, model, rag, llm, search, ocr, security)',
    setting_key VARCHAR(100) NOT NULL COMMENT '설정 키',
    setting_value TEXT COMMENT '설정 값',
    value_type VARCHAR(20) DEFAULT 'string' COMMENT '값 타입 (string, int, float, bool, json, list)',
    description VARCHAR(500) COMMENT '설정 설명',
    is_sensitive BOOLEAN DEFAULT FALSE COMMENT '민감 정보 여부 (API 키 등)',
    platform VARCHAR(20) DEFAULT 'all' COMMENT '적용 플랫폼 (all, windows, linux)',
    requires_restart BOOLEAN DEFAULT FALSE COMMENT '변경 시 서버 재시작 필요 여부',
    editable BOOLEAN DEFAULT TRUE COMMENT 'UI에서 수정 가능 여부',
    display_order INT DEFAULT 0 COMMENT '표시 순서',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_category_key_platform (category, setting_key, platform)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='시스템 설정값 (하드코딩 제거용)';
"""

# 초기 데이터
INITIAL_DATA = [
    # ===== 카테고리: path (경로 설정) =====
    # Linux 경로
    ("path", "structured_txt_root", "/data/weeslee/weeslee-mnt/structured_txt", "string",
     "수동 구조화 TXT 파일 루트 경로", False, "linux", False, True, 10),
    ("path", "structured_json_root", "/data/weeslee/weeslee-mnt/structured_json", "string",
     "수동 구조화 JSON 파일 루트 경로", False, "linux", False, True, 20),
    ("path", "data_dir", "/data/weeslee/weeslee-rag/data", "string",
     "데이터 디렉토리 루트", False, "linux", True, True, 30),
    ("path", "project_dir", "/data/weeslee/weeslee-rag", "string",
     "프로젝트 루트 디렉토리", False, "linux", True, True, 40),
    ("path", "knowledge_source_mount", "/mnt/w2_project", "string",
     "지식 소스 마운트 경로", False, "linux", True, True, 50),

    # Windows 경로
    ("path", "structured_txt_root", r"C:\xampp\htdocs\weeslee-mnt\structured_txt", "string",
     "수동 구조화 TXT 파일 루트 경로", False, "windows", False, True, 10),
    ("path", "structured_json_root", r"C:\xampp\htdocs\weeslee-mnt\structured_json", "string",
     "수동 구조화 JSON 파일 루트 경로", False, "windows", False, True, 20),
    ("path", "data_dir", r"C:\xampp\htdocs\weeslee-rag\data", "string",
     "데이터 디렉토리 루트", False, "windows", True, True, 30),
    ("path", "project_dir", r"C:\xampp\htdocs\weeslee-rag", "string",
     "프로젝트 루트 디렉토리", False, "windows", True, True, 40),
    ("path", "knowledge_source_mount", "W:\\", "string",
     "지식 소스 마운트 경로 (드라이브)", False, "windows", True, True, 50),

    # ===== 카테고리: endpoint (서비스 엔드포인트) =====
    ("endpoint", "ollama_host", "http://localhost:11434", "string",
     "Ollama 서버 URL", False, "all", False, True, 10),
    ("endpoint", "qdrant_url", "http://localhost:6333", "string",
     "Qdrant 벡터 DB URL", False, "all", False, True, 20),
    ("endpoint", "chroma_host", "localhost", "string",
     "ChromaDB 호스트", False, "all", False, True, 30),
    ("endpoint", "chroma_port", "8000", "int",
     "ChromaDB 포트", False, "all", False, True, 40),
    ("endpoint", "rag_api_base", "http://127.0.0.1:8080", "string",
     "RAG API 베이스 URL", False, "all", False, True, 50),
    ("endpoint", "db_host", "localhost", "string",
     "MySQL 데이터베이스 호스트", False, "all", True, True, 60),
    ("endpoint", "db_port", "3306", "int",
     "MySQL 데이터베이스 포트", False, "all", True, True, 70),

    # ===== 카테고리: model (모델 설정) =====
    ("model", "default_llm_model", "qwen3:8b", "string",
     "기본 LLM 모델", False, "all", False, True, 10),
    ("model", "default_embedding_model", "nomic-embed-text", "string",
     "기본 임베딩 모델", False, "all", False, True, 20),
    ("model", "late_chunk_model", "BAAI/bge-m3", "string",
     "Late Chunking 모델", False, "all", False, True, 30),
    ("model", "contextual_retrieval_model", "exaone3.5", "string",
     "Contextual Retrieval 모델", False, "all", False, True, 40),
    ("model", "answer_model", "qwen3:8b", "string",
     "답변 생성 모델", False, "all", False, True, 50),
    ("model", "step5_llm_model", "claude-3-5-sonnet", "string",
     "Step5 태그/키워드 생성 LLM 모델", False, "all", False, True, 60),
    ("model", "step6_embedding_model", "ollama/nomic-embed-text", "string",
     "Step6 임베딩 모델", False, "all", False, True, 70),
    ("model", "step8_llm_model", "claude-3-5-sonnet", "string",
     "Step8 위키 생성 LLM 모델", False, "all", False, True, 80),

    # ===== 카테고리: rag (RAG 파라미터) =====
    ("rag", "chunk_size", "512", "int",
     "청크 크기 (토큰)", False, "all", False, True, 10),
    ("rag", "chunk_overlap", "50", "int",
     "청크 오버랩 (토큰)", False, "all", False, True, 20),
    ("rag", "min_chunk_size", "100", "int",
     "최소 청크 크기 (토큰)", False, "all", False, True, 30),
    ("rag", "embedding_dim", "768", "int",
     "임베딩 벡터 차원", False, "all", False, True, 40),
    ("rag", "max_embed_chars", "8000", "int",
     "최대 임베딩 문자 수", False, "all", False, True, 50),
    ("rag", "max_text_chars", "12000", "int",
     "최대 텍스트 문자 수 (structured content)", False, "all", False, True, 60),
    ("rag", "late_chunk_model_max_length", "8192", "int",
     "Late Chunking 모델 최대 길이", False, "all", False, True, 70),
    ("rag", "late_chunk_macro_overlap_tokens", "128", "int",
     "Late Chunking 매크로 오버랩 토큰", False, "all", False, True, 80),
    ("rag", "contextual_retrieval_doc_chars", "6000", "int",
     "Contextual Retrieval 문서 최대 문자 수", False, "all", False, True, 90),

    # ===== 카테고리: llm (LLM 생성 파라미터) =====
    ("llm", "temperature", "0.3", "float",
     "LLM 생성 온도 (0.0 ~ 2.0)", False, "all", False, True, 10),
    ("llm", "top_p", "0.9", "float",
     "Top-P 샘플링 (0.0 ~ 1.0)", False, "all", False, True, 20),
    ("llm", "max_tokens", "2000", "int",
     "최대 생성 토큰 수", False, "all", False, True, 30),

    # ===== 카테고리: search (검색 파라미터) =====
    ("search", "default_top_k", "10", "int",
     "기본 검색 결과 수", False, "all", False, True, 10),
    ("search", "max_top_k", "50", "int",
     "최대 검색 결과 수", False, "all", False, True, 20),
    ("search", "default_limit", "100", "int",
     "기본 목록 조회 제한", False, "all", False, True, 30),

    # ===== 카테고리: ocr (OCR 설정) =====
    ("ocr", "ocr_engine", "tesseract", "string",
     "OCR 엔진 (tesseract, paddleocr, easyocr)", False, "all", False, True, 10),
    ("ocr", "ocr_dpi", "300", "int",
     "OCR 이미지 DPI", False, "all", False, True, 20),
    ("ocr", "ocr_language", "kor+eng", "string",
     "OCR 언어 설정", False, "all", False, True, 30),
    ("ocr", "ocr_mode", "auto", "string",
     "OCR 모드 (auto, force, skip)", False, "all", False, True, 40),
    ("ocr", "ocr_min_text_length", "50", "int",
     "OCR 최소 텍스트 길이", False, "all", False, True, 50),

    # ===== 카테고리: security (보안/CORS 설정) =====
    ("security", "jwt_expire_hours", "8", "int",
     "JWT 토큰 만료 시간 (시간)", False, "all", True, True, 10),
    ("security", "cors_origins", '["http://localhost:3000","http://127.0.0.1:3000","http://localhost:8080","http://127.0.0.1:8080","http://192.168.0.207:8080","http://192.168.0.207:9284","http://server.weeslee.co.kr:9284","https://server.weeslee.co.kr"]', "json",
     "CORS 허용 Origin 목록", False, "all", True, True, 20),
]


def run_migration():
    """마이그레이션 실행."""
    print(f"[{datetime.now()}] 마이그레이션 005 시작: system_settings 테이블 생성")

    with engine.connect() as conn:
        # 1. 테이블 생성
        print("  1. system_settings 테이블 생성...")
        conn.execute(text(CREATE_TABLE_SQL))
        conn.commit()
        print("     완료")

        # 2. 기존 데이터 확인
        result = conn.execute(text("SELECT COUNT(*) FROM system_settings"))
        count = result.scalar()

        if count > 0:
            print(f"  2. 기존 데이터 {count}개 발견 - 초기 데이터 삽입 스킵")
        else:
            # 3. 초기 데이터 삽입
            print(f"  2. 초기 데이터 {len(INITIAL_DATA)}개 삽입...")

            insert_sql = """
            INSERT INTO system_settings
                (category, setting_key, setting_value, value_type, description,
                 is_sensitive, platform, requires_restart, editable, display_order)
            VALUES
                (:category, :setting_key, :setting_value, :value_type, :description,
                 :is_sensitive, :platform, :requires_restart, :editable, :display_order)
            """

            for row in INITIAL_DATA:
                conn.execute(text(insert_sql), {
                    "category": row[0],
                    "setting_key": row[1],
                    "setting_value": row[2],
                    "value_type": row[3],
                    "description": row[4],
                    "is_sensitive": row[5],
                    "platform": row[6],
                    "requires_restart": row[7],
                    "editable": row[8],
                    "display_order": row[9],
                })

            conn.commit()
            print("     완료")

        # 4. 결과 확인
        result = conn.execute(text("""
            SELECT category, COUNT(*) as cnt
            FROM system_settings
            GROUP BY category
            ORDER BY category
        """))

        print("\n  카테고리별 설정 수:")
        for row in result:
            print(f"    - {row[0]}: {row[1]}개")

    print(f"\n[{datetime.now()}] 마이그레이션 005 완료")


def rollback_migration():
    """마이그레이션 롤백."""
    print(f"[{datetime.now()}] 마이그레이션 005 롤백: system_settings 테이블 삭제")

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS system_settings"))
        conn.commit()

    print(f"[{datetime.now()}] 롤백 완료")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="마이그레이션 005: system_settings 테이블")
    parser.add_argument("--rollback", action="store_true", help="롤백 실행")
    args = parser.parse_args()

    if args.rollback:
        rollback_migration()
    else:
        run_migration()
