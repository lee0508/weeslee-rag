# 데이터셋 빌드 결과 분석 보고서

**작성일**: 2026-07-02
**대상 소스**: `src_20260702_085410_d993a0`
**스냅샷 ID**: `snapshot_20260701_src_20260702_085410_d993a0_V1`

---

## 1. 빌드 단계별 결과 요약

| 단계 | 항목 | 상태 | 수량/결과 | 비고 |
|------|------|------|-----------|------|
| Step 1 | 문서 소스 스캔 | ✅ 완료 | 249개 문서 | - |
| Step 5 | OCR/파싱 | ⚠️ 부분 완료 | 247 성공 / 2 실패 | 99.2% 성공률 |
| Step 3 | 메타데이터 추출 | ❌ 미실행 | 0개 | snapshot에 기록 안됨 |
| Step 4 | Tag/Keyword 생성 | ❌ 미실행 | 0개 | snapshot에 기록 안됨 |
| Step 6 | 청킹/임베딩 | ✅ 완료 | 10,031 청크/벡터 | ollama/nomic-embed-text |
| Step 7 | Knowledge Graph | ❌ 미실행 | 0 노드 / 0 엣지 | graph_build가 null |
| Step 8 | LLM Wiki | ✅ 완료 | 20개 문서 | claude-3-5-sonnet |
| Step 10 | FAISS 인덱스 | ✅ 완료 | 30.8MB 인덱스 | 활성화 대기 |

---

## 2. 발견된 문제점

### 2.1 OCR 실패 문서 (2건)

#### 문서 1: HWP 파일 추출 실패
- **파일명**: `RFP_소방출동 데이터 기반, AI빅데이터 분석시스템 구축 ISP.hwp`
- **Document ID**: 291
- **오류 메시지**: "모든 추출 방법 실패"
- **파서 타입**: `hwp_all_failed`
- **원인 분석**: HWP 파일이 손상되었거나 암호화되어 있을 가능성
- **조치 방안**: 원본 파일 확인 후 수동으로 PDF 변환하여 재처리

#### 문서 2: PPTX 텍스트 품질 부족
- **파일명**: `전략및방법론_휴·폐업 의료기관 진료기록보관시스템 구축.pptx`
- **Document ID**: 305
- **오류 메시지**: "Text quality too low: score=0.6, text_length=365"
- **파서 타입**: `python-pptx`
- **원인 분석**: 이미지 중심의 PPTX로 텍스트 내용이 365자에 불과
- **조치 방안**: OCR 처리를 통해 이미지 내 텍스트 추출 필요

---

### 2.2 Knowledge Graph 미생성

**현상**: `data/graph/` 디렉토리가 비어 있음

**스냅샷 기록**:
```json
"graph_build": {
    "graph_build_id": null,
    "ontology_id": null,
    "built_at": null,
    "node_count": 0,
    "edge_count": 0,
    "nodes_file": null,
    "edges_file": null,
    "summary_file": null
}
```

**원인 분석**:
1. Step 7 API가 실행되었으나 결과가 저장되지 않음
2. autoPipeline에서 Step 7이 실행되었으나 에러 발생 가능성
3. Graph 생성 로직이 snapshot 업데이트와 연동되지 않음

**조치 방안**:
1. Step 7 백엔드 API 로그 확인
2. `admin_dataset_builder_step7.py`의 결과 저장 로직 점검
3. snapshot 메타데이터 업데이트 로직 확인

---

### 2.3 메타데이터/Tag-Keyword 스냅샷 미반영

**현상**: Step 3, 4가 실행되었으나 스냅샷에 기록되지 않음

**스냅샷 기록**:
```json
"metadata_build": {
    "metadata_version_id": null,
    "built_at": null,
    "document_count": 0,
    "avg_confidence": null
},
"tag_keyword": {
    "tag_keyword_build_id": null,
    "built_at": null,
    "tag_count": 0,
    "keyword_count": 0,
    "output_path": null
}
```

**실제 데이터 존재 여부**:
- `data/tag_keyword/src_20260702_085410_d993a0/latest/` 디렉토리에 결과 파일 존재 가능성 있음
- 스냅샷 메타데이터에는 반영되지 않음

**원인 분석**:
- Step 3, 4 API가 스냅샷 메타데이터를 업데이트하지 않음
- autoPipeline 실행 후 snapshot 통합 저장 로직 필요

**조치 방안**:
1. Step 3, 4 완료 시 snapshot 메타데이터 업데이트 API 추가
2. 또는 Step 10 (FAISS 활성화) 시점에 모든 빌드 결과 수집하여 snapshot 갱신

---

### 2.4 Wiki build_info.json 누락

**현상**: `data/wiki/src_20260702_085410_d993a0/build_info.json` 파일이 없거나 손상됨

**실제 상태**:
- `projects/` 디렉토리에 20개의 마크다운 위키 문서 존재
- `index.json` 파일 없음 (JSON 파싱 오류)
- `build_info.json` 파일 없음

