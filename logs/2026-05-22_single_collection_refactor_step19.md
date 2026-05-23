# 2026-05-22 단일 Collection 재정의 Step19

## 완료 내용
- `backend/app/services/rag_source_pipeline.py`에서 manifest `collection_name`을 `weeslee_rag_main`으로 고정했다.
- 기존 folder-based `collection_key`를 `document_group` 기반 metadata 값으로 되돌렸다.
- `document_category`를 manifest, extract, chunk metadata 흐름에 추가했다.
- `backend/app/api/rag_source_admin.py`의 `metadata/build` 응답도 `collection_name`, `collection_key`, `document_category`를 같이 내보내도록 맞췄다.
- `collections/bootstrap`는 여러 폴더 컬렉션 대신 `weeslee_rag_main` 한 건만 동기화하도록 바꿨다.

## 검증
- `python -m compileall backend/app/services/rag_source_pipeline.py backend/app/api/rag_source_admin.py backend/scripts/extract_manifest_batch.py backend/scripts/build_chunk_batch.py`
- 결과: 4개 파일 모두 compile 통과.

## 남은 메모
- `backend/app/api/rag_source_admin.py`의 `bootstrap_collections` 아래에는 과거 template 기반 dead code가 return 뒤에 남아 있다.
- 현재 실행 경로에는 영향이 없지만, 다음 정리 단계에서 제거하는 것이 좋다.
