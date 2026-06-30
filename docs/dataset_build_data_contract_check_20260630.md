# Dataset Builder 데이터 계약 점검 결과

**작성일:** 2026-06-30
**기준 문서:** `docs/2026-06-24_Codex_OCR_Metadata_Graph_Wiki_공통데이터계약_작업지시.md`
**점검 대상:** 서버 `/data/weeslee/weeslee-rag/data/` 실제 생성 데이터

---

## 1. 점검 요약

| 항목 | 상태 | 비고 |
|------|------|------|
| OCR/Parser 산출물 | ⚠️ 부분 충족 | 일부 필드 누락 |
| Metadata Store | ⚠️ 부분 충족 | scan/ocr/final 분리 안됨 |
| FAISS Payload | ⚠️ 부분 충족 | 핵심 필드 있음, 일부 누락 |
| Graph JSON | ⚠️ 부분 충족 | 노드/엣지 단순, 관계 제한적 |
| LLM Wiki | ❌ 미구현 | Wiki 데이터 없음 |

---

## 2. OCR/Parser 산출물 점검

### 2.1 실제 Metadata 파일 구조 (샘플: `metadata/1000.json`)

```json
{
  "document_id": "1000",
  "source_id": "src_20260623_001140_e030ed",
  "source_name": "01. 국내사업폴더",
  "category": "unknown",
  "document_group": "unknown",
  "document_category": "unknown",
  "source_path": "/mnt/w2_project/...",
  "input_path": "/mnt/w2_project/...",
  "extension": ".hwp",
  "project_name": "...",
  "project_confidence": 0.45,
  "organization": "",
  "organization_confidence": 0.55,
  "folder_year": "2016",
  "extraction_method": "hwp5txt",
  "is_scanned": false,
  "content_length": 193,
  "page_count": 0,
  "result": {
    "success": true,
    "content": "...",
    "metadata": { "quality": {...} }
  }
}
```

### 2.2 공통 데이터 계약 대비 필드 현황

| 계약 필드 | 현재 상태 | 비고 |
|-----------|----------|------|
| source_id | ✅ 있음 | |
| dataset_id | ❌ 없음 | **누락** |
| snapshot_id | ❌ 없음 | **누락** |
| document_id | ✅ 있음 | |
| section_id | ❌ 없음 | **누락** |
| chunk_id | ✅ 있음 (chunk에서) | |
| file_path | ✅ 있음 (source_path) | |
| file_name | ✅ 있음 | |
| file_type | ❌ 없음 (extension만 있음) | |
| page_no | ⚠️ 부분 | PDF에서만 |
| slide_no | ⚠️ 부분 | PPTX에서만 |
| section_title | ❌ 없음 | **누락** |
| heading_path | ❌ 없음 | **누락** |
| document_group | ✅ 있음 | 대부분 "unknown" |
| document_category | ✅ 있음 | 대부분 "unknown" |
| project_name | ✅ 있음 | |
| organization | ⚠️ 있음 | 대부분 빈값 |
| organization_type | ❌ 없음 | **누락** |
| business_domain | ❌ 없음 | **누락** |
| topic | ❌ 없음 | **누락** |
| requirement | ❌ 없음 | **누락** |
| technology | ❌ 없음 | **누락** |
| methodology | ❌ 없음 | **누락** |
| keyword | ❌ 없음 | **누락** |

### 2.3 Metadata 3단계 분리 현황

| 계층 | 계약 정의 | 현재 상태 |
|------|----------|----------|
| scan_metadata | 파일명/폴더명 추정값 | ❌ 분리 안됨 |
| ocr_metadata | OCR/Parser 추출값 | ❌ 분리 안됨 |
| final_metadata | 관리자 확정값 | ❌ 분리 안됨 |

**현재:** 모든 값이 하나의 JSON에 혼합 저장됨.

---

## 3. FAISS Metadata Payload 점검

### 3.1 실제 FAISS Metadata 구조 (샘플)

```json
{
  "chunk_id": "114524-chunk-0000",
  "document_id": "114524",
  "source_id": "src_20260629_065409_0f767a",
  "category": "제안서",
  "section_heading": "",
  "source_path": "/mnt/w2_project/...",
  "input_path": "/mnt/w2_project/...",
  "organization": "",
  "document_category": "전략및방법론",
  "document_group": "제안서",
  "project_name": "AI 기반 지능형 진로교육정보망...",
  "page_no": 1,
  "slide_no": 1,
  "start_char": 0,
  "total_pages": 1,
  "metadata": { /* 중첩된 전체 metadata */ }
}
```

