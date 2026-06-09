# Dataset Builder 전체 테스트 시나리오

## 문서 정보

- **작성일**: 2026-06-09
- **작성자**: Claude Code
- **테스트 대상**: Dataset Builder Steps 1-10 통합 테스트
- **테스트 환경**: 회사 서버 (192.168.0.207)
- **테스트 데이터**: 30개 파일

---

## 테스트 환경 설정

### 서버 정보
- **서버 주소**: 192.168.0.207
- **FastAPI 포트**: 8080
- **프로젝트 경로**: /data/weeslee/weeslee-rag
- **API Base URL**: http://192.168.0.207:8080/api

### 인증 정보
- **Username**: admin
- **Password**: weeslee12#$
- **인증 방식**: Bearer Token (JWT)

### 테스트 데이터
- **파일 수**: 30개
- **파일 위치**: 검수 완료된 문서 중 30개 선택
- **파일 형식**: HWP, PPTX, PDF, DOCX 등 다양한 형식 포함

---

## 사전 준비

### 1. 서버 접속 확인

```bash
# SSH 접속 테스트
ssh weeslee@192.168.0.207
```

### 2. FastAPI 서버 상태 확인

```bash
# 프로세스 확인
ps -ef | grep uvicorn | grep -v grep

# Health check
curl -s http://192.168.0.207:8080/api/health
```

**예상 결과**:
```json
{"status":"healthy"}
```

### 3. 인증 토큰 획득

```bash
# 로그인 API 호출
TOKEN=$(curl -s -X POST "http://192.168.0.207:8080/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"weeslee12#$"}' \
  | jq -r '.token')

echo "Token: $TOKEN"
```

**예상 결과**: JWT 토큰 문자열 반환

---

## Step 1: Source Scan

### 목적
원본 폴더를 스캔하여 snapshot_id, source_id, category_id, document_id를 생성합니다.

### API 엔드포인트
- **URL**: `POST /api/admin/dataset-builder/step1/scan`
- **인증**: 필요 (Bearer Token)

### 테스트 케이스 1-1: 전체 스캔

```bash
# Step 1 실행
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step1/scan" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": null,
    "force_rescan": false
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "message": "Scan completed",
  "scanned_files": 150,
  "new_files": 30,
  "updated_files": 0,
  "skipped_files": 120
}
```

### 테스트 케이스 1-2: 상태 조회

```bash
# Step 1 상태 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step1/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "total_sources": 14,
  "total_documents": 150,
  "by_source": {
    "01_RFP": 20,
    "02_제안서": 50,
    "03_산출물": 80
  }
}
```

### 검증 항목
- [ ] API 응답 성공 (HTTP 200)
- [ ] 신규 파일 30개 정상 스캔
- [ ] document_id 정상 생성
- [ ] source_id, category_id 정상 매핑

---

## Step 2: Metadata Auto

### 목적
LLM을 사용하여 문서 메타데이터를 자동 추출합니다.

### API 엔드포인트
- **URL**: `POST /api/admin/dataset-builder/step2/generate`
- **인증**: 필요 (Bearer Token)

### 테스트 케이스 2-1: 30개 문서 메타데이터 생성

```bash
# Step 2 실행 (30개 문서만)
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step2/generate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": null,
    "limit": 30,
    "force_regenerate": false
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "processed": 30,
  "failed": 0,
  "skipped": 0,
  "total_time_seconds": 180.5
}
```

### 테스트 케이스 2-2: 상태 조회

```bash
# Step 2 상태 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step2/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "total_documents": 150,
  "generated": 30,
  "pending": 120,
  "avg_confidence": 0.85
}
```

### 테스트 케이스 2-3: 개별 문서 메타데이터 조회

```bash
# 특정 문서의 메타데이터 조회 (document_id=1로 가정)
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step2/document/1" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "document_id": 1,
  "file_name": "ISP_제안서_2024.pptx",
  "metadata": {
    "organization": "한국수자원공사",
    "project_name": "ISP 수립 사업",
    "project_year": "2024",
    "document_type": "proposal"
  },
  "confidence": 0.92
}
```

### 검증 항목
- [ ] 30개 문서 메타데이터 정상 생성
- [ ] organization, project_name, project_year 추출 성공
- [ ] document_type 정확도 80% 이상
- [ ] 평균 confidence 0.7 이상

