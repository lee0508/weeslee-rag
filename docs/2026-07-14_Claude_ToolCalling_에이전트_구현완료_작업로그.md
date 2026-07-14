# LLM Tool Calling 에이전트 구현 완료 보고

## 1. 문서 정보

- 프로젝트: weeslee-rag
- 작성일: 2026-07-14
- 작성자: Claude
- 문서유형: 작업로그
- 관련 파일:
  - `backend/app/services/tool_registry.py` (신규)
  - `backend/app/services/tool_executor.py` (신규)
  - `backend/app/services/tools/__init__.py` (신규)
  - `backend/app/services/tools/data_analysis.py` (신규)
  - `backend/app/services/tools/document_search.py` (신규)
  - `backend/app/services/tools/statistics.py` (신규)
  - `backend/app/api/rag.py` (수정)
  - `frontend/rag-assistant.html` (수정)
- 관련 URL:
  - https://server.weeslee.co.kr/weeslee-rag/frontend/rag-assistant.html
- 선행 문서:
  - `docs/2026-07-14_Lee_QA1.md` (Tool Calling 설계 요청)

## 2. 작업 배경

사용자 질문: "지속가능발전포털 데이터는 단순 게시형 정보인지, 목표·지표·정책과제·평가·환류와 연결된 구조화 데이터인지, 유관기관 데이터와 연계 가능한 형태인지 진단해줘"

이 질문은 단순 RAG 검색으로 답변할 수 없고, LLM이 적절한 분석 도구를 선택하여 실행해야 한다. 이를 위해 Ollama Tool Calling 기반 에이전트 계층을 추가했다.

## 3. 구현 아키텍처

```
frontend/rag-assistant.html
        │  (기존 /api/rag/query 유지)
        ▼
FastAPI backend
 ├─ /api/rag/query              ← 기존 검색+답변 (변경 없음)
 ├─ /api/rag/query-with-tools   ← 신규: Tool Calling 에이전트 ★
 ├─ /api/rag/tools              ← 신규: 등록된 도구 목록 조회
 └─ /api/rag/tool/{name}        ← 신규: 특정 도구 직접 실행
         │
         ▼
   tool_executor.py + tool_registry.py
    ├─ Tool 0: analyze_data_structure    ← 데이터 구조 분석
    ├─ Tool 1: diagnose_data_quality     ← 품질 진단 (완전성/일관성/구조화/연계)
    ├─ Tool 2: analyze_data_linkage      ← 연계 가능성 분석
    ├─ Tool 3: search_documents          ← RAG 문서 검색
    ├─ Tool 4: query_graph_relations     ← GraphRAG 관계 조회
    ├─ Tool 5: get_document_details      ← 문서 상세 조회
    ├─ Tool 6: calculate_statistics      ← 통계 계산
    ├─ Tool 7: aggregate_by_field        ← 필드 기준 집계
    └─ Tool 8: compare_datasets          ← 데이터셋 비교
```

## 4. 구현 파일 상세

### 4.1 tool_registry.py (도구 레지스트리)

```python
# 핵심 구조
@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    required: list[str]

class ToolRegistry:
    def register(self, tool: ToolDefinition) -> None
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]
    def get_all_definitions(self, format: str = "ollama") -> list[dict]

# 데코레이터 방식 등록
@register_tool(
    name="diagnose_data_quality",
    description="데이터 품질 진단",
    parameters={...},
    required=["dataset_name"]
)
def diagnose_data_quality(dataset_name: str, criteria: list = None):
    ...
```

### 4.2 tool_executor.py (실행 엔진)

```python
class ToolExecutor:
    def execute_with_tools(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        max_tool_calls: int = 5,
    ) -> dict[str, Any]:
        """
        Tool Calling 루프 실행:
        1. LLM 호출 (messages + tools 스키마 전달)
        2. tool_calls 응답 확인
        3. 도구 실행 → 결과를 role="tool"로 추가
        4. 재호출 (max_iterations까지 반복)
        5. 최종 답변 반환
        """
```

