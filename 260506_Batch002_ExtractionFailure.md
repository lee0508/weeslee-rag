# Batch-002 추출 실패 분석

**날짜**: 2026-05-06  
**스냅샷**: `snapshot_2026-05-06_batch-002-top10-v1`  
**전체**: 32건 처리 → 27 성공 / 4 실패 / 1 스킵

---

## 실패 4건 요약

| DOC_ID | 파일명 | 카테고리 | 프로젝트 폴더 | 크기 | 원인 |
|--------|--------|----------|--------------|------|------|
| DOC-20260506-000005 | 221007_최종보고회_발표자료_국가통합물관리정보플랫폼_배포용(230407131042).pdf | presentation | 202212. k-water 데이터허브플랫폼_ISP | 14.7 MB | 스캔 PDF — 텍스트 레이어 없음 |
| DOC-20260506-000038 | 착수보고_v0.4_최종.pdf | kickoff | 202403. 기재부_전자수입인지 기관선정연구 | 4.0 MB | 스캔 PDF — 텍스트 레이어 없음 |
| DOC-20260506-000045 | 투이컨소시엄_서울주택도시공사_AX_ISP_발표본.pdf | presentation | 202503. AX 활용 정보화전략계획수립_서울주택도시개발공사 | 7.6 MB | 스캔 PDF — 텍스트 레이어 없음 |
| DOC-20260506-000048 | (최종제출)착수계.pdf | kickoff | 191. 제3차 보건의료기술 종합정보시스템 중기 isp 수립 | 0.9 MB | 스캔 PDF — 텍스트 레이어 없음 |

## 스킵 1건 (Phase 1 미지원)

| DOC_ID | 파일명 | 카테고리 | 프로젝트 폴더 | 크기 | 사유 |
|--------|--------|----------|--------------|------|------|
| DOC-20260506-000007 | 제안서 협상결과 통보서_00 (1).hwpx | proposal | 202603. AX기반의 차세대 업무 시스템 구축을 위한 ISMP | 0.1 MB | .hwpx — Phase 2 대상 |

---

## 공통 원인 분석

### 실패 원인: `PDF appears to be scanned but OCR is disabled`

모든 실패 파일이 **이미지 기반 스캔 PDF**입니다.

- pdfplumber로 읽으면 텍스트 레이어가 비어 있음
- `DocumentExtractor`가 빈 텍스트를 감지하여 "scanned" 판정
- `--use-ocr` 플래그 없이 실행되어 OCR 단계로 넘어가지 않음

### HWPX 스킵 원인

Phase 1 지원 포맷: `.pdf`, `.pptx`, `.docx`, `.xlsx`  
`.hwpx`는 `UNSUPPORTED_FOR_PHASE1`로 분류 → Phase 2 처리 예정

---

## 해결 방안

### 방안 A: OCR 재처리 (단기, 권장)

스캔 PDF 4건만 OCR 플래그로 재실행:

```bash
cd /data/weeslee/weeslee-rag/backend
.venv/bin/python3 scripts/extract_manifest_batch.py \
  --manifest-csv data/staged/manifest/snapshot_2026-05-06_batch-002-top10-v1_ocr_only.csv \
  --text-dir data/staged/text \
  --metadata-dir data/staged/metadata \
  --use-ocr
```

대상 4건만 담은 별도 CSV를 만들어 실행.  
완료 후 `build_chunk_batch.py` → `build_faiss_index.py` 재실행 (전체 or 증분).

**필요 의존성**: 서버에 `tesseract-ocr` + `pytesseract` 설치 여부 확인 필요.

### 방안 B: 해당 문서 교체 (중기)

원본 파일 중 텍스트 레이어가 있는 버전으로 교체 후 재처리.  
예: 발표자료 PPTX 원본, 또는 텍스트 PDF 재출력본.

### 방안 C: HWPX 추출기 적용 (Phase 2)

`validate_hwpx_pipeline.py`에 구현된 HWPX 추출기를 Phase 2에서 활성화.  
대상 1건: `제안서 협상결과 통보서_00 (1).hwpx`

---

## 영향 평가

| 항목 | 현재 | OCR 성공 시 |
|------|------|-------------|
| 인덱싱 문서 수 | 27 | 31 |
| FAISS 벡터 수 | 2,054 | 약 +200~400 예상 |
| 미포함 카테고리 비율 | presentation 2건 / kickoff 2건 누락 | 완전 커버 |

4건 모두 **presentation** 또는 **kickoff** 카테고리로, 해당 카테고리 쿼리의 검색 품질에 영향.

---

## 다음 단계

- [ ] 서버 OCR 의존성 확인: `tesseract --version`
- [ ] 스캔 PDF 4건 OCR 재처리용 mini-manifest CSV 생성
- [ ] OCR 완료 후 FAISS 증분 업데이트 또는 전체 재빌드
- [ ] `.hwpx` Phase 2 처리 일정 수립
