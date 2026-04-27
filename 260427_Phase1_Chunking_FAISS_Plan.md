# 2026-04-27 1차 청킹/임베딩/FAISS 계획

## 1. 목적

1차 추출 성공 문서 18건을 대상으로,
`청킹 -> 임베딩 -> FAISS 인덱스`까지 연결되는 최소 검색 파이프라인을 구축한다.

## 2. 현재 상태

- snapshot 복사 완료: 22건
- 추출 결과:
  - `success`: 18건
  - `skipped_unsupported`: 4건
- HWP/HWPX는 1차에서 제외

## 3. 1차 처리 범위

### 3.1 입력

- `data/staged/text/*.txt`
- `data/staged/metadata/*.json`
- `data/staged/manifest/snapshot_2026-04-27_batch-001-top5-v2_extraction_summary.csv`

### 3.2 출력

- `data/staged/chunks/*.jsonl`
- `data/staged/chunks/*.csv`
- `data/indexes/faiss/*.index`
- `data/indexes/faiss/*.jsonl`
- `data/indexes/faiss/*.manifest.json`

## 4. 청킹 원칙

1. 문서 전체를 무조건 고정 길이로 자르지 않는다.
2. 가능한 경우 제목/절/문단 경계를 유지한다.
3. 1차는 토큰 기반 정밀 분할보다 `문단 + 문자 수 기준`으로 단순화한다.
4. 한국어 문서 특성을 고려해 `1400 chars / 180 overlap` 기본값으로 시작한다.

## 5. 임베딩 원칙

### 5.1 1차 권장

- `Ollama + nomic-embed-text`

이유:

1. 사내 서버 중심 운영과 맞는다.
2. 외부 API 의존도를 줄일 수 있다.
3. 이후 RAG 응답 경로와도 자연스럽게 연결된다.

### 5.2 임시 fallback

- `hashing` provider

주의:

이 방식은 검색 품질 검증용이 아니라, 인덱스 구조와 배치 흐름 확인용이다.

## 6. FAISS 원칙

1. 1차는 `IndexFlatIP`로 단순 시작
2. 임베딩은 정규화 후 cosine 유사도처럼 사용
3. 메타데이터는 인덱스 내부가 아니라 별도 `.jsonl`로 관리

## 7. 구현 스크립트

### 7.1 청킹

- `backend/scripts/build_chunk_batch.py`

역할:

1. 추출 summary CSV 읽기
2. 성공 문서의 text/metadata 읽기
3. section-aware chunk 생성
4. chunk JSONL / CSV 저장

### 7.2 FAISS

- `backend/scripts/build_faiss_index.py`

역할:

1. chunk JSONL 읽기
2. 임베딩 생성
3. FAISS 인덱스 저장
4. 메타데이터 JSONL 저장
5. 인덱스 manifest 저장

## 8. 권장 실행 순서

1. chunk JSONL 생성
2. 샘플 chunk 품질 점검
3. Ollama 또는 fallback embedding provider 결정
4. FAISS 인덱스 생성
5. 샘플 질의 검색 테스트

## 9. 다음 확인 항목

1. 서버에 `ollama` 설치 여부
2. 서버 `.venv`에 `faiss-cpu` 설치 여부
3. 필요 시 `pip install faiss-cpu`

## 10. 1차 완료 기준

아래가 충족되면 1차 검색 PoC의 핵심 파이프라인은 완성으로 본다.

1. 18건 성공 문서가 chunk로 분해됨
2. chunk 기반 FAISS 인덱스 생성됨
3. 질의문으로 유사 chunk 상위 결과를 조회할 수 있음
4. 결과에 `document_id`, `category`, `section_heading`, `source_path`를 함께 반환할 수 있음
