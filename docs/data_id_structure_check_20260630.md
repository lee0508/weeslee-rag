# 데이터 ID 구조 구현 상태 점검 결과

**작성일:** 2026-06-30
**점검 대상:** Dataset Builder 파이프라인 전 단계

---

## 1. ID 구조 요약

| ID 유형 | 설명 | 생성 단계 | 전파 여부 |
|---------|------|----------|----------|
| source_id | Document Source 고유 식별자 | Source 등록 | ✅ 모든 단계 |
| dataset_id | 데이터셋 빌드 세션 식별자 | Source 등록/ensure-dataset | ⚠️ 부분 (active_index만) |
| snapshot_id | FAISS 빌드 스냅샷 식별자 | FAISS 빌드 시 | ⚠️ 부분 (파일명/active_index) |
| document_id | 파일 1개 고유 내부 ID | Scan 단계 | ✅ 모든 단계 |
| document_uid | source_id+relative_path 해시 | Scan 단계 | ⚠️ DB만 (파일 미전파) |
| relative_path | 소스 루트 기준 상대 경로 | Manifest 생성 | ⚠️ Manifest만 |

---

## 2. 단계별 ID 구현 현황

### 2.1 Stage 1: Manifest 생성

**파일:** `data/staged/manifest/*_manifest.csv`

| 필드 | 구현 상태 | 실제 값 예시 |
|------|----------|-------------|
| document_id | ✅ 구현됨 | `114477` |
| source_id | ✅ 구현됨 | `src_20260630_073459_3f4491` |
| relative_path | ✅ 구현됨 | `01. RFP/RFP_축산유통 데이터랩 고도화.hwp` |
| document_group | ✅ 구현됨 | `RFP`, `제안서`, `산출물` |
| document_category | ✅ 구현됨 | `rfp`, `전략및방법론`, `기술및기능` |
| proposal_section | ✅ 구현됨 | 제안서 하위 폴더 |
| deliverable_section | ✅ 구현됨 | 산출물 하위 폴더 |
| dataset_id | ❌ 미구현 | - |
| snapshot_id | ❌ 미구현 | - |
| document_uid | ❌ 미구현 | - |

### 2.2 Stage 2: Extract (OCR/Parser)

**파일:** `data/staged/metadata/*.json`

| 필드 | 구현 상태 | 비고 |
|------|----------|------|
| document_id | ✅ 구현됨 | |
| source_id | ✅ 구현됨 | |
| source_path | ✅ 구현됨 | 전체 경로 |
| input_path | ✅ 구현됨 | source_path 동일 |
| relative_path | ❌ 미구현 | 필드 자체가 없음 |
| document_uid | ❌ 미구현 | 필드 자체가 없음 |
| dataset_id | ❌ 미구현 | |
| snapshot_id | ❌ 미구현 | |
| document_group | ✅ 구현됨 | |
| document_category | ✅ 구현됨 | |

### 2.3 Stage 3: Chunk

**파일:** `data/staged/chunks/*.jsonl`

| 필드 | 구현 상태 | 비고 |
|------|----------|------|
| chunk_id | ✅ 구현됨 | `{document_id}-chunk-{idx}` |
| document_id | ✅ 구현됨 | |
| source_id | ✅ 구현됨 | |
| relative_path | ⚠️ 부분 | 메타데이터에서 가져오지만 메타데이터에 없어서 빈값 |
| document_uid | ❌ 미구현 | |
| dataset_id | ❌ 미구현 | |
| snapshot_id | ❌ 미구현 | |

### 2.4 Stage 4-5: FAISS Build

**파일:** `data/indexes/faiss/*_metadata.jsonl`

| 필드 | 구현 상태 | 실제 값 |
|------|----------|--------|
| chunk_id | ✅ 구현됨 | `114477-chunk-0000` |
| document_id | ✅ 구현됨 | `114477` |
| source_id | ✅ 구현됨 | `src_20260630_073459_3f4491` |
| source_path | ✅ 구현됨 | 전체 경로 |
| relative_path | ⚠️ 부분 | **빈 문자열** (`""`) |
| document_uid | ❌ 미구현 | |
| dataset_id | ❌ 미구현 | |
| snapshot_id | ❌ 미구현 | (파일명에만 존재) |
| document_group | ✅ 구현됨 | `RFP` |
| document_category | ✅ 구현됨 | `rfp` |

