답변 프롬프트 근거 파일 강제 작업 기록.

- 대상 파일.
  - `backend/scripts/assemble_rag_response.py`
- 변경 내용.
  - `build_prompt()`를 후반부에 다시 정의해서, 답변문에 실제 근거 파일명과 파일 위치 경로를 반드시 포함하라는 규칙을 추가했다.
  - 출력 형식도 `요약 답변 -> 근거 파일 목록 -> 각 파일의 위치 경로 -> 추천 이유` 순서로 유도했다.
  - 검색 결과 컨텍스트에 `file_name`, `collection`, `relative_path`, `file_path`를 포함시켜 모델이 실제 경로를 보고 답변하도록 했다.
- 구현 의도.
  - 사용자가 최종적으로 확인해야 하는 것은 “LLM이 무엇을 말했는가”보다 “어떤 파일을 찾았고 그 파일이 어디에 있는가”이다.
  - UI에서 파일을 보여주는 것과 별개로, 답변문 자체에도 같은 근거가 나타나야 한다.
- 검증.
  - `python -m compileall backend/scripts/assemble_rag_response.py backend/app/services/rag_runtime.py backend/app/api/rag.py`
  - 결과는 통과였다.
- 남은 리스크.
  - 기존 원본 `build_prompt()`는 파일 내부에 그대로 남아 있고, 뒤에서 재정의한 새 함수가 실제로 override 하는 구조다.
  - 파일 인코딩/깨진 문자열 정리를 별도 단계로 하지 않으면 장기적으로 유지보수가 불편하다.
