# 2026-05-28 Codex Figma 와이어프레임 구현 매핑

## 1. 확인 범위

- Figma 공유 주소는 접근 시 CloudFront 403으로 직접 조회되지 않았다.
- 로컬 기준 이미지는 `docs/figma_dashboard_wireframe.png`, `docs/figma_step1_wireframe.png`이다.
- 현재 구현 기준 파일은 `frontend/admin.html`, `frontend/assets/js/admin/admin-docs-layout.js`, `frontend/assets/css/admin-docs-layout.css`이다.

## 2. 현재 구현 구조

현재 `admin.html`은 두 계층이 공존한다.

| 구분 | 위치 | 역할 |
|---|---|---|
| Docs 스타일 신규 화면 | `#wrAdminDocsApp` | 상단 바, 좌측 메뉴, Overview, Source Documents, RAG Build Wizard, FAISS, Graph, Wiki, Jobs, Logs, Search Quality, Settings |
| Legacy Console | `tab-*` 패널 | 실제 Dataset Builder 상세 실행, FAISS, Graph View, LLM Wiki, 문서 관리 기능 보존 |
| 브리지 함수 | 하단 inline script | `openBuildWizard`, `wrWizardRunStep`, `openGraphRagBuildWizard` 등으로 신규 화면에서 Legacy 실행 함수를 호출 |

## 3. Figma 대 현재 구현 매핑

| Figma 영역 | 현재 구현 상태 | 판단 |
|---|---|---|
| 상단 브랜드 바 | 있음. `wr-docs-header` | 검색창, 상태 버튼, Theme, RAG Assistant, Legacy Console 버튼이 포함되어 Figma보다 개발자 도구 성격이 강하다. |
| 좌측 사이드바 | 있음. `wr-sidebar` | Figma의 운영 메뉴 구조와 다르다. 현재는 Docs/Legacy 메뉴가 섞여 있다. |
| Dashboard Alert | 부분 구현. `wrOverviewNextText` | Figma처럼 신규 문서, 수정 문서, 처리 대기, 실패 작업 수를 한 줄 Alert로 보여주지는 않는다. |
| Dashboard 상태 카드 | 부분 구현. `wr-summary-grid` | 문서소스, 스캔 파일, Metadata, FAISS, Graph/Wiki, 검색 테스트 상태는 있다. Figma의 카운트 중심 카드와 일부 다르다. |
| Dashboard 설정 패널 | 없음 | Figma의 자동 새로고침, 표시 항목 체크박스, 설정 저장 기능이 현재 Overview에는 없다. |
| 시스템 현황 패널 | 부분 구현 | 현재는 순차 작업 가이드가 중심이고, Figma의 총 질문, 성공률, 평균 응답, 참조 문서, 최근 질문 TOP 5 패널은 없다. |
| Dataset Builder 사이드바 10단계 | 부분 구현 | 현재 10단계는 있지만 Figma의 Step 1 OCR/파싱부터 Step 10 관리자 검수 순서와 다르다. |
| Step 1 OCR/파싱 상세 화면 | Legacy Wizard에는 유사 기능이 있음 | 현재 Step 5가 OCR/청킹 역할을 하며, Figma의 Step 1 화면처럼 별도 설정 폼과 결과 패널로 분리되어 있지 않다. |
| Step 실행 결과 패널 | 부분 구현 | Legacy Wizard 로그와 요약은 있으나 Figma처럼 처리 문서, 추출 성공, OCR 사용, 실패 문서 테이블을 고정 패널로 보여주지는 않는다. |

## 4. 구현 차이 핵심

현재 코드는 실제 백엔드 연결과 기존 운영 기능을 최대한 보존하는 구조다. Figma는 사용자가 작업 흐름을 이해하기 쉬운 운영자용 화면으로 재정렬한 구조다.

따라서 전면 교체보다 다음 순서로 맞추는 것이 안전하다.

1. 신규 Docs 화면의 사이드바를 Figma 기준 운영 메뉴로 재정렬한다.
2. Overview를 Figma의 Dataset Alert, 상태 카드, 설정 패널, 시스템 현황 패널 구조로 맞춘다.
3. Dataset Builder의 단계명을 Figma 기준 10단계로 맞추되, 기존 실행 API와 단계 매핑은 유지한다.
4. Step 1 화면은 바로 API를 바꾸지 말고, 기존 Step 5 OCR/청킹 실행을 호출하는 화면으로 먼저 구성한다.
5. Legacy Console은 삭제하지 않고 보조 상세 로그 화면으로 남긴다.

## 5. 다음 구현 우선순위

| 우선순위 | 작업 | 완료 기준 |
|---|---|---|
| P0 | 사이드바 메뉴를 Figma 운영 메뉴 기준으로 정리 | Dashboard, Alerts, RAG Source, Dataset Builder Step 1-10, FAISS Index, Analytics가 보인다. |
| P1 | Overview를 Figma Dashboard 구조로 개편 | Dataset Alert, 6개 상태 카드, Dashboard 설정, 시스템 현황 패널이 보인다. |
| P2 | Dataset Builder 단계명과 설명을 Figma 기준으로 정렬 | Step 1 OCR/파싱부터 Step 10 관리자 검수까지 표시된다. |
| P3 | Step 1 OCR/파싱 설정과 결과 패널 추가 | OCR 설정, 파일 제한, 대상 선택, 출력 형식, 결과 카드, 실패 문서 테이블이 보인다. |
| P4 | 기존 Legacy 실행 함수와 신규 Step UI 연결 검증 | Step 실행 버튼이 기존 API 호출 흐름을 깨지 않는다. |

## 6. 리스크

- Figma 원본 노드 구조를 직접 읽지 못했으므로 로컬 PNG 기준의 시각 매핑이다.
- 현재 `admin.html`은 단일 파일에 신규 화면과 Legacy 기능이 함께 있어, 대규모 재배치 시 회귀 위험이 크다.
- Step 번호를 Figma 기준으로 바꾸면 기존 `wizardRun(step)` 번호와 의미가 어긋날 수 있다. 표시 단계와 실행 단계의 매핑 테이블이 먼저 필요하다.
