# 데이터 계약 문서 (Data Contract)

> 작성일: 2026-06-24
> 버전: 1.0
> 목적: FAISS, Graph, Wiki가 공통으로 참조하는 기준 데이터 스키마 정의

---

## 1. 핵심 원칙

### 1.1 Metadata는 기준 데이터

Metadata는 FAISS 저장 이후에 별도로 만드는 후처리 데이터가 아니라,
**FAISS, Graph JSON, LLM Wiki가 공통으로 참조하는 기준 데이터**로 설계한다.

### 1.2 처리 파이프라인

```
1. Source Scan → scan_metadata 생성
2. OCR / Parser → ocr_metadata 생성
3. 관리자 검토 → final_metadata 확정
4. Chunk 분할
5. Embedding 생성
6. FAISS 저장 (metadata 포함)
7. Graph JSON 생성 (동일 metadata 참조)
8. Wiki 생성 (동일 metadata 참조)
9. Hybrid Search 테스트
```

### 1.3 Fallback 체인

사용 우선순위: `final_* → ocr_* → scan_*`

---

## 2. 공통 식별자 스키마

### 2.1 Document Level

| 필드명 | 타입 | 설명 | 예시 |
|--------|------|------|------|
| `document_id` | Integer | 문서 고유 ID (자동 증가) | `1234` |
| `document_uid` | String(64) | SHA1(source_id:relative_path) 해시 | `a1b2c3d4...` |
| `source_id` | String(100) | RAG Source ID | `consulting_docs` |
| `relative_path` | String(1000) | Document Source 기준 상대 경로 | `ISP/2024/한국수자원공사/제안서.pdf` |

### 2.2 Chunk Level

| 필드명 | 타입 | 설명 | 예시 |
|--------|------|------|------|
| `chunk_id` | String | `{document_id}-chunk-{index:04d}` | `1234-chunk-0001` |
| `chunk_index` | Integer | 문서 내 청크 순서 (0부터) | `0`, `1`, `2` |
| `char_count` | Integer | 청크 문자 수 | `1200` |

### 2.3 Section Level (Phase 2 신규)

| 필드명 | 타입 | 설명 | 예시 |
|--------|------|------|------|
| `section_id` | String | `{document_id}-section-{index:02d}` | `1234-section-01` |
| `section_title` | String | 섹션/목차 제목 | `기술및기능`, `프로젝트관리` |
| `section_type` | String | 섹션 유형 코드 | `tech_func`, `proj_mgmt` |

### 2.4 Page/Slide Level (Phase 2 신규)

| 필드명 | 타입 | 설명 | 예시 |
|--------|------|------|------|
| `page_no` | Integer | 페이지 번호 (1부터) | `42` |
| `slide_no` | Integer | 슬라이드 번호 (PPT용) | `15` |
| `page_title` | String | 페이지/슬라이드 제목 (있으면) | `보안 요구사항 대응방안` |

---

## 3. Metadata 3단계 구조

### 3.1 scan_metadata (Step 1: Source Scan)

파일명, 폴더명, 경로 기반 추정값. 신뢰도 낮음.

```json
{
  "scan_project_name": "한국수자원공사 ISP",
  "scan_organization": "한국수자원공사",
  "scan_year": "2024",
  "scan_document_category": "제안서"
}
```

### 3.2 ocr_metadata (Step 4: OCR/Parser)

OCR/Parser 결과에서 추출. 중간 신뢰도.

```json
{
  "ocr_project_name": "한국수자원공사 차세대 정보화전략계획 수립",
  "ocr_organization": "한국수자원공사",
  "ocr_year": "2024",
  "ocr_document_category": "제안서",
  "ocr_title": "차세대 정보화전략계획 제안서",
  "ocr_summary": "ISP 수립 및 정보화전략계획 제안 내용",
  "ocr_keywords": ["ISP", "정보화전략", "데이터 표준화"],
  "ocr_confidence": 0.85,
  "ocr_quality_score": 0.92,
  "ocr_page_count": 120
}
```

### 3.3 final_metadata (Step 3: 관리자 확정)

관리자 검토 후 확정값. 최고 신뢰도.

