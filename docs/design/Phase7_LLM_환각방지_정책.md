# Phase 7. LLM 환각 방지 정책

## 1. 문서 개요

이 문서는 weeslee-rag에서 LLM 환각(Hallucination)을 최소화하기 위한 정책을 정의한다.
선택 문서 기반 답변 생성에서 근거 없는 정보 생성을 방지하는 것이 핵심 목표다.

## 2. 환각 방지 핵심 원칙

### 2.1 5대 원칙

```
1. LLM이 먼저 답변하지 않는다
   └ 검색 결과를 먼저 사용자에게 표시한다

2. 근거 문서를 먼저 검색한다
   └ RAG, Agent, Graph, Wiki 4개 모드 병렬 검색

3. 사용자가 문서를 선택한다
   └ 자동 선택이 아닌 사용자 명시적 선택

4. 선택된 문서만 context로 답변을 생성한다
   └ grounded_only 모드 강제 적용

5. 모든 답변에 근거를 포함한다
   └ 문서명, 페이지, 청크 정보 필수 표시
```

### 2.2 검색 → 선택 → 답변 흐름

```
사용자 질문
    │
    ▼
[검색 실행] ──────────────────────────┐
    │                                │
    ▼                                │
[검색 결과 표시] ◀───────────────────┘
    │
    │ ※ LLM 답변 없음, 검색 결과만 표시
    │
    ▼
[사용자 문서 선택] ←─ 명시적 체크박스 선택
    │
    ▼
[답변 생성 요청] ←─ 사용자가 버튼 클릭
    │
    ▼
[Grounded Answer 생성]
    │
    └──▶ 선택 문서 context + 시스템 프롬프트 + 질문
              │
              ▼
         [답변 + Citations]
```

## 3. 시스템 프롬프트 정의

### 3.1 Grounded Answer 시스템 프롬프트

```
당신은 weeslee-rag 문서 검색 보조 AI입니다.

## 역할
사용자가 선택한 문서를 기반으로 질문에 답변합니다.

## 규칙
1. 반드시 제공된 문서 내용만 근거로 답변하세요.
2. 제공된 문서에 없는 내용은 절대 추측하지 마세요.
3. 확실하지 않은 내용은 "문서에서 확인되지 않음"이라고 답변하세요.
4. 답변에는 반드시 사용한 문서명, 페이지, 위치를 포함하세요.
5. 문서 내용을 그대로 인용할 때는 따옴표로 감싸세요.

## 인용 형식
- 단일 출처: [1]
- 복수 출처: [1,2]
- 인용 예시: "IoT 센서 기반 실시간 수질 모니터링 체계를 구축한다" [1]

## 답변 구조
1. 질문에 대한 직접 답변
2. 근거 설명 (어떤 문서의 어느 부분에서 확인했는지)
3. 추가 관련 정보 (문서에 있는 경우만)

## 금지 사항
- 일반 상식이나 학습된 지식으로 답변하기
- 문서에 없는 내용 추가하기
- "아마도", "추측하건대" 등의 불확실한 표현 사용
- 문서 내용을 과도하게 확대 해석하기
```

### 3.2 검색 결과 없음 프롬프트

```
선택된 문서에서 질문과 관련된 정보를 찾을 수 없습니다.

다음을 시도해 보세요:
1. 다른 문서를 선택하세요.
2. 검색어를 바꿔서 다시 검색하세요.
3. 더 구체적인 질문으로 변경하세요.

※ 이 시스템은 실제 문서에서 확인된 정보만 답변합니다.
```

## 4. grounded_only 모드 상세

### 4.1 API 요청 구조

```json
{
  "query": "K-water의 AI 수자원 관리 시스템의 주요 기능은?",
  "document_ids": ["doc_001", "doc_002", "doc_003"],
  "answer_mode": "grounded_only",
  "include_citations": true,
  "max_tokens": 2000,
  "temperature": 0.1
}
```