---

## Step 3: Metadata Review

### 목적
생성된 메타데이터를 검수하고 승인합니다.

### API 엔드포인트
- **URL**: `GET /api/admin/metadata-review/pending`
- **인증**: 필요 (Bearer Token)

### 테스트 케이스 3-1: 검수 대기 문서 조회

```bash
# 검수 대기 문서 목록
curl -s -X GET "http://192.168.0.207:8080/api/admin/metadata-review/pending?limit=30" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "documents": [
    {
      "document_id": 1,
      "file_name": "ISP_제안서_2024.pptx",
      "suggested_metadata": {...},
      "confidence": 0.92
    }
  ],
  "total": 30
}
```

### 테스트 케이스 3-2: 메타데이터 승인 (일괄 처리)

```bash
# 30개 문서 일괄 승인
DOCUMENT_IDS=$(curl -s -X GET "http://192.168.0.207:8080/api/admin/metadata-review/pending?limit=30" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.documents[].document_id' | jq -s '.')

curl -s -X POST "http://192.168.0.207:8080/api/admin/metadata-review/approve-batch" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"document_ids\": $DOCUMENT_IDS}" | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "approved_count": 30,
  "failed_count": 0
}
```

### 테스트 케이스 3-3: 검수 상태 확인

```bash
# Step 3 상태 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/metadata-review/stats" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "total": 150,
  "pending": 120,
  "approved": 30,
  "rejected": 0
}
```

### 검증 항목
- [ ] 검수 대기 문서 30개 조회 성공
- [ ] 일괄 승인 정상 처리
- [ ] meta_status가 "metadata_reviewed"로 변경
- [ ] include_in_rag가 true로 설정

---

## Step 4: OCR/Parser

### 목적
검수 완료된 문서에서 텍스트를 추출합니다.

### API 엔드포인트
- **URL**: `POST /api/admin/dataset-builder/step4/parse`
- **인증**: 필요 (Bearer Token)

### 테스트 케이스 4-1: 30개 문서 텍스트 추출

```bash
# Step 4 실행
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step4/parse" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": null,
    "force_reparse": false
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "total_documents": 30,
  "processed": 30,
  "failed": 0,
  "skipped": 0,
  "processing_time": 120.5
}
```

### 테스트 케이스 4-2: 상태 조회

```bash
# Step 4 상태 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step4/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "total": 30,
  "pending": 0,
  "processing": 0,
  "completed": 30,
  "failed": 0,
  "by_source": {...},
  "by_file_type": {
    "pptx": {"completed": 15, "failed": 0},
    "hwp": {"completed": 10, "failed": 0},
    "pdf": {"completed": 5, "failed": 0}
  }
}
```

### 테스트 케이스 4-3: 개별 문서 텍스트 조회

```bash
# 특정 문서의 추출된 텍스트 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step4/document/1/text?format=txt" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "document_id": 1,
  "format": "txt",
  "text": "ISP 수립 사업 제안서\n\n1. 사업 개요\n...",
  "text_length": 15234
}
```

### 검증 항목
- [ ] 30개 문서 100% 성공 처리
- [ ] PPTX, HWP, PDF 모든 형식 정상 추출
- [ ] text_length가 100자 이상 (품질 검증)
- [ ] processed_texts 디렉토리에 JSON 파일 생성 확인

---

## Step 5: Chunk Build

### 목적
추출된 텍스트를 청킹합니다.

### API 엔드포인트
- **URL**: `POST /api/admin/dataset-builder/step5/chunk`
- **인증**: 필요 (Bearer Token)

### 테스트 케이스 5-1: 30개 문서 청킹

```bash
# Step 5 실행
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step5/chunk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": null,
    "chunk_size": 512,
    "chunk_overlap": 50,
    "min_chunk_size": 100,
    "force_rebuild": false
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "processed": 30,
  "failed": 0,
  "skipped": 0,
  "total_chunks": 450,
  "chunk_size": 512,
  "chunk_overlap": 50
}
```

### 테스트 케이스 5-2: 상태 조회

