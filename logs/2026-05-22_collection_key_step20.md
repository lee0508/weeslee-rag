# 2026-05-22 collection_key 기준 수정 Step20

## 작업 목표
- collection_key를 "직접 상위 폴더명"에서 "문서 대분류 한글명"으로 변경한다.
- 기준: RFP / 제안서 / 산출물 (한글 표시)

## 변경 내용

### 1. rag_source_pipeline.py

**추가된 코드**

```python
COLLECTION_KEY_DISPLAY = {
    "rfp": "RFP",
    "proposal": "제안서",
    "deliverable": "산출물",
}

def _collection_key(document_group: str) -> str:
    """document_group을 한글 collection_key로 변환한다."""
    group = (document_group or "unknown").strip().lower()
    return COLLECTION_KEY_DISPLAY.get(group, group)
```

**변경된 함수: build_manifest_row()**

- `collection_key` 필드가 `_collection_key(document_group)` 호출로 변경됨
- 영문 document_group (`rfp`, `proposal`, `deliverable`)을 한글 표시값으로 변환

### 2. rag_source_admin.py

**변경 전**
```python
"collection_key": document_group,
```

**변경 후**
```python
from app.services.rag_source_pipeline import COLLECTION_KEY_DISPLAY

"collection_key": COLLECTION_KEY_DISPLAY.get(document_group.lower(), document_group),
```

## 검증 결과

| 파일 | Python 문법 검사 | 결과 |
|------|------------------|------|
| rag_source_pipeline.py | `python -m py_compile` | PASSED |
| rag_source_admin.py | `python -m py_compile` | PASSED |

## 예상 결과

| document_group | collection_key (변경 전) | collection_key (변경 후) |
|----------------|--------------------------|--------------------------|
| rfp | rfp | RFP |
| proposal | proposal | 제안서 |
| deliverable | deliverable | 산출물 |

## 결론
- **상태**: 완료
- collection_key가 한글 표시값으로 통일됨
- 단일 Collection (`weeslee_rag_main`) + metadata 필터링 전략에 부합

## 다음 단계
- Step21: metadata 파싱 기준 추가 (document_group, document_category, project_name)

---

작성일: 2026-05-22
작성자: Claude
상태: 완료