```json
{
  "final_project_name": "한국수자원공사 차세대 정보화전략계획",
  "final_organization": "한국수자원공사",
  "final_year": "2024",
  "final_document_category": "기술및기능",
  "final_document_group": "제안서",
  "final_confirmed_by": "admin",
  "final_confirmed_at": "2026-06-24T10:30:00Z"
}
```

---

## 4. FAISS 메타데이터 스키마

FAISS 인덱스의 각 벡터에 연결되는 메타데이터.

### 4.1 필수 필드

```json
{
  "chunk_id": "1234-chunk-0001",
  "document_id": "1234",
  "source_id": "consulting_docs",
  "category": "제안서",
  "section_heading": "보안 요구사항 대응",
  "char_count": 1200,
  "page_no": 42
}
```

### 4.2 메타데이터 필드 (확장)

```json
{
  "organization": "한국수자원공사",
  "project_name": "차세대 정보화전략계획",
  "document_group": "제안서",
  "document_category": "기술및기능",
  "folder_year": "2024",
  "file_name": "제안서_기술및기능.pdf",
  "relative_path": "ISP/2024/한국수자원공사/제안서/기술및기능.pdf"
}
```

### 4.3 Fallback 적용 규칙

```python
def get_effective_value(meta: dict, field: str) -> str:
    """final → ocr → scan 순으로 값 반환"""
    for prefix in ["final_", "ocr_", "scan_"]:
        key = f"{prefix}{field}"
        if meta.get(key):
            return meta[key]
    # prefix 없는 기본 필드 확인
    return meta.get(field, "")
```

---

## 5. Graph 노드/엣지 스키마

### 5.1 필수 노드 타입

| 노드 타입 | 속성 | 설명 |
|-----------|------|------|
| `PROJECT` | name, year, organization | 사업 |
| `DOCUMENT` | id, name, group, category | 문서 |
| `SECTION` | id, title, type | 섹션 (Phase 2) |
| `CHUNK` | id, page_no, summary | 청크 |
| `ORGANIZATION` | name, type | 기관 |
| `ORGANIZATION_TYPE` | name | 기관유형 (공공기관, 연구기관 등) |
| `PROJECT_TYPE` | name | 사업유형 (ISP, ISMP 등) |
| `TOPIC` | name | 주제 (보안, AI 등) |
| `REQUIREMENT` | code, name | 요구사항 |
| `TECHNOLOGY` | name | 기술 |

### 5.2 필수 엣지 타입

| 엣지 타입 | 소스 → 타겟 | 설명 |
|-----------|-------------|------|
| `HAS_DOCUMENT` | PROJECT → DOCUMENT | 사업의 문서 |
| `HAS_SECTION` | DOCUMENT → SECTION | 문서의 섹션 |
| `HAS_CHUNK` | SECTION → CHUNK | 섹션의 청크 |
| `BELONGS_TO` | DOCUMENT → PROJECT | 문서의 소속 사업 |
| `ISSUED_BY` | PROJECT → ORGANIZATION | 발주기관 |
| `BELONGS_TO_TYPE` | ORGANIZATION → ORGANIZATION_TYPE | 기관 유형 |
| `HAS_PROJECT_TYPE` | PROJECT → PROJECT_TYPE | 사업 유형 |
| `MENTIONS` | CHUNK → TOPIC | 청크가 언급하는 주제 |
| `MENTIONS` | CHUNK → REQUIREMENT | 청크가 언급하는 요구사항 |
| `APPEARS_IN` | CHUNK → SECTION | 청크가 속한 섹션 |
| `USES_TECHNOLOGY` | PROJECT → TECHNOLOGY | 사업에서 사용하는 기술 |

### 5.3 Graph 생성 시 필수 데이터

```
document_id
chunk_id
section_id (Phase 2)
section_title
page_no / slide_no
document_group
document_category
project_name
organization
organization_type
business_domain
requirement (있으면)
topic (있으면)
technology (있으면)
keyword
document_summary
chunk_summary
```

---

## 6. Wiki 문서 스키마

### 6.1 프로젝트 Wiki

