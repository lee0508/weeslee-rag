# 2026-05-29 Codex rag-assistant.html 수정 코드 분석

## 1. 작성 목적

이 문서는 `frontend/rag-assistant.html`의 현재 수정 상태를 기준으로 사용자 RAG 화면의 코드 구조, 기능 의도, 잔여 리스크, 다음 작업 우선순위를 정리한 Codex 분석 문서다.

어제 작성된 Codex 문서 형식은 다음 문서를 기준으로 맞췄다.

- `docs/2026-05-28_Codex_LLM_RAG_온톨로지_적용제안.md`.
- `docs/2026-05-28_Codex_Figma와이어프레임_구현매핑.md`.

## 2. 확인 범위

확인한 파일은 다음이다.

| 구분 | 파일 | 확인 내용 |
|---|---|---|
| 사용자 화면 | `frontend/rag-assistant.html` | 문서 검색, 답변 패널, 문서 상세, 미리보기, Graph 근거, 선택 문서 답변 UI |
| 작업 문서 | `docs/2026-05-28_Codex_LLM_RAG_온톨로지_적용제안.md` | 어제 Codex 문서 제목과 섹션 구성 |
| 작업 문서 | `docs/2026-05-28_Codex_Figma와이어프레임_구현매핑.md` | 확인 범위, 현재 구현 구조, 매핑, 리스크 형식 |

## 3. Git 기준 변경 상태

`frontend/rag-assistant.html`은 현재 워킹트리에서 수정 파일로 표시된다.

다만 다음 명령 기준으로 실제 내용 변경은 확인되지 않았다.

```bash
git diff --ignore-space-at-eol -- frontend/rag-assistant.html
```

명령 출력은 비어 있었다.

따라서 현재 Git diff의 대부분은 줄바꿈 형식 또는 줄 끝 공백 차이로 보는 것이 맞다.

문서에서는 기능 변경을 오늘 새로 작성된 코드로 단정하지 않고, 현재 파일에 포함된 구현 구조를 분석 대상으로 삼는다.

## 4. 현재 구현 구조

현재 `rag-assistant.html`은 단순 검색 화면이 아니라 사용자용 RAG 검증 워크스페이스에 가깝다.

| 영역 | 주요 함수와 요소 | 역할 |
|---|---|---|
| RAG 실행 | `runQuery`, `renderResults`, `renderAnswerPanel` | 질의 실행, 검색 결과 표시, 답변 패널 렌더링 |
| 문서 카드 | `renderDocumentCards`, `_renderedDocuments` | 검색 결과 문서 목록, 점수, 메타데이터, 근거 미리보기 표시 |
| 문서 선택 | `_selectedDocIndices`, `toggleDocSelection`, `runQueryWithSelectedDocs` | 답변 생성에 사용할 문서를 사용자가 직접 선택하는 UI |
| 문서 상세 | `openDocDetail`, `switchDocDetailTab`, `openDocDetailByIndex` | 원문, 요약, 청크, 근거, Graph 탭을 한 패널에서 전환 |
| 파일 미리보기 | `openFilePreview`, `loadPreviewFormat`, `printPreview`, `closePreview` | HTML, 요약, Markdown, TXT, PDF 원문 보기와 출력 |
| Graph 근거 | `formatGraphRelations`, 카드 내 `graphSummary` | 관계 데이터를 한국어 근거 문구로 변환 |
| 지식 검색 | `runKnowledgeSearch`, `renderKsCard` | 답변 생성 없이 유사 문서 검색과 파일 미리보기 제공 |
| 답변 검토 | `pushHistory`, `renderReviewList`, `selectReviewItem`, `rateItem` | 질의 이력 저장, 답변 복사, 별점 평가 |
| 제안서 초안 | `runProposalDraft`, `renderProposalResult` | 프로젝트명과 섹션 기반 제안서 초안 생성 |

## 5. 기능 분석

### 5.1 문서 카드 개선

문서 카드는 `document_id`, `source_id`, `project_name`, `document_group`, `proposal_section`, `deliverable_section` 같은 표준 메타데이터를 표시한다.

현재 구조는 백엔드 RAG 응답 표준화 작업과 맞물려 있다.

카드에는 다음 확인 흐름이 들어 있다.

- 검색 점수 확인.
- 프로젝트명과 파일명 확인.
- 원본 경로 확인.
- 검색 청크 또는 근거 스니펫 미리보기.
- 원문, 요약, 청크, 근거, Graph 보기 버튼.
- 답변 생성 대상 문서 선택 체크박스.

