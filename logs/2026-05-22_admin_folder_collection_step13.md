# 2026-05-22 폴더 기준 Collection 작업 1단계 기록

- 완료 시각: 2026-05-22
- 단계: 현행 기준 확인
- 작업 내용:
  - `backend/app/services/rag_source_pipeline.py`에서 현재 `collection_key`가 문서 그룹 기반(`rag_source_rfp` 등)으로 생성되는 점을 확인했다.
  - `backend/app/api/rag_source_admin.py`의 `bootstrap_collections()`가 템플릿 기반으로 `collections_active`를 채우고 있는 점을 확인했다.
  - `metadata/build`의 `collection` 값도 현재는 폴더가 아니라 규칙 기반 category를 사용하고 있는 점을 확인했다.
  - 사용자 요구에 맞추려면 manifest, metadata, collection bootstrap 세 군데를 동시에 같은 폴더 기준으로 바꿔야 한다고 판단했다.
