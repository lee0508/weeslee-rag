-- documents 테이블에 source_id 컬럼 추가
-- Dataset Builder로 생성한 특정 source_id의 문서만 필터링 가능하도록

ALTER TABLE documents ADD COLUMN source_id VARCHAR(100) NULL
  COMMENT 'Dataset Builder source ID for filtering';

CREATE INDEX idx_documents_source_id ON documents(source_id);
