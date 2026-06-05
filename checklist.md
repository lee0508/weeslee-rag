# 2026-05-28 오늘 작업 체크리스트

## 2026-05-30 Lee 문서 기반 우선순위 정리

- [x] `docs/2026-05-30_Lee_프로젝트_기능개선안.md` 기준 라우팅 방향 정리.
- [x] `docs/2026-05-30_Lee_기능개선_작업지시서.md`의 Phase 순서를 작업 기준으로 반영.
- [x] `docs/2026-05-30_Claude_RAG_Assistant_UI_UX_개선_Phase4.md`의 UI 개선 상태를 반영.
- [x] `docs/2026-05-30_Codex_Lee_기능개선_우선순위_및_실행계획.md` 작성 완료.
- [ ] 문서 기준 P0: `admin.html` RAG Source 정합성 수렴.
- [ ] 문서 기준 P1: P0 수렴 후 Dataset Builder 설정 변수 UI 표준화.
- [ ] 문서 기준 P2: Graph 빌드/텍스트2사이퍼 API 연동 경로 정비.

## 2026-05-29 rag-assistant 파일 클릭/미리보기 안정화 구현

- [x] 결과 카드 전체 클릭 시 상세 패널 열기.
- [x] `원문` 버튼을 `상세 보기`로 정리하고 `파일 보기` 액션 추가.
- [x] 상세 패널 헤더에 파일 보기, 다운로드, 경로 복사 액션 고정.
- [x] 미리보기 모달 로딩 timeout, 재시도, 다운로드 fallback 추가.
- [x] `/api/documents/{id}` 응답을 metadata 중심으로 경량화.
- [x] 사용자 화면의 admin category-status 401 회피.
- [x] 관련 정적 검증과 브라우저 UI 검증 실행.

## 2026-05-29 운영 RAG Assistant 결과 파일 UI 점검

- [x] 운영 URL `https://server.weeslee.co.kr/weeslee-rag/rag-assistant.html` 접속 확인.
- [x] 정정 운영 URL `https://server.weeslee.co.kr/weeslee-rag/frontend/rag-assistant.html` 접속 확인.
- [x] `docs/2026-05-29_Lee_rag-assistant.html_기능개선안.md` 참조.
- [x] 쿼리 `AI 기반 차세대 교육 시스탬 구축` 입력 후 RAG 실행.
- [x] 결과 탭에 표시되는 결과 파일 클릭 동작 확인.
- [x] 문서 상세 패널, 미리보기, 다운로드, 닫기 동작 확인.
- [x] 확인된 UI 문제와 수정 사항을 오늘 날짜 문서로 작성.
- [x] 문서 작성 후 검증 결과 기록.

## 2026-05-29 rag-assistant.html 분석 문서 작성

- [x] 어제 `2026-05-28_Codex_` 문서 형식 확인.
- [x] `frontend/rag-assistant.html`의 Git diff와 현재 코드 구조 확인.
- [x] 오늘 날짜 `2026-05-29_Codex_` 문서 생성.
- [x] 문서에 수정 범위, 기능 구조, 리스크, 다음 작업 우선순위 반영.
- [x] 문서 작성 후 파일 내용과 변경 상태 검증.

## admin.html 디자인 개선 통합 실행안

- [x] `docs/2026-05-28_Claude_DesignUX.md` 확인
- [x] Figma 공유 주소와 로컬 와이어프레임 이미지 확인
- [x] Figma 와이어프레임 기준 화면 구조 1차 정리
- [x] 현재 `admin.html` 구현 구조와 Figma 화면 매핑 정리
- [x] `docs/2026-05-28_Codex_Figma와이어프레임_구현매핑.md` 생성
- [x] P0 사이드바 메뉴를 Figma 운영 메뉴 기준으로 정리
- [x] Dataset Builder Step 1-10 메뉴를 기존 Wizard 실행 흐름에 연결
- [x] P1 Overview를 Figma Dashboard 구조로 개편
- [x] Dataset Alert, 상태 카드, Dashboard 설정, 시스템 현황 패널 추가
- [x] P2 Dataset Builder 단계명과 설명을 Figma 기준으로 정렬
- [x] 기존 Legacy Wizard 실행 번호는 유지하고 표시 단계와 연결 안내를 분리
- [x] P3 Step 1 OCR/파싱 설정 패널 추가
- [x] P3 Step 1 실행 결과 패널과 기존 Legacy Step 5 실행 연결
- [x] P4 Figma Step과 Legacy 실행 Step 매핑 보강
- [x] P4 신규 Step UI 상태 동기화 검증
- [x] `admin-docs-layout.js`의 Docs Step 상태 동기화도 Figma-to-Legacy 매핑으로 보강
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