### 2.5 Stage 6: Graph Build

**파일:** `data/indexes/graph/*.jsonl`

| 필드 | 구현 상태 | 비고 |
|------|----------|------|
| document_id | ✅ 구현됨 | |
| source_id | ✅ 구현됨 | |
| project_name | ✅ 구현됨 | |
| document_group | ✅ 구현됨 | |
| document_category | ✅ 구현됨 | |
| dataset_id | ❌ 미구현 | |
| snapshot_id | ❌ 미구현 | |

### 2.6 Active Index

**파일:** `data/indexes/faiss/active_index.json`

```json
{
  "snapshot": "snapshot_20260629_src_20260630_073459_3f4491_V1",
  "source_id": "src_20260630_073459_3f4491",
  "dataset_id": "",  // 비어있음
  "activated_at": "2026-06-30T..."
}
```

---

## 3. 코드 수준 구현 현황

### 3.1 document_uid

| 위치 | 상태 | 설명 |
|------|------|------|
| `services/document_uid.py` | ✅ 구현됨 | `make_document_uid(source_id, relative_path)` |
| `models/document_metadata.py` | ✅ 구현됨 | DB 컬럼 정의 |
| `models/document.py` | ✅ 구현됨 | DB 컬럼 정의 |
| `api/admin_dataset_builder_simple.py` | ✅ 사용됨 | Scan 시 생성 |
| FAISS 메타데이터 | ❌ 미전파 | 청크에 포함 안됨 |
| Graph 노드 | ❌ 미전파 | 노드 속성에 없음 |

### 3.2 dataset_id

| 위치 | 상태 | 설명 |
|------|------|------|
| `services/dataset_context.py` | ✅ 구현됨 | `generate_dataset_id()` |
| `api/document_sources.py` | ✅ 사용됨 | Source 등록/업데이트 시 |
| `services/faiss_job_runner.py` | ⚠️ 부분 | `activate_snapshot()`에만 전달 |
| Manifest CSV | ❌ 미포함 | |
| Metadata JSON | ❌ 미포함 | |
| FAISS 메타데이터 | ❌ 미포함 | |

### 3.3 relative_path

| 위치 | 상태 | 설명 |
|------|------|------|
| Manifest CSV | ✅ 생성됨 | `01. RFP/파일명.hwp` 형태 |
| Metadata JSON | ❌ 미포함 | 필드 자체가 없음 |
| Chunk JSONL | ⚠️ 빈값 | 메타데이터에서 가져오므로 빈값 |
| FAISS 메타데이터 | ⚠️ 빈값 | 빈 문자열 |

---

## 4. 문제점 및 개선 필요 사항

### 4.1 즉시 수정 필요 (P0)

1. **relative_path가 FAISS 메타데이터에 전파되지 않음**
   - 원인: Manifest에서 Metadata로 relative_path가 전달되지 않음
   - 영향: 검색 결과에서 파일 위치 추적 불가
   - 수정 위치: `scripts/prepare_snapshot_manifest.py` 또는 추출 단계

2. **dataset_id가 산출물에 포함되지 않음**
   - 원인: 파이프라인에서 dataset_id 전파 로직 누락
   - 영향: 데이터셋 버전 관리 불가
   - 수정 위치: 각 단계별 스크립트

### 4.2 단기 개선 필요 (P1)

1. **document_uid가 FAISS/Graph에 전파되지 않음**
   - 원인: DB에만 저장, 파일 산출물로 전파 안됨
   - 수정: 청크 생성 시 document_uid 포함

2. **snapshot_id가 메타데이터에 명시적으로 없음**
   - 현재: 파일명에만 존재
   - 수정: 각 레코드에 snapshot_id 필드 추가

### 4.3 section_type 명명 불일치

