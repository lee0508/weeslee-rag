context-notes.broken.md
- 2026-05-22. admin.html의 Step 5, Step 6은 개별 OCR/chunk/build API가 아니라 POST /api/admin/faiss/jobs 하나로 시작되는 통합 파이프라인입니다. 진행 조회는 GET /api/admin/faiss/jobs, 세부 추적은 GET /api/admin/faiss/jobs/{job_id}/stream으로 맞춰야 합니다.
- 2026-05-22. 위저드 카드 본문 텍스트는 파일 인코딩 이력 때문에 직접 문자열 수정이 불안정할 수 있어, syncWizardPipelineCopy()로 런타임 동기화하는 방식이 더 안전했습니다.