# LLM Wiki Service

## 1. 목적

LLM Wiki는 OCR, 메타데이터, 태그/키워드, FAISS, Graph 이후에 생성되는 보조 지식 계층이다.
원문 문서를 대체하지 않고, 다음 목적을 가진다.

- 프로젝트 단위 요약 지식 문서 생성
- 발주기관 단위 요약 지식 문서 생성
- 기술 키워드 단위 요약 지식 문서 생성
- `rag-assistant.html` 검색 결과의 보조 근거 제공
- 관리자 페이지에서 생성 상태와 미리보기 제공

## 2. 현재 구현 기준

현재 구현의 기준 API는 다음 두 계층이다.

- 관리자 API
  - `backend/app/api/admin_llm_wiki.py`
  - 생성 상태 조회, 미리보기, 내용 조회, 목록 조회
- 실행/생성 API
  - `backend/app/api/wiki.py`
  - 실제 프로젝트/기관/기술 Wiki 생성과 통계 처리

## 3. 저장 구조

### 3.1 source_id 기준 저장

프로젝트 Wiki는 `source_id` 기준 하위 폴더를 사용한다.

```text
data/wiki/<source_id>/projects/*.md
```

기관 Wiki와 기술 Wiki도 동일하게 `source_id` 기준 하위 폴더를 우선 사용한다.

```text
data/wiki/<source_id>/organizations/*.md
data/wiki/<source_id>/technologies/*.md
```

### 3.2 레거시 전역 경로

하위 `source_id` 없이 생성된 기존 파일은 아래 전역 경로를 사용한다.

```text
data/wiki/projects/*.md
data/wiki/organizations/*.md
data/wiki/technologies/*.md
```

## 4. API 계약

### 4.1 관리자 API

- `POST /api/admin/llm-wiki/build`
  - 비동기 빌드 시작
  - 입력:
    - `source_id`
    - `snapshot_id`
    - `wiki_type`
    - `model`
    - `max_wikis`
- `GET /api/admin/llm-wiki/status`
  - source 기준 빌드 상태 조회
- `GET /api/admin/llm-wiki/preview`
  - source 기준 미리보기 목록 반환
- `GET /api/admin/llm-wiki/content/{wiki_type}/{slug}`
  - Wiki 원문 조회
- `GET /api/admin/llm-wiki/list`
  - 관리자 표 전용 간단 목록 반환

### 4.2 실행 API

- `POST /api/wiki/build`
  - 프로젝트 Wiki 생성
- `POST /api/wiki/generate/by-project`
  - source/snapshot 기준 프로젝트 Wiki 생성
- `POST /api/wiki/generate/by-organization`
  - source 기준 기관 Wiki 생성
- `POST /api/wiki/generate/by-technology`
  - source 기준 기술 Wiki 생성
- `GET /api/wiki/stats`
  - source 기준 통계 조회

## 5. 관리자 페이지 연결 규칙

`frontend/admin.html`에서는 다음 규칙을 따른다.

- Wiki 생성 버튼:
  - `POST /api/admin/llm-wiki/build`
- Wiki 상태/미리보기:
  - `GET /api/admin/llm-wiki/status`
  - `GET /api/admin/llm-wiki/preview`
  - `GET /api/admin/llm-wiki/list`
- Wiki 탭 통계/기관별/기술별 생성:
  - `GET /api/wiki/stats?source_id=...`
  - `POST /api/wiki/generate/by-organization?source_id=...`
  - `POST /api/wiki/generate/by-project?source_id=...&snapshot=...`
  - `POST /api/wiki/generate/by-technology?source_id=...`

## 6. 현재 상태 점검 결과

2026-07-02 기준 현재 상태는 다음과 같다.

- 프로젝트 Wiki는 실제 생성되고 있음
- `source_id`별 `projects` 폴더에 저장되고 있음
- 기관 Wiki와 기술 Wiki는 `source_id` 기준 생성 계약으로 보완됨
- 관리자 페이지의 기존 `/admin/wiki/list` 참조는 `/admin/llm-wiki/list` 기준으로 정리 필요했고, 현재 코드에서 반영됨

## 7. 남은 과제

- 기관 Wiki/기술 Wiki의 검색 API 연동 강화
- Wiki 생성 결과에 `document_count`, `source_id`, `snapshot_id` 메타 포함 강화
- `rag-assistant.html`에서 Wiki 검색 결과와 Graph/FAISS 병합 품질 점검
- source별 `index.json` 또는 Wiki manifest 도입 여부 검토

## 8. 운영 원칙

- LLM Wiki는 원문 문서의 보조 계층이다.
- 검색 정확도 기준의 최우선 데이터는 원문 OCR, 청크, 메타데이터, Graph이다.
- Wiki는 요약/개요/탐색 보조 목적으로 사용한다.
