# Phase 2. 화면별 필요 데이터 정의서

## 1. 문서 개요

이 문서는 rag-assistant.html의 각 화면 영역에서 표시해야 하는 데이터 필드를 구체적으로 정의한다.
Phase 1에서 정의한 UX 설계를 기반으로, 각 컴포넌트가 필요로 하는 데이터 구조를 명세한다.

## 2. 화면 영역별 데이터 정의

### 2.1 질문 입력 영역

#### Request 데이터

```typescript
interface SearchRequest {
  query: string;                    // 사용자 질문 텍스트
  search_mode: SearchMode;          // 검색 모드
  filters: SearchFilters;           // 검색 필터
  top_k: number;                    // 반환할 결과 수 (기본값: 10)
  min_score: number;                // 최소 점수 임계값 (기본값: 0.5)
}

type SearchMode = 'all' | 'rag' | 'rag_agent' | 'graph_rag' | 'llm_wiki';

interface SearchFilters {
  year?: string;                    // 수행연도 (예: "2024")
  organization?: string;            // 발주기관 (예: "K-water")
  document_type?: DocumentType[];   // 문서 유형 배열
  technology_tags?: string[];       // 기술 태그 배열
  business_tags?: string[];         // 업무 태그 배열
}

type DocumentType = 'rfp' | 'proposal' | 'kickoff_report' | 'interim_report'
                  | 'final_report' | 'completion_report' | 'presentation' | 'unknown';
```

### 2.2 프롬프트 분석 결과 패널

#### Response 데이터

```typescript
interface PromptAnalysis {
  intent: Intent;                   // 사용자 의도 분류
  keywords: string[];               // 추출된 핵심 키워드
  organization?: string;            // 감지된 발주기관
  project_type?: string;            // 감지된 프로젝트 유형 (ISP, ISMP, EA 등)
  document_type_priority: DocumentType[];  // 문서 유형 우선순위
  suggested_filters: SearchFilters; // 자동 추천 필터
  confidence: number;               // 분석 신뢰도 (0.0 ~ 1.0)
}

type Intent = 'document_search'     // 문서 검색
            | 'information_query'   // 정보 질의
            | 'comparison'          // 비교 분석
            | 'summary'             // 요약 요청
            | 'unknown';            // 분류 불가
```

### 2.3 RAG 검색 결과

#### Response 데이터

```typescript
interface RAGSearchResult {
  documents: RAGDocument[];
  total_count: number;
  search_time_ms: number;
  query_embedding_time_ms: number;
}

interface RAGDocument {
  document_id: string;              // 문서 고유 ID
  file_name: string;                // 파일명
  file_path: string;                // 원본 파일 경로
  score: number;                    // 유사도 점수 (0.0 ~ 1.0)
  page?: number;                    // 페이지 번호 (PDF인 경우)
  chunk_id: string;                 // 청크 ID
  chunk_text: string;               // 매칭된 청크 텍스트
  chunk_index: number;              // 청크 순서
  metadata: DocumentMetadata;       // 문서 메타데이터
  highlight?: string;               // 하이라이트된 텍스트 (검색어 강조)
}

interface DocumentMetadata {
  document_type: DocumentType;      // 문서 유형
  organization?: string;            // 발주기관
  project_name?: string;            // 사업명
  project_year?: string;            // 수행연도
  business_domain?: string;         // 사업분야
  technology_tags: string[];        // 기술 태그
  business_tags: string[];          // 업무 태그
  file_type: string;                // 파일 확장자 (pdf, hwp, docx 등)
  file_size: number;                // 파일 크기 (bytes)
  page_count?: number;              // 총 페이지 수
  created_at: string;               // 인덱싱 일시 (ISO 8601)
  updated_at: string;               // 최종 수정 일시
}
```

### 2.4 RAG Agent 검색 결과

#### Response 데이터

```typescript
interface RAGAgentSearchResult {
  documents: RAGAgentDocument[];
  strategy: AgentStrategy;          // 선택된 검색 전략
  tools_used: string[];             // 사용된 도구 목록
  reasoning: string;                // 전략 선택 이유
  total_count: number;
  search_time_ms: number;
}

interface RAGAgentDocument extends RAGDocument {
  agent_score: number;              // Agent 계산 점수
  tool_source: string;              // 결과를 반환한 도구명
  relevance_reason: string;         // 관련성 판단 근거
}

interface AgentStrategy {
  name: string;                     // 전략 이름 (예: "multi_query", "decomposition")
  description: string;              // 전략 설명
  confidence: number;               // 전략 신뢰도
}
```

### 2.5 Graph RAG 검색 결과

#### Response 데이터

