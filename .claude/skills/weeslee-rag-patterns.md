# weeslee-rag 프로젝트 코딩 패턴

---
name: weeslee-rag-patterns
description: PromptoRAG 프로젝트에서 추출한 코딩 패턴 및 워크플로우
version: 1.0.0
source: local-git-analysis
analyzed_commits: 150
---

## 커밋 컨벤션

이 프로젝트는 **Conventional Commits** 형식을 사용한다. 전체 커밋의 약 69%가 이 형식을 따른다.

### 접두어 및 스코프

```
feat(scope): 새로운 기능 추가
fix(scope): 버그 수정
chore(scope): 빌드/설정 관련 작업
docs: 문서 업데이트
test(scope): 테스트 추가
refactor(scope): 리팩토링
style(scope): 코드 스타일 변경
```

### 주요 스코프 목록

| 스코프 | 사용 빈도 | 용도 |
|--------|----------|------|
| `admin` | 23회 | admin.html 관리자 UI |
| `rag` | 9회 | RAG 백엔드 API/서비스 |
| `frontend` | 6회 | 프론트엔드 전반 |
| `rag-assistant` | 3회 | rag-assistant.html UI |
| `pipeline` | 1회 | 데이터 파이프라인 |
| `deploy` | 1회 | 배포 관련 |

### 커밋 메시지 예시

```
feat(admin): RAG Build Wizard Stepper UI 상태 연동
fix(frontend): renderResultPanel 및 runQuery null 체크 추가
feat(rag): Prompt Analysis API 구현
refactor(rag): 중복 build_prompt 제거 및 document_group 한글 매핑 추가
```

## 코드 아키텍처

```
weeslee-rag/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI 라우터 (도메인별 분리)
│   │   │   ├── admin.py   # 관리자 API
│   │   │   ├── rag.py     # RAG 검색 API
│   │   │   ├── graph.py   # Knowledge Graph API
│   │   │   ├── faiss_admin.py  # FAISS 인덱스 관리
│   │   │   └── ...
│   │   ├── services/      # 비즈니스 로직 서비스
│   │   │   ├── rag_runtime.py       # RAG 실행 엔진
│   │   │   ├── query_expander.py    # 쿼리 확장/분석
│   │   │   ├── knowledge_graph.py   # 그래프 서비스
│   │   │   └── ...
│   │   ├── core/          # 설정, 공통 유틸
│   │   ├── models/        # DB 모델
│   │   ├── schemas/       # Pydantic 스키마
│   │   └── extractors/    # 문서 추출기 (HWP, PDF 등)
│   └── scripts/           # CLI 스크립트 (배치 처리, 파이프라인)
│       ├── build_*.py     # 빌드 스크립트
│       ├── extract_*.py   # 추출 스크립트
│       └── run_*.py       # 실행 스크립트
├── frontend/
│   ├── admin.html         # 관리자 페이지 (단일 파일, 359KB)
│   ├── rag-assistant.html # 사용자 검색 UI (단일 파일, 203KB)
│   └── assets/
│       ├── css/           # 스타일시트
│       └── js/admin/      # 관리자 JS 모듈
├── data/                  # 데이터 파일
│   ├── staged/            # 처리 대기 데이터
│   └── wiki/              # 프로젝트 위키
├── docs/                  # 문서
│   └── design/            # 설계 문서
├── e2e/                   # E2E 테스트 (Playwright)
└── harness/               # 개발 하네스/유틸
```

## 파일 동시 변경 패턴

Git 히스토리 분석 결과, 다음 파일들이 함께 변경되는 경향이 있다.

### RAG 기능 변경 시

```
backend/app/api/rag.py
backend/app/services/rag_runtime.py
backend/app/services/query_expander.py
frontend/rag-assistant.html
```

### 관리자 UI 기능 변경 시

```
frontend/admin.html
backend/app/api/admin.py
backend/app/api/faiss_admin.py
frontend/assets/css/admin-docs-layout.css
frontend/assets/js/admin/admin-docs-layout.js
```

### 파이프라인 변경 시

```
backend/app/services/rag_source_pipeline.py
backend/scripts/build_chunk_batch.py
backend/scripts/extract_manifest_batch.py
backend/scripts/build_faiss_index.py
```

## 워크플로우

### 새 API 엔드포인트 추가

1. `backend/app/api/` 아래에 라우터 파일 생성 또는 수정
2. `backend/app/services/` 아래에 비즈니스 로직 서비스 구현
3. `backend/app/main.py`에 라우터 등록
4. `frontend/admin.html` 또는 `rag-assistant.html`에 UI 연동

### RAG 검색 품질 개선

1. `backend/app/services/query_expander.py`에서 쿼리 확장 로직 수정
2. `backend/scripts/assemble_rag_response.py`에서 응답 조립 로직 수정
3. `backend/app/api/rag.py`에서 API 엔드포인트 조정
4. `frontend/rag-assistant.html`에서 결과 렌더링 수정

### 문서 인덱싱 파이프라인

1. `backend/scripts/extract_manifest_batch.py` - 문서 추출
2. `backend/scripts/build_chunk_batch.py` - 청크 생성
3. `backend/scripts/build_faiss_index.py` - FAISS 인덱스 빌드
4. `backend/scripts/build_graph_jsonl.py` - 그래프 데이터 생성

## 테스트 패턴

- E2E 테스트: `e2e/` 디렉토리, Playwright 사용
- 테스트 파일 명명: `*.spec.ts`
- GitHub Actions 워크플로우: `.github/workflows/playwright.yml`

## 코딩 컨벤션

### Python (Backend)

- FastAPI 라우터 사용
- Pydantic 스키마로 요청/응답 검증
- 서비스 레이어에서 비즈니스 로직 분리
- 스크립트는 `backend/scripts/`에 배치, CLI 인터페이스 제공

### HTML/JavaScript (Frontend)

- 단일 HTML 파일에 인라인 CSS/JS 포함 (대규모 파일)
- API 호출 시 `API_BASE` 상수 사용
- null 체크 필수 (getElementById, querySelector 반환값)
- SSE (Server-Sent Events) 스트리밍 지원

### 한국어 사용

- 커밋 메시지: 영어 접두어 + 한국어 설명 혼용 가능
- 문서: 한국어 사용
- UI 라벨: 한국어 사용
- 코드 주석: 한국어/영어 혼용

## 주의사항

### Frontend null 체크

DOM 요소 접근 시 반드시 null 체크 필요. 최근 커밋에서 여러 null 체크 버그가 수정됨.

```javascript
// Bad
document.getElementById('myElement').innerHTML = 'text';

// Good
const el = document.getElementById('myElement');
if (el) el.innerHTML = 'text';
```

### API 경로 정규화

프론트엔드에서 API 호출 시 `API_BASE` 사용 및 경로 정규화 필수.

```javascript
const API_BASE = 'http://server.weeslee.co.kr:9001';
// 중복 슬래시 방지
const url = `${API_BASE}/api/rag/search`;
```
