# Phase 3. API 응답 구조 설계서

## 1. 문서 개요

이 문서는 rag-assistant.html 사용자 화면과 admin.html 관리자 화면에서 호출하는 모든 API의 엔드포인트, Request/Response 구조를 정의한다.

## 2. API 목록 요약

### 2.1 사용자 검색 API

| Method | Endpoint | 설명 |
| --- | --- | --- |
| POST | /api/rag-assistant/analyze-prompt | 프롬프트 분석 |
| POST | /api/search/rag | RAG Vector 검색 |
| POST | /api/search/rag-agent | RAG Agent 검색 |
| POST | /api/search/graph-rag | Graph RAG 검색 |
| POST | /api/search/llm-wiki | LLM Wiki 검색 |
| POST | /api/search/all | 4개 모드 통합 검색 |
| GET | /api/documents/{document_id} | 문서 상세 조회 |
| GET | /api/documents/{document_id}/html | 문서 HTML 조회 |
| GET | /api/documents/{document_id}/markdown | 문서 Markdown 조회 |
| GET | /api/documents/{document_id}/summary | 문서 요약 조회 |
| POST | /api/documents/{document_id}/edit | 문서 편집 |
| GET | /api/documents/{document_id}/download | 문서 다운로드 |
| POST | /api/rag-assistant/generate-answer | Grounded Answer 생성 |

### 2.2 관리자 데이터 생성 API

| Method | Endpoint | 설명 |
| --- | --- | --- |
| GET | /api/admin/storage/health | 저장소 상태 확인 |
| POST | /api/admin/storage/list-folders | 폴더 목록 조회 |
| POST | /api/admin/storage/scan-folder | 폴더 스캔 |
| POST | /api/admin/preprocess/start | 전처리 시작 |
| POST | /api/admin/extract-text/start | 텍스트 추출 시작 |
| POST | /api/admin/chunk/start | 청킹 시작 |
| POST | /api/admin/embed/start | 임베딩 시작 |
| POST | /api/admin/rag/build | RAG 인덱스 빌드 |
| POST | /api/admin/graph-rag/build | Graph RAG 빌드 |
| POST | /api/admin/llm-wiki/build | LLM Wiki 생성 |
| GET | /api/admin/jobs | Job 목록 조회 |
| GET | /api/admin/jobs/{job_id} | Job 상세 조회 |
| POST | /api/admin/jobs/{job_id}/retry | Job 재시도 |
| POST | /api/admin/jobs/{job_id}/cancel | Job 취소 |

---

## 3. 사용자 검색 API 상세

### 3.1 POST /api/rag-assistant/analyze-prompt

프롬프트를 분석하여 검색 의도와 필터를 추출한다.

#### Request

```json
{
  "query": "K-water AI 수자원 관리 ISP 제안요청서"
}
```

#### Response

```json
{
  "intent": "document_search",
  "keywords": ["K-water", "AI", "수자원", "관리", "ISP"],
  "organization": "K-water",
  "project_type": "ISP",
  "document_type_priority": ["rfp", "proposal", "final_report"],
  "suggested_filters": {
    "organization": "K-water",
    "technology_tags": ["AI"],
    "business_tags": ["ISP"]
  },
  "confidence": 0.92
}
```

---

### 3.2 POST /api/search/rag

FAISS Vector 검색을 수행한다.

#### Request

```json
{
  "query": "K-water AI 수자원 관리",
  "top_k": 10,
  "min_score": 0.5,
  "filters": {
    "year": "2024",
    "organization": "K-water",
    "document_type": ["rfp", "proposal"]
  }
}
```

#### Response

```json
{
  "documents": [
    {
      "document_id": "doc_001",
      "file_name": "제안요청서_2024_K-water_AI수자원.pdf",
      "file_path": "\\\\diskstation\\W2_프로젝트폴더\\RFP\\2024\\...",
      "score": 0.92,
      "page": 12,
      "chunk_id": "chunk_001_012",
      "chunk_text": "AI 기반 수자원 관리 시스템 구축 사업은 K-water가 추진하는...",
      "chunk_index": 45,
      "highlight": "<em>AI</em> 기반 <em>수자원</em> <em>관리</em> 시스템...",
      "metadata": {
        "document_type": "rfp",
        "organization": "K-water",
        "project_name": "AI 기반 수자원 관리 시스템 구축",
        "project_year": "2024",
        "technology_tags": ["AI", "빅데이터", "IoT"],
        "business_tags": ["ISP", "컨설팅"],
        "file_type": "pdf",
        "file_size": 2456789,
        "page_count": 45
      }
    }
  ],
  "total_count": 15,
  "search_time_ms": 120,
  "query_embedding_time_ms": 25
}
```

