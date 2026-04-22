# PromptoRAG 개발 계획서

**작성일:** 2026-04-22
**버전:** 1.0
**프로젝트명:** PromptoRAG — 컨설팅 문서 재활용 및 AI 초안 생성 시스템

---

## 1. 개발 개요

### 1.1 프로젝트 현황

| 구분 | 상태 |
|------|------|
| UI 프로토타입 | `PromptoRAG_UI_v1.0.html` 완성 (단일 HTML 파일) |
| 백엔드 | 미구현 |
| 데이터베이스 | 설계 완료, 미구축 |
| RAG 파이프라인 | 미구현 |
| 문서 저장소 | `\\diskstation\W2_프로젝트폴더` (기존 네트워크 공유) |

### 1.2 핵심 요구사항

1. **Step Wizard 기반 단일 페이지 앱** (5단계 워크플로우)
2. **3-패널 레이아웃**: 좌측(템플릿) + 중앙(작업) + 우측(지식원/결과)
3. **RAG 기반 문서 검색**: 네트워크 폴더 스캔 → 청킹 → 벡터 검색
4. **LLM 연동**: Claude API 스트리밍 응답
5. **작업 이력 자산화**: 재사용 가능한 실행 기록

---

## 2. 개발 언어 및 프레임워크 선정

### 2.1 프론트엔드

| 항목 | 선정 기술 | 선정 이유 |
|------|----------|----------|
| **프레임워크** | **Next.js 14 (App Router)** | SSR/SSG 지원, React 기반, 빠른 개발, API Routes 통합 가능 |
| **언어** | TypeScript | 타입 안정성, IDE 지원, 대규모 프로젝트 유지보수성 |
| **상태관리** | Zustand | 경량, 간결한 API, Redux 대비 보일러플레이트 감소 |
| **HTTP 클라이언트** | TanStack Query (React Query) | 캐싱, 자동 리패칭, SSE 지원 |
| **스타일링** | Tailwind CSS + CSS Modules | 기존 CSS 변수 활용 가능, 유틸리티 클래스 생산성 |
| **UI 컴포넌트** | Shadcn/ui | Tailwind 기반, 커스터마이징 용이, 접근성 내장 |
| **아이콘** | Lucide React | 가볍고 일관된 아이콘 세트 |
| **폼 관리** | React Hook Form + Zod | 유효성 검증, 타입 안전 |

### 2.2 백엔드

| 항목 | 선정 기술 | 선정 이유 |
|------|----------|----------|
| **프레임워크** | **FastAPI (Python)** | 비동기 지원, 자동 OpenAPI 문서, LLM/ML 라이브러리 호환 |
| **언어** | Python 3.11+ | RAG 관련 라이브러리 풍부 (LangChain, FAISS, etc.) |
| **ORM** | SQLAlchemy 2.0 | 비동기 지원, 타입 힌트, Alembic 마이그레이션 |
| **인증** | JWT (PyJWT) + OAuth2 | 토큰 기반, 역할 기반 접근 제어 |
| **비동기 작업** | Celery + Redis | 문서 인덱싱, 스캔 등 백그라운드 처리 |
| **API 문서** | Swagger UI (자동 생성) | FastAPI 내장 |

### 2.3 데이터베이스 및 저장소

| 항목 | 선정 기술 | 선정 이유 |
|------|----------|----------|
| **RDBMS** | **MySQL 8.0** | XAMPP 환경 호환, JSON 컬럼 지원, 기존 인프라 활용 |
| **벡터 DB** | **FAISS** (로컬) | 오프라인 가능, 빠른 검색, 무료 |
| **캐시** | Redis | 세션 관리, 검색 캐싱, Celery 브로커 |
| **파일 저장** | 네트워크 공유 (SMB) | `\\diskstation\W2_프로젝트폴더` 직접 접근 |

### 2.4 RAG 파이프라인

| 항목 | 선정 기술 | 선정 이유 |
|------|----------|----------|
| **청킹** | LangChain RecursiveCharacterTextSplitter | 유연한 청크 크기 조정 |
| **임베딩** | **KoSimCSE-roberta** | 한국어 특화, 오프라인 가능, 무료 |
| **대안 임베딩** | OpenAI text-embedding-3-small | 고성능, API 비용 발생 |
| **PDF 추출** | pdfplumber | 표 추출 지원, 한글 호환 |
| **HWP 추출** | pyhwpx / hwp5 | 한글 문서 필수 |
| **DOCX 추출** | python-docx | MS Word 문서 |

