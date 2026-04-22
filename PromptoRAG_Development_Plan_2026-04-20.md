# PromptoRAG Development Plan

**작성일:** 2026-04-20
**버전:** 1.1
**프로젝트명:** PromptoRAG — 컨설팅 문서 재활용 및 AI 초안 생성 시스템

---

## 1. 프로젝트 개요

### 1.1 시스템 목적
PromptoRAG는 **컨설팅 업무에서 축적된 기존 문서를 검색·취합하여 새로운 문서 초안을 생성**하는 시스템입니다.

```
[기존 문서 검색] → [유사 문서 취합/요약] → [새 문서 초안 생성]
```

**핵심 문제 해결:**
- 과거 ISP/ISMP/ODA 등 컨설팅 산출물이 `\\diskstation\W2_프로젝트폴더`에 축적되어 있으나, 새 프로젝트 시작 시 유사 사례를 찾고 참조하는 데 많은 시간 소요
- 비슷한 유형의 제안서/보고서를 매번 처음부터 작성하는 비효율

**해결 방식:**
- RAG(Retrieval-Augmented Generation) 기반으로 기존 문서에서 관련 내용 자동 검색
- 검색된 문서를 참조하여 AI가 새 문서 초안 생성
- 작업 유형별 템플릿으로 반복 업무 표준화

### 1.2 핵심 작업 흐름

| 단계 | 작업 | 설명 |
|------|------|------|
| 1 | **문서 유형 선택** | ISP 계획서, ODA 제안서, 정책 분석 등 작업 템플릿 선택 |
| 2 | **검색 범위 지정** | 지식원 선택 (ISP 폴더, ODA 폴더, 전체 등) |
| 3 | **맥락 입력** | 기관명, 사업명, 목적 등 새 문서의 기본 정보 입력 |
| 4 | **기존 문서 검색** | AI가 지식원에서 유사한 기존 문서/내용 자동 검색 |
| 5 | **초안 생성** | 검색된 문서를 참조하여 새 문서 초안 생성 |
| 6 | **검토/수정** | 생성된 초안 검토, 부분 수정, 내보내기 |

### 1.3 핵심 가치
- **문서 재활용**: 기존 컨설팅 산출물을 새 프로젝트에 효과적으로 활용
- **작업 표준화**: 문서 유형별 템플릿으로 일관된 품질 유지
- **근거 투명성**: AI 생성 시 참조한 원본 문서 명시
- **지식 축적**: 생성된 문서와 실행 이력을 조직 자산으로 관리

### 1.4 대상 사용자
| 역할 | 설명 |
|------|------|
| 일반 사용자 | IT기획팀, 컨설팅팀 등 제안서/보고서 작성자 |
| 관리자 | 템플릿 승인, 지식원 관리, 품질 분석 담당자 |
| 시스템 관리자 | 인프라, 모델 정책, 감사 로그 관리 |

### 1.5 UI 메뉴 구성 (권장)

| 현재 UI 명칭 | 권장 변경 | 역할 |
|-------------|----------|------|
| 🏠 홈 | 🏠 대시보드 | 최근 작업, 통계 요약 |
| 📚 프롬프트 라이브러리 | 📚 작업 템플릿 | 문서 유형별 템플릿 목록/관리 |
| ▶ 새 작업 실행 | ▶ 새 문서 작성 | 템플릿 선택 → 검색 → 초안 생성 |
| 📋 실행 이력 | 📋 작업 이력 | 과거 생성 결과 조회/재활용 |
| ⚙ 관리자 | ⚙ 관리자 | 템플릿 승인, 지식원 관리 |

### 1.6 작업 이력 페이지 설계

작업 이력은 단순 로그가 아닌 **재활용 가능한 작업 자산**으로 설계합니다.

#### 1.6.1 설계 방향

| 구분 | 단순 로그 | 권장: 작업 자산 |
|------|----------|----------------|
| 목적 | 기록 열람 | **재활용 + 기록** |
| 주요 액션 | 조회만 | 재실행, 결과 복사, 수정 후 재생성 |
| 데이터 | 시간, 템플릿명 | 입력값, 결과물, 참조 문서 전체 |

#### 1.6.2 목록 화면 구성