### 4.2 answer_mode 옵션

| 모드 | 설명 | 사용 시점 |
| --- | --- | --- |
| grounded_only | 선택 문서만 근거로 답변 (기본) | 항상 |
| ~~creative~~ | ~~창의적 답변~~ | **사용 금지** |
| ~~mixed~~ | ~~문서 + 일반 지식~~ | **사용 금지** |

**중요**: weeslee-rag에서는 `grounded_only` 모드만 허용한다.

### 4.3 temperature 설정

```
temperature: 0.1 (고정)
```

낮은 temperature로 일관성 있고 사실적인 답변을 유도한다.

### 4.4 Context 구성

```python
def build_context(document_ids: List[str], query: str) -> str:
    context_parts = []

    for doc_id in document_ids:
        # 1. 관련 청크 검색 (document_id 필터링)
        chunks = search_chunks(query, filter={"document_id": doc_id}, top_k=5)

        # 2. 문서별 context 구성
        doc_context = f"""
## 문서: {chunks[0].file_name}

"""
        for i, chunk in enumerate(chunks):
            doc_context += f"""
### 섹션 {i+1} (페이지 {chunk.page_number})
{chunk.text}

"""
        context_parts.append(doc_context)

    return "\n".join(context_parts)
```

## 5. Citation 생성 규칙

### 5.1 Citation 구조

```json
{
  "index": 1,
  "document_id": "doc_001",
  "file_name": "제안요청서_2024_K-water.pdf",
  "page": 12,
  "chunk_id": "chunk_001_012",
  "chunk_text": "IoT 센서 기반 실시간 수질 모니터링 체계를 구축한다...",
  "relevance": 0.95
}
```

### 5.2 Citation 생성 로직

```python
def generate_citations(answer: str, chunks_used: List[Chunk]) -> List[Citation]:
    citations = []

    # 답변에서 인용 마커 추출
    citation_markers = extract_markers(answer)  # [1], [2], [1,2] 등

    for marker in citation_markers:
        # 마커에 해당하는 청크 매핑
        chunk = chunks_used[marker.index - 1]

        citation = Citation(
            index=marker.index,
            document_id=chunk.document_id,
            file_name=get_filename(chunk.document_id),
            page=chunk.page_number,
            chunk_id=chunk.chunk_id,
            chunk_text=chunk.text[:200] + "...",
            relevance=chunk.score
        )
        citations.append(citation)

    return citations
```

### 5.3 Citation 표시 형식 (UI)

```
답변:
K-water의 AI 수자원 관리 시스템의 주요 기능은 다음과 같습니다:

1. **실시간 수질 모니터링**: IoT 센서를 통한 24시간 수질 데이터 수집 및
   AI 기반 이상 탐지 [1]

2. **댐 운영 최적화**: 빅데이터 분석을 통한 방류량 예측 및
   최적 운영 의사결정 지원 [1,2]

3. **홍수 예측 시스템**: 기상 데이터와 수문 데이터를 결합한
   AI 모델로 72시간 사전 예측 [2,3]

───────────────────────────────────────────────
인용 출처:
[1] 제안요청서_2024_K-water.pdf (12페이지)
    "IoT 센서 기반 실시간 수질 모니터링 체계를 구축한다..."

[2] 최종보고서_2023_K-water_디지털트윈.pdf (45페이지)
    "댐 운영 최적화를 위한 AI 모델은 방류량 예측 정확도 95%를 달성..."

[3] 제안서_2024_수자원관리.pdf (8페이지)
    "홍수 예측 시스템은 72시간 사전 예측을 목표로 하며..."
```

## 6. 환각 탐지 및 경고

### 6.1 환각 의심 패턴

| 패턴 | 설명 | 대응 |
| --- | --- | --- |
| 인용 없는 구체적 수치 | "95%의 정확도" 등 | 경고 + 출처 요청 |
| 문서에 없는 고유명사 | 새로운 기관명, 기술명 | 경고 |
| 일반화된 지식 표현 | "일반적으로", "보통" | 경고 + 재생성 요청 |
| 미래 예측 | "~할 것이다" | 경고 |

