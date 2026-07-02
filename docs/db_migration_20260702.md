# DB Migration 작업 보고서

**작성일**: 2026-07-02
**작업자**: Claude Code
**목적**: 시스템 환경 정보 및 Dataset Builder 설정을 MySQL DB 테이블로 저장

---

## 1. 작업 요약

### 생성된 DB 테이블 (3개)

| 테이블명 | 용도 | 컬럼 수 |
|---------|------|--------|
| `runtime_compute_settings` | GPU/연산 환경 전역 설정 | 10 |
| `active_snapshot_state` | 활성 스냅샷 상태 관리 | 24 |
| `dataset_build_settings` | Dataset Builder 단계별 설정 | 19 |

### 생성된 파일

**마이그레이션 SQL**
- `backend/scripts/migrations/006_create_runtime_compute_settings.sql`
- `backend/scripts/migrations/007_create_active_snapshot_state.sql`
- `backend/scripts/migrations/008_create_dataset_build_settings.sql`

**Python 모델 및 서비스**
- `backend/app/models/dataset_build_settings.py`
- `backend/app/services/dataset_build_settings.py`
- `backend/app/services/active_snapshot_state.py` (기존 수정)
- `backend/app/services/runtime_compute_settings.py` (기존 수정)

---

## 2. 테이블 상세 설계

### 2.1 runtime_compute_settings

시스템 전역 GPU/연산 환경 설정 저장.

**주요 필드**
- `gpu_enabled`: GPU 전역 활성화 여부
- `cuda_visible_devices`: 사용할 GPU 디바이스 번호
- `ollama_use_gpu`: Ollama GPU 사용 여부
- `ocr_use_gpu`: OCR GPU 사용 여부
- `chunk_use_gpu`: 청킹 GPU 사용 여부
- `embedding_use_gpu`: 임베딩 GPU 사용 여부
- `faiss_use_gpu`: FAISS GPU 사용 여부

**기본값**: 모든 GPU 옵션 활성화 (CUDA_VISIBLE_DEVICES=0)

---

### 2.2 active_snapshot_state

현재 활성화된 스냅샷의 상태 정보 저장.

**주요 필드**
- `active_snapshot_id`: 활성 스냅샷 ID
- `source_id`: 소스 ID
- `dataset_id`: 데이터셋 ID
- `index_file`: FAISS 인덱스 파일 경로
- `metadata_file`: 메타데이터 파일 경로
- `embedding_provider`: 임베딩 제공자 (ollama 기본)
- `vector_count`: 벡터 수
- `document_count`: 문서 수
- `chunk_count`: 청크 수
- `tag_keyword_build_id`: Tag/Keyword 빌드 ID
- `graph_build_id`: Knowledge Graph 빌드 ID
- `wiki_build_id`: LLM Wiki 빌드 ID
- `rollback_available`: 롤백 가능 여부

**인덱스**
- `idx_active_snapshot_state_snapshot` (active_snapshot_id)
- `idx_active_snapshot_state_source` (source_id)
- `idx_active_snapshot_state_dataset` (dataset_id)

---

### 2.3 dataset_build_settings

source_id별 Dataset Builder 각 단계의 설정을 JSON 형식으로 저장.

**구조**
각 Step마다 `step{N}_enabled` (Boolean) + `step{N}_config` (JSON) 쌍으로 구성.

**Step별 설정**

| Step | 단계명 | 기본 설정 예시 |
|------|--------|---------------|
| 3 | 메타데이터 추출 | `{"extraction_rules": "default", "category_mapping": {}}` |
| 4 | OCR/파싱 | `{"ocr_engine": "tesseract", "ocr_dpi": 300, "ocr_language": "kor+eng", "ocr_mode": "auto"}` |
| 5 | Tag/Keyword 생성 | `{"llm_model": "claude-3-5-sonnet", "max_tags": 10, "max_keywords": 20}` |
| 6 | 청킹/임베딩 | `{"chunk_size": 512, "chunk_overlap": 50, "embedding_model": "ollama/nomic-embed-text"}` |
| 7 | Knowledge Graph | `{"ontology_id": "default", "graph_mode": "basic", "max_nodes": 1000}` |
| 8 | LLM Wiki | `{"llm_model": "claude-3-5-sonnet", "max_articles": 30, "temperature": 0.3}` |
| 10 | FAISS 인덱스 | `{"index_type": "Flat", "use_gpu": true, "gpu_devices": "0"}` |

**인덱스**
- `idx_dataset_build_settings_source` (source_id, UNIQUE)
- `idx_dataset_build_settings_dataset` (dataset_id)

---

## 3. 서비스 함수 API

### 3.1 runtime_compute_settings

