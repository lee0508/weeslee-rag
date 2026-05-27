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

## 2026-05-27 Dataset Builder 5/6단계 분리

- Step 5 `OCR 작업 + 청킹 시작`은 사용자 관점에서 텍스트 추출과 청킹까지만 수행해야 한다.
- 기존 `faiss_start` job은 manifest, OCR/텍스트 추출, 청킹, FAISS, 카테고리 인덱스, 그래프까지 한 번에 실행해 Step 6과 역할이 겹쳤다.
- Step 6 `임베딩 + Vector + FAISS 진행`은 청크 결과를 입력으로 FAISS 인덱스와 카테고리 인덱스를 생성하는 별도 단계로 둔다.
- Job 실패 시 runner가 `{"done": true}`만 보내면 프론트가 성공으로 오판하므로 완료 이벤트에 실패 상태와 error를 포함해야 한다.
- `/api/admin/faiss/jobs` 요청에 `end_stage`를 추가해 Step 5는 1-3, Step 6은 4-5만 실행하도록 했다.
- 기존 FAISS 탭의 직접 job 실행은 `end_stage` 기본값 6을 유지하므로 기존 전체 파이프라인 동작은 유지된다.
- 검증은 `python3 -m compileall`, `admin.html` inline script 파싱, `git diff --check`로 수행했다.

## 2026-05-27 Document Source source_id 자동 생성

- Source 이름이나 폴더명이 한글일 수 있으므로 내부 작업 키인 `source_id`를 사용자 입력에서 slug로 만들지 않는다.
- 서버가 신규 Document Source 생성 시 `source_id`가 비어 있으면 `src_YYYYMMDD_HHMMSS_랜덤` 형식으로 생성하는 것이 Dataset Builder 단계에서 안정적이다.
- 기존 `rag_source`와 이미 저장된 source_id는 그대로 유지해 기존 데이터와 URL을 깨지 않도록 한다.
- Legacy Document Source 폼과 새 Source 등록 흐름 모두 신규 등록 시 source_id를 보내지 않고 서버 응답값을 사용한다.
- 기본 Python 환경에는 `fastapi`가 없어 API 모듈 직접 import 검증은 실행하지 못했고, compileall과 admin inline script 파싱으로 정적 검증했다.

## 2026-05-27 Document Source Dataset 생성 버튼

- Document Source 목록의 행별 `Dataset 생성` 버튼은 기존에 `switchTab('wizard')`만 호출해 선택 Source가 Dataset Builder에 반영되지 않았다.
- 버튼 클릭 시 해당 행의 `source_id`를 `ctxSource`에 설정하고 `onCtxChange()`를 호출한 뒤 wizard로 이동해야 한다.

## 2026-05-27 기존 Document Source ID 재생성

- 기존에 한글 또는 관리하기 어려운 `source_id`로 저장된 Document Source를 새 자동 source_id로 다시 등록할 수 있어야 한다.
- 기존 레코드를 바로 삭제하거나 primary key를 수정하면 참조가 깨질 수 있으므로, 목록에서 기존 값을 읽어 새 레코드로 복제 생성하는 방식을 사용한다.
- 복제 생성 시 `source_id`는 보내지 않고 서버 자동 생성값을 사용하며, `client_id`, `source_name`, `source_type`, `source_uri`, `mount_path`, `root_subpath`, `readonly`, `enabled`만 넘긴다.
- 버튼 동작은 기존 Source 수정이 아니라 복제 생성이므로 표시 문구는 `새 ID로 복제`가 더 정확하다.

## 2026-05-27 Manifest source_id/source_name 추가

- 기존 manifest row에는 `source_id`가 없어 OCR, 청킹, FAISS metadata에서 어떤 Document Source 기준 산출물인지 추적하기 어려웠다.
- manifest 생성 시 Document Source 레코드를 조회해 `source_id`와 `source_name`을 각 row에 포함한다.
- OCR 추출 metadata와 chunk metadata에도 같은 값을 전달해 GraphRAG, LLM Wiki, 증분 처리에서 Source 기준 필터를 사용할 수 있게 한다.

## 2026-05-27 Dataset Builder Step 2 source_id 필터링

