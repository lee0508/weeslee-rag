# QA 소스 기능 분석 및 반영 여부 체크

**작성일:** 2026-06-30
**분석 대상:** QA1, QA8, QA9, QA10 폴더
**비교 대상:** weeslee-rag 현재 코드베이스

---

## 1. QA 폴더별 기능 요약

### QA1 - OCR 레이어 (Layer 1)
| 파일 | 기능 | 설명 |
|------|------|------|
| `ocr_engines.py` | OCR 엔진 어댑터 | PaddleOCR, CLOVA OCR, Tesseract 지원, 팩토리 패턴 |
| `region_detector.py` | 영역 검출 | HEADER/IMAGE/TABLE/TEXT/SEPARATOR/WHITESPACE 분류 |
| `extractor.py` | 문서 추출 통합 | PDF(벡터/이미지), HWP/HWPX, Office 형식 지원 |
| `doc_type_router.py` | 문서 타입 판별 | 확장자 및 내용 기반 라우팅 |
| `normalizer.py` | 텍스트 정규화 | 추출된 텍스트 후처리 |
| `source_manager.py` | 소스 관리 | 문서 소스 폴더 관리 |
| `run_ocr_layer.py` | 실행 진입점 | OCR 레이어 CLI 실행 |

### QA8 - FAISS 파이프라인 (수정본)
| 파일 | 기능 | 설명 |
|------|------|------|
| `faiss_job_runner_fixed.py` | 파이프라인 러너 | 6단계 파이프라인 실행, activate_snapshot 수정 |
| `rag_runtime_patched.py` | RAG 런타임 | 캐시 무효화, 스냅샷 활성화 개선 |
| `fix_suite.py` | 수정 스위트 | 여러 수정사항 통합 적용 |

### QA9 - FAISS 검색 및 스냅샷 (수정본)
| 파일 | 기능 | 설명 |
|------|------|------|
| `faiss_search_service_fixed.py` | FAISS 검색 | active_snapshot 읽기 순서 통일, 캐시 무효화 |
| `activate_snapshot_final.py` | 스냅샷 활성화 | 원자적 쓰기, 파일 검증 |
| `p0_contract.py` | P0 계약 정리 | 핵심 계약 정의 |

### QA10 - GraphRAG Agent (수정본)
| 파일 | 기능 | 설명 |
|------|------|------|
| `graphrag_agent_fixed.py` | GraphRAG Agent | 캐시 무효화 함수 추가, FAISS fallback |
| `faiss_job_runner_fixed.py` | 파이프라인 러너 | QA8과 동일 |
| `faiss_search_service_fixed.py` | FAISS 검색 | QA9와 동일 |
| `rag_runtime_patched.py` | RAG 런타임 | QA8과 동일 |
| `activate_snapshot_final.py` | 스냅샷 활성화 | QA9와 동일 |

---

## 2. 현재 weeslee-rag 코드 분석

### 2.1 OCR/추출 관련 파일

| 경로 | 기능 | QA1 대응 |
|------|------|----------|
| `backend/app/extractors/pdf_extractor.py` | PDF 추출 + OCR | ✅ 유사 기능 구현됨 |
| `backend/app/extractors/hwp_extractor.py` | HWP 추출 | ✅ 구현됨 |
| `backend/app/extractors/hwpx_extractor.py` | HWPX 추출 | ✅ 구현됨 |
| `backend/app/extractors/docx_extractor.py` | DOCX 추출 | ✅ 구현됨 |
| `backend/app/extractors/xlsx_extractor.py` | XLSX 추출 | ✅ 구현됨 |
| `backend/app/extractors/pptx_extractor.py` | PPTX 추출 | ✅ 구현됨 |
| `backend/app/services/ocr.py` | olmOCR 서비스 | ⚠️ 다른 방식 (olmOCR 사용) |

### 2.2 FAISS/RAG 관련 파일

| 경로 | 기능 | QA8/9/10 대응 |
|------|------|---------------|
| `backend/app/services/faiss_job_runner.py` | 파이프라인 러너 | ✅ 반영됨 |
| `backend/app/services/faiss_search_service.py` | FAISS 검색 | ✅ 반영됨 |
| `backend/app/agents/graphrag_agent.py` | GraphRAG Agent | ✅ 반영됨 |

---

## 3. 반영 여부 상세 비교

### 3.1 OCR 기능 (QA1 vs 현재)

#### 현재 구현 방식 (`pdf_extractor.py`)

```
추출 순서:
1. pdfplumber로 텍스트 직접 추출 시도
2. CID 인코딩 문제 감지
3. EasyOCR 우선 시도 (ko+en, GPU 지원)
4. Tesseract fallback
```

#### QA1 설계 방식

```
추출 순서:
1. 문서 타입 판별 (PDF_VECTOR/PDF_IMAGE/HWP/OFFICE)
2. PDF_IMAGE: 영역 검출 (HEADER/TABLE/TEXT)
3. 영역별 OCR 수행 (읽기 순서 보장)
4. PaddleOCR/CLOVA OCR/Tesseract 선택 가능
```

#### 차이점 분석

| 기능 | QA1 | 현재 | 상태 |
|------|-----|------|------|
| 영역 검출 (Region Detection) | ✅ | ❌ | **미반영** |
| 표 영역 분리 ([TABLE] 마커) | ✅ | ❌ | **미반영** |
| 읽기 순서 보장 | ✅ | ❌ | **미반영** |
| PaddleOCR 지원 | ✅ | ❌ | **미반영** |
| CLOVA OCR 지원 | ✅ | ❌ | **미반영** |
| EasyOCR 지원 | ✅ | ✅ | 반영됨 |
| Tesseract 지원 | ✅ | ✅ | 반영됨 |
| CID 폰트 감지 | ❌ | ✅ | 현재가 추가됨 |
| olmOCR 지원 | ❌ | ✅ | 현재가 추가됨 |

