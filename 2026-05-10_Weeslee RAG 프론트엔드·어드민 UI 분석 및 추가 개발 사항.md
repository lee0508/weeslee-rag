# 2026-05-10_Weeslee RAG 프론트엔드·어드민 UI 분석 및 추가 개발 사항.md

---

## 1. 분석 대상 및 목적

| 항목 | 내용 |
|------|------|
| **프론트엔드** | https://server.weeslee.co.kr/weeslee-rag/frontend/rag-assistant.html |
| **어드민** | https://server.weeslee.co.kr/weeslee-rag/frontend/admin.html |
| **백엔드 API** | http://192.168.0.207:8080/api (내부 IP 고정) |
| **프론트엔드 서버** | Nginx Port 9284 |
| **분석일** | 2026-05-10 |

---

## 2. 시스템 전체 구조 개요

```
[사용자 브라우저]
    │
    ├── rag-assistant.html (Nginx :9284)  ←→  FastAPI :8080/api
    │        RAG Assistant 탭                   /health/all
    │        Knowledge Search 탭                /rag/query (POST)
    │        Answer Review 탭                   /rag/reviews (POST)
    │
    └── admin.html (Nginx :9284)          ←→  FastAPI :8080/api
             FAISS Index 탭                     /admin/faiss/status
             Graph View 탭                      /admin/faiss/indexes
                                                /admin/faiss/activate
                                                /admin/faiss/jobs
                                                /admin/faiss/category-status
                                                /admin/faiss/benchmark
                                                /health/ollama
                                                /graph/summary
                                                /graph/projects
                                                /graph/project/:label
                                                /graph/build
                                                /wiki/match
                                                /wiki/projects/:slug
```

---

## 3. rag-assistant.html UI 현황 분석

### 3-1. 레이아웃 구조

```
┌─ 헤더 (Prompto RAG / WEESLEE RAG WORKSPACE) ──────────────────────┐
│  [RAG Assistant] [Knowledge Search] [Answer Review]    Live ●     │
├─ 좌측 사이드바 ──┬─ 중앙 메인 패널 ──────┬─ 우측 결과 패널 ──────┤
│ Runtime Target   │ RAG Query Workspace  │ Answer Panel          │
│ - API: healthy   │ - Query Input        │ - Draft Answer 탭     │
│ - VectorDB 상태  │ - Run RAG 버튼       │ - Result 탭           │
│ - Ollama: healthy│ - Refresh Health 버튼│                       │
│ Search Mode      │                      │                       │
│ Top K            │                      │                       │
│ Top Docs         │                      │                       │
│ Max Chunks/Doc   │                      │                       │
│ Category         │                      │                       │
│ Answer Mode      │                      │                       │
│ Model            │                      │                       │
│ Rec. Documents   │                      │                       │
└──────────────────┴──────────────────────┴───────────────────────┘
```

### 3-2. 탭별 기능 현황

#### ① RAG Assistant 탭 (메인)
| UI 요소 | 현재 상태 | 문제점 |
|---------|----------|--------|
| Search Mode 드롭다운 | General RAG / Bid Project Search / RFP Analysis | 카테고리명이 영문 혼용 — 한글화 미완성 |
| Category 드롭다운 | All/RFP/Proposal/Kickoff/Final Report/Presentation | 좌측 사이드바와 중앙 패널 간 카테고리 **이중 관리** 문제 |
| Answer Mode | Ollama(Generate) / Search Only | Claude API 등 외부 모델 옵션 없음 |
| Model 입력 | 텍스트 입력 (gemma4:latest 기본값) | Ollama에 설치된 모델 목록 **자동 불러오기 없음** — 수동 입력 필요 |
| Query 입력창 | textarea | 영문 placeholder — 한글 안내 없음 |
| Run RAG 버튼 | 정상 | 로딩 스피너/진행 상태 표시 없음 |
| Refresh Health 버튼 | 정상 | 헬스 새로고침 결과 피드백 없음 |
| Recommended Documents | 좌측 하단 섹션 존재 | **렌더링 조건 불명확**, 항상 비어 있음 |
| Answer Panel - Draft Answer | 우측 패널 | 결과 없을 때 "No answer yet." 만 표시 |
| Answer Panel - Result | JSON 원본 | 개발자용 — 일반 사용자에게 불필요하게 노출 |