- Step 2 `/api/admin/rag-source/metadata/build`는 요청 body에 `source_id`를 받지만 기존 코드는 `meta_status` 기준으로 전체 documents를 조회했다.
- `documents` 테이블에는 `source_id` 컬럼이 없으므로 현재 구조에서는 Document Source의 `mount_path` 또는 `source_uri`와 문서 `file_path` prefix를 비교해 대상 문서를 좁히는 방식이 맞다.
- Step 1 스캔도 같은 `source_id`의 mount path를 기준으로 파일을 documents에 저장하므로, Step 2 역시 같은 경로 기준을 사용해야 Source별 Dataset Builder 흐름이 맞는다.
- Step 5의 `openpyxl` 메시지 `Data Validation extension is not supported and will be removed`는 XLSX 데이터 유효성 확장을 보존하지 않는다는 경고이며 텍스트 추출 실패가 아니다.
- FAISS job runner는 subprocess stderr를 stdout과 합쳐 SSE 로그로 보내므로, 이 경고가 UI에서 오류처럼 보일 수 있다.
- XLSX 추출기에서 해당 `openpyxl.worksheet._reader` UserWarning만 억제하고, 실제 추출 예외는 기존처럼 `success=False`로 유지한다.

## 2026-05-27 Step 5 실패 상태 메시지

- Step 5 실행 중에는 상태가 `OCR/청킹 실행 중...`으로 표시되고, SSE 실패가 발생하면 `_wizardMarkError()`가 호출된다.
- 사용자가 보는 요약 영역이나 자동 실행 상태에 실행 중 메시지가 남으면 실패 원인을 놓치기 쉽다.
- Step 5와 Step 6 같은 FAISS job 단계는 실패 시 단계별 문맥을 붙여 `OCR/청킹 실패` 또는 `임베딩/FAISS 실패`로 명확히 표시해야 한다.

## 2026-05-27 사용자 문서 미리보기와 OCR 산출물

- `rag-assistant.html`의 문서 클릭은 `openDocDetail()`과 `openFilePreview()`로 이어지며, 미리보기는 `/api/documents/{document_id}` 상세 API를 먼저 조회한다.
- 백엔드 문서 상세 API는 Step 5 산출물인 `data/extracted_text/{document_id}/document.html`, `document.md`, `raw_text.txt`와 `data/staged/text/{document_id}.txt`를 이미 fallback으로 읽는다.
- 전체 본문 보기 연결은 되어 있으나 요약은 `available_formats.summary`가 있어도 미리보기 탭에 표시되지 않았다.

## 2026-05-27 Step 5 OCR/청킹 증분 처리

- Step 5 재실행 시간을 줄이려면 문서별 `data/staged/text/{document_id}.txt`와 `data/staged/metadata/{document_id}.json`을 재사용해야 한다.
- 기존 산출물이 원본 파일보다 최신이면 텍스트 추출/OCR은 건너뛰고 summary CSV에는 `skipped_existing`으로 남긴다.
- 청킹은 전체 snapshot chunks를 다시 만들 수 있어야 하므로 `success`뿐 아니라 `skipped_existing` row도 입력으로 처리해야 한다.

## 2026-05-27 Phase 9 체크리스트 현재화

- 기존 `docs/design/Phase9_Codex_구현_체크리스트.md`는 초기 설계 기준이라 현재 source_id 중심 Dataset Builder 구현과 맞지 않았다.
- 현재 구현은 Document Source, Dataset Builder Step 5/6 분리, 사용자 문서 미리보기, 문서 상세 API 중심으로 재정리해야 한다.
- `docs/2026-05-27_관리자시점_개발방향.md`는 관리자 관점 워크플로우를 문서 등록, 전처리, 구조 기반 청킹, FAISS/RAG, LLM Wiki, GraphRAG 순서로 제시한다.
- 특히 페이지별 OCR 결과 저장, 실패 로그, 재처리 버튼, 구조 기반 청킹, 관계 모델은 아직 남은 과제로 명시해야 한다.

## 2026-05-27 Step 5 manifest 대상 없음 장애

