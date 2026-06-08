# Design_Admin.md

# weeslee-rag 관리자 페이지 `admin.html` UI 수정 변경안

작성일: 2026-06-05  
대상 파일: `frontend/admin.html`  
대상 시스템: weeslee-rag 문서 중앙화 / RAG / LLM Wiki / Graph JSON 관리 콘솔  
작성 목적: 참조 영상 및 Material Admin Pro 스타일을 기반으로 `admin.html`을 운영자 중심의 관리자 대시보드로 개선하기 위한 UI/UX 설계 및 작업 지시서

---

## 1. 문서 작성 배경

현재 weeslee-rag 시스템의 관리자 페이지는 단순 관리 화면이 아니라 회사 문서를 RAG화하고, FAISS VectorDB, Graph JSON, LLM Wiki, Dataset Builder 작업 상태를 추적하는 핵심 운영 콘솔이다.

따라서 `admin.html` UI 개선의 목표는 단순히 Bootstrap 디자인을 입히는 것이 아니라 다음 운영 흐름을 한 화면에서 이해하고 조작할 수 있게 만드는 것이다.

```text
문서 원본 확인
→ 문서 상태 분류
→ 메타데이터 생성/검수
→ 청킹/임베딩
→ FAISS Collection 생성
→ Graph JSON 생성
→ LLM Wiki 생성
→ 사용자 검색 반영 여부 확인
```
# https://github.com/topics/bootstrap-5-dashboard
1. https://github.com/ColorlibHQ/gentelella
2. https://github.com/puikinsh/Adminator-admin-dashboard
3. https://github.com/themesberg/volt-bootstrap-5-dashboard
4. https://github.com/themeselection/sneat-bootstrap-html-admin-template-free
5. https://github.com/themeselection/materio-bootstrap-html-admin-template-free

참조한 디자인 방향은 다음과 같다.

1. Bootstrap 5 기반 Admin Dashboard 스타일
2. Material Design Admin Dashboard 스타일
3. 반응형 Sidebar + Topbar + Content Card 구조
4. Start Bootstrap Material Admin Pro의 Material Design + Bootstrap 5 조합

---

## 2. 참조 자료 분석 요약

### 2.1 Bootstrap Admin Dashboard Tutorial 방향

참조 영상 1은 Bootstrap 기반의 관리자 대시보드 화면 구성을 다룬다. 핵심은 다음과 같다.

- 좌측 Sidebar를 기준으로 주요 기능 메뉴를 분리한다.
- 상단 Header에는 검색, 알림, 사용자 메뉴를 배치한다.
- 본문에는 통계 카드, 테이블, 차트, 최근 작업 목록을 배치한다.
- Bootstrap Grid를 활용하여 데스크톱/태블릿/모바일 반응형을 구성한다.

weeslee-rag 적용 방향:

- Sidebar는 RAG 운영 메뉴로 구성한다.
- 상단 Header는 전체 문서 검색, Job 상태, 알림을 표시한다.
- 본문 첫 화면은 Dashboard Overview로 구성한다.
- 카드에는 문서 수, 미분류 수, FAISS 인덱스 수, Graph 생성 수, Wiki 생성 수를 표시한다.

---

### 2.2 Material Admin Dashboard Shorts 방향

참조 영상 2는 Material Admin Dashboard 스타일을 보여주는 짧은 영상으로, 핵심은 카드 중심의 시각적 정보 배치이다.

적용 포인트:

- Rounded Card
- Soft Shadow
- 색상으로 상태 구분
- 아이콘 기반 요약 카드
- Dark Mode 대응 가능 구조
- RTL, Vertical Layout 등 확장 가능한 구조

weeslee-rag 적용 방향:

- 각 RAG 처리 단계별 상태를 Material Card로 표시한다.
- 성공/경고/오류/대기 상태를 색상과 Badge로 구분한다.
- 미분류 문서, 실패 Job, 검수 필요 문서는 운영자가 즉시 확인할 수 있게 강조한다.

---

