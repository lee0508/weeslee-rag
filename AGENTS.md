# AGENTS.md

## Project: weeslee-rag

이 프로젝트는 weeslee 회사 문서 중앙화 RAG 시스템이다.

주요 목적:
- 회사 문서, 제안서, RFP, 산출물을 RAG 검색 대상으로 구조화한다.
- 관리자 페이지에서 문서 스캔, 메타데이터 생성, FAISS 인덱스 생성, Graph JSON 생성, LLM Wiki 생성을 관리한다.
- 사용자 페이지에서 RAG 검색, RAG Agent, Graph RAG, LLM Wiki 결과를 제공한다.

## Important Environment Rules

### Local Development Environment

개발 작업은 사용자 노트북 Windows 10 환경에서 진행한다.

기본 개발 위치:
- C:\xampp\htdocs\weeslee-rag
- VSCode 사용
- HTML, JavaScript, Python, FastAPI 중심
- 프론트엔드 파일 수정 시 기존 구조를 최대한 유지한다.

### Server Deployment Environment

데이터셋 구성, 서버 테스트, 웹 테스트는 회사 서버에서 진행한다.

서버:
- Host: 192.168.0.207
- Project path: /data/weeslee/weeslee-rag
- External URL:
  - Admin: https://server.weeslee.co.kr/weeslee-rag/frontend/admin.html
  - User: https://server.weeslee.co.kr/weeslee-rag/frontend/rag-assistant.html

주의:
- 로컬에서만 코드 수정했다고 완료로 판단하지 않는다.
- 서버에 배포한 후 admin.html, rag-assistant.html에서 실제 동작을 확인해야 한다.
- 데이터셋 생성, FAISS 인덱스, Graph JSON, LLM Wiki 테스트는 서버 기준으로 판단한다.

## Work Policy

1. 코드 수정 전 현재 파일 구조를 먼저 확인한다.
2. 기존 API 경로와 기존 함수명을 함부로 변경하지 않는다.
3. admin.html과 rag-assistant.html은 서로 연결되는 기능이 많으므로 한쪽만 수정하지 않는다.
4. 데이터셋 관련 변경은 다음 흐름을 기준으로 판단한다.

   Source Documents
   → Scan
   → Metadata Build
   → Collection Bootstrap
   → FAISS Jobs
   → Graph Build
   → Wiki Build
   → User Search Test

5. 기존 문서 중앙화 목적과 맞지 않는 임시 기능은 추가하지 않는다.
6. 수정 후에는 변경 파일, 변경 이유, 테스트 방법을 반드시 정리한다.

## Do Not

- 테스트 없이 “완료”라고 말하지 말 것.
- SQLite 전용 설계를 MySQL 기반 프로젝트에 그대로 적용하지 말 것.
- 서버 경로와 로컬 경로를 혼동하지 말 것.
- 운영 URL을 localhost 기준으로 설명하지 말 것.
- Dataset Builder와 단순 파일 업로드를 같은 기능으로 취급하지 말 것.
- Graph DB Neo4j 사용을 전제로 답변하지 말 것. 현재 기본 방향은 Graph JSON 저장이다.

## Preferred Output

답변은 한국어로 작성한다.
수정 코드는 가능한 한 주석을 포함한다.
작업 결과는 다음 형식으로 정리한다.

1. 수정 목적
2. 수정 파일
3. 핵심 변경 내용
4. 테스트 방법
5. 서버 배포 시 주의사항