# Phase 6. 데이터 생성 파이프라인 설계서

## 1. 문서 개요

이 문서는 admin.html에서 실행할 데이터 생성 파이프라인의 전체 흐름, 각 단계별 입출력, 실패 처리 정책을 정의한다.

## 2. 파이프라인 전체 흐름

### 2.1 단계 순서도

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. Storage Check                                                   │
│     └ 원문 저장소 연결 확인                                          │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2. Folder Scan                                                     │
│     └ 지정 폴더 스캔, 파일 목록 추출                                  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  3. Preprocess                                                      │
│     └ 파일 해시, 중복 체크, 기본 메타데이터                           │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  4. Metadata Extraction                                             │
│     └ 규칙 기반 + LLM 메타데이터 자동 추출                           │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  5. Text Extraction                                                 │
│     └ PDF/HWP/DOCX → raw_text, cleaned_text, HTML, MD               │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  6. Chunking                                                        │
│     └ 청크 분할, 페이지 매핑, 오버랩 처리                            │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  7. Embedding                                                       │
│     └ 청크 임베딩 벡터 생성                                          │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  8. FAISS Build                                                     │
│     └ FAISS Vector Index 생성/업데이트                               │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  9. Graph RAG Build                                                 │
│     └ 노드/엣지 생성, 관계 추출                                      │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  10. LLM Wiki Build                                                 │
│     └ 발주기관별/기술별 Wiki 생성                                    │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  11. Summary Generation                                             │
│     └ 문서별 요약 생성                                               │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  12. Search Test                                                    │
│     └ 검색 품질 검증                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

## 3. 단계별 상세 설계

### 3.1 Stage 1: Storage Check

#### 목적
원문 저장소(네트워크 드라이브) 연결 상태를 확인한다.

#### 입력
```json
{
  "storage_path": "\\\\diskstation\\W2_프로젝트폴더"
}
```

#### 출력
```json
{
  "status": "healthy",
  "accessible": true,
  "total_size_gb": 1250.5,
  "free_size_gb": 358.2
}
```

#### 실패 처리
| 실패 유형 | 처리 방법 |
| --- | --- |
| 네트워크 연결 실패 | 에러 반환, 재시도 권고 |
| 권한 없음 | 에러 반환, 권한 확인 요청 |
| 경로 없음 | 에러 반환, 경로 확인 요청 |

---

### 3.2 Stage 2: Folder Scan

#### 목적
지정 폴더를 스캔하여 파일 목록을 추출한다.

#### 입력
```json
{
  "path": "\\\\diskstation\\W2_프로젝트폴더\\00. RAG 소스",
  "recursive": true,
  "file_types": ["pdf", "hwp", "hwpx", "docx", "pptx"]
}
```

#### 출력
```json
{
  "total_files": 448,
  "new_files": 125,
  "modified_files": 23,
  "unchanged_files": 300,
  "files": [
    {
      "file_path": "...",
      "file_name": "제안요청서_2024_K-water.pdf",
      "file_size": 2456789,
      "modified_at": "2026-05-01T09:00:00Z",
      "status": "new"
    }
  ]
}
```

#### 실패 처리
| 실패 유형 | 처리 방법 |
| --- | --- |
| 폴더 접근 실패 | 해당 폴더 건너뛰고 계속, errors.jsonl 기록 |
| 파일 읽기 실패 | 해당 파일 건너뛰고 계속 |

---

### 3.3 Stage 3: Preprocess

#### 목적
파일 해시 계산, 중복 체크, 기본 메타데이터 추출.

#### 입력
```json
{
  "document_ids": ["doc_001", "doc_002"],
  "force": false
}
```

#### 처리 로직
```python
for file in files:
    # 1. 파일 해시 계산 (SHA-256)
    file_hash = calculate_hash(file)

    # 2. 중복 체크
    if exists_by_hash(file_hash) and not force:
        skip(file)
        continue

    # 3. 기본 메타데이터 추출
    metadata = {
        "file_name": file.name,
        "file_path": file.path,
        "file_type": file.extension,
        "file_size": file.size,
        "file_hash": file_hash,
        "created_at": now()
    }

    # 4. documents.jsonl에 저장
    save_to_manifest(metadata)
```

#### 출력
```json
{
  "processed": 125,
  "skipped_duplicate": 23,
  "failed": 2
}
```

#### 실패 처리
| 실패 유형 | 처리 방법 |
| --- | --- |
| 해시 계산 실패 | 파일 손상 표시, 건너뛰기 |
| 저장 실패 | 재시도 3회, 실패 시 에러 기록 |

