# P0 RAG 응답 구조 표준화 체크리스트

- [x] 현재 `/api/rag/query`, `/api/rag/similar-files`, 사용자 검색 카드 구조 확인
- [x] 백엔드 문서 응답에 표준 메타데이터 필드 추가
- [x] 검색 근거 chunk를 구조화된 `evidence_snippets`로 반환
- [x] 기존 프론트 카드가 구조화 snippet을 표시하도록 호환 처리
- [x] 백엔드와 프론트 문법 검증
- [x] 변경 사항 커밋
- [x] 실제 등록 라우터 `backend/app/api/rag.py` 반영
- [ ] 실제 등록 라우터 변경 재배포
