# 2026-04-27 작업 결과 문서

## 1. 작업 목적

`260427_Plan.md`를 기준으로, 위즐리앤컴퍼니 문서 중앙화 프로젝트의 1차 착수 전 분석 결과를 실제 실행 기준 문서와 저장소 구조로 정리했다.

## 2. 수행한 작업

1. 원본 문서 복사 정책 정리
2. 서버 `data/` 레이아웃 설계
3. manifest 구조 정의
4. 메타데이터 스키마 초안 정리
5. OCR/정규화/청킹/FAISS/그래프 결합 구조 설계
6. Git 추적/제외 범위 정리
7. 저장소 `.gitignore`에 데이터 파이프라인 제외 규칙 추가
8. 서버 `/data/weeslee/weeslee-rag/data` 기본 디렉터리 실제 생성
9. dry-run manifest 생성 스크립트 작성
10. manifest/metadata 예제 파일 작성
11. 복사 실행 런북 작성
12. 원본 저장소 `W:` 연결 성공
13. 원본 상위 폴더 구조 확인
14. 상위 폴더별 문서 수 인벤토리 생성
15. 1차 목표 범위 문서화
16. 1차 후보 프로젝트 50개 선정
17. 상위 10개 후보 프로젝트 하위 구조 및 대표 문서 패턴 분석
18. 상위 10개 프로젝트 대표 복사 대상 폴더 계획 수립
19. 상위 5개 프로젝트 대표 파일 1차 확정
20. 개발 계획 재검토 문서 작성
21. 상위 5개 대표 파일 기준 dry-run manifest 생성
22. manual_review 4건 중 2건 보완 완료

## 3. 생성/수정 파일

1. `260427_Ingestion_Design.md`
2. `260427_Work_Result.md`
3. `.gitignore`
4. `260427_Copy_Runbook.md`
5. `backend/scripts/prepare_snapshot_manifest.py`
6. `data/staged/metadata/_schema.example.json`
7. `data/staged/manifest/_manifest.example.json`
8. `data/.gitkeep`
9. `data/raw/.gitkeep`
10. `data/staged/.gitkeep`
11. `data/staged/manifest/.gitkeep`
12. `data/staged/metadata/.gitkeep`
13. `data/indexes/.gitkeep`
14. `data/wiki/.gitkeep`

## 4. 핵심 결정 사항

1. `W:\01. 국내사업폴더`는 원본으로 유지하고, 서버에는 snapshot 복제본만 둔다.
2. 원본과 검색용 가공본을 물리적으로 분리한다.
3. FAISS는 검색 인덱스 계층으로 사용하되, 메타데이터 필터와 그래프 탐색을 반드시 결합한다.
4. Git에는 정규화 규칙과 메타데이터, 위키, 그래프 규칙만 넣고 대용량 원본/인덱스는 제외한다.
5. 1차 개발은 전체 적재가 아니라 300~500건 표본 중심으로 시작한다.
6. 서버 기본 경로 `/data/weeslee/weeslee-rag/data`는 생성 완료 상태로 맞췄다.
7. 현재 세션에서는 `W:` 드라이브가 보이지 않아 실제 표본 복사는 보류했다.

## 5. 남은 작업

1. 서버 `/data/weeslee/weeslee-rag/data` 실제 생성
2. 샘플 폴더 선정
3. 1차 복사 배치 실행
4. manifest 생성 자동화
5. 메타데이터 JSON 예제 파일 작성
6. ingest 스크립트 구현
7. FAISS 인덱스 연결
8. `W:` 접근 가능한 윈도우 PC에서 dry-run 실행

## 6. 비고

현재 저장소는 `FastAPI + ChromaDB` 성격이 있으며, 사용자 목표는 `Flask + FAISS` 방향이다.  
즉시 전면 전환보다는 기존 추출/OCR/메타데이터 자산을 재사용하면서 인덱스 계층과 아키텍처를 정리하는 것이 1차 개발에 더 적합하다.
