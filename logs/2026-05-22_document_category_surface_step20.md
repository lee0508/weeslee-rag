# 2026-05-22 document_category 노출 Step20

## 완료 내용
- `/api/rag/search`와 답변 근거 문서 응답에 `document_category`를 추가했다.
- 관리자 `검색 테스트` 결과 카드에 `document_category` chip을 추가했다.
- `rag-assistant.html` 근거 파일 카드에도 `document_category` chip을 추가했다.

## 검증
- `python -m compileall backend/app/api/rag.py`
- `node -`로 `frontend/rag-assistant.html` 마지막 inline script를 `new Function(...)` 파싱
- 결과: 모두 통과.

## 메모
- 이제 단일 collection 구조에서도 사용자와 관리자 화면에서 `document_group`/`document_category` 기준이 함께 보인다.
