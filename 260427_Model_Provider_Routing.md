# 2026-04-27 모델 / Provider 분기 기준

## 1. 목적

`.env`에 정의된 API 키와 로컬 Ollama 설정을 기준으로,
문서 중앙화 RAG 시스템이 어떤 모델 provider를 어떤 용도로 사용할지 정리한다.

## 2. 현재 사용 가능한 provider

`.env` 기준:

- `Ollama`
- `OpenAI`
- `Gemini`
- `OpenRouter`

## 3. 권장 역할 분담

### 3.1 임베딩

- 기본: `Ollama + nomic-embed-text`

이유:

1. 서버 로컬 실행 가능
2. 외부 API 비용/지연 최소화
3. 문서 검색 인덱스 재생성이 쉬움

### 3.2 1차 응답 생성

- 기본: `Ollama + gemma4:latest`

이유:

1. 서버에 이미 설치되어 있음
2. 내부 문서 기반 초안 생성 실험에 적합
3. 외부 키 의존 없이 PoC 진행 가능

### 3.3 비교 실험 후보

- `OpenAI`
- `Gemini`
- `OpenRouter`

용도:

1. 초안 품질 비교
2. 응답 형식 안정성 비교
3. 장문 RFP 해석 성능 비교

## 4. 코드 반영 상태

`backend/scripts/assemble_rag_response.py`에서 아래 provider를 선택 가능하게 정리했다.

- `--answer-provider ollama`
- `--answer-provider openai`
- `--answer-provider gemini`
- `--answer-provider openrouter`

또한 `.env` 파일을 직접 읽어 API 키를 사용할 수 있게 했고,
모델명과 Ollama URL도 환경변수에서 기본값을 자동 보정하도록 했다.

## 5. 운영 권장

### 5.1 기본 운영

- embedding: `Ollama`
- answer: `Ollama gemma4`

### 5.2 비교 평가

같은 검색 결과에 대해 아래 비교를 권장한다.

1. `gemma4`
2. `OpenAI`
3. `Gemini`

평가 항목:

1. 문서 추천 타당성
2. 추천 이유 명확성
3. 제안서 작성 활용 포인트 품질
4. 환각 여부

## 6. 보안 메모

`.env`에 실 API 키가 있으므로 운영 전에는 아래 조치가 필요하다.

1. 키 재발급 또는 교체
2. 배포 환경에서는 서버 환경변수 또는 비밀 저장소 사용
3. `.env` 파일이 Git에 포함되지 않도록 유지