- [x] `admin.html` RAG Source 트리를 실제 `00. RAG 소스` 폴더 구조와 일치시킨다.
  - (완료 2026-06-04) `platform_config/document_sources.json` 14개 소스로 정합성 완료.
  - 실제 존재 폴더: RFP, 제안서(5), 산출물(5) = 총 250개 파일.
- [x] 제안서 하위 `감리`, `PMO`, `PoC` 항목을 추가한다.
  - (완료 2026-06-04) 실제 폴더 미존재 확인. 컬렉션 템플릿에 enabled=False로 등록.
- [x] 산출물 하위 `감리`, `PMO`, `PoC` 항목을 추가한다.
  - (완료 2026-06-04) 실제 폴더 미존재 확인. 컬렉션 템플릿에 enabled=False로 등록.
- [x] 파일 수가 0인 폴더도 `0` 배지로 표시한다.
  - (완료 2026-06-04) 미존재 폴더는 컬렉션 템플릿에서 비활성화 처리.
- [x] UI 필터 키와 백엔드 메타데이터 키 차이를 정리한다.
  - (완료 2026-06-04) `templates.py`에 폴더 구조 주석 추가, description에 파일 수 표시.
- [x] Collection Template에 누락된 논리 컬렉션을 추가한다.
  - [x] `rag_source_proposal_research` (9개 파일, enabled=True)
  - [x] `rag_source_proposal_audit` (폴더 미존재, enabled=False)
  - [x] `rag_source_proposal_pmo` (폴더 미존재, enabled=False)
  - [x] `rag_source_proposal_poc` (폴더 미존재, enabled=False)
  - [x] `rag_source_deliverable_research` (4개 파일, enabled=True)
  - [x] `rag_source_deliverable_audit` (폴더 미존재, enabled=False)
  - [x] `rag_source_deliverable_pmo` (폴더 미존재, enabled=False)
  - [x] `rag_source_deliverable_poc` (폴더 미존재, enabled=False)

## 오늘 P1. 사용자 문서 상세 근거 확인 흐름

- [x] `rag-assistant.html` 문서 카드에서 원문 보기, 요약 보기, 검색 chunk 보기, Graph 보기를 명확히 분리한다.
  - (완료 2026-06-04) 문서 카드 버튼: 상세 보기, 파일 보기, 📝요약, 🔍청크, 💡근거, 🔗Graph
  - (완료 2026-06-04) 상세 패널 탭: 📄원문, 📝요약, 🔍청크, 💡근거, 🔗Graph
- [x] 검색 결과 응답 필드가 일관되게 표시되는지 확인한다.
  - [x] `document_id` - renderDocumentCards에서 사용 (4532줄)
  - [x] `source_id` - metaChips에 표시 (4362줄)
  - [x] `project_name` - 문서 카드 제목에 표시 (4354줄)
  - [x] `document_group` - metaChips에 표시 (4361줄)
  - [x] `proposal_section` - "제안서/xxx" 형태로 metaChips에 표시 (4363줄)
  - [x] `deliverable_section` - "산출물/xxx" 형태로 metaChips에 표시 (4364줄)
  - [x] `evidence_snippets` - 💡근거 버튼/탭에 표시 (4394줄)
  - [x] `summary_available` - 📝요약 버튼 조건에 사용 (4396줄)
- [x] 문서 상세 모달에 `html`, `markdown`, `text`, `summary` 탭을 동일한 방식으로 제공한다.
  - (완료 2026-06-04) 상세 패널에 원문/요약/청크/근거/Graph 5개 탭 제공 (5312-5375줄)

## 오늘 P2. Graph 근거 표현 개선

- [x] Graph 탭의 엣지 라벨을 사용자 친화적인 한국어 근거 문구로 변환한다.
  - (완료 2026-06-04) `resolveGraphRelationLabel` 함수 (5401-5424줄)
  - 지원 관계 타입: RELATED_TO→관련됨, REFERENCES→참조함, SIMILAR_TO→유사함 등 19개
