# rag-assistant.html Graph Edge Label / 결과 패널 텍스트 조정 로그 (2026-05-30)

- 요청: 1) 오른쪽 패널 제목 "결과 패널" 삭제 또는 숨김 2) 그래프 엣지 표시 텍스트의 화살표/텍스트 가독성 개선
- 수행자: Codex
- 일시: 2026-05-30

## 변경 내용

- `frontend/rag-assistant.html`
  - 오른쪽 패널 헤더 제목(`div.card-title[data-i18n="result_panel"]`)을 `hidden` 처리하여 "결과 패널" 텍스트 비노출.
  - 그래프 엣지 라벨 포맷팅 유틸 추가:
    - `resolveGraphRelationLabel`
    - `formatGraphArrowLabel`
    - `normalizeGraphEdgeElement`
  - `loadKnowledgeGraph`, `loadGraphFromQuery`의 엣지 데이터 주입 시 `normalizeGraphEdgeElement` 적용.
  - 그래프 근거 문구 출력 로직(`formatGraphRelations`, `renderAnswerPanel`)에서 엣지 표기 형식을
    `──────── 관계명 ───────>` 형태로 변경하여 화살표-텍스트 가독성 개선.

## 검증

- 로컬 해시: `7802960550ca6f19669ab510ad5936752a4eca816889aa78e1c22bb79cffe34b`
- 서버 해시: `sha256sum /data/weeslee/weeslee-rag/frontend/rag-assistant.html` 동일 확인
- 서비스 상태: `systemctl is-active weeslee-rag-api.service` => `active`
- Playwright(원격 URL) 확인:
  - `.card-title[data-i18n="result_panel"] .hidden` => `true`
  - `window.formatGraphArrowLabel('REFERENCED_BY', '참조됨')` => `──────── 참조됨 ───────>`
  - `window.formatGraphArrowLabel('RELATED_TO')` => `──────── 관련됨 ───────>`
