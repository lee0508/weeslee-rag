# Phase 9. Codex 구현 체크리스트

## 1. 문서 개요

이 문서는 Claude 설계안을 실제 구현 상태 기준으로 다시 점검한 체크리스트다.
2026-05-27 현재 코드는 초기 Phase 9 설계와 다르게 `Document Source source_id` 중심의 Dataset Builder 흐름으로 정리되고 있다.

상태 표기는 다음 기준을 사용한다.

- `[x]` 완료 또는 현재 코드에 구현됨.
- `[ ]` 미완료 또는 별도 구현 필요.
- `부분 완료`는 항목 설명에 명시한다.

## 2. 현재 구현 핵심 결정

- Dataset Builder의 내부 작업 기준은 `source_id`다.
- 화면에는 `source_name`을 보여주고, API와 산출물 metadata에는 `source_id`를 저장한다.
- Document Source 목록의 `Dataset 생성` 버튼은 해당 `source_id`를 `ctxSource`에 선택한 뒤 Dataset Builder로 이동한다.
- Step 5는 OCR/텍스트 추출과 청킹까지만 수행한다.
- Step 6은 임베딩, Vector, FAISS 생성만 수행한다.
- GraphRAG와 LLM Wiki는 Step 5/6과 분리된 후속 단계로 다룬다.
- Step 5 산출물은 사용자 페이지의 문서 전체 보기와 요약 보기에서 재사용한다.

## 2.1 관리자 시점 개발 방향 반영

`docs/2026-05-27_관리자시점_개발방향.md`의 운영 흐름을 Phase 9의 상위 기준으로 반영한다.

1. 문서 등록 구조 확정.
2. 문서 전처리 파이프라인 안정화.
3. 구조 기반 청킹.
4. FAISS/RAG 생성.
5. LLM Wiki 생성.
6. Graphify/GraphRAG 생성.

현재 구현은 1~4단계의 기반이 진행 중이고, 5~6단계는 source_id 기준 실행 검증과 UI 정리가 남아 있다.

## 3. rag-assistant.html 구현 체크리스트

### 3.1 질문 입력 영역 (P0)

- [x] 검색어 입력 및 검색 실행.
- [x] 검색 모드 선택 UI.
- [x] 문서 그룹 필터.
- [x] Top K, Top Docs, Max Chunks 설정.
- [x] Enter 키 검색.
- [ ] 최소 점수 필터 UI.

완료 조건: 검색 모드와 필터를 선택하고 검색을 실행할 수 있다.

### 3.2 프롬프트 분석 패널 (P1)

- [x] `/api/rag/analyze-prompt` 호출.
- [x] intent, keywords, organization, suggested filters 표시.
- [ ] suggested_filters 자동 적용 버튼.
- [ ] confidence 점수 UI 정리.

완료 조건: 검색 시 프롬프트 분석 결과가 표시된다.

### 3.3 검색 결과 탭 (P0)

- [x] RAG, Agent, Graph, Wiki 패널 구조.
- [x] 문서 카드 렌더링.
- [x] 제목, 점수, 메타데이터, 매칭 텍스트 일부 표시.
- [x] 문서 선택 체크박스.
- [ ] 4개 모드 결과를 완전한 독립 탭 결과로 분리.
- [ ] 결과 정렬 옵션.

완료 조건: 검색 결과 문서와 주요 메타데이터를 확인할 수 있다.

### 3.4 RAG Agent 결과 표시 (P1)

- [x] Agent 패널 기본 구조.
- [x] 프롬프트 분석 기반 결과 표시 일부.
- [ ] strategy, tools_used, reasoning, agent_score 표시 정리.

완료 조건: Agent 검색 시 전략과 도구 정보가 표시된다.

### 3.5 Graph RAG 결과 표시 (P1)

- [x] Graph 패널 기본 구조.
- [x] Graph API와 일부 연결.
- [x] Graph summary, project/document/edge 통계 일부 표시.
- [ ] graph_path 노드-엣지 시각화 고도화.
- [ ] 노드 클릭 시 관련 문서 필터링.