---

### 3.3 POST /api/search/rag-agent

전략적 도구 선택을 통한 Agent 검색을 수행한다.

#### Request

```json
{
  "query": "K-water와 LH의 디지털트윈 프로젝트 비교",
  "top_k": 10,
  "min_score": 0.5
}
```

#### Response

```json
{
  "documents": [
    {
      "document_id": "doc_002",
      "file_name": "최종보고서_2023_K-water_디지털트윈.pdf",
      "score": 0.88,
      "agent_score": 0.91,
      "tool_source": "multi_query_search",
      "relevance_reason": "K-water 디지털트윈 프로젝트 성과 보고서로, 비교 분석에 필요한 상세 내용 포함",
      "chunk_id": "chunk_002_023",
      "chunk_text": "K-water 디지털트윈 플랫폼 구축 사업의 최종 성과는...",
      "metadata": {...}
    }
  ],
  "strategy": {
    "name": "comparison_analysis",
    "description": "두 기관의 프로젝트를 비교하기 위해 각 기관별 검색 후 병합",
    "confidence": 0.85
  },
  "tools_used": ["multi_query_search", "entity_filter", "result_merger"],
  "reasoning": "질문에 'K-water와 LH 비교'가 포함되어 있어 comparison_analysis 전략 선택. 각 기관별 검색 후 디지털트윈 키워드로 필터링하여 결과 병합.",
  "total_count": 8,
  "search_time_ms": 450
}
```

---

### 3.4 POST /api/search/graph-rag

관계 그래프를 탐색하여 연결된 문서를 검색한다.

#### Request

```json
{
  "query": "K-water ISP 관련 모든 프로젝트",
  "top_k": 10,
  "max_depth": 3
}
```

#### Response

```json
{
  "documents": [
    {
      "document_id": "doc_003",
      "file_name": "제안서_2022_K-water_ISP.pdf",
      "score": 0.85,
      "graph_score": 0.88,
      "path_length": 2,
      "connected_entities": [
        {
          "type": "organization",
          "name": "K-water",
          "relation": "발주기관"
        },
        {
          "type": "business_domain",
          "name": "ISP",
          "relation": "사업분야"
        }
      ],
      "metadata": {...}
    }
  ],
  "graph_paths": [
    {
      "nodes": [
        {"id": "org_001", "type": "organization", "label": "K-water"},
        {"id": "proj_001", "type": "project", "label": "K-water ISP 2022"},
        {"id": "doc_003", "type": "document", "label": "제안서_2022_K-water_ISP.pdf"}
      ],
      "edges": [
        {"source": "org_001", "target": "proj_001", "type": "published_by", "weight": 1.0},
        {"source": "proj_001", "target": "doc_003", "type": "contains", "weight": 1.0}
      ],
      "total_weight": 2.0
    }
  ],
  "nodes_visited": 45,
  "relationships_found": 12,
  "search_time_ms": 200
}
```

---

### 3.5 POST /api/search/llm-wiki

사전 생성된 Wiki 문서를 검색한다.

#### Request

```json
{
  "query": "K-water 디지털 전환 전략",
  "top_k": 5
}
```

#### Response

```json
{
  "wikis": [
    {
      "wiki_id": "wiki_org_kwater",
      "wiki_type": "organization",
      "title": "K-water (한국수자원공사)",
      "summary": "K-water는 국내 최대 물 전문 공기업으로, AI/빅데이터/디지털트윈 기반 스마트 물관리 체계 구축을 추진 중...",
      "content": "# K-water (한국수자원공사)\n\n## 개요\n...",
      "score": 0.89,
      "related_documents": [
        {"document_id": "doc_001", "file_name": "제안요청서_2024_K-water.pdf", "relevance": 0.95},
        {"document_id": "doc_003", "file_name": "제안서_2022_K-water_ISP.pdf", "relevance": 0.88}
      ],
      "generated_at": "2026-05-20T10:30:00Z",
      "source_count": 15
    }
  ],
  "total_count": 3,
  "search_time_ms": 80
}
```

---

### 3.6 POST /api/search/all

4개 검색 모드를 병렬 실행하고 통합 결과를 반환한다.

#### Request

```json
{
  "query": "K-water AI 수자원 관리",
  "top_k": 10,
  "min_score": 0.5,
  "filters": {
    "year": "2024"
  }
}
```

#### Response

