# Phase 4. 저장소 구조 설계서

## 1. 문서 개요

이 문서는 데이터 생성 산출물의 저장 경로와 파일 구조를 설계한다.
weeslee-rag가 생성하는 모든 데이터의 저장 위치, 파일 포맷, 스키마를 정의한다.

## 2. 저장소 구조 개요

### 2.1 전체 디렉토리 구조

```
weeslee-rag/
├── data/                           # 모든 생성 데이터 저장
│   ├── manifests/                  # 메타데이터 매니페스트
│   │   ├── documents.jsonl         # 문서 목록
│   │   ├── chunks.jsonl            # 청크 목록
│   │   ├── jobs.jsonl              # Job 목록
│   │   └── errors.jsonl            # 에러 로그
│   │
│   ├── extracted_text/             # 추출된 텍스트
│   │   └── {document_id}/          # 문서별 폴더
│   │       ├── raw_text.txt        # 원본 추출 텍스트
│   │       ├── cleaned_text.txt    # 정제된 텍스트
│   │       ├── document.html       # HTML 변환본
│   │       ├── document.md         # Markdown 변환본
│   │       ├── pages.json          # 페이지별 텍스트
│   │       └── metadata.json       # 추출 메타데이터
│   │
│   ├── summaries/                  # 문서 요약
│   │   └── {document_id}/
│   │       └── summary.md          # 요약 텍스트
│   │
│   ├── indexes/                    # 검색 인덱스
│   │   └── faiss/                  # FAISS Vector Index
│   │       ├── {collection}.index  # FAISS 인덱스 파일
│   │       └── {collection}.meta   # 인덱스 메타데이터
│   │
│   ├── graph/                      # Graph RAG 데이터
│   │   ├── nodes.jsonl             # 노드 목록
│   │   ├── edges.jsonl             # 엣지 목록
│   │   └── graph_manifest.json     # 그래프 메타데이터
│   │
│   └── wiki/                       # LLM Wiki
│       ├── organizations/          # 발주기관별 Wiki
│       │   └── {org_id}.md
│       ├── projects/               # 프로젝트별 Wiki
│       │   └── {project_id}.md
│       ├── technologies/           # 기술별 Wiki
│       │   └── {tech_id}.md
│       └── wiki_manifest.json      # Wiki 메타데이터
│
├── uploads/                        # 업로드된 파일 임시 저장
│   └── {upload_id}/
│
└── metadata.db                     # SQLite 메타데이터 DB
```

## 3. 매니페스트 파일 스키마

### 3.1 documents.jsonl

문서 메타데이터 목록. 한 줄에 하나의 JSON 객체.

```json
{
  "document_id": "doc_001",
  "file_name": "제안요청서_2024_K-water.pdf",
  "file_path": "\\\\diskstation\\W2_프로젝트폴더\\RFP\\2024\\...",
  "file_type": "pdf",
  "file_size": 2456789,
  "file_hash": "sha256:abc123...",
  "document_type": "rfp",
  "organization": "K-water",
  "project_name": "AI 기반 수자원 관리 시스템",
  "project_year": "2024",
  "business_domain": "ISP, 컨설팅",
  "technology_tags": ["AI", "빅데이터", "IoT"],
  "business_tags": ["ISP", "컨설팅"],
  "page_count": 45,
  "status": "rag_ready",
  "meta_status": "confirmed",
  "created_at": "2026-05-01T09:00:00Z",
  "updated_at": "2026-05-20T14:30:00Z",
  "indexed_at": "2026-05-20T15:00:00Z"
}
```

### 3.2 chunks.jsonl

청크 메타데이터 목록.

```json
{
  "chunk_id": "chunk_001_012",
  "document_id": "doc_001",
  "chunk_index": 12,
  "page_number": 3,
  "start_char": 4500,
  "end_char": 5500,
  "text": "AI 기반 수자원 관리 시스템 구축 사업은...",
  "text_length": 1000,
  "embedding_id": "emb_001_012",
  "created_at": "2026-05-20T15:00:00Z"
}
```

### 3.3 jobs.jsonl

Job 실행 이력.

```json
{
  "job_id": "job_rag_001",
  "job_type": "rag_build",
  "status": "completed",
  "config": {
    "collection_name": "weeslee_rag",
    "chunk_size": 1000,
    "embedding_model": "mxbai-embed-large"
  },
  "stats": {
    "total_documents": 125,
    "processed_documents": 125,
    "total_chunks": 3450,
    "failed_items": 0
  },
  "started_at": "2026-05-21T11:00:00Z",
  "completed_at": "2026-05-21T11:45:00Z",
  "duration_seconds": 2700
}
```

### 3.4 errors.jsonl

에러 로그.

