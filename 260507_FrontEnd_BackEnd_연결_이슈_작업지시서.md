# FrontEnd ↔ BackEnd 연결 이슈 작업지시서

**작성일**: 2026-05-07  
**분석 대상**: `http://192.168.0.207:9284/weeslee-rag/frontend/rag-assistant.html`  
**서버 환경**:
- XAMPP Apache (HTML 서빙): `http://192.168.0.207:9284`
- FastAPI 백엔드: `http://192.168.0.207:8080`

---

## 진단 요약 (실측 결과)

| 항목 | 상태 | 비고 |
|------|------|------|
| HTML 서빙 (포트 9284) | ✅ 정상 | XAMPP Apache |
| FastAPI 서버 (포트 8080) | ✅ 정상 | uvicorn |
| API_BASE 자동 감지 | ❌ 오작동 | 포트 9284를 API 베이스로 오인 |
| `/health/all` 경로 | ❌ 404 | prefix 불일치 |
| CORS (9284 → 8080) | ❌ 차단 | 9284가 허용 목록 미포함 |
| `/api/rag/query` | ✅ 정상 | 카테고리 필터 포함 |
| DB (MySQL) | ❌ 연결 실패 | health degraded, RAG는 무관 |
| VectorDB 표시 | ⚠️ 의미 없음 | ChromaDB 0 collections (실제는 FAISS) |

---

## Issue #1 — API_BASE 자동 감지 오류 [CRITICAL]

### 현상

```javascript
// 현재 코드
const API_BASE = window.__API_BASE__ || (
  window.location.origin === 'null'
    ? 'http://192.168.0.207:8080/api'
    : `${window.location.origin}/api`   // ← 이 분기가 실행됨
);
```

브라우저에서 `http://192.168.0.207:9284/...` 로 열면:

- `window.location.origin` = `http://192.168.0.207:9284`
- `API_BASE` = `http://192.168.0.207:9284/api` ← **XAMPP에 없는 경로**
- 결과: 모든 API 요청 404

`origin === 'null'` 분기는 `file://` 로컬 오픈 시에만 실행됨 — XAMPP 서빙 시 무의미.

### 수정 방법 (2가지 중 택 1)

**방법 A — HTML 하드코딩 수정 (즉시 적용 가능)**

```html
<!-- frontend/rag-assistant.html -->
<script>
  const API_BASE = 'http://192.168.0.207:8080/api';
</script>
```

**방법 B — XAMPP Apache 리버스 프록시 (운영 권장)**

`c:\xampp\apache\conf\extra\httpd-vhosts.conf` 또는 `httpd.conf`에 추가:

```apache
ProxyPass /api http://192.168.0.207:8080/api
ProxyPassReverse /api http://192.168.0.207:8080/api
```

그러면 `http://192.168.0.207:9284/api/rag/query` → `http://192.168.0.207:8080/api/rag/query` 로 투명 프록시.  
HTML 코드 변경 불필요.

**방법 C — window.__API_BASE__ 주입 (서버사이드)**

FastAPI에서 HTML을 직접 서빙하는 경우 (현재 `/weeslee-rag/frontend` 마운트):

```html
<script>
  window.__API_BASE__ = 'http://192.168.0.207:8080/api';
</script>
```

→ HTML 첫 줄에 삽입하면 자동 감지 로직보다 우선 적용됨.

---

## Issue #2 — `/api/health/all` 경로 404 [HIGH]

### 현상

HTML 코드:
```javascript
const response = await fetch(`${API_BASE}/health/all`);
// API_BASE = http://192.168.0.207:8080/api 이면
// → GET http://192.168.0.207:8080/api/health/all  ← 404
```

`main.py`에서 health 라우터는 `/api` prefix **없이** 마운트됨:

```python
# main.py
app.include_router(health_router, tags=["Health"])   # prefix 없음
# → GET /health/all   (O)
# → GET /api/health/all  (X)
```

실측 확인:
```
GET /health/all   → 200 OK (status: degraded)
GET /api/health/all → 404 Not Found
```

### 수정 방법 (2가지 중 택 1)

**방법 A — main.py health 라우터에 /api prefix 추가**

```python
# backend/app/main.py
app.include_router(health_router, prefix="/api", tags=["Health"])
```

