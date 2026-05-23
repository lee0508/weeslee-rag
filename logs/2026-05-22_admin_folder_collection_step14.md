폴더 기준 Collection 생성 작업 기록.

- 대상 파일.
  - `backend/app/services/rag_source_pipeline.py`
  - `backend/app/api/rag_source_admin.py`
- 변경 내용.
  - manifest의 `collection_key`를 문서 그룹 기반 값이 아니라 파일 직접 상위 폴더명 기준으로 변경했다.
  - `metadata/build` 결과의 `collection`도 같은 기준을 반환하도록 맞췄다.
  - `collections/bootstrap`는 `collection_templates` seed 대신 `metadata.db` 문서 경로를 읽어 폴더명별 `collections_active`를 동기화하도록 변경했다.
- 구현 판단.
  - 사용자 요청 문구인 `파일이 속해 있는 폴더명`을 현재는 직접 상위 폴더명으로 해석했다.
  - `00. RAG 소스`는 `source_root` 설명값으로 유지하고, 실제 마운트 경로는 `document_sources.mount_path` 우선, 없으면 `knowledge_source_service.get_root_path()` fallback으로 채웠다.
- 검증.
  - `python -m compileall backend/app/api/rag_source_admin.py backend/app/services/rag_source_pipeline.py`
  - 결과는 통과였다.
- 남은 리스크.
  - 직접 상위 폴더명과 프로젝트 루트 폴더명이 다를 수 있는 구조에서는 Collection 단위 해석을 다시 정해야 한다.