- 오류 메시지는 `manifest 대상 문서를 찾지 못했습니다. source_id=01_rfp, root=/mnt/w2_project/00. RAG 소스/01. RFP`이다.
- Step 5는 파일 시스템을 직접 순회하지 않고 `documents` 테이블의 `file_path`가 Document Source root prefix와 일치하는 문서만 manifest 대상으로 삼는다.
- 따라서 원인은 `01_rfp` 기준 Step 1 스캔 결과가 DB에 없거나, DB에는 있지만 경로 문자열이 Document Source root와 다르게 저장된 경우로 좁혀진다.
- 서버 확인 결과 `platform_config/document_sources.json`의 `01_rfp`는 `/mnt/w2_project/00. RAG 소스/01. RFP`를 가리키고, 실제 폴더에는 지원 확장자 파일 47개가 있다.
- `metadata.db` 전체 문서는 122,925건이고 `01_rfp` prefix와 맞는 문서는 47건 존재한다.
- Step 5의 `iter_source_documents()`가 `list_documents(limit=100000)`으로 최근 100,000건만 읽은 뒤 prefix 필터를 적용해, 오래된 47건이 후보에서 빠지는 것이 직접 원인이다.
- Step 5 manifest 조회는 SQLite에서 `source_root` prefix 조건을 먼저 적용하도록 변경해 전체 DB 크기와 무관하게 대상 Source 문서를 찾게 했다.
- Step 2 Metadata 생성도 `list_documents(limit=10000)` 후 필터링하던 구조라 같은 문제가 발생할 수 있어 Source prefix DB 조회로 맞췄다.
- 서버 배포 후 `PYTHONPATH=backend .venv/bin/python3`로 `iter_source_documents(resolve_source_path('01_rfp'))`를 실행해 47건 조회를 확인했다.
- `weeslee-rag-api.service`를 재시작했고 `/api/health/all`은 HTTP 200과 healthy 상태를 반환했다.

## 2026-05-27 Dataset Builder source_id 표시

- Dataset Builder 공통 컨텍스트 바의 `ctxSource`는 option value로 `source_id`를 가지고 있지만 표시 텍스트는 Source 이름만 보여줘 사용자가 `01. RFP`의 내부 ID가 `01_rfp`인지 확인하기 어려웠다.
- Source option 표시를 `Source 이름 (source_id)` 형식으로 바꾸고, 선택 박스 옆에 `source_id=...` 힌트를 별도로 표시한다.
- Step 5/6 job 요청은 원본 `source_id` 값을 그대로 보내고, 스냅샷명에만 안전한 문자열로 변환한 키를 사용해야 한다.
- 기존 스냅샷 선택 기능은 유지하되 Step 5/6 로그에 Document Source ID를 남겨, 어떤 Source 기준으로 기존 스냅샷을 재사용하거나 이어서 실행했는지 확인할 수 있게 한다.
- `59bf7f1`을 서버에 배포하고 `weeslee-rag-api.service` 재시작 후 `/api/health/all` HTTP 200을 확인했다.

## 2026-05-27 LLM Wiki 8단계 RAG timeout

- `/api/wiki/build`는 `build_project_wiki.py`를 subprocess로 실행한다.
- 스크립트의 `query_rag_for_project()`는 카테리별 RAG 근거 수집을 `/api/rag/query`로 호출하고, 기본 개별 timeout은 45초다.
- 사용자가 본 `[WARN] RAG query failed (rfp): timed out`은 RFP 카테고리 RAG 근거 수집이 45초를 넘긴 경고다.
- 해당 경고 자체는 빈 evidence로 계속 진행하도록 설계되어 있지만, 서버 로그상 12:26:36에 `/api/wiki/build` 500이 찍힌 직후 서비스 재시작이 발생해 진행 중 요청도 끊겼다.
- 현재 Dataset Builder Step 8은 선택 Source와 Step 6 스냅샷을 `/api/wiki/build`에 넘기지 않아 active snapshot 기준으로 Wiki를 만들 수 있다.
- 추가 검증 중 `/api/wiki/build`의 `async` 엔드포인트가 `subprocess.run()`으로 이벤트 루프를 blocking하고, 그 subprocess가 다시 같은 서버의 `/api/rag/query`를 호출해 내부 요청을 처리하지 못하는 구조를 확인했다.
- Wiki build subprocess 실행은 `asyncio.to_thread()`로 넘겨 API 서버가 내부 RAG 요청을 동시에 처리할 수 있게 해야 한다.
- `3d8d706` 배포 후 `source_id=01_rfp`, `snapshot=snapshot_20260527_01_rfp`, `max_projects=1`로 `/api/wiki/build`를 호출해 HTTP 200을 확인했다.
- 응답 stdout에서 지정 스냅샷을 사용했고 `data/wiki/01_rfp/projects/old.md` 1건이 생성됐다. 다만 source inventory의 첫 프로젝트가 `old`로 잡히는 것은 별도 데이터 품질 점검 대상이다.