```
┌─────────────────────────────────────────────────────────────┐
│ 📋 작업 이력                                    [검색] [필터] │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ISP 사업계획서 초안 생성                    2026-04-20 │ │
│ │ 과기정통부 / 행정업무 AX ISP        ★★★★☆  [재사용] │ │
│ │ 참조문서 3건 · 토큰 1,847                              │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ODA 제안서 작성                            2026-04-18 │ │
│ │ 농림부 / 스마트팜 역량강화          ★★★★★  [재사용] │ │
│ │ 참조문서 5건 · 토큰 2,103                              │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

#### 1.6.3 목록 항목별 표시 정보

| 필드 | 설명 |
|------|------|
| 템플릿명 | 사용한 작업 템플릿 |
| 입력 요약 | 기관명, 사업명 등 핵심 파라미터 |
| 실행 일시 | 작업 수행 시각 |
| 참조 문서 | 검색된 근거 문서 수 |
| 평가 | 사용자 만족도 (별점) |
| 토큰/모델 | 사용된 리소스 |

#### 1.6.4 상세 화면 (항목 클릭 시)

| 탭 | 내용 |
|----|------|
| **결과물** | 생성된 문서 전체 (복사/내보내기 가능) |
| **입력값** | 당시 입력한 파라미터 전체 |
| **참조 문서** | 검색된 근거 문서 목록 + 발췌 내용 |
| **프롬프트** | 실제 전송된 최종 프롬프트 |

#### 1.6.5 주요 액션 버튼

| 버튼 | 기능 |
|------|------|
| **입력값으로 재실행** | 동일 설정으로 새로 생성 |
| **입력값 수정 후 실행** | 파라미터 일부 변경 후 실행 |
| **결과물 복사** | 클립보드 복사 |
| **내보내기** | docx/hwp/pdf 다운로드 |
| **보관함 저장** | 결과 보관함에 별도 저장 |

#### 1.6.6 필터/검색 옵션

| 필터 | 옵션 |
|------|------|
| 기간 | 오늘, 이번 주, 이번 달, 직접 설정 |
| 템플릿 | 전체, ISP, ISMP, ODA, 정책분석 등 |
| 평가 | 전체, ★4 이상, ★3 이하 |
| 키워드 | 기관명, 사업명 등 텍스트 검색 |

---

## 2. 현재 상태 분석 (UI 프로토타입 기준)

### 2.1 구현 완료 항목 (프론트엔드 UI/UX)

#### 2.1.1 레이아웃 구조
- **Top Navigation**: 로고, 탭 메뉴(홈/라이브러리/새 작업/이력/관리자), 사용자 정보
- **Left Sidebar** (270px): 프롬프트 검색, 필터 칩, 즐겨찾기/조직 표준/개인 저장 템플릿 목록
- **Main Center**: Step Wizard(5단계), 템플릿 헤더, 입력 파라미터 폼, 추가 요청, AI 결과, 실행 이력
- **Right Panel** (320px): 지식원 선택, 검색 조건 설정, 근거 문서, 주의 알림, 통계

#### 2.1.2 주요 모달
| 모달 ID | 기능 |
|---------|------|
| modal-params | 입력 파라미터 도움말 + DB 구조 |
| modal-extra | 추가 요청 입력 도움말 |
| modal-result | AI 생성 결과 후처리 기능 |
| modal-ks | 지식원 선택 도움말 + RAG 구현 안내 |
| modal-search-opt | 검색 조건 설정 (Top-K, 정렬, 기간, 보안) |
| modal-ref | 근거 문서 패널 설명 |
| modal-warn | 주의 알림 유형 |
| modal-template-detail | 템플릿 상세 (프롬프트 본문/메타/출력형식/DB) |
| modal-version | 버전 이력 관리 |
| modal-preview | 최종 프롬프트 미리보기 |
| modal-export | 결과 내보내기 (docx/hwpx/pdf/txt) |
| modal-history | 나의 실행 이력 |
| modal-new-prompt | 새 프롬프트 템플릿 만들기 |
| modal-admin | 관리자 대시보드 |
| modal-approve-mgmt | 승인 대기 목록 |
| modal-settings | 모델 설정 (Temperature, Max Tokens) |
| modal-rate | 결과 평가 |
| modal-save-result | 결과 보관함 저장 |
| modal-upload | 문서 업로드 |
| modal-prompt-mgmt | 프롬프트 관리 (관리자) |

#### 2.1.3 인터랙션 (JavaScript)
- 모달 열기/닫기
- 탭 전환
- 아코디언 토글
- 템플릿 선택
- 지식원 토글 (다중 선택)
- 필터 칩 토글
- 프롬프트 미리보기 실시간 업데이트
- 추가 요청 빠른 선택
- 입력값 초기화
- AI 생성 실행 시뮬레이션 (프로그레스 바, 단계별 메시지)
- 근거 문서 표시
- 결과 복사
- 평가 (별점)
- Step Wizard 전환
- 템플릿 검색 필터
- Toast 알림

### 2.2 미구현 항목 (백엔드/인프라)

| 영역 | 미구현 내용 |
|------|------------|
| 데이터베이스 | 모든 테이블 실제 생성 및 연동 |
| API 서버 | FastAPI/Django 기반 REST API |
| 인증/인가 | 사용자 로그인, 세션 관리, 역할별 권한 |
| RAG 파이프라인 | 문서 수집, 청킹, 임베딩, 벡터 검색 |
| LLM 연동 | Claude/GPT API 호출, 스트리밍 응답 |
| 파일 내보내기 | docx/hwpx/pdf 변환 서버 |
| 문서 업로드 | 파일 저장, OCR, 인덱싱 파이프라인 |

---

## 3. 데이터베이스 설계

### 3.1 ERD 개요

```
┌─────────────────┐      ┌─────────────────┐
│     users       │      │   departments   │
├─────────────────┤      ├─────────────────┤
│ id (PK)         │──┐   │ id (PK)         │
│ email           │  │   │ name            │
│ name            │  │   │ created_at      │
│ dept_id (FK)    │──┼───│                 │
│ role            │  │   └─────────────────┘
│ created_at      │  │
└─────────────────┘  │
                     │