---

### 3.4 Stage 4: Metadata Extraction

#### 목적
파일명과 본문에서 메타데이터를 자동 추출한다.

#### 입력
```json
{
  "document_ids": ["doc_001"],
  "use_llm": true,
  "llm_model": "gemma4:latest"
}
```

#### 처리 로직
```python
for doc in documents:
    # 1. 규칙 기반 추출 (MetadataAutoGenerator)
    rule_result = extract_by_rules(doc.file_name, doc.content[:2000])

    # 2. LLM 기반 추출 (선택적)
    if use_llm:
        llm_result = extract_by_llm(doc.file_name, doc.content[:2000])
        result = merge(rule_result, llm_result)
    else:
        result = rule_result

    # 3. suggestions 테이블에 저장
    save_suggestion(doc.id, result)
```

#### 출력
```json
{
  "document_type": "rfp",
  "organization": "K-water",
  "project_year": "2024",
  "technology_tags": ["AI", "빅데이터"],
  "confidence": 0.85
}
```

#### 실패 처리
| 실패 유형 | 처리 방법 |
| --- | --- |
| LLM 호출 실패 | 규칙 기반 결과만 사용 |
| 추출 실패 | unknown 타입으로 저장 |

---

### 3.5 Stage 5: Text Extraction

#### 목적
PDF/HWP/DOCX 원문에서 텍스트를 추출하고 변환한다.

#### 입력
```json
{
  "document_ids": ["doc_001"],
  "output_formats": ["raw", "cleaned", "html", "md"]
}
```

#### 처리 로직
```python
for doc in documents:
    # 1. 파일 유형별 추출
    if doc.file_type == "pdf":
        raw_text = extract_pdf(doc.path)  # pdfplumber
    elif doc.file_type in ["hwp", "hwpx"]:
        raw_text = extract_hwp(doc.path)  # pyhwp 또는 olmocr
    elif doc.file_type == "docx":
        raw_text = extract_docx(doc.path)  # python-docx

    # 2. 텍스트 정제
    cleaned_text = clean_text(raw_text)

    # 3. HTML/MD 변환
    html_content = convert_to_html(cleaned_text)
    md_content = convert_to_markdown(cleaned_text)

    # 4. 페이지별 분리
    pages = split_by_page(raw_text)

    # 5. 저장
    save_to_extracted_text(doc.id, raw_text, cleaned_text, html, md, pages)
```

#### 출력 파일
```
extracted_text/{document_id}/
├── raw_text.txt
├── cleaned_text.txt
├── document.html
├── document.md
├── pages.json
└── metadata.json
```

#### 실패 처리
| 실패 유형 | 처리 방법 |
| --- | --- |
| PDF 파손 | OCR 시도, 실패 시 에러 기록 |
| HWP 구버전 | olmocr로 대체 시도 |
| 인코딩 오류 | 다중 인코딩 시도 (UTF-8, CP949, EUC-KR) |
| 암호화 파일 | 건너뛰기, 에러 기록 |

---

### 3.6 Stage 6: Chunking

#### 목적
정제된 텍스트를 청크로 분할한다.

#### 입력
```json
{
  "document_ids": ["doc_001"],
  "chunk_size": 1000,
  "chunk_overlap": 200,
  "split_by": "semantic"
}
```

#### 처리 로직
```python
for doc in documents:
    cleaned_text = load_cleaned_text(doc.id)
    pages = load_pages(doc.id)

    chunks = []
    for page in pages:
        # 1. 의미 단위 분할 (문단, 섹션)
        segments = split_semantic(page.text)

        for segment in segments:
            # 2. 크기 기반 분할
            if len(segment) > chunk_size:
                sub_chunks = split_by_size(segment, chunk_size, overlap)
                chunks.extend(sub_chunks)
            else:
                chunks.append(segment)

    # 3. 청크 메타데이터 추가
    for i, chunk in enumerate(chunks):
        chunk_data = {
            "chunk_id": f"chunk_{doc.id}_{i:03d}",
            "document_id": doc.id,
            "chunk_index": i,
            "page_number": find_page(chunk),
            "text": chunk,
            "text_length": len(chunk)
        }
        save_chunk(chunk_data)
```

#### 출력
```json
{
  "total_chunks": 45,
  "avg_chunk_size": 850,
  "min_chunk_size": 200,
  "max_chunk_size": 1000
}
```

