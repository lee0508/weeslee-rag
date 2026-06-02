# weeslee-rag 코딩 패턴 스킬

---
name: weeslee-rag-patterns
description: PromptoRAG 프로젝트에서 추출한 코딩 패턴 및 워크플로우
version: 1.2.0
source: local-git-analysis
analyzed_commits: 200
conventional_commits_ratio: 45%
last_analyzed: 2026-06-02
---

## 커밋 컨벤션

이 프로젝트는 **혼합형 커밋 메시지** 스타일을 사용합니다 (최근 200개 커밋 분석 기준).

### 주요 패턴 분포

1. **Conventional Commits (약 45%)** - `feat:`, `fix:`, `docs:`, `chore:` 등
2. **Phase-based Commits (약 25%)** - `Phase N:`, `Figma PN:` 등 단계별 작업
3. **Component Prefix (약 20%)** - `UI:`, `Fix:`, `RAG`, `admin` 등 컴포넌트 기반
4. **한글 설명형 (약 10%)** - 명확한 한글 작업 설명

| 접두사 | 용도 | 예시 |
|--------|------|------|
| `feat:` | 새로운 기능 추가 | `feat: Phase 7 Hybrid RAG API 구현` |
| `feat(scope):` | 스코프 지정 기능 | `feat(admin): RAG Build Wizard Stepper UI 상태 연동` |
| `fix:` | 버그 수정 | `fix: mask graph edge lines behind labels` |
| `fix(scope):` | 스코프 지정 수정 | `fix(rag): use fallback values for document_group` |
| `chore:` | 유지보수 작업 | `chore: Hide result panel title and improve graph edge labels` |
| `docs:` | 문서 업데이트 | `docs: Phase 0 코드 안정화 및 GraphRAG 작업계획서 작성` |
| `Phase N:` | 단계별 기능 구현 | `Phase 10: GraphRAG + Wiki 통합 제안서 초안 생성 기능` |
| `Figma PN:` | Figma 디자인 구현 | `Figma P1 대시보드 Overview 개편` |
| `UI:` | UI 변경 사항 | `UI: 검색 모드를 버튼에서 셀렉트 박스로 변경` |
| 한글 설명 | 직관적 작업 설명 | `Dataset Builder Source ID 표시 개선` |

### 커밋 메시지 작성 원칙

- **명확성**: 무엇을 왜 변경했는지 한눈에 파악 가능하게
- **구체성**: 기술적 수치나 파일명 포함 (`81.8% 달성`, `admin.html`)
- **한글 우선**: 한글로 작성하되, 기술 용어는 영문 병기
- **Phase/Step 명시**: 큰 작업은 단계로 구분

### 커밋 메시지 예시

```bash
# Conventional Commits
feat(graph): Document Source별 Graph RAG 분리 지원
fix: rag assistant 파일 미리보기 안정화
docs: 운영 rag assistant UI 테스트 결과 추가

# Phase-based
Phase 8: rag-assistant.html Hybrid RAG 모드 연동
Phase 9: admin.html GRAPH/ONTOLOGY 관리자 검증 화면 추가

# Component Prefix
UI: 검색 모드 기본값을 '전체'로 변경
Figma P3 OCR 파싱 패널 추가

# 한글 설명형
RAG 응답 구조 표준화
Graph RAG 생성 경로 7단계로 통일
```

## 코드 아키텍처

### 디렉토리 구조

```
weeslee-rag/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI 라우터 (admin.py, rag.py, graph.py 등)
│   │   ├── core/          # 설정, 인증, 데이터베이스 (config.py, auth.py)
│   │   ├── extractors/    # 문서 추출기 (pdf, hwp, docx, xlsx, pptx)
│   │   ├── models/        # SQLAlchemy 모델
│   │   ├── schemas/       # Pydantic 스키마
│   │   └── services/      # 비즈니스 로직 서비스
│   ├── scripts/           # CLI 스크립트 (빌드, 배포, 벤치마크)
│   ├── mcp_server.py      # MCP 서버 구현
│   └── requirements.txt
├── frontend/
│   ├── admin.html         # 어드민 대시보드 (단일 HTML)
│   ├── rag-assistant.html # RAG 어시스턴트 UI (단일 HTML)
│   └── config.js          # API 설정
├── data/
│   ├── staged/            # 파이프라인 스테이징 데이터
│   ├── wiki/              # 생성된 위키 문서
│   └── active_index.json  # 활성 FAISS 인덱스 설정
├── tests/
│   ├── queries/           # 벤치마크 쿼리 JSON
│   └── evaluation.py      # 평가 스크립트
└── deployment/
    └── nginx/             # Nginx 설정
```

