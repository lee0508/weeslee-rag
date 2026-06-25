# Document Source 및 Snapshot 개념 정의

**작성일:** 2026-06-25
**버전:** 1.0

---

## 1. 개요

PromptoRAG 시스템에서 문서 데이터를 관리하는 핵심 개념인 **Document Source**, **Dataset**, **Snapshot**의 정의와 관계를 명확히 한다.

---

## 2. 용어 정의

### 2.1 Document Source

| 항목 | 설명 |
|------|------|
| **정의** | RAG 파이프라인의 원본 문서 저장소 루트 폴더 |
| **식별자** | `source_id` (예: `rag_source`, `src_20260625_abc123`) |
| **특성** | 고정된 물리적 경로를 가리키며, 시스템에 1개 또는 소수만 등록 |
| **예시** | `\\diskstation\W2_프로젝트폴더`, `/mnt/nas/oda_archive` |

**핵심 포인트:**
- Document Source는 **개별 문서가 아니라 루트 폴더**이다
- 고객사별로 서로 다른 Document Source를 등록할 수 있다
- 하나의 Document Source 아래에 수천 개의 문서가 포함될 수 있다

### 2.2 Dataset

| 항목 | 설명 |
|------|------|
| **정의** | 특정 시점에 Document Source를 스캔하여 생성한 데이터 세트 |
| **식별자** | `dataset_id` (예: `ds_20260625_rag_source_abc123`) |
| **특성** | Document Source의 스캔 시점 스냅샷, 메타데이터 포함 |
| **생성 시점** | Dataset Builder Step 1 (파일 스캔) 시작 시 |

### 2.3 Snapshot

| 항목 | 설명 |
|------|------|
| **정의** | Dataset을 기반으로 RAG 인덱스를 빌드한 검색 가능한 버전 |
| **식별자** | `snapshot_id` (예: `snapshot_20260625_rag_source_v1`) |
| **특성** | FAISS 인덱스, 메타데이터, Graph 등 검색에 필요한 모든 산출물 포함 |
| **생성 시점** | Dataset Builder Step 6 (FAISS 빌드) 완료 시 |

**Snapshot 상태:**
| 상태 | 설명 |
|------|------|
| `draft` | 생성 중 (인덱스 미완료) |
| `indexed` | 인덱스 빌드 완료 (검색 가능) |
| `active` | 현재 운영 중인 Snapshot |
| `archived` | 보관용 (검색 가능하나 비활성) |

---

## 3. ID 체인 구조

```
Document Source (source_id)
    │
    ├── Dataset A (dataset_id)
    │       ├── Snapshot v1 (snapshot_id) ← archived
    │       └── Snapshot v2 (snapshot_id) ← active
    │
    └── Dataset B (dataset_id)  ← 새 스캔 시 생성
            └── Snapshot v1 (snapshot_id)
```

### 3.1 ID 명명 규칙

| ID 유형 | 형식 | 예시 |
|---------|------|------|
| source_id | `{prefix}_{timestamp}_{random}` | `src_20260625_abc123` |
| dataset_id | `ds_{date}_{source_id}_{random}` | `ds_20260625_rag_source_def456` |
| snapshot_id | `snapshot_{date}_{source_id}_v{N}` | `snapshot_20260625_rag_source_v1` |

### 3.2 전체 ID 체인

```
source_id
    └── dataset_id
            └── snapshot_id
                    └── document_id
                            └── section_id
                                    └── chunk_id
```

---

## 4. 멀티 Source 환경

### 4.1 구조

여러 Document Source를 등록하면 각각 독립적인 Dataset/Snapshot 체인을 가진다.

```
Document Source A (source_id: rag_source)
    └── Snapshot: snapshot_20260625_rag_source_v1 [active]

Document Source B (source_id: oda_archive)
    └── Snapshot: snapshot_20260624_oda_archive_v2 [active]

Document Source C (source_id: policy_docs)
    └── Snapshot: snapshot_20260620_policy_docs_v1 [active]
```

### 4.2 Active Snapshot 관리

| 파일 경로 | 용도 |
|----------|------|
| `data/active_snapshot.json` | 글로벌 Active (단일 Source 환경) |
| `data/active_index.json` | RAG 검색용 (하위 호환성) |
| `data/snapshots/{source_id}/active.json` | Source별 Active |

**멀티 Source 환경에서는 각 Source마다 별도의 Active Snapshot을 가질 수 있다.**

---

## 5. 사용자 검색 (Search Scope)

### 5.1 검색 범위 옵션

| Scope ID | 설명 | 대상 Snapshot |
|----------|------|---------------|
| `active_snapshot` | 현재 Active Snapshot | 글로벌 Active 1개 |
| `all_sources` | 전체 데이터셋 | 모든 Source의 최신 Snapshot 합산 |
| `source:{source_id}` | 특정 Source | 해당 Source의 최신 Snapshot |
| `{custom_profile}` | 사용자 정의 | 지정된 Snapshot 조합 |

### 5.2 Snapshot 직접 선택

사용자는 검색 범위와 별도로 **특정 Snapshot을 직접 다중 선택**하여 검색할 수 있다.

```
검색 요청
    ├── snapshot_ids가 있으면 → 해당 Snapshot들만 검색 (우선)
    └── 없으면 → search_scope에 따라 검색
```

