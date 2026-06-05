## 2026-06-04 Dataset Builder 상태 추적 시스템 구축 시작

- **작업 배경**
  - Lee님의 피드백: admin.html은 단순 버튼 나열이 아니라 **문서 처리 상태를 보여줘야 함**.
  - 필수 표시 항목: 문서 신규 등록 여부, 관리자 승인 여부, OCR 완료, Chunk 완료, Embedding 완료, FAISS 반영, 검색 가능 상태, Graph/Wiki 생성 여부.
  - 구현 순서: 문서별 상태 구조 정의 → status-summary API → Dataset Builder 상태 요약 카드 → 문서 목록 상태 컬럼 → Metadata Review UI → Pipeline Progress UI

- **Step 1 완료: 문서별 상태 구조 정의**
  - `backend/app/models/document_pipeline_status.py` 생성.
  - `StepStatus` enum: NOT_STARTED, PENDING, IN_PROGRESS, COMPLETED, FAILED, SKIPPED, REVIEW_REQUIRED, REJECTED
  - 10단계별 상태 모델 정의:
    - `Step1SourceScanStatus`: document_id, source_id, category_id, snapshot_id, file_count, scanned_at
    - `Step2MetadataAutoStatus`: project_name, organization, document_type, year, collection_candidates, confidence
    - `Step3MetadataReviewStatus`: reviewed_by, review_status, final_project_name, tags, keywords, include_in_rag/graph/wiki
    - `Step4OCRParserStatus`: ocr_engine, total_pages, extracted_chars, ocr_quality_score, failed_pages
    - `Step5ChunkBuildStatus`: chunk_method, chunk_size, total_chunks, text/table/slide_chunks
    - `Step6EmbeddingBuildStatus`: embedding_model, embedding_dimension, total_embeddings, failed_embeddings
    - `Step7FAISSBuildStatus`: collections_built, total_vectors, index_type, snapshot_id
    - `Step8GraphBuildStatus`: graph_storage, nodes_created, edges_created, node_types
    - `Step9WikiBuildStatus`: wiki_model, grouping_by, wiki_files_created, wiki_count
    - `Step10SearchQualityStatus`: quality_test_passed, quality_score, activated_at, active_snapshot_id, rollback_available
  - `DocumentPipelineStatus`: 전체 10단계 상태를 담는 마스터 모델
  - `DatasetStatusSummary`: 전체 데이터셋 상태 요약 (admin.html Dataset Builder용)

- **Step 2 완료: GET /api/admin/dataset/status-summary API 구현**
  - `backend/app/api/admin.py` 라인 1221-1443에 엔드포인트 추가.
  - 기능: 10단계 파이프라인 각 단계별 처리 현황 집계하여 `DatasetStatusSummary` 반환.
  - 집계 로직:
    - **Step 1**: `data/staged/manifest/*.jsonl` 파일에서 copy_status="copied" 문서 수 집계
    - **Step 2**: `data/staged/metadata/*.json` 파일에서 provenance=INFERRED/EXTRACTED 문서 수, confidence 평균 집계
    - **Step 3**: SQLite `metadata_db_service`에서 meta_status=confirmed/review_required/rejected 문서 수 집계
    - **Step 4**: `data/processed_text/*.txt` 파일 수 집계 (OCR 완료)
    - **Step 5**: FAISS metadata에서 chunk 수, 문서별 평균 chunk 수 집계
    - **Step 6**: FAISS index 존재 여부로 embedding 완료 판단, embedding_model 정보 포함
    - **Step 7**: collection별 index 파일 수, total_vectors, snapshot_id 집계
    - **Step 8**: `data/indexes/graph/graph_nodes.jsonl`, `graph_edges.jsonl` 라인 수 집계
    - **Step 9**: `data/wiki/*.md` 파일 수 집계, wiki_model 정보 포함
    - **Step 10**: `active_index.json`에서 active_snapshot, active_collections 추출, quality_report.json에서 검증 통과 여부 확인
  - Response 모델: Pydantic `DatasetStatusSummary` (JSON 직렬화 지원)
  - 특징: 기존 파일 기반 상태 데이터를 읽어서 집계 (DB 의존성 최소화)

- **Step 3 완료: Dataset Builder 상태 요약 카드 추가**
  - `frontend/admin.html` 라인 1364-1372에 상태 요약 카드 HTML 추가.
  - `frontend/admin.html` 라인 1361에 "🔄 상태 새로고침" 버튼 추가.
  - `frontend/admin.html` 라인 9102-9237에 `loadDatasetStatusSummary()` JavaScript 함수 구현.
  - 기능:
    - GET /api/admin/dataset/status-summary API 호출
    - 4개 요약 카드: 전체 문서, Step 1 완료, Step 3 검수 대기, Step 3 검수 완료
    - 10단계 상태 테이블: 단계별 완료 수, 진행 상태, 상세 정보 표시
    - 마지막 업데이트 시간 표시
  - MutationObserver로 Dataset Builder 페이지 활성화 시 자동으로 상태 로드.
  - 새로고침 버튼 클릭 시 수동으로 상태 갱신 가능.

