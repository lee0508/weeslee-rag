# 관리자 페이지 Graph View 미분류 수정

**작성일**: 2026-05-08  
**수정 대상**: `https://server.weeslee.co.kr/weeslee-rag/frontend/admin.html` → Graph View 탭

---

## 문제 현상

Graph View 탭 프로젝트 목록에 **"미분류" 61개 문서**가 최상단에 표시됨.

수정 전 통계:
- 5개 프로젝트 · 65개 문서 · 190개 관계

---

## 원인 분석

### 루트 원인

`backend/scripts/build_graph_jsonl.py`의 `_docs_from_faiss_meta()` 함수가 FAISS 메타데이터 JSONL에서 문서를 읽을 때, `metadata.project_name` 필드가 비어 있는 문서를 `"미분류"` 프로젝트로 분류함.

```python
# 기존 코드 (문제)
key = doc["project_name"] or "미분류"
```

### 발생 배경

배치-002 (snapshot_2026-05-06_batch-002) 이후 인덱싱된 문서들은 `metadata.project_name`이 빈 문자열로 저장됨.
반면 `input_path`에는 프로젝트 폴더명이 포함되어 있음.

예시:
```
input_path: /data/weeslee/weeslee-rag/data/raw/snapshot_.../domestic_business/202212. k-water 데이터허브플랫폼_ISP/...
project_name: ""  ← 비어있음
```

### 영향 범위

활성 인덱스 `snapshot_2026-05-07_combined-v3` 기준 275개 문서 중 **61개(22.2%)** 가 미분류 상태.

---

## 수정 내용

**파일**: `/data/weeslee/weeslee-rag/backend/scripts/build_graph_jsonl.py`

### 변경 사항

`_docs_from_faiss_meta()` 함수에 `project_name` 추론 로직 추가.

`_infer_project_name()` 헬퍼 함수를 추가하여 `input_path`에서 프로젝트명을 추출:

1. `input_path` 경로에서 `domestic_business` / `oda` / `overseas` 폴더를 찾음
2. 해당 폴더 바로 다음 세그먼트를 프로젝트 폴더명으로 사용
3. 기존 `_DATE_PREFIX` 정규식(`^\d+\.\s*`)으로 날짜 접두어 제거

```python
_ROOT_FOLDERS = {"domestic_business", "oda", "overseas"}


def _infer_project_name(input_path: str) -> str:
    parts = Path(input_path).parts
    for i, part in enumerate(parts):
        if part in _ROOT_FOLDERS and i + 1 < len(parts):
            return _DATE_PREFIX.sub("", parts[i + 1]).strip()
    return ""


def _docs_from_faiss_meta(path: Path) -> list[dict]:
    ...
    project_name = meta.get("project_name") or ""
    if not project_name:
        input_path = meta.get("input_path", "") or row.get("input_path", "")
        project_name = _infer_project_name(input_path)
    ...
```

### 백업

수정 전 원본 백업 생성:
```
/data/weeslee/weeslee-rag/backend/scripts/build_graph_jsonl.py.bak.20260508
```

---

## 수정 결과

그래프 재빌드 후(`POST /api/graph/build` 또는 `python3 build_graph_jsonl.py`):

| 항목 | 수정 전 | 수정 후 |
|------|---------|---------|
| 프로젝트 수 | 5개 (미분류 포함) | **91개** |
| 문서 수 | 65개 | **275개** |
| 관계 수 | 190개 | **734개** |
| 미분류 문서 | **61개** | **0개** |
| 빌드 날짜 | 2026-05-07 | **2026-05-08** |

---

## 후속 조치 권고

### 단기

- 새 배치 인덱싱 시 `metadata.project_name`이 비어있으면 파이프라인 단계에서 폴더명 기반으로 채워주는 것이 근본 해결책
- `metadata_enricher.py` 또는 추출 스크립트에서 `input_path` → `project_name` 자동 추출 적용 권고

### 중기

- `_infer_project_name()` 로직을 `metadata_enricher.py`에 통합하여 FAISS 인덱싱 시점에 `project_name` 확정
- `project_name` 없이 인덱싱된 문서 감지 경보 추가 (`faiss_admin.py` `/category-status` 엔드포인트 활용)
