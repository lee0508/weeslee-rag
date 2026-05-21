# 사용자 질의와 검색 결과 요약 로그를 SQLite에 저장하고 조회하는 서비스
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data" / "metadata.db"


def _dict_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


class QueryLogService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS query_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    endpoint TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    query_preview TEXT,
                    prompt_source TEXT DEFAULT 'user',
                    effective_mode TEXT,
                    category_filter TEXT,
                    organization_filter TEXT,
                    year_filter TEXT,
                    top_k INTEGER DEFAULT 0,
                    top_docs INTEGER DEFAULT 0,
                    result_count INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 1,
                    error_message TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    client_ip TEXT,
                    user_agent TEXT,
                    top_document_ids TEXT DEFAULT '[]',
                    top_categories TEXT DEFAULT '[]',
                    top_source_paths TEXT DEFAULT '[]',
                    extra_json TEXT DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_query_logs_created_at ON query_logs (created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_query_logs_endpoint ON query_logs (endpoint)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_query_logs_success ON query_logs (success)"
            )
            conn.commit()

    def log_query(self, data: dict[str, Any]) -> int:
        query_text = str(data.get("query_text") or "").strip()
        if not query_text:
            query_text = "(empty)"
        query_preview = query_text[:240]
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO query_logs (
                    endpoint, query_text, query_preview, prompt_source, effective_mode,
                    category_filter, organization_filter, year_filter, top_k, top_docs,
                    result_count, success, error_message, duration_ms, client_ip, user_agent,
                    top_document_ids, top_categories, top_source_paths, extra_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("endpoint", ""),
                    query_text,
                    query_preview,
                    data.get("prompt_source", "user"),
                    data.get("effective_mode", ""),
                    data.get("category_filter", ""),
                    data.get("organization_filter", ""),
                    data.get("year_filter", ""),
                    int(data.get("top_k", 0) or 0),
                    int(data.get("top_docs", 0) or 0),
                    int(data.get("result_count", 0) or 0),
                    1 if data.get("success", True) else 0,
                    data.get("error_message", ""),
                    int(data.get("duration_ms", 0) or 0),
                    data.get("client_ip", ""),
                    data.get("user_agent", ""),
                    json.dumps(data.get("top_document_ids", []), ensure_ascii=False),
                    json.dumps(data.get("top_categories", []), ensure_ascii=False),
                    json.dumps(data.get("top_source_paths", []), ensure_ascii=False),
                    json.dumps(data.get("extra_json", {}), ensure_ascii=False),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_query_logs(
        self,
        *,
        endpoint: str = "",
        success: str = "",
        search: str = "",
        days: int = 7,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT *
            FROM query_logs
            WHERE created_at >= datetime('now', ?)
        """
        params: list[Any] = [f"-{max(1, days)} days"]

        if endpoint:
            query += " AND endpoint = ?"
            params.append(endpoint)
        if success in {"success", "failed"}:
            query += " AND success = ?"
            params.append(1 if success == "success" else 0)
        if search:
            query += " AND (query_text LIKE ? OR query_preview LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like])

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))

        with self._connect() as conn:
            rows = [_dict_from_row(row) for row in conn.execute(query, params).fetchall()]

        return [self._decode_row(row) for row in rows if row]

    def get_summary(self, *, days: int = 7, top_n: int = 10) -> dict[str, Any]:
        day_expr = f"-{max(1, days)} days"
        with self._connect() as conn:
            base = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failure_count,
                    SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) AS zero_result_count,
                    AVG(duration_ms) AS avg_duration_ms,
                    AVG(result_count) AS avg_result_count
                FROM query_logs
                WHERE created_at >= datetime('now', ?)
                """,
                (day_expr,),
            ).fetchone()

            endpoint_rows = conn.execute(
                """
                SELECT endpoint, COUNT(*) AS count
                FROM query_logs
                WHERE created_at >= datetime('now', ?)
                GROUP BY endpoint
                ORDER BY count DESC, endpoint ASC
                """,
                (day_expr,),
            ).fetchall()

            mode_rows = conn.execute(
                """
                SELECT effective_mode, COUNT(*) AS count
                FROM query_logs
                WHERE created_at >= datetime('now', ?)
                GROUP BY effective_mode
                ORDER BY count DESC, effective_mode ASC
                """,
                (day_expr,),
            ).fetchall()

            top_query_rows = conn.execute(
                """
                SELECT query_preview, COUNT(*) AS count
                FROM query_logs
                WHERE created_at >= datetime('now', ?)
                GROUP BY query_preview
                ORDER BY count DESC, MAX(created_at) DESC
                LIMIT ?
                """,
                (day_expr, top_n),
            ).fetchall()

            recent_failures = conn.execute(
                """
                SELECT id, endpoint, query_preview, error_message, created_at
                FROM query_logs
                WHERE created_at >= datetime('now', ?) AND success = 0
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (day_expr, top_n),
            ).fetchall()

        total = int((base["total"] or 0) if base else 0)
        success_count = int((base["success_count"] or 0) if base else 0)
        failure_count = int((base["failure_count"] or 0) if base else 0)
        zero_result_count = int((base["zero_result_count"] or 0) if base else 0)
        success_rate = round((success_count / total) * 100, 2) if total else 0.0

        return {
            "days": days,
            "total": total,
            "success_count": success_count,
            "failure_count": failure_count,
            "zero_result_count": zero_result_count,
            "success_rate": success_rate,
            "avg_duration_ms": round(float(base["avg_duration_ms"] or 0), 2) if base else 0.0,
            "avg_result_count": round(float(base["avg_result_count"] or 0), 2) if base else 0.0,
            "endpoint_counts": {row["endpoint"] or "(unknown)": row["count"] for row in endpoint_rows},
            "mode_counts": {row["effective_mode"] or "(none)": row["count"] for row in mode_rows},
            "top_queries": [
                {"query_preview": row["query_preview"] or "", "count": row["count"]}
                for row in top_query_rows
            ],
            "recent_failures": [
                {
                    "id": row["id"],
                    "endpoint": row["endpoint"],
                    "query_preview": row["query_preview"] or "",
                    "error_message": row["error_message"] or "",
                    "created_at": row["created_at"],
                }
                for row in recent_failures
            ],
        }

    def _decode_row(self, row: dict[str, Any]) -> dict[str, Any]:
        for key in ("top_document_ids", "top_categories", "top_source_paths", "extra_json"):
            try:
                row[key] = json.loads(row.get(key) or ("{}" if key == "extra_json" else "[]"))
            except Exception:
                row[key] = {} if key == "extra_json" else []
        row["success"] = bool(row.get("success"))
        return row


query_log_service = QueryLogService(DB_PATH)