### 2.5 LLM 연동

| 항목 | 선정 기술 | 선정 이유 |
|------|----------|----------|
| **기본 모델** | Claude Sonnet 4 | 비용 대비 성능, 한국어 품질 |
| **고품질 모델** | Claude Opus 4 | 복잡한 분석/연구 문서 |
| **빠른 응답** | Claude Haiku | 요약, 간단한 질의응답 |
| **SDK** | Anthropic Python SDK | 공식 SDK, 스트리밍 지원 |
| **스트리밍** | SSE (Server-Sent Events) | 실시간 응답 표시 |

### 2.6 인프라 및 배포

| 항목 | 선정 기술 | 선정 이유 |
|------|----------|----------|
| **로컬 개발** | Docker Compose | 통합 환경 구성, 재현성 |
| **웹 서버** | Nginx | 리버스 프록시, 정적 파일 서빙 |
| **프로세스 관리** | PM2 (Node) / Gunicorn (Python) | 프로덕션 안정성 |
| **모니터링** | Prometheus + Grafana | 성능 모니터링 (선택) |

---

## 3. 프로젝트 구조

### 3.1 전체 구조

```
weeslee-rag/
├── frontend/                    # Next.js 프론트엔드
│   ├── src/
│   │   ├── app/                 # App Router 페이지
│   │   │   ├── (auth)/          # 인증 관련 페이지
│   │   │   │   ├── login/
│   │   │   │   └── logout/
│   │   │   ├── (main)/          # 메인 레이아웃
│   │   │   │   ├── dashboard/   # 대시보드 (홈)
│   │   │   │   ├── workspace/   # 새 작업 실행 (Step Wizard)
│   │   │   │   ├── templates/   # 템플릿 라이브러리
│   │   │   │   ├── history/     # 작업 이력
│   │   │   │   └── admin/       # 관리자
│   │   │   ├── api/             # API Routes (선택적 BFF)
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── components/
│   │   │   ├── ui/              # Shadcn/ui 기반 공통 컴포넌트
│   │   │   ├── layout/          # 레이아웃 컴포넌트
│   │   │   │   ├── TopNav.tsx
│   │   │   │   ├── LeftSidebar.tsx
│   │   │   │   ├── RightPanel.tsx
│   │   │   │   └── MainContent.tsx
│   │   │   ├── workspace/       # Step Wizard 관련
│   │   │   │   ├── StepWizard.tsx
│   │   │   │   ├── TemplateHeader.tsx
│   │   │   │   ├── InputParameters.tsx
│   │   │   │   ├── ExtraRequest.tsx
│   │   │   │   ├── ResultOutput.tsx
│   │   │   │   └── ExecutionBar.tsx
│   │   │   ├── knowledge/       # 지식원 관련
│   │   │   ├── modals/          # 모달 컴포넌트
│   │   │   └── shared/          # 공유 컴포넌트
│   │   ├── hooks/               # 커스텀 훅
│   │   ├── stores/              # Zustand 스토어
│   │   │   ├── useAuthStore.ts
│   │   │   ├── useTemplateStore.ts
│   │   │   ├── useWorkspaceStore.ts
│   │   │   └── useKnowledgeStore.ts
│   │   ├── lib/                 # 유틸리티
│   │   │   ├── api.ts           # API 클라이언트
│   │   │   ├── sse.ts           # SSE 핸들러
│   │   │   └── utils.ts
│   │   ├── types/               # TypeScript 타입
│   │   └── styles/              # 글로벌 스타일
│   │       └── globals.css      # CSS 변수 (기존 UI 기반)
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   └── next.config.js
│
├── backend/                     # FastAPI 백엔드
│   ├── app/
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── auth.py
│   │   │   │   ├── prompts.py
│   │   │   │   ├── knowledge.py
│   │   │   │   ├── rag.py
│   │   │   │   ├── execution.py
│   │   │   │   └── admin.py
│   │   │   └── deps.py          # 의존성 주입
│   │   ├── core/
│   │   │   ├── config.py        # 설정
│   │   │   ├── security.py      # 인증/암호화
│   │   │   └── database.py      # DB 연결
│   │   ├── models/              # SQLAlchemy 모델
│   │   │   ├── user.py
│   │   │   ├── prompt.py
│   │   │   ├── knowledge.py
│   │   │   ├── document.py
│   │   │   └── execution.py
│   │   ├── schemas/             # Pydantic 스키마
│   │   ├── services/            # 비즈니스 로직
│   │   │   ├── auth_service.py
│   │   │   ├── prompt_service.py
│   │   │   ├── rag_service.py
│   │   │   ├── llm_service.py
│   │   │   └── scanner_service.py  # 네트워크 폴더 스캔
│   │   ├── tasks/               # Celery 태스크
│   │   │   ├── scan_task.py
│   │   │   ├── index_task.py
│   │   │   └── export_task.py
│   │   └── main.py              # FastAPI 앱 진입점
│   ├── alembic/                 # DB 마이그레이션
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
│
├── docker/
│   ├── docker-compose.yml       # 개발 환경
│   ├── docker-compose.prod.yml  # 프로덕션
│   ├── nginx/
│   │   └── nginx.conf
│   └── mysql/
│       └── init.sql
│
├── docs/                        # 문서
│   ├── api/                     # API 명세
│   ├── architecture/            # 아키텍처 문서
│   └── guides/                  # 개발 가이드
│
├── scripts/                     # 유틸리티 스크립트
│   ├── setup.sh
│   ├── migrate.sh
│   └── seed.py                  # 초기 데이터
│
├── .env.example                 # 환경 변수 예시
├── .gitignore
├── README.md
│
└── legacy/                      # 기존 파일 보관
    ├── PromptoRAG_UI_v1.0.html
    └── *.md
```

