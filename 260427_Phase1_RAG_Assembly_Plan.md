# 2026-04-27 1차 RAG 응답 조립 계획

## 1. 목적

실제 embedding 기반 FAISS 검색 결과를
`문서 단위 추천 -> 추천 이유 -> 초안 응답` 형태로 조립한다.

## 2. 입력 자산

- 실제 embedding 인덱스
- 인덱스 메타데이터 JSONL
- chunk JSONL
- 질의문 또는 RFP 일부 문장

## 3. 처리 단계

1. top-k chunk 검색
2. 동일 문서 hit 집계
3. 문서별 최고 점수 / hit count / 관련 section 정리
4. 추천 이유 자동 생성
5. `gemma4:latest`로 초안 응답 생성

## 4. 산출물

- JSON 결과
- Markdown 보고서
- 추천 문서 목록
- 추천 이유
- 제안서 작성 활용 포인트

## 5. 1차 구현 원칙

1. reranker 없이 단순 집계부터 시작
2. chunk 점수와 반복 hit를 문서 점수 신호로 사용
3. 추천 이유는 규칙 기반으로 생성
4. 최종 초안만 `gemma4`에 위임

## 6. 다음 보완 항목

1. query expansion
2. document-level reranking
3. 기관/사업유형/문서유형 메타데이터 결합
4. 그래프 기반 explainable recommendation