┌─────────────────┐  │   ┌─────────────────┐
│   categories    │  │   │   prompts       │
├─────────────────┤  │   ├─────────────────┤
│ id (PK)         │──┼───│ id (PK)         │
│ name            │  │   │ tpl_code        │
│ parent_id       │  │   │ name            │
│ icon            │  │   │ category_id (FK)│
└─────────────────┘  │   │ description     │
                     │   │ system_prompt   │
                     │   │ user_prompt_tpl │
                     │   │ output_format   │
                     │   │ rag_enabled     │
                     │   │ rec_model       │
                     │   │ rec_top_k       │
                     │   │ creator_id (FK) │───┘
                     │   │ dept_id (FK)    │
                     │   │ status          │
                     │   │ version         │
                     │   │ created_at      │
                     │   └─────────────────┘
```

### 3.2 테이블 상세

#### 3.2.1 사용자 관리

```sql
-- 부서 테이블
CREATE TABLE departments (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    name        VARCHAR(100) NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 사용자 테이블
CREATE TABLE users (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    email       VARCHAR(200) UNIQUE NOT NULL,
    password    VARCHAR(255) NOT NULL,
    name        VARCHAR(100) NOT NULL,
    dept_id     INT,
    role        ENUM('user', 'admin', 'superadmin') DEFAULT 'user',
    avatar      VARCHAR(10),
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME,
    FOREIGN KEY (dept_id) REFERENCES departments(id)
);
```

#### 3.2.2 프롬프트 관리

```sql
-- 카테고리 테이블
CREATE TABLE categories (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    name        VARCHAR(100) NOT NULL,
    parent_id   INT,
    icon        VARCHAR(50),
    sort_order  INT DEFAULT 0,
    FOREIGN KEY (parent_id) REFERENCES categories(id)
);

-- 프롬프트 마스터 테이블
CREATE TABLE prompts (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    tpl_code        VARCHAR(30) UNIQUE,
    name            VARCHAR(200) NOT NULL,
    category_id     INT,
    description     TEXT,
    system_prompt   LONGTEXT,
    user_prompt_tpl LONGTEXT,
    output_format   TEXT,
    forbidden_rules TEXT,
    rag_enabled     BOOLEAN DEFAULT TRUE,
    rec_ks_ids      JSON,
    rec_model       VARCHAR(50) DEFAULT 'claude-sonnet-4',
    rec_top_k       TINYINT DEFAULT 5,
    creator_id      INT NOT NULL,
    dept_id         INT,
    status          ENUM('draft', 'review', 'approved', 'deprecated') DEFAULT 'draft',
    version         VARCHAR(10) DEFAULT '1.0',
    is_favorite     BOOLEAN DEFAULT FALSE,
    tags            JSON,
    usage_count     INT DEFAULT 0,
    avg_rating      DECIMAL(2,1) DEFAULT 0.0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME,
    FOREIGN KEY (category_id) REFERENCES categories(id),
    FOREIGN KEY (creator_id) REFERENCES users(id),
    FOREIGN KEY (dept_id) REFERENCES departments(id)
);

-- 프롬프트 변수 정의 테이블
CREATE TABLE prompt_variables (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    prompt_id   INT NOT NULL,
    var_name    VARCHAR(50) NOT NULL,
    label       VARCHAR(100) NOT NULL,
    input_type  ENUM('text', 'textarea', 'select', 'number', 'date') DEFAULT 'text',
    is_required BOOLEAN DEFAULT TRUE,
    default_val TEXT,
    example_val TEXT,
    placeholder TEXT,
    options     JSON,
    hint        TEXT,
    sort_order  INT DEFAULT 0,
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE
);

-- 프롬프트 버전 이력 테이블
CREATE TABLE prompt_versions (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    prompt_id       INT NOT NULL,
    version         VARCHAR(10) NOT NULL,
    system_prompt   LONGTEXT,
    user_prompt_tpl LONGTEXT,
    change_reason   TEXT,
    changed_by      INT,
    approved_by     INT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
    FOREIGN KEY (changed_by) REFERENCES users(id),
    FOREIGN KEY (approved_by) REFERENCES users(id)
);

-- 승인 요청 테이블
CREATE TABLE approval_requests (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    prompt_id   INT NOT NULL,
    requester   INT NOT NULL,
    approver    INT,
    status      ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
    reason      TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    decided_at  DATETIME,
    FOREIGN KEY (prompt_id) REFERENCES prompts(id),
    FOREIGN KEY (requester) REFERENCES users(id),
    FOREIGN KEY (approver) REFERENCES users(id)
);
```

#### 3.2.3 지식원 관리

**실제 문서 저장 위치:** `\\diskstation\W2_프로젝트폴더`

> 회사의 컨설팅 업무에서 작성한 모든 문서가 이 네트워크 공유 폴더에 저장되어 있습니다.
> 지식원 시스템은 이 폴더를 스캔하여 문서를 수집하고 인덱싱합니다.

```sql
-- 지식원(Knowledge Source) 관리 테이블
CREATE TABLE knowledge_sources (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    name          VARCHAR(100) NOT NULL,
    description   TEXT,
    ks_type       ENUM('global', 'dept', 'project', 'personal', 'policy') DEFAULT 'global',
    source_path   VARCHAR(500),              -- 실제 문서 경로 (예: \\diskstation\W2_프로젝트폴더\ISP)
    vector_index  VARCHAR(200),
    doc_count     INT DEFAULT 0,
    access_level  TINYINT DEFAULT 1,
    owner_id      INT,
    dept_id       INT,
    icon          VARCHAR(50),
    is_active     BOOLEAN DEFAULT TRUE,
    last_scan_at  DATETIME,                  -- 마지막 폴더 스캔 시각
    scan_status   ENUM('idle', 'scanning', 'indexing', 'completed', 'failed') DEFAULT 'idle',
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME,
    FOREIGN KEY (owner_id) REFERENCES users(id),
    FOREIGN KEY (dept_id) REFERENCES departments(id)
);

-- 문서 테이블
CREATE TABLE documents (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    ks_id           INT NOT NULL,
    title           VARCHAR(500) NOT NULL,
    file_path       VARCHAR(500),            -- 원본 파일 경로 (예: \\diskstation\W2_프로젝트폴더\ISP\보고서.hwp)
    relative_path   VARCHAR(500),            -- 상대 경로 (예: ISP\보고서.hwp)
    file_type       VARCHAR(20),
    file_size       BIGINT,
    page_count      INT,
    content_text    LONGTEXT,
    file_modified   DATETIME,                -- 원본 파일 최종 수정일
    upload_by       INT,
    security_level  TINYINT DEFAULT 1,
    ocr_status      ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending',
    index_status    ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME,
    FOREIGN KEY (ks_id) REFERENCES knowledge_sources(id),
    FOREIGN KEY (upload_by) REFERENCES users(id)
);

-- 문서 청크 테이블 (RAG용)
CREATE TABLE document_chunks (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    doc_id      INT NOT NULL,
    chunk_index INT NOT NULL,
    chunk_text  TEXT NOT NULL,
    page_num    INT,
    para_num    INT,
    token_count INT,
    embedding   BLOB,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,
    INDEX idx_doc_chunk (doc_id, chunk_index)
);
```

#### 3.2.4 실행 및 결과 관리

```sql
-- 실행 이력 테이블
CREATE TABLE execution_logs (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    user_id         INT NOT NULL,
    prompt_id       INT NOT NULL,
    prompt_version  VARCHAR(10),
    input_vars      JSON,
    extra_request   TEXT,
    ks_ids          JSON,
    search_params   JSON,
    model_used      VARCHAR(50),
    temperature     DECIMAL(2,1),
    max_tokens      INT,
    final_prompt    LONGTEXT,
    result_text     LONGTEXT,
    tokens_used     INT,
    generation_time DECIMAL(5,2),
    rating          TINYINT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (prompt_id) REFERENCES prompts(id)
);

-- 근거 문서 이력 테이블
CREATE TABLE reference_logs (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    exec_log_id INT NOT NULL,
    doc_id      INT,
    chunk_id    INT,
    chunk_text  TEXT,
    score       DECIMAL(4,3),
    page_num    INT,
    para_num    INT,
    is_applied  BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (exec_log_id) REFERENCES execution_logs(id) ON DELETE CASCADE,
    FOREIGN KEY (doc_id) REFERENCES documents(id),
    FOREIGN KEY (chunk_id) REFERENCES document_chunks(id)
);

-- 검색 품질 경고 테이블
CREATE TABLE search_warnings (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    exec_log_id INT NOT NULL,
    warn_type   ENUM('low_score', 'outdated', 'conflict', 'permission', 'ocr_pending'),
    warn_level  ENUM('info', 'warning', 'error') DEFAULT 'info',
    message     TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (exec_log_id) REFERENCES execution_logs(id) ON DELETE CASCADE
);

-- 결과 보관함 테이블
CREATE TABLE result_archive (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    exec_log_id   INT,
    user_id       INT NOT NULL,
    title         VARCHAR(200) NOT NULL,
    content       LONGTEXT,
    format        VARCHAR(20) DEFAULT 'html',
    tags          JSON,
    is_shared     BOOLEAN DEFAULT FALSE,
    retention     ENUM('1year', '3years', 'permanent') DEFAULT '1year',
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME,
    FOREIGN KEY (exec_log_id) REFERENCES execution_logs(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 사용자 피드백 테이블
CREATE TABLE user_feedbacks (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    exec_log_id INT NOT NULL,
    user_id     INT NOT NULL,
    rating      TINYINT NOT NULL,
    fail_types  JSON,
    comment     TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (exec_log_id) REFERENCES execution_logs(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

#### 3.2.5 사용자 설정

```sql
-- 사용자 검색 기본 설정
CREATE TABLE user_search_prefs (
    user_id       INT PRIMARY KEY,
    top_k         INT DEFAULT 5,
    sort_mode     ENUM('relevance', 'recency', 'hybrid') DEFAULT 'relevance',
    period_filter INT,
    doc_types     JSON,
    security_max  TINYINT DEFAULT 1,
    updated_at    DATETIME,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 사용자 즐겨찾기
CREATE TABLE user_favorites (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    user_id     INT NOT NULL,
    prompt_id   INT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY (user_id, prompt_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (prompt_id) REFERENCES prompts(id)
);
```

---

## 4. API 설계

### 4.1 인증 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | /api/auth/login | 로그인 |
| POST | /api/auth/logout | 로그아웃 |
| GET | /api/auth/me | 현재 사용자 정보 |
| POST | /api/auth/refresh | 토큰 갱신 |

### 4.2 프롬프트 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | /api/prompts | 프롬프트 목록 조회 (필터/검색/페이징) |
| GET | /api/prompts/{id} | 프롬프트 상세 조회 |
| POST | /api/prompts | 프롬프트 생성 |
| PUT | /api/prompts/{id} | 프롬프트 수정 |
| DELETE | /api/prompts/{id} | 프롬프트 삭제 |
| GET | /api/prompts/{id}/variables | 변수 목록 조회 |
| POST | /api/prompts/{id}/variables | 변수 추가 |
| GET | /api/prompts/{id}/versions | 버전 이력 조회 |
| POST | /api/prompts/{id}/versions | 새 버전 생성 |
| POST | /api/prompts/{id}/restore/{version} | 버전 복원 |
| POST | /api/prompts/{id}/favorite | 즐겨찾기 토글 |

### 4.3 지식원 API

**기본 문서 경로:** `\\diskstation\W2_프로젝트폴더`

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | /api/knowledge-sources | 지식원 목록 조회 |
| GET | /api/knowledge-sources/{id} | 지식원 상세 조회 |
| POST | /api/knowledge-sources | 지식원 생성 (source_path 지정) |
| PUT | /api/knowledge-sources/{id} | 지식원 수정 |
| DELETE | /api/knowledge-sources/{id} | 지식원 삭제 |
| GET | /api/knowledge-sources/{id}/documents | 문서 목록 조회 |
| POST | /api/knowledge-sources/{id}/documents | 문서 업로드 |
| POST | /api/knowledge-sources/{id}/scan | 폴더 스캔 시작 (신규/변경 문서 탐지) |
| GET | /api/knowledge-sources/{id}/scan-status | 스캔 상태 조회 |
| POST | /api/knowledge-sources/{id}/reindex | 전체 재인덱싱 |
| GET | /api/knowledge-sources/browse | 네트워크 폴더 탐색 (하위 폴더 목록) |

### 4.4 RAG/실행 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | /api/rag/search | RAG 검색 (청크 반환) |
| POST | /api/run | AI 생성 실행 |
| GET | /api/run/{exec_id}/stream | SSE 스트리밍 응답 |
| POST | /api/run/{exec_id}/regenerate | 재생성 |
| POST | /api/run/{exec_id}/partial-edit | 부분 수정 요청 |

### 4.5 결과/이력 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | /api/execution-logs | 실행 이력 조회 |
| GET | /api/execution-logs/{id} | 실행 이력 상세 |
| POST | /api/result-archive | 결과 보관함 저장 |
| GET | /api/result-archive | 보관함 목록 조회 |
| DELETE | /api/result-archive/{id} | 보관함 삭제 |
| POST | /api/export | 결과 내보내기 (docx/hwpx/pdf) |

### 4.6 평가/피드백 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | /api/feedbacks | 피드백 제출 |
| GET | /api/prompts/{id}/stats | 템플릿 품질 통계 |

### 4.7 관리자 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | /api/admin/approvals | 승인 대기 목록 |
| POST | /api/admin/approvals/{id}/approve | 승인 처리 |
| POST | /api/admin/approvals/{id}/reject | 반려 처리 |
| GET | /api/admin/audit-logs | 감사 로그 조회 |
| GET | /api/admin/dashboard | 관리자 대시보드 통계 |

---

## 5. RAG 파이프라인 설계

### 5.1 문서 저장소 구조

**기본 경로:** `\\diskstation\W2_프로젝트폴더`

```
\\diskstation\W2_프로젝트폴더\
├── ISP/                        → 지식원: ISP 사업문서
│   ├── 2024_과기정통부_ISP/
│   │   ├── 제안서.hwp
│   │   ├── 현황분석.xlsx
│   │   └── 최종보고서.pdf
│   └── 2023_행안부_ISP/
├── ISMP/                       → 지식원: ISMP 사업문서
├── ODA/                        → 지식원: ODA 제안서
├── 정책연구/                   → 지식원: 정책/법령 문서
├── 내부문서/                   → 지식원: 부서 공유 문서
│   ├── 회의록/
│   ├── 가이드라인/
│   └── 템플릿/
└── 레퍼런스/                   → 지식원: 참고자료
    ├── 법령/
    └── 표준/
```

### 5.2 문서 수집 흐름

```
[네트워크 폴더 스캔] → [변경 감지] → [텍스트 추출] → [청킹] → [임베딩] → [벡터DB]
        │                  │              │            │          │           │
        ▼                  ▼              ▼            ▼          ▼           ▼
 \\diskstation\W2_*   신규/수정 파일   PDF/HWP/DOCX  500토큰   KoSimCSE   FAISS/Chroma
                       타임스탬프 비교  텍스트 추출   단위 분할  또는 OpenAI
```

### 5.3 네트워크 폴더 스캔 로직

```python
import os
from pathlib import Path
from datetime import datetime

class NetworkFolderScanner:
    """네트워크 공유 폴더에서 문서를 스캔하는 클래스"""

    BASE_PATH = r"\\diskstation\W2_프로젝트폴더"
    SUPPORTED_EXTENSIONS = {'.pdf', '.hwp', '.hwpx', '.docx', '.xlsx', '.pptx', '.txt'}

    def __init__(self, source_path: str):
        """
        Args:
            source_path: 스캔할 경로 (예: \\diskstation\W2_프로젝트폴더\ISP)
        """
        self.source_path = Path(source_path)

    def scan_folder(self, last_scan_time: datetime = None) -> list:
        """
        폴더를 스캔하여 문서 목록 반환

        Args:
            last_scan_time: 마지막 스캔 시각 (None이면 전체 스캔)

        Returns:
            list of dict: [{
                'file_path': str,
                'relative_path': str,
                'file_name': str,
                'file_type': str,
                'file_size': int,
                'modified_time': datetime,
                'is_new': bool
            }]
        """
        documents = []

        for root, dirs, files in os.walk(self.source_path):
            # 숨김 폴더 제외
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for file in files:
                file_path = Path(root) / file
                ext = file_path.suffix.lower()

                if ext not in self.SUPPORTED_EXTENSIONS:
                    continue

                stat = file_path.stat()
                modified_time = datetime.fromtimestamp(stat.st_mtime)

                # 변경 감지: 마지막 스캔 이후 수정된 파일만
                if last_scan_time and modified_time <= last_scan_time:
                    continue

                documents.append({
                    'file_path': str(file_path),
                    'relative_path': str(file_path.relative_to(self.source_path)),
                    'file_name': file,
                    'file_type': ext[1:],  # .hwp → hwp
                    'file_size': stat.st_size,
                    'modified_time': modified_time,
                    'is_new': last_scan_time is None or modified_time > last_scan_time
                })

        return documents

    def get_folder_tree(self, max_depth: int = 3) -> dict:
        """
        폴더 트리 구조 반환 (지식원 선택 UI용)
        """
        def build_tree(path: Path, depth: int) -> dict:
            if depth > max_depth:
                return None

            result = {
                'name': path.name,
                'path': str(path),
                'children': []
            }

            try:
                for item in sorted(path.iterdir()):
                    if item.is_dir() and not item.name.startswith('.'):
                        child = build_tree(item, depth + 1)
                        if child:
                            result['children'].append(child)
            except PermissionError:
                pass

            return result

        return build_tree(self.source_path, 0)


# 사용 예시
scanner = NetworkFolderScanner(r"\\diskstation\W2_프로젝트폴더\ISP")
new_docs = scanner.scan_folder(last_scan_time=datetime(2026, 4, 1))
```

### 5.4 지식원 자동 구성 예시

| 지식원 이름 | source_path | 설명 |
|------------|-------------|------|
| 전체 문서 저장소 | `\\diskstation\W2_프로젝트폴더` | 모든 컨설팅 문서 |
| ISP 사업문서 | `\\diskstation\W2_프로젝트폴더\ISP` | ISP 관련 제안서/보고서 |
| ISMP 사업문서 | `\\diskstation\W2_프로젝트폴더\ISMP` | ISMP 관련 문서 |
| ODA 제안서 | `\\diskstation\W2_프로젝트폴더\ODA` | ODA 사업 문서 |
| 정책/법령 문서 | `\\diskstation\W2_프로젝트폴더\정책연구` | 정책 연구 자료 |
| 부서 공유 문서 | `\\diskstation\W2_프로젝트폴더\내부문서` | 내부 가이드, 회의록 |

### 5.5 텍스트 추출 도구

| 파일 형식 | 추출 라이브러리 |
|----------|----------------|
| PDF | pdfplumber, PyPDF2, PDFMiner |
| HWP/HWPX | hwp5, pyhwpx, LibreOffice 변환 |
| DOCX | python-docx |
| XLSX | openpyxl, pandas |
| TXT | 기본 텍스트 읽기 |

### 5.3 청킹 전략

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    separators=["\n\n", "\n", ".", " "]
)
chunks = splitter.split_text(document_text)
```

### 5.4 임베딩 모델

| 모델 | 특징 |
|------|------|
| KoSimCSE | 한국어 특화, 경량, 오프라인 가능 |
| OpenAI text-embedding-3-small | 고성능, API 의존 |
| HuggingFace multilingual-e5 | 다국어 지원, 오픈소스 |

### 5.5 벡터 검색

```python
from langchain.vectorstores import FAISS, Chroma

# 검색 수행
results = vectorstore.similarity_search_with_score(
    query=user_query,
    k=top_k,
    filter={"security_level": {"$lte": user_security_level}}
)
```

---

## 6. LLM 연동 설계

### 6.1 지원 모델

| 모델 | 용도 |
|------|------|
| claude-sonnet-4 | 일반 보고서 (권장) |
| claude-opus-4 | 고품질 분석/연구 |
| claude-haiku-4-5 | 빠른 요약/질의응답 |
| gpt-4o | 대체 옵션 |

### 6.2 프롬프트 구성

```python
def build_final_prompt(template, variables, rag_context, extra_request):
    system_prompt = template.system_prompt
    user_prompt = template.user_prompt_tpl.format(**variables)

    if rag_context:
        user_prompt += f"\n\n참조근거:\n{rag_context}"

    if extra_request:
        user_prompt += f"\n\n추가요청: {extra_request}"

    return {
        "system": system_prompt,
        "user": user_prompt
    }
```

### 6.3 스트리밍 응답

```python
from anthropic import Anthropic

client = Anthropic()

async def generate_stream(prompt, model, max_tokens, temperature):
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=prompt["system"],
        messages=[{"role": "user", "content": prompt["user"]}]
    ) as stream:
        for text in stream.text_stream:
            yield text
```

---

## 7. 기술 스택 권장

### 7.1 백엔드

| 구성요소 | 기술 |
|----------|------|
| 웹 프레임워크 | FastAPI (Python) 또는 Django REST Framework |
| 비동기 처리 | asyncio, Celery (문서 인덱싱용) |
| ORM | SQLAlchemy / Django ORM |
| 인증 | JWT (PyJWT) |
| API 문서 | OpenAPI (Swagger) |

### 7.2 프론트엔드

| 구성요소 | 기술 |
|----------|------|
| 프레임워크 | React / Vue.js / Next.js |
| 상태관리 | Zustand / Redux Toolkit |
| UI 컴포넌트 | Tailwind CSS / Shadcn |
| HTTP 클라이언트 | Axios / TanStack Query |

### 7.3 데이터베이스 & 인프라

| 구성요소 | 기술 |
|----------|------|
| RDBMS | MySQL 8.0 / PostgreSQL |
| 벡터DB | FAISS / Chroma / Pinecone |
| 캐시 | Redis |
| 파일 저장 | AWS S3 / MinIO |
| 컨테이너 | Docker + Docker Compose |
| 오케스트레이션 | Kubernetes (선택) |

---

## 8. 개발 단계별 계획

### Phase 1: 기반 구축

**목표:** 기본 인프라 및 인증 시스템 구축

| 작업 | 상세 |
|------|------|
| 개발 환경 설정 | Docker Compose 기반 로컬 환경 |
| 데이터베이스 구축 | MySQL 테이블 생성, 마이그레이션 스크립트 |
| 인증 시스템 | 로그인/로그아웃, JWT 토큰, 역할 기반 접근 제어 |
| 기본 API 구조 | FastAPI 프로젝트 구조, 라우터 설정 |

### Phase 2: 프롬프트 관리

**목표:** 프롬프트 CRUD 및 버전 관리

| 작업 | 상세 |
|------|------|
| 프롬프트 CRUD | 생성/조회/수정/삭제 API |
| 변수 시스템 | 동적 폼 생성을 위한 변수 정의 |
| 버전 관리 | 버전 이력 저장 및 복원 |
| 승인 프로세스 | 개인→조직 표준 승격 워크플로우 |
| 프론트엔드 연동 | 기존 UI와 API 연결 |

### Phase 3: RAG 시스템

**목표:** 네트워크 폴더 기반 문서 수집 및 벡터 검색 구현

**문서 저장소:** `\\diskstation\W2_프로젝트폴더`

| 작업 | 상세 |
|------|------|
| 네트워크 폴더 연결 | `\\diskstation\W2_프로젝트폴더` 접근 권한 설정, SMB 마운트 |
| 폴더 스캔 서비스 | NetworkFolderScanner 클래스 구현, 변경 감지 로직 |
| 지식원 자동 생성 | 하위 폴더 기반 지식원 구성 (ISP, ISMP, ODA 등) |
| 텍스트 추출 | PDF/HWP/HWPX/DOCX/XLSX 파서 구현 |
| 청킹 파이프라인 | RecursiveCharacterTextSplitter 적용 (500토큰, 50 오버랩) |
| 임베딩 생성 | KoSimCSE (한국어 특화) 또는 OpenAI text-embedding-3 |
| 벡터 검색 | FAISS 인덱스 생성 및 쿼리 |
| 비동기 인덱싱 | Celery 기반 백그라운드 처리, 스캔/인덱싱 상태 관리 |
| 증분 업데이트 | 파일 수정 시각 기반 변경된 문서만 재인덱싱 |

### Phase 4: LLM 연동

**목표:** AI 생성 및 스트리밍 구현

| 작업 | 상세 |
|------|------|
| Claude API 연동 | Anthropic SDK 통합 |
| 프롬프트 조합 | 템플릿 + 변수 + RAG 컨텍스트 결합 |
| 스트리밍 응답 | SSE(Server-Sent Events) 구현 |
| 실행 이력 저장 | execution_logs 테이블 저장 |
| 근거 문서 저장 | reference_logs 테이블 저장 |

### Phase 5: 결과 후처리

**목표:** 내보내기, 평가, 재사용 기능

| 작업 | 상세 |
|------|------|
| 결과 내보내기 | docx/hwpx/pdf 변환 서버 |
| 결과 보관함 | 저장/조회/공유 기능 |
| 평가 시스템 | 별점 + 피드백 수집 |
| 재생성/부분수정 | 후속 LLM 호출 |
| 품질 통계 | 템플릿별 성공률/만족도 분석 |

### Phase 6: 관리자 기능

**목표:** 거버넌스 및 모니터링

| 작업 | 상세 |
|------|------|
| 관리자 대시보드 | 통계 시각화 |
| 승인 관리 | 대기 목록, 승인/반려 처리 |
| 지식원 관리 | 문서 현황, 인덱스 재구축 |
| 모델 정책 | 허용 모델, 토큰 제한 설정 |
| 감사 로그 | 사용자별 접근/실행 이력 |

### Phase 7: 고도화

**목표:** 성능 최적화 및 확장

| 작업 | 상세 |
|------|------|
| 캐싱 | Redis 기반 검색 결과 캐싱 |
| 성능 최적화 | 쿼리 튜닝, 인덱스 최적화 |
| 확장성 | 수평 확장 아키텍처 |
| 보안 강화 | 암호화, 접근 제어 고도화 |
| 모니터링 | 로그 수집, 알림 시스템 |

---

## 9. 보안 고려사항

### 9.1 인증/인가
- JWT 토큰 기반 인증
- Refresh Token 분리 관리
- 역할 기반 접근 제어 (RBAC)
- API Rate Limiting

### 9.2 데이터 보안
- 비밀번호 bcrypt 해싱
- 중요 데이터 AES-256 암호화
- 문서 보안 등급별 접근 제어
- 개인정보 마스킹

### 9.3 인프라 보안
- HTTPS 필수
- CORS 정책 설정
- SQL Injection 방지 (ORM 사용)
- XSS/CSRF 방지

### 9.4 감사
- 모든 API 호출 로깅
- 민감 작업 이력 추적
- 정기 보안 점검

---

## 10. 참고 자료

### 10.1 UI 모달에 포함된 DB 코드
HTML 파일 내 각 모달에 포함된 SQL 예시 코드를 실제 구현에 참고할 것

### 10.2 외부 참고
- LangChain Documentation
- Anthropic Claude API Reference
- FAISS Documentation
- FastAPI Documentation

---

## 11. 결론

PromptoRAG UI v1.0 프로토타입은 **변수형 프롬프트 템플릿**, **RAG 기반 근거 문서 검색**, **실행 이력 자산화**라는 핵심 개념을 명확히 시각화하고 있습니다.

본 개발 계획은 이 프로토타입을 실제 운영 시스템으로 구현하기 위한 로드맵을 제시합니다. Phase별 순차적 구현을 통해 안정적인 시스템 구축이 가능하며, 특히 **Phase 3(RAG 시스템)**과 **Phase 4(LLM 연동)**이 시스템의 핵심 가치를 결정하는 중요 단계입니다.

---

**문서 끝**