```json
{
  "query": "K-water AI 수자원 관리",
  "analysis": {
    "intent": "document_search",
    "keywords": ["K-water", "AI", "수자원", "관리"],
    "organization": "K-water",
    "confidence": 0.85
  },
  "results": {
    "rag": {
      "documents": [...],
      "total_count": 15,
      "search_time_ms": 120
    },
    "rag_agent": {
      "documents": [...],
      "strategy": {...},
      "total_count": 8,
      "search_time_ms": 450
    },
    "graph_rag": {
      "documents": [...],
      "graph_paths": [...],
      "total_count": 12,
      "search_time_ms": 200
    },
    "llm_wiki": {
      "wikis": [...],
      "total_count": 3,
      "search_time_ms": 80
    }
  },
  "merged": {
    "documents": [
      {
        "document_id": "doc_001",
        "file_name": "제안요청서_2024_K-water.pdf",
        "merged_score": 0.90,
        "sources": [
          {"source": "rag", "score": 0.92, "rank": 1},
          {"source": "graph_rag", "score": 0.85, "rank": 3}
        ],
        "recommendation_reason": "RAG와 Graph RAG 모두에서 상위 랭킹, K-water 발주 문서",
        "selected": false
      }
    ],
    "dedup_count": 5,
    "merge_strategy": "weighted_average"
  },
  "total_search_time_ms": 450
}
```

---

### 3.7 GET /api/documents/{document_id}

문서 상세 정보를 조회한다.

#### Response

```json
{
  "document_id": "doc_001",
  "file_name": "제안요청서_2024_K-water.pdf",
  "file_path": "\\\\diskstation\\W2_프로젝트폴더\\RFP\\2024\\제안요청서_2024_K-water.pdf",
  "metadata": {
    "document_type": "rfp",
    "organization": "K-water",
    "project_name": "AI 기반 수자원 관리 시스템 구축",
    "project_year": "2024",
    "business_domain": "ISP, 컨설팅",
    "technology_tags": ["AI", "빅데이터", "IoT"],
    "business_tags": ["ISP", "컨설팅"],
    "file_type": "pdf",
    "file_size": 2456789,
    "page_count": 45,
    "created_at": "2026-05-01T09:00:00Z",
    "updated_at": "2026-05-20T14:30:00Z"
  },
  "has_html": true,
  "has_markdown": true,
  "has_summary": true,
  "editable": true,
  "downloadable_formats": ["pdf", "txt", "md"]
}
```

---

### 3.8 GET /api/documents/{document_id}/html

문서의 HTML 렌더링 본문을 조회한다.

#### Response

```json
{
  "document_id": "doc_001",
  "html_content": "<!DOCTYPE html><html>...",
  "page_count": 45,
  "generated_at": "2026-05-20T10:00:00Z"
}
```

---

### 3.9 GET /api/documents/{document_id}/markdown

문서의 Markdown 본문을 조회한다.

#### Response

```json
{
  "document_id": "doc_001",
  "markdown_content": "# AI 기반 수자원 관리 시스템 구축 사업\n\n## 1. 사업개요\n...",
  "generated_at": "2026-05-20T10:00:00Z"
}
```

---

### 3.10 GET /api/documents/{document_id}/summary

문서 요약을 조회한다.

#### Response

```json
{
  "document_id": "doc_001",
  "summary": {
    "summary_text": "K-water의 AI 기반 수자원 관리 시스템 구축 사업 RFP입니다. 주요 내용은 실시간 수질 모니터링, AI 기반 댐 운영 최적화, 홍수 예측 시스템 구축입니다.",
    "key_points": [
      "실시간 수질 모니터링 시스템 구축",
      "AI 기반 댐 운영 최적화",
      "홍수 예측 시스템 고도화",
      "클라우드 기반 데이터 플랫폼 구축"
    ],
    "generated_at": "2026-05-20T11:00:00Z",
    "model_used": "gemma4:latest",
    "source_chunks": 45
  }
}
```

---

### 3.11 POST /api/documents/{document_id}/edit

문서 메타데이터를 편집한다.

#### Request

```json
{
  "metadata": {
    "document_type": "rfp",
    "organization": "K-water",
    "project_name": "AI 기반 수자원 관리 시스템 구축 (수정)",
    "technology_tags": ["AI", "빅데이터", "IoT", "클라우드"]
  }
}
```

#### Response

```json
{
  "success": true,
  "document_id": "doc_001",
  "updated_at": "2026-05-21T15:30:00Z"
}
```

---

### 3.12 GET /api/documents/{document_id}/download

문서를 지정된 포맷으로 다운로드한다.

#### Query Parameters

- `format`: pdf | txt | md | docx (기본값: pdf)

#### Response

- Content-Type: application/pdf | text/plain | text/markdown | application/vnd.openxmlformats-officedocument.wordprocessingml.document
- Content-Disposition: attachment; filename="..."

