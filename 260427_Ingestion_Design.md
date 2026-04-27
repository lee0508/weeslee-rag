# 위즐리앤컴퍼니 문서 중앙화 1차 수집/정규화 설계서

**작성일:** 2026-04-27  
**기준 문서:** `260427_Plan.md`  
**대상 원본 경로:** `W:\01. 국내사업폴더`  
**서버 작업 경로:** `/data/weeslee/weeslee-rag/data`

---

## 1. 목적

본 문서는 위즐리앤컴퍼니 문서 중앙화 시스템의 1차 개발 착수를 위해, 원본 문서 복사 방식, 메타데이터 표준, OCR/정규화 파이프라인, FAISS 기반 인덱스 전략, Git 관리 범위를 정의한다.

핵심 원칙은 다음과 같다.

1. 원본은 훼손하지 않는다.
2. 원본 복제본과 검색용 가공본을 분리한다.
3. 대용량 원본과 벡터 인덱스는 Git에 넣지 않는다.
4. 메타데이터, 정규화 텍스트, 위키, 그래프 규칙은 Git에서 추적한다.
5. 검색은 FAISS 단독이 아니라 메타데이터 필터와 관계 그래프를 결합한다.

---

## 2. 1차 범위

1차 개발은 전체 15년 문서를 한 번에 모두 적재하지 않는다.

### 2.1 복사 대상 권장 범위

1. `RFP/과업지시서`
2. `제안서`
3. `착수보고서`
4. `최종보고서`
5. `발표자료`

### 2.2 권장 표본 규모

1. 우선 300~500건
2. 기관별/연도별/문서유형별 대표 샘플 포함
3. 스캔 PDF와 디지털 문서를 모두 포함

이 범위로 OCR 품질, 메타데이터 추출 품질, 추천 정확도를 먼저 검증한다.

---

## 3. 데이터 레이아웃

서버의 `/data/weeslee/weeslee-rag/data`는 다음 구조를 권장한다.

```text
data/
  raw/
    snapshot_2026-04-27/
      domestic_business/
        ...
  staged/
    manifest/
    metadata/
    text/
    markdown/
    chunks/
    ocr/
    thumbnails/
  indexes/
    faiss/
    bm25/
    graph/
  wiki/
    organizations/
    projects/
    document-types/
    methods/
    generated/
```

### 3.1 계층별 역할

`raw/`
- 원본의 읽기 전용 복제본
- 원본 상대경로 유지
- 재수집 기준점 역할

`staged/`
- 추출 텍스트, OCR 결과, 메타데이터, Markdown, 청크 저장
- 검색 파이프라인의 재처리 입력

`indexes/`
- FAISS, 키워드 인덱스, 그래프 캐시 저장
- Git 비추적 대상

`wiki/`
- 기관/프로젝트/방법론/문서유형 위키 저장
- 수동 보정 및 운영형 지식 축적 대상

---

## 4. 원본 복사 정책

### 4.1 복사 원칙

1. `W:\01. 국내사업폴더`는 원본으로 유지한다.
2. 서버에는 `snapshot_YYYY-MM-DD` 단위로 복제한다.
3. 1차는 선택된 표본 폴더만 복사한다.
4. 복사 시 원본 상대경로를 유지한다.
5. 동일 파일명이라도 해시가 다르면 다른 문서 또는 다른 버전으로 간주한다.

### 4.2 복사 방식

권장 방식:

1. 윈도우에서 `robocopy` 또는 서버 측 `rsync` 등 검증 가능한 도구 사용
2. 복사 후 `sha256` 해시 기록
3. manifest 생성
4. 복사 실패 파일 별도 로그 저장

### 4.3 snapshot 정책

예시:

```text
/data/weeslee/weeslee-rag/data/raw/snapshot_2026-04-27/domestic_business/...
```

개발 1차가 끝나도 snapshot은 보존하여 재현성을 확보한다.

---

## 5. Manifest 설계

복사 단계에서 모든 파일은 manifest에 등록한다.

예시:

```json
{
  "document_id": "DOC-20260427-000123",
  "source_root": "W:\\01. 국내사업폴더",
  "source_path": "W:\\01. 국내사업폴더\\A기관\\2023\\제안서\\final.pptx",
  "snapshot_path": "/data/weeslee/weeslee-rag/data/raw/snapshot_2026-04-27/domestic_business/A기관/2023/제안서/final.pptx",
  "sha256": "abc123...",
  "size_bytes": 1234567,
  "modified_at": "2024-11-02T13:20:00+09:00",
  "copied_at": "2026-04-27T11:40:00+09:00",
  "copy_batch": "batch-001",
  "copy_status": "copied"
}
```

### 5.1 Manifest 필수 필드

1. `document_id`
2. `source_path`
3. `snapshot_path`
4. `sha256`
5. `size_bytes`
6. `modified_at`
7. `copied_at`
8. `copy_batch`
9. `copy_status`

---

## 6. 메타데이터 스키마

### 6.1 최소 메타데이터

1. `document_id`
2. `title`
3. `original_filename`
4. `normalized_filename`
5. `extension`
6. `source_path`
7. `snapshot_path`
8. `document_type`
9. `project_name`
10. `organization_client`
11. `organization_vendor`
12. `year`
13. `domain`
14. `stage`
15. `version_label`
16. `language`
17. `ocr_required`
18. `ocr_confidence`
19. `text_extraction_status`
20. `security_level`
21. `duplicate_group`
22. `related_project_ids`

### 6.2 확장 메타데이터

1. `keywords`
2. `named_entities`
3. `deliverables`
4. `table_of_contents`
5. `budget_terms`
6. `schedule_terms`
7. `methodology_terms`
8. `summary_short`
9. `summary_long`
10. `provenance_tags`

