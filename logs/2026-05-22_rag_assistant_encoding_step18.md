# 2026-05-22 `rag-assistant.html` 인코딩 복구 Step18

## 완료 내용
- `frontend/rag-assistant.html`의 `I18N` 한국어 연결을 `I18N_KO_SAFE`로 전환했다.
- 리뷰 히스토리 별점 렌더링 문자열을 `\u2605`, `\u2606` 이스케이프 기반으로 교체했다.
- Graph 결과 패널의 카테고리 라벨을 `cat_*` 번역 키 기준으로 바꾸고, 구분자 `→`, 아이콘 `🔗` 표시를 정리했다.

## 검증
- inline script 추출 후 `new Function(src)` 파싱 통과.
- `Select-String`으로 `ko: I18N_KO_SAFE`, 별점 문자열, Graph 패널 문자열 반영 확인.

## 후속 메모
- `node --check frontend/__rag_assistant_inline_check.js`는 같은 위치를 계속 오진했다. 브라우저 실행 기준 파싱은 통과했으므로 이번 단계에서는 `new Function(...)` 검증을 채택했다.
- `2026-05-22_leedh_질문답변.txt` 확인 결과, 다음 백엔드 정리는 folder-based collection이 아니라 `weeslee_rag_main` 단일 collection + metadata filter 기준으로 다시 맞춰야 한다.
