# 2026-04-27 Front End / Back End 구성 및 실행 계획

## 1. 현재 기준

이 프로젝트의 목적은 공공/민간 입찰의 RFP를 분석하고, 과거 컨설팅 문서를 찾아 제안서 초안을 빠르게 작성하도록 돕는 것이다.

현재 상태는 다음과 같다.

- 원본 문서 표본 복사 및 스냅샷 체계 확보
- 추출/OCR/메타데이터/청킹/FAISS 인덱스 1차 구축
- 실제 RFP 기반 추천 품질 검증 완료
- `proposal` 문서가 실제 RFP 질의에서 1순위로 추천되는 것을 확인

즉, 지금은 기능 추가보다 `구조 정리`, `API 고정`, `화면 분리`가 필요한 단계다.

## 2. 권장 아키텍처

### 2.1 Back End

백엔드는 `FastAPI` 기반의 모듈형 모놀리식 구조를 유지한다.

역할은 다음과 같다.

- 문서 수집 및 처리
- OCR 및 텍스트 추출
- 메타데이터 추출
- 청킹 및 임베딩
- FAISS/VectorDB 검색
- RAG 응답 조립
- 문서 관계 그래프 생성
- 관리자 작업 API

### 2.2 Front End

프론트엔드는 두 단계로 나눈다.

1. 1차 운영 콘솔
- 현재 `frontend/admin.html`을 유지
- 문서 스캔, 업로드, 처리 상태 확인, 기본 검색만 담당

2. 2차 분석자용 UI
- RFP 분석
- 추천 문서 비교
- 근거 하이라이트
- 관계 그래프 시각화
- 제안서 초안 검토

## 3. Back End 구성안

### 3.1 핵심 모듈

- `knowledge_source`
  - 원본 경로 탐색
  - 폴더/파일 스캔
  - 접근성 확인

- `extractors`
  - PDF, DOCX, PPTX, XLSX
  - HWP/HWPX는 별도 경로

- `ocr`
  - 스캔 문서 이미지 OCR

- `metadata_extractor`
  - 제목, 요약, 키워드, 기관명, 프로젝트명, 문서유형 추출

- `chunking`
  - 문단/슬라이드/섹션 단위 분할

- `vectordb`
  - Chroma 또는 FAISS 인터페이스

- `rag`
  - 검색 결과 조립
  - 설명 가능한 추천 이유 생성

- `graph`
  - Document / Project / Organization / Requirement / Methodology 관계 관리

### 3.2 API 우선순위

1. `GET /api/knowledge-sources/status`
2. `GET /api/knowledge-sources/folders`
3. `GET /api/knowledge-sources/scan`
4. `POST /api/admin/documents/process`
5. `GET /api/admin/documents/process-progress/{task_id}`
6. `GET /api/admin/stats`
7. `GET /api/search`
8. `POST /api/rag/query`
9. `GET /api/graph/*`

### 3.3 데이터 저장 원칙

- 원본 파일은 `data/raw`
- 추출 텍스트는 `data/staged/text`
- 메타데이터는 `data/staged/metadata`
- 청크는 `data/staged/chunks`
- 인덱스는 `data/indexes`
- 그래프 산출물은 `data/indexes/graph` 또는 `data/staged/graph`

## 4. Front End 구성안

### 4.1 1차 운영 콘솔

현재의 `frontend/admin.html`은 다음 역할로 제한한다.

- 네트워크 드라이브/로컬 소스 확인
- 폴더 스캔
- 파일 선택
- 문서 처리 실행
- 처리 진행률 확인
- 기본 통계 표시

### 4.2 2차 분석자용 화면

별도 UI를 추가한다.

- RFP 분석 화면
- 유사 문서 비교 화면
- 문서 상세 화면
- 추천 근거 화면
- 그래프 시각화 화면
- 제안서 초안 리뷰 화면

### 4.3 화면 우선순위

1. 문서 목록과 처리 상태
2. RFP 입력 및 검색 결과
3. 추천 이유와 근거 하이라이트
4. 문서 관계 그래프
5. 초안 응답 리뷰

## 5. 다음 작업 순서

1. `RFP 직접 추출 경로` 개선
   - HWPX 내부 XML/preview 텍스트를 구조화 추출

2. `표준 메타데이터 스키마` 확정
   - document_id, source_path, project_name, organization, doc_type, stage, confidence

3. `검색 API` 정리
   - 질의, 필터, rerank, 추천 이유, 근거 snippet 반환

4. `문서 관계 그래프` 반영
   - RFP -> proposal -> kickoff -> final_report

5. `운영자 콘솔` 개선
   - 처리 큐, 실패 문서, 재실행 버튼, 통계

6. `분석자용 UI` 설계
   - 추천 결과 비교, 근거 표시, 그래프 시각화

7. `RAG 응답 품질 개선`
   - 문서 단위 집계
   - 추론 근거 정리
   - 제안서 초안 템플릿 반영

## 6. 구현 원칙

- 원본과 가공본을 분리한다.
- 검색과 저장을 분리한다.
- 문서 추천의 근거를 항상 남긴다.
- 화면은 운영 콘솔과 분석 화면을 분리한다.
- 1차는 작게, 2차는 그래프와 시각화로 확장한다.