```markdown
# {project_name}

## 기본 정보
- 발주기관: {organization}
- 사업연도: {year}
- 사업유형: {project_type}
- 사업영역: {business_domain}

## 문서 목록
- 제안서 (기술및기능): 120페이지
- 제안서 (프로젝트관리): 45페이지
- 최종보고서: 280페이지

## 주요 내용 요약
{summary}

## 핵심 키워드
{keywords}

## 관련 기술
{technologies}
```

### 6.2 기관 Wiki

```markdown
# {organization}

## 기관 정보
- 기관유형: {organization_type}
- 관련 사업 수: {project_count}

## 수행 사업 목록
1. {project_name_1} ({year_1})
2. {project_name_2} ({year_2})
...
```

---

## 7. 검색 결과 출력 스키마

### 7.1 표준 검색 결과

```json
{
  "question_interpretation": {
    "intent": "보안 요구사항 장표 검색",
    "filters": {
      "document_group": "제안서",
      "topic": "보안"
    }
  },
  "answer_summary": "이전 제안서 4건에서 유사한 보안 요구사항 장표가 확인되었습니다.",
  "related_documents": [
    {
      "project_name": "○○ 정보화전략계획 수립",
      "organization": "○○공사",
      "document_name": "제안서.pptx",
      "section": "기술및기능 > 보안 요구사항 대응",
      "page_no": 42,
      "reuse_level": "high",
      "reuse_reason": "문구 일부 재사용 가능"
    }
  ],
  "evidence_chunks": [
    {
      "chunk_id": "1234-chunk-0042",
      "text_preview": "누출금지 정보에 대한 보안 대책으로...",
      "score": 0.92
    }
  ],
  "graph_path": [
    "Requirement(누출금지 정보)",
    "→ BELONGS_TO Topic(보안 요구사항)",
    "→ APPEARS_IN Section(기술및기능)",
    "→ BELONGS_TO Document(제안서)",
    "→ BELONGS_TO Project(○○ 정보화전략계획)"
  ]
}
```

---

## 8. ID 생성 규칙

### 8.1 document_id

- MySQL AUTO_INCREMENT 사용
- 정수형, 1부터 시작

### 8.2 document_uid

```python
import hashlib

def generate_document_uid(source_id: str, relative_path: str) -> str:
    """SHA1(source_id:relative_path) 문서 고유 식별자"""
    key = f"{source_id}:{relative_path}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()
```

### 8.3 chunk_id

```python
def generate_chunk_id(document_id: int, chunk_index: int) -> str:
    """{document_id}-chunk-{index:04d}"""
    return f"{document_id}-chunk-{chunk_index:04d}"
```

### 8.4 section_id (Phase 2)

```python
def generate_section_id(document_id: int, section_index: int) -> str:
    """{document_id}-section-{index:02d}"""
    return f"{document_id}-section-{section_index:02d}"
```

---

## 9. 확장 포인트 (Phase 2+)

### 9.1 Requirement 노드 추출

- 정규식 패턴: `[A-Z]{2,4}-\d{3}` (예: SER-002)
- entity_mappings.json에 RFP별 요구사항 코드 등록
- OCR 텍스트에서 자동 추출 후 수동 보정

### 9.2 Topic 노드 생성

- entity_mappings.json의 document_keywords 기반
- LLM을 통한 주제 자동 분류 (선택적)

### 9.3 Page/Slide 노드

- 초기 버전에서는 Chunk의 page_no 속성으로 관리
- 핵심 장표 노드화는 관리자 지정 방식으로 확장

---

## 10. 검증 체크리스트

### 10.1 데이터 일관성

- [ ] 모든 chunk_id가 해당 document_id를 포함하는가?
- [ ] FAISS 메타데이터의 document_id가 Graph 노드의 DOCUMENT.id와 일치하는가?
- [ ] Wiki 문서의 project_name이 Graph 노드의 PROJECT.name과 일치하는가?

### 10.2 Fallback 체인

- [ ] final_* 값이 없을 때 ocr_* 값이 사용되는가?
- [ ] ocr_* 값이 없을 때 scan_* 값이 사용되는가?

### 10.3 검색 결과 정합성

- [ ] FAISS 검색 결과의 document_id로 Graph 노드를 찾을 수 있는가?
- [ ] Graph 경로 추적 결과가 FAISS 검색 결과와 일치하는가?

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|----------|
| 1.0 | 2026-06-24 | 초기 버전 작성 |