완료 조건: Graph 검색 시 관계 경로가 표시된다.

### 3.6 LLM Wiki 결과 표시 (P1)

- [x] Wiki 패널 기본 구조.
- [x] Wiki 상세 미리보기 일부.
- [ ] Wiki 검색 결과 카드 정리.
- [ ] related_documents 링크 정리.
- [ ] wiki_type 배지.

완료 조건: Wiki 검색 결과가 표시되고 미리보기가 가능하다.

### 3.7 통합 추천 문서 리스트 (P0)

- [x] 검색 결과 문서 리스트.
- [x] document_id 기준 문서 선택.
- [x] 체크박스 기반 선택 문서 관리.
- [ ] 4개 모드 결과 병합 로직.
- [ ] 중복 제거와 merged_score 계산.
- [ ] sources 표시.

완료 조건: 통합 추천 리스트에서 문서를 선택할 수 있다.

### 3.8 문서 상세 및 미리보기 (P0)

- [x] 문서 클릭 시 상세 패널 표시.
- [x] `openFilePreview()`로 전체 문서 미리보기.
- [x] HTML 콘텐츠 iframe 렌더링.
- [x] Markdown/TXT 콘텐츠 렌더링.
- [x] 요약 탭 연결.
- [x] `/api/documents/{document_id}` 상세 API 연결.
- [x] `/api/documents/{document_id}/html`, `/markdown`, `/text`, `/summary` 연결.
- [ ] 상세 패널 내부를 원문/요약/메타데이터 3개 탭으로 정리.
- [ ] 핵심 포인트 UI.

완료 조건: 문서 상세 정보를 원문, 요약, 메타데이터 기준으로 확인할 수 있다.

### 3.9 편집/다운로드 기능 (P2)

- [x] 원본 다운로드.
- [x] TXT/MD/HTML/요약/JSON 다운로드 API.
- [x] `/api/documents/{document_id}/edit` API.
- [ ] 사용자 페이지 인라인 에디터 UI.
- [ ] 다운로드 드롭다운 UI.

완료 조건: 문서 메타데이터 편집과 다운로드가 가능하다.

### 3.10 Grounded Answer 생성 (P0)

- [x] 선택 문서 목록 수집.
- [x] 선택 문서 기반 답변 생성 UI 틀.
- [ ] 실제 generate-answer API 연동.
- [ ] SSE 스트리밍 응답 표시.
- [ ] citation 클릭 시 문서/청크 이동.

완료 조건: 선택 문서 기반 grounded answer가 생성되고 인용이 표시된다.

### 3.11 API Fallback 처리 (P1)

- [x] 주요 검색 API 실패 메시지 표시.
- [x] 일부 offline/mock 흐름.
- [ ] 모드별 타임아웃 정책.
- [ ] 재시도 버튼.
- [ ] 부분 성공 결과 표시 정책.

완료 조건: API 실패 시 사용자에게 적절한 피드백이 제공된다.

## 4. admin.html 구현 체크리스트

### 4.1 Document Source 관리 (P0)

- [x] Document Source 등록.
- [x] 접근 테스트.
- [x] 스캔 미리보기와 DB 저장.
- [x] 기존 Document Source 목록 표시.
- [x] `source_id` 자동 생성.
- [x] 한글 source_name 표시와 내부 source_id 분리.
- [x] 기존 Source를 새 source_id로 복제.
- [x] `Dataset 생성` 버튼 클릭 시 해당 Source가 Dataset Builder에 자동 선택.
- [ ] 프로젝트명, 발주기관, 문서유형, 연도, 제안/수행/완료/발표자료 구분 입력 체계 정리.
- [ ] 태그와 메타데이터 입력/검수 흐름 정리.

완료 조건: Source별 Dataset Builder 작업 대상을 안정적으로 선택할 수 있다.