이 구조는 사용자가 “왜 이 문서가 검색됐는지”를 카드 수준에서 빠르게 확인하게 만든다.

### 5.2 문서 상세 패널

`openDocDetail()`은 검색 결과 문서 하나를 상세 패널로 열고, 보기 모드를 `original`, `summary`, `chunks`, `evidence`, `graph`로 분리한다.

이 설계의 장점은 근거 확인 흐름이 명확하다는 점이다.

- `original`은 파일 열기 버튼으로 원문 미리보기에 연결된다.
- `summary`는 기존 summary 값이 없으면 `/api/documents/{document_id}/summary`를 호출한다.
- `chunks`는 검색에 사용된 chunk를 최대 10개까지 표시한다.
- `evidence`는 `evidence_snippets`를 표시한다.
- `graph`는 `graph_context` 또는 `relations`를 한국어 관계 설명으로 변환한다.

이 구조는 RAG 답변 검증에 필요한 원문, 요약, chunk, Graph 근거를 한 곳에 묶는 방향이다.

### 5.3 파일 미리보기 모달

파일 미리보기는 `document_id`가 있는 경우와 없는 경우를 나눠 처리한다.

`document_id`가 있으면 `/api/documents/{document_id}` 상세 API를 먼저 조회하고, 사용 가능한 형식에 따라 탭을 만든다.

지원 흐름은 다음이다.

| 형식 | 호출 endpoint |
|---|---|
| HTML | `/api/documents/{document_id}/html` |
| 요약 | `/api/documents/{document_id}/summary` |
| Markdown | `/api/documents/{document_id}/markdown` |
| TXT | `/api/documents/{document_id}/text` |
| 다운로드 | `/api/documents/{document_id}/download?format=...` |

`document_id`가 없고 PDF 경로만 있으면 `/api/files/view?path=...` iframe으로 원문을 표시한다.

문서 상세의 `파일 열기` 버튼과 Knowledge Search의 문서 제목 버튼이 같은 미리보기 흐름을 사용하므로 사용자 경험은 비교적 일관적이다.

### 5.4 Graph 근거 표현

`formatGraphRelations()`는 Graph 관계를 다음 형태로 사용자에게 보여준다.

- edge 기반 관계.
- 프로젝트 체인 기반 관계.
- entity 기반 관계.
- 기타 JSON 상세 보기.

관계 타입은 `RELATED_TO`, `REFERENCES`, `SIMILAR_TO`, `SAME_PROJECT`, `SAME_ORGANIZATION` 같은 값을 한국어 문구로 변환한다.

이 방향은 전체 Knowledge Graph 탐색보다 검색 결과 검증에 초점을 둔다.

특히 사용자 화면에서는 Graph 탭이 “전체 그래프 보기”가 아니라 “이번 검색 결과 문서의 관계 근거 확인”으로 쓰이는 편이 더 적합하다.

### 5.5 선택 문서 기반 답변 UI

문서 선택 UI는 `_selectedDocIndices` Set으로 선택 상태를 관리한다.

선택된 문서 수는 `selectedDocsIndicator`와 `runSelectedBtn`으로 표시된다.

다만 `runQueryWithSelectedDocs()`는 현재 실제 백엔드 호출이 아니라 Mock 안내에 가깝다.

코드 안에도 실제 API 호출은 백엔드 연동 후 구현한다는 주석이 있다.

따라서 이 기능은 사용자 화면의 기대값을 만들지만, 아직 운영 기능으로 완료됐다고 보면 안 된다.

## 6. 현재 구현의 좋은 점

현재 구조의 장점은 다음이다.

| 항목 | 판단 |
|---|---|
| 근거 확인 흐름 | 문서 카드, 상세 패널, 미리보기 모달이 이어져 사용자가 근거를 따라갈 수 있다. |
| 응답 필드 확장 대응 | 문자열 snippet과 객체 snippet을 모두 처리하는 `snippetText()`가 있어 백엔드 응답 전환에 비교적 안전하다. |
| Graph 설명 | 원시 관계 데이터를 바로 보여주지 않고 한국어 설명으로 변환하려는 방향이 맞다. |
| 파일 형식 처리 | HTML, 요약, Markdown, TXT, PDF 경로를 한 미리보기 모달에서 처리한다. |
| 답변 검토 | 질의 이력과 별점이 있어 RAG 품질 검토 화면으로 확장할 수 있다. |

## 7. 리스크

현재 구조에서 주의할 점은 다음이다.