#### ② Knowledge Search 탭
| UI 요소 | 현재 상태 | 문제점 |
|---------|----------|--------|
| 검색 입력창 | "사업명, 키워드, 업무 영역 입력..." | 검색 결과 레이아웃 없음 — 결과 카드 렌더링 영역 부재 |
| 검색 모드 | General RAG / Bid Project / RFP Analysis | RAG Assistant 탭과 동일 옵션이나 **UI 언어 불일치** (한글/영문 혼재) |
| 카테고리 | 전체/RFP/Proposal 등 | RAG Assistant 탭과 **동기화 안됨** — 탭 전환 시 설정 초기화 |
| TOP K | 20 (고정 기본값) | |
| TOP DOCS | 8 (고정 기본값) | |
| 결과 표시 영역 | 검색 전 빈 상태 메시지만 | **페이지네이션 없음** — 결과 많을 때 UX 저하 |
| 문서 카드 | 검색 후 렌더링 (추정) | 파일 열기/다운로드 링크가 내부 IP 경로 의존 |

#### ③ Answer Review 탭
| UI 요소 | 현재 상태 | 문제점 |
|---------|----------|--------|
| 세션 기록 | 좌측 목록 | RAG Assistant에서 쿼리 실행 후에만 채워짐 — **탭 간 상태 연계** 필수 |
| 세션 카운트 | "0개" 표시 | 브라우저 새로고침 시 **세션 기록 초기화** — 영속성 없음 |
| 내용 영역 | "좌측 목록에서 항목 선택" 안내만 | 실제 답변 비교, 평점, 수정 기능 없음 |

### 3-3. 공통 문제점

| 구분 | 문제 내용 |
|------|----------|
| **API 주소 하드코딩** | Backend API가 `http://192.168.0.207:8080/api` 내부 IP로 고정되어 있음. 외부 접속 시 CORS 오류 또는 연결 불가 발생 |
| **인증/권한 없음** | 모든 엔드포인트에 인증 없이 접근 가능 — Admin 기능 포함 누구나 접근 가능 |
| **에러 처리 미흡** | API 오류 시 콘솔 출력만 있고 사용자 대면 에러 메시지 없음 |
| **로딩 상태 없음** | Run RAG 실행 중 버튼 비활성화 및 로딩 UI 없음 |
| **모바일 미지원** | 3단 고정 레이아웃 — 모바일·태블릿 반응형 없음 |
| **언어 혼재** | 한글/영문이 섞여 있음 (Query, Run RAG, Draft Answer 등 영문 잔존) |
| **세션 영속성 없음** | 브라우저 새로고침 시 모든 상태(쿼리 기록, 검색 설정) 초기화 |

---

## 4. admin.html UI 현황 분석

### 4-1. 레이아웃 구조

```
┌─ 헤더 (FAISS Index Management Console) ─────────────────────────┐
│  [FAISS Index 탭] [Graph View 탭]              ● 서버 연결됨    │
├─ 좌측 사이드바 ──────┬─ 우측 메인 콘텐츠 영역 ───────────────────┤
│ [FAISS Index 탭]     │ [FAISS Index 탭]                         │
│ - 활성 인덱스 정보   │ - 사용 가능한 인덱스 목록 (카드)          │
│ - Ollama 상태        │ - 잡 이력                                 │
│ - 카테고리 인덱스    │ - 검색 품질 벤치마크                      │
│ - 파이프라인 실행    │                                           │
│ [Graph View 탭]      │ [Graph View 탭]                          │
│ - 프로젝트 목록      │ - 그래프 캔버스 (Cytoscape.js)            │
│ - Build 버튼         │ - Fit / Reset 버튼                        │
│                      │ - 노드 상세 패널 (우측)                   │
└──────────────────────┴───────────────────────────────────────────┘
```

### 4-2. FAISS Index 탭 현황

#### 좌측 사이드바
| UI 요소 | 현재 상태 | 문제점 |
|---------|----------|--------|
| 활성 인덱스 표시 | 스냅샷명, 크기, 청크 수, 활성화 시각 표시 | 활성 인덱스 **변경 이력** 없음 |
| Ollama 상태 | running / 모델 목록 | 모델별 상태(로딩 중/오류) 구분 없음 |
| 카테고리 인덱스 | rfp/proposal/kickoff 등 크기 표시 | 카테고리별 **청크 수** 표시 없음 (크기만 표시) |
| 파이프라인 실행 | 스냅샷 이름 직접 입력 후 시작 | 입력 형식 강제(YYYY-MM-DD 등) 없음 — 오타 유발 |
| 파이프라인 로그 | (스크롤 없음) | 실행 중 로그 스트리밍 있으나 로그 **저장/복사 기능** 없음 |

