# PromptoRAG 개발 순서

**작성일:** 2026-04-22
**기준 문서:** 260422_Requirements_Clarification.md, 260422_DEV_Plan.md

---

## 개발 원칙

1. **Backend First**: API 먼저 개발 후 Frontend 연동
2. **핵심 기능 우선**: RAG 파이프라인 → 문서 생성 순서
3. **단계별 검증**: 각 단계 완료 후 테스트 진행
4. **점진적 확장**: 기본 기능 → 고급 기능 순서

---

## Phase 1: 개발 환경 구축

### 1.1 Backend 환경 설정

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 1.1.1 | Python 가상환경 생성 | `venv/` |
| 1.1.2 | FastAPI 프로젝트 초기화 | `backend/` 폴더 구조 |
| 1.1.3 | 의존성 패키지 설치 | `requirements.txt` |
| 1.1.4 | 환경 변수 설정 | `.env`, `config.py` |

```bash
# 설치할 주요 패키지
fastapi
uvicorn
sqlalchemy
pymysql
chromadb
python-multipart
python-pptx
python-docx
pyhwpx
pdfplumber
openpyxl
langchain
```

### 1.2 Database 설정

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 1.2.1 | MySQL 데이터베이스 생성 | `promptorag` DB |
| 1.2.2 | SQLAlchemy 모델 정의 | `models/` |
| 1.2.3 | 마이그레이션 설정 | `alembic/` |
| 1.2.4 | 초기 테이블 생성 | 테이블 생성 완료 |

```
생성할 테이블:
├── collections (컬렉션)
├── documents (문서)
├── document_chunks (청크)
├── processing_logs (처리 로그)
├── prompts (템플릿)
├── prompt_variables (변수)
├── execution_logs (실행 이력)
└── users (사용자)
```

### 1.3 Ollama 설정

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 1.3.1 | Ollama 설치 확인 | `ollama serve` 실행 |
| 1.3.2 | LLM 모델 다운로드 | `llama3:8b` 등 |
| 1.3.3 | 임베딩 모델 다운로드 | `nomic-embed-text` |
| 1.3.4 | 연결 테스트 | API 호출 테스트 |

### 1.4 Chroma VectorDB 설정

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 1.4.1 | Chroma 클라이언트 설정 | `services/vectordb.py` |
| 1.4.2 | 기본 컬렉션 생성 | `all_documents` 컬렉션 |
| 1.4.3 | 연결 테스트 | CRUD 테스트 |

---

## Phase 2: RAG 파이프라인 개발 (핵심)

### 2.1 문서 텍스트 추출 모듈

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 2.1.1 | 파일 업로드 API | `POST /api/documents/upload` |
| 2.1.2 | PPTX 텍스트 추출 | `extractors/pptx_extractor.py` |
| 2.1.3 | DOCX 텍스트 추출 | `extractors/docx_extractor.py` |
| 2.1.4 | HWP/HWPX 텍스트 추출 | `extractors/hwp_extractor.py` |
| 2.1.5 | PDF 텍스트 추출 | `extractors/pdf_extractor.py` |
| 2.1.6 | 통합 추출 인터페이스 | `extractors/base.py` |

```python
# 추출기 인터페이스
class BaseExtractor:
    def extract(self, file_path: str) -> ExtractedContent:
        pass

class ExtractedContent:
    text: str
    pages: list[str]
    metadata: dict
```

### 2.2 텍스트 청킹 모듈

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 2.2.1 | 청킹 설정 정의 | `ChunkConfig` 클래스 |
| 2.2.2 | 토큰 기반 청킹 구현 | `chunkers/token_chunker.py` |
| 2.2.3 | 오버랩 처리 | 오버랩 로직 |
| 2.2.4 | 메타데이터 유지 | 페이지 번호, 위치 정보 |

```python
# 청킹 설정
class ChunkConfig:
    chunk_size: int = 512      # 토큰 수
    chunk_overlap: int = 50    # 오버랩 토큰
    separator: str = "\n\n"    # 구분자
```

### 2.3 임베딩 생성 모듈

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 2.3.1 | Ollama 임베딩 연동 | `embeddings/ollama_embedder.py` |
| 2.3.2 | 배치 처리 구현 | 32개씩 배치 |
| 2.3.3 | 임베딩 캐시 | 중복 방지 |

```python
# Ollama 임베딩 호출
async def get_embedding(text: str, model: str = "nomic-embed-text"):
    response = await ollama.embeddings(model=model, prompt=text)
    return response["embedding"]
```

