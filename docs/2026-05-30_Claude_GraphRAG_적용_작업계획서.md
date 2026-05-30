# weeslee-rag GraphRAG 적용 작업 계획서

**문서 작성일**: 2026-05-30
**버전**: 1.0
**작성자**: Claude
**근거 문서**:
- `2026-05-30_Lee_프로젝트_기능개선안.md`
- `2026-05-30_Lee_기능개선_작업지시서.md`

---

## 1. 프로젝트 방향 요약

### 1.1 핵심 결론

> **"지금 바로 LangGraph Agent부터 만들면 안 됩니다."**

GraphRAG Agent를 바로 구현하는 것이 아니라, **기반 데이터와 인프라를 먼저 정리**해야 합니다.

### 1.2 적용 순서 (필수)

```
1. Dataset Builder 정리          ← 데이터 기반
2. Graph 데이터 생성             ← GraphRAG 대상
3. Text2Cypher 테스트            ← 관리자 검증
4. GraphRAG Agent 자동 수정       ← 핵심 기능
5. Hybrid RAG 통합               ← FAISS + Graph
6. 사용자 화면 연결              ← rag-assistant.html
7. 관리자 검증 화면 연결          ← admin.html
8. 제안서 작성 기능 연결          ← 최종 목표
```

---

## 2. 현재 상태 분석

### 2.1 완료된 작업

| 영역 | 상태 | 비고 |
|------|------|------|
| admin.html 사이드바 구조 | ✅ | RAG SOURCE 동적 로드, ALERTS 배지 |
| rag-assistant.html 기본 구조 | ✅ | 문서 카드, 상세 패널, 미리보기 |
| Phase 3 사이드바 고도화 | ✅ | API 연동, Ctrl+K 검색 |
| Phase 4 UI/UX 개선 | ✅ | 서버 상태 축소, 마크다운 렌더링, Citation 앵커 |

### 2.2 미완료/문제점

| 영역 | 상태 | 문제점 |
|------|------|--------|
| Dataset Builder 설정 변수 | ⚠️ | API 경로는 있으나 필수 변수/request body 불투명 |
| Graph 응답 스키마 | ⚠️ | graph_context, relations, edge, chain, entity 혼재 |
| 선택 문서 답변 API | ⚠️ | UI는 있으나 백엔드 Mock 수준 |
| Text2Cypher | ❌ | 미구현 |
| GraphRAG Agent | ❌ | 미구현 |

---

## 3. Phase별 상세 계획

### 3.1 Phase 0: 현재 코드 안정화 (P0 - 필수)

**목적**: GraphRAG 적용 전 기존 코드 정리

| 작업 | 내용 | 예상 공수 |
|------|------|----------|
| 0.1 | `.gitattributes` 추가 (줄바꿈 정책 LF 고정) | 0.5h |
| 0.2 | rag-assistant.html 불필요 diff 제거 | 1h |
| 0.3 | 선택 문서 답변 DOM ID 통일 | 1h |
| 0.4 | 선택 문서 답변 API 계약 문서화 | 1h |
| 0.5 | Graph 응답 스키마 표준화 초안 | 2h |

**산출물**:
- `.gitattributes` 파일
- 선택 문서 답변 API 명세 문서
- Graph 응답 표준 스키마 정의서

---

### 3.2 Phase 1: Dataset Builder 설정 변수 UI 완성 (P1 - 중요)

**목적**: Graph 데이터 생성의 출발점 확보

| Step | 이름 | API | 필수 변수 |
|------|------|-----|----------|
| 1 | Source Scan | POST /api/admin/files/scan | source_path, recursive |
| 2 | Collection Bootstrap | POST /api/admin/collections/sync | client_id, source_id |
| 3 | Metadata Build | POST /api/admin/metadata/generate | client_id, collection_name, overwrite |
| 4 | Tags/Keywords Extract | POST /api/admin/tags/generate | client_id, min_count |
| 5 | Chunk/Embedding/FAISS | POST /api/admin/faiss/build | collection_name, chunk_size |
| **6** | **Graph Schema Build** | POST /api/admin/graph/schema/build | client_id, node_types, relation_types |
| **7** | **Graph Data Build** | POST /api/admin/graph/build | client_id, graph_depth, entity_threshold |
| **8** | **LLM-Wiki Build** | POST /api/admin/wiki/build | client_id, language, include_graph_context |
| **9** | **Text2Cypher Test** | POST /api/admin/graph/text2cypher/test | question, readonly |
| **10** | **Hybrid RAG Publish** | POST /api/admin/rag/publish | enable_faiss, enable_graph, enable_wiki |