#### 우측 메인 콘텐츠
| UI 요소 | 현재 상태 | 문제점 |
|---------|----------|--------|
| 인덱스 카드 목록 | 스냅샷명, 크기, 청크 수, 상태, Activate 버튼 | **인덱스 삭제 기능 없음** — 쌓이면 정리 불가 |
| Activate 버튼 | 비활성 인덱스에만 표시 | Activate 전 확인 다이얼로그 없음 — 실수 가능 |
| 인덱스 상세 정보 | 없음 | 카드 클릭 시 상세(문서 목록, 카테고리 분포) 없음 |
| 잡 이력 | "실행된 잡 없음" | 잡 **실행 시간, 소요 시간, 성공/실패** 표시 없음 |
| 잡 이력 | 새로고침 수동 | **자동 폴링** 없음 — 파이프라인 완료 감지 불가 |
| 검색 품질 벤치마크 | Run Benchmark 버튼만 | 벤치마크 **결과 기록 누적** 없음, 과거 결과 비교 불가 |

### 4-3. Graph View 탭 현황

| UI 요소 | 현재 상태 | 문제점 |
|---------|----------|--------|
| 프로젝트 목록 | 91개 프로젝트, 275개 문서, 734개 관계 표시 | **검색/필터 기능 없음** — 91개 목록 스크롤만 가능 |
| Build 버튼 | 그래프 데이터 빌드 | 빌드 소요 시간 길 수 있으나 **진행률 표시 없음** |
| 그래프 캔버스 | Cytoscape.js 렌더링 | 그래프 **너무 작게 렌더링** — 노드 텍스트 겹침 |
| 그래프 캔버스 | 프로젝트 클릭 후 노드 표시 | 노드 클릭 전까지 캔버스 **비어 있음** — 초기 안내 없음 |
| Fit / Reset 버튼 | 뷰 조정 | 줌 인/아웃 단축키 없음 |
| 노드 상세 패널 | PROJECT 타입 클릭 시 표시 | **DOCUMENT, CHUNK 타입 노드** 상세 패널 미완성 |
| 노드 상세 | RAG 검색 → / Wiki 보기 버튼 | Wiki 보기 버튼이 어드민 내부에서 열리지 않고 외부로 이동 |
| 색상 범례 | 없음 | 노드 색상(주황/파랑/초록/빨강)의 의미 설명 없음 |

---

## 5. 두 페이지 간 연동 문제 분석

### 5-1. API 엔드포인트 비교

| 기능 영역 | rag-assistant.html | admin.html | 문제 |
|----------|-------------------|------------|------|
| 헬스 체크 | `/health/all` | `/health/ollama` | **엔드포인트 불일치** — 동일 상태를 다른 API로 조회 |
| FAISS 인덱스 정보 | 사이드바에 VectorDB 이름만 표시 | `/admin/faiss/status`, `/admin/faiss/indexes` | rag-assistant는 **활성 인덱스 변경을 감지 못함** |
| 카테고리 | 드롭다운 하드코딩 | `/admin/faiss/category-status` | rag-assistant의 카테고리 목록이 **admin 실제 데이터와 동기화 안됨** |
| Ollama 모델 | 수동 텍스트 입력 | `/health/ollama` 로 모델 목록 조회 | rag-assistant가 admin의 **모델 목록 API를 재사용하지 않음** |
| 그래프/Wiki | 없음 | `/graph/*`, `/wiki/*` | rag-assistant에서 **프로젝트 그래프 탐색 불가** |

### 5-2. 상태 공유 문제

| 문제 | 설명 | 영향 |
|------|------|------|
| **API BASE URL 불일치 가능성** | 두 페이지 모두 `detectApiBase()` 함수로 런타임에 API 주소 결정 | 내부 IP(`192.168.0.207`)로 고정되어 외부 도메인 접근 시 CORS 오류 |
| **인덱스 Activate 반영 지연** | admin에서 인덱스 교체 후 rag-assistant에 **즉시 반영 안됨** | RAG 결과가 구버전 인덱스 기반일 수 있음 |
| **카테고리 동기화 없음** | admin에서 새 카테고리 추가해도 rag-assistant 드롭다운은 **코드에 하드코딩** | 새 카테고리 추가 시 양쪽 코드 수동 수정 필요 |
| **공유 상태 저장소 없음** | 두 페이지가 각자 독립적 상태 관리 | 한 페이지의 변경이 다른 페이지에 자동 전파 안됨 |
| **Admin 링크 없음** | rag-assistant에 admin 페이지 링크 없음 | 운영자가 두 URL을 별도로 북마크해야 함 |