### 3.2 프론트엔드 상세 구조

```
frontend/src/
├── app/
│   ├── (auth)/
│   │   ├── login/
│   │   │   └── page.tsx         # 로그인 페이지
│   │   └── layout.tsx           # 인증 레이아웃 (사이드바 없음)
│   │
│   ├── (main)/
│   │   ├── layout.tsx           # 3-패널 레이아웃
│   │   ├── dashboard/
│   │   │   └── page.tsx         # 대시보드 (최근 작업, 통계)
│   │   ├── workspace/
│   │   │   ├── page.tsx         # Step Wizard 메인
│   │   │   └── [templateId]/
│   │   │       └── page.tsx     # 특정 템플릿으로 시작
│   │   ├── templates/
│   │   │   ├── page.tsx         # 템플릿 목록
│   │   │   ├── [id]/
│   │   │   │   └── page.tsx     # 템플릿 상세
│   │   │   └── new/
│   │   │       └── page.tsx     # 새 템플릿 생성
│   │   ├── history/
│   │   │   ├── page.tsx         # 작업 이력 목록
│   │   │   └── [id]/
│   │   │       └── page.tsx     # 이력 상세
│   │   └── admin/
│   │       ├── page.tsx         # 관리자 대시보드
│   │       ├── approvals/
│   │       ├── knowledge/
│   │       └── users/
│   │
│   ├── api/                     # Next.js API Routes (선택)
│   │   └── [...proxy]/
│   │       └── route.ts         # 백엔드 프록시 (CORS 우회)
│   │
│   ├── layout.tsx               # 루트 레이아웃
│   ├── page.tsx                 # 리다이렉트 → /dashboard
│   └── globals.css
│
├── components/
│   ├── ui/                      # Shadcn/ui 컴포넌트
│   │   ├── button.tsx
│   │   ├── card.tsx
│   │   ├── dialog.tsx
│   │   ├── input.tsx
│   │   ├── select.tsx
│   │   ├── slider.tsx
│   │   ├── tabs.tsx
│   │   ├── toast.tsx
│   │   └── ...
│   │
│   ├── layout/
│   │   ├── TopNav.tsx           # 상단 네비게이션
│   │   ├── LeftSidebar.tsx      # 좌측 사이드바
│   │   │   ├── SearchBar.tsx
│   │   │   ├── FilterChips.tsx
│   │   │   ├── TemplateGroup.tsx
│   │   │   └── TemplateCard.tsx
│   │   ├── RightPanel.tsx       # 우측 패널
│   │   │   ├── KnowledgeSection.tsx
│   │   │   ├── SearchOptions.tsx
│   │   │   ├── ReferenceDocuments.tsx
│   │   │   ├── Warnings.tsx
│   │   │   └── Statistics.tsx
│   │   └── MainContent.tsx
│   │
│   ├── workspace/               # Step Wizard 컴포넌트
│   │   ├── StepWizard.tsx       # 단계 표시 바
│   │   ├── Step1-CategorySelect.tsx
│   │   ├── Step2-TemplateSelect.tsx
│   │   ├── Step3-InputParams/
│   │   │   ├── index.tsx
│   │   │   ├── TemplateHeader.tsx
│   │   │   ├── ParameterForm.tsx
│   │   │   ├── PromptPreview.tsx
│   │   │   └── ExtraRequest.tsx
│   │   ├── Step4-KnowledgeSelect.tsx
│   │   ├── Step5-ResultReview/
│   │   │   ├── index.tsx
│   │   │   ├── ResultOutput.tsx
│   │   │   ├── ResultActions.tsx
│   │   │   └── RatingSection.tsx
│   │   └── ExecutionBar.tsx     # 하단 실행 바
│   │
│   ├── modals/
│   │   ├── TemplateDetailModal.tsx
│   │   ├── VersionHistoryModal.tsx
│   │   ├── PromptPreviewModal.tsx
│   │   ├── ExportModal.tsx
│   │   ├── UploadModal.tsx
│   │   ├── SettingsModal.tsx
│   │   ├── RatingModal.tsx
│   │   └── ...
│   │
│   └── shared/
│       ├── LoadingSpinner.tsx
│       ├── EmptyState.tsx
│       ├── ErrorBoundary.tsx
│       └── Badge.tsx
│
├── hooks/
│   ├── useAuth.ts
│   ├── useTemplate.ts
│   ├── useWorkspace.ts
│   ├── useKnowledge.ts
│   ├── useSSE.ts                # SSE 스트리밍 훅
│   └── useDebounce.ts
│
├── stores/
│   ├── useAuthStore.ts          # 인증 상태
│   ├── useTemplateStore.ts      # 템플릿 목록/선택
│   ├── useWorkspaceStore.ts     # Step Wizard 상태
│   │   # - currentStep
│   │   # - inputValues
│   │   # - extraRequest
│   │   # - selectedKnowledgeSources
│   │   # - searchOptions
│   │   # - result
│   ├── useKnowledgeStore.ts     # 지식원 상태
│   └── useUIStore.ts            # UI 상태 (사이드바 접힘 등)
│
├── lib/
│   ├── api.ts                   # Axios 인스턴스
│   ├── sse.ts                   # SSE 클라이언트
│   ├── utils.ts                 # 유틸리티 함수
│   └── constants.ts             # 상수
│
├── types/
│   ├── auth.ts
│   ├── template.ts
│   ├── knowledge.ts
│   ├── execution.ts
│   └── api.ts
│
└── styles/
    └── globals.css              # CSS 변수 (기존 UI 기반)
```