| 리스크 | 내용 | 권장 대응 |
|---|---|---|
| 실제 diff 혼선 | Git 기준 내용 변경은 없고 줄바꿈 차이만 보인다. | 기능 변경 커밋 전 줄바꿈 정규화 여부를 먼저 결정한다. |
| 선택 문서 답변 미완성 | `runQueryWithSelectedDocs()`가 실제 답변 API를 호출하지 않는다. | 백엔드 API 계약을 정한 뒤 버튼을 활성 운영 기능으로 전환한다. |
| DOM ID 불일치 가능성 | 선택 문서 답변은 `resultTabContent-rag`를 찾지만 현재 결과 패널은 `ragAnswerSection` 중심이다. | 실제 DOM 존재 여부를 브라우저에서 확인하고 렌더링 대상 ID를 통일한다. |
| inline handler 증가 | 단일 HTML 파일 안에 inline `onclick`과 대형 script가 많다. | 당장 분리보다 회귀 테스트 확보 후 단계적으로 모듈화한다. |
| Graph 데이터 형태 다양성 | `graph_context`, `relations`, chain, edge, entity 형태가 혼재한다. | 백엔드 응답 스키마를 표준화하고 fallback만 프론트에 둔다. |
| 보안 처리 | HTML preview는 `srcdoc`에 escape된 문자열을 넣지만 원본 HTML 렌더링 정책은 더 확인이 필요하다. | 신뢰 경계와 sanitize 정책을 백엔드와 프론트에서 명확히 한다. |
| 줄바꿈 변경량 | CRLF/LF 변환만으로 대규모 diff가 발생할 수 있다. | `.gitattributes` 또는 에디터 설정으로 HTML 줄바꿈 정책을 고정한다. |

## 8. 다음 작업 우선순위

| 우선순위 | 작업 | 완료 기준 |
|---|---|---|
| P0 | `rag-assistant.html` 줄바꿈 정책 결정 | `git diff --ignore-space-at-eol`이 아닌 일반 diff에서도 불필요한 대량 변경이 사라진다. |
| P1 | 선택 문서 답변 UI의 렌더링 대상 ID 확인 | 선택 문서 버튼 클릭 시 현재 결과 패널에 상태가 정확히 표시된다. |
| P2 | 선택 문서 답변 API 계약 정의 | `selected_document_ids`를 받는 백엔드 endpoint와 응답 형식이 문서화된다. |
| P3 | 문서 상세 탭별 API 실패 상태 정리 | summary, html, markdown, text 실패 시 사용자가 원인을 구분할 수 있다. |
| P4 | Graph 관계 응답 스키마 정규화 | 프론트가 edge, chain, entity를 임시 추론하지 않고 표준 필드로 렌더링한다. |
| P5 | 미리보기 보안 정책 확인 | HTML preview와 파일 view endpoint의 신뢰 범위가 정리된다. |

## 9. 결론

현재 `frontend/rag-assistant.html`은 사용자 RAG 화면에서 문서 근거를 검증하는 기능이 꽤 많이 들어간 상태다.

핵심 방향은 맞다.

사용자는 검색 결과 카드에서 후보 문서를 훑고, 상세 패널에서 원문, 요약, 청크, 근거, Graph 관계를 확인한 뒤, 필요하면 답변 검토 이력으로 품질을 남길 수 있다.

다만 오늘 Git 기준으로는 실제 코드 내용 변경이 아니라 줄바꿈 차이만 확인됐다.

따라서 다음 단계는 기능을 더 추가하기보다, 줄바꿈 diff를 정리하고 선택 문서 기반 답변의 실제 API 연결 여부를 먼저 확정하는 것이다.

## 10. 검증 기록

이번 문서 작성 전 확인한 명령은 다음이다.

```bash
rg --files | rg '(^|/)2026-05-28_Codex_'
git diff --ignore-space-at-eol -- frontend/rag-assistant.html --stat
git diff --ignore-space-at-eol -- frontend/rag-assistant.html
rg -n "function renderResults|function openDocDetailByIndex|function runQuery|selectedDocs|_activeSnapshot" frontend/rag-assistant.html
sed -n '3880,4520p' frontend/rag-assistant.html
sed -n '4520,5135p' frontend/rag-assistant.html
```

검증 결과는 다음이다.

- 어제 Codex 문서는 `docs/2026-05-28_Codex_LLM_RAG_온톨로지_적용제안.md`, `docs/2026-05-28_Codex_Figma와이어프레임_구현매핑.md`로 확인했다.
- `frontend/rag-assistant.html`은 줄 끝 공백을 무시하면 실제 diff가 없다.
- 문서 카드, 상세 패널, 미리보기 모달, Graph 근거, 선택 문서 UI는 현재 파일 내부에서 확인했다.
