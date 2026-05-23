# admin.html의 FAISS 파이프라인 API 안내를 실제 백엔드 흐름에 맞춘 작업 로그.

- 완료 시각: 2026-05-22
- 대상 파일: `frontend/admin.html`

## 작업 내용

- RAG Build Wizard Step 5 API 안내를 `POST /api/admin/faiss/jobs`, `GET /api/admin/faiss/jobs`, `GET /api/admin/faiss/jobs/{job_id}/stream` 기준으로 수정했습니다.
- RAG Build Wizard Step 6 API 안내를 `POST /api/admin/faiss/jobs`, `GET /api/admin/faiss/jobs`, `GET /api/admin/faiss/status` 기준으로 수정했습니다.
- RAG Source 탭의 stale 문구 `POST /api/admin/rag-source/faiss/build`를 제거하고 실제 흐름인 `POST /api/admin/faiss/jobs`와 `GET /api/admin/faiss/jobs`로 교체했습니다.
- 위저드 진행명과 카드 설명은 `syncWizardPipelineCopy()`로 런타임 동기화되도록 맞췄습니다.

## 검증

- `node -`로 `frontend/admin.html` 마지막 inline script를 추출한 뒤 `new Function(...)` 파싱 검증을 실행했습니다.
- 결과: `ADMIN_INLINE_PARSE_OK`
