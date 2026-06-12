# Dataset Builder 문서 고유 식별자 및 추적 필드 마이그레이션
"""
Migration: Add document_uid and tracking fields for Dataset Builder
Date: 2026-06-12
Description: source_id + relative_path 기반 문서 고유 식별자 및 추적 필드 추가
Reference: docs/2026-06-12_Claude_QA_V1_Followup_Order.md

Usage:
    cd /data/weeslee/weeslee-rag/backend
    python scripts/migrations/003_add_document_uid_and_tracking_fields.py
"""
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from sqlalchemy import text, inspect
from app.core.database import engine


# ============================================================
# 1. document_metadata 테이블 컬럼 정의
# ============================================================
DOCUMENT_METADATA_COLUMNS = {
    "document_uid": "VARCHAR(64) NULL COMMENT 'sha1(source_id:relative_path) 문서 고유 식별자'",
    "relative_path": "VARCHAR(1000) NULL COMMENT 'Document Source 기준 상대 경로'",
    "file_checksum": "VARCHAR(64) NULL COMMENT 'SHA256 파일 내용 체크섬'",
    "file_modified_at": "DATETIME NULL COMMENT '원본 파일 수정 시간'",
    "is_excluded": "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '전체 처리 제외 여부'",
    "exclude_reason": "VARCHAR(255) NULL COMMENT '제외 사유'",
    "removed_at": "DATETIME NULL COMMENT '원본 파일 삭제 감지 일시'",
    "removed_reason": "VARCHAR(255) NULL COMMENT '삭제/제거 사유'",
    "is_orphan": "TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Document Source 매칭 실패 여부'",
    "orphan_reason": "VARCHAR(255) NULL COMMENT 'orphan 사유'",
}


# ============================================================
# 2. documents 테이블 컬럼 정의
# ============================================================
DOCUMENTS_COLUMNS = {
    "document_uid": "VARCHAR(64) NULL COMMENT 'sha1(source_id:relative_path) 문서 고유 식별자'",
    "source_id": "VARCHAR(100) NULL COMMENT 'RAG Source ID'",
    "relative_path": "VARCHAR(1000) NULL COMMENT 'Document Source 기준 상대 경로'",
    "removed_at": "DATETIME NULL COMMENT '원본 파일 삭제 감지 일시'",
}


# ============================================================
# 3. 인덱스 정의
# ============================================================
DOCUMENT_METADATA_INDEXES = [
    ("idx_dm_document_uid", "document_metadata", "(document_uid)"),
    ("idx_dm_relative_path", "document_metadata", "(relative_path(255))"),
    ("idx_dm_is_excluded", "document_metadata", "(is_excluded)"),
    ("idx_dm_removed_at", "document_metadata", "(removed_at)"),
    ("idx_dm_is_orphan", "document_metadata", "(is_orphan)"),
    ("idx_dm_faiss_target", "document_metadata", "(meta_status, include_in_rag, is_excluded, removed_at)"),
    ("idx_dm_graph_target", "document_metadata", "(meta_status, include_in_graph, is_excluded, removed_at)"),
    ("idx_dm_wiki_target", "document_metadata", "(meta_status, include_in_wiki, is_excluded, removed_at)"),
]

DOCUMENTS_INDEXES = [
    ("idx_docs_document_uid", "documents", "(document_uid)"),
    ("idx_docs_source_id", "documents", "(source_id)"),
    ("idx_docs_removed_at", "documents", "(removed_at)"),
]


def get_existing_columns(inspector, table_name: str) -> set:
    """테이블의 기존 컬럼 목록 조회"""
    try:
        columns = inspector.get_columns(table_name)
        return {col["name"] for col in columns}
    except Exception:
        return set()


def get_existing_indexes(inspector, table_name: str) -> set:
    """테이블의 기존 인덱스 목록 조회"""
    try:
        indexes = inspector.get_indexes(table_name)
        return {idx["name"] for idx in indexes}
    except Exception:
        return set()


def add_columns(conn, table_name: str, columns: dict, existing: set):
    """누락된 컬럼만 추가"""
    for name, ddl in columns.items():
        if name in existing:
            print(f"  [SKIP] {table_name}.{name} - already exists")
            continue

        sql = f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"
        print(f"  [ADD] {table_name}.{name}")
        try:
            conn.execute(text(sql))
        except Exception as e:
            print(f"  [ERROR] {e}")


def add_indexes(conn, indexes: list, existing: set):
    """누락된 인덱스만 추가"""
    for idx_name, table_name, columns in indexes:
        if idx_name in existing:
            print(f"  [SKIP] {idx_name} - already exists")
            continue

        sql = f"CREATE INDEX {idx_name} ON {table_name} {columns}"
        print(f"  [ADD] {idx_name}")
        try:
            conn.execute(text(sql))
        except Exception as e:
            print(f"  [ERROR] {e}")


def run():
    """마이그레이션 실행"""
    inspector = inspect(engine)

    print("=" * 60)
    print("Migration 003: Add document_uid and tracking fields")
    print("=" * 60)

    with engine.begin() as conn:
        # 1. document_metadata 테이블
        print("\n[1/4] document_metadata 컬럼 추가")
        dm_existing = get_existing_columns(inspector, "document_metadata")
        add_columns(conn, "document_metadata", DOCUMENT_METADATA_COLUMNS, dm_existing)

        # 2. documents 테이블
        print("\n[2/4] documents 컬럼 추가")
        docs_existing = get_existing_columns(inspector, "documents")
        add_columns(conn, "documents", DOCUMENTS_COLUMNS, docs_existing)

        # 3. document_metadata 인덱스
        print("\n[3/4] document_metadata 인덱스 추가")
        dm_idx_existing = get_existing_indexes(inspector, "document_metadata")
        add_indexes(conn, DOCUMENT_METADATA_INDEXES, dm_idx_existing)

        # 4. documents 인덱스
        print("\n[4/4] documents 인덱스 추가")
        docs_idx_existing = get_existing_indexes(inspector, "documents")
        add_indexes(conn, DOCUMENTS_INDEXES, docs_idx_existing)

    print("\n" + "=" * 60)
    print("Migration 003 completed!")
    print("=" * 60)


if __name__ == "__main__":
    run()
