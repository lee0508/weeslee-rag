# Phase 9. Codex 구현 체크리스트

## 1. 문서 개요

이 문서는 Claude 설계를 기반으로 Codex가 실제 구현할 체크리스트를 작성한다.
우선순위와 완료 조건을 명시하여 구현 진행을 추적한다.

## 2. 우선순위 정의

| 우선순위 | 설명 | 기준 |
| --- | --- | --- |
| P0 | 필수 | 시스템 동작에 필수적 |
| P1 | 높음 | 핵심 기능 |
| P2 | 중간 | 편의 기능 |
| P3 | 낮음 | 추가 기능 |

## 3. rag-assistant.html 구현 체크리스트

### 3.1 질문 입력 영역 (P0)

- [ ] 검색 모드 Chips 추가 (RAG, Agent, Graph, Wiki, 전체)
- [ ] 검색 필터 UI 추가 (연도, 발주기관, 문서유형)
- [ ] Top K, 최소 점수 설정 슬라이더
- [ ] 검색 버튼 및 Enter 키 검색

**완료 조건**: 검색 모드와 필터를 선택하고 검색을 실행할 수 있다.

### 3.2 프롬프트 분석 패널 (P1)

- [ ] Right Panel에 프롬프트 분석 결과 영역 추가
- [ ] intent, keywords, organization 표시
- [ ] suggested_filters 자동 적용 버튼
- [ ] confidence 점수 표시

**완료 조건**: 검색 시 프롬프트 분석 결과가 표시된다.

### 3.3 검색 결과 탭 (P0)

- [ ] 4개 탭 UI 추가 (RAG, Agent, Graph, Wiki)
- [ ] 각 탭별 결과 카드 리스트 렌더링
- [ ] 문서 카드: 제목, 점수, 매칭 텍스트, 메타데이터
- [ ] 하이라이트 텍스트 표시
- [ ] 결과 정렬 옵션 (점수순, 날짜순)

**완료 조건**: 4개 모드 검색 결과가 각 탭에 표시된다.

### 3.4 RAG Agent 결과 표시 (P1)

- [ ] strategy 정보 표시 (전략명, 설명)
- [ ] tools_used 배지 표시
- [ ] reasoning 텍스트 표시
- [ ] agent_score와 일반 score 비교 표시

**완료 조건**: Agent 검색 시 전략과 도구 정보가 표시된다.

### 3.5 Graph RAG 결과 표시 (P1)

- [ ] graph_path 시각화 (간단한 노드-엣지 표시)
- [ ] connected_entities 리스트 표시
- [ ] path_length 표시
- [ ] 노드 클릭 시 관련 문서 필터링

**완료 조건**: Graph 검색 시 관계 경로가 표시된다.

### 3.6 LLM Wiki 결과 표시 (P1)

- [ ] Wiki 카드 (제목, 요약, 관련 문서 수)
- [ ] Wiki 미리보기 모달
- [ ] related_documents 링크
- [ ] wiki_type 배지 (organization, technology)

**완료 조건**: Wiki 검색 결과가 표시되고 미리보기가 가능하다.

### 3.7 통합 추천 문서 리스트 (P0)

- [ ] 4개 모드 결과 병합 로직 (프론트엔드)
- [ ] 중복 제거 (document_id 기준)
- [ ] merged_score 계산 (가중 평균)
- [ ] sources 표시 (RAG 0.92, Graph 0.85 형식)
- [ ] 체크박스로 문서 선택

**완료 조건**: 통합 추천 리스트에서 문서를 선택할 수 있다.

### 3.8 문서 상세 패널 (P0)

- [ ] 문서 클릭 시 상세 패널 슬라이드 인
- [ ] 원문/요약/메타데이터 탭
- [ ] HTML 콘텐츠 렌더링 (iframe 또는 div)
- [ ] Markdown 콘텐츠 렌더링
- [ ] 요약 텍스트 및 핵심 포인트 표시
- [ ] 메타데이터 표 (발주기관, 연도, 태그)

**완료 조건**: 문서 상세 정보를 3개 탭으로 확인할 수 있다.

### 3.9 편집/다운로드 기능 (P2)

