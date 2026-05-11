sequenceDiagram
    actor 사용자
    participant GW as API Gateway
    participant QA as Q&A Service
    participant RAG as RAG Pipeline
    participant VDB as Vector DB
    participant LLM as LLM Engine
    participant DOC as Document Store

    사용자->>GW: 자연어 질문 입력
    GW->>GW: 인증 / 권한 확인 (RBAC)
    GW->>QA: 질문 전달

    QA->>RAG: 질문 임베딩 요청
    RAG->>VDB: 벡터 유사도 검색 (Top-K)
    VDB-->>RAG: 관련 청크 반환

    RAG->>DOC: 원문 문서 조회
    DOC-->>RAG: 원문 텍스트 반환

    RAG->>LLM: [질문 + 컨텍스트] 프롬프트 전송
    LLM-->>RAG: 생성된 답변 반환

    RAG-->>QA: 답변 + 출처 문서 목록
    QA-->>사용자: 최종 응답\n(답변 본문 + 참조 문서 링크)