```bash
# Step 5 상태 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step5/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "total_documents": 30,
  "chunked_documents": 30,
  "total_chunks": 450,
  "avg_chunks_per_doc": 15.0,
  "not_chunked": 0
}
```

### 테스트 케이스 5-3: 개별 문서 청크 조회

```bash
# 특정 문서의 청크 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step5/document/1/chunks" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "document_id": 1,
  "file_name": "ISP_제안서_2024.pptx",
  "chunks": [
    {
      "chunk_index": 0,
      "content_preview": "ISP 수립 사업 제안서\n\n1. 사업 개요...",
      "token_count": 512,
      "char_count": 2048
    }
  ],
  "total_chunks": 15
}
```

### 검증 항목
- [ ] 30개 문서 청킹 완료
- [ ] 총 청크 수 400개 이상
- [ ] 평균 청크 수 10-20개 사이
- [ ] chunk_size, chunk_overlap 설정 정상 적용

---

## Step 6: Embedding Build

### 목적
청크에 대한 임베딩을 생성합니다.

### API 엔드포인트
- **URL**: `POST /api/admin/dataset-builder/step6/embed`
- **인증**: 필요 (Bearer Token)

### 테스트 케이스 6-1: 30개 문서 임베딩 생성

```bash
# Step 6 실행
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step6/embed" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": null,
    "model": "nomic-embed-text",
    "batch_size": 32,
    "force_rebuild": false
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "processed": 30,
  "failed": 0,
  "total_embeddings": 450,
  "processing_time": 180.5,
  "model": "nomic-embed-text",
  "embedding_dim": 768
}
```

### 테스트 케이스 6-2: 상태 조회

```bash
# Step 6 상태 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step6/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "total_chunks": 450,
  "embedded_chunks": 450,
  "pending_chunks": 0,
  "model": "nomic-embed-text",
  "embedding_dim": 768
}
```

### 검증 항목
- [ ] 450개 청크 임베딩 생성 완료
- [ ] 임베딩 차원 768 확인
- [ ] 임베딩 파일 생성 확인
- [ ] 처리 시간 5분 이내

---

## Step 7: FAISS Build

### 목적
FAISS 벡터 인덱스를 생성합니다.

### API 엔드포인트
- **URL**: `POST /api/admin/dataset-builder/step7/build`
- **인증**: 필요 (Bearer Token)

### 테스트 케이스 7-1: FAISS 인덱스 빌드

```bash
# Step 7 실행
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step7/build" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": null,
    "force_rebuild": false
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "message": "FAISS index built successfully",
  "total_vectors": 450,
  "index_file": "/data/weeslee/weeslee-rag/data/indexes/faiss/default.index",
  "processing_time": 15.3
}
```

### 테스트 케이스 7-2: 상태 조회

```bash
# Step 7 상태 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step7/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "index_status": "ready",
  "total_vectors": 450,
  "index_file_size_mb": 3.5,
  "last_built_at": "2026-06-09T10:30:00"
}
```

### 테스트 케이스 7-3: FAISS 검색 테스트

```bash
# FAISS 검색 테스트
curl -s -X POST "http://192.168.0.207:8080/api/faiss/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "ISP 방법론",
    "top_k": 5
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "results": [
    {
      "rank": 1,
      "score": 0.92,
      "document_id": 1,
      "chunk_id": 5,
      "text": "ISP 방법론은 정보시스템 구축을 위한..."
    }
  ],
  "result_count": 5
}
```

### 검증 항목
- [ ] FAISS 인덱스 파일 생성
- [ ] 450개 벡터 인덱싱 완료
- [ ] 검색 테스트 정상 동작
- [ ] 검색 결과 score 0.5 이상

---

## Step 8: Graph Build

### 목적
Knowledge Graph를 빌드합니다.

### API 엔드포인트
- **URL**: `POST /api/admin/dataset-builder/step8/build`
- **인증**: 필요 (Bearer Token)

### 테스트 케이스 8-1: Graph 빌드

```bash
# Step 8 실행
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step8/build" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": null,
    "rebuild": false
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "message": "Graph built successfully: 45 nodes, 90 edges",
  "node_count": 45,
  "edge_count": 90,
  "processing_time": 25.3,
  "output": "..."
}
```

### 테스트 케이스 8-2: 상태 조회