### 2.3 Responsive Admin Dashboard Panel 방향

참조 영상 3은 Bootstrap 5, HTML, CSS, JavaScript 기반 반응형 관리자 패널 방향이다.

적용 포인트:

- 모바일에서는 Sidebar가 접히고 Drawer 형태로 동작한다.
- 카드와 테이블이 화면 크기에 맞게 재배치된다.
- 관리자 기능은 탭보다 명확한 메뉴 구조가 유리하다.
- 화면 상단에서 현재 위치와 작업 상태를 알 수 있어야 한다.

weeslee-rag 적용 방향:

- 기존 탭 구조는 유지하되, 상위 구조는 Sidebar 중심으로 개편한다.
- 모바일/태블릿에서는 Sidebar를 접고 상단 메뉴 버튼으로 열 수 있게 한다.
- 긴 테이블은 `.table-responsive`로 감싼다.
- 단계별 Wizard는 모바일에서도 세로 Stepper로 전환되게 한다.

---

### 2.4 Start Bootstrap Material Admin Pro 방향

Start Bootstrap Material Admin Pro는 Material Design 언어와 Bootstrap 5 프레임워크를 결합한 관리자 UI 템플릿 방향이다.

적용 포인트:

- Material Design 기반 카드와 컴포넌트
- Bootstrap 5의 반응형 레이아웃
- 관리자 페이지에 적합한 Sidebar / Topbar / Dashboard / Tables / Forms 구조
- 재사용 가능한 UI 컴포넌트 중심 설계

weeslee-rag 적용 방향:

- `admin.html` 내부에 반복되는 카드, 배지, 상태 표시, 테이블, 버튼을 컴포넌트화한다.
- CSS 변수 기반으로 색상/간격/그림자/Radius를 통일한다.
- 향후 `admin.css`, `admin.js` 분리 구조로 확장할 수 있게 설계한다.

---

## 3. UI 개선의 핵심 목표

`admin.html`은 다음 5가지 목적을 만족해야 한다.

### 3.1 운영자가 현재 상태를 즉시 파악해야 한다

관리자 첫 화면에서 다음 정보를 바로 볼 수 있어야 한다.

| 항목 | 설명 |
|---|---|
| 전체 문서 수 | 스캔된 원본 문서 전체 수 |
| 미분류 문서 수 | 카테고리/메타데이터가 없는 문서 수 |
| Dataset Builder 대기 수 | RAG 반영 전 처리 대기 문서 수 |
| FAISS Collection 수 | 생성된 벡터 컬렉션 수 |
| Graph JSON 수 | 생성된 그래프 데이터 수 |
| LLM Wiki 수 | 생성된 Wiki 문서 수 |
| 실패 Job 수 | OCR/파싱/임베딩/Graph/Wiki 실패 작업 수 |

---

### 3.2 RAG 처리 흐름이 한눈에 보여야 한다

관리자는 단순히 파일 목록을 보는 것이 아니라 문서가 사용자 검색에 반영되기까지의 상태를 확인해야 한다.

권장 단계:

```text
01. Source Scan
02. Metadata Build
03. Category / Tag Review
04. Chunking
05. Embedding
06. FAISS Build
07. Graph Build
08. LLM Wiki Build
09. Publish to Search
```

각 단계는 다음 상태값을 가져야 한다.

| 상태 | 표시 | 설명 |
|---|---|---|
| 대기 | `Pending` | 아직 처리되지 않음 |
| 진행 | `Running` | 현재 작업 중 |
| 완료 | `Done` | 정상 완료 |
| 검수 필요 | `Review` | 자동 처리 결과를 관리자가 확인해야 함 |
| 실패 | `Failed` | 오류 발생 |
| 제외 | `Excluded` | RAG 대상에서 제외됨 |

---

### 3.3 미분류 문서 문제를 최우선으로 해결해야 한다

현재 관리자 페이지에서 중요한 문제는 “미분류” 발생이다. 미분류는 사용자 검색 품질 저하의 직접 원인이 된다.