### 6.3 provenance 태그

Graphify 개념을 반영하여 다음 태그를 저장한다.

1. `EXTRACTED`
2. `INFERRED`
3. `AMBIGUOUS`
4. `HUMAN_REVIEWED`

예:

```json
{
  "project_name": {
    "value": "A기관 2023 ISP",
    "provenance": "INFERRED",
    "confidence": 0.72
  }
}
```

---

## 7. OCR/정규화 파이프라인

### 7.1 처리 단계

1. 파일 형식 판별
2. 텍스트 직접 추출
3. 실패 시 OCR 수행
4. 제목/목차/장절/슬라이드 구조 추출
5. 메타데이터 추출
6. 정규화 Markdown 생성
7. 청킹
8. 임베딩 생성
9. FAISS 적재
10. 그래프 노드/엣지 생성
11. 위키 갱신

### 7.2 산출물

문서별로 다음 파일을 생성한다.

1. `metadata/<document_id>.json`
2. `text/<document_id>.txt`
3. `markdown/<document_id>.md`
4. `chunks/<document_id>.jsonl`
5. `ocr/<document_id>.json`

---

## 8. 청킹 및 임베딩 전략

### 8.1 청킹 원칙

1. 문서 유형별 청킹 규칙 분리
2. 문단 기반 우선, 필요 시 토큰 기반 보정
3. 표와 슬라이드는 별도 단위로 저장 가능

### 8.2 권장 청크 크기

1. 본문 청크: 300~700 tokens
2. overlap: 10~20%
3. 문서 요약 벡터 별도 생성
4. 섹션 단위 벡터 별도 생성

### 8.3 인덱스 단위

1. `document_summary`
2. `section`
3. `chunk`

---

## 9. FAISS + 메타데이터 + 그래프 검색 구조

1차 개발에서 FAISS는 본문 유사도 탐색의 핵심이지만, 단독으로는 부족하다.

### 9.1 검색 구성

1. 메타데이터 필터 검색
2. BM25 또는 FTS 검색
3. FAISS 기반 벡터 검색
4. 그래프 관계 확장
5. reranking

### 9.2 추천 절차

1. 신규 RFP/과업지시서 업로드
2. 기관/사업유형/요구사항/산출물 추출
3. 메타데이터 필터로 후보군 축소
4. FAISS에서 유사 청크 탐색
5. 그래프에서 연관 프로젝트/기관/파생문서 확장
6. LLM이 추천 이유와 활용 포인트 설명

---

## 10. Graphify 기능 대응 설계

참조 문서:
- https://graphify.net/kr/knowledge-graph-for-ai-coding-assistants.html

Graphify의 핵심을 문서 시스템에 대응시키면 다음과 같다.

### 10.1 노드

1. `Document`
2. `Project`
3. `Organization`
4. `DocumentType`
5. `Section`
6. `Requirement`
7. `Deliverable`
8. `Methodology`
9. `Keyword`
10. `DateRange`

### 10.2 엣지

1. `document_belongs_to_project`
2. `document_for_organization`
3. `document_has_type`
4. `document_contains_section`
5. `section_mentions_requirement`
6. `proposal_responds_to_rfp`
7. `report_derived_from_project`
8. `document_semantically_similar_to`
9. `section_reuses_template_from`
10. `organization_reuses_methodology`

### 10.3 꼭 구현할 기능

1. 구조적 탐색
2. provenance 표시
3. 요약 노드 생성
4. 근거 설명 가능한 추천

---

## 11. Git 관리 원칙

### 11.1 Git에 포함

1. 기획 문서
2. 메타데이터 스키마
3. 정규화 규칙
4. 위키 문서
5. 수동 보정 메타데이터
6. 그래프 생성 규칙
7. 샘플 manifest

### 11.2 Git 제외

1. 원본 문서
2. OCR 대량 산출물
3. FAISS 인덱스
4. 대용량 청크 파일
5. 썸네일/프리뷰 캐시

---

## 12. 현재 코드베이스 관찰 사항

현재 저장소는 이미 다음 자산을 일부 보유하고 있다.

1. 백엔드 문서 추출기
2. OCR 서비스
3. 메타데이터 추출 서비스
4. 청킹 서비스
5. 기존 VectorDB 연동 코드
6. 관리자용 문서 처리 API

다만 현재 백엔드는 `FastAPI + ChromaDB` 성격이 강하다.  
사용자 목표가 `Flask + FAISS + OCR + RAG + LLM`이라면 다음 두 가지 경로 중 하나를 선택해야 한다.

1. 현재 FastAPI 기반 코드를 유지하면서 FAISS/그래프 계층을 추가
2. Flask로 전환하되, 기존 추출/OCR/메타데이터 코드를 재사용

1차 착수 관점에서는 `기존 파이프라인 자산을 활용`하는 것이 현실적이며, 프레임워크 전환은 후순위가 맞다.

---

## 13. 권장 실행 순서

1. `data/` 레이아웃 생성
2. 메타데이터 스키마 확정
3. 원본 표본 선정
4. snapshot 복사
5. manifest 생성
6. OCR/추출/정규화 파이프라인 적용
7. FAISS + BM25 + 메타데이터 검색 구축
8. 그래프/위키 계층 추가

---

## 14. 다음 실행 작업

다음 작업은 아래 순서로 진행하는 것이 적절하다.

1. 서버 `data/` 폴더 실제 생성
2. 표본 복사 배치 계획 수립
3. manifest/metadata 예제 파일 생성
4. ingest 스크립트 초안 작성
5. FAISS 인덱스 설계 반영