- [ ] 편집 버튼 → 인라인 에디터 활성화
- [ ] 다운로드 드롭다운 (PDF, TXT, MD, DOCX)
- [ ] 다운로드 API 호출 및 파일 저장

**완료 조건**: 문서 메타데이터 편집과 다운로드가 가능하다.

### 3.10 Grounded Answer 생성 (P0)

- [ ] "선택 문서 기반 답변 생성" 버튼
- [ ] 선택된 문서 ID 목록 수집
- [ ] generate-answer API 호출
- [ ] 스트리밍 응답 표시 (SSE)
- [ ] 답변 + citations 렌더링
- [ ] citation 클릭 시 해당 문서/청크로 이동

**완료 조건**: 선택 문서 기반 grounded answer가 생성되고 인용이 표시된다.

### 3.11 API Fallback 처리 (P1)

- [ ] 각 검색 모드별 타임아웃 처리
- [ ] 에러 시 해당 탭에 에러 메시지 표시
- [ ] 재시도 버튼
- [ ] 부분 성공 시 성공한 결과만 표시

**완료 조건**: API 실패 시 사용자에게 적절한 피드백이 제공된다.

---

## 4. admin.html 구현 체크리스트

### 4.1 RAG Build Wizard 탭 (P0)

- [ ] 새 탭 추가: "RAG Build Wizard"
- [ ] Stepper UI 컴포넌트 구현
- [ ] 9단계 상태 관리 (current, completed, pending)
- [ ] 단계 전환 로직

**완료 조건**: Stepper를 통해 각 단계를 순차적으로 진행할 수 있다.

### 4.2 Step 1: Storage Check (P0)

- [ ] 저장소 경로 입력 필드
- [ ] 연결 테스트 버튼
- [ ] 상태 표시 (연결됨/연결 실패)
- [ ] 용량 정보 표시

**완료 조건**: 저장소 연결 상태를 확인할 수 있다.

### 4.3 Step 2: Folder Scan (P0)

- [ ] 폴더 트리 UI (체크박스)
- [ ] 파일 유형 필터 체크박스
- [ ] 하위 폴더 포함 옵션
- [ ] 스캔 시작 버튼
- [ ] 스캔 결과 표시 (총 파일 수, 신규/수정/동일)

**완료 조건**: 폴더를 스캔하고 파일 목록을 확인할 수 있다.

### 4.4 Step 3: Preprocess (P0)

- [ ] 전처리 시작 버튼
- [ ] 진행률 바
- [ ] 현재 처리 중인 파일 표시
- [ ] 처리 로그 영역 (스크롤)
- [ ] 일시정지/건너뛰기/취소 버튼

**완료 조건**: 전처리 진행 상황을 실시간으로 확인할 수 있다.

### 4.5 Step 4: Text Extraction (P0)

- [ ] 추출 옵션 (HTML, MD, OCR)
- [ ] 진행률 바
- [ ] 파일 유형별 통계 표시
- [ ] 실패 목록 펼치기/접기

**완료 조건**: 텍스트 추출 결과와 실패 항목을 확인할 수 있다.

### 4.6 Step 5: Chunking (P1)

- [ ] 청크 크기/오버랩 설정 드롭다운
- [ ] 분할 방식 라디오 버튼
- [ ] 진행률 바
- [ ] 결과 통계 (총 청크, 평균/최소/최대 크기)

**완료 조건**: 청킹 설정을 변경하고 결과를 확인할 수 있다.

### 4.7 Step 6: Embedding (P1)

- [ ] 임베딩 모델 선택 드롭다운
- [ ] 배치 크기 설정
- [ ] 진행률 바
- [ ] 예상 남은 시간 표시
- [ ] 처리 속도 표시
- [ ] Ollama 연결 상태 표시

**완료 조건**: 임베딩 진행 상황과 Ollama 상태를 확인할 수 있다.

### 4.8 Step 7: FAISS Build (P1)

- [ ] Collection 이름 입력
- [ ] 인덱스 타입 라디오 버튼
- [ ] 덮어쓰기 옵션 체크박스
- [ ] 빌드 진행률 바
- [ ] 결과 (벡터 수, 인덱스 크기, 빌드 시간)

**완료 조건**: FAISS 인덱스를 빌드하고 결과를 확인할 수 있다.

