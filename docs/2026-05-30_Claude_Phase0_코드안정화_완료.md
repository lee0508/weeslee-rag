# Phase 0 코드 안정화 완료 보고서

**작성일**: 2026-05-30
**작성자**: Claude
**버전**: 1.0

---

## 1. 개요

GraphRAG 적용을 위한 Phase 0 코드 안정화 작업을 완료했다. 작업지시서(`2026-05-30_Lee_기능개선_작업지시서.md`)에 명시된 Phase 0 항목들을 점검하고 필요한 정책 파일과 스키마 문서를 작성했다.

---

## 2. 완료 항목

### 2.1 .gitattributes 줄바꿈 정책 설정

**파일**: `.gitattributes`

모든 텍스트 파일의 줄바꿈을 LF로 통일하여 Windows/macOS/Linux 환경 간 불필요한 diff를 방지한다.

| 파일 유형 | 정책 |
|-----------|------|
| HTML, CSS, JS, TS | `text eol=lf` |
| Python, Shell | `text eol=lf` |
| Markdown, TXT | `text eol=lf` |
| YAML, JSON, TOML | `text eol=lf` |
| 이미지, PDF, HWP | `binary` |
| DB, FAISS 인덱스 | `binary` |

### 2.2 rag-assistant.html 점검

Phase 4 UI/UX 개선 작업에서 +504줄 변경이 발생했다. 변경 내용은 모두 의도된 기능 추가이며 불필요한 diff는 없음을 확인했다.

| 기능 | 상태 |
|------|------|
| 서버 상태 축소형 표시 | 정상 동작 |
| 검색 설정 그룹화 | 정상 동작 |
| 마크다운 렌더링 | 정상 동작 |
| 사이드바 토글 | 정상 동작 |
| Citation 앵커 연결 | 정상 동작 |

### 2.3 선택 문서 답변 UI DOM ID 확인

| DOM ID | 용도 |
|--------|------|
| `selectedDocsIndicator` | 선택 문서 개수 배지 |
| `runSelectedBtn` | 선택 문서 답변 버튼 |

`_selectedDocIndices` Set과 `updateSelectedDocsCount()` 함수로 문서 선택 상태를 관리한다.

### 2.4 runQueryWithSelectedDocs() API 연결 준비

현재 프론트엔드에 구현된 `runQueryWithSelectedDocs()` 함수의 요청 형태를 분석했다.

**프론트엔드 요청 파라미터**:
```javascript
{
  query: string,
  search_mode: string,
  top_k: number,
  top_docs: number,
  organization: string,
  category: string,
  answer_mode: string,
  model: string,
  selected_document_ids: string[]  // 추가 필요
}
```

**백엔드 수정 필요 사항**:

`backend/app/api/rag.py`의 `RagQueryRequest`에 다음 필드 추가 필요.

```python
class RagQueryRequest(BaseModel):
    # 기존 필드들...
    selected_document_ids: Optional[List[str]] = None  # 추가
```

`_run_query()` 함수에서 `selected_document_ids`가 있으면 해당 문서만 필터링하여 컨텍스트로 사용해야 한다.

---

## 3. Graph 응답 스키마 표준화 초안

### 3.1 현재 상태

현재 `graph_context`는 다음 두 가지 형태가 혼재한다.

**형태 A (chain)**:
```json
{
  "graph_context": [
    {
      "project_name": "프로젝트명",
      "chain": [
        { "category": "rfp", "documents": [...] },
        { "category": "proposal", "documents": [...] }
      ]
    }
  ]
}
```

**형태 B (related_docs)**:
```json
{
  "graph_context": [
    {
      "project_name": "프로젝트명",
      "related_docs": [
        { "category": "proposal", "file_name": "..." }
      ]
    }
  ]
}
```

### 3.2 표준화 스키마 (제안)

모든 Graph 응답은 다음 스키마를 따른다.

```typescript
interface GraphContextItem {
  project_name: string;
  organization?: string;

  // 문서 체인 (RFP → 제안서 → 착수 → 보고서 순서)
  document_chain: DocumentChainItem[];

  // 관련 문서 (체인 외 유사 문서)
  related_documents: RelatedDocument[];

  // 관계 정보 (향후 Neo4j 연동 시 사용)
  relations?: Relation[];
}

interface DocumentChainItem {
  category: 'rfp' | 'proposal' | 'kickoff' | 'final_report' | 'presentation';
  document_count: number;
  documents: DocumentRef[];
}

interface DocumentRef {
  document_id: string;
  file_name: string;
  source_path: string;
  score?: number;
}

interface RelatedDocument {
  document_id: string;
  category: string;
  file_name: string;
  source_path: string;
  relation_type: 'similar' | 'same_project' | 'same_organization' | 'same_keyword';
  score?: number;
}

interface Relation {
  source_id: string;
  target_id: string;
  relation_type: string;
  properties?: Record<string, any>;
}
```

### 3.3 변환 함수 (제안)

`backend/app/services/graph_traversal.py`에 다음 함수 추가.

```python
def standardize_graph_context(raw_context: list[dict]) -> list[dict]:
    """기존 graph_context를 표준 스키마로 변환한다."""
    result = []
    for ctx in raw_context:
        item = {
            "project_name": ctx.get("project_name", ""),
            "organization": ctx.get("organization", ""),
            "document_chain": [],
            "related_documents": [],
            "relations": [],
        }

        # chain 형태 처리
        if "chain" in ctx:
            for chain_item in ctx["chain"]:
                item["document_chain"].append({
                    "category": chain_item.get("category", "unknown"),
                    "document_count": len(chain_item.get("documents", [])),
                    "documents": [
                        {
                            "document_id": doc.get("document_id", ""),
                            "file_name": doc.get("file_name", ""),
                            "source_path": doc.get("source_path", ""),
                        }
                        for doc in chain_item.get("documents", [])
                    ],
                })

        # related_docs 형태 처리
        if "related_docs" in ctx:
            for doc in ctx["related_docs"]:
                item["related_documents"].append({
                    "document_id": doc.get("document_id", ""),
                    "category": doc.get("category", ""),
                    "file_name": doc.get("file_name", ""),
                    "source_path": doc.get("source_path", ""),
                    "relation_type": "same_project",
                })

        result.append(item)
    return result
```

---

## 4. 다음 단계 (Phase 1)

Phase 0 완료 후 Phase 1 작업을 시작할 수 있다.

### Phase 1 Dataset Builder 설정 변수 UI 완성

1. Step별 필수/선택 파라미터 표시
2. request body 미리보기 추가
3. 입력값 검증 추가
4. 신규 Step 추가
   - Step 6: Graph Schema Build
   - Step 7: Graph Data Build
   - Step 8: LLM-Wiki Build
   - Step 9: Text2Cypher Test
   - Step 10: Hybrid RAG Publish

---

## 5. 파일 변경 요약

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `.gitattributes` | 신규 | 줄바꿈 정책 설정 |
| `docs/2026-05-30_Claude_Phase0_코드안정화_완료.md` | 신규 | 본 문서 |

---

**End of Document**