```typescript
interface GraphRAGSearchResult {
  documents: GraphRAGDocument[];
  graph_paths: GraphPath[];         // 탐색된 그래프 경로
  nodes_visited: number;            // 방문한 노드 수
  relationships_found: number;      // 발견된 관계 수
  search_time_ms: number;
}

interface GraphRAGDocument extends RAGDocument {
  graph_score: number;              // 그래프 기반 점수
  path_length: number;              // 쿼리에서 문서까지 경로 길이
  connected_entities: GraphEntity[]; // 연결된 엔티티
}

interface GraphPath {
  nodes: GraphNode[];               // 경로상의 노드들
  edges: GraphEdge[];               // 경로상의 엣지들
  total_weight: number;             // 경로 총 가중치
}

interface GraphNode {
  id: string;                       // 노드 ID
  type: NodeType;                   // 노드 유형
  label: string;                    // 노드 레이블 (표시명)
  properties: Record<string, any>;  // 노드 속성
}

type NodeType = 'organization'      // 발주기관
              | 'project'           // 프로젝트
              | 'technology'        // 기술
              | 'document'          // 문서
              | 'year'              // 연도
              | 'business_domain';  // 업무분야

interface GraphEdge {
  source: string;                   // 출발 노드 ID
  target: string;                   // 도착 노드 ID
  type: EdgeType;                   // 관계 유형
  weight: number;                   // 가중치
}

type EdgeType = 'published_by'      // 발주기관이 발행
              | 'belongs_to'        // 프로젝트 소속
              | 'uses_tech'         // 기술 사용
              | 'related_to'        // 관련
              | 'similar_to';       // 유사

interface GraphEntity {
  type: NodeType;
  name: string;
  relation: string;                 // 문서와의 관계 설명
}
```

### 2.6 LLM Wiki 검색 결과

#### Response 데이터

```typescript
interface LLMWikiSearchResult {
  wikis: WikiDocument[];
  total_count: number;
  search_time_ms: number;
}

interface WikiDocument {
  wiki_id: string;                  // Wiki 문서 ID
  wiki_type: WikiType;              // Wiki 유형
  title: string;                    // Wiki 제목
  summary: string;                  // 요약 텍스트
  content: string;                  // Wiki 본문 (markdown)
  score: number;                    // 검색 점수
  related_documents: RelatedDoc[];  // 관련 원본 문서
  generated_at: string;             // 생성 일시
  source_count: number;             // 참조 문서 수
}

type WikiType = 'organization'      // 발주기관별 Wiki
              | 'project'           // 프로젝트별 Wiki
              | 'technology'        // 기술별 Wiki
              | 'business_domain';  // 업무분야별 Wiki

interface RelatedDoc {
  document_id: string;
  file_name: string;
  relevance: number;                // 관련도 (0.0 ~ 1.0)
}
```

### 2.7 통합 추천 문서 리스트

#### Response 데이터

```typescript
interface MergedRecommendation {
  documents: MergedDocument[];
  merge_strategy: string;           // 병합 전략 설명
  dedup_count: number;              // 중복 제거된 문서 수
}

interface MergedDocument {
  document_id: string;
  file_name: string;
  merged_score: number;             // 통합 점수 (가중 평균)
  sources: DocumentSource[];        // 검색 소스별 점수
  recommendation_reason: string;    // 추천 이유
  selected: boolean;                // 사용자 선택 여부
}

interface DocumentSource {
  source: 'rag' | 'rag_agent' | 'graph_rag' | 'llm_wiki';
  score: number;
  rank: number;                     // 해당 소스 내 순위
}
```

### 2.8 문서 상세 패널

#### Response 데이터

```typescript
interface DocumentDetail {
  document_id: string;
  file_name: string;
  file_path: string;
  metadata: DocumentMetadata;

  // 원문 탭
  html_content?: string;            // HTML 렌더링 본문
  markdown_content?: string;        // Markdown 본문
  raw_text?: string;                // 원본 텍스트
  pages?: PageContent[];            // 페이지별 콘텐츠

  // 요약 탭
  summary?: DocumentSummary;

  // 메타데이터 탭 (metadata 필드 참조)

  // 상태
  has_html: boolean;
  has_markdown: boolean;
  has_summary: boolean;
  editable: boolean;                // 편집 가능 여부
  downloadable_formats: string[];   // 다운로드 가능 포맷
}

interface PageContent {
  page_number: number;
  text: string;
  has_image: boolean;
  image_count: number;
}

interface DocumentSummary {
  summary_text: string;             // 요약 텍스트
  key_points: string[];             // 핵심 포인트
  generated_at: string;             // 요약 생성 일시
  model_used: string;               // 사용된 LLM 모델
  source_chunks: number;            // 요약에 사용된 청크 수
}
```

### 2.9 Grounded Answer 패널

#### Request 데이터

```typescript
interface GenerateAnswerRequest {
  query: string;                    // 사용자 질문
  document_ids: string[];           // 선택된 문서 ID 목록
  answer_mode: 'grounded_only';     // 항상 grounded_only
  include_citations: boolean;       // 인용 포함 여부 (기본: true)
  max_tokens?: number;              // 최대 토큰 수 (기본: 2000)
}
```

#### Response 데이터

