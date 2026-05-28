# 2026-05-28 오늘 작업 체크리스트

## admin.html 디자인 개선 통합 실행안

- [x] `docs/2026-05-28_Claude_DesignUX.md` 확인
- [x] Figma 공유 주소와 로컬 와이어프레임 이미지 확인
- [x] Figma 와이어프레임 기준 화면 구조 1차 정리
- [x] 현재 `admin.html` 구현 구조와 Figma 화면 매핑 정리
- [x] `docs/2026-05-28_Codex_Figma와이어프레임_구현매핑.md` 생성
- [x] 기존 관리자 디자인 개선 문서 확인
- [x] 현재 `frontend/admin.html` Docs 화면 구조 확인
- [x] live admin.html URL HTTP 200 확인
- [x] 이전 문서 내용을 통합한 실행 순서 문서 작성
- [x] `docs/2026-05-28_admin_html_디자인개선_통합실행순서.md` 생성
- [x] 메뉴별 필수 설정 입력폼과 실행 후 확인 섹션 원칙 반영
- [x] 온프라미스 구성값 기준 반영
- [x] `2026-05-28_Codex_` 시작 문서로 LLM/RAG/온톨로지 적용 제안 저장
- [x] LLM/RAG/온톨로지 실행 순서를 P0부터 P9까지 문서화

## 기준 문서 확인

- [x] 어제 Codex 문서 확인
  - [x] `docs/2026-05-27_Codex_RAG근거자료_수정권고.md`
- [x] 오늘 작업 기준을 Codex 권고 실행 순서로 재정리
- [x] 기존 Claude 작업목록의 RAG 근거자료 항목과 비교
- [x] 표시 기준을 `context-notes.md`에 기록

## 오늘 P0. RAG Source와 Collection Template 정합성

- [ ] `admin.html` RAG Source 트리를 실제 `00. RAG 소스` 폴더 구조와 일치시킨다.
- [ ] 제안서 하위 `감리`, `PMO`, `PoC` 항목을 추가한다.
- [ ] 산출물 하위 `감리`, `PMO`, `PoC` 항목을 추가한다.
- [ ] 파일 수가 0인 폴더도 `0` 배지로 표시한다.
- [ ] UI 필터 키와 백엔드 메타데이터 키 차이를 정리한다.
- [ ] Collection Template에 누락된 논리 컬렉션을 추가한다.
  - [ ] `rag_source_proposal_research`
  - [ ] `rag_source_proposal_audit`
  - [ ] `rag_source_proposal_pmo`
  - [ ] `rag_source_proposal_poc`
  - [ ] `rag_source_deliverable_research`
  - [ ] `rag_source_deliverable_audit`
  - [ ] `rag_source_deliverable_pmo`
  - [ ] `rag_source_deliverable_poc`

## 오늘 P1. 사용자 문서 상세 근거 확인 흐름

- [ ] `rag-assistant.html` 문서 카드에서 원문 보기, 요약 보기, 검색 chunk 보기, Graph 보기를 명확히 분리한다.
- [ ] 검색 결과 응답 필드가 일관되게 표시되는지 확인한다.
  - [ ] `document_id`
  - [ ] `source_id`
  - [ ] `project_name`
  - [ ] `document_group`
  - [ ] `proposal_section`
  - [ ] `deliverable_section`
  - [ ] `evidence_snippets`
  - [ ] `summary_available`
- [ ] 문서 상세 모달에 `html`, `markdown`, `text`, `summary` 탭을 동일한 방식으로 제공한다.

## 오늘 P2. Graph 근거 표현 개선

- [ ] Graph 탭의 엣지 라벨을 사용자 친화적인 한국어 근거 문구로 변환한다.
- [ ] 검색 결과 문서별 `근거 관계` 요약을 생성한다.
- [ ] Graph 탭은 시각화 중심으로 유지한다.
- [ ] 문서 카드는 짧은 관계 설명을 표시한다.

## 오늘 P3. Dataset Builder 완료 메시지 보강

- [ ] Step 5 완료 결과에 문서별 OCR 산출물 생성 여부를 표시한다.
- [ ] Step 6 완료 결과에 snapshot, chunk 수, 색인 문서 수를 표시한다.
- [ ] Step 7 완료 결과에 source_id별 graph node, edge, document 수를 표시한다.
- [ ] Step 8 완료 결과에 source_id별 Wiki 프로젝트 수와 실패 프로젝트를 표시한다.
- [ ] 단계 설명에 사용자 검증용 근거 생성 목적을 표시한다.

## 오늘 P4. Graphify 문장형 근거 요약

- [ ] Graphify 형태의 문장형 근거 요약 위치를 정한다.
- [ ] 문서 카드 또는 답변 하단에 짧은 관계 설명을 추가한다.
- [ ] 전체 Knowledge Graph 탐색과 검색 결과 검증용 Graph를 UI 문구로 구분한다.

## 별도 트랙

- [ ] `docs/2026-05-28_Claude_작업목록.md`의 보안 이슈는 별도 보안 트랙으로 유지한다.
- [ ] XSS, API 인증, 에러 핸들링 작업은 Codex RAG 근거자료 정합성 작업과 섞지 않는다.

## 검증

- [x] 수정 문서 내용 확인
- [x] 관련 파일 diff 확인
- [ ] 코드 변경 후 관련 테스트 또는 정적 검증 실행
- [ ] 검증 결과를 최종 응답과 `context-notes.md`에 기록
