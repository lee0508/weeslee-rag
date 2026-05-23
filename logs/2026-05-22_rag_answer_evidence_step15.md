답변 근거 파일 노출 작업 기록.

- 대상 파일.
  - `backend/app/api/rag.py`
  - `frontend/rag-assistant.html`
- 변경 내용.
  - `/api/rag/query` 응답에 `evidence_documents`, `retrieval_summary`를 추가했다.
  - `/api/rag/answer` 응답에도 상위 근거 파일 목록 `evidence_documents`를 포함시켰다.
  - `rag-assistant.html`의 답변 탭에서 답변 텍스트만 보여주던 구조를 바꾸고, 관련 파일명, 상대 경로/원본 경로, 열기/다운로드 액션을 함께 표시하도록 했다.
  - 검색 전용 모드에서도 답변 탭에서 근거 파일을 바로 볼 수 있게 했다.
- 구현 의도.
  - 시스템 목적을 “LLM이 무엇을 생성했는가”보다 “어떤 문서를 찾아서 근거로 삼았는가”에 맞췄다.
  - 사용자는 관련 파일이 실제로 검색되었는지와 해당 파일 위치를 즉시 확인할 수 있어야 한다.
- 검증.
  - `python -m compileall backend/app/api/rag.py`
  - 결과는 통과였다.
  - `rag-assistant.html` inline script를 추출해 `node --check`를 시도했지만, 파일 내 기존 깨진 문자열 토큰 때문에 실패했다.
- 남은 리스크.
  - 프런트 파일의 기존 인코딩/문자열 손상 구간을 정리하지 않으면 전체 script 문법 검증 자동화가 계속 불안정하다.
  - LLM 프롬프트 자체에 “근거 파일명과 위치를 답변문에 명시” 규칙을 강제하는 작업은 아직 하지 않았다.