## 2026-05-27 LLM Wiki source inventory 품질

- 서버의 `data/staged/01_rfp_inventory.json`은 9,052개 폴더를 포함해 `01_rfp` 전용 inventory가 아니라 전체 문서 기반 inventory처럼 보인다.
- `snapshot_20260527_01_rfp_chunks.jsonl` 샘플에는 `folder_name`과 `project_name`이 `축산유통 데이터랩 고도화`처럼 정상적으로 들어 있다.
- 현재 `/api/wiki/build?source_id=01_rfp&snapshot=...`는 snapshot을 Wiki build에는 넘기지만, 선행 inventory 생성은 `build_project_inventory.py --source-id 01_rfp`만 호출해 DB 기반 inventory를 만든다.
- snapshot이 지정된 Dataset Builder 흐름에서는 inventory도 같은 snapshot chunks에서 생성해야 Step 5/6 산출물과 Wiki 대상 프로젝트가 일치한다.
- `build_project_inventory.py --source-id 01_rfp --from-chunks --snapshot snapshot_20260527_01_rfp` 실행 결과 inventory가 45개 프로젝트, 45개 문서로 재생성됐다.
- `/api/wiki/build?source_id=01_rfp&snapshot=snapshot_20260527_01_rfp&max_projects=1`은 `축산유통-데이터랩-고도화.md`를 생성했다.
- 이전 검증 중 잘못 생성된 `data/wiki/01_rfp/projects/old.md`는 서버에서 삭제했다.

## 2026-05-27 FAISS Index 직접 파이프라인 버튼

- FAISS Index 탭의 `파이프라인 시작` 버튼은 초기 개발용 전체 파이프라인 실행 경로로 남아 있었다.
- 기존 `startJob()`은 `/api/admin/faiss/jobs`에 `{snapshot}`만 보내므로 백엔드 기본값인 `source_id=rag_source`, `start_from_stage=1`, `end_stage=6`으로 전체 파이프라인을 실행한다.
- 현재 운영 흐름은 Dataset Builder가 Source별 Step 5, Step 6, Step 7, Step 8을 관리하므로 FAISS Index 탭에서는 직접 실행 대신 Dataset Builder로 이동시키는 것이 안전하다.
- staged 준비 현황의 스냅샷 사용 버튼은 Dataset Builder의 스냅샷 선택값으로 연결한다.
- `d128823` 배포 후 서비스를 재시작했고 `/api/health/all` HTTP 200을 확인했다.

## 2026-05-27 RAG Assistant 검색 결과 Graph 탭

- 사용자 페이지의 Graph 탭 목적은 전체 Knowledge Graph 탐색이 아니라 이번 쿼리로 반환된 문서들이 왜 함께 표시됐는지 검증하는 것이다.
- 기존 `loadGraphFromQuery()`는 검색 결과 문서의 `organization` 값이나 쿼리 문자열에서 기관명을 추정해 조직 중심 또는 전체 그래프를 불러왔다.
- 이 방식은 `documents[].document_id` 목록과 그래프 노드를 직접 연결하지 못해 검색 결과 검증용 화면이라는 목적과 맞지 않는다.
- 백엔드에는 단일 문서용 `/api/graph/document/{document_id}`가 있지만 Cytoscape 형식이 아니고 여러 검색 결과 문서를 한 번에 묶는 API가 없다.
- 수정 방향은 `document_ids`와 선택 가능한 `source_id`를 받아 결과 문서, 연결 프로젝트, 기관, 카테고리, 기술, 방법론 노드를 Cytoscape 형식으로 반환하는 API를 추가하는 것이다.
- `/api/graph/cytoscape/documents`를 추가해 검색 결과 문서 노드를 중심으로 프로젝트, 카테고리, 기관, 기술, 방법론 연결을 반환하게 했다.
- 프론트 Graph 탭은 더 이상 기관명을 추정하지 않고 `documents[].document_id` 목록을 POST로 전달한다.
- `source_id`는 문서 응답에 있으면 그 값을 사용하고, 없으면 active snapshot 이름에서 `snapshot_YYYYMMDD_{source_id}` 패턴으로 추정한다.
- source별 그래프에서 문서를 찾지 못하면 기본 그래프로 fallback해 기존 GraphRAG 산출물이 있는 환경에서도 화면이 비지 않게 했다.
- 검증은 `python3 -m compileall backend/app/api/graph.py`, `node --check /tmp/rag-assistant-inline.js`, 샘플 문서 2건 helper 실행으로 진행했다.
- `git diff --check`는 저장소의 기존 미추적/변경 파일과 CRLF 추가 줄을 trailing whitespace로 보고해 별도 잔여 리스크로 기록한다.
- 서버 API 확인 중 `similar_project` 엣지로 다른 프로젝트가 많이 포함되어 결과 검증 그래프가 흐려지는 것을 확인했다.
- 검색 결과 문서의 프로젝트가 아닌 다른 프로젝트 노드는 제외하고, 결과 문서와 직접 설명 노드 중심으로 유지하도록 필터를 추가했다.