- **Step 4 완료: 문서 목록 상태 컬럼 추가**
  - `frontend/admin.html` 라인 4281에 "파이프라인 상태 (10단계)" 테이블 헤더 추가.
  - `frontend/admin.html` 라인 4286, 8049, 8067, 8146에 colspan을 8→9로 수정.
  - `frontend/admin.html` 라인 8117-8141에 `renderPipelineStatus(doc)` 함수 구현.
  - 기능:
    - 10개 단계 상태를 1~10 숫자 박스로 시각화
    - 완료된 단계: 녹색 배경 (#22c55e), 흰색 텍스트
    - 미완료 단계: 회색 배경 (#e5e7eb), 회색 텍스트 (#9ca3af)
    - 각 단계 완료 여부를 기존 문서 필드 기반으로 추정:
      - Step 1: document_id 존재 여부
      - Step 2: project_name 존재 여부
      - Step 3: meta_status === 'confirmed'
      - Step 4: status가 text_extracted 이상
      - Step 5: status가 chunked 이상
      - Step 6: status가 embedded 이상
      - Step 7: status가 faiss_indexed 이상
      - Step 8: status === 'graph_created'
      - Step 9: status === 'wiki_created'
      - Step 10: status === 'rag_ready'
  - `frontend/admin.html` 라인 8160, 8170에 pipelineStatus 컬럼 렌더링 추가.
  - 문서 목록 테이블에서 각 문서의 10단계 처리 진행 상황을 한눈에 확인 가능.

- **다음 작업**
  - Step 5: Metadata Review UI 구현 (Step 3 관리자 검수 화면)
  - Step 6: Pipeline Progress UI 추가 (진행 중인 작업 실시간 모니터링)

## 2026-06-04 Dataset Builder 10단계 재구성 완료

- **작업 배경**
  - Lee님의 `docs/2026-06-04_Lee_데이타셋_생성단계.md`, `docs/2026-06-04_Lee_데이타셋구조.md`, `docs/2026-06-04_Lee_마지막질문.md` 문서 분석.
  - 기존 6단계 구조(OCR→청킹/임베딩→메타데이터→GraphRAG→Wiki→FAISS 활성화)의 문제점 파악.
  - 나무 비유: 뿌리(snapshot_id) → 큰 줄기(source_id) → 작은 줄기(category_id) → 잎(document_id) → 잎맥(chunk_id).
  - **핵심 원칙: Source Scan과 Metadata를 OCR보다 먼저 실행하여 document_id를 먼저 확정.**

- **frontend/admin.html 수정 사항**
  - 좌측 네비게이션 메뉴: 6단계 → 10단계 업데이트 (라인 1155-1167).
  - 파이프라인 개요 카드: 6단계 → 10단계 업데이트 (라인 1359-1404).
  - 상단 안내 문구: Lee님 지시서대로 변경 (라인 1352-1353).

- **10단계 구조**
  - **Step 1: Source Scan** (라인 1419-1467)
    - 목적: 원본 폴더 스캔, snapshot_id/source_id/category_id/document_id 생성.
    - 출력: source_scan_result.jsonl, documents.jsonl, snapshot 정보.

  - **Step 2: Metadata Auto** (라인 1469-1510)
    - 목적: 파일명/폴더명/접두사 기반 1차 메타데이터 자동 생성.
    - 처리: RFP_ 접두사 분석, 프로젝트명 추출, collection_id 후보 추천.

  - **Step 3: Metadata Review** (라인 1512-1557)
    - 목적: 관리자 검수 및 확정.
    - 상태값: registered → metadata_suggested → review_required → metadata_reviewed → ready_for_processing.
    - 주의: `metadata_reviewed` 또는 `ready_for_processing` 상태만 운영 FAISS 반영.

  - **Step 4: OCR/Parser** (라인 1559-1727, 기존 Step 1에서 변경)
    - 목적: PDF/HWP/HWPX/DOCX/PPTX/XLSX 텍스트 추출.
    - 출력: full_text.md, pages.jsonl, tables.jsonl, ocr_report.json.

  - **Step 5: Chunk Build** (라인 1731-1786, 기존 Step 2에서 분리)
    - 목적: 제목/목차/슬라이드/표/문단 단위 청킹.
    - 설정: chunk_size, chunk_overlap, chunk_type (text/table/slide).
    - 주의: Graph에 Chunk 노드는 생성 안 함(B안), FAISS 검색용 chunk_id는 유지.

  - **Step 6: Embedding Build** (라인 1788-1861, 기존 Step 2에서 분리)
    - 목적: Chunk 텍스트를 embedding vector로 변환.
    - 설정: nomic-embed-text(권장), batch_size, retry_count.
    - 출력: embeddings.jsonl, embedding_build_report.json.

  - **Step 7: FAISS Build** (라인 1927-1941, placeholder 추가)
    - 목적: Embedding vector를 collection_id 기준 FAISS Index로 구성.
    - 출력: data/faiss/{collection_id}/index.faiss, index_meta.jsonl, snapshot.

  - **Step 8: Graph Build (Ontology / JSON Graph)** (라인 1943-2011, 기존 Step 4에서 변경)
    - 목적: 문서, 프로젝트, 기관, 기술, 키워드 간 관계 생성.
    - **중요 수정: JSON Graph를 기본값으로, Neo4j는 선택 옵션** (라인 1952-1964).
    - Graph 저장 방식: JSON Graph (graph_nodes.jsonl, graph_edges.jsonl) 기본, Neo4j 선택.
    - Chunk 노드: 생성 안 함(B안 권장), Document 노드에 chunk_count만 저장.

  - **Step 9: Wiki Build** (라인 2013-2077, 기존 Step 5에서 변경)
    - 목적: 프로젝트/기관/분야/기술 기준 지식 문서 생성.
    - 설정: gemma3:12b(권장), grouping 기준(프로젝트/기관/분야/기술/문서유형).
    - 주의: Wiki는 원문 근거를 대체하지 않음, 검색/답변 보조 지식 계층.

  - **Step 10: Search Quality / Activate** (라인 2079-2155, 기존 Step 6에서 변경)
    - 목적: 운영 반영 전 검색 품질 검증, 검증 완료 Snapshot만 활성화.
    - Search Quality 검증 항목: 테스트 질문 Top-K, source_id/category_id 필터, RFP→제안서 유사 검색, GraphRAG 관계, Wiki, 한글 검색.
    - Activate: Snapshot pointer 방식, rollback 정보 저장.
    - 주의: Search Quality 검증 없이 Activate 금지, 기존 Index 직접 덮어쓰기 금지.

- **API 엔드포인트 (Lee 지시서 제안)**
  - Step 1: GET /api/admin/dataset/sources, POST /api/admin/dataset/source-scan
  - Step 2: POST /api/admin/dataset/metadata/auto
  - Step 3: GET /api/admin/dataset/metadata/review-list, POST /api/admin/dataset/metadata/review
  - Step 4: POST /api/admin/dataset/ocr-run
  - Step 5: POST /api/admin/dataset/chunk-build
  - Step 6: POST /api/admin/dataset/embedding-build
  - Step 7: POST /api/admin/dataset/faiss-build
  - Step 8: POST /api/admin/dataset/graph-build
  - Step 9: POST /api/admin/dataset/wiki-build
  - Step 10: POST /api/admin/search-quality/run, POST /api/admin/dataset/activate, POST /api/admin/dataset/rollback

- **기존 Step 3 (Metadata) 섹션 처리**
  - 라인 1863-1925에 "기존 Step 3: 메타데이터 (삭제 예정 - Step 2, 3으로 이미 분리)" 주석으로 남김.
  - 실제 코드는 유지(나중에 필요시 참조용), 새로운 Step 2, 3으로 기능 분리 완료.

- **작업 결과**
  - admin.html Dataset Builder가 6단계 → 10단계로 완전히 재구성됨.
  - Lee님의 나무 비유와 10단계 흐름이 UI에 정확히 반영됨.
  - JSON Graph가 기본값으로 명시됨(Neo4j는 선택 옵션).
  - Search Quality 검증이 Activate 전 필수 단계로 포함됨.
  - Snapshot/Rollback 구조가 Step 10에 명시됨.

## 2026-06-04 P0~P2 체크리스트 작업 완료

- **P0: RAG Source 트리 정합성**
  - `rag_filelistdetail.txt` 실제 폴더 구조 분석 완료.
  - 실제 존재 폴더: RFP(47), 제안서 5개(147), 산출물 5개(56) = 총 250개 파일.
  - `platform_config/document_sources.json`을 14개 소스로 정합성 완료.
  - 미존재 폴더(감리, PMO, PoC)는 document_sources.json에서 제거.

- **P0: Collection Template 논리 컬렉션 정합성**
  - `backend/app/api/templates.py`의 `_WEESLEE_COLLECTIONS` 업데이트.
  - 실제 존재 폴더 컬렉션 14개: enabled=True, 파일 수 description 추가.
  - 미존재 폴더 컬렉션 6개(감리/PMO/PoC × 제안서/산출물): enabled=False, "폴더 미존재" description.
  - 주석에 실제 폴더 구조 아스키 트리 추가.

- **P1: rag-assistant.html 문서 카드 근거 확인 흐름**
  - 이미 구현 확인: 문서 카드 버튼 6개(상세/파일/요약/청크/근거/Graph).
  - 상세 패널 탭 5개(원문/요약/청크/근거/Graph).
  - 검색 결과 필드 8개(document_id, source_id, project_name 등) 일관 표시 확인.

- **P2: Graph 엣지 라벨 한국어 변환**
  - `resolveGraphRelationLabel` 함수로 19개 관계 타입 한국어 변환 확인.
  - `formatGraphRelations` 함수로 문서별 근거 관계 요약 생성 확인.
  - cytoscape 기반 시각화, 팝업 창 지원 확인.
  - graphSummary 변수로 문서 카드에 🔗 관계 배지 표시 확인.

## 2026-05-29 rag-assistant 파일 클릭/미리보기 안정화 구현

## 2026-05-30 Lee 문서 우선순위 정리

- `2026-05-30_Lee_프로젝트_기능개선안.md`와 `2026-05-30_Lee_기능개선_작업지시서.md`를 기준으로 구현 순서를 재정렬했다.
- `docs/2026-05-30_Codex_Lee_기능개선_우선순위_및_실행계획.md`를 생성해 P0→P1→P2→P3 순 실행 계획으로 정리했다.
- Lee 문서 공통 결론: 지금 당장 LangGraph/Agent 중심의 신규 기능보다 기존 Source 트리 정합성, 데이터 계약 정리, Graph 스키마 고정이 선행되어야 한다.
- `checklist.md`에 2026-05-30 우선순위 반영 항목을 추가했고, P0 8개 항목을 당일 실행 대상으로 남겼다.

- 사용자는 운영 UI 직접 테스트 문서의 결론에 따라 파일 클릭과 미리보기 안정화 작업을 구현 순서대로 진행하라고 요청했다.
- 변경 범위는 `frontend/rag-assistant.html`의 결과 카드/상세 패널/미리보기 모달과 `backend/app/api/documents.py`의 문서 상세 API 경량화로 제한한다.
- 기존 워킹트리에는 사용자가 만든 미커밋 변경이 많으므로, 관련 파일의 필요한 부분만 수정하고 다른 파일은 건드리지 않는다.
- `/api/documents/{id}`는 현재 `raw_text`까지 포함한 큰 JSON을 반환하므로, 기본 상세 응답에서는 metadata와 available formats만 반환하고 본문은 `/text`, `/html`, `/markdown`, `/summary`에서 지연 로드하는 방향으로 수정한다.
- 사용자 페이지에서 `/api/admin/faiss/category-status` 401이 보였으므로, 해당 호출은 실패해도 콘솔 오류를 만들지 않도록 인증 상태를 사전 확인하거나 조용히 fallback한다.
- 구현 결과 카드 전체에 `onclick`, `role=button`, `tabindex=0`, Enter/Space 처리를 추가했고, 카드 액션은 `상세 보기`, `파일 보기`, 요약, 청크, 근거, Graph로 분리했다.
- 상세 패널 헤더에 `파일 보기`, `다운로드`, `경로 복사` 액션을 고정했다.
- 미리보기 모달은 metadata 조회와 형식별 조회에 timeout을 두고, 실패 시 `다시 시도`와 `다운로드` fallback을 표시한다.
- 검증은 `python3 -m compileall backend/app/api/documents.py`, inline script 파싱, 로컬 Playwright 카드 클릭 테스트, `git diff --cached --check`로 수행했다.
- `frontend/rag-assistant.html`의 워킹트리에는 기존 CRLF 줄바꿈 변경이 남아 있어, 커밋에는 `--ignore-space-at-eol` 기준 기능 변경만 staged patch로 반영했다.

## 2026-05-29 운영 RAG Assistant 결과 파일 UI 점검

- 사용자는 운영 URL `https://server.weeslee.co.kr/weeslee-rag/rag-assistant.html`에서 쿼리 `AI 기반 차세대 교육 시스탬 구축`으로 RAG 실행 후 결과 탭 파일 클릭 UI를 직접 테스트하고 수정 사항 문서를 작성해 달라고 요청했다.
- 작업은 실제 브라우저 자동화로 운영 화면을 열어 클릭 흐름을 확인하고, 코드 수정이 아니라 문서 작성 범위로 진행한다.
- 문서에는 확인 환경, 재현 절차, 관찰 결과, 문제점, 수정 권고, 우선순위를 남긴다.
- 사용자가 경로를 `https://server.weeslee.co.kr/weeslee-rag/rag-assistant.html`로 재확인했으므로 해당 URL 그대로 테스트했다.
- `curl -i -L`와 Playwright 브라우저 접속 모두 HTTP 404와 `{"detail":"Not Found"}`를 반환했다.
- 따라서 지정 URL에서는 쿼리 입력, RAG 실행, 결과 파일 클릭 UI까지 진행할 수 없다.
- 별도 확인 결과 `/weeslee-rag/`는 `/weeslee-rag/frontend/rag-assistant.html`로 리다이렉트되고 해당 경로는 200 OK였지만, 사용자가 지정한 경로와 다르므로 직접 UI 테스트 대상에서는 분리한다.
- 사용자가 최종 테스트 URL을 `https://server.weeslee.co.kr/weeslee-rag/frontend/rag-assistant.html`로 정정했다.
- `docs/2026-05-29_Lee_rag-assistant.html_기능개선안.md`를 참조해 운영 테스트 결과와 개선 항목을 매핑했다.
- Playwright로 쿼리 `AI 기반 차세대 교육 시스탬 구축`을 실행했고 결과 카드 10건, 우측 답변 패널 관련 파일 5건을 확인했다.
- 카드 본문 클릭은 동작하지 않았고 카드 헤더 또는 `원문` 버튼만 문서 상세 패널을 열었다.
- 우측 답변 패널의 `보기` 버튼은 미리보기 모달을 열었지만 테스트 시점에는 `불러오는 중...` 상태가 관찰됐다.
- 직접 API 확인 결과 문서 114698의 상세 JSON은 약 981KB, text JSON은 약 489KB, original PPTX는 약 41.5MB로 응답했다.
- 작성 문서는 `docs/2026-05-29_Codex_rag-assistant_운영UI_직접테스트_수정사항.md`이다.

## 2026-05-29 rag-assistant.html 분석 문서 작성

- 사용자는 `frontend/rag-assistant.html` 수정 코드 분석을 어제 Codex 문서 형식으로 오늘 날짜 문서에 작성해 달라고 요청했다.
- 어제 Codex 문서 형식은 `docs/2026-05-28_Codex_LLM_RAG_온톨로지_적용제안.md`, `docs/2026-05-28_Codex_Figma와이어프레임_구현매핑.md`를 기준으로 삼는다.
- `git diff --ignore-space-at-eol -- frontend/rag-assistant.html` 결과는 비어 있어, 현재 워킹트리의 `rag-assistant.html` 변경은 줄바꿈 또는 공백 끝 차이로 판단한다.
- 따라서 문서는 "실제 내용 diff 없음"을 먼저 명시하고, 현재 파일에 들어 있는 문서 카드, 미리보기 모달, 상세 패널, Graph 근거, 선택 문서 답변 UI의 구조 분석과 잔여 리스크를 정리한다.
- 작성 문서는 `docs/2026-05-29_Codex_rag-assistant_html_수정코드분석.md`이다.
- 검증은 문서 내용 확인, `git diff --check -- checklist.md context-notes.md docs/2026-05-29_Codex_rag-assistant_html_수정코드분석.md`, 변경 상태 확인으로 수행했다.

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

## 2026-05-28 오늘 작업 표시

- 오늘 작업 기준 파일은 `docs/2026-05-28_Claude_작업목록.md`로 확인했다.
- 루트 `checklist.md`는 이전 P0 RAG 응답 구조 표준화 완료 목록만 담고 있어, 오늘 실행용 체크리스트로 교체했다.
- 실제 개발 구현은 아직 수행하지 않았으므로 P0, P1, P2, P3 개발 항목은 모두 미완료 상태로 표시했다.
- 완료로 표시한 항목은 작업목록 확인, 체크박스 변환, 루트 체크리스트 반영, context notes 기록뿐이다.
- 검증은 `sed`로 수정 문서 내용을 확인하고 `git diff -- checklist.md context-notes.md docs/2026-05-28_Claude_작업목록.md`로 tracked 파일 diff를 확인했다.

## 2026-05-28 Codex 문서 기준 오늘 작업 재표시

- 사용자가 어제 Codex가 작성한 문서를 기준으로 오늘 작업을 다시 표시해 달라고 요청했다.
- 확인한 기준 문서는 `docs/2026-05-27_Codex_RAG근거자료_수정권고.md`이다.
- 이 문서의 권고 실행 순서는 RAG Source 트리와 Collection Template 정합성, 사용자 문서 상세 근거 확인, Graph 엣지 라벨 개선, Step 5~8 산출물 통계 표시, Graphify 문장형 근거 요약이다.
- 따라서 `checklist.md`를 Codex 권고 실행 순서 중심으로 재정리했다.
- `docs/2026-05-28_Claude_작업목록.md`의 XSS, API 인증, 에러 핸들링은 별도 보안 트랙으로 두고 이번 RAG 근거자료 작업과 섞지 않는다.

## 2026-05-28 admin.html 디자인 개선 통합 실행순서

- 사용자가 `docs/2026-05-28_Claude_DesignUX.md`도 확인해 `admin.html` 디자인 개선안을 실행 순서대로 작성하고 이전 문서를 통합해 달라고 요청했다.
- 확인한 문서는 `docs/2026-05-28_Claude_DesignUX.md`, `docs/2026-05-28_Claude_관리자페이지_전면개편안.md`, `docs/2026-05-23_Codex_관리자페이지_디자인개선안.md`, `docs/2026-05-23_관리자html_UX_UI_개선안.md`, `docs/2026-05-26_관리자페이지_UX_UI_개선안.md`, `docs/2026-05-27_Codex_RAG근거자료_수정권고.md`, `frontend/admin.html`이다.
- live URL `https://server.weeslee.co.kr/weeslee-rag/frontend/admin.html`은 `curl -I -L --max-time 15`로 HTTP 200, `Content-Length: 387375`, `last-modified: Wed, 27 May 2026 07:18:07 GMT`를 확인했다.
- 현재 `admin.html`은 Docs 스타일 화면, Overview, Source Documents, RAG Build Wizard, FAISS, Graph/Wiki, Jobs/Logs, Search Quality, Settings, Legacy Console을 이미 포함한다.
- 통합 실행 문서는 전면 재작성보다 현재 구조를 유지하면서 Legacy 분리, Dashboard 상태 중심 개편, RAG Source 트리 정합성, 신규 문서 알림, Dataset Builder Step 5~8 근거 목적 표시 순서로 작성했다.
- 산출물은 `docs/2026-05-28_admin_html_디자인개선_통합실행순서.md`이다.

## 2026-05-28 온프라미스 메뉴 구성 원칙 반영

- 사용자가 관리자 메뉴별로 작업 실행에 필요한 필수 설정값 입력폼과 실행 후 확인 섹션을 같은 페이지에 표시해야 한다고 요구했다.
- 이 요구사항은 온프라미스 운영 콘솔 기준으로 맞다. 사내 서버, NAS mount, 로컬 DB, FAISS index, LLM endpoint, Job timeout 같은 값은 메뉴 이동 없이 확인 가능해야 한다.
- `docs/2026-05-28_admin_html_디자인개선_통합실행순서.md`에 메뉴별 화면 구성 표준, 온프라미스 구성 기준, 메뉴별 필수 입력폼과 실행 후 확인 섹션을 추가했다.
- 실행 순서의 각 메뉴 작업에도 Source ID, Snapshot, 경로, 모델, 필터 같은 필수 입력폼을 상단에 둔다는 항목을 추가했다.

## 2026-05-28 Codex LLM RAG 온톨로지 적용제안 문서화

- 사용자가 방금 작성한 답변 내용을 `2026-05-28_Codex_`로 시작하는 문서로 작성했는지 확인했다.
- 기존에는 해당 이름의 문서가 없어서 `docs/2026-05-28_Codex_LLM_RAG_온톨로지_적용제안.md`를 새로 작성했다.
- 문서에는 기존 FAISS RAG 구조 유지, metadata 정규화, ontology schema 추가, 기존 `build_graph_jsonl.py` 확장, JSONL Graph 유지, Hybrid Search API 추가, LLM context 분리, 관리자 Ontology Manager와 Relation Review 추가 순서를 담았다.

## 2026-05-28 LLM RAG 온톨로지 P0 실행순서

- 사용자가 실행 순서를 P0부터 작성해 달라고 요청했다.
- `docs/2026-05-28_Codex_LLM_RAG_온톨로지_적용제안.md`에 P0부터 P9까지 목표, 작업 파일, 구현 항목, 검증 기준, 완료 조건을 추가했다.
- P0은 기준 스키마와 메타데이터 계약 확정으로 두었다.
- 오늘 착수 권장 범위는 `ontology_schema.json` 생성, metadata/chunk 필수 필드 점검, 현재 Graph node/relation 목록 추출, schema와 현재 산출물 차이 문서화, P1 구현 범위 확정으로 제한했다.

## 2026-05-28 Figma 와이어프레임 화면 구조 확인

- 사용자가 공유한 Figma 주소는 `https://www.figma.com/design/xL27BRiX1TTxV00OpFIB9W/WEESLEE-RAG-Admin-Dashboard---Wireframe?node-id=0-1&t=Jip7hCj0ni20lofi-1`이다.
- 현재 세션의 Figma MCP 도구는 노출되지 않았고, URL 직접 조회는 CloudFront 403으로 막혔다.
- 대신 저장소에 있는 `docs/figma_dashboard_wireframe.png`와 `docs/figma_step1_wireframe.png`를 확인했다.
- 확인된 공통 레이아웃은 상단 브랜드 바, 좌측 고정 사이드바, 본문 작업 영역, 카드 기반 상태 및 결과 패널이다.
- 대시보드 화면은 Dataset Alert, 문서소스/스캔 파일/메타데이터/FAISS/Graph-Wiki/검색 상태 카드, 대시보드 설정, 시스템 현황 패널로 구성된다.
- Dataset Builder 사이드바는 Step 1 OCR/파싱, Step 2 청킹/임베딩, Step 3 메타데이터, Step 4 온톨로지, Step 5 엔티티/관계, Step 6 Graph 저장, Step 7 하이브리드 검색, Step 8 LLM 답변, Step 9 Wiki 생성, Step 10 관리자 검수 순서다.
- 확인된 Step 1 화면은 텍스트 추출 설정, OCR 설정, 파일 제한, 대상 선택, 출력 형식, Step 1 실행 결과, 실패 문서 재처리 흐름을 포함한다.
- 다음 구현 비교는 `frontend/admin.html`과 `frontend/assets/js/admin/admin-docs-layout.js`를 기준으로 Figma의 사이드바 단계와 대시보드 카드 구성을 맞추는 방향이 적절하다.

## 2026-05-28 Figma 와이어프레임 구현 매핑

- 현재 `frontend/admin.html`은 `#wrAdminDocsApp` 신규 Docs 스타일 화면과 `tab-*` Legacy Console이 공존한다.
- 신규 Docs 화면은 상단 바, 좌측 메뉴, Overview, Source Documents, RAG Build Wizard, FAISS, Graph, Wiki, Jobs, Logs, Search Quality, Settings를 제공한다.
- Legacy Console은 Dataset Builder 상세 실행, FAISS, Graph View, LLM Wiki, 문서 관리 기능을 실제 실행 경로로 보존한다.
- Figma 대시보드에는 Dataset Alert, 6개 상태 카드, Dashboard 설정, 시스템 현황 패널이 있으나 현재 Overview는 다음 작업 안내와 순차 작업 가이드 중심이다.
- Figma Dataset Builder는 Step 1 OCR/파싱부터 Step 10 관리자 검수까지 표시하지만, 현재 구현은 파일 스캔, Collection, Metadata, Tag/Keyword, OCR/청킹, FAISS, Graph, Wiki, 검색 테스트, FAISS 활성화 순서다.
- Step 번호를 바로 바꾸면 `wizardRun(step)` 실행 의미가 깨질 수 있으므로, 표시 단계와 기존 실행 단계의 매핑 테이블을 먼저 두는 방식이 안전하다.
- 구현 매핑 문서는 `docs/2026-05-28_Codex_Figma와이어프레임_구현매핑.md`에 저장했다.

## 2026-05-28 Figma P0 사이드바 구현

- P0 범위는 `frontend/admin.html`의 신규 Docs 스타일 사이드바를 Figma 운영 메뉴 기준으로 재정렬하는 작업으로 제한했다.
- 사이드바는 OVERVIEW, ALERTS, RAG SOURCE, DATASET BUILDER, FAISS INDEX, ANALYTICS 순서로 정리했다.
- Dataset Builder에는 Figma 기준 Step 1 OCR/파싱부터 Step 10 관리자 검수까지의 버튼을 모두 노출했다.
- 기존 `wizardRun(step)` 번호를 바꾸면 실행 의미가 깨질 수 있으므로, `openDatasetBuilderStep(figmaStep)`에서 Figma 표시 단계와 기존 구현 단계의 임시 매핑을 둔다.
- 현재 매핑은 Step 1 -> 기존 Step 5, Step 2 -> 기존 Step 6, Step 3 -> 기존 Step 3, Step 4~6 -> 기존 Step 7, Step 7~8 -> 기존 Step 9, Step 9 -> 기존 Step 8, Step 10 -> 기존 Step 9이다.
- `openDashboardAlerts()`는 대시보드 상태판 위치로 이동하도록 추가했다.
- 다음 P1에서는 Overview 본문을 Dataset Alert, 6개 상태 카드, Dashboard 설정, 시스템 현황 패널 구조로 맞추는 작업이 필요하다.

## 2026-05-28 서버 배포 경로 확인

- 사용자가 서버 배포 시 프로젝트 폴더는 `/data/weeslee/weeslee-rag`라고 재확인했다.
- 이후 배포, 원격 검증, 운영 경로 설명은 이 경로를 기준으로 한다.

## 2026-05-28 Figma P1 Overview 구현

- P1 범위는 `frontend/admin.html` Overview 본문을 Figma Dashboard 구조로 재배치하는 작업으로 제한했다.
- Overview 페이지는 `wr-page-wide` 클래스를 추가해 기존 920px 폭 제한을 풀었다.
- Dataset Alert에는 신규 문서, 수정 문서, 처리 대기, 실패 작업 카드를 추가했다.
- 기존 `wrOverviewSourceState`, `wrOverviewFileState`, `wrOverviewMetaState`, `wrOverviewFaissState`, `wrOverviewGraphWikiState`, `wrOverviewSearchState` ID는 유지해 기존 상태 조회 흐름을 깨지 않게 했다.
- Dashboard 설정 패널과 시스템 현황 패널을 추가했다.
- `loadOverviewStepStatus()`는 새 Alert 카드와 시스템 현황 ID를 초기화하고, 기존 API 응답에 값이 있으면 카운트를 채우도록 보강했다.
- 검색 품질 히스토리 API가 응답하면 총 질문, 성공률, 평균 응답, 참조 문서, 최근 질문 목록을 표시한다.

## 2026-05-28 Figma P2 Dataset Builder 단계명 정렬

- P2 범위는 `frontend/admin.html`의 Docs 스타일 Dataset Builder와 Legacy Wizard의 표시 단계명을 Figma 기준으로 맞추는 작업으로 제한했다.
- Docs 스타일 Wizard 제목을 `Dataset Builder`로 변경하고, Figma 기준 표시 단계와 기존 Legacy 실행 흐름이 연결된다는 안내를 추가했다.
- Docs 스타일 Step 1~10은 OCR/파싱, 청킹/임베딩, 메타데이터, 온톨로지, 엔티티/관계, Graph 저장, 하이브리드 검색, LLM 답변, Wiki 생성, 관리자 검수 순서로 표시한다.
- Legacy Wizard 상세 목록도 동일한 Figma 단계 문구를 반영하되, 기존 API 경로와 `wizardRun(step)` 번호는 유지했다.
- `syncWizardPipelineCopy()`가 Step 5/6 문구를 예전 이름으로 되돌리지 않도록 Figma 기준 문구로 갱신했다.

## 2026-05-28 Figma P3 Step 1 OCR/파싱 패널

- P3 범위는 `frontend/admin.html`의 Docs 스타일 Dataset Builder 안에 Step 1 OCR/파싱 설정과 실행 결과 패널을 추가하는 작업으로 제한했다.
- 설정 패널에는 OCR 활성화, OCR 언어, OCR DPI, 최소 텍스트 길이, 최대 파일 크기, 지원 확장자, 처리 대상, 출력 형식을 배치했다.
- 실행 결과 패널에는 처리 문서, 추출 성공, OCR 사용, 추출 실패 카드와 실패 문서 안내 영역을 추가했다.
- 새 API를 만들지 않고 `runStep1Parsing()`에서 기존 `wizardRun(5)` OCR/청킹 실행 흐름을 호출한다.
- 설정 저장은 현재 표시용이며 `saveStep1ParsingSettings()`에서 사용자 피드백만 제공한다. 실제 백엔드 파라미터 연결은 후속 작업으로 남긴다.

## 2026-05-28 Figma P4 Step UI 연결 검증

- P4 범위는 Figma 기준 Step UI와 기존 Legacy Wizard 실행 단계의 연결을 보강하는 작업으로 제한했다.
- `DATASET_BUILDER_LEGACY_STEP_MAP`과 `getDatasetBuilderLegacyStep()`을 추가해 표시 단계와 실행 단계를 명시적으로 분리했다.
- `openDatasetBuilderStep(figmaStep)`는 이제 Figma Step 카드를 우선 강조하고, 연결된 Legacy Step도 함께 강조한다.
- `syncWizardStepperState()`는 Figma Step 상태를 같은 번호의 Legacy Step이 아니라 매핑된 Legacy Step 상태에서 가져오도록 수정했다.
- 예: Figma Step 1 OCR/파싱은 Legacy Step 5 OCR/청킹 상태를 표시한다.
- 실제 브라우저에서는 `frontend/assets/js/admin/admin-docs-layout.js`의 `syncWizardStepperState()`가 나중에 로드되어 inline 함수를 덮어쓰므로, 외부 스크립트에도 같은 Figma-to-Legacy 매핑을 반영했다.

## 2026-05-28 P3-P4 RAG 근거자료 표시 개선

### P3: Dataset Builder 완료 메시지 보강

**위치:** `frontend/admin.html:7494-7562` (_wizardFormatResponseSummary 함수)

**변경 내용:**
- Step 5 (OCR/파싱): OCR 성공/실패 건수, 청킹 성공 건수 표시 + "(사용자 검증용 근거 생성)" 목적 표시
- Step 6 (청킹/임베딩): 스냅샷명, 문서 수, 청크 수, 임베딩 수 표시 + "(검색 검증용 색인 완료)" 목적 표시
- Step 7 (Graph RAG): source_id, 노드/엣지/문서 수 표시 + "(관계 근거 Graph 생성 완료)" 목적 표시
- Step 8 (Wiki 생성): source_id, 프로젝트 수, 성공/실패 건수 + 실패 프로젝트명(최대 3개) 표시 + "(지식 체계 Wiki 구축 완료)" 목적 표시

**UI 라벨 보강:**
- 사이드바 메뉴 버튼 (frontend/admin.html:748-756)에 목적 괄호 표시 추가
  - Step 1: OCR/파싱 (근거 생성)
  - Step 5: 엔티티/관계 (근거 산출)
  - Step 6: Graph 저장 (색인 완료)
  - Step 7: 하이브리드 검색 (Graph 근거)
  - Step 9: Wiki 생성 (지식 체계)
- 단계 상세 헤더 (frontend/admin.html:1803, 1824, 1845, 1866)에 목적 괄호 표시 추가

**목적:**
- 관리자가 각 단계 완료 후 결과를 명확히 확인
- 각 단계의 목적(사용자 검증용 근거 생성, 색인 완료, Graph 생성, Wiki 구축)을 UI에 명시

### P4: Graphify 문장형 근거 요약

**위치:** `frontend/rag-assistant.html:3418-3450` (renderAnswerPanel 함수)

**변경 내용:**
- 답변 하단에 "📊 관계 근거 (검색 결과 검증용 Graph)" 섹션 추가
- 검색 결과 문서들의 graph_context/relations 필드에서 상위 3개 관계 추출
- 엣지 관계: "source → 관계유형 → target" 형태로 표시
- 프로젝트 체인: "🔗 프로젝트명 (N단계 문서 체인)" 형태로 표시
- 3개 초과 시 "외 N개 관계" 표시

**UI 구분:**
- 문서 카드의 graphSummary (frontend/rag-assistant.html:3725-3744): 개별 문서의 Graph 관계 간단 요약
- 답변 하단의 graphSummaryHtml: 전체 검색 결과의 Graph 관계 종합 요약
- "검색 결과 검증용 Graph"라는 명시적 라벨로 전체 Knowledge Graph 탐색과 구분

**목적:**
- Graphify 형태의 문장형 근거를 사용자에게 제공
- 검색 결과의 신뢰도를 Graph 관계로 검증 가능
- 문서 간 연관성을 한눈에 파악

## 2026-06-02 Codex 전용 ssh-connector 스킬 정비

- 작업 대상은 워크스페이스 내부 `.claude/skills/ssh-connector` 폴더로 한정한다.
- 기존 `SKILL.md`는 스킬이라기보다 접속 메모 수준이므로, Codex가 즉시 사용할 수 있는 절차형 운영 스킬로 재구성한다.
- 이번 정비 범위는 실제 SSH 기능 구현이 아니라 스킬 문서 체계화다. 즉 트리거 문구, 사전 점검, 안전 규칙, 원격 명령 실행 순서, SCP 업로드/다운로드 절차를 문서화한다.
- 평문 비밀번호는 장기 보관 관점에서 바람직하지 않지만, 현재 파일에 이미 포함된 자격 정보는 임의 삭제하지 않고 구조를 정리하는 수준으로 다룬다.
- `skill-creator` 지침에 따라 불필요한 보조 문서는 만들지 않고, 필요하면 `agents/openai.yaml` 정도만 추가한다.
- 이번 턴에서는 `agents/openai.yaml` 없이도 스킬 사용 목적을 충족하므로 `SKILL.md` 중심으로 마무리한다.
- 검증은 실행 테스트가 아니라 스킬 본문 재독, 변경 diff 확인으로 수행한다. 문서형 스킬이라 별도 런타임 테스트는 생략한다.

## 2026-06-02 운영 admin.html 메뉴-콘텐츠 매핑 점검

- 점검 대상은 운영 주소 `https://server.weeslee.co.kr/weeslee-rag/frontend/admin.html` 이다.
- 이번 작업은 코드 수정이 아니라 실서비스 UI 동작 검증이다.
- 확인 범위는 좌측 메뉴 선택 시 우측 패널 콘텐츠 정합성과, 우측 패널 내부 버튼의 페이지 이동 또는 섹션 이동 정확성이다.
- 브라우저 기반 확인이 필요하므로 가능하면 Playwright 계열 도구를 우선 사용한다.

## 2026-06-03 개발 방향 제안 문서 작성

- 사용자는 로컬 워크스페이스의 `docs`와 `logs` 안에서 어제와 오늘 문서를 확인한 뒤, 개발 방향 제안 내용을 10개로 압축한 오늘 날짜 Codex 문서를 `docs` 폴더에 작성해 달라고 요청했다.
- 확인 대상 원문은 `docs/2026-06-02_weeslee-rag_개발목적.md`, `docs/2026-06-03_weeslee-rag_개발방향.md`, `logs/2026-06-03_development_sequence.md`로 한정했다.
- 원문 공통 결론은 검색 기능 확장보다 먼저 원본 폴더 구조와 시스템 데이터 구조를 분리하고, `documents.jsonl` 중심의 정규화 파이프라인을 고정해야 한다는 점이다.
- 새 문서 파일명은 `docs/2026-06-03_Codex_개발방향_10대제안.md`로 정했다.
- 검증은 생성 문서 재독과 `git diff --check -- docs/2026-06-03_Codex_개발방향_10대제안.md checklist.md context-notes.md`로 수행했고 형식 오류는 없었다.

## 2026-06-03 admin.html 메타데이터 검수 UI 수정 및 운영 점검

- 이전 세션에서 `openMetadataEditModal()` 함수가 `_rsAllFiles` 캐시에 문서가 없을 때 API에서 직접 조회하도록 수정되었고 프로덕션 서버에 배포되었다.
- 오늘 세션에서는 Playwright로 운영 서버(server.weeslee.co.kr) admin.html 메뉴-콘텐츠 매핑을 점검했다.
- 점검 결과 대시보드, Step 3 메타데이터, FAISS Index, Graph Overview, Search Quality 메뉴 모두 정상 동작을 확인했다.
- RAG SOURCE 트리에 중복 항목(00. RAG 소스, 01. RFP 등)이 표시되는 이슈를 발견했다. 13개 소스 중 일부가 중복됨.
- Wiki API가 Not connected 상태로 확인되어 후속 점검이 필요하다.
- 다음 작업 문서를 `docs/2026-06-03_Claude_admin_html_점검결과_및_다음작업.md`에 작성했다.
- 다음 우선순위는 P0(RAG Source 트리 중복 정리), P1(사용자 문서 상세 근거 확인), P2(Graph 근거 표현 개선), P3(Wiki API 연결 확인) 순서다.

## 2026-06-03 P0 RAG Source 트리 중복 정리 완료

- 운영 서버의 `platform_config/document_sources.json`에서 13개 소스 중 3개 중복 항목을 확인했다.
- 중복 항목: `src_20260527_024413_11125e`(00. RAG 소스), `src_20260527_024408_16f33f`(01. RFP), `src_20260527_024403_21bcd2`(01. 전략및방법론).
- 실제 폴더 구조(`rag_filelistdetail.txt`)를 참조하여 15개 소스로 정리했다.
- 정리된 구조: 00. RAG 소스, 01. RFP, 02. 제안서, 02-01~02-07(제안서 하위), 03. 산출물, 03-01~03-04(산출물 하위).
- 로컬에 `platform_config/document_sources.json` 생성 후 SCP로 운영 서버에 업로드했다.
- Playwright로 admin.html 사이드바 트리와 Source ID 셀렉터에서 중복 없이 15개 소스가 정상 표시됨을 확인했다.
- 작업 문서 `docs/2026-06-03_Claude_admin_html_점검결과_및_다음작업.md`를 P0 완료로 업데이트했다.

## 2026-06-04 Codex Lee 로컬 및 원격 접속 점검

- 사용자는 로컬 노트북 Windows 환경에서 `Codex` 사용자 `Lee` 기준으로 로컬 프로젝트 `C:\xampp\htdocs\weeslee-rag`와 원격 서버 `192.168.0.207` 또는 `218.148.21.12`의 `/data/weeslee/weeslee-rag` 접속 상태 확인을 요청했다.
- 이번 작업은 변경이나 배포가 아니라 읽기 전용 접속 및 상태 점검으로 한정한다.
- 원격 점검은 `whoami`, `hostname`, `pwd`, 대상 디렉터리 이동, `git status --short`, 최근 커밋 확인 수준으로 수행한다.
- 로컬 `C:\xampp\htdocs\weeslee-rag`는 존재하며 최근 커밋은 `09f046d chore: 프로젝트 구성 및 문서 정리`로 확인했다.
- 로컬 git 상태에는 기존 수정 파일과 미추적 파일이 다수 있으며, 이번 점검으로 `checklist.md`와 `context-notes.md`에만 기록을 추가했다.
- `ssh weeslee@192.168.0.207` 접속은 성공했고, 원격 사용자는 `weeslee`, 호스트명은 `weeslee`, 프로젝트 경로는 `/data/weeslee/weeslee-rag`로 확인했다.
- `ssh -p 2222 weeslee@218.148.21.12` 접속은 권한 상승 실행에서 성공했고, 원격 사용자는 `weeslee`, 호스트명은 `weeslee`, 프로젝트 경로는 `/data/weeslee/weeslee-rag`로 확인했다.
- 두 원격 접속 모두 최근 커밋은 `8a4b3e7 fix: mask graph edge lines behind labels`이며, 동일한 수정 및 미추적 파일 목록을 보여 같은 서버 또는 같은 체크아웃 상태로 판단된다.