### 3.2 공통 데이터 계약 대비 FAISS Payload 현황

| 계약 필드 | 현재 상태 | 비고 |
|-----------|----------|------|
| source_id | ✅ 있음 | |
| dataset_id | ❌ 없음 | **누락** |
| snapshot_id | ❌ 없음 | **누락** |
| document_id | ✅ 있음 | |
| section_id | ❌ 없음 | **누락** |
| chunk_id | ✅ 있음 | |
| file_path | ✅ 있음 | |
| file_name | ✅ 있음 | |
| page_no | ✅ 있음 | |
| slide_no | ✅ 있음 | |
| section_title | ❌ 없음 | section_heading만 (빈값) |
| document_group | ✅ 있음 | |
| document_category | ✅ 있음 | |
| project_name | ✅ 있음 | |
| organization | ⚠️ 있음 | 대부분 빈값 |
| organization_type | ❌ 없음 | **누락** |
| topic | ❌ 없음 | **누락** |
| requirement | ❌ 없음 | **누락** |
| keyword | ❌ 없음 | **누락** |

---

## 4. Graph JSON 점검

### 4.1 현재 Graph 노드 타입

| 노드 타입 | 계약 정의 | 현재 상태 | 비고 |
|-----------|----------|----------|------|
| Project | ✅ 필수 | ✅ 있음 | |
| Organization | ✅ 필수 | ❌ 없음 | **누락** |
| OrganizationType | ✅ 필수 | ❌ 없음 | **누락** |
| BusinessDomain | ✅ 필수 | ❌ 없음 | **누락** |
| Document | ✅ 필수 | ✅ 있음 | |
| DocumentSection | ✅ 필수 | ❌ 없음 | **누락** |
| Requirement | ✅ 필수 | ❌ 없음 | **누락** |
| Topic | ✅ 필수 | ❌ 없음 | **누락** |
| Technology | ✅ 필수 | ❌ 없음 | **누락** |
| Methodology | ✅ 필수 | ❌ 없음 | **누락** |
| Keyword | ✅ 필수 | ❌ 없음 | **누락** |
| DeliverableType | ✅ 필수 | ❌ 없음 | **누락** |
| Summary | ✅ 필수 | ❌ 없음 | **누락** |
| Category | ❌ 미정의 | ✅ 있음 | 추가됨 (rfp/proposal/deliverable) |

### 4.2 현재 Graph 엣지 타입

| 엣지 타입 | 계약 정의 | 현재 상태 | 비고 |
|-----------|----------|----------|------|
| has_document | ✅ 필수 | ✅ 있음 | Project → Document |
| ORDERED_BY | ✅ 필수 | ❌ 없음 | Project → Organization |
| HAS_TYPE | ✅ 필수 | ❌ 없음 | Organization → OrganizationType |
| HAS_DOMAIN | ✅ 필수 | ❌ 없음 | Project → BusinessDomain |
| HAS_SECTION | ✅ 필수 | ❌ 없음 | Document → DocumentSection |
| MENTIONS | ✅ 필수 | ❌ 없음 | Chunk → Topic/Requirement |
| HAS_KEYWORD | ✅ 필수 | ❌ 없음 | Chunk → Keyword |
| HAS_SUMMARY | ✅ 필수 | ❌ 없음 | Document/Section → Summary |

### 4.3 현재 Graph 구조 요약

```
현재:
  Category (rfp/proposal/deliverable)
  Project ─── has_document ──→ Document

계약 요구:
  Project ─── ORDERED_BY ──→ Organization ─── HAS_TYPE ──→ OrganizationType
      │
      ├── HAS_DOMAIN ──→ BusinessDomain
      │
      └── HAS_DOCUMENT ──→ Document ─── HAS_SECTION ──→ DocumentSection
                                │                            │
                                └── HAS_SUMMARY ──→ Summary   └── HAS_CHUNK ──→ Chunk
                                                                        │
                                                                        ├── MENTIONS ──→ Topic
                                                                        ├── MENTIONS ──→ Requirement
                                                                        └── HAS_KEYWORD ──→ Keyword
```

---

## 5. LLM Wiki 점검

| 항목 | 계약 정의 | 현재 상태 |
|------|----------|----------|
| Wiki 페이지 생성 | 필수 | ❌ 미구현 |
| document_summary | 필수 | ❌ 없음 |
| section_summary | 필수 | ❌ 없음 |
| chunk_summary | 필수 | ❌ 없음 |
| 프로젝트별 요약 | 필수 | ❌ 없음 |
| 기관별 프로필 | 필수 | ❌ 없음 |
| 기술별 사용 사례 | 필수 | ❌ 없음 |