### 4.3 tools/ 모듈

| 파일 | 도구 | 기능 |
|------|------|------|
| data_analysis.py | `analyze_data_structure` | 스키마/필드/관계 분석 |
| data_analysis.py | `diagnose_data_quality` | 완전성/일관성/구조화/연계성 진단 |
| data_analysis.py | `analyze_data_linkage` | 유관기관 연계 가능성 분석 |
| document_search.py | `search_documents` | RAG 문서 검색 |
| document_search.py | `query_graph_relations` | GraphRAG 관계 조회 |
| document_search.py | `get_document_details` | 문서 상세 조회 |
| statistics.py | `calculate_statistics` | 문서/청크 통계 |
| statistics.py | `aggregate_by_field` | 필드 기준 집계 |
| statistics.py | `compare_datasets` | 데이터셋 비교 |

### 4.4 rag.py (API 엔드포인트)

```python
class ToolCallingRequest(BaseModel):
    query: str
    enable_tools: bool = True
    max_tool_calls: int = 5
    model: Optional[str] = None
    system_prompt: Optional[str] = None

@router.post("/query-with-tools")
async def query_with_tools(request: ToolCallingRequest):
    """Tool Calling 기반 쿼리 실행"""

@router.get("/tools")
async def list_tools():
    """등록된 도구 목록 조회"""

@router.post("/tool/{tool_name}")
async def execute_tool(tool_name: str, arguments: dict):
    """특정 도구 직접 실행"""
```

### 4.5 rag-assistant.html (프론트엔드)

```javascript
// 검색 모드 드롭다운에 추가
<option value="tool_calling" data-i18n="mode_tool">데이터 분석</option>

// i18n 추가
mode_tool: '데이터 분석',
hint_tool: 'LLM이 데이터 분석 도구를 선택하여 실행합니다...',
query_example_tool: '지속가능발전포털 데이터가 구조화 데이터인지 진단해줘',

// Tool Calling API 호출
} else if (effectiveMode === 'tool_calling') {
  const toolPayload = {
    query: effectiveQuery,
    enable_tools: true,
    max_tool_calls: 5,
    model: answerModel,
  };
  const response = await fetch(`${API_BASE}/rag/query-with-tools`, {...});
  data = transformToolCallingResponse(toolData, effectiveQuery);
}
```

## 5. 테스트 결과

### 5.1 도구 목록 조회

```bash
curl -s http://127.0.0.1:8080/api/rag/tools
```

**응답:**
```json
{
  "success": true,
  "tools": [
    {"name": "analyze_data_structure", "description": "데이터셋의 구조를 분석합니다..."},
    {"name": "diagnose_data_quality", "description": "데이터 품질을 진단합니다..."},
    {"name": "analyze_data_linkage", "description": "데이터 연계 가능성을 분석합니다..."},
    {"name": "search_documents", "description": "RAG 기반 문서 검색..."},
    {"name": "query_graph_relations", "description": "GraphRAG 관계 조회..."},
    {"name": "get_document_details", "description": "문서 상세 정보 조회..."},
    {"name": "calculate_statistics", "description": "데이터셋 통계 계산..."},
    {"name": "aggregate_by_field", "description": "필드 기준 집계..."},
    {"name": "compare_datasets", "description": "데이터셋 비교 분석..."}
  ],
  "total": 9
}
```

### 5.2 Tool Calling 쿼리 실행

```bash
curl -X POST http://127.0.0.1:8080/api/rag/query-with-tools \
  -H 'Content-Type: application/json' \
  -d '{"query":"지속가능발전포털 데이터의 품질을 진단해줘","enable_tools":true}'
```