### 3.3 백엔드 상세 구조

```
backend/app/
├── api/
│   ├── v1/
│   │   ├── __init__.py
│   │   ├── auth.py              # 인증 API
│   │   ├── prompts.py           # 프롬프트/템플릿 API
│   │   ├── variables.py         # 프롬프트 변수 API
│   │   ├── knowledge.py         # 지식원 API
│   │   ├── documents.py         # 문서 API
│   │   ├── rag.py               # RAG 검색 API
│   │   ├── execution.py         # 실행/결과 API
│   │   ├── export.py            # 내보내기 API
│   │   └── admin.py             # 관리자 API
│   ├── deps.py                  # 의존성 주입
│   └── router.py                # 라우터 통합
│
├── core/
│   ├── config.py                # 환경 설정
│   │   # - DATABASE_URL
│   │   # - REDIS_URL
│   │   # - ANTHROPIC_API_KEY
│   │   # - NETWORK_SHARE_PATH
│   │   # - JWT_SECRET
│   ├── security.py              # 인증/암호화
│   ├── database.py              # DB 연결 (async)
│   └── exceptions.py            # 커스텀 예외
│
├── models/                      # SQLAlchemy 모델
│   ├── __init__.py
│   ├── base.py                  # Base 클래스
│   ├── user.py
│   │   # - User
│   │   # - Department
│   ├── prompt.py
│   │   # - Prompt
│   │   # - PromptVariable
│   │   # - PromptVersion
│   │   # - Category
│   │   # - ApprovalRequest
│   ├── knowledge.py
│   │   # - KnowledgeSource
│   │   # - Document
│   │   # - DocumentChunk
│   └── execution.py
│       # - ExecutionLog
│       # - ReferenceLog
│       # - SearchWarning
│       # - ResultArchive
│       # - UserFeedback
│
├── schemas/                     # Pydantic 스키마
│   ├── auth.py
│   ├── prompt.py
│   ├── knowledge.py
│   ├── execution.py
│   └── common.py
│
├── services/                    # 비즈니스 로직
│   ├── auth_service.py
│   ├── prompt_service.py
│   ├── knowledge_service.py
│   ├── scanner_service.py       # 네트워크 폴더 스캔
│   ├── extractor_service.py     # 텍스트 추출
│   ├── chunker_service.py       # 청킹
│   ├── embedder_service.py      # 임베딩
│   ├── rag_service.py           # RAG 검색
│   ├── llm_service.py           # LLM 호출
│   ├── export_service.py        # 문서 변환
│   └── stats_service.py         # 통계
│
├── tasks/                       # Celery 태스크
│   ├── __init__.py
│   ├── celery_app.py
│   ├── scan_task.py             # 폴더 스캔
│   ├── index_task.py            # 문서 인덱싱
│   └── export_task.py           # 문서 변환
│
├── utils/
│   ├── file_utils.py
│   ├── text_utils.py
│   └── validators.py
│
└── main.py                      # FastAPI 앱 진입점
```

