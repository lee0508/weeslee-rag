## 2026-05-26 Overview 빠른 이동 버튼 점검

- `frontend/admin.html`의 Overview 빠른 이동 버튼은 `openSourceManagement()`, `openBuildWizard()`, `openSearchQuality()` inline 함수를 호출한다.
- 현재 세 함수는 각각 Legacy 탭인 `docsource`, `wizard`, `benchmark`로 이동한다.
- 새 관리자 화면의 사이드바와 본문은 `frontend/assets/js/admin/admin-docs-layout.js`의 `setActivePage()`가 제어한다.
- 빠른 이동 버튼 문구는 Overview의 Docs 스타일 섹션에서 쓰이고 있으므로, 기본 동작은 Docs 페이지인 `source-documents`, `rag-build-wizard`, `search-quality`로 이동하는 것이 자연스럽다.
- `admin-docs-layout.js`에 `window.openWrDocsPage(pageName)`를 노출하고, 기존 inline 함수는 이 함수를 우선 호출한다.
- Docs 레이아웃 스크립트가 로드되지 않는 경우를 대비해 기존 Legacy 탭 이동 fallback은 유지한다.
- 배포본도 확인했으며, 2026-05-26 13:36 KST 기준 `openWrDocsPage`가 없고 빠른 이동 함수가 Legacy 탭으로 직접 이동하는 상태다.
- `openBuildWizard()`의 fallback은 존재하지 않는 `syncWizardStepStatuses` 대신 실제 정의된 `window.syncWizardStepperState`를 호출하도록 정리했다.

## 2026-05-26 Source Document 새 파일 감지 점검

- `backend/app/api/document_sources.py`의 `/admin/document-sources/{source_id}/scan`은 현재 파일 수와 `last_scanned_at`만 저장한다.
- 기존 API는 이전 스캔과 현재 스캔을 비교하지 않으므로 새 파일, 변경 파일, 삭제 파일을 관리자에게 알려줄 수 없다.
- `frontend/assets/js/admin/admin-docs-layout.js`의 Source Documents 화면은 등록된 source와 mount 상태만 표시하며, 새 파일 감지 결과와 다음 작업 메시지는 표시하지 않는다.
- 새 파일 감지는 Document Source 레지스트리의 상태 필드와 별도 인벤토리 파일을 함께 사용한다.
- 첫 스캔은 기준점을 만드는 작업으로 보고 모든 파일을 새 파일로 경고하지 않는다.
- 두 번째 스캔부터 새 파일, 변경 파일, 삭제 파일 수를 계산하고 `needs_rag_build`와 `next_action`으로 관리자에게 RAG 작업 진행 필요성을 안내한다.
- 화면 진입 시 자동 확인은 과도한 NAS 탐색을 피하기 위해 source별 최소 간격을 둔다.
- 기본 `python3` 환경에는 `fastapi`가 없어 API 모듈 import 기반 동작 테스트는 실행하지 못했다.
- 대신 `compileall`, 프론트 스크립트 `node --check`, `admin.html` inline script VM 파싱, UTF-8 파일 인코딩 확인, `git diff --check`로 정적 검증했다.

## 2026-05-26 관리자 5단계 OCR/청킹 파이프라인 점검

- 5단계 `OCR 작업 + 청킹 시작`은 프론트에서 `/api/admin/faiss/jobs`를 호출한다.
- 백엔드 job runner는 manifest 확인 또는 생성 후 `extract_manifest_batch.py`, `build_chunk_batch.py`, `build_faiss_index.py`, `build_category_indexes.py` 순서로 실행한다.
- `rag_source_pipeline.py`의 manifest 후보 확장자는 `.doc`, `.ppt`, `.xls`, `.txt`까지 포함하고 있었다.
- `extract_manifest_batch.py`는 실제 추출 지원 목록을 `.pdf`, `.pptx`, `.docx`, `.xlsx`, `.hwpx`, `.hwp`로 두고 `.doc`, `.ppt`, `.xls`는 스킵했다.
- `.txt`는 manifest 후보에는 들어가지만 추출 지원 목록에는 없어 `skipped_unknown`이 된다.
- `PptxExtractor`와 `XlsxExtractor`가 각각 `.ppt`, `.xls`를 지원한다고 노출하지만 내부 라이브러리는 OOXML 계열 처리라 구형 바이너리 형식 지원으로 보기 어렵다.
- 5단계 정상 운영 기준은 PDF/HWP/HWPX/DOCX/PPTX/XLSX로 통일하고, 구형 DOC/PPT/XLS와 TXT는 5단계 대상처럼 표시하지 않는 것이 안전하다.
- 확장자 상수 import 기반 검증은 기본 Python 환경에 `pdfplumber`가 없어 실행하지 못했다.
- `compileall`, `admin.html` inline script VM 파싱, UTF-8 인코딩 확인, `git diff --check`는 통과했다.

## 2026-05-26 관리자 페이지 1차 UI 개선

- 앞선 분석 문서의 1차 개선 순서는 대시보드 상태 요약, RAG Source Manager, 작업 마법사, Collection 자동 생성, Metadata 버튼 분리, API 경로 접이식 표시다.
- 사용자가 새 요구사항을 주었지만, 그 전에 앞선 UI 개선 분석 내용을 먼저 구현하는 것이 맞다고 정정했다.
- 방금 시작했던 운영 대시보드형 Overview 변경은 커밋 전 원복했다.
- 이번 1차 구현은 `Overview` 상단을 상태판과 다음 작업 안내 중심으로 바꾸는 데 한정한다.
- 기존 Legacy Dashboard와 `loadDashboard()`가 이미 상태 카드와 다음 작업 판단을 제공하므로, 새 Docs-style Overview에서도 같은 판단 흐름을 보여주도록 연결한다.
- Source/Dataset 세부 관리, GraphRAG 관계 편집, LLM Wiki 미리보기는 후속 단계로 남긴다.

## 2026-05-26 관리자 오른쪽 Source 운영 패널

- 전체 Dataset은 `weeslee_rag_main`으로 유지하되 단계별 생성과 재개는 `Document Source ID` 기준으로 보는 것이 맞다.
- 오른쪽 패널은 기존 `On This Page`, `Current Job`, `API Status`보다 Source 운영 상태를 먼저 보여줘야 한다.
- 제안 구조는 Project Dataset, Current Source, Next Source Action, Recent Jobs, API Status 순서다.
- Source 선택은 `/admin/document-sources` 응답의 `source_id`를 select에 표시하고 선택값을 `localStorage`에 저장한다.
- Source별 변경 감지 값은 `new_file_count`, `changed_file_count`, `removed_file_count`, `needs_rag_build`, `next_action` 필드를 사용한다.
- 최근 작업은 `/admin/faiss/jobs`에서 선택 Source ID 또는 snapshot 문자열에 source ID가 포함된 job을 우선 표시한다.
- 오른쪽 패널은 `Project Dataset`, `Current Source`, `Next Source Action`, `Recent Source Jobs`, `On This Page`, `API Status` 순서로 구성했다.
- 상태 새로고침 버튼은 Source 스캔을 강제로 다시 실행하고, Overview 진입 시에는 10분 throttling 규칙을 유지한다.