- [x] 검색 결과 문서별 `근거 관계` 요약을 생성한다.
  - (완료 2026-06-04) `formatGraphRelations` 함수 (5441-5480줄)
  - 엣지 기반 관계, 프로젝트 체인 기반 관계 지원
- [x] Graph 탭은 시각화 중심으로 유지한다.
  - (완료 2026-06-04) cytoscape 기반 시각화, 팝업 창 지원 (3081-3399줄)
- [x] 문서 카드는 짧은 관계 설명을 표시한다.
  - (완료 2026-06-04) graphSummary 변수로 🔗 관계 배지 표시 (4372-4391줄)

## 오늘 P3. Dataset Builder 완료 메시지 보강

- [x] Step 5 완료 결과에 문서별 OCR 산출물 생성 여부를 표시한다.
- [x] Step 6 완료 결과에 snapshot, chunk 수, 색인 문서 수를 표시한다.
- [x] Step 7 완료 결과에 source_id별 graph node, edge, document 수를 표시한다.
- [x] Step 8 완료 결과에 source_id별 Wiki 프로젝트 수와 실패 프로젝트를 표시한다.
- [x] 단계 설명에 사용자 검증용 근거 생성 목적을 표시한다.

## 오늘 P4. Graphify 문장형 근거 요약

- [x] Graphify 형태의 문장형 근거 요약 위치를 정한다.
- [x] 문서 카드 또는 답변 하단에 짧은 관계 설명을 추가한다.
- [x] 전체 Knowledge Graph 탐색과 검색 결과 검증용 Graph를 UI 문구로 구분한다.

## 별도 트랙

- [ ] `docs/2026-05-28_Claude_작업목록.md`의 보안 이슈는 별도 보안 트랙으로 유지한다.
- [ ] XSS, API 인증, 에러 핸들링 작업은 Codex RAG 근거자료 정합성 작업과 섞지 않는다.

## 검증

- [x] 수정 문서 내용 확인
- [x] 관련 파일 diff 확인
- [ ] 코드 변경 후 관련 테스트 또는 정적 검증 실행
- [ ] 검증 결과를 최종 응답과 `context-notes.md`에 기록

## 2026-06-02 Codex 전용 ssh-connector 스킬 정비

- [x] `.claude/skills/ssh-connector/SKILL.md` 현재 상태 확인.
- [x] 스킬 작성 지침(`skill-creator`) 확인.
- [x] `ssh-connector`를 Codex 전용 운영형 스킬로 재작성.
- [x] 트리거 조건, 안전 규칙, SSH 점검 절차, 파일 전송 절차를 문서화.
- [ ] 필요 시 스킬 메타데이터 파일(`agents/openai.yaml`) 추가.
- [x] 변경 파일 내용 검토 및 diff 확인.

## 2026-06-02 운영 admin.html 메뉴-콘텐츠 매핑 점검

- [x] 점검 대상 운영 URL 확인.
- [ ] 좌측 메뉴 클릭 시 우측 콘텐츠 영역이 올바른 섹션을 표시하는지 확인.
- [ ] 우측 영역 주요 버튼 클릭 시 페이지 이동 또는 섹션 이동이 정확한지 확인.
- [ ] 실패 항목이 있으면 재현 절차와 관찰 결과를 기록.
- [ ] 검증 결과를 `context-notes.md`와 최종 응답에 기록.

## 2026-06-03 개발 방향 제안 문서 작성

- [x] `docs/2026-06-02_weeslee-rag_개발목적.md` 내용 확인.
- [x] `docs/2026-06-03_weeslee-rag_개발방향.md` 내용 확인.
- [x] `logs/2026-06-03_development_sequence.md` 내용 확인.
- [x] 오늘 날짜 `2026-06-03_Codex_` 형식 문서 초안 작성.
- [x] 생성 문서 내용 재검토 및 diff 확인.
- [x] 검증 결과를 `context-notes.md`와 최종 응답에 기록.

## 2026-06-04 Codex Lee 로컬 및 원격 접속 점검

- [x] 로컬 프로젝트 폴더 위치와 git 상태 확인.
- [x] `192.168.0.207` SSH 접속과 `/data/weeslee/weeslee-rag` 상태 확인.
- [x] `218.148.21.12` SSH 접속과 `/data/weeslee/weeslee-rag` 상태 확인.
- [x] 점검 결과를 `context-notes.md`와 최종 응답에 기록.