---

## 4. 핵심 컴포넌트 설계

### 4.1 Step Wizard 상태 관리

```typescript
// stores/useWorkspaceStore.ts

interface WorkspaceState {
  // 현재 단계
  currentStep: 1 | 2 | 3 | 4 | 5;
  completedSteps: Set<number>;

  // Step 1-2: 템플릿 선택
  selectedCategory: string | null;
  selectedTemplate: Template | null;

  // Step 3: 입력값
  inputValues: Record<string, string>;
  extraRequest: string;

  // Step 4: 지식원/검색 설정
  selectedKnowledgeSources: string[];
  searchOptions: {
    topK: number;
    sortBy: 'relevance' | 'recency' | 'hybrid';
    periodFilter: number | null;
    docTypes: string[];
    securityLevel: number;
  };

  // Step 5: 결과
  isGenerating: boolean;
  generationProgress: {
    stage: string;
    percent: number;
  };
  result: {
    text: string;
    references: Reference[];
    warnings: Warning[];
    tokenUsed: number;
    generationTime: number;
  } | null;

  // 액션
  setStep: (step: number) => void;
  setTemplate: (template: Template) => void;
  setInputValue: (key: string, value: string) => void;
  setExtraRequest: (text: string) => void;
  toggleKnowledgeSource: (id: string) => void;
  setSearchOption: <K extends keyof SearchOptions>(key: K, value: SearchOptions[K]) => void;
  startGeneration: () => Promise<void>;
  reset: () => void;
}
```

### 4.2 SSE 스트리밍 처리

```typescript
// hooks/useSSE.ts

export function useSSEGeneration() {
  const [isStreaming, setIsStreaming] = useState(false);
  const [content, setContent] = useState('');
  const [progress, setProgress] = useState({ stage: '', percent: 0 });

  const startStream = async (executionId: string) => {
    setIsStreaming(true);
    setContent('');

    const eventSource = new EventSource(
      `${API_URL}/api/run/${executionId}/stream`
    );

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'progress':
          setProgress({ stage: data.stage, percent: data.percent });
          break;
        case 'content':
          setContent((prev) => prev + data.text);
          break;
        case 'done':
          setIsStreaming(false);
          eventSource.close();
          break;
        case 'error':
          setIsStreaming(false);
          eventSource.close();
          throw new Error(data.message);
      }
    };

    eventSource.onerror = () => {
      setIsStreaming(false);
      eventSource.close();
    };
  };

  return { isStreaming, content, progress, startStream };
}
```

### 4.3 RAG 파이프라인

