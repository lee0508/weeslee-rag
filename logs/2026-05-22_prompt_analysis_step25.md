# 2026-05-22 Prompt Analysis API 구현 Step25

## 작업 목표
- 사용자 쿼리를 분석하여 검색 의도, 키워드, 필터 정보를 추출하는 API 구현

## 변경 내용

### 1. query_expander.py

**추가된 패턴 상수**
- `_ORG_PATTERNS`: 발주기관 감지 패턴 (18개)
- `_PROJECT_TYPE_PATTERNS`: 프로젝트 유형 패턴 (9개)
- `_TECH_PATTERNS`: 기술 키워드 패턴 (8개)

**추가된 함수: analyze_prompt()**

```python
def analyze_prompt(query: str) -> dict:
    """
    Returns:
        {
            "original_query": str,
            "mode_detection": {...},
            "extracted_keywords": [...],
            "detected_organization": str | None,
            "detected_project_type": str | None,
            "detected_technologies": [...],
            "detected_year": str | None,
            "detected_document_group": str | None,
            "detected_document_category": str | None,
            "suggested_filters": {...},
            "expanded_query": str,
        }
    """
```

### 2. rag.py

**추가된 API 엔드포인트**

```
POST /api/rag/analyze-prompt
```

**Request**
```json
{
  "query": "K-water AI 기반 ISP 전략및방법론 제안서"
}
```

**Response**
```json
{
  "success": true,
  "original_query": "K-water AI 기반 ISP 전략및방법론 제안서",
  "mode_detection": {
    "mode": "bid_project",
    "reason": "입찰 사업 검색 의도 감지",
    "matched_keyword": "제안서"
  },
  "extracted_keywords": ["K-water", "AI", "기반", "ISP", "전략및방법론", "제안서"],
  "detected_organization": "K-water",
  "detected_project_type": "ISP",
  "detected_technologies": ["AI"],
  "detected_year": null,
  "detected_document_group": "제안서",
  "detected_document_category": "전략및방법론",
  "suggested_filters": {
    "organization": "K-water",
    "document_group": "제안서",
    "document_category": "전략및방법론"
  },
  "expanded_query": "K-water AI 기반 ISP 전략및방법론 제안서 정보화전략계획 인공지능 ..."
}
```

## 검증 결과

| 파일 | Python 문법 검사 | 결과 |
|------|------------------|------|
| query_expander.py | `python -m py_compile` | PASSED |
| rag.py | `python -m py_compile` | PASSED |

## 활용 방안

1. **rag-assistant.html Right Panel**: 쿼리 분석 결과 표시
2. **자동 필터 적용**: suggested_filters를 검색 API에 전달
3. **쿼리 확장**: expanded_query로 검색 품질 향상

## 결론
- **상태**: 완료
- Prompt Analysis API 구현 완료
- 발주기관, 프로젝트 유형, 기술 키워드, 문서 분류 감지 기능 추가

## 다음 단계
- 서버 배포 후 API 테스트
- rag-assistant.html에 분석 결과 표시 UI 추가 (선택)

---

작성일: 2026-05-22
작성자: Claude
상태: 완료