**작업 내용**:
1. 각 Step별 필수/선택 파라미터 UI 표시
2. request body 미리보기 추가
3. 입력값 검증 추가
4. 실행 결과 표시 영역 추가

---

### 3.3 Phase 2: Graph 데이터 모델 확정 (P1 - 중요)

**목적**: Text2Cypher 정확도 확보를 위한 스키마 고정

#### 노드 정의

| 노드 | 설명 | 주요 속성 |
|------|------|----------|
| Organization | 발주기관, 고객사 | id, name, normalized_name, type |
| Project | 사업, 프로젝트 | id, name, year, business_type, status |
| Document | RFP, 제안서, 보고서 등 | document_id, title, file_name, document_type |
| Keyword | 기술/업무/산업 키워드 | id, name, weight |
| Category | 문서 분류 | id, name, depth |

#### 관계 정의

| 관계 | 설명 |
|------|------|
| `(:Organization)-[:ORDERED]->(:Project)` | 기관이 사업 발주 |
| `(:Project)-[:HAS_DOCUMENT]->(:Document)` | 사업에 문서 포함 |
| `(:Document)-[:HAS_KEYWORD]->(:Keyword)` | 문서에 키워드 |
| `(:Document)-[:SAME_PROJECT]->(:Document)` | 같은 사업 문서 |
| `(:Document)-[:SAME_ORGANIZATION]->(:Document)` | 같은 기관 문서 |
| `(:Project)-[:SIMILAR_TO]->(:Project)` | 유사 사업 |

#### 규칙
- 노드명/관계명은 **영문 PascalCase / UPPER_SNAKE_CASE** 고정
- 한글명은 속성으로만 저장
- Text2Cypher 정확도를 위해 명명 규칙 엄격 준수

---

### 3.4 Phase 3: Graph 생성 파이프라인 (P1)

**목적**: 문서 메타데이터 → Graph DB 자동 변환

#### 신규 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | /api/admin/graph/schema/build | 스키마 생성 |
| POST | /api/admin/graph/build | 데이터 생성 |
| GET | /api/admin/graph/status | 상태 조회 |
| GET | /api/admin/graph/schema | 스키마 조회 |
| GET | /api/admin/graph/documents/{id}/relations | 문서별 관계 |

#### 처리 흐름

```
문서 메타데이터
    ↓
Organization 추출 → Organization 노드
    ↓
Project 추출 → Project 노드
    ↓
Document 노드 생성
    ↓
Keyword 노드 생성
    ↓
관계 생성 (HAS_DOCUMENT, HAS_KEYWORD, SAME_PROJECT 등)
    ↓
유사도 기반 SIMILAR_TO 관계 생성
```

---

### 3.5 Phase 4: Text2Cypher 테스트 API (P2)

**목적**: 관리자가 자연어 → Cypher 변환을 검증

#### 신규 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | /api/admin/graph/text2cypher/generate | Cypher 생성만 |
| POST | /api/admin/graph/text2cypher/execute | Cypher 실행 |
| POST | /api/admin/graph/text2cypher/test | 생성 + 실행 + 결과 |
| GET | /api/admin/graph/text2cypher/logs | 실행 로그 |

#### 요청/응답 예시

```json
// Request
{
  "question": "한국수자원공사 ISP 관련 수행 실적을 찾아줘",
  "schema_version": "v1",
  "readonly": true,
  "max_retry": 2
}

// Response
{
  "ok": true,
  "question": "한국수자원공사 ISP 관련 수행 실적을 찾아줘",
  "generated_cypher": "MATCH (o:Organization)-[:ORDERED]->(p:Project)-[:HAS_DOCUMENT]->(d:Document) WHERE o.name CONTAINS '한국수자원공사' RETURN d LIMIT 20",
  "records": [...],
  "execution_time_ms": 123,
  "retry_count": 0
}
```

---

### 3.6 Phase 5: Cypher Guard 보안 (P2 - 필수)

**목적**: Graph DB 보호 (삭제/변경 쿼리 차단)

#### 금지 키워드

```python
FORBIDDEN_CYPHER_KEYWORDS = [
    "CREATE", "MERGE", "DELETE", "DETACH DELETE",
    "SET", "REMOVE", "DROP", "LOAD CSV",
    "CALL DBMS", "CALL APOC"
]
```

