# 2026-04-27 문서 그래프 스키마 초안

## 1. 목적

위즐리앤컴퍼니 문서 중앙화 시스템에서, 단순 벡터 검색을 넘어서
`RFP 분석 -> 과거 유사 문서 탐색 -> 제안서 초안 작성 지원`을 가능하게 하는 문서 관계 그래프의 기본 스키마를 정의한다.

## 2. 그래프 설계 원칙

1. 모든 추천은 근거를 남긴다.
2. 추출값과 추론값을 구분한다.
3. 문서 자체보다 `프로젝트`, `기관`, `요구사항`, `방법론`, `산출물` 관계를 우선 모델링한다.
4. 그래프는 FAISS를 대체하지 않고 보완한다.

## 3. 핵심 노드

### 3.1 Document

속성:
- `document_id`
- `title`
- `document_type`
- `extension`
- `source_path`
- `snapshot_path`
- `year`
- `language`
- `security_level`
- `extraction_status`
- `ocr_required`

### 3.2 Project

속성:
- `project_id`
- `project_name`
- `project_year`
- `industry_domain`
- `bid_type`
- `status`

### 3.3 Organization

속성:
- `organization_id`
- `name`
- `role`
  - `client`
  - `vendor`
  - `partner`
- `sector`
  - `public`
  - `private`

### 3.4 DocumentType

예:
- `rfp`
- `proposal`
- `kickoff`
- `final_report`
- `presentation`

### 3.5 Section

속성:
- `section_id`
- `document_id`
- `heading`
- `order_no`
- `page_start`
- `page_end`
- `chunk_count`

### 3.6 Requirement

속성:
- `requirement_id`
- `requirement_text`
- `requirement_type`
  - `scope`
  - `deliverable`
  - `schedule`
  - `evaluation`
  - `technical`

### 3.7 Methodology

속성:
- `methodology_id`
- `name`
- `description`
- `domain`

### 3.8 Deliverable

속성:
- `deliverable_id`
- `name`
- `deliverable_type`
- `phase`

### 3.9 Chunk

속성:
- `chunk_id`
- `document_id`
- `section_id`
- `chunk_order`
- `text`
- `embedding_id`
- `token_count`

## 4. 핵심 엣지

### 4.1 문서 소속 관계

- `Document -> belongs_to -> Project`
- `Document -> has_type -> DocumentType`
- `Document -> created_for -> Organization`
- `Document -> created_by -> Organization`

### 4.2 문서 내부 구조

- `Document -> contains -> Section`
- `Section -> contains -> Chunk`
- `Section -> mentions -> Requirement`
- `Section -> describes -> Methodology`
- `Section -> defines -> Deliverable`

### 4.3 프로젝트 관계

- `Proposal -> responds_to -> RFP`
- `Kickoff -> starts -> Project`
- `FinalReport -> closes -> Project`
- `Presentation -> summarizes -> Document`

### 4.4 유사성 및 재사용

- `Document -> similar_to -> Document`
- `Section -> reused_in -> Section`
- `Methodology -> reused_in -> Proposal`
- `Requirement -> addressed_by -> Section`

## 5. provenance 규칙

모든 노드/엣지에는 아래 provenance 중 하나를 붙인다.

- `EXTRACTED`
  - 문서 원문에서 직접 확인됨
- `INFERRED`
  - 문맥/규칙 기반으로 추론됨
- `AMBIGUOUS`
  - 후보는 있으나 확정이 어려움

예:
- 문서 파일명에서 `제안요청서`를 읽어 `DocumentType=rfp`를 지정하면 `EXTRACTED`
- 프로젝트명 유사성으로 `Proposal -> responds_to -> RFP`를 연결하면 `INFERRED`
- 기관명이 여러 후보와 충돌하면 `AMBIGUOUS`

## 6. 검색 결합 방식

### 6.1 1차 검색

1. 업로드된 RFP 또는 질의문을 chunking
2. FAISS에서 유사 chunk 검색
3. metadata filter로 연도, 기관, 문서 유형 필터

### 6.2 2차 그래프 확장

1. 유사 chunk가 속한 Document 확인
2. Document가 속한 Project 확인
3. 같은 Project의 Proposal, Kickoff, FinalReport 탐색
4. 같은 Organization 또는 Methodology로 확장

### 6.3 설명 생성

추천 결과에는 아래 설명을 붙인다.

1. 동일 기관 또는 유사 기관
2. 동일 사업 유형
3. 동일 요구사항 키워드
4. 같은 프로젝트의 선행/후행 문서
5. 동일 방법론 재사용 이력

## 7. 예시 질의

### 7.1 질의

`이 RFP와 유사한 공공기관 ISP 제안서를 찾아줘`

### 7.2 기대 그래프 탐색

1. 입력 RFP에서 `Requirement`, `Organization`, `Project domain` 추출
2. 유사 `Requirement`를 가진 과거 `RFP` 탐색
3. 해당 `RFP`와 연결된 `Proposal` 탐색
4. 같은 `Methodology` 또는 `Deliverable`이 있는 `FinalReport` 탐색

## 8. 1차 구현 범위

1. `Document`
2. `Project`
3. `Organization`
4. `DocumentType`
5. `Section`
6. `Chunk`
7. `Requirement`

1차에서는 위 노드와 기본 엣지만 구현하면 충분하다.

## 9. 다음 구현 항목

1. metadata JSON schema에 `project_name`, `organization_client`, `document_type` 추가
2. chunk metadata에 `section_heading`, `page_no`, `project_id` 추가
3. `graph_nodes.jsonl`, `graph_edges.jsonl` 산출 포맷 설계
4. 이후 FAISS 결과와 graph expansion 결합
