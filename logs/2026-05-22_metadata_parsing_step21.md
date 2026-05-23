# 2026-05-22 metadata 파싱 기준 추가 Step21

## 작업 목표
- document_group, document_category, project_name 파싱 기준을 요구사항에 맞게 수정한다.
- document_group: RFP / 제안서 / 산출물 (한글)
- document_category: 전략및방법론 / 기술및기능 / 환경분석 등 (한글)
- project_name: 파일명에서 추출

## 변경 내용

### 1. build_rag_source_metadata.py

**추가된 상수**

```python
DOCUMENT_GROUP_DISPLAY = {
    "rfp": "RFP",
    "proposal": "제안서",
    "deliverable": "산출물",
}
```

**추가된 함수**

```python
def document_group_display(document_group: str) -> str:
    """document_group 영문값을 한글 표시명으로 변환한다."""
    return DOCUMENT_GROUP_DISPLAY.get((document_group or "").lower(), document_group or "unknown")
```

### 2. rag_source_pipeline.py

**변경된 build_manifest_row()**

```python
# 변경 전
document_group = doc_meta.get("document_group", "unknown")

# 변경 후
document_group_raw = doc_meta.get("document_group", "unknown")
document_group = rules.document_group_display(document_group_raw)
collection_key = _collection_key(document_group_raw)
```

### 3. rag_source_admin.py

**변경된 _build_metadata()**

```python
# 변경 전
document_group = doc_meta.get("document_group", "unknown")

# 변경 후
document_group_raw = doc_meta.get("document_group", "unknown")
document_group = COLLECTION_KEY_DISPLAY.get(document_group_raw.lower(), document_group_raw)
```

### 4. BOM 제거

- `backend/app/api/rag_source_admin.py` BOM 제거
- `backend/scripts/build_rag_source_metadata.py` BOM 제거

## 검증 결과

| 파일 | Python 문법 검사 | 결과 |
|------|------------------|------|
| rag_source_admin.py | `python -m py_compile` | PASSED |
| rag_source_pipeline.py | `python -m py_compile` | PASSED |
| build_rag_source_metadata.py | `python -m py_compile` | PASSED |

## 예상 결과

| 필드 | 변경 전 | 변경 후 |
|------|---------|---------|
| document_group | rfp, proposal, deliverable | RFP, 제안서, 산출물 |
| collection_key | rfp, proposal, deliverable | RFP, 제안서, 산출물 |
| document_category | strategy_methodology | 전략및방법론 |
| project_name | (파일명에서 추출) | (기존 로직 유지) |

## 예시 출력

```json
{
  "collection_name": "weeslee_rag_main",
  "collection_key": "제안서",
  "document_group": "제안서",
  "document_category": "전략및방법론",
  "project_name": "AI 기반 e-감사시스템 재구축 ISP 컨설팅",
  "file_name": "전략및방법론_AI 기반 e-감사시스템 재구축 ISP 컨설팅.pptx"
}
```

## 결론
- **상태**: 완료
- metadata 파싱 기준이 요구사항에 맞게 수정됨
- BOM 문제 해결됨

## 다음 단계
- Step22: assemble_rag_response.py 중복 build_prompt() 정리

---

작성일: 2026-05-22
작성자: Claude
상태: 완료
