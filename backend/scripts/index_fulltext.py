# OCR 텍스트를 FTS5 테이블에 인덱싱

import sqlite3
import sys
from pathlib import Path

def index_fulltext(source_id: str = None, batch_size: int = 100):
    """
    OCR 텍스트를 FTS5 테이블에 인덱싱

    Args:
        source_id: 특정 source_id만 인덱싱 (None이면 전체)
        batch_size: 배치 크기
    """
    db_path = Path(__file__).resolve().parents[2] / 'data' / 'metadata.db'
    processed_text_dir = Path(__file__).resolve().parents[2] / 'data' / 'processed_text'

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # documents 테이블에서 문서 목록 가져오기
    if source_id:
        cursor.execute('SELECT id, file_name, source_id FROM documents WHERE source_id = ?', (source_id,))
    else:
        cursor.execute('SELECT id, file_name, source_id FROM documents')

    documents = cursor.fetchall()
    total = len(documents)
    print(f'=== 전문 검색 인덱싱 시작 ===')
    print(f'대상 문서 수: {total}개')

    indexed = 0
    failed = 0

    for i, (doc_id, file_name, src_id) in enumerate(documents, 1):
        # processed_text에서 텍스트 로드
        text_file = processed_text_dir / str(doc_id) / 'full_text.txt'

        if not text_file.exists():
            failed += 1
            if i % batch_size == 0:
                print(f'진행: {i}/{total} (인덱싱: {indexed}, 실패: {failed})')
            continue

        try:
            full_text = text_file.read_text(encoding='utf-8')

            # FTS 테이블에 삽입 또는 업데이트
            cursor.execute('''
                INSERT INTO documents_fts(rowid, document_id, source_id, file_name, full_text)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(rowid) DO UPDATE SET
                    document_id = excluded.document_id,
                    source_id = excluded.source_id,
                    file_name = excluded.file_name,
                    full_text = excluded.full_text
            ''', (doc_id, doc_id, src_id, file_name, full_text[:50000]))  # 최대 50KB로 제한

            indexed += 1

            if i % batch_size == 0:
                conn.commit()
                print(f'진행: {i}/{total} (인덱싱: {indexed}, 실패: {failed})')

        except Exception as e:
            failed += 1
            print(f'문서 {doc_id} 인덱싱 실패: {e}')

    conn.commit()
    conn.close()

    print(f'\n=== 인덱싱 완료 ===')
    print(f'전체: {total}개')
    print(f'성공: {indexed}개')
    print(f'실패: {failed}개')


if __name__ == '__main__':
    source_id = sys.argv[1] if len(sys.argv) > 1 else None
    index_fulltext(source_id)