| 기대 필드명 | 실제 구현 | 비고 |
|------------|----------|------|
| section_type | - | 없음 |
| - | proposal_section | 제안서 하위 분류 |
| - | deliverable_section | 산출물 하위 분류 |

**권장:** `section_type` 필드로 통합하거나 현재 방식 유지 결정 필요

---

## 5. 데이터 흐름 다이어그램

```
Source 등록
    │
    ├── source_id: ✅ 생성 (src_YYYYMMDD_HHMMSS_xxxxxx)
    ├── dataset_id: ✅ 생성 (dataset_{source_id}_{timestamp})
    └── dataset_status: ✅ 생성 (pending → draft)
    │
    ▼
Stage 1: Manifest
    │
    ├── document_id: ✅ 생성
    ├── source_id: ✅ 전파됨
    ├── relative_path: ✅ 생성 ("01. RFP/파일명.hwp")
    ├── document_group: ✅ 생성
    ├── document_category: ✅ 생성
    ├── dataset_id: ❌ 없음
    └── document_uid: ❌ 없음
    │
    ▼
Stage 2: Extract/OCR
    │
    ├── document_id: ✅ 전파됨
    ├── source_id: ✅ 전파됨
    ├── relative_path: ❌ 누락됨 ← 문제!
    ├── document_group: ✅ 전파됨
    └── document_category: ✅ 전파됨
    │
    ▼
Stage 3: Chunk
    │
    ├── chunk_id: ✅ 생성
    ├── document_id: ✅ 전파됨
    ├── source_id: ✅ 전파됨
    └── relative_path: ⚠️ 빈값 (메타데이터에 없어서)
    │
    ▼
Stage 4-5: FAISS
    │
    ├── chunk_id: ✅ 전파됨
    ├── document_id: ✅ 전파됨
    ├── source_id: ✅ 전파됨
    ├── relative_path: ⚠️ 빈값
    ├── document_group: ✅ 전파됨
    └── document_category: ✅ 전파됨
    │
    ▼
Stage 6: Graph
    │
    ├── document_id: ✅ 전파됨
    ├── source_id: ✅ 전파됨
    ├── project_name: ✅ 전파됨
    └── document_group: ✅ 전파됨
```

---

## 6. 권장 수정 순서

### 1단계: relative_path 전파 수정
```python
# scripts/build_rag_source_metadata.py 또는 extract 단계에서
# Manifest CSV의 relative_path를 메타데이터로 전달

metadata["relative_path"] = manifest_row["relative_path"]
```

### 2단계: document_uid 전파
```python
# 청크 생성 시
from app.services.document_uid import make_document_uid

chunk_meta["document_uid"] = make_document_uid(
    source_id,
    relative_path
)
```

### 3단계: dataset_id/snapshot_id 전파
```python
# 각 단계 시작 시 컨텍스트에서 가져와 산출물에 포함
chunk_meta["dataset_id"] = current_dataset_id
chunk_meta["snapshot_id"] = current_snapshot_id
```

---

## 7. 검증 쿼리

### FAISS 메타데이터 ID 확인
```bash
# relative_path 확인
head -1 data/indexes/faiss/*_metadata.jsonl | jq '.relative_path'

# source_id 확인
head -1 data/indexes/faiss/*_metadata.jsonl | jq '.source_id'
```

### Manifest relative_path 확인
```bash
cut -d',' -f16 data/staged/manifest/*_manifest.csv | head -5
```

---

## 8. 결론

| 항목 | 상태 | 우선순위 |
|------|------|---------|
| source_id | ✅ 완료 | - |
| document_id | ✅ 완료 | - |
| document_group | ✅ 완료 | - |
| document_category | ✅ 완료 | - |
| relative_path | ⚠️ 부분 | P0 |
| document_uid | ⚠️ 부분 | P1 |
| dataset_id | ⚠️ 부분 | P1 |
| snapshot_id | ⚠️ 부분 | P2 |
| section_type | ⚠️ 분리됨 | P2 |

**핵심 문제:** `relative_path`가 Manifest에서 생성되지만 이후 단계로 전파되지 않아 FAISS 메타데이터에서 빈값으로 남아 있음. 이로 인해 `document_uid` 생성도 불가능.