**결과:** LLM Wiki 기능은 전혀 구현되어 있지 않음.

---

## 6. OCR 처리 시간 분석

### 6.1 실제 추출 방식 분포

| 추출 방식 | 설명 | OCR 여부 |
|-----------|------|----------|
| hwp5txt | HWP 직접 추출 | ❌ No |
| python-pptx | PPTX 직접 추출 | ❌ No |
| pdfplumber | PDF 텍스트 추출 | ❌ No |
| tesseract | PDF OCR | ✅ Yes |
| easyocr | PDF/이미지 OCR | ✅ Yes |

### 6.2 처리 시간이 짧은 이유

메타데이터 샘플 분석 결과:
- `extraction_method: "hwp5txt"` - HWP 직접 추출 (OCR 없음)
- `extraction_method: "python-pptx"` - PPTX 직접 추출 (OCR 없음)
- `is_scanned: false` - 대부분 스캔 PDF가 아님

**결론:** 250개 파일 중 대부분이 텍스트 기반 문서라서 OCR이 실행되지 않음. 몇 초 만에 완료된 것은 정상.

### 6.3 실제 OCR이 필요한 경우

- `is_scanned: true`인 PDF 파일
- 이미지 내 텍스트 추출 필요 시
- CID 폰트 인코딩 문제가 있는 PDF

---

## 7. 우선순위별 개선 필요 사항

### P0. 즉시 필요 (검색 품질 직결)

1. **dataset_id, snapshot_id 연결**
   - 모든 산출물에 일관된 ID 체계 적용

2. **organization 필드 채우기**
   - 폴더명/파일명에서 기관명 추출 로직 개선
   - 예: "한국수자원공사 ISP" → organization: "한국수자원공사"

3. **section_title / section_id 추출**
   - PPTX: 슬라이드 제목 추출
   - PDF: 목차/헤딩 추출
   - HWP: 문단 스타일 기반 섹션 추출

### P1. 단기 필요 (1~2주)

1. **Metadata 3단계 분리**
   - scan_metadata: 경로 기반 추정값
   - ocr_metadata: 추출 결과값
   - final_metadata: 관리자 확정값

2. **Graph 노드 확장**
   - Organization, OrganizationType 노드 추가
   - Topic, Requirement 노드 추가 (정규식 기반 추출)

3. **Graph 엣지 확장**
   - ORDERED_BY, HAS_DOMAIN 관계 추가
   - MENTIONS, HAS_KEYWORD 관계 추가

### P2. 중기 필요 (2~4주)

1. **LLM Wiki 구현**
   - document_summary 생성
   - section_summary 생성
   - 프로젝트/기관별 요약 페이지

2. **Topic/Requirement 자동 추출**
   - 정규식 + 사전 기반 1차 추출
   - LLM 보정 (선택적)

3. **Hybrid Search 응답 스키마**
   - Graph + FAISS + Wiki 통합 응답 구조

---

## 8. 완료 기준 대비 현재 상태

| 완료 기준 | 현재 상태 |
|-----------|----------|
| ① page_no/slide_no 확인 가능 | ✅ 충족 |
| ② Chunk가 document_id, source_id와 연결 | ⚠️ 부분 (dataset_id, snapshot_id 누락) |
| ③ FAISS에서 파일/페이지/섹션 복원 가능 | ⚠️ 부분 (section 누락) |
| ④ Graph에서 Project-Org-Doc-Section 관계 확인 | ❌ 미충족 (Org, Section 노드 없음) |
| ⑤ Wiki가 동일 source/dataset/snapshot 기준 | ❌ 미충족 (Wiki 미구현) |
| ⑥ admin에서 Graph+FAISS+Wiki 경로 확인 | ❌ 미충족 |
| ⑦ rag-assistant에서 근거 묶음 표시 | ⚠️ 부분 |

---

## 9. 권장 작업 순서

```
1. dataset_id, snapshot_id를 모든 산출물에 추가
2. organization 추출 로직 개선 (폴더명/파일명 파싱)
3. section_title 추출 로직 추가 (PPTX 슬라이드 제목 등)
4. Metadata 3단계 분리 구조 적용
5. Graph 노드 확장 (Organization, Topic, Requirement)
6. Graph 엣지 확장 (ORDERED_BY, MENTIONS 등)
7. LLM Wiki Builder 구현
8. Hybrid Search 응답 스키마 구현
9. Q1~Q7 테스트 질문 검증
```
