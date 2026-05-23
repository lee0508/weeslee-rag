# 2026-05-22 Wizard Collection 작업 2단계 기록

- 완료 시각: 2026-05-22
- 단계: 자동 실행 순서 및 문구 수정
- 작업 내용:
  - `frontend/admin.html`의 Wizard Step 2 문구를 `Collection 생성`에서 `Collection 메타 동기화`로 변경했다.
  - Step 2 설명에 `전체 순차 실행에서는 자동으로 건너뜁니다.` 문구를 추가했다.
  - `WIZARD_STEPS[2].name`을 `Collection 메타 동기화`로 변경했다.
  - `wizardRunAll()`의 실행 순서를 `[1, 3, 4, 5, 6, 7, 8, 9, 10]`으로 바꿔 Step 2 `collections/bootstrap` 자동 호출을 제외했다.
  - 준비 상태 안내 문구도 `Collection 메타 동기화가 필요합니다.`로 수정했다.
  - `node --check frontend/assets/js/admin/admin-docs-layout.js` 정적 검증과 `rg` 기반 변경 확인을 수행했다.