#### 허용 키워드

```python
ALLOWED_CYPHER_KEYWORDS = [
    "MATCH", "OPTIONAL MATCH", "WHERE", "WITH",
    "RETURN", "ORDER BY", "LIMIT"
]
```

---

### 3.7 Phase 6: GraphRAG Agent 자동 수정 루프 (P2)

**목적**: 실패/0건 결과 시 쿼리 자동 수정

#### 처리 흐름

```
사용자 질문
    ↓
Graph Schema 조회
    ↓
1차 Cypher 생성
    ↓
읽기 전용 검사 (Cypher Guard)
    ↓
Cypher 실행
    ↓
결과 검증 (0건? 오류?)
    ↓ (실패 시)
Cypher 수정 프롬프트 생성
    ↓
2차 Cypher 실행
    ↓ (여전히 실패 시)
FAISS 검색 fallback
    ↓
최종 결과 반환
```

#### 재시도 정책

| 횟수 | 전략 |
|------|------|
| 1차 | 조건 완화 (CONTAINS 사용) |
| 2차 | 유사어/부분검색 사용 |
| 최종 실패 | FAISS 검색으로 fallback |

---

### 3.8 Phase 7: Hybrid RAG API (P3)

**목적**: FAISS + GraphRAG + Wiki 통합 검색

#### 신규 API

```
POST /api/rag/hybrid-query
```

#### 처리 흐름

```
사용자 질문
    ↓
┌──────────────┬──────────────┬──────────────┐
│ FAISS 검색   │ GraphRAG     │ Wiki 검색    │
│ (본문 의미)  │ (관계 검색)  │ (요약 검색)  │
└──────────────┴──────────────┴──────────────┘
    ↓
결과 병합 + 중복 제거
    ↓
근거 우선순위 계산
    ↓
최종 답변 생성
```

---

### 3.9 Phase 8: rag-assistant.html 연결 (P3)

**목적**: 사용자 화면에서 GraphRAG 결과 표시

#### 추가 작업

| 작업 | 내용 |
|------|------|
| 검색 모드 추가 | Hybrid RAG, GraphRAG 옵션 |
| GraphRAG 패널 | Generated Cypher, Retry Count 표시 |
| 관계 표시 | Related Projects, Related Documents |
| Graph 탭 연결 | GraphRAG Agent 결과와 연동 |

---

### 3.10 Phase 9: admin.html 관리자 검증 화면 (P3)

**목적**: 관리자가 GraphRAG Agent 동작 검증

#### 추가 메뉴

```
GRAPH / ONTOLOGY
├─ Graph Overview
├─ Schema Viewer
├─ Node / Edge Browser
├─ Text2Cypher Test
├─ Agent Retry Logs
├─ Failed Query Logs
└─ Graph Publish
```

---

### 3.11 Phase 10: LLM-Wiki / 제안서 초안 연결 (P4)

**목적**: GraphRAG를 제안서 작성 지원에 연결

#### 적용 예시

```
사용자: "경기주택도시공사 ISP 사업 제안서 초안 작성에 참고할 기존 수행 실적"

FAISS:
- ISP 관련 제안서 본문 검색

GraphRAG:
- 경기주택도시공사와 유사 기관
- ISP 관련 프로젝트
- 같은 키워드 수행 실적

LLM-Wiki:
- 해당 프로젝트 요약 페이지
- 기관별 수행 이력 요약

최종:
- 제안서 작성 참고자료
- 근거 문서 목록
- 추천 문단
```

---

## 4. 우선순위 매트릭스

```
           높은 영향
              │
    P1        │        P0
 (Dataset     │    (코드 안정화)
  Builder)    │
              │
──────────────┼──────────────
              │
    P3        │        P2
 (UI 연결)    │    (Text2Cypher)
              │
           낮은 영향
     낮은 긴급도    높은 긴급도
```

---

## 5. 작업 일정 (권장)

### Week 1: 기반 정리

| Day | Phase | 작업 |
|-----|-------|------|
| 1 | Phase 0 | .gitattributes, diff 정리 |
| 2 | Phase 0 | 선택 문서 답변 API 계약, Graph 스키마 초안 |
| 3-4 | Phase 1 | Dataset Builder Step 1-5 설정 변수 UI |
| 5 | Phase 1 | Dataset Builder Step 6-10 (Graph/Wiki/Test) |

