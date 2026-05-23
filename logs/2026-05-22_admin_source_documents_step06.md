# 2026-05-22 Source Documents 작업 2단계 기록

- 완료 시각: 2026-05-22
- 단계: Docs 페이지 API 연결 구현
- 작업 내용:
  - `frontend/assets/js/admin/admin-docs-layout.js`에 `ensureSourceDocumentsUi()`를 추가했다.
  - `Source Documents` 페이지 진입 시 정적 fallback callout은 숨기고, 페이지 안내 문구를 실사용 기준 문구로 교체하도록 했다.
  - `Source Registry`, `Scan Preview` 목록 컨테이너가 HTML에 없어도 JS가 동적으로 삽입하도록 처리했다.
  - 기본 source path/client input에 id가 없어도 JS가 현재 입력 필드를 찾아 연결하도록 처리했다.
  - API 성공 시 source 요약, mount 상태, 기본 경로/클라이언트를 반영하고, 실패 시 고정 fallback 대신 실제 실패 메시지를 표시하도록 바꿨다.