### 4.9 Step 8: Summary Generation (P2)

- [ ] 요약 모델 선택
- [ ] 요약 길이 라디오 버튼
- [ ] 핵심 포인트 추출 옵션
- [ ] 진행률 바
- [ ] 예상 남은 시간

**완료 조건**: 문서 요약을 생성할 수 있다.

### 4.10 Step 9: Complete (P0)

- [ ] 빌드 요약 표시
- [ ] 다음 단계 버튼 (Graph RAG, Wiki, 검색 테스트)
- [ ] 대시보드로 이동 버튼

**완료 조건**: 빌드 완료 후 다음 작업으로 이동할 수 있다.

### 4.11 Graph RAG 탭 (P1)

- [ ] 새 탭 추가: "Graph RAG"
- [ ] 노드 유형 체크박스
- [ ] 관계 추출 모델 선택
- [ ] 빌드 시작 버튼
- [ ] 그래프 시각화 영역 (D3.js 또는 vis.js)
- [ ] 노드/엣지 통계 표시

**완료 조건**: Graph RAG를 빌드하고 시각화를 확인할 수 있다.

### 4.12 LLM Wiki 탭 (P1)

- [ ] 새 탭 추가: "LLM Wiki"
- [ ] 생성 단위 체크박스 (발주기관, 기술 등)
- [ ] Wiki 모델 선택
- [ ] 요약 길이 라디오
- [ ] Wiki 생성 버튼
- [ ] Wiki 목록 (생성 상태 표시)
- [ ] Wiki 미리보기/편집 버튼

**완료 조건**: Wiki를 생성하고 목록에서 확인할 수 있다.

### 4.13 Jobs 탭 (P0)

- [ ] 새 탭 추가: "Jobs"
- [ ] Job 목록 테이블 (ID, 유형, 상태, 진행률, 시간)
- [ ] 필터 (상태, 날짜)
- [ ] Job 상세 모달
- [ ] 재시도/취소 버튼
- [ ] 로그 보기 버튼

**완료 조건**: Job 목록을 조회하고 상세 정보를 확인할 수 있다.

### 4.14 Logs 탭 (P2)

- [ ] 새 탭 추가: "Logs"
- [ ] 에러 로그 목록
- [ ] 로그 레벨 필터
- [ ] 검색 기능
- [ ] 로그 상세 모달

**완료 조건**: 처리 로그와 에러를 조회할 수 있다.

### 4.15 Settings 탭 (P1)

- [ ] 새 탭 추가: "Settings"
- [ ] 저장소 설정 섹션
- [ ] RAG 설정 섹션
- [ ] LLM 설정 섹션
- [ ] Graph RAG 설정 섹션
- [ ] 저장/초기화 버튼
- [ ] 설정값 영속화 (localStorage 또는 API)

**완료 조건**: 시스템 설정을 변경하고 저장할 수 있다.

### 4.16 Search Quality 탭 (P2)

- [ ] 새 탭 추가: "Search Quality"
- [ ] 테스트 쿼리 입력
- [ ] 검색 테스트 버튼
- [ ] 모드별 결과 요약
- [ ] 벤치마크 결과 (Precision, Recall, F1)

**완료 조건**: 검색 품질을 테스트하고 결과를 확인할 수 있다.

---

## 5. Backend API 구현 체크리스트

### 5.1 사용자 검색 API (P0)

- [ ] POST /api/rag-assistant/analyze-prompt
- [ ] POST /api/search/rag
- [ ] POST /api/search/rag-agent
- [ ] POST /api/search/graph-rag
- [ ] POST /api/search/llm-wiki
- [ ] POST /api/search/all (병렬 실행)
- [ ] GET /api/documents/{document_id}
- [ ] GET /api/documents/{document_id}/html
- [ ] GET /api/documents/{document_id}/markdown
- [ ] GET /api/documents/{document_id}/summary
- [ ] POST /api/documents/{document_id}/edit
- [ ] GET /api/documents/{document_id}/download
- [ ] POST /api/rag-assistant/generate-answer (SSE)

**완료 조건**: 모든 사용자 검색 API가 Phase 3 설계대로 동작한다.

### 5.2 관리자 데이터 생성 API (P0)