### 5-3. CORS 및 네트워크 문제

```
현재 구조:
  외부 사용자 → Nginx(server.weeslee.co.kr:9284) → [정적 HTML 로드]
  브라우저 JS → http://192.168.0.207:8080/api  [직접 호출!]
                       ↑
           내부 IP — 외부에서 접근 불가!
           CORS 미설정 시 브라우저 차단
```

**핵심 문제**: 프론트엔드 JS가 내부 IP(`192.168.0.207:8080`)를 직접 호출하므로
외부 네트워크에서는 API 호출이 전부 실패함.

---

## 6. 추가 개발 필요 사항

### 6-1. 🔴 긴급 (서비스 안정성)

| 우선순위 | 항목 | 설명 |
|---------|------|------|
| P0 | **API 프록시 설정** | Nginx에서 `/api/` 경로를 내부 FastAPI로 프록시 처리 — 브라우저가 내부 IP 직접 호출하지 않도록 수정 |
| P0 | **CORS 헤더 설정** | FastAPI에 CORS 미들웨어 추가 또는 Nginx에서 CORS 헤더 삽입 |
| P0 | **인증/접근 제어** | Admin 페이지 최소한 HTTP Basic Auth 또는 토큰 기반 인증 적용 |
| P1 | **API 주소 환경변수화** | `config.js` 또는 `.env` 기반으로 API URL 외부 주입 가능하도록 수정 |

### 6-2. 🟠 높음 (핵심 기능 개선)

| 항목 | 현재 | 개선 방향 |
|------|------|----------|
| **Ollama 모델 드롭다운** | 수동 텍스트 입력 | `/health/ollama` API로 설치된 모델 목록 자동 조회 후 드롭다운 렌더링 |
| **카테고리 동적 로드** | 하드코딩 | `/admin/faiss/category-status` API 기반 동적 카테고리 목록 로드 (양쪽 페이지 공통 적용) |
| **인덱스 상태 자동 반영** | 수동 새로고침 | admin에서 Activate 시 rag-assistant의 VectorDB 상태도 자동 갱신 (WebSocket 또는 SSE 적용) |
| **로딩 상태 UI** | 없음 | Run RAG 실행 중 버튼 비활성화 + 스피너 + 진행 메시지 표시 |
| **에러 메시지 UI** | 없음 | API 오류 시 토스트 알림 또는 인라인 에러 박스 표시 |
| **파이프라인 날짜 자동 입력** | 수동 입력 | 스냅샷 이름 입력창에 오늘 날짜 자동 완성 + 형식 검증 |
| **잡 이력 자동 폴링** | 수동 새로고침 | 파이프라인 실행 중 3~5초 간격 자동 폴링으로 진행 상태 실시간 표시 |

### 6-3. 🟡 중간 (UX 개선)

| 항목 | 설명 |
|------|------|
| **인덱스 삭제 기능** | 사용하지 않는 구버전 인덱스 삭제 버튼 + 확인 다이얼로그 추가 |
| **Activate 확인 다이얼로그** | "현재 활성 인덱스를 변경합니다. 계속하시겠습니까?" 모달 추가 |
| **그래프 노드 색상 범례** | Graph View에 노드 타입별 색상 설명 범례 박스 추가 |
| **프로젝트 목록 검색 필터** | Graph View 프로젝트 목록에 검색창 추가 (91개 목록 탐색 편의) |
| **벤치마크 결과 기록** | 벤치마크 실행 결과를 로컬스토리지에 누적 저장, 이전 결과와 비교 |
| **Admin ↔ RAG 링크** | 두 페이지 헤더에 서로의 링크 버튼 추가 |
| **로그 복사/저장** | 파이프라인 로그 복사 버튼 및 텍스트 파일 다운로드 기능 |
| **세션 기록 영속화** | Answer Review 탭의 세션 기록을 `localStorage`에 저장 — 새로고침 후에도 유지 |

### 6-4. 🟢 낮음 (완성도 향상)