따라서 Dashboard 상단에 다음 경고 영역을 둔다.

```text
⚠ 미분류 문서 128건이 있습니다.
Dataset Builder를 실행하기 전에 카테고리/태그/메타데이터 검수가 필요합니다.
[미분류 문서 보기] [AI 메타데이터 추천] [일괄 검수 시작]
```

---

### 3.4 개발자용 API 정보는 숨기지 말고 접이식으로 제공한다

기존 논의에서 API 경로는 DEV 토글로 숨기는 방식보다 접이식으로 보여주는 방향이 적합하다고 정리되었다.

적용 방식:

- 각 기능 카드 하단에 `API Details` 접이식 영역 추가
- 기본은 접힘 상태
- 클릭 시 Endpoint, Method, Payload 예시, Response 예시 표시

예시:

```html
<details class="api-details">
  <summary>API Details</summary>
  <pre>POST /api/admin/rag-source/scan</pre>
</details>
```

---

### 3.5 사용자 검색 반영 여부를 관리자 페이지에서 확인해야 한다

문서가 처리되었더라도 사용자 페이지 `rag-assistant.html` 검색 결과에 반영되지 않으면 운영상 완료가 아니다.

따라서 문서 상태 테이블에는 다음 컬럼을 추가한다.

| 컬럼 | 설명 |
|---|---|
| Source 상태 | 원본 파일 존재 여부 |
| Metadata 상태 | 카테고리/태그/메타데이터 생성 여부 |
| FAISS 상태 | 벡터 인덱스 반영 여부 |
| Graph 상태 | Graph JSON 반영 여부 |
| Wiki 상태 | LLM Wiki 반영 여부 |
| Search 반영 | 사용자 검색 결과 반영 여부 |
| 최종 검수 | 관리자 승인 여부 |

---

## 4. 권장 전체 레이아웃

### 4.1 기본 화면 구조

```text
┌──────────────────────────────────────────────────────────────┐
│ Topbar                                                       │
│ [☰] weeslee-rag Admin   [전체 검색] [Job 상태] [알림] [User] │
├───────────────┬──────────────────────────────────────────────┤
│ Sidebar       │ Main Content                                  │
│               │                                              │
│ Dashboard     │ Page Header                                   │
│ Source Docs   │ KPI Cards                                     │
│ Dataset       │ Alerts                                        │
│ FAISS Index   │ Main Tables / Wizard / Forms                  │
│ Graph JSON    │ API Details                                   │
│ LLM Wiki      │                                              │
│ Jobs          │                                              │
│ Settings      │                                              │
└───────────────┴──────────────────────────────────────────────┘
```

---

### 4.2 Sidebar 메뉴 구조

```text
Dashboard
├─ Overview
├─ Alerts

Source Documents
├─ 전체 문서
├─ 미분류 문서
├─ 제외 문서
├─ 신규 문서

Dataset Builder
├─ Scan
├─ Metadata Build
├─ Category Review
├─ Tag Review
├─ Build Wizard

FAISS Index
├─ Collections
├─ Index Jobs
├─ Chunk Preview

Graph JSON
├─ Graph Build
├─ Graph Preview
├─ Entity / Relation

LLM Wiki
├─ Wiki Build
├─ Wiki Preview
├─ Wiki Publish

Jobs
├─ Running Jobs
├─ Failed Jobs
├─ Job History

Settings
├─ Source Path
├─ Category Rules
├─ Tag Rules
├─ API Settings
```

---

## 5. Dashboard Overview 화면 설계

### 5.1 상단 KPI 카드

상단에는 6개 카드를 배치한다.

```text
[전체 문서] [미분류] [Dataset 대기] [FAISS] [Graph] [Wiki]
```

각 카드 구성:

- 아이콘
- 제목
- 숫자
- 전일/최근 스캔 대비 증감
- 상태 색상
- 상세보기 버튼

예시 HTML 구조:

```html
<div class="admin-kpi-card status-warning">
  <div class="kpi-icon">📂</div>
  <div class="kpi-body">
    <span class="kpi-label">미분류 문서</span>
    <strong class="kpi-value">128</strong>
    <small class="kpi-desc">검수 필요</small>
  </div>
</div>
```

---

### 5.2 RAG Pipeline Status 영역

Dashboard 중앙에는 RAG 처리 파이프라인 상태를 Stepper 형태로 보여준다.

```text
Source Scan → Metadata → Chunking → Embedding → FAISS → Graph → Wiki → Publish
```

각 단계는 완료율과 실패 건수를 함께 표시한다.

예시:

```text
Metadata Build
완료 82% / 실패 14건 / 검수 필요 31건
```

---

### 5.3 최근 작업 Job 목록

최근 실행된 작업을 테이블로 표시한다.

| 시간 | 작업명 | 대상 | 상태 | 소요시간 | 실행자 | 로그 |
|---|---|---|---|---|---|---|
| 2026-06-05 09:20 | Metadata Build | 01. RFP | Done | 3m 12s | admin | 보기 |
| 2026-06-05 09:30 | FAISS Build | 제안서 | Failed | 1m 41s | admin | 보기 |

---

## 6. Source Documents 화면 설계

### 6.1 문서 목록 테이블

문서 목록은 운영자가 가장 많이 사용하는 영역이다. 단순 파일 목록이 아니라 처리 상태를 함께 보여야 한다.

필수 컬럼:

| 컬럼 | 설명 |
|---|---|
| 선택 | 체크박스 |
| 파일명 | 원본 파일명 |
| 문서 대분류 | RFP / 제안서 / 산출물 / 참고자료 |
| 세부분류 | 전략, 기술, PMO, 감리 등 |
| 확장자 | pdf, hwp, docx, pptx 등 |
| 크기 | 파일 크기 |
| 수정일 | 원본 수정일 |
| Metadata | 생성 상태 |
| FAISS | 반영 상태 |
| Graph | 반영 상태 |
| Wiki | 반영 상태 |
| Search | 사용자 검색 반영 여부 |
| Action | 보기 / 수정 / 제외 / 재처리 |

---

### 6.2 필터 영역

테이블 상단에는 다음 필터를 배치한다.

```text
[문서 대분류] [세부분류] [상태] [확장자] [검색어] [기간] [검색] [초기화]
```

상태 필터:

- 전체
- 미분류
- 검수 필요
- 처리 완료
- 실패
- 제외
- 사용자 검색 미반영

---

### 6.3 문서 상세 패널

문서 클릭 시 오른쪽 Drawer 또는 Modal로 상세 정보를 표시한다.

표시 항목:

- 원본 경로
- 상대 경로
- 문서 대분류
- 세부분류
- 자동 추천 태그
- 관리자 확정 태그
- 청크 수
- FAISS Collection
- Graph Node/Edge 수
- Wiki 생성 여부
- 사용자 페이지 검색 테스트 버튼

---

## 7. Dataset Builder 화면 설계

Dataset Builder는 관리자 페이지의 핵심 기능이다.

### 7.1 Build Wizard 구조

```text
Step 1. Source Scan
Step 2. Metadata Build
Step 3. Category / Tag Review
Step 4. Chunk & Embedding
Step 5. FAISS Collection Build
Step 6. Graph JSON Build
Step 7. LLM Wiki Build
Step 8. Publish / Search Test
```

각 Step은 다음 구조를 가진다.

```text
[Step 제목]
설명 문구
입력값 / 옵션
실행 버튼
진행률
결과 로그
API Details
```

---

### 7.2 Source Scan Step

기능:

- 원본 폴더 선택
- 스캔 범위 선택
- 제외 규칙 적용
- 신규/변경/삭제 문서 감지

UI 항목:

```text
Source Root Path: /data/weeslee/weeslee-rag/source_documents
[폴더 선택]
[스캔 실행]
[변경 문서만 스캔]
[제외 규칙 적용]
```

---

### 7.3 Metadata Build Step

기능:

- 파일 경로와 파일명 기반 자동 분류
- 문서 대분류/세부분류 추천
- 태그/메타태그 추천
- Confidence Score 표시

UI 항목:

```text
[AI 메타데이터 추천 실행]
[Confidence 80% 이상 자동 승인]
[낮은 Confidence 문서만 검수]
```

---

### 7.4 Category / Tag Review Step

기능:

- AI 추천 결과를 관리자가 승인/수정
- 미분류 문서 정리
- 태그 일괄 적용

필수 버튼:

```text
[선택 승인]
[선택 수정]
[일괄 태그 적용]
[제외 처리]
[재추천]
```

---

### 7.5 FAISS Build Step

기능:

- Collection 선택
- Chunk Size 설정
- Overlap 설정
- Embedding Model 선택
- 벡터 생성 실행

UI 항목:

```text
Collection Name: proposal_strategy
Chunk Size: 800
Overlap: 120
Embedding Model: nomic-embed-text
[FAISS Build 실행]
```

---

### 7.6 Graph JSON Build Step

기능:

- 문서에서 Entity / Relation 추출
- Graph JSON 생성
- Graph Preview 표시

UI 항목:

```text
[Graph Build 실행]
[Entity 추출 보기]
[Relation 추출 보기]
[Graph JSON 다운로드]
```

---

### 7.7 LLM Wiki Build Step

기능:

- 문서 요약
- 업무 지식화
- Wiki Markdown / JSON 생성
- 사용자 검색 보조 지식으로 반영

UI 항목:

```text
[LLM Wiki 생성]
[Wiki Preview]
[Markdown 다운로드]
[사용자 검색 반영]
```

---

## 8. FAISS Index 화면 설계

FAISS 화면에서는 단순히 인덱스 생성 여부만 보여주면 부족하다. 운영자는 어떤 Collection에 어떤 문서가 들어갔는지 확인해야 한다.

### 8.1 Collection 목록

| Collection | 문서 수 | 청크 수 | 임베딩 모델 | 생성일 | 최근 업데이트 | 상태 | Action |
|---|---:|---:|---|---|---|---|---|
| rfp | 320 | 12,480 | nomic-embed-text | 2026-06-01 | 2026-06-05 | Active | 보기 |
| proposal_strategy | 210 | 8,940 | nomic-embed-text | 2026-06-02 | 2026-06-04 | Active | 보기 |

---

### 8.2 Chunk Preview

문서별 청크를 미리 볼 수 있어야 한다.

표시 항목:

- Chunk ID
- 문서명
- 페이지/섹션
- 텍스트 일부
- Vector 반영 여부
- 검색 테스트 버튼

---

## 9. Graph JSON 화면 설계

Graph 기능은 관리자에게 추상적으로 보이면 안 된다. 어떤 문서에서 어떤 Entity와 Relation이 나왔는지 확인해야 한다.

### 9.1 Graph Summary 카드

```text
[Graph JSON 파일 수]
[Entity 수]
[Relation 수]
[검수 필요 Relation]
[최근 생성일]
```

---

### 9.2 Graph Preview

초기 버전에서는 복잡한 그래프 시각화보다 다음 구성이 실용적이다.

```text
왼쪽: Entity 목록
중앙: Relation 목록
오른쪽: 원문 근거 Preview
```

---

## 10. LLM Wiki 화면 설계

LLM Wiki는 단순 요약이 아니라 회사 내부 업무 지식을 구조화하는 영역이다.

### 10.1 Wiki 목록

| Wiki 제목 | 원본 문서 | 카테고리 | 태그 | 생성일 | 검색 반영 | Action |
|---|---|---|---|---|---|---|
| K-water 플랫폼 구축 전략 | 제안서.pdf | 제안서/전략 | K-water, 플랫폼 | 2026-06-05 | 반영 | 보기 |

---

### 10.2 Wiki Preview

Wiki 상세 화면 구성:

```text
제목
요약
핵심 키워드
관련 문서
관련 Entity
관련 Graph
원문 근거
검색 반영 상태
```

---

## 11. Jobs 화면 설계