### 자주 변경되는 파일 (핫스팟)

최근 200개 커밋 분석 기준 가장 자주 변경되는 파일.

| 순위 | 파일 | 변경 빈도 | 역할 |
|------|------|----------|------|
| 1 | `frontend/rag-assistant.html` | 40+ | 메인 RAG 사용자 UI (4탭 구조) |
| 2 | `frontend/admin.html` | 35+ | Dataset Builder 관리자 대시보드 |
| 3 | `checklist.md` | 30+ | 작업 진행 체크리스트 |
| 4 | `context-notes.md` | 30+ | 설계 결정 기록 |
| 5 | `backend/app/api/rag.py` | 15+ | RAG 검색 API 엔드포인트 |
| 6 | `backend/app/api/graph.py` | 12+ | Knowledge Graph API |
| 7 | `backend/app/api/faiss_admin.py` | 10+ | FAISS 파이프라인 관리 |
| 8 | `backend/app/services/rag_source_pipeline.py` | 8+ | RAG 소스 파이프라인 로직 |

### 파일 네이밍 규칙

| 타입 | 규칙 | 예시 |
|------|------|------|
| Python 모듈 | snake_case | `query_expander.py` |
| 임시/실험 스크립트 | `_` 접두사 | `_rag_quality_eval.py` |
| 프론트엔드 | kebab-case | `rag-assistant.html` |
| 데이터 파일 | snake_case + 날짜 | `eval_20260507_122128.json` |
| 문서 | `YYMMDD_제목.md` | `260507_개발완료단계.md` |

## 워크플로우

### 새 API 엔드포인트 추가

1. `backend/app/api/` 에 라우터 파일 생성 또는 수정
2. `backend/app/main.py` 에 라우터 등록
3. 필요시 `backend/app/services/` 에 서비스 로직 분리
4. `frontend/*.html` 에서 API 호출 코드 추가

### 문서 추출기 추가

1. `backend/app/extractors/` 에 `{format}_extractor.py` 생성
2. `backend/app/extractors/__init__.py` 에 등록
3. `backend/app/extractors/extractor.py` 의 확장자 매핑에 추가

### 검색 품질 개선

1. `backend/app/services/query_expander.py` 에 동의어/확장 규칙 추가
2. `tests/queries/*.json` 에 테스트 쿼리 추가
3. `backend/scripts/run_quality_eval.py` 또는 `tests/evaluation.py` 로 벤치마크 실행
4. 결과 확인 후 커밋 (`feat(rag): 검색 품질 X% 달성`)

### Dataset Builder 파이프라인 (7단계)

관리자가 문서 소스에서 RAG 시스템을 구축하는 표준 프로세스.

```
Step 1: 메타데이터 추출     → extract_manifest_batch.py
Step 2: OCR 청킹           → build_chunk_batch.py
Step 3: FAISS 인덱스 빌드   → build_faiss_index.py
Step 4: 카테고리 인덱스     → build_category_indexes.py
Step 5: Graph RAG 생성     → build_graph_jsonl.py
Step 6: LLM Wiki 생성      → build_project_wiki.py
Step 7: 검색 품질 검증      → admin.html (테스트 탭)
```

**파일 연계**:
- `frontend/admin.html` - Dataset Builder UI
- `backend/app/api/faiss_admin.py` - 파이프라인 API
- `backend/app/services/faiss_job_runner.py` - 백그라운드 실행
- `backend/app/services/rag_source_pipeline.py` - 파이프라인 로직
- `backend/scripts/` - 각 단계 실행 스크립트

**증분 실행**: 각 단계는 재시작 가능하며, 이미 처리된 파일은 스킵합니다.

## 테스팅 패턴

### 벤치마크 기반 품질 평가

- 테스트 쿼리는 `tests/queries/` 에 JSON으로 관리
- 카테고리별 분리: `bid_project.json`, `rfp.json`, `proposal.json` 등
- `tests/evaluation.py` 로 자동화된 평가 실행
- 결과는 `tests/eval_*.json` 에 타임스탬프와 함께 저장

### 테스트 쿼리 JSON 형식

```json
{
  "queries": [
    {
      "query": "K-water ISP 추진 배경",
      "expected_doc": "k-water-isp",
      "category": "project_specific"
    }
  ]
}
```