| 항목 | 설명 |
|------|------|
| **UI 언어 통일** | 한글/영문 혼재 요소 전체 한글화 또는 i18n 적용 |
| **반응형 레이아웃** | 모바일/태블릿 환경 지원 (CSS Grid/Flexbox 재설계) |
| **그래프 확대/축소 단축키** | +/- 키 또는 마우스 휠로 Graph View 줌 조절 |
| **카테고리 인덱스 청크 수 표시** | admin 사이드바 카테고리 인덱스에 크기와 함께 청크 수 추가 표시 |
| **Answer Review 평점 기능** | 답변에 별점/좋아요 평가 기능 추가 — RAG 품질 모니터링 기반 |
| **다크/라이트 테마 전환** | 현재 다크 테마 고정 — 사용자 테마 선택 옵션 |
| **인덱스 카드 상세 펼치기** | 카드 클릭 시 포함 문서 목록, 카테고리 분포 차트 표시 |

---

## 7. 우선순위별 개발 로드맵

### Phase 1 — 기반 안정화 (1~2주)
1. Nginx API 프록시 설정 (`location /api/` → FastAPI)
2. FastAPI CORS 미들웨어 추가
3. Admin 페이지 인증 적용
4. API URL 환경변수화 (`config.js` 분리)

### Phase 2 — 핵심 연동 개선 (2~3주)
5. Ollama 모델 목록 동적 로드 (양쪽 공통)
6. 카테고리 목록 API 기반 동적 로드
7. 로딩/에러 UI 컴포넌트 공통화
8. 잡 이력 자동 폴링 구현

### Phase 3 — UX 개선 (3~4주)
9. 인덱스 삭제 + Activate 확인 다이얼로그
10. 세션 기록 localStorage 영속화
11. 그래프 범례 + 프로젝트 검색 필터
12. Admin ↔ RAG 페이지 간 링크 추가

### Phase 4 — 완성도 (4~6주)
13. UI 언어 통일
14. 반응형 레이아웃
15. 벤치마크 결과 누적 기록
16. Answer Review 평점 기능

---

## 8. Nginx API 프록시 설정 예시 (즉시 적용 권장)

```nginx
# /etc/nginx/sites-available/weeslee-rag
server {
    listen 9284;
    server_name server.weeslee.co.kr;

    root /path/to/weeslee-rag/frontend;
    index rag-assistant.html;

    # 정적 파일
    location / {
        try_files $uri $uri/ =404;
    }

    # API 프록시 추가 — 브라우저가 내부 IP 직접 호출하지 않도록
    location /api/ {
        proxy_pass http://127.0.0.1:8080/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # CORS 헤더
        add_header Access-Control-Allow-Origin "*" always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Content-Type, Authorization" always;

        if ($request_method = OPTIONS) {
            return 204;
        }
    }
}
```

그리고 프론트엔드 JS의 API_BASE를 내부 IP 대신 상대 경로로 변경:
```javascript
// 변경 전
const API_BASE = 'http://192.168.0.207:8080/api';

// 변경 후
const API_BASE = '/api';  // Nginx가 프록시 처리
```

---

## 9. 카테고리 동적 로드 예시 코드

```javascript
// 현재: 하드코딩
// <option value="rfp">RFP</option>
// <option value="proposal">Proposal</option>

// 개선: API에서 동적 로드
async function loadCategories() {
    const res = await fetch(`${API_BASE}/admin/faiss/category-status`);
    const data = await res.json();
    const categories = Object.keys(data.categories || {});

    const selects = document.querySelectorAll('select#category, select#ks-category');
    selects.forEach(sel => {
        sel.innerHTML = '<option value="">전체</option>';
        categories.forEach(cat => {
            const opt = document.createElement('option');
            opt.value = cat;
            opt.textContent = cat.replace('_', ' ').toUpperCase();
            sel.appendChild(opt);
        });
    });
}
// 페이지 로드 시 호출
loadCategories();
```

---

## 10. 요약

| 구분 | 발견된 문제 수 | 긴급 | 높음 | 중간 | 낮음 |
|------|-------------|------|------|------|------|
| rag-assistant.html | 12개 | 2 | 4 | 4 | 2 |
| admin.html | 14개 | 2 | 4 | 5 | 3 |
| 연동 문제 | 7개 | 3 | 3 | 1 | 0 |
| **합계** | **33개** | **7** | **11** | **10** | **5** |

**가장 시급한 조치**: Nginx API 프록시 설정 + API URL 환경변수화
이 두 가지만 해결해도 외부 접속 문제와 유지보수성이 크게 개선됨.