```bash
# Step 8 상태 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step8/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "graph_status": "ready",
  "node_count": 45,
  "edge_count": 90,
  "built_at": "2026-06-09T10:35:00",
  "schema_version": "phase2"
}
```

### 테스트 케이스 8-3: Graph 통계 조회

```bash
# Step 8 통계 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step8/stats" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "source_id": "all",
  "total_nodes": 45,
  "total_edges": 90,
  "node_types": {
    "project": 10,
    "document": 30,
    "organization": 5
  },
  "relation_types": {
    "belongs_to": 30,
    "has_category": 30,
    "related_to": 30
  }
}
```

### 검증 항목
- [ ] Graph 빌드 정상 완료
- [ ] 노드 수 30개 이상 (문서 수 기준)
- [ ] 엣지 수 60개 이상
- [ ] graph_nodes.jsonl, graph_edges.jsonl 파일 생성

---

## Step 9: Wiki Build

### 목적
프로젝트, 조직, 기술별 Wiki를 생성합니다.

### API 엔드포인트
- **URL**: `POST /api/admin/dataset-builder/step9/build`
- **인증**: 필요 (Bearer Token)

### 테스트 케이스 9-1: 프로젝트 Wiki 빌드

```bash
# Step 9 실행 (프로젝트 Wiki)
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step9/build" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": null,
    "wiki_type": "project",
    "slug": null,
    "from_inventory": false,
    "max_wikis": 10
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "message": "Wiki build completed: 10 wikis generated",
  "generated_count": 10,
  "generated_wikis": [
    "isp-proposal-2024",
    "ismp-final-report-2023",
    "..."
  ],
  "processing_time": 180.5,
  "output": "..."
}
```

### 테스트 케이스 9-2: 상태 조회

```bash
# Step 9 상태 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step9/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "project_wikis": 10,
  "organization_wikis": 0,
  "technology_wikis": 0,
  "total_wikis": 10
}
```

### 테스트 케이스 9-3: Wiki 목록 조회

```bash
# Wiki 목록 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step9/list?wiki_type=project" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "pages": [
    {
      "slug": "isp-proposal-2024",
      "file_name": "isp-proposal-2024.md",
      "size_bytes": 12345
    }
  ],
  "count": 10,
  "wiki_type": "project"
}
```

### 테스트 케이스 9-4: 조직 Wiki 빌드

```bash
# 조직별 Wiki 빌드
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step9/build" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "wiki_type": "organization"
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "message": "Organization wikis generated: 5",
  "generated_count": 5,
  "generated_wikis": [
    "한국수자원공사",
    "경기주택도시공사",
    "..."
  ],
  "processing_time": 30.2
}
```

