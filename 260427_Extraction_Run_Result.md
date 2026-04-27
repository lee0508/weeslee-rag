# 2026-04-27 1차 추출 실행 결과

## 1. 목적

상위 5개 프로젝트에서 선정한 대표 문서 22건을 대상으로, 서버 `/data/weeslee/weeslee-rag` 기준 1차 텍스트 추출 배치를 실행하고 실제 추출 가능 범위를 확인한다.

## 2. 실행 환경

- 서버: `192.168.0.207`
- 작업 경로: `/data/weeslee/weeslee-rag`
- 입력 manifest:
  `data/staged/manifest/snapshot_2026-04-27_batch-001-top5-v2_20260427_130600.csv`

## 3. 사전 조치

1. 로컬 최신 커밋 `b223672`를 GitHub `origin/main`에 push
2. 서버 저장소를 `origin/main` 최신 상태로 sync
3. 서버 `.venv`에 추출 최소 의존성 설치
   - `pdfplumber`
   - `python-pptx`
   - `python-docx`
   - `openpyxl`
   - `httpx`
   - `aiohttp`
   - `python-dotenv`
   - `pydantic`
   - `pydantic-settings`

## 4. 1차 실행 결과

초기 실행 결과:

- `skipped_unsupported`: 4건
- `failed`: 18건

실패 원인:

- 추출 스크립트가 서버 snapshot 경로가 아니라 원본 `W:\01. 국내사업폴더\...` 경로를 직접 읽도록 되어 있었음
- 서버에는 `W:` 드라이브가 없으므로 모든 지원 포맷이 `File not found`로 실패함

## 5. 수정 사항

`backend/scripts/extract_manifest_batch.py`를 수정했다.

- manifest에 `snapshot_path`가 있으면 해당 경로를 우선 사용
- `snapshot_path`가 상대경로면 프로젝트 루트 기준 절대경로로 변환
- `snapshot_path`가 없거나 존재하지 않을 때만 `source_path` fallback 사용
- metadata에 실제 사용한 `input_path`와 `snapshot_path`를 함께 기록

## 6. 현재 판단

1차 배치 실패는 문서 자체 문제가 아니라 입력 경로 해석 문제다.
즉, snapshot 기준 재실행하면 `.pdf`, `.pptx`, `.docx`, `.xlsx`는 실제 추출 가능성 검증 단계로 넘어갈 수 있다.

## 7. 다음 작업

1. 수정된 추출 스크립트를 GitHub와 서버에 반영
2. 같은 manifest 22건으로 추출 배치 재실행
3. 성공/실패/unsupported 결과를 다시 집계
4. 성공 문서 기준 metadata 확인
5. 다음 단계로 chunking/FAISS 준비
