# 위즐리앤컴퍼니 상위 5개 대표 파일 Dry-Run 결과

**작성일:** 2026-04-27  
**입력 파일:** `data/staged/manifest/phase1_representative_docs_top5.csv`  
**결과 파일:**  
- `data/staged/manifest/snapshot_2026-04-27_batch-001-top5_20260427_130019.csv`  
- `data/staged/manifest/snapshot_2026-04-27_batch-001-top5_20260427_130019.jsonl`

---

## 1. 결과 요약

상위 5개 프로젝트 대표 파일 목록을 기준으로 dry-run manifest를 생성했다.

### 집계

1. 입력 대표 파일 목록 기준 `selected` 대상: `22건`
2. `manual_review` 제외 건수: `2건`
3. manifest 생성 상태: `planned`
4. snapshot 복사 수행 여부: `미수행`

---

## 2. 의미

이 결과는 실제 snapshot 복사 전에 다음을 검증한 상태다.

1. 원본 파일 경로 확인
2. 상대경로 계산 확인
3. snapshot 저장 경로 계산 확인
4. 파일 해시 계산 확인
5. 복사 배치 입력 데이터 준비 완료

---

## 3. 현재 바로 가능한 다음 작업

1. `manual_review` 4건 보완
2. 현재 manifest 기준으로 실제 snapshot 복사 실행
3. 동일 방식으로 상위 6~10위 프로젝트 확장
4. 이후 OCR/추출/메타데이터 파이프라인 적용

---

## 4. 비고

초기에는 네트워크 저장소의 대규모 재귀 스캔이 느려 자동 대표 파일 선정이 비효율적이었다.  
그래서 `후보 프로젝트 선정 -> 대표 폴더 확정 -> 대표 파일 수동 보정 -> dry-run manifest 생성` 순서로 전략을 조정했고, 이는 1차 PoC 목표와 일치한다.
