# 2026-04-27 Graphify 도입 판단

## 1. 판단 대상

- 참조 문서: `https://graphify.net/kr/index.html#install`
- 참조 문서: `https://graphify.net/kr/knowledge-graph-for-ai-coding-assistants.html`
- 현재 프로젝트 목적:
  공공/민간 입찰의 RFP 문서를 분석하고, 과거 컨설팅 문서와 연결하여 제안서 초안 작성을 지원하는 시스템 구축

## 2. 결론

Graphify는 **1차 PoC의 필수 설치 항목은 아니다.**
다만 **2차 그래프 레이어 설계와 실험에는 유용하다.**

즉, 지금 단계에서는 `OCR -> 텍스트 추출 -> 메타데이터 -> 청킹 -> FAISS/RAG`를 우선 완성하고,
그 다음 단계에서 Graphify의 구조적 아이디어를 문서 관계 그래프에 반영하는 것이 맞다.

## 3. 이유

### 3.1 지금 1차 목표와 직접 맞닿은 기능

1. 원본 문서 snapshot 보존
2. 지원 포맷 텍스트 추출
3. OCR fallback
4. 메타데이터 정규화
5. 청킹
6. 벡터 검색
7. RAG 기반 추천

위 항목은 Graphify 없이도 구축 가능하다.

### 3.2 Graphify의 강점

Graphify 계열 문서에서 중요한 개념은 아래와 같다.

1. 그래프 기반 구조화
2. provenance 추적
3. 관계 중심 탐색
4. 압축된 컨텍스트 생성
5. explainable retrieval

이 강점은 현재 프로젝트의 2차 목표와 잘 맞는다.
특히 "왜 이 문서를 추천했는가"를 설명해야 하는 입찰/제안 지원 시스템에는 적합하다.

### 3.3 바로 핵심 엔진으로 넣지 않는 이유

1. 현재 1차 PoC는 그래프보다 추출 품질과 데이터 정규화가 더 중요하다.
2. 우리 데이터는 코드 저장소가 아니라 `RFP / 제안서 / 착수보고 / 최종보고 / 발표자료` 중심 문서 집합이다.
3. Graphify를 즉시 도입하면 일반 그래프 구조에 문서 체계를 맞추게 될 위험이 있다.
4. 먼저 위즐리앤컴퍼니 전용 문서 그래프 스키마를 정리한 뒤, Graphify를 실험적으로 붙이는 편이 안전하다.

## 4. 권장 적용 시점

### 4.1 지금 즉시 필요한 것

- 설치 보류 가능
- 문서/기관/프로젝트/요구사항 관계 모델 정의
- extraction metadata와 chunk metadata 표준화

### 4.2 2차에서 검토할 것

- Graphify 별도 실험 환경 설치
- normalized markdown/text 입력 기준 그래프 생성 실험
- `graph.json` 또는 유사 그래프 산출물을 내부 schema와 매핑

## 5. 실제 적용 권장 방식

Graphify를 그대로 주 시스템의 핵심 저장소로 쓰기보다는 아래 방식이 적합하다.

1. 1차:
   - `FAISS + metadata filter + BM25 + extraction pipeline`
2. 2차:
   - `document graph` 추가
   - Graphify 아이디어 또는 도구를 실험적으로 적용
3. 3차:
   - explainable recommendation
   - project wiki / organization wiki / methodology wiki 자동 생성

## 6. 설치 여부 판단

### 6.1 지금 설치하지 않아도 되는 이유

1. 1차 추출 배치와 검색 PoC는 이미 Graphify 없이 진행 가능하다.
2. 설치 즉시 얻는 효용보다 운영 복잡도 증가가 더 크다.
3. 현재는 HWP/HWPX 처리, chunking, embedding, retrieval 품질 검증이 우선이다.

### 6.2 설치가 필요한 시점

아래 질문에 답해야 할 때 설치 검토 가치가 높다.

1. 왜 이 문서가 추천되었는지 관계 기반 설명이 필요한가
2. 프로젝트/기관/산출물 간 재사용 패턴을 시각적으로 추적할 것인가
3. 단순 벡터 검색을 넘어 graph traversal을 도입할 것인가

세 질문에 모두 `예`라면 2차에서 Graphify 실험이 의미 있다.

## 7. 최종 판단

- `필수 여부`: 아니오
- `지금 설치`: 보류
- `2차 실험`: 권장
- `핵심 반영 요소`: provenance, relation edges, explainable retrieval