## 프론트엔드 패턴

### 단일 HTML 파일 구조

이 프로젝트는 SPA 프레임워크 없이 단일 HTML 파일에 CSS와 JavaScript를 인라인으로 포함합니다.

```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <style>/* CSS 변수 및 스타일 */</style>
</head>
<body>
    <!-- 3-panel 레이아웃 -->
    <script>
        // API 호출 및 UI 로직
        const API_BASE = '/weeslee-rag/api';

        async function fetchData() {
            const token = localStorage.getItem('authToken');
            const res = await fetch(`${API_BASE}/endpoint`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            // ...
        }
    </script>
</body>
</html>
```

### i18n (국제화)

```javascript
const i18n = {
    ko: { search_btn: '검색', result_tab: '결과' },
    en: { search_btn: 'Search', result_tab: 'Results' }
};
let currentLang = 'ko';

function t(key) {
    return i18n[currentLang][key] || key;
}
```

## 백엔드 패턴

### 파일 헤더 주석 (한국어)

모든 Python 파일은 한국어 또는 영문 역할 설명으로 시작합니다.

```python
# RAG 질의와 생성 경로를 분리해 제공하는 API
# -*- coding: utf-8 -*-
"""
RAG query API endpoints.
"""
```

### FastAPI 라우터 구조

```python
# backend/app/api/{feature}.py
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user

router = APIRouter(prefix="/feature", tags=["feature"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "backend" / "scripts" / "script_name.py"

@router.get("/items")
async def list_items(user = Depends(get_current_user)):
    """엔드포인트 설명"""
    return {"items": []}
```

### 동적 임포트 패턴

순환 임포트 방지를 위한 런타임 임포트.

```python
import importlib

def _rag_runtime():
    return importlib.import_module("app.services.rag_runtime")
```

### 서비스 레이어 분리

복잡한 비즈니스 로직은 `services/` 에 분리합니다.

```python
# backend/app/services/query_expander.py
_EXPANSIONS: dict[str, list[str]] = {
    "isp": ["정보화전략계획", "ISP", "information strategy plan"],
    "ai": ["인공지능", "AI", "생성형AI", "머신러닝"],
}

def expand_query(query: str) -> list[str]:
    # 쿼리 확장 로직
    return expanded_queries
```

### 설정 관리

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    upload_dir: str = "./uploads"
    faiss_index_path: str = "./data/faiss"
    ollama_base_url: str = "http://localhost:11434"

    class Config:
        env_file = ".env"

