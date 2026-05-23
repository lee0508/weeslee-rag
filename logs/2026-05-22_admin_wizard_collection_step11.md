# 2026-05-22 Wizard Collection 작업 1단계 기록

- 완료 시각: 2026-05-22
- 단계: 원인 확인
- 작업 내용:
  - `frontend/admin.html`의 `WIZARD_STEPS`와 `wizardRunAll()` 흐름을 확인했다.
  - 현재 `전체 순차 실행`이 Step 2 `POST /api/admin/rag-source/collections/bootstrap`를 자동 실행하고 있는 점을 확인했다.
  - `backend/app/api/rag_source_admin.py`의 `bootstrap_collections()`는 실제 VectorDB collection 생성이 아니라 `collections_active` 스토어 메타 동기화라는 점을 확인했다.
  - 따라서 현재 Step 2 명칭과 자동 실행 순서가 운영 의미와 맞지 않는다고 판단했다.