### Week 2: Graph 인프라

| Day | Phase | 작업 |
|-----|-------|------|
| 1 | Phase 2 | Graph 데이터 모델 확정 |
| 2-3 | Phase 3 | Graph Build API 구현 |
| 4-5 | Phase 4 | Text2Cypher Test API 구현 |

### Week 3: Agent 구현

| Day | Phase | 작업 |
|-----|-------|------|
| 1 | Phase 5 | Cypher Guard 구현 |
| 2-3 | Phase 6 | GraphRAG Agent 자동 수정 루프 |
| 4-5 | Phase 7 | Hybrid RAG API |

### Week 4: UI 연결

| Day | Phase | 작업 |
|-----|-------|------|
| 1-2 | Phase 8 | rag-assistant.html 연결 |
| 3-4 | Phase 9 | admin.html 관리자 검증 화면 |
| 5 | Phase 10 | LLM-Wiki / 제안서 초안 연결 |

---

## 6. 완료 기준

| 항목 | 기준 |
|------|------|
| Phase 0 | `git diff` 깨끗, 선택 문서 API 문서화 완료 |
| Phase 1 | Dataset Builder Step별 request body 표시 |
| Phase 2 | Node/Relation 목록 확정, 스키마 문서화 |
| Phase 3 | Graph Build 실행 후 admin.html에서 확인 가능 |
| Phase 4 | 질문 → Cypher → 결과 확인 가능 |
| Phase 5 | 쓰기/삭제 쿼리 100% 차단 |
| Phase 6 | 실패 쿼리 자동 수정 후 재실행 |
| Phase 7 | FAISS + Graph 결과 병합 |
| Phase 8 | rag-assistant.html에서 Hybrid RAG 결과 표시 |
| Phase 9 | admin.html에서 Agent 로그 확인 |
| Phase 10 | 제안서 초안에 관련 실적 자동 추천 |

---

## 7. 신규 파일 목록 (예상)

### Backend

```
backend/app/services/
├─ graph_build_service.py      # Graph 데이터 생성
├─ graph_query_service.py      # Graph 조회
├─ text2cypher_service.py      # Text → Cypher 변환
├─ cypher_guard.py             # Cypher 보안 검사
└─ hybrid_search_service.py    # FAISS + Graph + Wiki 통합

backend/app/agents/
└─ graphrag_agent.py           # GraphRAG Agent (자동 수정 루프)

backend/app/api/
├─ graph_admin.py              # 관리자용 Graph API
└─ graph_agent.py              # GraphRAG Agent API
```

### Frontend

```
frontend/
├─ rag-assistant.html          # GraphRAG 패널 추가
└─ admin.html                  # Graph/Ontology 메뉴 추가
```

### 설정/문서

```
.gitattributes                  # 줄바꿈 정책
docs/
├─ graph_schema.md             # Graph 스키마 정의서
├─ api_graph_admin.md          # Graph 관리 API 명세
└─ api_hybrid_rag.md           # Hybrid RAG API 명세
```

---

## 8. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| Graph DB 미설치 | 높음 | Neo4j 또는 인메모리 Graph 라이브러리 검토 |
| Text2Cypher 정확도 낮음 | 중간 | 스키마 기반 프롬프트 고도화, 재시도 루프 |
| LLM API 비용 증가 | 중간 | max_retry 제한, 캐시 도입 |
| 기존 UI 충돌 | 낮음 | 단계별 테스트, 롤백 계획 |

---

## 9. 다음 단계 (오늘 시작)

### 즉시 실행 가능한 작업

1. **`.gitattributes` 파일 생성**
   - HTML/JS/CSS/PY/MD 줄바꿈 LF 고정

2. **선택 문서 답변 API 계약 문서화**
   - `runQueryWithSelectedDocs()` 분석
   - 필요한 API 엔드포인트 정의

3. **Graph 응답 스키마 표준화 초안**
   - 현재 graph_context, relations, edge, chain, entity 분석
   - 표준 구조 제안

### 사용자 확인 필요 사항

| 항목 | 질문 |
|------|------|
| Graph DB | Neo4j 사용 여부? 또는 NetworkX 등 인메모리? |
| LLM 선택 | Text2Cypher에 사용할 LLM? (Ollama gemma4 / Claude API) |
| 우선순위 조정 | Phase 0부터 순서대로 진행? 또는 특정 Phase 우선? |

---

**End of Document**