```json
{
  "error_id": "err_001",
  "job_id": "job_rag_001",
  "document_id": "doc_005",
  "error_type": "extraction_failed",
  "error_message": "PDF 파일 손상",
  "stack_trace": "...",
  "occurred_at": "2026-05-21T11:15:00Z",
  "resolved": false
}
```

## 4. 추출 텍스트 파일 스키마

### 4.1 raw_text.txt

원본 추출 텍스트. 인코딩: UTF-8.

```
[페이지 1]
AI 기반 수자원 관리 시스템 구축 사업
제안요청서

1. 사업개요
...

[페이지 2]
...
```

### 4.2 cleaned_text.txt

정제된 텍스트. 불필요한 공백, 특수문자 제거.

```
AI 기반 수자원 관리 시스템 구축 사업 제안요청서

1. 사업개요
본 사업은 K-water가 추진하는 스마트 물관리 체계 구축의 일환으로...
```

### 4.3 document.html

HTML 렌더링 본문.

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>제안요청서_2024_K-water</title>
</head>
<body>
  <h1>AI 기반 수자원 관리 시스템 구축 사업</h1>
  <h2>제안요청서</h2>
  <section>
    <h3>1. 사업개요</h3>
    <p>본 사업은 K-water가 추진하는...</p>
  </section>
</body>
</html>
```

### 4.4 document.md

Markdown 본문.

```markdown
# AI 기반 수자원 관리 시스템 구축 사업

## 제안요청서

### 1. 사업개요

본 사업은 K-water가 추진하는 스마트 물관리 체계 구축의 일환으로...
```

### 4.5 pages.json

페이지별 텍스트.

```json
{
  "document_id": "doc_001",
  "total_pages": 45,
  "pages": [
    {
      "page_number": 1,
      "text": "AI 기반 수자원 관리 시스템 구축 사업...",
      "char_count": 1250,
      "has_image": true,
      "image_count": 1
    },
    {
      "page_number": 2,
      "text": "1. 사업개요...",
      "char_count": 2100,
      "has_image": false,
      "image_count": 0
    }
  ]
}
```

### 4.6 metadata.json

추출 메타데이터.

```json
{
  "document_id": "doc_001",
  "extraction_method": "pdfplumber",
  "ocr_used": false,
  "total_chars": 125000,
  "total_pages": 45,
  "language_detected": "ko",
  "extracted_at": "2026-05-20T10:00:00Z",
  "extraction_time_ms": 3500
}
```

## 5. 요약 파일 스키마

### 5.1 summary.md

```markdown
# 문서 요약

## 개요

K-water의 AI 기반 수자원 관리 시스템 구축 사업 RFP입니다.

## 핵심 포인트

1. **실시간 수질 모니터링 시스템 구축**
   - IoT 센서 기반 24시간 모니터링
   - AI 기반 이상 탐지

2. **AI 기반 댐 운영 최적화**
   - 빅데이터 분석 기반 방류량 예측
   - 최적 운영 의사결정 지원

3. **홍수 예측 시스템 고도화**
   - 기상/수문 데이터 통합
   - 72시간 사전 예측

## 메타데이터

- 생성일: 2026-05-20T11:00:00Z
- 모델: gemma4:latest
- 참조 청크 수: 45
```

## 6. FAISS 인덱스 구조

### 6.1 {collection}.index

FAISS 바이너리 인덱스 파일. faiss.write_index()로 생성.

### 6.2 {collection}.meta

인덱스 메타데이터.

```json
{
  "collection_name": "weeslee_rag",
  "embedding_model": "mxbai-embed-large",
  "embedding_dim": 1024,
  "total_vectors": 3450,
  "index_type": "IndexFlatIP",
  "created_at": "2026-05-20T15:00:00Z",
  "documents_indexed": 125,
  "chunk_id_map": {
    "0": "chunk_001_001",
    "1": "chunk_001_002",
    "...": "..."
  }
}
```

## 7. Graph RAG 구조

### 7.1 nodes.jsonl

그래프 노드 목록.

```json
{
  "node_id": "org_001",
  "type": "organization",
  "label": "K-water",
  "properties": {
    "full_name": "한국수자원공사",
    "document_count": 45,
    "project_count": 12
  },
  "created_at": "2026-05-20T12:00:00Z"
}
```

```json
{
  "node_id": "doc_001",
  "type": "document",
  "label": "제안요청서_2024_K-water.pdf",
  "properties": {
    "document_type": "rfp",
    "project_year": "2024",
    "page_count": 45
  },
  "created_at": "2026-05-20T12:00:00Z"
}
```

### 7.2 edges.jsonl

그래프 엣지 목록.

```json
{
  "edge_id": "edge_001",
  "source": "org_001",
  "target": "doc_001",
  "type": "published_by",
  "weight": 1.0,
  "properties": {
    "year": "2024"
  },
  "created_at": "2026-05-20T12:00:00Z"
}
```

### 7.3 graph_manifest.json

그래프 메타데이터.

```json
{
  "total_nodes": 450,
  "total_edges": 1250,
  "node_types": {
    "organization": 25,
    "project": 120,
    "technology": 35,
    "document": 250,
    "year": 10,
    "business_domain": 10
  },
  "edge_types": {
    "published_by": 250,
    "belongs_to": 400,
    "uses_tech": 350,
    "related_to": 150,
    "similar_to": 100
  },
  "created_at": "2026-05-20T12:00:00Z",
  "last_updated": "2026-05-21T10:00:00Z"
}
```

## 8. LLM Wiki 구조

### 8.1 organizations/{org_id}.md

발주기관별 Wiki.

```markdown
# K-water (한국수자원공사)

