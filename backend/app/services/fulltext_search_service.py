# 전문 검색 서비스 (SQLite FTS5 사용)

import sqlite3
from pathlib import Path
from typing import List, Dict, Any

_DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'metadata.db'


def search_fulltext(
    query: str,
    source_id: str = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    FTS5를 사용한 전문 검색

    Args:
        query: 검색 쿼리
        source_id: 특정 source_id로 필터링 (None이면 전체)
        limit: 최대 결과 수

    Returns:
        검색 결과 리스트 (document_id, score, snippet 포함)
    """
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # FTS5 검색 쿼리
    if source_id:
        cursor.execute('''
            SELECT
                document_id,
                source_id,
                file_name,
                snippet(documents_fts, 3, '<b>', '</b>', '...', 30) AS snippet,
                rank AS score
            FROM documents_fts
            WHERE documents_fts MATCH ? AND source_id = ?
            ORDER BY rank
            LIMIT ?
        ''', (query, source_id, limit))
    else:
        cursor.execute('''
            SELECT
                document_id,
                source_id,
                file_name,
                snippet(documents_fts, 3, '<b>', '</b>', '...', 30) AS snippet,
                rank AS score
            FROM documents_fts
            WHERE documents_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        ''', (query, limit))

    results = []
    for row in cursor.fetchall():
        results.append({
            'document_id': row['document_id'],
            'source_id': row['source_id'],
            'file_name': row['file_name'],
            'snippet': row['snippet'],
            'score': row['score']
        })

    conn.close()
    return results


def count_fulltext_indexed(source_id: str = None) -> int:
    """
    인덱싱된 문서 수 확인

    Args:
        source_id: 특정 source_id (None이면 전체)

    Returns:
        인덱싱된 문서 수
    """
    conn = sqlite3.connect(_DB_PATH)
    cursor = conn.cursor()

    if source_id:
        cursor.execute('SELECT COUNT(*) FROM documents_fts WHERE source_id = ?', (source_id,))
    else:
        cursor.execute('SELECT COUNT(*) FROM documents_fts')

    count = cursor.fetchone()[0]
    conn.close()
    return count
