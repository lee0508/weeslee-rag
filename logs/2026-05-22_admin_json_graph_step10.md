# 2026-05-22 JSON Graph 작업 1단계 기록

- 완료 시각: 2026-05-22
- 단계: Docs 페이지 요약 연결
- 작업 내용:
  - `frontend/admin.html`의 `JSON Graph` 페이지 상단에 callout과 summary 카드 3개를 추가했다.
  - `frontend/assets/js/admin/admin-docs-layout.js`에 `refreshGraphSummary()`를 추가했다.
  - `/graph/summary` 응답을 읽어 프로젝트 수, 문서 수, edge 수, 데이터 존재 여부를 docs 페이지에 요약 표시하도록 했다.
  - `Graph Summary`, `Graph View` 카드 내부에 `wrGraphSummaryList`, `wrGraphViewList` 컨테이너가 없으면 JS가 동적으로 삽입하도록 처리했다.
  - 실제 상세 탐색은 기존 `graph` 레거시 탭을 유지하고, docs 페이지에는 운영 요약만 남기도록 정리했다.
  - `node --check frontend/assets/js/admin/admin-docs-layout.js` 정적 검증을 통과했다.
