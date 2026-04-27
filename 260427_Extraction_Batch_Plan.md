# 위즐리앤컴퍼니 1차 추출 배치 계획

**작성일:** 2026-04-27  
**대상 manifest:** `snapshot_2026-04-27_batch-001-top5-v2_20260427_130600.csv`

---

## 1. 목적

상위 5개 프로젝트 대표 파일 22건에 대해 서버 `/data/weeslee/weeslee-rag` 기준으로 실제 텍스트 추출 배치를 실행한다.

---

## 2. 현재 환경 상태

서버 확인 결과:

1. Python 3.12 사용 가능
2. 프로젝트 가상환경 없음
3. `pdfplumber`, `python-pptx`, `python-docx`, `openpyxl` 미설치
4. `olmocr` 미설치

즉, 추출 배치 실행 전에 최소 라이브러리 설치가 필요하다.

---

## 3. 1차 배치 정책

### 지원 포맷

1. `.pdf`
2. `.pptx`
3. `.docx`
4. `.xlsx`

### 1차 제외 포맷

1. `.hwp`
2. `.hwpx`
3. `.doc`
4. `.ppt`
5. `.xls`

제외 포맷은 `skipped_unsupported` 상태로 기록하고, 2차에 별도 HWP/HWPX 처리 경로를 설계한다.

---

## 4. 배치 산출물

1. `data/staged/text/<document_id>.txt`
2. `data/staged/metadata/<document_id>.json`
3. `data/staged/manifest/<manifest_stem>_extraction_summary.csv`

---

## 5. 다음 실행 순서

1. 서버 가상환경 생성
2. 추출 필수 라이브러리 설치
3. `extract_manifest_batch.py` 동기화
4. 22건 배치 추출 실행
5. 성공/실패/unsupported 집계 확인