**응답 (요약):**
```json
{
  "success": true,
  "query": "지속가능발전포털 데이터의 품질을 진단해줘",
  "tool_calls_count": 1,
  "tool_results": [{
    "tool": "diagnose_data_quality",
    "arguments": {
      "dataset_name": "지속가능발전포털",
      "criteria": ["completeness", "consistency", "structure_level", "linkability"]
    },
    "result": {
      "overall_score": 0.62,
      "results": {
        "completeness": {"score": 0.20, "total_documents": 551, "total_chunks": 1096},
        "consistency": {"score": 1.0, "missing_fields": []},
        "structure_level": {"score": 0.3, "structure_type": "단순 게시형"},
        "linkability": {"score": 1.0, "linkable_field_count": 12}
      },
      "recommendations": ["데이터가 단순 게시형입니다. 목표-지표-정책과제-평가 연결 구조화가 필요합니다."]
    }
  }],
  "answer": "## 지속가능발전포털 데이터 품질 진단 보고서\n\n**종합 점수: 0.62 / 1.0 (보통 수준)**\n\n| 진단 영역 | 점수 | 평가 요약 |\n|---|---|---|\n| 완전성 | 0.20 | 청크 수 대비 문서 밀도 낮음 |\n| 일관성 | 1.0 | 필수 필드 모두 존재 |\n| 구조화 수준 | 0.3 | 단순 게시형, 계층 구조 없음 |\n| 연계 가능성 | 1.0 | 12개 연계 필드 보유 |\n\n**권고 사항:** 목표→지표→정책과제→평가 연결 구조화 필요"
}
```

## 6. 안전장치

| 장치 | 설명 |
|------|------|
| 화이트리스트 실행 | TOOL_REGISTRY에 등록된 함수만 실행 |
| 반복 상한 | `max_tool_calls=5` (LLM 폭주 방지) |
| 도구별 타임아웃 | Ollama 120초, DB 5초 |
| Degraded 폴백 | 모델 tool 미지원 시 일반 답변 반환 |

## 7. Git 커밋

```
commit 3bdbbee
feat: Tool Calling 기능 추가 (LLM 데이터 분석 에이전트)

- tool_registry.py: 도구 정의 및 레지스트리 시스템
- tool_executor.py: Ollama 통합 Tool Calling 실행 엔진
- tools/data_analysis.py: 데이터 구조 분석, 품질 진단, 연계 분석
- tools/document_search.py: RAG 문서 검색, GraphRAG 관계 조회
- tools/statistics.py: 통계 계산, 필드 집계, 데이터셋 비교
- rag.py: /query-with-tools, /tools, /tool/{name} API 엔드포인트
- rag-assistant.html: 데이터 분석 모드 UI (tool_calling)
```

## 8. 다음 단계 (제안)

1. **qwen2.5:14b 모델 설치** - 더 정확한 Tool Calling 지원
2. **외부 API 연동** - 통계청, 환경부 등 유관기관 API 화이트리스트 등록
3. **LangGraph Phase 2** - 현재 도구들을 ToolNode로 승격

## 9. 사용 방법

### 프론트엔드
1. rag-assistant.html 접속
2. 검색 모드에서 "데이터 분석" 선택
3. 질문 입력 (예: "지속가능발전포털 데이터 품질 진단해줘")
4. RAG 실행

### API 직접 호출
```bash
# 도구 목록 조회
curl http://server.weeslee.co.kr:8080/api/rag/tools

# Tool Calling 쿼리
curl -X POST http://server.weeslee.co.kr:8080/api/rag/query-with-tools \
  -H 'Content-Type: application/json' \
  -d '{"query":"데이터 구조 분석해줘","enable_tools":true}'

# 특정 도구 직접 실행
curl -X POST http://server.weeslee.co.kr:8080/api/rag/tool/diagnose_data_quality \
  -H 'Content-Type: application/json' \
  -d '{"dataset_name":"지속가능발전포털","criteria":["structure_level"]}'
```
