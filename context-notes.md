## 2026-05-26 Overview 빠른 이동 버튼 점검

- `frontend/admin.html`의 Overview 빠른 이동 버튼은 `openSourceManagement()`, `openBuildWizard()`, `openSearchQuality()` inline 함수를 호출한다.
- 현재 세 함수는 각각 Legacy 탭인 `docsource`, `wizard`, `benchmark`로 이동한다.
- 새 관리자 화면의 사이드바와 본문은 `frontend/assets/js/admin/admin-docs-layout.js`의 `setActivePage()`가 제어한다.
- 빠른 이동 버튼 문구는 Overview의 Docs 스타일 섹션에서 쓰이고 있으므로, 기본 동작은 Docs 페이지인 `source-documents`, `rag-build-wizard`, `search-quality`로 이동하는 것이 자연스럽다.
- `admin-docs-layout.js`에 `window.openWrDocsPage(pageName)`를 노출하고, 기존 inline 함수는 이 함수를 우선 호출한다.
- Docs 레이아웃 스크립트가 로드되지 않는 경우를 대비해 기존 Legacy 탭 이동 fallback은 유지한다.
- 배포본도 확인했으며, 2026-05-26 13:36 KST 기준 `openWrDocsPage`가 없고 빠른 이동 함수가 Legacy 탭으로 직접 이동하는 상태다.
- `openBuildWizard()`의 fallback은 존재하지 않는 `syncWizardStepStatuses` 대신 실제 정의된 `window.syncWizardStepperState`를 호출하도록 정리했다.
