# RAG Assistant UI/UX 개선 (Phase 4)

**문서 작성일**: 2026-05-30
**버전**: 1.0
**작성자**: Claude
**테스트 URL**: https://server.weeslee.co.kr/weeslee-rag/frontend/rag-assistant.html

---

## 1. 개요

### 1.1 작업 배경

`docs/2026-05-29_Lee_rag-assistant.html_기능개선안.md` 문서에서 제시된 UI/UX 개선 항목 중 우선순위가 높은 작업을 Phase 4로 실행했다.

### 1.2 완료된 작업 목록

| 우선순위 | 항목 | 상태 |
|----------|------|------|
| **높음** | 좌측 사이드바 서버 상태 축소 + 설정 그룹화 | ✅ 완료 |
| **높음** | 검색 입력창 확장 + 실행 피드백 개선 | ✅ 완료 |
| **높음** | RAG 결과 마크다운 렌더링 | ✅ 완료 |
| 중간 | 사이드바 접기/펼치기 | ✅ 완료 |
| 중간 | Citation 번호 ↔ 근거 문서 앵커 연결 | ✅ 완료 |

---

## 2. 상세 변경 사항

### 2.1 서버 상태 축소형 표시

#### Before
- API, VectorDB, Ollama 상태가 큰 카드 3개로 사이드바 상단에 배치
- 실제 검색 설정보다 상태 모니터링 UI가 더 많은 공간 차지

#### After
- **Dot Indicator 방식**: API/Vector/LLM 상태를 작은 점(●)으로 한 줄에 표시
- **클릭하면 상세 펼침**: 필요 시 상세 정보 확인 가능
- **색상 코드**: 녹색(정상), 노랑(경고), 빨강(오류)

```html
<!-- 축소형 상태 표시 -->
<div class="sidebar-status-compact" onclick="toggleStatusDetail()">
  <div class="status-item">
    <span class="status-dot ok"></span>
    <span class="status-label">API</span>
  </div>
  <div class="status-item">
    <span class="status-dot ok"></span>
    <span class="status-label">Vector</span>
  </div>
  <div class="status-item">
    <span class="status-dot ok"></span>
    <span class="status-label">LLM</span>
  </div>
  <span class="status-expand-icon">▼</span>
</div>
```

### 2.2 검색 설정 그룹화

#### Before
- 검색 모드, 카테고리, 답변 모드가 서버 상태 아래 단순 나열

#### After
- **"🔍 기본 검색 설정" 섹션**으로 시각적 그룹화
- 섹션 헤더에 아이콘과 구분선 추가

```css
.settings-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--gray-400);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255,255,255,.08);
}
```

### 2.3 검색 입력창 확장 + 실행 피드백

#### 입력창 확장
- **min-height**: 80px → 120px
- **font-size**: 14px → 15px
- 긴 쿼리 작성 시 가독성 향상

#### 실행 피드백 배너
검색 실행 시 상태를 입력창 상단에 배너로 표시.

| 상태 | 배경 | 아이콘 | 메시지 예시 |
|------|------|--------|-------------|
| loading | shimmer 애니메이션 | 🔍 | "문서 검색 중..." |
| success | 연녹색 | ✅ | "5개 문서를 찾았습니다. (2.3초)" |
| error | 연빨강 | ❌ | "검색 실패: 서버 연결 오류" |

```javascript
function showSearchFeedback(type, message) {
  const feedback = document.getElementById('searchFeedback');
  feedback.className = 'search-feedback show ' + type;
  // 성공 시 소요 시간 표시
  if (type === 'success' && _searchStartTime) {
    const elapsed = ((Date.now() - _searchStartTime) / 1000).toFixed(1);
    document.getElementById('feedbackTime').textContent = `${elapsed}초`;
  }
  document.getElementById('feedbackText').textContent = message;
}
```

### 2.4 RAG 결과 마크다운 렌더링

