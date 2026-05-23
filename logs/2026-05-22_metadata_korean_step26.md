# 2026-05-22 한글 메타데이터 적용 Step26

## 작업 목표
- FAISS 인덱스 메타데이터에 한글 표시값 적용
- collection_key, document_group 한글화 (RFP, 제안서, 산출물)
- API 응답에서 한글 메타데이터 반환

## 변경 내용

### 1. rag_source_pipeline.py
- `rules.document_group_display()` 의존성 제거
- `_collection_key()` 함수로 통일

```python
document_group = _collection_key(document_group_raw)  # 한글 표시값으로 변환
collection_key = document_group  # document_group과 동일한 한글 표시값
```

### 2. rag_runtime.py
- `collection_key` 읽기 로직 수정

```python
# 기존
collection_key=meta.get("collection_key", ""),

# 수정
collection_key=row.get("collection_key", "") or meta.get("collection_key", ""),
```

### 3. rag.py (API)
- fallback 로직 추가

```python
"collection_key": doc.get("collection_key", "") or doc.get("category", ""),
"document_group": doc.get("document_group", "") or doc.get("collection_key", "") or doc.get("category", ""),
"document_category": doc.get("document_category", "") or doc.get("section_label", ""),
```

### 4. FAISS 메타데이터 파일 변환
- `snapshot_2026-05-06_combined-v2_ollama_metadata.jsonl` (7,066 rows)
- `snapshot_2026-05-07_combined-v3_ollama_metadata.jsonl` (34,161 rows)

변환 내용:
- category: proposal → 제안서
- category: rfp → RFP
- collection_key 추가
- document_group 추가
- document_category 추가

## 검증 결과

| 항목 | 결과 |
|------|------|
| API 응답 category | 제안서 ✅ |
| API 응답 collection_key | 제안서 ✅ |
| API 응답 document_group | 제안서 ✅ |
| Python 문법 검사 | PASSED ✅ |

### 테스트 쿼리

```bash
curl -X POST http://localhost:8002/api/rag/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "ISP 전략", "top_k": 3}'
```

응답:
```json
{
  "category": "제안서",
  "collection_key": "제안서",
  "document_group": "제안서"
}
```

## 결론
- **상태**: 완료
- FAISS 인덱스 메타데이터 한글 적용 완료
- API 응답에서 한글 메타데이터 반환 확인
- 폴백 로직 적용으로 기존 영문 메타데이터도 호환

---

작성일: 2026-05-22
작성자: Claude
상태: 완료