→ `/api/health`, `/api/health/all`, `/api/health/ollama` 모두 사용 가능.

**방법 B — HTML에서 경로 수정**

```javascript
// frontend/rag-assistant.html
const response = await fetch(`${window.location.origin.replace(':9284', ':8080')}/health/all`);
// 또는 prefix 없이
const response = await fetch('http://192.168.0.207:8080/health/all');
```

---

## Issue #3 — CORS 차단 (포트 9284 → 8080) [HIGH]

### 현상

```python
# backend/app/core/config.py
cors_origins: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "null",
]
```

`http://192.168.0.207:9284` 가 허용 목록에 없음 → 브라우저 CORS 차단.

실측: `Access-Control-Allow-Origin: MISSING` (헤더 없음)

### 수정 방법

```python
# backend/app/core/config.py 또는 .env

cors_origins: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://192.168.0.207:9284",   # ← 추가
    "http://192.168.0.207:8080",   # ← 추가
    "null",
]
```

또는 `.env`에서 환경변수로 관리:

```env
CORS_ORIGINS=["http://localhost:3000","http://192.168.0.207:9284","http://192.168.0.207:8080","null"]
```

---

## Issue #4 — Health 상태 표시 왜곡 [MEDIUM]

### 현상

`/health/all` 응답:

```json
{
  "status": "degraded",
  "components": {
    "database": { "status": "unhealthy", "error": "Access denied (root@localhost)" },
    "ollama":   { "status": "healthy", "model_count": 9 },
    "vectordb": { "status": "healthy", "collections_count": 0 }
  }
}
```

HTML에서:
```javascript
document.getElementById('apiStatus').className =
  data.status === 'healthy' ? 'value ok' : 'value warn';   // ← "degraded"이므로 항상 warn 표시
```

→ MySQL DB가 RAG 동작과 무관함에도 API 상태가 항상 경고색으로 표시됨.

### 수정 방법

**방법 A — HTML 표시 로직 수정**

```javascript
// API 상태 = ollama + RAG 기준으로 판단
const ragHealthy = data.components?.ollama?.status === 'healthy';
document.getElementById('apiStatus').textContent = ragHealthy ? 'healthy' : 'degraded';
document.getElementById('apiStatus').className = ragHealthy ? 'value ok' : 'value warn';
```

**방법 B — health/all에서 DB를 non-critical로 변경**

```python
# backend/app/api/health.py
# DB 오류 시 status를 "degraded"가 아닌 "healthy" 유지 (RAG에 DB 불필요)
except Exception as e:
    results["components"]["database"] = {"status": "unavailable", "error": str(e)}
    # results["status"] = "degraded"  ← 제거
```

---

## Issue #5 — VectorDB 표시 항목 부정확 [MEDIUM]

### 현상

HTML이 표시하는 "VectorDB" 상태는 **ChromaDB** (collections=0)를 의미함.  
실제 RAG 시스템은 **FAISS** 기반이고 ChromaDB는 사용하지 않음.

```javascript
document.getElementById('vectorStatus').textContent =
  data.components?.vectordb?.status || '-';
// → "healthy" 출력 (ChromaDB 빈 인스턴스 — 실제 사용 안 함)
```

사용자에게 "VectorDB OK"로 보이지만 의미 없는 정보.

### 수정 방법

**방법 A — FAISS 상태 표시로 교체**

`/health/all`에 FAISS 상태 추가:

```python
# backend/app/api/health.py
from pathlib import Path
from app.core.config import settings

# FAISS index health
faiss_index = Path(f"data/indexes/faiss/{settings.faiss_snapshot}_ollama.index")
results["components"]["faiss"] = {
    "status": "healthy" if faiss_index.exists() else "unhealthy",
    "snapshot": settings.faiss_snapshot,
    "index_exists": faiss_index.exists(),
}
```

HTML:

```javascript
document.getElementById('vectorStatus').textContent =
  data.components?.faiss?.snapshot?.split('_').slice(-1)[0] || '-';
// → "combined-v2" 같은 실용적인 정보 표시
```

---

## Issue #6 — UI에 category 필터 없음 [MEDIUM]

### 현상