### 4.2 Dataset Builder 컨텍스트 (P0)

- [x] 현재 작업 대상 바.
- [x] `ctxSource` 셀렉트가 `source_id`를 value로 보관.
- [x] Source 선택 시 Snapshot 목록 갱신.
- [x] Step 실행 시 선택 Source의 source_id 사용.

완료 조건: 모든 Dataset Builder 단계가 선택 Source 기준으로 실행된다.

### 4.3 Step 1 파일 스캔 (P0)

- [x] `/api/admin/rag-source/scan` 연동.
- [x] Document Source mount path 기준 scan.
- [x] documents 테이블에 파일 목록 저장.
- [ ] 신규/수정/삭제 대상만 Dataset Builder 실행 대상으로 넘기는 UI 고도화.

완료 조건: Source 폴더를 스캔하고 파일 목록을 DB에 저장할 수 있다.

### 4.4 Step 2 Collection 메타 동기화 (P0)

- [x] `weeslee_rag_main` 단일 Collection 메타 동기화.
- [x] 전체 순차 실행에서는 자동 제외.
- [ ] Source별 Collection을 만들지 않는다는 정책 문서화 보강.

완료 조건: 단일 Collection과 metadata filter 정책이 유지된다.

### 4.5 Step 3 Metadata 생성 (P0)

- [x] `/api/admin/rag-source/metadata/build` 연동.
- [x] `source_id` 요청 반영.
- [x] Document Source 경로 기준 문서 필터링.
- [x] 응답과 JSONL row에 `source_id`, `source_name` 포함.
- [ ] Metadata 생성 결과 검수 UI 고도화.

완료 조건: 선택 Source의 문서만 metadata 생성 대상으로 처리된다.

### 4.6 Step 4 Tag/Keyword 생성 (P1)

- [x] 기본 Tag bootstrap.
- [x] Keyword extract.
- [ ] Source별 tag/keyword 생성 범위 정책 정리.

완료 조건: 기본 Tag와 Keyword를 생성할 수 있다.

### 4.7 Step 5 OCR 작업 + 청킹 시작 (P0)

- [x] `/api/admin/faiss/jobs` 기반 비동기 job 실행.
- [x] `end_stage=3`으로 manifest, OCR/텍스트 추출, 청킹까지만 실행.
- [x] manifest에 `source_id`, `source_name`, `document_id` 포함.
- [x] OCR/텍스트 추출 metadata에 `source_id`, `source_name` 포함.
- [x] chunk metadata에 `source_id`, `source_name` 포함.
- [x] Step 5 실패 시 `OCR/청킹 실패` 메시지 표시.
- [x] XLSX Data Validation 경고 억제.
- [x] 기존 추출 산출물 재사용 증분 처리.
- [ ] 파일별 진행 로그 개선.
- [ ] 성공/스킵/실패 수 실시간 표시.
- [ ] OCR 사용 여부 표시.
- [ ] OCR 필요 여부 판단 결과를 문서별 metadata에 명확히 저장.
- [ ] 페이지별 OCR 결과 저장.
- [ ] 실패 로그 저장 표준화.
- [ ] 재처리 버튼 제공.

완료 조건: 선택 Source 기준으로 OCR/텍스트 추출과 청킹까지만 완료된다.

#### 4.7.1 OCR/Parser 서버 의존성 체크리스트 (P0)

- [x] Python OCR fallback 패키지를 `backend/requirements.txt`에 명시.
  - `pytesseract>=0.3.13`
  - `pdf2image>=1.17.0`
  - `Pillow>=10.0.0`
