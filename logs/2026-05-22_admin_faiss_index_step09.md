# 2026-05-22 FAISS Index 작업 1단계 기록

- 완료 시각: 2026-05-22
- 단계: Docs 페이지 요약 연결
- 작업 내용:
  - `frontend/admin.html`의 `FAISS Index` 페이지 상단에 callout과 summary 카드 3개를 추가했다.
  - `frontend/assets/js/admin/admin-docs-layout.js`에 `refreshFaissSummary()`를 추가했다.
  - `FAISS status`와 `jobs` API를 읽어 활성 snapshot, chunk 수, 최근 job 수를 요약 카드에 표시하도록 했다.
  - `Active Index`, `Pipeline` 카드 내부에 `wrFaissActiveList`, `wrFaissJobList` 컨테이너가 없으면 JS가 동적으로 삽입하도록 처리했다.
  - API 실패 시 `FAISS API 연결 실패` 문구와 빈 상태 메시지를 표시하도록 했다.
  - `node --check frontend/assets/js/admin/admin-docs-layout.js` 정적 검증을 통과했다.