settings = Settings()
```

## 보안 패턴

### JWT 인증

- `/admin/*` 및 `/graph/build` 엔드포인트는 JWT 토큰 필요
- 프론트엔드에서 `localStorage.getItem('authToken')` 사용
- 민감한 자격 증명은 `.env` 파일에 저장 (`.gitignore` 에 포함)

### 하드코딩 금지

```python
# BAD
password = "hardcoded_secret"

# GOOD
import os
password = os.environ.get("DEPLOY_PASSWORD")
```

## 배포 패턴

### 자동 배포 훅

`.claude/settings.json` 에 pre-commit 훅 설정으로 서버 재시작 자동화가 가능합니다.

### 재시작 스크립트

```python
# backend/scripts/restart_server.py
# SSH 키 인증 사용, 비밀번호 하드코딩 금지
# AST 문법 검사 후 배포
```

## 문서화 패턴

### 날짜 기반 작업 문서

작업 문서는 `YYMMDD_주제.md` 형식으로 루트에 저장됩니다.

```
260506_RAG_Quality_Evaluation.md
260507_CheckPoint.md
260508_작업계획_Rerank_Wiki확장.md
```

### CLAUDE.md 활용

프로젝트 컨텍스트와 개발 가이드는 `CLAUDE.md` 에 유지합니다.

## 공동 변경 패턴 (Co-change)

다음 파일들은 함께 변경되는 경향이 있습니다.

| 기능 | 함께 변경되는 파일 |
|------|-------------------|
| RAG 검색 모드 | `rag.py`, `rag-assistant.html`, `query_expander.py` |
| 어드민 기능 | `admin.py`, `admin.html`, `faiss_admin.py` |
| 그래프 기능 | `graph.py`, `build_graph_jsonl.py`, `admin.html` |
| 인증 | `auth.py`, `admin.html`, `main.py` |
| 배포 설정 | `config.py`, `nginx/weeslee-rag-9284.conf` |

## 한국어 IT 용어 확장 (검색 품질용)

| 영문 | 한국어 동의어 |
|------|--------------|
| ISP | 정보화전략계획, IT전략, 정보전략 |
| ISMP | 정보시스템마스터플랜 |
| DX | 디지털전환, 디지털혁신, 스마트화 |
| AI/LLM | 인공지능, 대형언어모델, 생성형AI |
| BPR | 업무재설계, 프로세스혁신 |
| ERP | 전사자원관리 |
| RFP | 제안요청서, 과업지시서 |

## 새로운 패턴 (2026-05-21 ~ 2026-06-02)

### GraphRAG + Hybrid RAG 통합

최근 커밋에서 가장 큰 변화는 **GraphRAG**, **Hybrid RAG**, **Text2Cypher** 기능 추가입니다.

**주요 커밋**:
```
Phase 10: GraphRAG + Wiki 통합 제안서 초안 생성 기능
Phase 8: rag-assistant.html Hybrid RAG 모드 연동
feat: Phase 7 Hybrid RAG API 구현
feat: Phase 6 GraphRAG Agent 구현
feat: Phase 4 Text2Cypher API 및 Cypher Guard 구현
```

**관련 파일**:
- `backend/app/agents/graphrag_agent.py` - GraphRAG 에이전트
- `backend/app/services/hybrid_rag_service.py` - 하이브리드 RAG 로직
- `backend/app/services/text2cypher_service.py` - 자연어→Cypher 변환
- `backend/app/services/cypher_guard.py` - Cypher 쿼리 안전성 검증
- `backend/app/services/graph_query_service.py` - 그래프 쿼리 실행

### MCP 서버 통합

Claude Code와의 통합을 위한 MCP 서버가 추가되었습니다.

```python
# backend/mcp_server.py
@mcp.tool()
def search_documents(query: str, category: str = "", top_k: int = 5) -> str:
    """컨설팅 문서 저장소에서 질의와 관련된 문서를 검색"""
    # Claude Code에서 직접 문서 검색 가능
```

**사용 가능한 도구**:
- `search_documents` - RAG 문서 검색
- `get_project_chain` - 프로젝트별 문서 체인 조회
- `list_projects` - 전체 프로젝트 목록
- `graph_summary` - 그래프 통계

### Figma 기반 UI 개선 워크플로우

Figma 디자인을 단계별로 구현하는 패턴이 정착되었습니다.

```
Figma P0: 사이드바 메뉴 정리
Figma P1: 대시보드 Overview 개편
Figma P2: Dataset Builder 단계 정렬
Figma P3: OCR 파싱 패널 추가
Figma P4: Step UI 연결 보강
```

**특징**:
- Figma 와이어프레임 먼저 검토
- 단계별(P0~P4) 구현 및 커밋
- `docs/2026-05-28_Codex_Figma와이어프레임_구현매핑.md` 문서로 매핑 관리

### 4탭 결과 UI 패턴

사용자 검색 결과를 4개 탭으로 분리하는 UI 패턴이 도입되었습니다.

```javascript
// frontend/rag-assistant.html
const tabs = ['RAG', 'Agent', 'Graph', 'Wiki'];

// RAG 탭: 기본 RAG 검색 결과
// Agent 탭: Multi-Query 확장 분석
// Graph 탭: Knowledge Graph 시각화
// Wiki 탭: LLM 생성 Wiki 컨텍스트
```

**관련 커밋**:
```
feat(rag-assistant): 4탭 결과 분리 UI (RAG/Agent/Graph/Wiki)
feat(rag-assistant): Wiki 탭 기능 및 RAG 근거 문서 섹션 구현
feat(agent): Agent 탭 Multi-Query 분석 기능 구현
```

## MCP 연결 문제 해결 패턴

MCP 서버 연결 실패 시 점검 순서:

1. **패키지 설치 확인**: `pip install mcp` 또는 `pip install fastmcp`
2. **`.mcp.json` 검증**: 올바른 Python 경로 및 스크립트 경로 확인
3. **백엔드 서버 실행**: MCP 서버는 `http://127.0.0.1:8080` API 의존
4. **Claude Code 재시작**: 설정 변경 후 재시작 필요

---

*Generated by /skill-create from 200 commits (2026-04-27 ~ 2026-06-02)*
*Updated: 2026-06-02 with GraphRAG, Hybrid RAG, MCP patterns*