**스냅샷 기록**:
```json
"wiki_build": {
    "wiki_build_id": null,
    "built_at": null,
    "llm_model": "claude-3-5-sonnet",
    "article_count": 0,
    "total_tokens_used": 0,
    "output_dir": null
}
```

**원인 분석**:
- Step 8 API가 위키 문서는 생성했으나 메타데이터 파일 저장 실패
- snapshot 업데이트 로직이 wiki_build에 대해 누락

**조치 방안**:
1. Step 8 완료 시 `build_info.json` 및 `index.json` 생성 로직 확인
2. snapshot wiki_build 필드 업데이트 로직 추가

---

## 3. FAISS 인덱스 상세 정보

| 항목 | 값 |
|------|-----|
| 인덱스 파일 | `snapshot_20260701_src_20260702_085410_d993a0_V1_ollama.index` |
| 인덱스 크기 | 30,815,277 bytes (약 29.4MB) |
| 메타데이터 파일 | `snapshot_20260701_src_20260702_085410_d993a0_V1_ollama_metadata.jsonl` |
| 메타데이터 크기 | 31,679,453 bytes (약 30.2MB) |
| 임베딩 모델 | `ollama/nomic-embed-text` |
| 청크 수 | 10,031 |
| 벡터 수 | 10,031 |
| 청크 크기 | 512 토큰 |
| 청크 오버랩 | 50 토큰 |
| 활성화 상태 | `is_active: false` (대기 중) |

---

## 4. LLM Wiki 생성 문서 목록 (20건)

| 번호 | 프로젝트명 |
|------|-----------|
| 1 | AI 기반 지능형 진로교육정보망 |
| 2 | AX 활용 정보화전략계획수립 (서울주택도시개발공사) |
| 3 | AX기반의 차세대 업무 시스템 구축을 위한 ISMP |
| 4 | K-water 데이터허브 |
| 5 | K-water 데이터허브플랫폼 ISP |
| 6 | LH 스마트시티플랫폼 |
| 7 | 과기정통부 AI Next 고도화 ISP 수립 |
| 8 | 국토지리정보원 |
| 9 | 기재부 전자수입인지 기관선정연구 |
| 10 | 농정원 AgriX |
| 11 | 범죄예방정책 거대언어모델 도입활용방안 연구 |
| 12 | 법무부 디지털플랫폼 교육강화 환경개선 로드맵 연구사업 |
| 13 | 안양시청 |
| 14 | 양형기준 운영점검시스템 및 양형정보시스템의 고도화를 위한 AI시스템 구축 ISP |
| 15 | 자율주행차 성과평가 |
| 16 | 재난정신건강서비스 |
| 17 | 제3차 보건의료기술 종합정보시스템 중기 ISP 수립 |
| 18 | 차세대 국립병원 정보시스템 구축을 위한 BPR/ISP |
| 19 | 차세대 보건의료빅데이터개방시스템 구축을 위한 ISP |
| 20 | 통계청 통계지리정보서비스 ISP |

---

## 5. 권장 조치사항

### 즉시 조치 (우선순위 높음)

1. **Knowledge Graph 재실행**
   - Step 7 API를 수동으로 재실행
   - 결과가 `data/graph/` 디렉토리에 저장되는지 확인
   - snapshot 메타데이터 업데이트 확인

2. **실패 문서 재처리**
   - Document ID 291 (HWP): 원본 파일 상태 확인 후 PDF 변환 시도
   - Document ID 305 (PPTX): OCR 강제 실행 옵션으로 재처리

### 코드 수정 (우선순위 중간)

3. **Snapshot 메타데이터 통합 업데이트**
   - 각 Step 완료 시 snapshot 파일을 갱신하는 공통 함수 구현
   - 또는 Step 10 실행 시 모든 빌드 결과를 수집하여 snapshot 완성

4. **Wiki 메타데이터 생성 로직 보완**
   - `build_info.json` 생성 로직 추가
   - `index.json` 생성 로직 추가

### 모니터링 개선 (우선순위 낮음)

5. **빌드 결과 검증 API 추가**
   - 각 Step 완료 후 결과물 존재 여부 자동 검증
   - 누락된 결과물에 대한 경고 표시

---

## 6. 결론

현재 데이터셋 빌드는 **부분 성공** 상태입니다.

- **성공 항목**: 문서 스캔, OCR/파싱 (99.2%), 청킹/임베딩, LLM Wiki, FAISS 인덱스
- **실패/누락 항목**: Knowledge Graph, 메타데이터/Tag-Keyword 스냅샷 반영, Wiki 메타데이터

RAG 검색 기능은 FAISS 인덱스가 생성되어 기본적으로 동작 가능하나, Knowledge Graph 기반 연관 검색 기능은 사용할 수 없습니다. 스냅샷 메타데이터가 불완전하여 관리자 UI에서 빌드 상태를 정확히 파악하기 어렵습니다.