### 2.4 VectorDB 저장 모듈

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 2.4.1 | Chroma 저장 로직 | `services/vectordb.py` |
| 2.4.2 | 메타데이터 저장 | 파일명, 페이지, 청크 인덱스 |
| 2.4.3 | 컬렉션별 저장 | 컬렉션 라우팅 |

### 2.5 RAG 파이프라인 통합

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 2.5.1 | 파이프라인 오케스트레이터 | `services/rag_pipeline.py` |
| 2.5.2 | 비동기 처리 (Celery) | `tasks/document_tasks.py` |
| 2.5.3 | 진행 상태 추적 | `processing_logs` 테이블 |
| 2.5.4 | 에러 핸들링 | 실패 시 재시도 |

```
파이프라인 흐름:
upload → extract → chunk → embed → store → complete
         ↓         ↓        ↓       ↓
      [로그]    [로그]   [로그]  [로그]
```

---

## Phase 3: 관리자 API 개발

### 3.1 컬렉션 관리 API

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 3.1.1 | 컬렉션 목록 조회 | `GET /api/admin/collections` |
| 3.1.2 | 컬렉션 생성 | `POST /api/admin/collections` |
| 3.1.3 | 컬렉션 수정 | `PUT /api/admin/collections/{id}` |
| 3.1.4 | 컬렉션 삭제 | `DELETE /api/admin/collections/{id}` |
| 3.1.5 | 컬렉션 통계 | `GET /api/admin/collections/{id}/stats` |
| 3.1.6 | 전체 재인덱싱 | `POST /api/admin/collections/{id}/reindex` |

### 3.2 문서 관리 API

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 3.2.1 | 문서 목록 조회 | `GET /api/admin/documents` |
| 3.2.2 | 문서 업로드 | `POST /api/admin/documents/upload` |
| 3.2.3 | 문서 삭제 | `DELETE /api/admin/documents/{id}` |
| 3.2.4 | 문서 재처리 | `POST /api/admin/documents/{id}/reprocess` |
| 3.2.5 | 처리 상태 조회 | `GET /api/admin/documents/{id}/status` |

### 3.3 처리 상태 API

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 3.3.1 | 현재 처리 현황 | `GET /api/admin/processing/status` |
| 3.3.2 | 대기열 조회 | `GET /api/admin/processing/queue` |
| 3.3.3 | 처리 취소 | `POST /api/admin/processing/{id}/cancel` |

---

## Phase 4: 검색 및 생성 API 개발

### 4.1 문서 검색 API

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 4.1.1 | 유사도 검색 | `POST /api/search` |
| 4.1.2 | 다중 컬렉션 검색 | 컬렉션 필터링 |
| 4.1.3 | Top-K 설정 | 결과 개수 제한 |
| 4.1.4 | 메타데이터 필터 | 날짜, 파일 유형 필터 |

```python
# 검색 요청
class SearchRequest:
    query: str
    collections: list[str]
    top_k: int = 10
    filters: dict = {}
```

### 4.2 LLM 생성 API

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 4.2.1 | Ollama 연동 | `services/llm.py` |
| 4.2.2 | 프롬프트 조합 | 템플릿 + 변수 + 컨텍스트 |
| 4.2.3 | SSE 스트리밍 | 실시간 응답 |
| 4.2.4 | 생성 실행 API | `POST /api/generate` |

```python
# 생성 요청
class GenerateRequest:
    prompt_id: int
    variables: dict
    collections: list[str]
    model: str = "llama3:8b"
    options: GenerateOptions
```

### 4.3 실행 이력 API

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 4.3.1 | 실행 로그 저장 | 자동 저장 |
| 4.3.2 | 이력 목록 조회 | `GET /api/executions` |
| 4.3.3 | 이력 상세 조회 | `GET /api/executions/{id}` |
| 4.3.4 | 참조 문서 조회 | `GET /api/executions/{id}/references` |

---

## Phase 5: 템플릿 관리 API 개발

### 5.1 템플릿 CRUD API

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 5.1.1 | 템플릿 목록 조회 | `GET /api/prompts` |
| 5.1.2 | 템플릿 상세 조회 | `GET /api/prompts/{id}` |
| 5.1.3 | 템플릿 생성 | `POST /api/prompts` |
| 5.1.4 | 템플릿 수정 | `PUT /api/prompts/{id}` |
| 5.1.5 | 템플릿 삭제 | `DELETE /api/prompts/{id}` |

