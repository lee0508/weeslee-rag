# 2026-04-27 Gemma4 / Hermes 점검

## 1. 점검 목적

다음 단계인 `문서 단위 추천 + RAG 응답 조립`에 앞서,
회사 서버에서 사용할 수 있는 생성 모델과 보조 에이전트 자산을 확인한다.

## 2. Ollama 모델 상태

서버 `192.168.0.207`의 `ollama list` 기준:

- `gemma4:latest`
- `nomic-embed-text:latest`
- `llama3:8b`
- `qwen3:latest`
- `qwen:14b`
- `qwen:7b`
- `gemma3:4b`
- `exaone3.5:2.4b`

판단:

1. 임베딩은 `nomic-embed-text` 사용 유지
2. RAG 응답 생성 후보는 `gemma4:latest` 사용 가능

## 3. Hermes 상태

`weeslee` 계정 홈 아래에서 `~/.hermes` 설치 확인:

- 경로: `/home/weeslee/.hermes`
- 확인 항목:
  - `config.yaml`
  - `auth.json`
  - `skills/`
  - `sessions/`
  - `logs/`
  - `hermes-agent/`
  - `bin/tirith`

## 4. Hermes 설정 의미

`config.yaml` 기준:

1. 기본 provider는 로컬 `Ollama`
2. base URL은 `http://127.0.0.1:11434/v1`
3. 기본 모델은 `qwen3:0.6b`
4. context length는 `64000`

판단:

1. Hermes는 서버에서 이미 `로컬 Ollama 기반 에이전트`로 운용 가능한 상태다.
2. 다만 현재 문서 중앙화 프로젝트는 별도 저장소와 데이터 구조를 갖고 있으므로,
   즉시 Hermes 내부 구조와 결합하는 것보다 현재 repo 안에서 RAG 조립 스크립트를 유지하는 편이 안전하다.
3. 이후 2차에서 Hermes를 `운영형 에이전트 인터페이스`로 붙일 수는 있다.

## 5. 적용 결론

### 지금 바로 사용하는 것

- `nomic-embed-text`
- `gemma4:latest`

### 지금 바로 통합하지 않는 것

- Hermes 내부 워크플로우 전체

이유:

1. 1차 목표는 PoC 검색/RAG 품질 확보가 우선이다.
2. Hermes는 운영/에이전트 계층에 가깝다.
3. 지금은 `검색 -> 문서 집계 -> 추천 이유 -> 초안 응답`을 현재 저장소에서 완결시키는 편이 리스크가 낮다.
