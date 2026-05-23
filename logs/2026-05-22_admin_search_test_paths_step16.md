관리자 검색 테스트 경로 노출 작업 기록.

- 대상 파일.
  - `backend/app/api/rag.py`
  - `frontend/admin.html`
- 변경 내용.
  - `/api/rag/search` 결과에 `project_name`, `file_name`, `source_path`, `original_source_path`, `relative_path`, `collection_key`를 추가했다.
  - 관리자 `검색 테스트`는 기존 `renderSearchResults()` 대신 파일 경로 중심 표시용 `renderSearchResultsWithPaths()`를 사용하도록 바꿨다.
  - 결과 카드에서 snippet만 보는 것이 아니라 collection, relative path, 실제 원본 경로를 함께 보이게 했다.
- 구현 의도.
  - 관리자 화면에서도 “검색이 실제 파일을 찾았는지”를 바로 판단할 수 있어야 한다.
  - 운영자는 경로와 collection을 보고 검색 품질과 데이터 정합성을 빠르게 확인할 수 있어야 한다.
- 검증.
  - `python -m compileall backend/app/api/rag.py`
  - 결과는 통과였다.
- 남은 리스크.
  - `frontend/admin.html` 전체 script 문법 자동 검증은 아직 수행하지 못했다.
  - 실제 브라우저에서 관리자 `검색 테스트`를 실행해 카드 레이아웃과 긴 경로 줄바꿈을 확인해야 한다.