```python
# backend/app/services/rag_service.py

class RAGService:
    def __init__(self):
        self.embedder = KoSimCSEEmbedder()
        self.vector_store = FAISSVectorStore()

    async def search(
        self,
        query: str,
        knowledge_source_ids: list[int],
        top_k: int = 5,
        filters: dict = None
    ) -> list[ChunkResult]:
        """RAG 검색 수행"""

        # 1. 쿼리 임베딩
        query_embedding = await self.embedder.embed(query)

        # 2. 벡터 검색
        results = await self.vector_store.search(
            query_embedding=query_embedding,
            knowledge_source_ids=knowledge_source_ids,
            top_k=top_k,
            filters=filters
        )

        # 3. 점수 기반 필터링 및 경고 생성
        filtered_results = []
        warnings = []

        for result in results:
            if result.score < 0.5:
                warnings.append({
                    'type': 'low_score',
                    'message': f'관련도가 낮은 문서입니다: {result.doc_title}'
                })

            if result.doc_modified < datetime.now() - timedelta(days=365*2):
                warnings.append({
                    'type': 'outdated',
                    'message': f'2년 이상 된 문서입니다: {result.doc_title}'
                })

            filtered_results.append(result)

        return filtered_results, warnings
```

---

## 5. 데이터 흐름

### 5.1 AI 생성 실행 흐름

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Frontend (Next.js)                               │
├─────────────────────────────────────────────────────────────────────────┤
│  1. 사용자 입력 (템플릿, 변수, 지식원, 추가요청)                         │
│  2. POST /api/run → 실행 요청                                           │
│  3. GET /api/run/{id}/stream → SSE 연결                                 │
│  4. 스트리밍 응답 수신 → 실시간 UI 업데이트                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Backend (FastAPI)                                │
├─────────────────────────────────────────────────────────────────────────┤
│  1. 요청 검증 (입력값, 권한)                                             │
│  2. execution_logs 레코드 생성                                          │
│  3. RAG 검색 수행                                                        │
│     ├─ 쿼리 임베딩 생성                                                  │
│     ├─ FAISS 벡터 검색                                                   │
│     └─ 필터 적용 (기간, 문서유형, 보안등급)                              │
│  4. 프롬프트 조합                                                        │
│     ├─ system_prompt + user_prompt_template                              │
│     ├─ 변수 치환 ({{기관명}} → 과기정통부)                               │
│     ├─ RAG 컨텍스트 삽입                                                 │
│     └─ 추가 요청 삽입                                                    │
│  5. LLM 호출 (Claude API, 스트리밍)                                      │
│  6. SSE로 응답 전송                                                      │
│  7. 완료 시 execution_logs, reference_logs 저장                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      External Services                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  • Anthropic Claude API                                                  │
│  • FAISS Vector Store                                                    │
│  • MySQL Database                                                        │
│  • Network Share (\\diskstation\W2_프로젝트폴더)                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 문서 인덱싱 흐름

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Celery Worker (Background Task)                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. 폴더 스캔 (NetworkFolderScanner)                                     │
│     └─ \\diskstation\W2_프로젝트폴더\{source_path}                       │
│                                                                          │
│  2. 변경 감지                                                            │
│     ├─ 마지막 스캔 이후 신규 파일                                        │
│     └─ 마지막 스캔 이후 수정된 파일                                      │
│                                                                          │
│  3. 텍스트 추출 (ExtractorService)                                       │
│     ├─ PDF → pdfplumber                                                  │
│     ├─ HWP/HWPX → pyhwpx                                                 │
│     ├─ DOCX → python-docx                                                │
│     └─ XLSX → openpyxl                                                   │
│                                                                          │
│  4. 청킹 (ChunkerService)                                                │
│     └─ RecursiveCharacterTextSplitter (500토큰, 50 오버랩)               │
│                                                                          │
│  5. 임베딩 (EmbedderService)                                             │
│     └─ KoSimCSE-roberta                                                  │
│                                                                          │
│  6. 벡터 저장 (FAISS)                                                    │
│     └─ document_chunks 테이블 + FAISS 인덱스 파일                        │
│                                                                          │
│  7. 메타데이터 저장 (MySQL)                                              │
│     ├─ documents 테이블 업데이트                                         │
│     └─ knowledge_sources.last_scan_at 업데이트                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 개발 단계 (Phase)

### Phase 1: 기반 구축 (환경 설정)

| 작업 | 상세 | 산출물 |
|------|------|--------|
| 프로젝트 초기화 | Next.js, FastAPI 프로젝트 생성 | 프로젝트 구조 |
| Docker 설정 | docker-compose.yml (MySQL, Redis, FastAPI, Next.js) | 개발 환경 |
| DB 스키마 | Alembic 마이그레이션 스크립트 | 테이블 생성 |
| 기본 인증 | 로그인/로그아웃, JWT | 인증 API |
| CI/CD | GitHub Actions (선택) | 자동화 파이프라인 |

