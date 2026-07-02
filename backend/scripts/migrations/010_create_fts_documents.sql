-- SQLite FTS5 가상 테이블 생성
-- OCR 텍스트 전문 검색 지원

-- FTS5 가상 테이블 생성
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    document_id UNINDEXED,
    source_id UNINDEXED,
    file_name,
    full_text,
    content='documents',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- 트리거: documents 테이블에 새 레코드 삽입 시 FTS 테이블에도 삽입
CREATE TRIGGER IF NOT EXISTS documents_fts_insert AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, document_id, source_id, file_name, full_text)
    VALUES (new.id, new.id, new.source_id, new.file_name, '');
END;

-- 트리거: documents 테이블의 레코드 삭제 시 FTS 테이블에서도 삭제
CREATE TRIGGER IF NOT EXISTS documents_fts_delete AFTER DELETE ON documents BEGIN
    DELETE FROM documents_fts WHERE rowid = old.id;
END;

-- 트리거: documents 테이블의 레코드 업데이트 시 FTS 테이블도 업데이트
CREATE TRIGGER IF NOT EXISTS documents_fts_update AFTER UPDATE ON documents BEGIN
    DELETE FROM documents_fts WHERE rowid = old.id;
    INSERT INTO documents_fts(rowid, document_id, source_id, file_name, full_text)
    VALUES (new.id, new.id, new.source_id, new.file_name, '');
END;