### 5.2 템플릿 분류 API

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 5.2.1 | 카테고리별 조회 | 필터 파라미터 |
| 5.2.2 | 즐겨찾기 목록 | `GET /api/prompts/favorites` |
| 5.2.3 | 조직 표준 목록 | `GET /api/prompts/org-standard` |
| 5.2.4 | 개인 저장 목록 | `GET /api/prompts/personal` |

### 5.3 템플릿 승인 API

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 5.3.1 | 승인 대기 목록 | `GET /api/admin/prompts/pending` |
| 5.3.2 | 템플릿 승인 | `POST /api/admin/prompts/{id}/approve` |
| 5.3.3 | 템플릿 반려 | `POST /api/admin/prompts/{id}/reject` |

### 5.4 버전 관리 API

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 5.4.1 | 버전 이력 조회 | `GET /api/prompts/{id}/versions` |
| 5.4.2 | 버전 복원 | `POST /api/prompts/{id}/versions/{version}/restore` |

---

## Phase 6: Frontend 개발 - 관리자 페이지

### 6.1 프로젝트 설정

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 6.1.1 | Next.js 프로젝트 생성 | `frontend/` |
| 6.1.2 | Tailwind CSS 설정 | `tailwind.config.js` |
| 6.1.3 | Shadcn/ui 설치 | 컴포넌트 라이브러리 |
| 6.1.4 | API 클라이언트 설정 | `lib/api.ts` |
| 6.1.5 | 상태 관리 설정 | Zustand store |

### 6.2 레이아웃 컴포넌트

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 6.2.1 | 공통 레이아웃 | `components/layout/` |
| 6.2.2 | 네비게이션 바 | `TopNav.tsx` |
| 6.2.3 | 관리자 사이드바 | `AdminSidebar.tsx` |

### 6.3 관리자 - 문서 관리 페이지

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 6.3.1 | 문서 목록 테이블 | `admin/documents/page.tsx` |
| 6.3.2 | 문서 업로드 모달 | `DocumentUploadModal.tsx` |
| 6.3.3 | 필터 및 검색 | 필터 컴포넌트 |
| 6.3.4 | 처리 상태 표시 | 상태 뱃지 |
| 6.3.5 | 일괄 작업 | 선택 후 삭제/재처리 |

### 6.4 관리자 - 컬렉션 관리 페이지

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 6.4.1 | 컬렉션 카드 목록 | `admin/collections/page.tsx` |
| 6.4.2 | 컬렉션 생성 모달 | `CollectionCreateModal.tsx` |
| 6.4.3 | 컬렉션 상세 모달 | `CollectionDetailModal.tsx` |
| 6.4.4 | 통계 표시 | 문서 수, 벡터 수, 용량 |

### 6.5 관리자 - 처리 현황 페이지

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 6.5.1 | 실시간 처리 현황 | `admin/processing/page.tsx` |
| 6.5.2 | 진행률 바 | 프로그레스 컴포넌트 |
| 6.5.3 | 대기열 목록 | 대기 중인 작업 |
| 6.5.4 | 자동 새로고침 | 폴링 또는 WebSocket |

---

## Phase 7: Frontend 개발 - 메인 UI

### 7.1 3-Panel 레이아웃

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 7.1.1 | 3-Panel 레이아웃 | `app/page.tsx` |
| 7.1.2 | 좌측 사이드바 (270px) | `LeftSidebar.tsx` |
| 7.1.3 | 중앙 영역 (flex) | `CenterPanel.tsx` |
| 7.1.4 | 우측 패널 (320px) | `RightPanel.tsx` |

### 7.2 좌측 사이드바

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 7.2.1 | 검색 입력창 | `SearchInput.tsx` |
| 7.2.2 | 카테고리 필터 칩 | `CategoryChips.tsx` |
| 7.2.3 | 즐겨찾기 목록 | `FavoritesList.tsx` |
| 7.2.4 | 조직 표준 목록 | `OrgStandardList.tsx` |
| 7.2.5 | 개인 저장 목록 | `PersonalList.tsx` |
| 7.2.6 | 새 템플릿 만들기 버튼 | `NewTemplateButton.tsx` |
| 7.2.7 | 최근 사용 목록 | `RecentList.tsx` |

### 7.3 중앙 영역 - Step Wizard

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 7.3.1 | Step Wizard 바 | `StepWizard.tsx` |
| 7.3.2 | 템플릿 헤더 카드 | `TemplateHeader.tsx` |
| 7.3.3 | 입력 파라미터 폼 | `InputParamsForm.tsx` |
| 7.3.4 | 추가 요청 입력 | `ExtraRequestInput.tsx` |
| 7.3.5 | AI 생성 결과 영역 | `ResultSection.tsx` |
| 7.3.6 | 실행 바 | `ExecutionBar.tsx` |