### 3.2 FAISS 파이프라인 (QA8 vs 현재)

| 기능 | QA8 | 현재 | 상태 |
|------|-----|------|------|
| 6단계 파이프라인 | ✅ | ✅ | 반영됨 |
| activate_snapshot 원자적 쓰기 | ✅ | ✅ | 반영됨 |
| FAISS 파일 사전 검증 | ✅ | ✅ | 반영됨 |
| rag_runtime 캐시 무효화 | ✅ | ✅ | 반영됨 |

### 3.3 FAISS 검색 서비스 (QA9 vs 현재)

| 기능 | QA9 | 현재 | 상태 |
|------|-----|------|------|
| active_snapshot 우선 읽기 | ✅ | ✅ | 반영됨 |
| invalidate_faiss_search_cache | ✅ | ✅ | 반영됨 |
| hashing_embedding | ✅ | ✅ | 반영됨 |
| ollama_embedding | ✅ | ✅ | 반영됨 |

### 3.4 GraphRAG Agent (QA10 vs 현재)

| 기능 | QA10 | 현재 | 상태 |
|------|------|------|------|
| 질문 유형 분석 | ✅ | ✅ | 반영됨 |
| Cypher 생성/검증 | ✅ | ✅ | 반영됨 |
| 자동 수정 루프 | ✅ | ✅ | 반영됨 |
| FAISS fallback | ✅ | ✅ | 반영됨 |
| invalidate_graphrag_cache | ✅ | ✅ | 반영됨 |

---

## 4. 반영 현황 요약

### 반영됨 (✅)

1. **QA8 - faiss_job_runner_fixed.py**
   - 6단계 파이프라인 구조
   - activate_snapshot 원자적 쓰기
   - 캐시 무효화 연동

2. **QA9 - faiss_search_service_fixed.py**
   - active_snapshot 읽기 순서 통일
   - 캐시 무효화 함수

3. **QA10 - graphrag_agent_fixed.py**
   - GraphRAG Agent 전체 구조
   - 자동 수정 루프
   - FAISS fallback

### 미반영 (❌) - QA1 OCR 고급 기능

1. **영역 검출 (Region Detection)**
   - HEADER/TABLE/TEXT/IMAGE 자동 분류
   - 페이지 내 구조 분석

2. **표 영역 분리**
   - [TABLE]...[/TABLE] 마커로 표 영역 구분
   - 후처리에서 표 데이터 별도 처리 가능

3. **읽기 순서 보장**
   - 영역 검출 후 order 기반 정렬
   - 자연스러운 문서 흐름 유지

4. **PaddleOCR 지원**
   - 온프레미스/망분리 환경용
   - GPU 활용, 한국어 최적화

5. **CLOVA OCR 지원**
   - Naver API 연동
   - 한국어 정확도 최상

---

## 5. 권장 사항

### 5.1 즉시 반영 권장 (우선순위 높음)

| 기능 | 이유 | 난이도 |
|------|------|--------|
| 영역 검출 | 표/이미지 텍스트 품질 향상 | 중 |
| 표 영역 마커 | 청크 분리 시 표 데이터 보존 | 하 |

### 5.2 선택적 반영 (필요시)

| 기능 | 이유 | 난이도 |
|------|------|--------|
| PaddleOCR | 망분리 환경, GPU 서버 필요 | 중 |
| CLOVA OCR | API 비용 발생, 한국어 최상 품질 | 하 |
| 읽기 순서 | 복잡한 레이아웃 문서에서 유용 | 중 |

### 5.3 현재 유지 권장

| 기능 | 이유 |
|------|------|
| EasyOCR + Tesseract | 범용성 좋음, 무료 |
| olmOCR | 마크다운 출력 지원 |
| CID 폰트 감지 | 깨진 텍스트 사전 방지 |

---

## 6. OCR 처리 시간 이슈

### 현재 상황
- 250개 파일 OCR 처리 시간: **몇 초** (비정상적으로 빠름)

### 예상 원인
1. **OCR이 실제로 실행되지 않음**
   - pdfplumber로 텍스트 추출 성공 (OCR 스킵)
   - 대부분이 텍스트 기반 PDF

2. **이미 처리된 캐시 사용**
   - 이전 빌드 결과 재사용

3. **실패한 파일 건너뜀**
   - 오류 발생 시 빈 텍스트로 처리

### 확인 방법
```bash
# 추출 로그에서 OCR 메서드 확인
grep -r "method.*ocr" data/staged/*/extract_*.json
grep -r "is_scanned.*true" data/staged/*/extract_*.json
```

### 정상 처리 시간 기준
| 파일 수 | pdfplumber만 | OCR 포함 |
|---------|--------------|----------|
| 250개 | 30초 ~ 2분 | 10분 ~ 30분 |

---

## 7. 결론

### QA8, QA9, QA10
- **대부분 반영됨** (FAISS 파이프라인, 검색, GraphRAG Agent)
- P0 계약 정리 수정 사항 적용 완료

### QA1 (OCR 레이어)
- **부분 반영** (EasyOCR, Tesseract만 사용)
- 영역 검출, 표 분리, PaddleOCR, CLOVA OCR **미반영**
- 현재는 단순 OCR 방식으로 동작

### OCR 처리 시간
- 몇 초 완료는 **OCR이 실행되지 않았을 가능성** 높음
- 텍스트 기반 PDF가 대부분이거나 캐시 사용 중
- 로그 확인 필요