## 2026-05-27 Graph Build 메뉴와 Dataset Builder 7단계 통일

- Graph Build 메뉴와 Legacy Graph의 `buildGraph()`는 `/api/graph/build`를 직접 호출한다.
- Dataset Builder 7단계도 같은 `/api/graph/build`를 호출하므로 실제 작업은 같은 GraphRAG 생성 작업이다.
- 기존 직접 Build 버튼은 `source_id` 없이 전체 그래프를 만들 수 있어 Source별 Dataset Builder 흐름과 다르다.
- 운영 기준은 GraphRAG 생성 실행을 Dataset Builder 7단계로 통일하고, Graph Build 메뉴는 7단계로 이동하는 안내 경로로 둔다.
- Graph Build 메뉴, Legacy Graph View의 Build 버튼, 문서 선택 Graph 반영, Wiki의 Graphify 버튼, RAG Source의 Graph 생성 버튼을 모두 7단계 이동으로 바꿨다.
- Dataset Builder 7단계는 현재 `ctxSource` 값을 읽어 `/api/graph/build?source_id={source_id}`로 호출한다.
- 직접 Build를 남기는 유일한 위치는 7단계 실행 코드이며, 사용자가 Source 선택 후 실행하는 경로로 통일됐다.

## 2026-05-27 P0 RAG 응답 구조 표준화

- 사용자 페이지의 문서 카드 개선안은 백엔드 RAG 응답에 `source_id`, `document_id`, 원본 경로, 문서 그룹, 섹션, 사용 가능 산출물, 검색 근거 chunk, 관계 요약이 안정적으로 포함되어야 한다.
- 기존 `/api/rag/query`의 내부 답변 생성 프롬프트는 `evidence_snippets`를 문자열 목록으로 사용하므로, 검색과 답변 생성이 끝난 뒤 API 반환 직전에 구조화된 응답으로 정규화하는 방식이 안전하다.
- 프론트 `rag-assistant.html`은 현재 `evidence_snippets[0].slice()`와 `escapeHtml(snippet)` 형태로 문자열만 가정한다.
- 따라서 백엔드는 구조화된 `evidence_snippets`와 문자열 호환용 `content_snippets`를 함께 반환하고, 프론트는 snippet 객체와 문자열을 모두 표시할 수 있게 한다.
- `/api/rag/query`와 `/api/rag/similar-files` 응답에는 `source_id`, `snapshot`, 문서별 `original_path`, `document_group`, `document_type`, `file_ext`, 사용 가능 산출물 flag, `relation_summary`를 포함한다.
- `/api/rag/query`는 기존 `draft_answer`를 유지하면서 표준 응답용 `answer` alias도 함께 반환한다.
- `assemble_rag_response.py`는 기존 문자열 `evidence_snippets`를 유지하면서 `evidence_chunks`에 `chunk_id`, `text`, `page`, `score`를 추가해 API 정규화 단계에서 구조화 근거로 사용할 수 있게 했다.
- 실제 `main.py`에 등록된 RAG 라우터는 `backend/app/api/rag.py`이다. `rag_with_similar_files.py`는 같은 목적의 보조 파일이지만 현재 서비스 라우터가 아니므로, P0 표준화 호출은 `rag.py`의 `_run_query()`에 들어가야 한다.
- 서버 프로젝트 경로는 항상 `/data/weeslee/{프로젝트 폴더}` 기준으로 확인한다. `weeslee-rag`의 운영 경로는 `/data/weeslee/weeslee-rag`이다.
