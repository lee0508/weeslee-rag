# 문서 메타데이터 관리용 SQLite DB 초기화 스크립트
"""
init_metadata_db.py

문서 메타데이터 관리를 위한 SQLite DB를 생성한다.
기존 FAISS 메타데이터(JSONL)와 별도로 운영되며,
문서 업로드/자동 메타 생성/검수/확정 워크플로우를 지원한다.

사용:
    python backend/scripts/init_metadata_db.py

생성 파일:
    data/metadata.db
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "metadata.db"


def init_db():
    """SQLite DB를 초기화한다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print(f"[시작] SQLite DB 초기화: {DB_PATH}")

    # ────────────────────────────────────────────────────────────────────────
    # 1. documents 테이블 - 문서 기본 정보 및 메타데이터
    # ────────────────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- 파일 정보
            file_name TEXT NOT NULL,
            file_path TEXT,
            file_type TEXT,
            file_size INTEGER,

            -- 문서 유형 (rfp, proposal, kickoff_report 등)
            document_type TEXT DEFAULT 'unknown',

            -- 사업 정보
            project_name TEXT,
            organization TEXT,
            project_year TEXT,
            business_domain TEXT,

            -- 재사용 가능성 (high, medium, low)
            reuse_level TEXT DEFAULT 'medium',

            -- 문서 요약
            summary TEXT,

            -- 처리 상태 (uploaded, text_extracted, chunked, embedded, faiss_indexed, rag_ready 등)
            status TEXT DEFAULT 'uploaded',

            -- 메타데이터 상태 (pending, auto_suggested, confirmed)
            meta_status TEXT DEFAULT 'pending',

            -- FAISS 인덱스 연결 정보
            faiss_snapshot TEXT,
            chunk_count INTEGER DEFAULT 0,

            -- 타임스탬프
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("[OK] documents 테이블 생성 완료")

    # ────────────────────────────────────────────────────────────────────────
    # 2. document_metadata_suggestions 테이블 - 자동 생성된 메타데이터
    # ────────────────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_metadata_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,

            -- 자동 생성된 메타데이터
            document_type TEXT,
            project_name TEXT,
            organization TEXT,
            project_year TEXT,
            business_domain TEXT,
            summary TEXT,
            reuse_level TEXT DEFAULT 'medium',

            -- 자동 추출 신뢰도 (0.0 ~ 1.0)
            confidence REAL DEFAULT 0.0,

            -- 태그 (JSON 배열 문자열)
            technology_tags TEXT DEFAULT '[]',
            business_tags TEXT DEFAULT '[]',
            deliverable_tags TEXT DEFAULT '[]',

            -- 자동 추출 근거
            reason TEXT,

            -- 상태 (auto_suggested, confirmed, rejected)
            status TEXT DEFAULT 'auto_suggested',

            -- 타임스탬프
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        )
    """)
    print("[OK] document_metadata_suggestions 테이블 생성 완료")

    # ────────────────────────────────────────────────────────────────────────
    # 3. document_tags 테이블 - 태그 관리 (정규화)
    # ────────────────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,

            -- 태그 유형 (technology, business, deliverable, organization)
            tag_type TEXT NOT NULL,

            -- 태그 값
            tag_value TEXT NOT NULL,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        )
    """)
    print("[OK] document_tags 테이블 생성 완료")

    # ────────────────────────────────────────────────────────────────────────
    # 4. processing_jobs 테이블 - 처리 작업 이력
    # ────────────────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processing_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- 작업 유형 (auto_metadata, chunking, embedding, faiss_indexing)
            job_type TEXT NOT NULL,

            -- 대상 문서 ID (단일 문서) 또는 NULL (배치)
            document_id INTEGER,

            -- 배치 작업 시 대상 문서 ID 목록 (JSON 배열)
            document_ids TEXT,

            -- 작업 상태 (pending, running, completed, failed)
            status TEXT DEFAULT 'pending',

            -- 진행률 (0 ~ 100)
            progress INTEGER DEFAULT 0,

            -- 결과 메시지
            message TEXT,

            -- 타임스탬프
            started_at DATETIME,
            completed_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("[OK] processing_jobs 테이블 생성 완료")

    # ────────────────────────────────────────────────────────────────────────
    # 인덱스 생성
    # ────────────────────────────────────────────────────────────────────────
    indexes = [
        ("idx_documents_document_type", "documents", "document_type"),
        ("idx_documents_status", "documents", "status"),
        ("idx_documents_meta_status", "documents", "meta_status"),
        ("idx_documents_organization", "documents", "organization"),
        ("idx_documents_project_year", "documents", "project_year"),
        ("idx_suggestions_document_id", "document_metadata_suggestions", "document_id"),
        ("idx_suggestions_status", "document_metadata_suggestions", "status"),
        ("idx_tags_document_id", "document_tags", "document_id"),
        ("idx_tags_type_value", "document_tags", "tag_type, tag_value"),
        ("idx_jobs_status", "processing_jobs", "status"),
    ]

    for idx_name, table, columns in indexes:
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({columns})
        """)
    print(f"[OK] 인덱스 {len(indexes)}개 생성 완료")

    conn.commit()
    conn.close()

    print(f"[완료] SQLite DB 초기화 완료: {DB_PATH}")
    print(f"       파일 크기: {DB_PATH.stat().st_size} bytes")


def import_from_faiss_metadata():
    """
    기존 FAISS 메타데이터(JSONL)에서 문서 정보를 가져와 documents 테이블에 삽입한다.
    """
    import os

    FAISS_DIR = DATA_DIR / "indexes" / "faiss"
    ACTIVE_INDEX_PATH = DATA_DIR / "active_index.json"

    if not ACTIVE_INDEX_PATH.exists():
        print("[SKIP] active_index.json이 없습니다. FAISS 메타데이터 가져오기를 건너뜁니다.")
        return

    # 활성 스냅샷 확인
    with open(ACTIVE_INDEX_PATH, "r", encoding="utf-8") as f:
        active_info = json.load(f)
    snapshot = active_info.get("snapshot", "")

    if not snapshot:
        print("[SKIP] 활성 스냅샷이 없습니다.")
        return

    meta_path = FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl"
    if not meta_path.exists():
        print(f"[SKIP] 메타데이터 파일이 없습니다: {meta_path}")
        return

    print(f"[시작] FAISS 메타데이터 가져오기: {meta_path}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 기존 문서 파일명 목록 조회 (중복 방지)
    cursor.execute("SELECT file_name FROM documents")
    existing_files = {row[0] for row in cursor.fetchall()}

    # FAISS 메타데이터에서 고유 문서 추출 (document_id 기준)
    documents_map = {}  # document_id -> metadata

    # category를 document_type으로 매핑
    category_to_type = {
        "rfp": "rfp",
        "proposal": "proposal",
        "kickoff": "kickoff_report",
        "final_report": "final_report",
        "presentation": "presentation",
    }

    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
                document_id = chunk.get("document_id", "")
                if not document_id:
                    continue

                # 첫 번째 청크의 메타데이터만 사용
                if document_id not in documents_map:
                    # source_path에서 파일명 추출
                    source_path = chunk.get("source_path", "")
                    file_name = os.path.basename(source_path) if source_path else document_id

                    # 중첩된 metadata에서 추가 정보 추출
                    nested_meta = chunk.get("metadata", {})

                    # category를 document_type으로 변환
                    category = chunk.get("category", "unknown")
                    document_type = category_to_type.get(category, category)

                    # source_path에서 사업명/기관 추정 (폴더 이름 활용)
                    project_name = nested_meta.get("project_name", "")
                    organization = nested_meta.get("organization_client", "")

                    # 폴더 경로에서 사업명 추정 시도
                    if not project_name and source_path:
                        # 예: "202212. k-water 데이터허브플랫폼_ISP" 형태에서 추출
                        path_parts = source_path.replace("\\", "/").split("/")
                        for part in path_parts:
                            if part.startswith("20") and len(part) > 10:
                                project_name = part
                                break

                    documents_map[document_id] = {
                        "document_id": document_id,
                        "file_name": file_name,
                        "file_path": source_path,
                        "document_type": document_type,
                        "project_name": project_name,
                        "organization": organization,
                        "project_year": "",
                        "faiss_snapshot": snapshot,
                    }
            except json.JSONDecodeError:
                continue

    # 신규 문서 삽입
    inserted = 0
    for doc_id, meta in documents_map.items():
        if meta["file_name"] in existing_files:
            continue

        cursor.execute("""
            INSERT INTO documents (
                file_name, file_path, document_type, project_name, organization,
                project_year, faiss_snapshot, status, meta_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'rag_ready', 'pending')
        """, (
            meta["file_name"],
            meta["file_path"],
            meta["document_type"],
            meta["project_name"],
            meta["organization"],
            meta["project_year"],
            meta["faiss_snapshot"],
        ))
        inserted += 1

    conn.commit()
    conn.close()

    print(f"[완료] {inserted}개 문서 가져오기 완료 (기존: {len(existing_files)}개)")


if __name__ == "__main__":
    init_db()

    # 기존 FAISS 메타데이터가 있으면 가져오기
    import_from_faiss_metadata()