---

### 3.13 POST /api/rag-assistant/generate-answer

선택된 문서를 기반으로 Grounded Answer를 생성한다.

#### Request

```json
{
  "query": "K-water의 AI 수자원 관리 시스템의 주요 기능은?",
  "document_ids": ["doc_001", "doc_002", "doc_003"],
  "answer_mode": "grounded_only",
  "include_citations": true,
  "max_tokens": 2000
}
```

#### Response

```json
{
  "answer": "K-water의 AI 수자원 관리 시스템의 주요 기능은 다음과 같습니다:\n\n1. **실시간 수질 모니터링**: IoT 센서를 통한 24시간 수질 데이터 수집 및 AI 기반 이상 탐지 [1]\n2. **댐 운영 최적화**: 빅데이터 분석을 통한 방류량 예측 및 최적 운영 의사결정 지원 [1,2]\n3. **홍수 예측 시스템**: 기상 데이터와 수문 데이터를 결합한 AI 모델로 72시간 사전 예측 [2,3]\n4. **디지털트윈 플랫폼**: 물리적 시설의 가상 복제본을 통한 시뮬레이션 및 관리 [3]",
  "citations": [
    {
      "index": 1,
      "document_id": "doc_001",
      "file_name": "제안요청서_2024_K-water.pdf",
      "page": 12,
      "chunk_id": "chunk_001_012",
      "chunk_text": "본 사업은 IoT 센서 기반 실시간 수질 모니터링 체계를 구축하고...",
      "relevance": 0.95
    },
    {
      "index": 2,
      "document_id": "doc_002",
      "file_name": "최종보고서_2023_K-water_디지털트윈.pdf",
      "page": 45,
      "chunk_id": "chunk_002_045",
      "chunk_text": "댐 운영 최적화를 위한 AI 모델은 방류량 예측 정확도 95%를 달성...",
      "relevance": 0.92
    },
    {
      "index": 3,
      "document_id": "doc_003",
      "file_name": "제안서_2024_수자원관리.pdf",
      "page": 8,
      "chunk_id": "chunk_003_008",
      "chunk_text": "홍수 예측 시스템은 72시간 사전 예측을 목표로 하며, 디지털트윈 기반...",
      "relevance": 0.88
    }
  ],
  "confidence": 0.91,
  "documents_used": 3,
  "chunks_used": 12,
  "model_used": "gemma4:latest",
  "generation_time_ms": 1250
}
```

---

## 4. 관리자 데이터 생성 API 상세

### 4.1 GET /api/admin/storage/health

저장소 연결 상태를 확인한다.

#### Response

```json
{
  "status": "healthy",
  "storage_path": "\\\\diskstation\\W2_프로젝트폴더",
  "accessible": true,
  "total_size_gb": 1250.5,
  "used_size_gb": 892.3,
  "free_size_gb": 358.2,
  "last_checked": "2026-05-21T10:00:00Z"
}
```

---

### 4.2 POST /api/admin/storage/list-folders

저장소의 폴더 구조를 조회한다.

#### Request

```json
{
  "path": "\\\\diskstation\\W2_프로젝트폴더",
  "depth": 2
}
```

#### Response

```json
{
  "path": "\\\\diskstation\\W2_프로젝트폴더",
  "folders": [
    {
      "name": "00. RAG 소스",
      "path": "\\\\diskstation\\W2_프로젝트폴더\\00. RAG 소스",
      "file_count": 0,
      "subfolders": [
        {"name": "RFP", "path": "...\\RFP", "file_count": 125},
        {"name": "제안서", "path": "...\\제안서", "file_count": 89},
        {"name": "산출물", "path": "...\\산출물", "file_count": 234}
      ]
    }
  ],
  "total_files": 448
}
```

---

### 4.3 POST /api/admin/storage/scan-folder

폴더를 스캔하여 문서 목록을 추출한다.

#### Request

```json
{
  "path": "\\\\diskstation\\W2_프로젝트폴더\\00. RAG 소스\\RFP",
  "recursive": true,
  "file_types": ["pdf", "hwp", "hwpx", "docx"]
}
```

#### Response

```json
{
  "job_id": "job_scan_001",
  "status": "running",
  "started_at": "2026-05-21T10:30:00Z",
  "progress": 0,
  "message": "폴더 스캔 시작..."
}
```

---

### 4.4 POST /api/admin/preprocess/start

문서 전처리(해시, 메타데이터 추출)를 시작한다.

#### Request

```json
{
  "document_ids": ["doc_001", "doc_002"],
  "force": false
}
```

#### Response