```python
from app.services.runtime_compute_settings import (
    get_runtime_compute_settings,
    save_runtime_compute_settings,
    is_stage_gpu_enabled,
    build_runtime_compute_env,
    describe_stage_compute_mode,
    get_runtime_compute_snapshot,
)

# 설정 조회
settings = get_runtime_compute_settings()
# → {"gpu_enabled": True, "ollama_use_gpu": True, ...}

# 특정 스테이지 GPU 활성화 여부
enabled = is_stage_gpu_enabled("embedding")
# → True/False

# 환경변수 생성
env = build_runtime_compute_env("embedding")
# → {"WEESLEE_GPU_MODE": "1", "CUDA_VISIBLE_DEVICES": "0", ...}
```

### 3.2 active_snapshot_state

```python
from app.services.active_snapshot_state import (
    get_active_snapshot_state,
    save_active_snapshot_state,
    get_active_snapshot_id,
)

# 활성 스냅샷 조회
state = get_active_snapshot_state()
# → {"active_snapshot_id": "...", "source_id": "...", ...}

# 활성 스냅샷 ID만 조회
snapshot_id = get_active_snapshot_id()
# → "snapshot_20260701_..."

# 활성 스냅샷 저장
save_active_snapshot_state({
    "active_snapshot_id": "snapshot_20260702_...",
    "source_id": "src_20260702_...",
    "vector_count": 10031,
    "document_count": 247,
})
```

### 3.3 dataset_build_settings

```python
from app.services.dataset_build_settings import (
    get_dataset_build_settings,
    save_dataset_build_settings,
    get_step_config,
    is_step_enabled,
)

# source_id별 빌드 설정 조회
settings = get_dataset_build_settings("src_20260702_085410_d993a0")
# → {"source_id": "...", "step4_enabled": True, "step4_config": {...}, ...}

# 특정 step 설정만 조회
step6_config = get_step_config("src_20260702_085410_d993a0", "6")
# → {"chunk_size": 512, "chunk_overlap": 50, ...}

# 특정 step 활성화 여부
enabled = is_step_enabled("src_20260702_085410_d993a0", "7")
# → True/False

# 설정 저장
save_dataset_build_settings("src_20260702_085410_d993a0", {
    "step6_config": {
        "chunk_size": 1024,
        "chunk_overlap": 100,
    }
})
```

---

## 4. 서버 배포 완료

### 배포 항목
1. ✅ SQL 마이그레이션 파일 (006, 007, 008)
2. ✅ Python 모델 파일 (dataset_build_settings.py)
3. ✅ Python 서비스 파일 (dataset_build_settings.py)
4. ✅ DB 테이블 생성 실행
5. ✅ 서비스 함수 테스트 통과
6. ✅ 서버 Health 체크 정상

### 테스트 결과

```
✓ runtime_compute_settings - 존재 (컬럼 수: 10)
✓ active_snapshot_state - 존재 (컬럼 수: 24)
✓ dataset_build_settings - 존재 (컬럼 수: 19)

=== API 테스트 ===
✓ get_runtime_compute_settings() - 정상
✓ get_active_snapshot_state() - 정상
✓ get_dataset_build_settings() - 정상

=== Health Check ===
✓ http://127.0.0.1:8080/api/health → {"status":"healthy"}
```

---

## 5. 향후 작업 권장사항

### 5.1 API 엔드포인트 추가

Dataset Builder 설정을 관리자 UI에서 조회/수정할 수 있도록 API 추가 필요.

**권장 엔드포인트**
- `GET /admin/dataset-builder/settings/{source_id}`
- `PUT /admin/dataset-builder/settings/{source_id}`
- `GET /admin/dataset-builder/settings/{source_id}/step/{step_num}`
- `PUT /admin/dataset-builder/settings/{source_id}/step/{step_num}`

### 5.2 관리자 UI 연동

`frontend/admin.html`에 Dataset Builder 설정 페이지 추가.

**기능 요구사항**
- source_id별 설정 조회
- Step별 활성화/비활성화 토글
- Step별 설정값 편집 (JSON 에디터)
- 기본값 복원 버튼

### 5.3 기존 코드 통합

현재 파일 기반으로 저장하던 설정을 DB 테이블로 점진적 이관.

**대상 파일**
- `platform_config/runtime_compute_settings.json`
- `platform_config/active_snapshot_state.json`
- 각 source별 설정 JSON 파일들

**이관 전략**
1. 기존 JSON 파일이 있으면 DB로 import
2. DB에 없으면 JSON에서 읽기 (fallback)
3. 저장 시 DB 우선, JSON은 백업용으로 유지

---

## 6. 체크리스트

- [x] DB 마이그레이션 스크립트 작성 (006, 007, 008)
- [x] Python 모델 클래스 작성
- [x] Python 서비스 함수 작성
- [x] 서버 배포 및 테이블 생성
- [x] 서비스 함수 테스트
- [x] Health 체크
- [ ] API 엔드포인트 추가
- [ ] 관리자 UI 연동
- [ ] 기존 JSON 파일 이관

---

**작업 완료**: 2026-07-02
**상태**: ✅ 성공
