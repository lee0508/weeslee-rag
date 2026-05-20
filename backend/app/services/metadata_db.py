# 문서 메타데이터 SQLite DB 서비스
"""
metadata_db.py

문서 메타데이터 관리를 위한 SQLite DB 서비스.
CRUD 및 쿼리 기능을 제공한다.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data" / "metadata.db"


@contextmanager
def get_db_connection():
    """SQLite DB 연결 컨텍스트 매니저."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def dict_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    """sqlite3.Row를 dict로 변환한다."""
    return dict(row) if row else None


class MetadataDBService:
    """문서 메타데이터 DB 서비스."""

    # ────────────────────────────────────────────────────────────────────────
    # Documents CRUD
    # ────────────────────────────────────────────────────────────────────────

    def get_document(self, document_id: int) -> Optional[Dict]:
        """문서 ID로 조회한다."""
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            )
            row = cursor.fetchone()
            return dict_from_row(row)

    def get_document_by_filename(self, file_name: str) -> Optional[Dict]:
        """파일명으로 조회한다."""
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM documents WHERE file_name = ?", (file_name,)
            )
            row = cursor.fetchone()
            return dict_from_row(row)

    def list_documents(
        self,
        document_type: Optional[str] = None,
        status: Optional[str] = None,
        meta_status: Optional[str] = None,
        organization: Optional[str] = None,
        project_year: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """문서 목록을 조회한다."""
        query = "SELECT * FROM documents WHERE 1=1"
        params = []

        if document_type:
            query += " AND document_type = ?"
            params.append(document_type)

        if status:
            query += " AND status = ?"
            params.append(status)

        if meta_status:
            query += " AND meta_status = ?"
            params.append(meta_status)

        if organization:
            query += " AND organization LIKE ?"
            params.append(f"%{organization}%")

        if project_year:
            query += " AND project_year = ?"
            params.append(project_year)

        if search:
            query += " AND (file_name LIKE ? OR project_name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with get_db_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict_from_row(row) for row in cursor.fetchall()]

    def count_documents(
        self,
        document_type: Optional[str] = None,
        status: Optional[str] = None,
        meta_status: Optional[str] = None,
    ) -> int:
        """문서 수를 센다."""
        query = "SELECT COUNT(*) FROM documents WHERE 1=1"
        params = []

        if document_type:
            query += " AND document_type = ?"
            params.append(document_type)

        if status:
            query += " AND status = ?"
            params.append(status)

        if meta_status:
            query += " AND meta_status = ?"
            params.append(meta_status)

        with get_db_connection() as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchone()[0]

    def get_document_stats(self) -> Dict[str, int]:
        """문서 현황 통계를 반환한다."""
        with get_db_connection() as conn:
            stats = {}

            # 전체 문서 수
            cursor = conn.execute("SELECT COUNT(*) FROM documents")
            stats["total"] = cursor.fetchone()[0]

            # 미분류 문서 수
            cursor = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE document_type = 'unknown' OR document_type IS NULL"
            )
            stats["unclassified"] = cursor.fetchone()[0]

            # 메타 확정 문서 수
            cursor = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE meta_status = 'confirmed'"
            )
            stats["confirmed"] = cursor.fetchone()[0]

            # RAG 준비 문서 수
            cursor = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE status = 'rag_ready'"
            )
            stats["rag_ready"] = cursor.fetchone()[0]

            # 상태별 문서 수
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count
                FROM documents
                GROUP BY status
            """)
            stats["by_status"] = {row["status"]: row["count"] for row in cursor.fetchall()}

            # 문서 유형별 수
            cursor = conn.execute("""
                SELECT document_type, COUNT(*) as count
                FROM documents
                GROUP BY document_type
            """)
            stats["by_type"] = {row["document_type"]: row["count"] for row in cursor.fetchall()}

            # 메타 상태별 수 (pending, auto_suggested, confirmed)
            cursor = conn.execute("""
                SELECT meta_status, COUNT(*) as count
                FROM documents
                GROUP BY meta_status
            """)
            stats["by_meta_status"] = {row["meta_status"] or "pending": row["count"] for row in cursor.fetchall()}

            return stats

    def create_document(self, data: Dict) -> int:
        """문서를 생성하고 ID를 반환한다."""
        with get_db_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO documents (
                    file_name, file_path, file_type, file_size,
                    document_type, project_name, organization, project_year,
                    business_domain, reuse_level, summary, status, meta_status,
                    faiss_snapshot, chunk_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("file_name"),
                data.get("file_path"),
                data.get("file_type"),
                data.get("file_size"),
                data.get("document_type", "unknown"),
                data.get("project_name"),
                data.get("organization"),
                data.get("project_year"),
                data.get("business_domain"),
                data.get("reuse_level", "medium"),
                data.get("summary"),
                data.get("status", "uploaded"),
                data.get("meta_status", "pending"),
                data.get("faiss_snapshot"),
                data.get("chunk_count", 0),
            ))
            conn.commit()
            return cursor.lastrowid

    def update_document(self, document_id: int, data: Dict) -> bool:
        """문서를 업데이트한다."""
        allowed_fields = [
            "file_name", "file_path", "file_type", "file_size",
            "document_type", "project_name", "organization", "project_year",
            "business_domain", "reuse_level", "summary", "status", "meta_status",
            "faiss_snapshot", "chunk_count",
        ]

        updates = []
        params = []
        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = ?")
                params.append(data[field])

        if not updates:
            return False

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(document_id)

        query = f"UPDATE documents SET {', '.join(updates)} WHERE id = ?"

        with get_db_connection() as conn:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0

    def delete_document(self, document_id: int) -> bool:
        """문서를 삭제한다."""
        with get_db_connection() as conn:
            cursor = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ────────────────────────────────────────────────────────────────────────
    # Metadata Suggestions
    # ────────────────────────────────────────────────────────────────────────

    def get_suggestion(self, document_id: int) -> Optional[Dict]:
        """문서의 자동 생성 메타데이터를 조회한다."""
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM document_metadata_suggestions WHERE document_id = ? ORDER BY id DESC LIMIT 1",
                (document_id,)
            )
            row = cursor.fetchone()
            if row:
                result = dict_from_row(row)
                # JSON 태그 파싱
                for tag_field in ["technology_tags", "business_tags", "deliverable_tags"]:
                    if result.get(tag_field):
                        try:
                            result[tag_field] = json.loads(result[tag_field])
                        except json.JSONDecodeError:
                            result[tag_field] = []
                return result
            return None

    def create_suggestion(self, document_id: int, data: Dict) -> int:
        """자동 생성 메타데이터를 저장한다."""
        with get_db_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO document_metadata_suggestions (
                    document_id, document_type, project_name, organization,
                    project_year, business_domain, summary, reuse_level,
                    confidence, technology_tags, business_tags, deliverable_tags,
                    reason, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                document_id,
                data.get("document_type"),
                data.get("project_name"),
                data.get("organization"),
                data.get("project_year"),
                data.get("business_domain"),
                data.get("summary"),
                data.get("reuse_level", "medium"),
                data.get("confidence", 0.0),
                json.dumps(data.get("technology_tags", []), ensure_ascii=False),
                json.dumps(data.get("business_tags", []), ensure_ascii=False),
                json.dumps(data.get("deliverable_tags", []), ensure_ascii=False),
                data.get("reason"),
                data.get("status", "auto_suggested"),
            ))
            conn.commit()
            return cursor.lastrowid

    def confirm_suggestion(self, document_id: int, data: Dict) -> bool:
        """자동 생성 메타데이터를 확정하고 documents 테이블에 반영한다."""
        with get_db_connection() as conn:
            # suggestion 상태 업데이트
            conn.execute("""
                UPDATE document_metadata_suggestions
                SET status = 'confirmed', updated_at = CURRENT_TIMESTAMP
                WHERE document_id = ?
            """, (document_id,))

            # documents 테이블 업데이트
            conn.execute("""
                UPDATE documents
                SET document_type = ?,
                    project_name = ?,
                    organization = ?,
                    project_year = ?,
                    business_domain = ?,
                    summary = ?,
                    reuse_level = ?,
                    meta_status = 'confirmed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                data.get("document_type"),
                data.get("project_name"),
                data.get("organization"),
                data.get("project_year"),
                data.get("business_domain"),
                data.get("summary"),
                data.get("reuse_level", "medium"),
                document_id,
            ))

            # 태그 저장
            self._save_tags(conn, document_id, data)

            conn.commit()
            return True

    def _save_tags(self, conn, document_id: int, data: Dict):
        """태그를 저장한다."""
        # 기존 태그 삭제
        conn.execute("DELETE FROM document_tags WHERE document_id = ?", (document_id,))

        # 새 태그 삽입
        tag_types = [
            ("technology", data.get("technology_tags", [])),
            ("business", data.get("business_tags", [])),
            ("deliverable", data.get("deliverable_tags", [])),
        ]

        for tag_type, tags in tag_types:
            for tag_value in tags:
                if tag_value:
                    conn.execute("""
                        INSERT INTO document_tags (document_id, tag_type, tag_value)
                        VALUES (?, ?, ?)
                    """, (document_id, tag_type, tag_value))

    # ────────────────────────────────────────────────────────────────────────
    # Processing Jobs
    # ────────────────────────────────────────────────────────────────────────

    def create_job(self, job_type: str, document_id: Optional[int] = None, document_ids: Optional[List[int]] = None) -> int:
        """처리 작업을 생성한다."""
        with get_db_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO processing_jobs (job_type, document_id, document_ids, status, started_at)
                VALUES (?, ?, ?, 'running', CURRENT_TIMESTAMP)
            """, (
                job_type,
                document_id,
                json.dumps(document_ids) if document_ids else None,
            ))
            conn.commit()
            return cursor.lastrowid

    def update_job(self, job_id: int, status: str, progress: int = 0, message: str = None):
        """처리 작업 상태를 업데이트한다."""
        with get_db_connection() as conn:
            if status in ("completed", "failed"):
                conn.execute("""
                    UPDATE processing_jobs
                    SET status = ?, progress = ?, message = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (status, progress, message, job_id))
            else:
                conn.execute("""
                    UPDATE processing_jobs
                    SET status = ?, progress = ?, message = ?
                    WHERE id = ?
                """, (status, progress, message, job_id))
            conn.commit()

    def get_job(self, job_id: int) -> Optional[Dict]:
        """처리 작업을 조회한다."""
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,))
            return dict_from_row(cursor.fetchone())


# 싱글톤 인스턴스
metadata_db_service = MetadataDBService()