- [x] 서버 `.venv` 기준 `pip install -r backend/requirements.txt` 실행 확인.
- [x] HWP 직접 추출 도구 `.venv/bin/hwp5txt` 설치 확인.
- [x] 시스템 OCR 명령 `tesseract` 설치 확인.
- [x] Tesseract 언어팩 `kor`, `eng`, `osd` 설치 확인.
- [x] PDF 이미지 변환용 `poppler-utils` 명령 `pdftoppm`, `pdftocairo` 설치 확인.
- [x] 확장자가 `.hwp`여도 내부가 HWPX(ZIP/XML)인 파일은 `HwpxExtractor` fallback으로 처리.
- [x] 샘플 90개 기준 OCR/Parser 결과 `done=90`, `failed=0`, `text_length<500=0` 확인.
- [ ] 신규 서버 설치 문서에 `apt install tesseract-ocr tesseract-ocr-kor poppler-utils` 항목 반영.

### 4.7.2 구조 기반 청킹 고도화 (P1)

- [x] 기본 section heading 감지와 chunk_id 생성.
- [x] 원본 파일 경로와 metadata 유지.
- [ ] 제목, 소제목, 본문, 표, 이미지 구분.
- [ ] 페이지 번호 유지.
- [ ] 페이지별 metadata.json 저장 정책.
- [ ] 표와 이미지 설명 텍스트 처리 정책.

완료 조건: 청크가 문서 구조와 페이지 출처를 유지한다.

### 4.8 Step 6 임베딩 + Vector + FAISS 진행 (P0)

- [x] `/api/admin/faiss/jobs` 기반 별도 job 실행.
- [x] `start_from_stage=4`, `end_stage=5`로 임베딩/FAISS 단계 분리.
- [x] Step 5 완료 snapshot 재사용.
- [x] 실패 시 `임베딩/FAISS 실패` 메시지 표시.
- [ ] FAISS metadata source_id 검증 UI.
- [ ] 처리 속도와 예상 남은 시간 표시.
- [ ] 문서 대분류/세부분류 기준 인덱스 생성 정책 확정.
- [ ] 카테고리별 Collection 생성 요구와 현재 단일 Collection 정책의 차이 정리.

완료 조건: Step 5에서 생성한 chunk를 입력으로 FAISS 인덱스를 생성한다.

### 4.9 Graph RAG 단계 (P1)

- [x] Graph build API 존재.
- [x] source_id별 graph 디렉토리 구조 일부 지원.
- [x] Dataset Builder에 Graph 생성 단계 존재.
- [ ] Step 6과 완전 분리된 운영 플로우 정리.
- [ ] source_id 전달 UI/API 검증.
- [ ] Graph 시각화 고도화.
- [ ] 기관, 사업, 문서, 기술, 인력, 실적 관계 모델 정리.
- [ ] 나라장터 신규 공고와 기존 실적 매칭 흐름 설계.

완료 조건: 선택 Source 기준 GraphRAG를 생성하고 조회할 수 있다.

### 4.10 LLM Wiki 단계 (P1)

- [x] Wiki build API 존재.
- [x] source_id별 Wiki 디렉토리 구조 일부 지원.
- [x] Dataset Builder에 LLM Wiki 생성 단계 존재.
- [ ] Source별 Wiki 생성/조회 UI 정리.
- [ ] Wiki 생성 상태 목록.
- [ ] Wiki 미리보기/편집 UI 고도화.
- [ ] 기관별 Wiki.
- [ ] 프로젝트별 Wiki.
- [ ] 기술분야별 Wiki.
- [ ] 수행실적 Wiki.
- [ ] 제안서 작성용 Wiki.

완료 조건: 선택 Source 기준 Wiki를 생성하고 목록에서 확인할 수 있다.

### 4.11 Jobs 탭 (P0)

- [x] Jobs 페이지와 Legacy Jobs 탭.
- [x] `/api/admin/faiss/jobs` 목록 조회.
- [x] SSE job stream.
- [x] running/completed/failed 요약.
- [ ] Job 상세 모달.
- [ ] 재시도/취소 버튼.
- [ ] source_id 필터.

완료 조건: Job 목록을 조회하고 진행 상태를 확인할 수 있다.

### 4.12 Logs 탭 (P2)

