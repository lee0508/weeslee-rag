# 위즐리앤컴퍼니 문서 복사 실행 런북

**작성일:** 2026-04-27  
**목적:** `W:\01. 국내사업폴더` 원본을 훼손하지 않고 1차 개발용 snapshot을 준비하기 위한 실행 절차

---

## 1. 전제

1. 원본은 `W:\01. 국내사업폴더`
2. 서버 대상 경로는 `/data/weeslee/weeslee-rag/data/raw`
3. 현재 서버 기본 `data/` 구조는 생성 완료
4. 현재 Codex 작업 세션에서는 `W:` 드라이브가 보이지 않음

즉, 실제 복사는 `W:`에 접근 가능한 윈도우 PC 또는 서버에서 접근 가능한 중간 공유 경로를 통해 실행해야 한다.

---

## 2. 권장 1차 복사 단위

초기에는 전체가 아니라 표본 위주로 진행한다.

1. 기관 3~5곳
2. 연도 2~3개 구간
3. 문서유형 4~5종
4. 총량 300~500건

권장 우선순위:

1. RFP/과업지시서
2. 제안서
3. 착수보고서
4. 최종보고서
5. 발표자료

---

## 3. 실행 순서

### 3.1 표본 폴더 선정

1. 원본에서 대표 폴더 선정
2. 대상 목록을 엑셀 또는 CSV로 정리
3. 중복/임시/개인 보관 폴더는 제외

### 3.2 dry-run manifest 생성

`backend/scripts/prepare_snapshot_manifest.py`를 먼저 dry-run으로 실행한다.

예:

```powershell
python backend/scripts/prepare_snapshot_manifest.py `
  --source "W:\01. 국내사업폴더" `
  --snapshot-name "snapshot_2026-04-27" `
  --output-dir "data/staged/manifest" `
  --limit 300 `
  --batch-id "batch-001"
```

### 3.3 결과 검토

검토 항목:

1. 문서 수량
2. 기관/연도/유형 분포
3. 확장자 분포
4. 지나치게 큰 파일 여부
5. 제외해야 할 개인/임시 파일 여부

### 3.4 실제 복사

복사가 필요한 경우에만 `--copy`와 `--copy-dest`를 사용한다.

예:

```powershell
python backend/scripts/prepare_snapshot_manifest.py `
  --source "W:\01. 국내사업폴더" `
  --snapshot-name "snapshot_2026-04-27" `
  --output-dir "data/staged/manifest" `
  --copy `
  --copy-dest "\\192.168.0.207\projects\weeslee-rag\data\raw" `
  --limit 300 `
  --batch-id "batch-001"
```

주의:

1. 위 UNC 경로는 실제 서버 공유 구조에 맞게 다시 검증해야 한다.
2. 원본 경로를 직접 이동하거나 삭제하지 않는다.
3. 복사 로그와 manifest를 함께 보관한다.

---

## 4. 복사 후 확인

1. snapshot 디렉터리 생성 여부
2. manifest JSONL/CSV 생성 여부
3. 파일 수량 일치 여부
4. 해시 계산 완료 여부
5. 샘플 문서 10건 수동 열람 여부

---

## 5. 다음 단계

복사 완료 후 다음 순서로 진행한다.

1. 텍스트 추출
2. OCR fallback
3. 메타데이터 추출
4. 정규화 Markdown 생성
5. 청킹
6. FAISS 인덱싱
7. 그래프 생성
8. 위키 생성

