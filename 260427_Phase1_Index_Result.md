# 2026-04-27 1차 청킹/FAISS 실행 결과

## 1. 목적

1차 표본 문서에 대해
`추출 -> 청킹 -> FAISS 인덱스 -> 검색 테스트`까지 실제 실행 결과를 기록한다.

## 2. 실행 기준

- 서버: `192.168.0.207`
- 작업 경로: `/data/weeslee/weeslee-rag`
- 입력 배치:
  `snapshot_2026-04-27_batch-001-top5-v2`

## 3. 추출 결과

- 전체 표본: 22건
- 추출 성공: 18건
- 1차 제외:
  - `.hwp`
  - `.hwpx`
  총 4건

## 4. 청킹 결과

실행 스크립트:

- `backend/scripts/build_chunk_batch.py`

산출물:

- `data/staged/chunks/snapshot_2026-04-27_batch-001-top5-v2_chunks.jsonl`
- `data/staged/chunks/snapshot_2026-04-27_batch-001-top5-v2_chunks.csv`

결과:

- 문서 수: 18건
- chunk 수: 1,598건

해석:

1. 청킹 파이프라인 자체는 정상 동작했다.
2. 일부 문서에서 chunk 수가 많아 과분할 가능성이 있다.
3. 다음 단계에서 `max_chars`, `min_chars`, heading 인식 규칙을 재조정할 필요가 있다.

## 5. 인프라 확인 결과

### 5.1 Ollama

- 설치 확인: `있음`
- 확인 모델:
  - `qwen3:0.6b`
  - `qwen:14b`
  - `llama3:8b`
  - `qwen3:latest`
  - `gemma4:latest`
  - `qwen:7b`
  - `gemma3:4b`
  - `exaone3.5:2.4b`

현재 상태:

- `nomic-embed-text` 미설치

### 5.2 FAISS

- `.venv`에 `faiss-cpu` 설치 완료

## 6. FAISS 인덱스 결과

실행 스크립트:

- `backend/scripts/build_faiss_index.py`

산출물:

- `data/indexes/faiss/snapshot_2026-04-27_batch-001-top5-v2_hashing.index`
- `data/indexes/faiss/snapshot_2026-04-27_batch-001-top5-v2_hashing_metadata.jsonl`
- `data/indexes/faiss/snapshot_2026-04-27_batch-001-top5-v2_hashing_manifest.json`

결과:

- embedding provider: `hashing`
- vector count: `1,598`
- document count: `18`

주의:

- `hashing`은 검색 품질 검증용이 아니라 배치 흐름 검증용이다.
- 실제 RAG 품질 검증은 `nomic-embed-text` 또는 동급 embedding 모델로 재인덱싱해야 한다.

## 6.1 실제 embedding 재인덱싱 결과

추가 조치:

1. 서버 `ollama`에 `nomic-embed-text` 설치
2. 일부 chunk에서 `input length exceeds the context length` 오류 확인
3. `build_faiss_index.py`에 `max_embed_chars=1800` 제한 추가

실행 결과:

- 인덱스:
  `data/indexes/faiss/snapshot_2026-04-27_batch-001-top5-v2_ollama.index`
- 메타데이터:
  `data/indexes/faiss/snapshot_2026-04-27_batch-001-top5-v2_ollama_metadata.jsonl`
- manifest:
  `data/indexes/faiss/snapshot_2026-04-27_batch-001-top5-v2_ollama_manifest.json`

상태:

- `embedding_provider`: `ollama`
- `ollama_model`: `nomic-embed-text`
- `vector_count`: `1,598`
- 실제 embedding 기반 FAISS 재생성 성공

## 7. 검색 테스트 결과

실행 스크립트:

- `backend/scripts/search_faiss_index.py`

테스트 질의:

- `차세대 업무 시스템 ISMP 제안서`

결과 해석:

1. 상위 결과가 `202603. AX기반의 차세대 업무 시스템 구축을 위한 ISMP` 제안서 문서로 집중되었다.
2. 즉, 1차 기준 검색 파이프라인 연결은 확인되었다.
3. 다만 현재는 hashing 기반이라 점수 품질은 의미 있게 해석하면 안 된다.

## 7.1 실제 embedding 검색 확인

추가 검색:

- 질의: `차세대업무시스템`
- 인덱스: `snapshot_2026-04-27_batch-001-top5-v2_ollama.index`

해석:

1. 실제 embedding 인덱스에서도 질의 응답 경로는 정상 동작했다.
2. 다만 매우 짧은 질의에서는 상위 점수가 과도하게 비슷하게 나타났다.
3. 이는 현재 chunk 과분할과 문서 단위 집계 부재 영향이 크다.
4. 다음 단계에서는 `질의 확장`, `document-level reranking`, `chunk 파라미터 조정`이 필요하다.

## 8. 현재 판단

1차 목표에서 중요한 것은 이미 달성되었다.

1. 원본 snapshot 복사
2. 추출 성공 경로 확보
3. 청킹 산출물 생성
4. FAISS 인덱스 생성
5. 질의 기반 검색 가능 확인

## 9. 다음 단계

1. `nomic-embed-text` 설치 여부 검토
2. chunk 수 과다 문서에 대한 청킹 파라미터 조정
3. 문서 단위 집계와 추천 이유 생성
4. 질의 확장 및 reranking
5. 이후 RAG 응답 조립