- [x] Query Logs 탭.
- [x] `/api/admin/query-logs` 조회.
- [x] `/api/admin/query-logs/summary` 조회.
- [ ] 처리 로그와 에러 로그 통합.
- [ ] 로그 상세 모달.

완료 조건: 주요 질의 로그와 실패 로그를 조회할 수 있다.

### 4.13 Settings 탭 (P1)

- [x] Settings 페이지 기본 틀.
- [ ] 저장소 설정 저장.
- [ ] RAG/LLM/Graph 설정 저장.
- [ ] 설정 API 또는 localStorage 정책 확정.

완료 조건: 시스템 설정을 변경하고 저장할 수 있다.

### 4.14 Search Quality 탭 (P2)

- [x] Search Quality 페이지 기본 틀.
- [x] 기존 Benchmark 탭 연결.
- [x] 간단 검색 테스트 UI.
- [ ] Precision, Recall, F1 표시.
- [ ] 모드별 품질 비교.

완료 조건: 검색 품질을 테스트하고 결과를 확인할 수 있다.

## 5. Backend API 구현 체크리스트

### 5.1 사용자 문서 조회 API (P0)

- [x] `GET /api/documents/{document_id}`.
- [x] `GET /api/documents/{document_id}/text`.
- [x] `GET /api/documents/{document_id}/html`.
- [x] `GET /api/documents/{document_id}/markdown`.
- [x] `GET /api/documents/{document_id}/summary`.
- [x] `POST /api/documents/{document_id}/edit`.
- [x] `GET /api/documents/{document_id}/download`.

완료 조건: 사용자 페이지에서 문서 원문, 요약, metadata, 다운로드를 사용할 수 있다.

### 5.2 사용자 검색 API (P0)

- [x] `POST /api/rag/similar-files`.
- [x] `POST /api/rag/analyze-prompt`.
- [ ] `POST /api/search/rag`.
- [ ] `POST /api/search/rag-agent`.
- [ ] `POST /api/search/graph-rag`.
- [ ] `POST /api/search/llm-wiki`.
- [ ] `POST /api/search/all`.
- [ ] `POST /api/rag-assistant/generate-answer` SSE.

완료 조건: 설계상의 4개 검색 모드 API가 정리된다.

### 5.3 관리자 데이터 생성 API (P0)

- [x] `GET/POST /api/admin/document-sources`.
- [x] `POST /api/admin/document-sources/{source_id}/test`.
- [x] `POST /api/admin/document-sources/{source_id}/scan`.
- [x] `POST /api/admin/rag-source/scan`.
- [x] `POST /api/admin/rag-source/metadata/build`.
- [x] `POST /api/admin/faiss/jobs`.
- [x] `GET /api/admin/faiss/jobs`.
- [x] `GET /api/admin/faiss/jobs/{job_id}/stream`.
- [x] `GET /api/admin/faiss/staged-summary`.
- [x] `POST /api/graph/build`.
- [x] `POST /api/wiki/build`.
- [ ] Job retry/cancel API.
- [ ] Summary generation 전용 API.

완료 조건: Dataset Builder 각 단계가 API로 실행된다.

### 5.4 백엔드 서비스 (P0)

- [x] 규칙 기반 Prompt 분석 일부.
- [x] GraphTraversalService 기본 구조.
- [x] Wiki build/search 일부.
- [x] FAISS job runner.
- [x] source_id 기반 manifest/OCR/chunk metadata.
- [ ] MergedRecommendationService.
- [ ] GroundedAnswerService.

완료 조건: 검색과 답변 생성 서비스가 설계대로 동작한다.

## 6. 저장소 구조 구현 체크리스트

### 6.1 디렉토리 구조 (P0)

- [x] `data/extracted_text/{document_id}`.
- [x] `data/staged/manifest`.
- [x] `data/staged/text`.
- [x] `data/staged/metadata`.
- [x] `data/staged/chunks`.
- [x] `data/indexes/faiss`.
- [x] `data/indexes/graph/{source_id}` 일부.
- [x] `data/wiki/{source_id}/projects` 일부.
- [ ] `data/summaries/{document_id}/summary.md` 자동 생성 플로우.