```typescript
interface GroundedAnswer {
  answer: string;                   // 생성된 답변
  citations: Citation[];            // 인용 목록
  confidence: number;               // 답변 신뢰도
  documents_used: number;           // 사용된 문서 수
  chunks_used: number;              // 사용된 청크 수
  model_used: string;               // 사용된 LLM 모델
  generation_time_ms: number;       // 생성 시간
  warning?: string;                 // 경고 메시지 (근거 부족 등)
}

interface Citation {
  index: number;                    // 인용 번호 [1], [2], ...
  document_id: string;
  file_name: string;
  page?: number;                    // 페이지 번호
  chunk_id: string;
  chunk_text: string;               // 인용된 원문 텍스트
  relevance: number;                // 관련도
}
```

## 3. 화면별 필요 데이터 요약표

| 화면 영역 | 필드 | 데이터 출처 |
| --- | --- | --- |
| 질문 입력 | query, search_mode, filters, top_k, min_score | 사용자 입력 |
| 프롬프트 분석 | intent, keywords, organization, document_type_priority | POST /api/rag-assistant/analyze-prompt |
| RAG 결과 | document_id, file_name, score, chunk_text, metadata | POST /api/search/rag |
| Agent 결과 | strategy, tools_used, reasoning, agent_score | POST /api/search/rag-agent |
| Graph 결과 | graph_paths, connected_entities, graph_score | POST /api/search/graph-rag |
| Wiki 결과 | wiki_id, title, summary, related_documents | POST /api/search/llm-wiki |
| 통합 추천 | merged_score, sources, recommendation_reason | 프론트엔드 병합 로직 |
| 문서 상세 | html_content, markdown_content, summary, metadata | GET /api/documents/{id}/* |
| Grounded Answer | answer, citations, confidence | POST /api/rag-assistant/generate-answer |

## 4. 데이터 생성 위치

각 데이터 필드가 어디서 생성되는지 명시한다.

| 데이터 | 생성 시점 | 생성 위치 | 저장 위치 |
| --- | --- | --- | --- |
| document_id | 문서 스캔 시 | backend/storage | documents.jsonl |
| metadata | 전처리 시 | MetadataAutoGenerator | documents.jsonl |
| chunk_text | 청킹 시 | Chunker | chunks.jsonl |
| embedding | 임베딩 시 | EmbeddingService | FAISS Index |
| score | 검색 시 | FAISSService | 실시간 계산 |
| graph_path | 그래프 탐색 시 | GraphTraversal | 실시간 계산 |
| summary | Wiki 생성 시 | LLMWikiGenerator | data/wiki/*.md |
| answer | 답변 생성 시 | LLMService | 실시간 생성 |
| citations | 답변 생성 시 | LLMService | 실시간 생성 |

## 5. JSON Response 구조 초안

### 5.1 검색 API 통합 응답

```json
{
  "query": "K-water AI 수자원 관리",
  "analysis": {
    "intent": "document_search",
    "keywords": ["K-water", "AI", "수자원", "관리"],
    "organization": "K-water",
    "suggested_filters": {
      "organization": "K-water",
      "technology_tags": ["AI"]
    },
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
    "documents": [...],
    "dedup_count": 5
  },
  "total_search_time_ms": 450
}
```

### 5.2 문서 상세 API 응답

```json
{
  "document_id": "doc_001",
  "file_name": "제안요청서_2024_K-water.pdf",
  "file_path": "\\\\diskstation\\W2_프로젝트폴더\\RFP\\2024\\제안요청서_2024_K-water.pdf",
  "metadata": {
    "document_type": "rfp",
    "organization": "K-water",
    "project_name": "AI 기반 수자원 관리 시스템",
    "project_year": "2024",
    "technology_tags": ["AI", "빅데이터", "클라우드"],
    "business_tags": ["ISP", "컨설팅"],
    "file_type": "pdf",
    "file_size": 2456789,
    "page_count": 45
  },
  "html_content": "<html>...</html>",
  "summary": {
    "summary_text": "K-water의 AI 기반 수자원 관리 시스템 구축 사업...",
    "key_points": [
      "실시간 수질 모니터링 시스템 구축",
      "AI 기반 댐 운영 최적화",
      "홍수 예측 시스템 고도화"
    ]
  },
  "has_html": true,
  "has_markdown": true,
  "has_summary": true,
  "downloadable_formats": ["pdf", "txt", "md"]
}
```

## 6. 산출물 체크리스트

- [x] 질문 입력 영역 데이터 정의
- [x] 프롬프트 분석 결과 데이터 정의
- [x] RAG 검색 결과 데이터 정의
- [x] RAG Agent 검색 결과 데이터 정의
- [x] Graph RAG 검색 결과 데이터 정의
- [x] LLM Wiki 검색 결과 데이터 정의
- [x] 통합 추천 문서 데이터 정의
- [x] 문서 상세 패널 데이터 정의
- [x] Grounded Answer 데이터 정의
- [x] JSON Response 구조 초안

---

작성일: 2026-05-21
작성자: Claude
다음 단계: Phase 3. API 응답 구조 설계