비동기 작업이 많은 RAG 시스템에서는 Jobs 화면이 매우 중요하다.

### 11.1 Job 상태 카드

```text
[Running] [Pending] [Done] [Failed] [Review]
```

---

### 11.2 Job History 테이블

| Job ID | 작업 | 대상 | 상태 | 시작 | 종료 | 소요시간 | 로그 | 재실행 |
|---|---|---|---|---|---|---|---|
| job_260605_001 | FAISS Build | proposal | Failed | 09:00 | 09:03 | 3m | 보기 | 재실행 |

---

## 12. Settings 화면 설계

Settings는 개발자와 운영자가 함께 사용하는 영역이다.

### 12.1 Source Path 설정

```text
Source Root: /data/weeslee/weeslee-rag/source_documents
Output Root: /data/weeslee/weeslee-rag/data
FAISS Path: /data/weeslee/weeslee-rag/data/faiss
Graph Path: /data/weeslee/weeslee-rag/data/graph
Wiki Path: /data/weeslee/weeslee-rag/data/wiki
```

---

### 12.2 제외 규칙 설정

기존 운영 기준을 반영한다.

기본 제외 대상:

- 임시 `.json` 산출물
- `[제안실주]` 폴더
- `old` 폴더
- 대량 이미지 폴더
- 백업 파일
- 중복 파일

---

## 13. 권장 디자인 시스템

### 13.1 색상 토큰

```css
:root {
  --admin-bg: #f5f7fb;
  --admin-surface: #ffffff;
  --admin-primary: #2563eb;
  --admin-primary-soft: #e0ecff;
  --admin-success: #16a34a;
  --admin-warning: #f59e0b;
  --admin-danger: #dc2626;
  --admin-muted: #64748b;
  --admin-border: #e5e7eb;
  --admin-text: #0f172a;
  --admin-radius: 16px;
  --admin-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
}
```

---

### 13.2 상태 Badge

```html
<span class="status-badge status-done">Done</span>
<span class="status-badge status-running">Running</span>
<span class="status-badge status-warning">Review</span>
<span class="status-badge status-failed">Failed</span>
<span class="status-badge status-muted">Pending</span>
```

---

### 13.3 카드 스타일

```css
.admin-card {
  background: var(--admin-surface);
  border: 1px solid var(--admin-border);
  border-radius: var(--admin-radius);
  box-shadow: var(--admin-shadow);
  padding: 20px;
}
```

---

## 14. `admin.html` 수정 작업 지시서

### 14.1 1단계: 기존 파일 백업

```bash
cp frontend/admin.html frontend/admin.backup.20260605.html
```

---

### 14.2 2단계: 레이아웃 Shell 추가

기존 `admin.html`의 기능 코드는 유지하고, 최상위 구조를 다음처럼 감싼다.

```html
<body>
  <div class="admin-shell">
    <aside class="admin-sidebar">
      <!-- 좌측 메뉴 -->
    </aside>

    <div class="admin-main">
      <header class="admin-topbar">
        <!-- 상단 검색/알림/사용자 메뉴 -->
      </header>

      <main class="admin-content">
        <!-- 기존 탭/카드/테이블 영역 -->
      </main>
    </div>
  </div>
</body>
```

---

### 14.3 3단계: Dashboard Overview 추가

새 섹션 ID:

```html
<section id="admin-dashboard-overview" class="admin-page-section active">
</section>
```

포함 요소:

- KPI 카드 6개
- 미분류 경고 Alert
- RAG Pipeline Stepper
- 최근 Job 테이블

---

### 14.4 4단계: 기존 탭 구조 정리

기존 탭은 제거하지 않는다. 다만 Sidebar 메뉴와 연결되도록 정리한다.

예시:

```javascript
function showAdminSection(sectionId) {
  document.querySelectorAll('.admin-page-section').forEach(section => {
    section.classList.remove('active');
  });

  const target = document.getElementById(sectionId);
  if (target) {
    target.classList.add('active');
  }
}
```

---