### Phase 2: 프론트엔드 기반

| 작업 | 상세 | 산출물 |
|------|------|--------|
| 레이아웃 구현 | 3-패널 레이아웃 (TopNav, Sidebar, Main, RightPanel) | 레이아웃 컴포넌트 |
| UI 컴포넌트 | Shadcn/ui 기반 공통 컴포넌트 | 컴포넌트 라이브러리 |
| 라우팅 | App Router 페이지 구조 | 페이지 파일 |
| 상태 관리 | Zustand 스토어 설정 | 스토어 파일 |
| CSS 이전 | 기존 HTML의 CSS 변수 → Tailwind 설정 | globals.css |

### Phase 3: 프롬프트/템플릿 시스템

| 작업 | 상세 | 산출물 |
|------|------|--------|
| 템플릿 CRUD API | 생성/조회/수정/삭제 | API 엔드포인트 |
| 변수 시스템 | 동적 폼 생성, 유효성 검증 | 변수 관리 |
| 버전 관리 | 버전 이력, 복원 | 버전 API |
| 승인 프로세스 | 개인 → 조직 표준 | 승인 워크플로우 |
| 프론트엔드 연동 | 사이드바, 템플릿 상세 | UI 통합 |

### Phase 4: RAG 파이프라인

| 작업 | 상세 | 산출물 |
|------|------|--------|
| 폴더 스캔 | NetworkFolderScanner 구현 | 스캔 서비스 |
| 텍스트 추출 | PDF, HWP, DOCX 파서 | 추출 서비스 |
| 청킹 | LangChain 기반 청킹 | 청커 서비스 |
| 임베딩 | KoSimCSE 모델 적용 | 임베더 서비스 |
| 벡터 검색 | FAISS 인덱스 | RAG 서비스 |
| 백그라운드 처리 | Celery 태스크 | 인덱싱 워커 |

### Phase 5: LLM 연동 및 생성

| 작업 | 상세 | 산출물 |
|------|------|--------|
| Claude API 연동 | Anthropic SDK 통합 | LLM 서비스 |
| 프롬프트 조합 | 템플릿 + 변수 + RAG 결합 | 프롬프트 빌더 |
| SSE 스트리밍 | 실시간 응답 전송 | SSE 엔드포인트 |
| 실행 이력 | execution_logs 저장 | 이력 서비스 |
| 프론트엔드 | Step Wizard 완성 | UI 통합 |

### Phase 6: 결과 후처리 및 이력

| 작업 | 상세 | 산출물 |
|------|------|--------|
| 내보내기 | DOCX, HWP, PDF 변환 | 내보내기 서비스 |
| 결과 보관함 | 저장/조회/공유 | 보관함 API |
| 평가 시스템 | 별점 + 피드백 | 평가 API |
| 재생성/부분수정 | 후속 LLM 호출 | 수정 API |
| 작업 이력 페이지 | 목록/상세/재사용 | 이력 UI |

### Phase 7: 관리자 기능

| 작업 | 상세 | 산출물 |
|------|------|--------|
| 관리자 대시보드 | 통계 시각화 | 대시보드 UI |
| 승인 관리 | 대기 목록, 승인/반려 | 승인 UI |
| 지식원 관리 | 문서 현황, 재인덱싱 | 지식원 UI |
| 사용자 관리 | 역할/권한 설정 | 사용자 UI |
| 감사 로그 | 접근/실행 이력 | 로그 UI |

### Phase 8: 고도화 및 최적화

| 작업 | 상세 | 산출물 |
|------|------|--------|
| 성능 최적화 | 쿼리 튜닝, 캐싱 | 최적화 |
| 보안 강화 | 암호화, 접근 제어 | 보안 적용 |
| 테스트 | 단위/통합/E2E | 테스트 코드 |
| 문서화 | API 문서, 사용자 가이드 | 문서 |
| 배포 | 프로덕션 환경 구성 | 배포 스크립트 |

---

## 7. 환경 변수 설정