#### Before
- LLM 답변이 `escapeHtml()`로 처리되어 raw 텍스트로 표시
- 마크다운 마크업(#, **, ```, - 등)이 그대로 보임

#### After
- **간단한 마크다운 렌더러** 구현
- 지원 문법: 헤더(#), 굵게(**), 기울임(*), 코드블록(```), 인라인 코드(`), 목록(- / 1.), 인용(>), 수평선(---)
- Citation 링크([1], [2])도 클릭 가능한 앵커로 변환

```javascript
function renderMarkdown(text) {
  let html = escapeHtml(text);

  // 코드 블록
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="md-code-block"><code>$2</code></pre>');
  // 헤더
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>');
  // 굵게/기울임
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  // Citation 링크
  html = html.replace(/\[(\d+)\]/g,
    '<a href="#citation-$1" class="md-citation" onclick="scrollToCitation($1); return false;">[$1]</a>');

  return `<div class="md-content">${html}</div>`;
}
```

#### 스타일링 예시

```css
.md-content .md-h2 {
  font-size: 18px;
  font-weight: 700;
  color: var(--navy);
  margin: 16px 0 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--gray-200);
}

.md-content .md-code-block {
  background: var(--gray-800);
  color: #e2e8f0;
  padding: 12px 16px;
  border-radius: 6px;
  font-family: 'Consolas', 'Monaco', monospace;
}

.md-content .md-blockquote {
  border-left: 3px solid var(--amber);
  background: var(--amber-l);
  padding: 8px 12px;
  font-style: italic;
}
```

### 2.5 사이드바 접기/펼치기

#### 기능
- 사이드바 우측에 **토글 버튼(◀)** 추가
- 클릭 시 사이드바 접힘 → 중앙 작업 공간 넓어짐
- **상태 저장**: localStorage에 저장하여 새로고침 후에도 유지

```javascript
function toggleSidebar() {
  const sidebar = document.getElementById('leftSidebar');
  sidebar.classList.toggle('collapsed');
  localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
}

function restoreSidebarState() {
  const collapsed = localStorage.getItem('sidebarCollapsed') === 'true';
  if (collapsed) {
    document.getElementById('leftSidebar')?.classList.add('collapsed');
  }
}
```

```css
.sidebar.collapsed {
  width: 0;
  margin-left: calc(var(--sidebar) * -1);
  overflow: hidden;
}

.sidebar-toggle {
  position: absolute;
  top: 50%;
  right: -14px;
  width: 28px;
  height: 48px;
  background: var(--navy);
  border-radius: 0 8px 8px 0;
}
```

### 2.6 Citation 앵커 연결

#### 기능
- 답변 내 **[1], [2] 등 Citation 번호**를 클릭하면 해당 근거 문서로 스크롤
- 해당 문서 카드에 **하이라이트 애니메이션** 적용 (3초 후 해제)

#### 구현

1. **근거 문서에 ID 부여**
```html
<div class="answer-evidence-item" id="citation-1" data-citation="1">
  <span class="citation-badge">[1]</span>
  <div class="answer-evidence-name">프로젝트명</div>
  ...
</div>
```

2. **스크롤 및 하이라이트 함수**
```javascript
function scrollToCitation(citationNum) {
  const target = document.getElementById(`citation-${citationNum}`);
  if (!target) return;

  // 모든 하이라이트 제거
  document.querySelectorAll('.answer-evidence-item.highlight').forEach(el => {
    el.classList.remove('highlight');
  });

  // 해당 항목 하이라이트
  target.classList.add('highlight');
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });

  // 3초 후 하이라이트 제거
  setTimeout(() => target.classList.remove('highlight'), 3000);
}
```

3. **하이라이트 스타일**
```css
.answer-evidence-item.highlight {
  border-color: var(--amber);
  background: var(--amber-l);
  animation: citationPulse .5s ease;
}

@keyframes citationPulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.01); }
}
```

---

## 3. 커밋 정보

| 항목 | 내용 |
|------|------|
| **커밋 해시** | `a607a08` |
| **커밋 메시지** | feat: RAG Assistant UI/UX 개선 (Phase 4) |
| **변경 파일** | `frontend/rag-assistant.html` |
| **변경 규모** | +504 lines, -47 lines |

---

## 4. 배포 정보

| 항목 | 내용 |
|------|------|
| **배포 방법** | SCP (포트 2222) |
| **배포 시간** | 2026-05-30 |
| **배포 서버** | 218.148.21.12 |
| **배포 경로** | `/home/weeslee/weeslee-rag/frontend/rag-assistant.html` |
| **테스트 URL** | https://server.weeslee.co.kr/weeslee-rag/frontend/rag-assistant.html |

---

## 5. 테스트 체크리스트

| 기능 | 테스트 방법 | 예상 결과 |
|------|-------------|-----------|
| 서버 상태 축소 | 페이지 로드 | API/Vector/LLM dot 표시 |
| 서버 상태 펼침 | dot 영역 클릭 | 상세 카드 펼침 |
| 검색 피드백 | 검색 실행 | 로딩 배너 → 성공/실패 배너 |
| 마크다운 렌더링 | Ollama 답변 생성 | 헤더, 목록, 코드블록 스타일 적용 |
| 사이드바 토글 | ◀ 버튼 클릭 | 사이드바 접힘/펼침 |
| 사이드바 상태 유지 | 페이지 새로고침 | 이전 상태 유지 |
| Citation 앵커 | 답변 내 [1] 클릭 | 해당 문서로 스크롤 + 하이라이트 |

---

## 6. 남은 작업 (Phase 5 예정)

| 우선순위 | 항목 | 설명 |
|----------|------|------|
| 중간 | 세션 기록 중복 그룹화 | 동일 검색어 기록 묶기, 반복 횟수 표시 |
| 중간 | 세션 기록 날짜별 구분 | 오늘/어제/이전 그룹 헤더 |
| 낮음 | 제안서 초안 스텝 위저드 | 단계별 진행 UI |
| 낮음 | 그래프 패널 기본 영역 확장 | 최소 높이 400px |

---

## 7. 관련 문서

- `docs/2026-05-29_Lee_rag-assistant.html_기능개선안.md` - 전체 개선안 목록
- `logs/2026-05-29_rag_assistant_file_preview_stabilization.md` - 파일 미리보기 안정화 로그
- `logs/2026-05-29_Phase3_사이드바_고도화_작업로그.md` - Phase 3 작업 로그

---

**End of Document**
