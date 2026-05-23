# 2026-05-22 Source Documents 작업 4단계 기록

- 완료 시각: 2026-05-22
- 단계: 호출 경로 정리 및 검증 보강
- 작업 내용:
  - `frontend/assets/js/admin/admin-docs-layout.js`에 `renderSourceDocumentsPage()`를 추가하고, `refreshPageData('source-documents')`가 이 함수를 직접 호출하도록 바꿨다.
  - `frontend/admin.html`의 기본 source path/client input에 `wrSourceDefaultPath`, `wrSourceDefaultClient` id를 명시적으로 추가했다.
  - `refreshSourceDocuments = renderSourceDocumentsPage;` 바인딩을 추가해 최종 실행 경로를 새 함수로 고정했다.
  - `node --check frontend/assets/js/admin/admin-docs-layout.js` 문법 검증은 통과했다.
  - `curl.exe -I http://127.0.0.1/weeslee-rag/frontend/admin.html` 검증은 로컬 `127.0.0.1:80` 연결 실패로 브라우저 경로 확인을 진행하지 못했다.