```bash
# .env.example

# 데이터베이스
DATABASE_URL=mysql+aiomysql://user:password@localhost:3306/prompto_rag
REDIS_URL=redis://localhost:6379/0

# 인증
JWT_SECRET=your-super-secret-key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# LLM
ANTHROPIC_API_KEY=sk-ant-xxxxx
DEFAULT_MODEL=claude-sonnet-4
MAX_TOKENS=4096

# 네트워크 공유
NETWORK_SHARE_PATH=\\\\diskstation\\W2_프로젝트폴더
NETWORK_SHARE_USER=user
NETWORK_SHARE_PASSWORD=password

# 임베딩
EMBEDDING_MODEL=BM-K/KoSimCSE-roberta
EMBEDDING_DEVICE=cpu  # or cuda

# FAISS
FAISS_INDEX_PATH=./data/faiss

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# 프론트엔드
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 8. Docker Compose 구성

```yaml
# docker/docker-compose.yml

version: '3.8'

services:
  # MySQL
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: rootpass
      MYSQL_DATABASE: prompto_rag
      MYSQL_USER: prompto
      MYSQL_PASSWORD: prompto123
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
      - ./mysql/init.sql:/docker-entrypoint-initdb.d/init.sql

  # Redis
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  # FastAPI Backend
  backend:
    build:
      context: ../backend
      dockerfile: Dockerfile
    environment:
      - DATABASE_URL=mysql+aiomysql://prompto:prompto123@mysql:3306/prompto_rag
      - REDIS_URL=redis://redis:6379/0
    ports:
      - "8000:8000"
    volumes:
      - ../backend:/app
      - faiss_data:/app/data/faiss
    depends_on:
      - mysql
      - redis
    command: uvicorn app.main:app --host 0.0.0.0 --reload

  # Celery Worker
  celery:
    build:
      context: ../backend
      dockerfile: Dockerfile
    environment:
      - DATABASE_URL=mysql+aiomysql://prompto:prompto123@mysql:3306/prompto_rag
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
    volumes:
      - ../backend:/app
      - faiss_data:/app/data/faiss
    depends_on:
      - mysql
      - redis
    command: celery -A app.tasks.celery_app worker --loglevel=info

  # Next.js Frontend
  frontend:
    build:
      context: ../frontend
      dockerfile: Dockerfile
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
    ports:
      - "3000:3000"
    volumes:
      - ../frontend:/app
      - /app/node_modules
    depends_on:
      - backend
    command: npm run dev

volumes:
  mysql_data:
  redis_data:
  faiss_data:
```

---

## 9. 주요 API 엔드포인트

### 9.1 인증

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | /api/v1/auth/login | 로그인 |
| POST | /api/v1/auth/logout | 로그아웃 |
| POST | /api/v1/auth/refresh | 토큰 갱신 |
| GET | /api/v1/auth/me | 현재 사용자 |

### 9.2 템플릿

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | /api/v1/prompts | 목록 조회 |
| GET | /api/v1/prompts/{id} | 상세 조회 |
| POST | /api/v1/prompts | 생성 |
| PUT | /api/v1/prompts/{id} | 수정 |
| DELETE | /api/v1/prompts/{id} | 삭제 |
| GET | /api/v1/prompts/{id}/variables | 변수 목록 |
| GET | /api/v1/prompts/{id}/versions | 버전 이력 |

### 9.3 지식원

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | /api/v1/knowledge-sources | 목록 조회 |
| POST | /api/v1/knowledge-sources/{id}/scan | 스캔 시작 |
| GET | /api/v1/knowledge-sources/{id}/documents | 문서 목록 |

### 9.4 실행

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | /api/v1/run | 생성 실행 |
| GET | /api/v1/run/{id}/stream | SSE 스트리밍 |
| POST | /api/v1/run/{id}/regenerate | 재생성 |
| GET | /api/v1/execution-logs | 이력 목록 |
| GET | /api/v1/execution-logs/{id} | 이력 상세 |

---

## 10. 참고 문서

| 문서 | 설명 |
|------|------|
| PromptoRAG_UI_v1.0.html | 메인 UI 시안 |
| Step_Wizard_Page_Structure_2026-04-20.md | Step Wizard 단계별 구조 |
| PromptoRAG_Development_Plan_2026-04-20.md | 기존 개발 계획 |
| Design_Review_Checklist_2026-04-20.md | 디자인 검토 체크리스트 |
| CLAUDE.md | 프로젝트 가이드 |

---

**문서 끝**
