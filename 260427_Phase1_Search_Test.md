# 2026-04-27 1차 검색 테스트 계획

## 1. 목적

1차 표본 18건에서 생성한 chunk/FAISS 인덱스를 대상으로,
질의문 기반 상위 유사 chunk 조회가 가능한지 확인한다.

## 2. 현재 전제

- chunking 완료
- hashing 기반 FAISS 인덱스 완료
- 이 인덱스는 검색 품질 검증이 아니라 배치/검색 흐름 검증용이다

## 3. 테스트 스크립트

- `backend/scripts/search_faiss_index.py`

## 4. 테스트 질의 예시

1. `공공기관 ISP 제안 발표자료`
2. `착수보고 데이터 플랫폼 전략`
3. `최종보고 스마트시티 플랫폼`
4. `ISMP 제안서 차세대 업무 시스템`

## 5. 기대 결과

1. 질의 결과가 chunk 단위로 반환된다
2. 각 결과에 `document_id`, `category`, `section_heading`, `source_path`가 포함된다
3. 이후 RAG 응답 조립 시 이 결과를 근거 컨텍스트로 사용할 수 있다

## 6. 다음 보완

1. `nomic-embed-text` 설치 후 실제 embedding 기반 재인덱싱
2. 상위 결과를 문서 단위로 집계하는 reranking 추가
3. 추천 이유 템플릿 추가
