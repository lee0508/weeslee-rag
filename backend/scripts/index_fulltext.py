# OCR 텍스트를 FTS5 테이블에 인덱싱

import sqlite3
import sys
from pathlib import Path

# MySQL 연결을 위한 import
backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))
from app.core.database import get_db
from app.models.document_metadata import DocumentMetadata


def index_fulltext(source_id: str = None, batch_size: int = 100):
    """
    OCR 텍스트를 FTS5 테이블에 인덱싱

    Args:
        source_id: 특정 source_id만 인덱싱 (None이면 전체)
        batch_size: 배치 크기
    """
    db_path = Path(__file__).resolve().parents[2] / 'data' / 'metadata.db'
    processed_text_dir = Path(__file__).resolve().parents[2] / 'data' / 'processed_text'

    # SQLite 연결 (FTS5 테이블용)
    sqlite_conn = sqlite3.connect(db_path)
    sqlite_cursor = sqlite_conn.cursor()

    # MySQL에서 문서 목록 가져오기
    db = next(get_db())
    query = db.query(DocumentMetadata)

    if source_id:
        query = query.filter(DocumentMetadata.source_id == source_id)

    documents = query.all()
    total = len(documents)
    print(f'=== 전문 검색 인덱싱 시작 ===')
    print(f'대상 문서 수: {total}개')

    indexed = 0
    failed = 0

    for i, doc in enumerate(documents, 1):
        doc_id = doc.document_id
        file_name = Path(doc.file_path).name if doc.file_path else f"doc_{doc_id}"
        src_id = doc.source_id

        # processed_text에서 텍스트 로드
        text_file = processed_text_dir / str(doc_id) / 'full_text.txt'

        if not text_file.exists():
            failed += 1
            if i % batch_size == 0:
                print(f'진행: {i}/{total} (인덱싱: {indexed}, 실패: {failed})')
            continue

        try:
            full_text = text_file.read_text(encoding='utf-8')

            # FTS 테이블에 기존 레코드 삭제 후 삽입
            sqlite_cursor.execute('DELETE FROM documents_fts WHERE rowid = ?', (doc_id,))
            sqlite_cursor.execute('''
                INSERT INTO documents_fts(rowid, document_id, source_id, file_name, full_text)
                VALUES (?, ?, ?, ?, ?)
            ''', (doc_id, doc_id, src_id, file_name, full_text[:50000]))  # 최대 50KB로 제한

            indexed += 1

            if i % batch_size == 0:
                sqlite_conn.commit()
                print(f'진행: {i}/{total} (인덱싱: {indexed}, 실패: {failed})')

        except Exception as e:
            failed += 1
            print(f'문서 {doc_id} 인덱싱 실패: {e}')

    sqlite_conn.commit()
    sqlite_conn.close()
    db.close()

    print(f'\n=== 인덱싱 완료 ===')
    print(f'전체: {total}개')
    print(f'성공: {indexed}개')
    print(f'실패: {failed}개')


if __name__ == '__main__':
    source_id = sys.argv[1] if len(sys.argv) > 1 else None
    index_fulltext(source_id)