#### 실패 처리
| 실패 유형 | 처리 방법 |
| --- | --- |
| 빈 텍스트 | 건너뛰기 |
| 청크 크기 이상 | 강제 분할 |

---

### 3.7 Stage 7: Embedding

#### 목적
청크를 벡터로 임베딩한다.

#### 입력
```json
{
  "chunk_ids": ["chunk_001_000", "chunk_001_001"],
  "model": "mxbai-embed-large",
  "batch_size": 32
}
```

#### 처리 로직
```python
# 배치 처리
for batch in chunks.batch(batch_size):
    texts = [chunk.text for chunk in batch]

    # Ollama 임베딩 API 호출
    embeddings = ollama.embed(model, texts)

    # 임베딩 저장 (메모리 또는 임시 파일)
    for chunk, embedding in zip(batch, embeddings):
        chunk.embedding = embedding
        chunk.embedding_id = f"emb_{chunk.id}"
```

#### 출력
```json
{
  "total_embeddings": 3450,
  "embedding_dim": 1024,
  "model": "mxbai-embed-large",
  "time_ms": 45000
}
```

#### 실패 처리
| 실패 유형 | 처리 방법 |
| --- | --- |
| Ollama 연결 실패 | 대기 후 재시도 (최대 5회) |
| 배치 실패 | 배치 크기 축소 후 재시도 |
| 메모리 부족 | 배치 크기 축소 |

---

### 3.8 Stage 8: FAISS Build

#### 목적
FAISS Vector Index를 생성하거나 업데이트한다.

#### 입력
```json
{
  "collection_name": "weeslee_rag",
  "index_type": "IndexFlatIP",
  "rebuild": false
}
```

#### 처리 로직
```python
if rebuild or not exists(index_path):
    # 전체 재빌드
    index = faiss.IndexFlatIP(embedding_dim)

    for chunk in all_chunks:
        index.add(chunk.embedding)
        id_map[index.ntotal - 1] = chunk.id

    faiss.write_index(index, index_path)
    save_metadata(collection_name, id_map)
else:
    # 증분 업데이트
    index = faiss.read_index(index_path)

    for chunk in new_chunks:
        index.add(chunk.embedding)
        id_map[index.ntotal - 1] = chunk.id

    faiss.write_index(index, index_path)
```

#### 출력
```json
{
  "collection_name": "weeslee_rag",
  "total_vectors": 3450,
  "index_size_mb": 14.2,
  "build_time_ms": 5000
}
```

#### 실패 처리
| 실패 유형 | 처리 방법 |
| --- | --- |
| 인덱스 손상 | 전체 재빌드 |
| 디스크 공간 부족 | 에러 반환, 정리 요청 |

---

### 3.9 Stage 9: Graph RAG Build

#### 목적
문서 메타데이터에서 노드와 엣지를 생성한다.

#### 입력
```json
{
  "document_ids": null,
  "node_types": ["organization", "project", "technology", "document"],
  "relation_model": "gemma4:latest"
}
```

#### 처리 로직
```python
# 1. 노드 생성
for doc in documents:
    # 문서 노드
    create_node("document", doc.id, doc.file_name)

    # 발주기관 노드
    if doc.organization:
        org_id = get_or_create_node("organization", doc.organization)
        create_edge(org_id, doc.id, "published_by")

    # 기술 노드
    for tech in doc.technology_tags:
        tech_id = get_or_create_node("technology", tech)
        create_edge(doc.id, tech_id, "uses_tech")

# 2. 관계 추출 (LLM 기반, 선택적)
if relation_model:
    for doc_pair in similar_documents:
        relation = extract_relation_llm(doc_pair)
        if relation:
            create_edge(doc_pair[0], doc_pair[1], relation)
```

#### 출력
```json
{
  "total_nodes": 450,
  "total_edges": 1250,
  "node_types": {
    "organization": 25,
    "document": 250,
    "technology": 35
  }
}
```

#### 실패 처리
| 실패 유형 | 처리 방법 |
| --- | --- |
| LLM 관계 추출 실패 | 규칙 기반만 사용 |
| 중복 노드 | 기존 노드 재사용 |

---

### 3.10 Stage 10: LLM Wiki Build

#### 목적
발주기관별, 기술별 Wiki 문서를 생성한다.

#### 입력
```json
{
  "generation_units": ["organization", "technology"],
  "wiki_model": "gemma4:latest",
  "summary_length": "medium"
}
```