### 6.2 Post-processing 검증

```python
def validate_answer(answer: str, context: str, citations: List[Citation]) -> dict:
    warnings = []

    # 1. 인용 없는 문장 탐지
    sentences = split_sentences(answer)
    for sentence in sentences:
        if has_specific_claim(sentence) and not has_citation(sentence):
            warnings.append({
                "type": "missing_citation",
                "sentence": sentence
            })

    # 2. Context에 없는 내용 탐지
    for sentence in sentences:
        if not is_grounded(sentence, context):
            warnings.append({
                "type": "possibly_hallucinated",
                "sentence": sentence
            })

    # 3. 신뢰도 계산
    confidence = 1.0 - (len(warnings) * 0.1)

    return {
        "warnings": warnings,
        "confidence": max(confidence, 0.0)
    }
```

### 6.3 경고 표시

```json
{
  "answer": "...",
  "citations": [...],
  "confidence": 0.85,
  "warning": "일부 내용이 제공된 문서에서 직접 확인되지 않을 수 있습니다. 원문을 확인해 주세요."
}
```

## 7. 사용자 인터페이스 가이드라인

### 7.1 검색 결과 화면

```
┌────────────────────────────────────────────────────────────────┐
│  검색 결과                                                     │
│                                                                │
│  ※ 아래 문서를 검토하고, 답변 생성에 사용할 문서를 선택하세요.   │
│                                                                │
│  ☐ 제안요청서_2024_K-water.pdf (점수: 0.92)                   │
│  ☐ 최종보고서_2023_K-water.pdf (점수: 0.88)                   │
│  ☐ 제안서_2024_수자원.pdf (점수: 0.85)                        │
│                                                                │
│  [선택 문서 기반 답변 생성]                                     │
│                                                                │
│  ⚠️ 선택한 문서의 내용만 근거로 답변이 생성됩니다.              │
└────────────────────────────────────────────────────────────────┘
```

### 7.2 답변 생성 화면

```
┌────────────────────────────────────────────────────────────────┐
│  AI 답변                                                       │
│                                                                │
│  ⓘ 이 답변은 선택한 3개 문서를 근거로 생성되었습니다.           │
│                                                                │
│  [답변 내용...]                                                │
│                                                                │
│  ───────────────────────────────────────────────────────────   │
│  📚 인용 출처                                                  │
│  [1] 제안요청서_2024_K-water.pdf (12p)                        │
│  [2] 최종보고서_2023_K-water.pdf (45p)                        │
│  [3] 제안서_2024_수자원.pdf (8p)                              │
│                                                                │
│  [답변 복사] [출처와 함께 복사] [원문 확인]                      │
└────────────────────────────────────────────────────────────────┘
```

### 7.3 신뢰도 낮음 경고

```
┌────────────────────────────────────────────────────────────────┐
│  ⚠️ 주의                                                       │
│                                                                │
│  이 답변의 신뢰도가 낮습니다. (75%)                             │
│  다음 내용은 원문에서 직접 확인해 주세요:                        │
│                                                                │
│  - "AI 모델의 정확도가 95%를 달성" → 원문 확인 필요             │
│                                                                │
│  [원문 확인하기]                                                │
└────────────────────────────────────────────────────────────────┘
```

## 8. 산출물 체크리스트

- [x] 환각 방지 5대 원칙 정의
- [x] 검색 → 선택 → 답변 흐름도
- [x] 시스템 프롬프트 정의
- [x] grounded_only 모드 상세 설계
- [x] Citation 생성 규칙
- [x] 환각 탐지 및 경고 로직
- [x] UI 가이드라인

---

작성일: 2026-05-21
작성자: Claude
다음 단계: Phase 8. admin.html UI 설계
