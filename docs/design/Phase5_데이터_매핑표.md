# Phase 5. 데이터 매핑표

## 1. 문서 개요

이 문서는 사용자 화면 데이터와 관리자 생성 데이터의 연결 관계를 정리한다.
rag-assistant.html에서 필요한 데이터가 admin.html의 어떤 파이프라인에서 생성되어 어디에 저장되는지를 명확히 한다.

## 2. 데이터 매핑 총괄표

### 2.1 사용자 화면 → 데이터 출처 매핑

| 사용자 화면 영역 | 필요 데이터 | 생성 파이프라인 | 저장 위치 | API |
| --- | --- | --- | --- | --- |
| 질문 분석 | intent, keywords, filters | Prompt Analyzer | 실시간 생성 | POST /api/rag-assistant/analyze-prompt |
| RAG 결과 | chunk_text, score, metadata | RAG Build | FAISS + chunks.jsonl | POST /api/search/rag |
| RAG Agent 결과 | strategy, tools_used, reason | RAG Agent | 실시간 생성 | POST /api/search/rag-agent |
| Graph RAG 결과 | graph_path, connected_entities | Graph RAG Build | nodes.jsonl, edges.jsonl | POST /api/search/graph-rag |
| LLM Wiki 결과 | title, summary, related_docs | Wiki Generator | data/wiki/*.md | POST /api/search/llm-wiki |
| 통합 추천 | merged_score, sources | Frontend Merger | 실시간 계산 | - |
| 문서 상세 (원문) | html_content, markdown | Text Extractor | extracted_text/{id}/ | GET /api/documents/{id}/html |
| 문서 상세 (요약) | summary_text, key_points | Summary Generator | summaries/{id}/ | GET /api/documents/{id}/summary |
| 문서 상세 (메타) | organization, tags, year | Metadata Generator | documents.jsonl | GET /api/documents/{id} |
| Grounded Answer | answer, citations | LLM Service | 실시간 생성 | POST /api/rag-assistant/generate-answer |
| 다운로드 | original, txt, md, docx | Document Store | source_documents | GET /api/documents/{id}/download |

### 2.2 관리자 파이프라인 → 저장 위치 매핑

| 파이프라인 단계 | 입력 | 출력 | 저장 위치 |
| --- | --- | --- | --- |
| 폴더 스캔 | 네트워크 경로 | 파일 목록 | documents.jsonl |
| 전처리 | 원문 파일 | 해시, 기본 메타 | documents.jsonl, metadata.db |
| 메타데이터 추출 | 파일명, 본문 | 자동 메타데이터 | document_metadata_suggestions |
| 텍스트 추출 | 원문 파일 | raw_text, cleaned_text | extracted_text/{id}/ |
| HTML/MD 변환 | cleaned_text | document.html, document.md | extracted_text/{id}/ |
| 청킹 | cleaned_text | chunks | chunks.jsonl |
| 임베딩 | chunks | embedding vectors | FAISS Index |
| FAISS 빌드 | embeddings | Vector Index | indexes/faiss/ |
| Graph RAG 빌드 | 메타데이터 | nodes, edges | graph/ |
| Wiki 생성 | 문서 그룹 | wiki markdown | wiki/ |
| 요약 생성 | cleaned_text | summary | summaries/{id}/ |

## 3. 데이터 필드 상세 매핑

### 3.1 RAG 검색 결과 매핑

| UI 필드 | 데이터 출처 | 저장 파일 | 생성 시점 |
| --- | --- | --- | --- |
| document_id | 스캔 시 생성 | documents.jsonl | 폴더 스캔 |
| file_name | 스캔 시 추출 | documents.jsonl | 폴더 스캔 |
| score | FAISS 검색 | 실시간 계산 | 검색 시 |
| page | 청킹 시 기록 | chunks.jsonl | 청킹 |
| chunk_text | 청킹 시 저장 | chunks.jsonl | 청킹 |
| highlight | 검색 시 생성 | 실시간 생성 | 검색 시 |
| metadata.document_type | 메타 추출/확정 | documents.jsonl | 전처리/확정 |
| metadata.organization | 메타 추출/확정 | documents.jsonl | 전처리/확정 |
| metadata.technology_tags | 메타 추출/확정 | document_tags | 전처리/확정 |

### 3.2 Graph RAG 검색 결과 매핑

| UI 필드 | 데이터 출처 | 저장 파일 | 생성 시점 |
| --- | --- | --- | --- |
| graph_score | 그래프 탐색 | 실시간 계산 | 검색 시 |
| path_length | 그래프 탐색 | 실시간 계산 | 검색 시 |
| connected_entities | nodes.jsonl | graph/nodes.jsonl | Graph RAG 빌드 |
| graph_paths | edges.jsonl | graph/edges.jsonl | Graph RAG 빌드 |
| nodes[].type | 그래프 빌드 | graph/nodes.jsonl | Graph RAG 빌드 |
| nodes[].label | 그래프 빌드 | graph/nodes.jsonl | Graph RAG 빌드 |
| edges[].type | 그래프 빌드 | graph/edges.jsonl | Graph RAG 빌드 |

### 3.3 LLM Wiki 검색 결과 매핑

| UI 필드 | 데이터 출처 | 저장 파일 | 생성 시점 |
| --- | --- | --- | --- |
| wiki_id | Wiki 생성 시 | wiki_manifest.json | Wiki 생성 |
| wiki_type | Wiki 생성 시 | wiki_manifest.json | Wiki 생성 |
| title | Wiki 생성 시 | wiki/{type}/{id}.md | Wiki 생성 |
| summary | Wiki 생성 시 | wiki/{type}/{id}.md | Wiki 생성 |
| content | Wiki 생성 시 | wiki/{type}/{id}.md | Wiki 생성 |
| related_documents | Wiki 생성 시 | wiki/{type}/{id}.md | Wiki 생성 |

### 3.4 문서 상세 매핑

| UI 탭 | UI 필드 | 데이터 출처 | 저장 파일 |
| --- | --- | --- | --- |
| 원문 | html_content | HTML 변환 | extracted_text/{id}/document.html |
| 원문 | markdown_content | MD 변환 | extracted_text/{id}/document.md |
| 원문 | pages | 텍스트 추출 | extracted_text/{id}/pages.json |
| 요약 | summary_text | 요약 생성 | summaries/{id}/summary.md |
| 요약 | key_points | 요약 생성 | summaries/{id}/summary.md |
| 메타데이터 | document_type | 메타 확정 | documents.jsonl |
| 메타데이터 | organization | 메타 확정 | documents.jsonl |
| 메타데이터 | technology_tags | 태그 확정 | document_tags (DB) |

### 3.5 Grounded Answer 매핑

| UI 필드 | 데이터 출처 | 참조 데이터 | 생성 시점 |
| --- | --- | --- | --- |
| answer | LLM 생성 | selected_docs의 chunks | 답변 생성 요청 시 |
| citations[].chunk_text | chunks.jsonl | chunks.jsonl | 답변 생성 시 참조 |
| citations[].page | chunks.jsonl | chunks.jsonl | 답변 생성 시 참조 |
| citations[].document_id | 사용자 선택 | documents.jsonl | 답변 생성 요청 시 |

## 4. 데이터 생성 순서 의존성

### 4.1 의존성 다이어그램

```
[원문 파일]
     │
     ▼
[폴더 스캔] ──────────────────────────────────────────────────┐
     │                                                       │
     ▼                                                       │
[전처리] ─────────────────────────────────────────────────┐  │
     │                                                    │  │
     ├──▶ [메타데이터 추출] ──▶ document_metadata_suggestions
     │                                                    │  │
     ▼                                                    │  │
[텍스트 추출] ──▶ raw_text.txt, cleaned_text.txt          │  │
     │                                                    │  │
     ├──▶ [HTML/MD 변환] ──▶ document.html, document.md   │  │
     │                                                    │  │
     ▼                                                    │  │
[청킹] ──▶ chunks.jsonl                                   │  │
     │                                                    │  │
     ▼                                                    │  │
[임베딩] ──▶ embedding vectors                            │  │
     │                                                    │  │
     ▼                                                    │  │
[FAISS 빌드] ──▶ {collection}.index ──────────────────────┼──┼──▶ [RAG 검색]
     │                                                    │  │
     │                                                    ▼  │
     ├──────────────────────────────────────────▶ [Graph RAG 빌드]
     │                                                    │  │
     │                                                    ▼  │
     │                                            nodes.jsonl
     │                                            edges.jsonl
     │                                                    │  │
     │                                                    ▼  │
     │                                           [Graph RAG 검색]
     │                                                       │
     └──────────────────────────────────────────────────────▶│
                                                             │
[메타데이터 확정] ◀─────────────────────────────────────────┘
     │
     ▼
[Wiki 생성] ──▶ wiki/*.md ──▶ [Wiki 검색]
     │
     ▼
[요약 생성] ──▶ summaries/{id}/summary.md
```

### 4.2 단계별 의존성 표

| 단계 | 선행 조건 | 필수 입력 | 출력 |
| --- | --- | --- | --- |
| 폴더 스캔 | 저장소 접근 가능 | 폴더 경로 | documents.jsonl |
| 전처리 | 스캔 완료 | 원문 파일 | 해시, 기본 메타 |
| 메타데이터 추출 | 전처리 완료 | 파일명, 본문 일부 | suggestions |
| 텍스트 추출 | 전처리 완료 | 원문 파일 | raw_text, cleaned_text |
| HTML/MD 변환 | 텍스트 추출 완료 | cleaned_text | html, md |
| 청킹 | 텍스트 추출 완료 | cleaned_text | chunks.jsonl |
| 임베딩 | 청킹 완료 | chunks | vectors |
| FAISS 빌드 | 임베딩 완료 | vectors | FAISS index |
| Graph RAG 빌드 | 메타데이터 확정 | documents, metadata | nodes, edges |
| Wiki 생성 | Graph RAG 빌드 완료 | documents by group | wiki markdown |
| 요약 생성 | 텍스트 추출 완료 | cleaned_text | summary |

## 5. 실시간 vs 사전 생성 데이터

### 5.1 사전 생성 데이터 (Batch)

| 데이터 | 생성 시점 | 갱신 조건 |
| --- | --- | --- |
| documents.jsonl | 폴더 스캔 시 | 새 파일 추가/수정 시 |
| chunks.jsonl | 청킹 시 | 문서 변경 시 |
| FAISS index | 빌드 시 | 청크 변경 시 |
| nodes.jsonl | Graph 빌드 시 | 메타데이터 변경 시 |
| edges.jsonl | Graph 빌드 시 | 관계 변경 시 |
| wiki/*.md | Wiki 생성 시 | 주기적 재생성 |
| summaries/*.md | 요약 생성 시 | 문서 변경 시 |
| document.html | 변환 시 | 원문 변경 시 |
| document.md | 변환 시 | 원문 변경 시 |

### 5.2 실시간 생성 데이터 (On-demand)

| 데이터 | 생성 시점 | 캐싱 여부 |
| --- | --- | --- |
| intent, keywords | 검색 요청 시 | 세션 내 캐시 |
| RAG score | 검색 시 | 캐시 안함 |
| highlight | 검색 시 | 캐시 안함 |
| agent_strategy | Agent 검색 시 | 캐시 안함 |
| graph_path | Graph 검색 시 | 캐시 안함 |
| merged_score | 결과 병합 시 | 캐시 안함 |
| answer | 답변 생성 시 | 캐시 안함 |
| citations | 답변 생성 시 | 캐시 안함 |

## 6. 데이터 갱신 트리거

### 6.1 문서 추가/수정 시

```
새 파일 감지
    │
    ├──▶ documents.jsonl 업데이트
    ├──▶ 텍스트 재추출
    ├──▶ 청크 재생성
    ├──▶ 임베딩 재생성
    ├──▶ FAISS 인덱스 재빌드
    ├──▶ Graph 노드/엣지 업데이트
    └──▶ 관련 Wiki 재생성 (해당 그룹)
```

### 6.2 메타데이터 확정 시

```
메타데이터 확정
    │
    ├──▶ documents.jsonl 업데이트
    ├──▶ document_tags 업데이트
    ├──▶ Graph 노드 속성 업데이트
    └──▶ 관련 Wiki 재생성 플래그
```

### 6.3 전체 재빌드 시

```
전체 재빌드 요청
    │
    ├──▶ 모든 청크 재생성
    ├──▶ 모든 임베딩 재생성
    ├──▶ FAISS 인덱스 전체 재빌드
    ├──▶ Graph 전체 재빌드
    └──▶ 모든 Wiki 재생성
```

## 7. 산출물 체크리스트

- [x] 사용자 화면 → 데이터 출처 매핑표
- [x] 관리자 파이프라인 → 저장 위치 매핑표
- [x] 데이터 필드 상세 매핑 (RAG, Graph, Wiki, 문서상세, Answer)
- [x] 데이터 생성 순서 의존성 다이어그램
- [x] 실시간 vs 사전 생성 데이터 구분
- [x] 데이터 갱신 트리거 정의

---

작성일: 2026-05-21
작성자: Claude
다음 단계: Phase 6. 데이터 생성 파이프라인 설계