#### 처리 로직
```python
# 발주기관별 Wiki
for org in organizations:
    docs = get_documents_by_org(org)

    prompt = f"""
    다음 {org}의 프로젝트 문서들을 분석하여 Wiki를 작성하세요.

    문서 목록:
    {format_doc_list(docs)}

    Wiki 형식:
    - 개요
    - 주요 프로젝트 (연도별)
    - 기술 트렌드
    """

    wiki_content = llm.generate(prompt)
    save_wiki("organizations", org, wiki_content)

# 기술별 Wiki
for tech in technologies:
    docs = get_documents_by_tech(tech)
    wiki_content = generate_tech_wiki(tech, docs)
    save_wiki("technologies", tech, wiki_content)
```

#### 출력
```json
{
  "total_wikis": 60,
  "by_type": {
    "organization": 25,
    "technology": 35
  },
  "generation_time_ms": 120000
}
```

#### 실패 처리
| 실패 유형 | 처리 방법 |
| --- | --- |
| LLM 생성 실패 | 건너뛰기, 에러 기록 |
| 문서 부족 | 최소 문서 수 미달 시 건너뛰기 |

---

### 3.11 Stage 11: Summary Generation

#### 목적
각 문서의 요약을 생성한다.

#### 입력
```json
{
  "document_ids": ["doc_001"],
  "summary_model": "gemma4:latest",
  "max_tokens": 500
}
```

#### 처리 로직
```python
for doc in documents:
    cleaned_text = load_cleaned_text(doc.id)

    prompt = f"""
    다음 문서를 요약하세요.

    문서: {cleaned_text[:4000]}

    요약 형식:
    - 개요 (1-2문장)
    - 핵심 포인트 (3-5개)
    """

    summary = llm.generate(prompt)
    save_summary(doc.id, summary)
```

#### 출력
```json
{
  "total_summaries": 125,
  "avg_length": 350,
  "generation_time_ms": 60000
}
```

---

### 3.12 Stage 12: Search Test

#### 목적
검색 품질을 검증한다.

#### 입력
```json
{
  "test_queries": [
    "K-water AI 수자원 관리",
    "LH 디지털트윈",
    "한전 스마트그리드"
  ],
  "expected_results": {
    "K-water AI 수자원 관리": ["doc_001", "doc_002"]
  }
}
```

#### 출력
```json
{
  "tests_passed": 8,
  "tests_failed": 2,
  "precision": 0.85,
  "recall": 0.92,
  "details": [...]
}
```

## 4. Job 상태 관리

### 4.1 상태 정의

| 상태 | 설명 |
| --- | --- |
| pending | 대기 중 |
| running | 실행 중 |
| completed | 완료 |
| failed | 실패 |
| cancelled | 취소됨 |
| paused | 일시 중지 |

### 4.2 진행률 계산

```python
progress = (processed_items / total_items) * 100
```

### 4.3 Job 이력 저장

```json
{
  "job_id": "job_rag_001",
  "job_type": "rag_build",
  "status": "completed",
  "progress": 100,
  "total_items": 125,
  "processed_items": 125,
  "failed_items": 0,
  "started_at": "2026-05-21T11:00:00Z",
  "completed_at": "2026-05-21T11:45:00Z"
}
```

## 5. 실패 처리 총괄 정책

### 5.1 재시도 정책

| 단계 | 최대 재시도 | 재시도 간격 |
| --- | --- | --- |
| Storage Check | 3회 | 5초 |
| Folder Scan | 2회 | 3초 |
| Text Extraction | 2회 | 즉시 |
| Embedding | 5회 | 10초 (exponential backoff) |
| LLM 호출 | 3회 | 5초 |

### 5.2 에러 기록

모든 실패는 `errors.jsonl`에 기록한다.

```json
{
  "error_id": "err_001",
  "job_id": "job_rag_001",
  "document_id": "doc_005",
  "stage": "text_extraction",
  "error_type": "pdf_corrupted",
  "error_message": "PDF 파일 손상",
  "occurred_at": "2026-05-21T11:15:00Z"
}
```

### 5.3 부분 실패 처리

파이프라인의 일부 문서가 실패해도 나머지는 계속 진행한다.
실패한 문서는 `failed` 상태로 표시되고, 나중에 개별 재시도 가능.

## 6. 산출물 체크리스트

- [x] 파이프라인 전체 흐름도
- [x] 12단계 상세 설계 (입력/출력/처리로직)
- [x] 각 단계별 실패 처리 정책
- [x] Job 상태 관리
- [x] 재시도 정책
- [x] 에러 기록 구조

---

작성일: 2026-05-21
작성자: Claude
다음 단계: Phase 7. LLM 환각 방지 정책