### 검증 항목
- [ ] 프로젝트 Wiki 10개 생성
- [ ] 조직 Wiki 5개 이상 생성
- [ ] Wiki 파일 정상 생성 (data/wiki/projects/*.md)
- [ ] Wiki 내용 품질 확인 (100자 이상)

---

## Step 10: Search Quality

### 목적
RAG 검색 품질을 테스트합니다.

### API 엔드포인트
- **URL**: `POST /api/admin/dataset-builder/step10/test`
- **인증**: 필요 (Bearer Token)

### 테스트 케이스 10-1: 샘플 쿼리 조회

```bash
# 샘플 쿼리 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step10/sample-queries" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "sample_queries": [
    {
      "query": "ISP 방법론이 적용된 프로젝트는?",
      "category": "proposal"
    },
    {
      "query": "클라우드 마이그레이션 관련 문서",
      "category": null
    }
  ]
}
```

### 테스트 케이스 10-2: 검색 품질 테스트 (FAISS)

```bash
# FAISS 검색 품질 테스트
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step10/test" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "test_queries": [
      {
        "query": "ISP 방법론이 적용된 프로젝트는?",
        "expected_doc_ids": null,
        "category": "proposal"
      },
      {
        "query": "클라우드 마이그레이션 관련 문서",
        "expected_doc_ids": null,
        "category": null
      },
      {
        "query": "한국수자원공사 사업",
        "expected_doc_ids": null,
        "category": null
      }
    ],
    "source_id": null,
    "top_k": 10,
    "use_graph": false
  }' | jq '.'
```

**예상 결과**:
```json
{
  "success": true,
  "total_queries": 3,
  "passed_queries": 3,
  "failed_queries": 0,
  "avg_precision": null,
  "avg_recall": null,
  "avg_search_time_ms": 125.5,
  "test_results": [
    {
      "query": "ISP 방법론이 적용된 프로젝트는?",
      "success": true,
      "results_count": 10,
      "results": [...],
      "precision": null,
      "recall": null,
      "search_time_ms": 120.3,
      "error": null
    }
  ]
}
```

### 테스트 케이스 10-3: GraphRAG 검색 테스트

```bash
# GraphRAG 검색 품질 테스트
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step10/test" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "test_queries": [
      {
        "query": "ISP 방법론",
        "expected_doc_ids": null
      }
    ],
    "top_k": 10,
    "use_graph": true
  }' | jq '.'
```

### 테스트 케이스 10-4: 상태 조회

```bash
# Step 10 상태 조회
curl -s -X GET "http://192.168.0.207:8080/api/admin/dataset-builder/step10/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

**예상 결과**:
```json
{
  "faiss_status": "ready",
  "faiss_doc_count": 450,
  "graph_status": "ready",
  "graph_node_count": 45,
  "last_test_at": null,
  "total_tests": 0
}
```

### 검증 항목
- [ ] 3개 테스트 쿼리 모두 성공
- [ ] 평균 검색 시간 200ms 이내
- [ ] 각 쿼리당 10개 결과 반환
- [ ] FAISS와 GraphRAG 모두 정상 동작

---

## 통합 테스트 시나리오

### 전체 파이프라인 실행

```bash
#!/bin/bash
# 전체 Dataset Builder 파이프라인 실행 스크립트

# 토큰 획득
TOKEN=$(curl -s -X POST "http://192.168.0.207:8080/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"weeslee12#$"}' \
  | jq -r '.token')

echo "Token obtained: ${TOKEN:0:20}..."

# Step 1: Source Scan
echo "\n=== Step 1: Source Scan ==="
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step1/scan" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_id": null, "force_rescan": false}' | jq '.success, .new_files'

# Step 2: Metadata Auto (30개만)
echo "\n=== Step 2: Metadata Auto ==="
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step2/generate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"limit": 30, "force_regenerate": false}' | jq '.success, .processed'

# Step 3: Metadata Review (일괄 승인)
echo "\n=== Step 3: Metadata Review ==="
DOCUMENT_IDS=$(curl -s -X GET "http://192.168.0.207:8080/api/admin/metadata-review/pending?limit=30" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.documents[].document_id' | jq -s '.')

curl -s -X POST "http://192.168.0.207:8080/api/admin/metadata-review/approve-batch" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"document_ids\": $DOCUMENT_IDS}" | jq '.success, .approved_count'

# Step 4: OCR/Parser
echo "\n=== Step 4: OCR/Parser ==="
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step4/parse" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"force_reparse": false}' | jq '.success, .processed, .failed'

# Step 5: Chunk Build
echo "\n=== Step 5: Chunk Build ==="
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step5/chunk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"chunk_size": 512, "chunk_overlap": 50, "force_rebuild": false}' \
  | jq '.success, .processed, .total_chunks'

# Step 6: Embedding Build
echo "\n=== Step 6: Embedding Build ==="
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step6/embed" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "nomic-embed-text", "batch_size": 32, "force_rebuild": false}' \
  | jq '.success, .processed, .total_embeddings'

# Step 7: FAISS Build
echo "\n=== Step 7: FAISS Build ==="
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step7/build" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"force_rebuild": false}' | jq '.success, .total_vectors'

# Step 8: Graph Build
echo "\n=== Step 8: Graph Build ==="
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step8/build" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"rebuild": false}' | jq '.success, .node_count, .edge_count'

# Step 9: Wiki Build
echo "\n=== Step 9: Wiki Build ==="
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step9/build" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"wiki_type": "project", "max_wikis": 10}' \
  | jq '.success, .generated_count'

# Step 10: Search Quality Test
echo "\n=== Step 10: Search Quality ==="
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step10/test" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "test_queries": [
      {"query": "ISP 방법론", "category": "proposal"},
      {"query": "클라우드 마이그레이션"},
      {"query": "한국수자원공사 사업"}
    ],
    "top_k": 10,
    "use_graph": false
  }' | jq '.success, .total_queries, .passed_queries, .avg_search_time_ms'

echo "\n=== 전체 파이프라인 실행 완료 ==="
```

---

## 성공 기준

### 전체 파이프라인
- [ ] Step 1-10 모두 정상 실행
- [ ] 30개 문서 100% 처리 완료
- [ ] 각 단계별 실패율 0%

### 성능 기준
- [ ] Step 2 (Metadata Auto): 평균 6초/문서 (총 180초)
- [ ] Step 4 (OCR/Parser): 평균 4초/문서 (총 120초)
- [ ] Step 5 (Chunk Build): 30초 이내
- [ ] Step 6 (Embedding): 180초 이내
- [ ] Step 7 (FAISS Build): 30초 이내
- [ ] Step 8 (Graph Build): 60초 이내
- [ ] Step 9 (Wiki Build): 180초 이내
- [ ] Step 10 (Search): 평균 200ms 이내

### 품질 기준
- [ ] Metadata 정확도 80% 이상
- [ ] OCR/Parser 텍스트 추출 성공률 100%
- [ ] 청크 생성 성공률 100%
- [ ] FAISS 검색 결과 relevance score 0.5 이상
- [ ] Graph 노드/엣지 정상 생성
- [ ] Wiki 문서 품질 (100자 이상)

---

## 문제 해결 가이드

### 자주 발생하는 문제

#### 1. 인증 토큰 만료
**증상**: `{"detail":"유효하지 않거나 만료된 토큰입니다."}`

**해결**:
```bash
# 토큰 재발급
TOKEN=$(curl -s -X POST "http://192.168.0.207:8080/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"weeslee12#$"}' \
  | jq -r '.token')
```

#### 2. FastAPI 서버 다운
**증상**: `curl: (7) Failed to connect`

**해결**:
```bash
# 서버 SSH 접속
ssh weeslee@192.168.0.207

# 프로세스 확인
ps -ef | grep uvicorn | grep -v grep

# 서버 재시작
cd /data/weeslee/weeslee-rag
./start_server.sh
```

#### 3. Step 실행 실패
**증상**: `{"success": false, "error": "..."}`

**해결**:
```bash
# 로그 확인
ssh weeslee@192.168.0.207
tail -100 /data/weeslee/weeslee-rag/logs/uvicorn.log

# 특정 Step 재실행 (force 옵션)
curl -s -X POST "http://192.168.0.207:8080/api/admin/dataset-builder/step4/parse" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"force_reparse": true}'
```

---

## 테스트 결과 기록

### 테스트 실행 정보
- **실행 일시**: _______________
- **실행자**: _______________
- **테스트 데이터**: 30개 파일

### 각 단계별 결과

| Step | 성공 | 실패 | 건너뜀 | 처리 시간 | 비고 |
|------|------|------|--------|----------|------|
| 1. Source Scan | ☐ | ☐ | - | _____초 | |
| 2. Metadata Auto | ☐ | ☐ | ☐ | _____초 | |
| 3. Metadata Review | ☐ | ☐ | - | _____초 | |
| 4. OCR/Parser | ☐ | ☐ | ☐ | _____초 | |
| 5. Chunk Build | ☐ | ☐ | ☐ | _____초 | |
| 6. Embedding Build | ☐ | ☐ | ☐ | _____초 | |
| 7. FAISS Build | ☐ | ☐ | - | _____초 | |
| 8. Graph Build | ☐ | ☐ | - | _____초 | |
| 9. Wiki Build | ☐ | ☐ | - | _____초 | |
| 10. Search Quality | ☐ | ☐ | - | _____초 | |

### 발견된 이슈

1. _______________________________________________________
2. _______________________________________________________
3. _______________________________________________________

### 종합 평가

- **전체 성공률**: _____% (____/10 단계)
- **총 처리 시간**: ______분
- **품질 평가**: ☐ 우수 ☐ 양호 ☐ 보통 ☐ 개선 필요

---

**문서 작성**: Claude Code
**최종 수정**: 2026-06-09