현재 UI 입력 항목: Query, Top K, Top Docs, Model  
API가 지원하는 필드: `category`, `max_chunks_per_doc`, `answer_provider`

사용자가 "rfp만 검색하고 싶다"는 의도를 표현할 방법 없음.

### 수정 방법

Query 섹션에 추가:

```html
<div class="row">
  <div>
    <label>Category</label>
    <select id="category">
      <option value="">전체 (combined)</option>
      <option value="rfp">RFP</option>
      <option value="proposal">Proposal</option>
      <option value="kickoff">Kickoff</option>
      <option value="final_report">Final Report</option>
      <option value="presentation">Presentation</option>
    </select>
  </div>
  <div><label>Max Chunks/Doc</label><input id="maxChunks" type="number" min="1" max="10" value="3"></div>
  <div>
    <label>Answer Mode</label>
    <select id="answerProvider">
      <option value="ollama">Ollama (생성)</option>
      <option value="none">검색만 (빠름)</option>
    </select>
  </div>
</div>
```

JS `runQuery()` 수정:

```javascript
const category = document.getElementById('category').value;
const maxChunks = parseInt(document.getElementById('maxChunks').value || '3', 10);
const answerProvider = document.getElementById('answerProvider').value;

body: JSON.stringify({
  query,
  top_k: topK,
  top_docs: topDocs,
  answer_provider: answerProvider,
  answer_model: answerProvider === 'none' ? '' : answerModel,
  ...(category ? { category } : {}),
  max_chunks_per_doc: maxChunks
})
```

---

## Issue #7 — project_name이 결과 카드에 표시 안 됨 [LOW]

### 현상

`/api/rag/query` 응답에 `project_name` 필드가 포함되어 있지만 현재 렌더링에서 사용되지 않음.

```javascript
// 현재 결과 카드
`<div class="doc-title">#${doc.rank} ${doc.document_id}</div>`
// document_id: "DOC-20260506B3-000037" → 비직관적
```

사용자에게 어떤 프로젝트 문서인지 바로 보이지 않음.

### 수정 방법

```javascript
// project_name을 doc-title에 우선 표시
const title = doc.project_name
  ? `#${doc.rank} ${doc.project_name}`
  : `#${doc.rank} ${doc.document_id}`;

`<div class="doc-title">${escapeHtml(title)}</div>
 <div class="meta"><span class="muted">${doc.document_id}</span></div>`
```

---

## 작업 우선순위 및 순서

| 순서 | Issue | 난이도 | 예상 시간 |
|------|-------|--------|---------|
| 1 | **#1** API_BASE 하드코딩 (방법 A) | 낮음 | 5분 |
| 2 | **#3** CORS 허용 목록 추가 | 낮음 | 5분 |
| 3 | **#2** health 라우터 /api prefix 추가 | 낮음 | 5분 |
| 4 | **#4** health 표시 로직 수정 | 낮음 | 10분 |
| 5 | **#5** FAISS 상태 표시로 교체 | 중간 | 20분 |
| 6 | **#6** category/mode 필터 UI 추가 | 중간 | 30분 |
| 7 | **#7** project_name 카드 표시 | 낮음 | 10분 |

**1, 2, 3번 먼저 처리하면 즉시 브라우저에서 동작함.**

---

## 빠른 검증 방법 (작업 후 확인)

```javascript
// 브라우저 DevTools Console에서 실행
fetch('http://192.168.0.207:8080/health/all')
  .then(r => r.json()).then(console.log)

fetch('http://192.168.0.207:8080/api/rag/query', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({query: "ISP 제안서", top_k: 5, answer_provider: "none"})
}).then(r => r.json()).then(d => console.log('docs:', d.documents?.length))
```

현재 실측 기준 API 자체 정상 동작 확인:

```
✅ POST /api/rag/query         → success=True, docs 반환
✅ POST /api/rag/query?category=rfp → cats=['rfp', 'rfp', ...]
✅ POST /api/rag/query + answer_provider=none → 빠른 검색 전용
✅ GET  /health                → {"status":"healthy"}
❌ GET  /api/health/all        → 404 (prefix 문제)
✅ GET  /health/all            → degraded (DB 없음, RAG는 정상)
❌ CORS 9284→8080              → Access-Control-Allow-Origin 없음
```