## 개요

K-water는 국내 최대 물 전문 공기업으로, AI/빅데이터/디지털트윈 기반 스마트 물관리 체계 구축을 추진 중입니다.

## 주요 프로젝트

### 2024년

1. **AI 기반 수자원 관리 시스템 구축**
   - 사업분야: ISP
   - 주요 기술: AI, 빅데이터, IoT
   - 관련 문서: [제안요청서](doc_001), [제안서](doc_002)

### 2023년

1. **디지털트윈 플랫폼 구축**
   - 사업분야: SI
   - 주요 기술: 디지털트윈, 클라우드
   - 관련 문서: [최종보고서](doc_003)

## 기술 트렌드

- AI/머신러닝 도입 확대
- 클라우드 전환 가속화
- 데이터 기반 의사결정 강화

---

생성일: 2026-05-20T13:00:00Z
참조 문서: 45건
```

### 8.2 technologies/{tech_id}.md

기술별 Wiki.

```markdown
# AI (인공지능)

## 개요

공공 컨설팅 프로젝트에서 AI 기술은 주로 예측 분석, 이상 탐지, 자동화에 활용됩니다.

## 적용 사례

### 예측 분석

- K-water: 홍수 예측, 방류량 최적화
- LH: 부동산 가격 예측, 수요 분석

### 이상 탐지

- 한전: 설비 고장 예측
- K-water: 수질 이상 탐지

## 관련 프로젝트

| 기관 | 프로젝트명 | 연도 | 문서 |
| --- | --- | --- | --- |
| K-water | AI 기반 수자원 관리 | 2024 | [RFP](doc_001) |
| LH | AI 부동산 분석 | 2023 | [제안서](doc_004) |

---

생성일: 2026-05-20T13:30:00Z
참조 문서: 28건
```

### 8.3 wiki_manifest.json

Wiki 메타데이터.

```json
{
  "total_wikis": 70,
  "wiki_types": {
    "organization": 25,
    "project": 0,
    "technology": 35,
    "business_domain": 10
  },
  "generation_config": {
    "model": "gemma4:latest",
    "summary_length": "medium",
    "max_related_docs": 20
  },
  "created_at": "2026-05-20T13:00:00Z",
  "last_updated": "2026-05-21T10:00:00Z"
}
```

## 9. SQLite 메타데이터 DB 스키마

기존 `metadata.db`와 통합. 이미 존재하는 테이블은 그대로 사용.

### 주요 테이블

- `documents`: 문서 메타데이터 (이미 존재)
- `document_metadata_suggestions`: 자동 생성 메타데이터 (이미 존재)
- `document_tags`: 문서 태그 (이미 존재)
- `processing_jobs`: Job 이력 (이미 존재)

## 10. 파일 네이밍 규칙

| 파일 종류 | 네이밍 규칙 | 예시 |
| --- | --- | --- |
| 문서 ID | doc_{timestamp_hex} | doc_001, doc_a1b2c3 |
| 청크 ID | chunk_{doc_id}_{chunk_index:03d} | chunk_001_012 |
| 임베딩 ID | emb_{doc_id}_{chunk_index:03d} | emb_001_012 |
| Job ID | job_{type}_{timestamp} | job_rag_20260521_1100 |
| 노드 ID | {type}_{hash} | org_001, tech_ai |
| 엣지 ID | edge_{source}_{target}_{hash} | edge_org001_doc001_a1b2 |
| Wiki ID | wiki_{type}_{slug} | wiki_org_kwater |

## 11. 산출물 체크리스트

- [x] 전체 디렉토리 구조 정의
- [x] 매니페스트 파일 스키마 (documents, chunks, jobs, errors)
- [x] 추출 텍스트 파일 스키마
- [x] FAISS 인덱스 구조
- [x] Graph RAG 구조 (nodes, edges, manifest)
- [x] LLM Wiki 구조
- [x] 파일 네이밍 규칙

---

작성일: 2026-05-21
작성자: Claude
다음 단계: Phase 5. 데이터 매핑표 작성