완료 조건: Step 5/6 산출물과 사용자 문서 보기 산출물이 분리 저장된다.

### 6.2 매니페스트와 산출물 관리 (P0)

- [x] manifest CSV/JSONL 생성.
- [x] extraction summary CSV 생성.
- [x] chunks JSONL 생성.
- [x] FAISS metadata JSONL 생성.
- [x] pipeline state JSON 생성.
- [ ] errors JSONL 또는 실패 파일 관리 표준화.
- [ ] jobs 영속화.

완료 조건: 파이프라인 산출물을 재실행과 증분 처리에 사용할 수 있다.

## 7. 남은 작업 우선순위

### 7.1 즉시 진행 권장

1. Step 5 진행 로그 개선.
2. Document Source 변경 감지 결과와 Step 5 증분 대상 연결 확인.
3. Step 6 FAISS metadata의 `source_id` 검증 UI 추가.
4. GraphRAG build에 `source_id` 전달 여부 실제 실행 검증.
5. LLM Wiki build에 `source_id` 전달 여부 실제 실행 검증.
6. OCR 필요 여부, 페이지별 결과, 실패 로그, 재처리 버튼 설계.

### 7.2 다음 단계

1. 사용자 페이지 문서 상세 패널을 원문/요약/메타데이터 탭으로 정리.
2. 선택 문서 기반 Grounded Answer API와 SSE 구현.
3. 검색 모드별 API를 `/api/search/*` 계열로 정리할지 기존 `/api/rag/*`를 유지할지 결정.
4. Jobs retry/cancel과 영속화.
5. Search Quality 지표 고도화.
6. 구조 기반 청킹에서 제목, 소제목, 본문, 표, 이미지, 페이지 번호를 유지.

## 8. 필수 완료 항목 현황

- [x] Dataset Builder 기본 동작.
- [x] Document Source 기반 source_id 흐름.
- [x] Step 5 OCR/텍스트 추출/청킹.
- [x] Step 6 임베딩/FAISS 분리.
- [x] 문서 상세 원문/요약 조회 API.
- [x] 사용자 문서 미리보기.
- [ ] 4개 모드 검색 완성.
- [ ] 통합 추천 문서 리스트 완성.
- [ ] Grounded Answer 생성과 citations.
- [ ] Jobs retry/cancel.
- [ ] GraphRAG/Wiki source_id 실행 검증.

## 9. 검증 방법

1. Document Source 목록에서 `Dataset 생성` 클릭 시 Dataset Builder `ctxSource`가 해당 Source로 자동 선택되는지 확인한다.
2. Step 1 실행 후 documents에 해당 Source 파일만 저장되는지 확인한다.
3. Step 3 실행 후 해당 Source 경로 문서만 metadata 생성되는지 확인한다.
4. Step 5 실행 후 `data/extracted_text/{document_id}`와 `data/staged/chunks/{snapshot}_chunks.jsonl`이 생성되는지 확인한다.
5. Step 5 재실행 시 기존 산출물이 `skipped_existing`으로 처리되는지 확인한다.
6. Step 6 실행 후 FAISS metadata에 `source_id`, `source_name`, `document_id`가 유지되는지 확인한다.
7. 사용자 페이지에서 검색 결과 문서를 클릭해 HTML/Markdown/TXT/요약 탭이 열리는지 확인한다.
8. GraphRAG와 LLM Wiki가 선택 Source 기준으로 생성되는지 확인한다.
9. OCR 실패 파일이 실패 로그와 재처리 대상으로 남는지 확인한다.
10. 페이지 번호와 원본 경로가 chunk metadata에 유지되는지 확인한다.

---

작성일: 2026-05-21
최종 업데이트: 2026-05-27
작성자: Claude 설계, Codex 구현 상태 반영
상태: 구현 진행 중