```json
{
  "job_id": "job_preprocess_001",
  "status": "running",
  "total_documents": 2,
  "started_at": "2026-05-21T10:35:00Z"
}
```

---

### 4.5 POST /api/admin/rag/build

RAG 인덱스를 빌드한다.

#### Request

```json
{
  "collection_name": "weeslee_rag",
  "document_ids": null,
  "chunk_size": 1000,
  "chunk_overlap": 200,
  "embedding_model": "mxbai-embed-large"
}
```

#### Response

```json
{
  "job_id": "job_rag_001",
  "status": "running",
  "config": {
    "collection_name": "weeslee_rag",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "embedding_model": "mxbai-embed-large"
  },
  "started_at": "2026-05-21T11:00:00Z"
}
```

---

### 4.6 POST /api/admin/graph-rag/build

Graph RAG 노드/엣지를 생성한다.

#### Request

```json
{
  "document_ids": null,
  "node_types": ["organization", "project", "technology", "document"],
  "relation_model": "gemma4:latest"
}
```

#### Response

```json
{
  "job_id": "job_graph_001",
  "status": "running",
  "config": {
    "node_types": ["organization", "project", "technology", "document"],
    "relation_model": "gemma4:latest"
  },
  "started_at": "2026-05-21T12:00:00Z"
}
```

---

### 4.7 POST /api/admin/llm-wiki/build

LLM Wiki를 생성한다.

#### Request

```json
{
  "generation_units": ["organization", "technology"],
  "wiki_model": "gemma4:latest",
  "summary_length": "medium"
}
```

#### Response

```json
{
  "job_id": "job_wiki_001",
  "status": "running",
  "config": {
    "generation_units": ["organization", "technology"],
    "wiki_model": "gemma4:latest"
  },
  "started_at": "2026-05-21T13:00:00Z"
}
```

---

### 4.8 GET /api/admin/jobs

Job 목록을 조회한다.

#### Query Parameters

- `status`: running | completed | failed | all (기본값: all)
- `limit`: 반환 개수 (기본값: 20)
- `offset`: 시작 위치 (기본값: 0)

#### Response

```json
{
  "jobs": [
    {
      "job_id": "job_rag_001",
      "job_type": "rag_build",
      "status": "completed",
      "progress": 100,
      "total_items": 125,
      "processed_items": 125,
      "failed_items": 0,
      "started_at": "2026-05-21T11:00:00Z",
      "completed_at": "2026-05-21T11:45:00Z",
      "duration_seconds": 2700
    }
  ],
  "total_count": 15,
  "running_count": 1,
  "failed_count": 2
}
```

---

### 4.9 GET /api/admin/jobs/{job_id}

Job 상세 정보를 조회한다.

#### Response

```json
{
  "job_id": "job_rag_001",
  "job_type": "rag_build",
  "status": "completed",
  "progress": 100,
  "config": {
    "collection_name": "weeslee_rag",
    "chunk_size": 1000,
    "embedding_model": "mxbai-embed-large"
  },
  "stats": {
    "total_documents": 125,
    "processed_documents": 125,
    "total_chunks": 3450,
    "total_embeddings": 3450
  },
  "errors": [],
  "started_at": "2026-05-21T11:00:00Z",
  "completed_at": "2026-05-21T11:45:00Z"
}
```

---

## 5. 에러 응답 구조

모든 API는 동일한 에러 응답 구조를 사용한다.

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "문서를 찾을 수 없습니다.",
    "details": {
      "document_id": "doc_999"
    }
  },
  "timestamp": "2026-05-21T10:30:00Z",
  "request_id": "req_abc123"
}
```

### 에러 코드 목록

| 코드 | HTTP Status | 설명 |
| --- | --- | --- |
| DOCUMENT_NOT_FOUND | 404 | 문서를 찾을 수 없음 |
| STORAGE_UNAVAILABLE | 503 | 저장소 연결 불가 |
| JOB_NOT_FOUND | 404 | Job을 찾을 수 없음 |
| INVALID_REQUEST | 400 | 잘못된 요청 |
| SEARCH_FAILED | 500 | 검색 실패 |
| GENERATION_FAILED | 500 | 답변 생성 실패 |
| EMBEDDING_FAILED | 500 | 임베딩 실패 |

---

## 6. 산출물 체크리스트

- [x] 사용자 검색 API 목록 정의
- [x] 관리자 데이터 생성 API 목록 정의
- [x] 각 API별 Request/Response JSON 구조
- [x] 에러 응답 구조 정의

---

작성일: 2026-05-21
작성자: Claude
다음 단계: Phase 4. 저장소 구조 설계
