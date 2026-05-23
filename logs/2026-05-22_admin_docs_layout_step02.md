# 2026-05-22 admin docs layout step 2

- 완료 시각: 2026-05-22
- 단계: 정적 검증

## 실행 내용

- `python -m compileall backend`
- `node --check frontend/assets/js/admin/admin-docs-layout.js`
- `frontend/admin.html` 내 새 Docs 레이아웃 페이지 위치를 수동 확인했다.

## 결과

- `backend` 전체 compileall이 통과했다.
- `admin-docs-layout.js` 문법 검사가 통과했다.
- 새 Docs 레이아웃 안에는 `rag-build-wizard`, `logs`, `search-quality` 페이지가 존재한다.
- 레거시 `pipeline` 내부에 잘못 들어간 `search-quality` 중복 블록은 HTML 주석으로 비활성화했다.

## 다음 단계

- 커밋 범위를 확정한다.
- `.claude/settings.json`은 배포 범위에서 제외한다.
- 커밋 후 `git push`, 원격 pull, 서비스 재시작, 헬스체크를 진행한다.