### 7.4 우측 패널

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 7.4.1 | 지식원 선택 | `KnowledgeSourceSelect.tsx` |
| 7.4.2 | 검색 조건 설정 | `SearchOptions.tsx` |
| 7.4.3 | 근거 문서 목록 | `ReferenceDocuments.tsx` |
| 7.4.4 | 주의 알림 | `WarningAlert.tsx` |

### 7.5 모달 컴포넌트

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 7.5.1 | 모델 설정 모달 | `ModelSettingsModal.tsx` |
| 7.5.2 | 템플릿 전체보기 모달 | `TemplateDetailModal.tsx` |
| 7.5.3 | 버전 이력 모달 | `VersionHistoryModal.tsx` |
| 7.5.4 | 활용 통계 모달 | `UsageStatsModal.tsx` |
| 7.5.5 | 새 템플릿 만들기 모달 | `NewTemplateModal.tsx` |
| 7.5.6 | 도움말 모달들 | `HelpModal.tsx` |

### 7.6 AI 생성 기능

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 7.6.1 | 생성 실행 로직 | `useGenerate.ts` |
| 7.6.2 | SSE 스트리밍 처리 | 실시간 결과 표시 |
| 7.6.3 | 결과 복사/내보내기 | 클립보드, 다운로드 |
| 7.6.4 | 재생성 기능 | 재실행 버튼 |

---

## Phase 8: 통합 및 테스트

### 8.1 통합 테스트

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 8.1.1 | API 통합 테스트 | `tests/api/` |
| 8.1.2 | RAG 파이프라인 테스트 | 문서 → 검색 → 생성 |
| 8.1.3 | E2E 테스트 | Playwright |

### 8.2 성능 최적화

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 8.2.1 | 임베딩 배치 최적화 | 처리 속도 개선 |
| 8.2.2 | 검색 성능 튜닝 | 인덱스 최적화 |
| 8.2.3 | 프론트엔드 최적화 | 번들 사이즈, 로딩 |

### 8.3 배포 준비

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 8.3.1 | Docker 설정 | `docker-compose.yml` |
| 8.3.2 | 환경별 설정 | dev, staging, prod |
| 8.3.3 | 문서화 | README, API 문서 |

---

## 개발 우선순위 요약

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              개발 순서 로드맵                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Phase 1        Phase 2           Phase 3          Phase 4                 │
│  ┌─────┐       ┌─────────┐       ┌─────────┐      ┌─────────┐              │
│  │ 환경 │ ───▶ │   RAG   │ ───▶ │ 관리자  │ ───▶ │ 검색/   │              │
│  │ 구축 │       │파이프라인│       │  API    │      │ 생성API │              │
│  └─────┘       └─────────┘       └─────────┘      └─────────┘              │
│                     ⬆                                                       │
│                  [핵심]                                                     │
│                                                                             │
│  Phase 5        Phase 6           Phase 7          Phase 8                 │
│  ┌─────────┐   ┌─────────┐       ┌─────────┐      ┌─────────┐              │
│  │ 템플릿  │ ──▶│ 관리자  │ ───▶ │ 메인 UI │ ───▶ │ 통합/   │              │
│  │  API    │   │ Frontend│       │Frontend │      │ 테스트  │              │
│  └─────────┘   └─────────┘       └─────────┘      └─────────┘              │
│                                       ⬆                                     │
│                                    [주요]                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 마일스톤

| 마일스톤 | Phase | 완료 기준 |
|----------|-------|-----------|
| **M1: 환경 구축** | 1 | DB, Ollama, Chroma 연동 확인 |
| **M2: RAG 완성** | 2 | 문서 업로드 → VectorDB 저장 성공 |
| **M3: API 완성** | 3-5 | 모든 API 엔드포인트 동작 |
| **M4: 관리자 UI** | 6 | 문서/컬렉션 관리 UI 완성 |
| **M5: 메인 UI** | 7 | 문서 생성 기능 완성 |
| **M6: 릴리스** | 8 | 테스트 완료, 배포 준비 |

---

## 다음 단계

**Phase 1부터 시작:**
1. Backend 폴더 구조 생성
2. FastAPI 프로젝트 초기화
3. MySQL 데이터베이스 생성
4. SQLAlchemy 모델 정의

---

**문서 끝**