- [ ] GET /api/admin/storage/health
- [ ] POST /api/admin/storage/list-folders
- [ ] POST /api/admin/storage/scan-folder
- [ ] POST /api/admin/preprocess/start
- [ ] POST /api/admin/extract-text/start
- [ ] POST /api/admin/chunk/start
- [ ] POST /api/admin/embed/start
- [ ] POST /api/admin/rag/build
- [ ] POST /api/admin/graph-rag/build
- [ ] POST /api/admin/llm-wiki/build
- [ ] POST /api/admin/summary/generate
- [ ] GET /api/admin/jobs
- [ ] GET /api/admin/jobs/{job_id}
- [ ] POST /api/admin/jobs/{job_id}/retry
- [ ] POST /api/admin/jobs/{job_id}/cancel

**완료 조건**: 모든 관리자 API가 Phase 3 설계대로 동작한다.

### 5.3 백엔드 서비스 (P0)

- [ ] PromptAnalyzer 서비스 (규칙 기반 + LLM)
- [ ] GraphTraversalService 개선 (검색 API 연동)
- [ ] WikiSearchService 구현
- [ ] MergedRecommendationService 구현
- [ ] GroundedAnswerService 구현 (환각 방지 정책 적용)

**완료 조건**: 각 서비스가 설계대로 동작한다.

---

## 6. 저장소 구조 구현 체크리스트

### 6.1 디렉토리 생성 (P0)

- [ ] data/manifests/ 생성
- [ ] data/extracted_text/ 생성
- [ ] data/summaries/ 생성
- [ ] data/indexes/faiss/ 생성
- [ ] data/graph/ 생성
- [ ] data/wiki/ (organizations, projects, technologies)

**완료 조건**: Phase 4 설계대로 디렉토리가 존재한다.

### 6.2 매니페스트 파일 관리 (P0)

- [ ] documents.jsonl 읽기/쓰기 유틸리티
- [ ] chunks.jsonl 읽기/쓰기 유틸리티
- [ ] jobs.jsonl 읽기/쓰기 유틸리티
- [ ] errors.jsonl 쓰기 유틸리티

**완료 조건**: 매니페스트 파일을 CRUD 할 수 있다.

---

## 7. 구현 순서 권장

### Phase A: 핵심 인프라 (1주차)

1. 디렉토리 구조 생성
2. 매니페스트 파일 유틸리티
3. admin.html Jobs 탭 + Job API
4. Storage Check API

### Phase B: RAG 파이프라인 (2주차)

1. Folder Scan API + UI
2. Preprocess API + UI
3. Text Extraction API + UI
4. Chunking API + UI
5. Embedding API + UI
6. FAISS Build API + UI

### Phase C: 검색 기능 (3주차)

1. POST /api/search/rag
2. POST /api/search/all
3. rag-assistant.html 검색 결과 탭
4. 문서 상세 패널
5. Grounded Answer 생성

### Phase D: 고급 기능 (4주차)

1. Graph RAG Build + 검색
2. LLM Wiki Build + 검색
3. Summary Generation
4. Search Quality 탭

### Phase E: 완성도 (5주차)

1. Settings 탭
2. Logs 탭
3. 에러 처리 개선
4. UI 폴리싱

---

## 8. 완료 조건 총괄

### 필수 완료 항목 (P0)

- [ ] RAG Build Wizard 전체 동작
- [ ] 4개 모드 검색 (RAG, Agent, Graph, Wiki)
- [ ] 통합 추천 문서 리스트
- [ ] 문서 상세 (원문/요약/메타)
- [ ] Grounded Answer 생성 + Citations
- [ ] Jobs 모니터링

### 검증 방법

1. **RAG 빌드**: 100개 문서를 스캔 → 전처리 → 추출 → 청킹 → 임베딩 → FAISS 빌드 완료
2. **검색**: "K-water AI 수자원" 검색 시 관련 문서 상위 노출
3. **Grounded Answer**: 선택 문서 기반 답변 생성, citations 정확성 확인
4. **환각 방지**: 문서에 없는 내용 답변 거부 확인

---

작성일: 2026-05-21
작성자: Claude
상태: 설계 완료, Codex 구현 대기