### 14.5 5단계: Dataset Builder Wizard 추가

새 섹션 ID:

```html
<section id="dataset-builder-wizard" class="admin-page-section">
</section>
```

Step 목록:

```javascript
const datasetSteps = [
  'Source Scan',
  'Metadata Build',
  'Category Review',
  'Chunking',
  'Embedding',
  'FAISS Build',
  'Graph Build',
  'LLM Wiki Build',
  'Publish Test'
];
```

---

### 14.6 6단계: API Details 접이식 적용

각 기능 실행 영역 하단에 API 정보를 추가한다.

```html
<details class="api-details">
  <summary>API Details</summary>
  <div class="api-detail-body">
    <p><strong>Method:</strong> POST</p>
    <p><strong>Endpoint:</strong> /api/admin/rag-source/metadata/build</p>
    <pre>{ "source_root": "source_documents", "mode": "changed_only" }</pre>
  </div>
</details>
```

---

### 14.7 7단계: 모바일 반응형 적용

```css
@media (max-width: 992px) {
  .admin-sidebar {
    position: fixed;
    left: -280px;
    top: 0;
    width: 280px;
    height: 100vh;
    z-index: 1000;
    transition: left 0.25s ease;
  }

  .admin-sidebar.is-open {
    left: 0;
  }

  .admin-main {
    margin-left: 0;
  }

  .admin-kpi-grid {
    grid-template-columns: 1fr;
  }
}
```

---

## 15. 우선순위

### P0. 즉시 수정

1. Dashboard Overview 추가
2. 미분류 문서 경고 카드 추가
3. Source Documents 상태 테이블 개선
4. Dataset Builder Wizard 추가
5. API Details 접이식 추가

### P1. 1차 고도화

1. FAISS Collection 관리 화면 개선
2. Graph JSON Preview 개선
3. LLM Wiki Preview 개선
4. Job History / Failed Job 재실행 버튼 추가
5. 사용자 검색 반영 여부 표시

### P2. 2차 고도화

1. Dark Mode
2. Drag & Drop 문서 업로드
3. Graph 시각화 고도화
4. 관리자 권한 분리
5. 알림 기능
6. 작업 완료 후 사용자 페이지 자동 반영 확인

---

## 16. 최종 결론

`admin.html`은 일반적인 관리자 페이지가 아니라 weeslee-rag 시스템의 문서 중앙화 운영 본부 역할을 해야 한다.

따라서 이번 UI 수정의 핵심은 다음이다.

```text
예쁜 Dashboard가 아니라
문서가 RAG 검색에 반영되는 전체 과정을 관리자가 추적하고 통제하는 운영 콘솔로 개선한다.
```

최종 방향:

1. Material Admin Pro 스타일의 Sidebar + Topbar + Card 구조 적용
2. Dashboard Overview에서 전체 상태 즉시 파악
3. 미분류 문서와 실패 Job을 최상단에서 경고
4. Dataset Builder를 단계형 Wizard로 구성
5. FAISS / Graph / LLM Wiki 상태를 문서 단위로 추적
6. API Details는 숨기지 않고 접이식으로 제공
7. 사용자 검색 반영 여부까지 관리자 화면에서 확인

이 방향으로 수정하면 `admin.html`은 단순 설정 페이지가 아니라 회사 문서를 RAG/LLM Wiki/Graph 데이터셋으로 전환하는 운영형 AI Knowledge Console이 된다.

---

## 17. 참조 URL

1. Bootstrap Admin Dashboard Tutorial  
   https://youtu.be/iEasMXu72No?si=y1uLmwfp4r7GdKRz

2. Material Admin Dashboard Shorts  
   https://youtube.com/shorts/yxkYaO02ILI?si=S1CYv65J0Zl0c62i

3. Full Responsive Admin Dashboard Panel  
   https://youtu.be/iNnLHlpdrao?si=u3b5QBwo4GMuYBbn

4. Start Bootstrap Material Admin Pro  
   https://startbootstrap.com/previews/material-admin-pro

