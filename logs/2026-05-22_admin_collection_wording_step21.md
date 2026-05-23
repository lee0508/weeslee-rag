# 2026-05-22 관리자 Collection 문구 정리 Step21

## 완료 내용
- `frontend/admin.html`의 Wizard Step 2 설명을 `weeslee_rag_main` 단일 Collection + metadata filter 구조에 맞게 수정했다.
- 증분 추가용 Collection 선택을 `weeslee_rag_main` 기준으로 단순화했다.
- Collection Manager의 버튼, 빈 상태 안내, 입력 placeholder를 현재 구조에 맞게 정리했다.
- `backend/app/api/rag_source_admin.py`의 `bootstrap_collections` 아래 return 뒤 dead code를 제거했다.

## 검증
- `python -m compileall backend/app/api/rag_source_admin.py backend/app/api/rag.py`
- `node -`로 `frontend/admin.html` 마지막 inline script `new Function(...)` 파싱
- `node -`로 `frontend/rag-assistant.html` 마지막 inline script `new Function(...)` 파싱
- 결과: 모두 통과.

## 메모
- 이제 관리자 문구와 실제 백엔드 구조가 같은 방향을 가리킨다.