### 5.3 UI 구성 (rag-assistant.html)

```
┌─────────────────────────────────────┐
│ 검색 범위                            │
│ ┌─────────────────────────────────┐ │
│ │ 현재 Active Snapshot      ▼    │ │
│ └─────────────────────────────────┘ │
│ 기존 운영 방식과 동일하게 현재 활성   │
│ 스냅샷 1개만 검색합니다.              │
├─────────────────────────────────────┤
│ Snapshot 직접 선택                   │
│ ┌─────────────────────────────────┐ │
│ │ ▸ rag_source                    │ │
│ │   ☑ snapshot_20260625_v2 [active]│ │
│ │   ☐ snapshot_20260624_v1        │ │
│ │ ▸ oda_archive                   │ │
│ │   ☐ snapshot_20260624_v1 [active]│ │
│ └─────────────────────────────────┘ │
│ 선택 없으면 위 검색 범위를 사용합니다. │
│                    [Snapshot 선택 해제]│
└─────────────────────────────────────┘
```

---

## 6. 관리자 워크플로우

### 6.1 Document Source 등록 (admin.html)

1. **Document Source 탭** 접근
2. **+ 신규 Source 등록** 클릭
3. 원본 경로 (UNC/절대경로) 입력
4. 마운트 경로 설정
5. **DB에 저장** → `source_id` 및 `dataset_id` 자동 생성

### 6.2 Dataset/Snapshot 생성 (Dataset Builder)

| 단계 | 작업 | 산출물 |
|------|------|--------|
| Step 1 | 파일 스캔 | 문서 목록, scan_metadata |
| Step 2 | 메타데이터 생성 | 태그, 키워드, 분류 |
| Step 3 | 메타데이터 보강 | organization, domain 등 |
| Step 4 | OCR/Parser | 텍스트 추출, ocr_metadata |
| Step 5 | 청킹 | chunks JSONL |
| Step 6 | FAISS 빌드 | 인덱스, metadata JSONL |
| Step 7 | Graph 빌드 | nodes/edges JSONL |

### 6.3 Snapshot 활성화

1. **Snapshot 관리** 탭에서 목록 확인
2. 원하는 Snapshot의 **Active로 설정** 클릭
3. 이전 Active는 자동으로 `archived` 상태로 변경

---

## 7. 데이터 파일 구조

```
data/
├── active_snapshot.json              # 글로벌 Active 설정
├── active_index.json                 # RAG 검색용 (하위 호환성)
│
├── snapshots/
│   ├── snapshot_20260625_rag_source_v1.json   # Snapshot manifest
│   ├── snapshot_20260625_rag_source_v2.json
│   │
│   └── rag_source/                   # Source별 디렉토리
│       └── active.json               # Source별 Active 설정
│
├── indexes/
│   └── faiss/
│       ├── snapshot_20260625_rag_source_v2_ollama.index
│       ├── snapshot_20260625_rag_source_v2_ollama_metadata.jsonl
│       └── ...
│
├── staged/
│   ├── manifest/                     # 빌드 입력 manifest
│   ├── chunks/                       # 청크 JSONL
│   └── graph/                        # Graph JSONL
│
└── config/
    └── search_profiles.json          # 검색 프로필 설정
```

---

## 8. API 엔드포인트

### 8.1 Document Source 관리

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/admin/document-sources` | Source 목록 조회 |
| POST | `/api/admin/document-sources` | Source 등록 |
| GET | `/api/admin/document-sources/{source_id}` | Source 상세 |
| PUT | `/api/admin/document-sources/{source_id}` | Source 수정 |
| DELETE | `/api/admin/document-sources/{source_id}` | Source 삭제 |
| POST | `/api/admin/document-sources/{source_id}/scan` | 변경 파일 스캔 |
| POST | `/api/admin/document-sources/{source_id}/ensure-dataset` | Dataset 준비 |

### 8.2 Snapshot 관리

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/admin/snapshots` | Snapshot 목록 |
| POST | `/api/admin/snapshots` | Snapshot 생성 |
| GET | `/api/admin/snapshots/active` | Active Snapshot 조회 |
| POST | `/api/admin/snapshots/{snapshot_id}/activate` | Active로 설정 |

### 8.3 검색 (사용자)

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/rag/search-scopes` | 검색 범위 카탈로그 |
| POST | `/api/rag/query` | RAG 검색 (search_scope, snapshot_ids 지원) |

---

## 9. 요약

| 개념 | 정의 | 개수 | 예시 |
|------|------|------|------|
| **Document Source** | 루트 폴더 | 1~N개 (소수) | `rag_source` |
| **Dataset** | 스캔 시점 데이터 | Source당 1~N개 | `ds_20260625_...` |
| **Snapshot** | 검색 가능 버전 | Dataset당 1~N개 | `snapshot_20260625_..._v1` |
| **Active Snapshot** | 운영 중 버전 | Source당 1개 | `[active]` 표시 |

**핵심:**
- Document Source는 **루트 폴더**이며, 개별 문서 목록이 아니다
- 멀티 Source 환경에서는 각 Source별로 독립적인 Active Snapshot을 가진다
- 사용자는 검색 시 Search Scope 또는 Snapshot 직접 선택으로 검색 범위를 지정할 수 있다

---

*End of Document*
