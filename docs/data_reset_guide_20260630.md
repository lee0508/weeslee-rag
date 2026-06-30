# weeslee-rag 서비스 데이터 초기화 가이드

작성일: 2026-06-30

## 개요

이 문서는 weeslee-rag 서비스에서 사용하는 모든 데이터(파일 및 데이터베이스)를 초기화하는 방법을 설명합니다.

---

## 1. 파일 시스템 데이터

### 1.1 데이터 디렉토리 구조

| 경로 | 크기 | 설명 | 재생성 방법 |
|------|------|------|------------|
| `data/extracted_text/` | 5.4GB | OCR 추출 텍스트 (레거시) | Step 4 재실행 |
| `data/processed_text/` | 239MB | 처리된 텍스트/청크 | Step 4-5 재실행 |
| `data/staged/` | 7.0GB | 청크 JSONL, 매니페스트, 상태 파일 | Step 1-5 재실행 |
| `data/indexes/faiss/` | 543MB | FAISS 벡터 인덱스 | Step 6-7 재실행 |
| `data/indexes/graph/` | 28MB | 지식 그래프 노드/엣지 | Step 8 재실행 |
| `data/faiss/` | 14MB | FAISS 인덱스 (레거시) | - |
| `data/graph/` | 4KB | 그래프 데이터 (레거시) | - |
| `data/tag_keyword/` | 142MB | 태그/키워드 데이터 (Step 6 임베딩에서 생성) | Step 6 재실행 |
| `data/wiki/` | 284KB | LLM 위키 페이지 | Step 9 재실행 |
| `data/ontology/` | 252KB | 온톨로지 스키마 | 설정 파일 |
| `data/snapshots/` | 16KB | 스냅샷 매니페스트 | 스냅샷 생성 시 |
| `data/reviews/` | 152KB | RAG 리뷰 저장소 (/api/rag/reviews) | API 사용 시 생성 |
| `data/raw/` | 4.9GB | 원본 문서 복사본 (레거시) | - |
| `uploads/` | 64KB | 업로드된 파일 (backend/app/core/config.py 설정) | 사용자 업로드 |
| `data/logs/` | 12KB | 로그 파일 | 자동 생성 |
| `data/config/` | 32KB | 설정 파일 | - |
| `data/metadata/` | 4KB | 메타데이터 설정 | - |

### 1.2 설정 파일 (JSON)

| 파일명 | 설명 | 초기화 시 영향 |
|--------|------|---------------|
| `data/active_index.json` | 활성 FAISS 인덱스 설정 | 활성화 상태 초기화 |
| `data/active_snapshot.json` | 활성 스냅샷 설정 | 활성화 상태 초기화 |
| `data/platform_store.json` | Document Source, Client 설정 | UI에서 재생성 필요 |

---

## 2. 데이터베이스 테이블

### 2.1 MySQL 테이블 목록

| 테이블명 | 설명 | 초기화 대상 |
|----------|------|------------|
| `documents` | 문서 메타데이터 | ✅ Yes |
| `document_chunks` | 문서 청크 | ✅ Yes |
| `document_metadata` | 확장 메타데이터 | ✅ Yes |
| `document_sections` | 문서 섹션 구조 | ✅ Yes |
| `document_pages` | 문서 페이지 정보 | ✅ Yes |
| `processing_logs` | 처리 로그 | ✅ Yes |
| `collections` | 컬렉션 정의 | ⚠️ 선택적 |
| `prompts` | 프롬프트 템플릿 | ⚠️ 선택적 |
| `prompt_variables` | 프롬프트 변수 | ⚠️ 선택적 |
| `execution_logs` | 실행 이력 | ⚠️ 선택적 |
| `reference_logs` | 참조 이력 | ⚠️ 선택적 |
| `clients` | 클라이언트 설정 | ⚠️ 선택적 |
| `document_sources` | Document Source 설정 | ⚠️ 선택적 |
| `llm_settings` | LLM 설정 | ⚠️ 선택적 |

---

## 3. 초기화 명령어

### 3.1 파일 시스템 전체 초기화

```bash
# 서버에서 실행
cd /data/weeslee/weeslee-rag

# 1. 생성 데이터 삭제 (원본 문서는 유지)
rm -rf data/extracted_text/*
rm -rf data/processed_text/*
rm -rf data/staged/*
rm -rf data/indexes/faiss/*
rm -rf data/indexes/graph/*
rm -rf data/faiss/*
rm -rf data/graph/*
rm -rf data/tag_keyword/*
rm -rf data/wiki/*
rm -rf data/snapshots/*
rm -rf data/reviews/*       # RAG 리뷰 저장소 (Step 3과 무관)
rm -rf data/logs/*
rm -rf uploads/*            # 업로드 파일 (선택)

# 2. 설정 파일 삭제
rm -f data/active_index.json
rm -f data/active_snapshot.json
rm -f data/platform_store.json

# 3. 레거시 데이터 삭제 (선택)
rm -rf data/raw/*
```

### 3.2 데이터베이스 초기화

```sql
-- MySQL에서 실행
-- 문서 관련 테이블 초기화 (순서 중요 - 외래키 제약)
SET FOREIGN_KEY_CHECKS = 0;

TRUNCATE TABLE document_chunks;
TRUNCATE TABLE document_metadata;
TRUNCATE TABLE document_sections;
TRUNCATE TABLE document_pages;
TRUNCATE TABLE processing_logs;
TRUNCATE TABLE documents;

-- 선택적: 설정 테이블도 초기화
-- TRUNCATE TABLE collections;
-- TRUNCATE TABLE prompts;
-- TRUNCATE TABLE prompt_variables;
-- TRUNCATE TABLE execution_logs;
-- TRUNCATE TABLE reference_logs;
-- TRUNCATE TABLE clients;
-- TRUNCATE TABLE document_sources;
-- TRUNCATE TABLE llm_settings;

SET FOREIGN_KEY_CHECKS = 1;
```

### 3.3 서비스 재시작

```bash
# 서비스 재시작
pkill -f 'uvicorn.*8080'
cd /data/weeslee/weeslee-rag/backend
source ../.venv/bin/activate
nohup uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/weeslee-rag.log 2>&1 &
```

---

## 4. 부분 초기화 시나리오

### 4.1 특정 Document Source만 초기화

```bash
# source_id 예: src_20260630_101756_02b6aa
SOURCE_ID="src_20260630_101756_02b6aa"

# 해당 소스의 데이터만 삭제
rm -rf data/staged/*${SOURCE_ID}*
rm -rf data/indexes/faiss/*${SOURCE_ID}*
rm -rf data/indexes/graph/${SOURCE_ID}
```

### 4.2 FAISS 인덱스만 재생성

```bash
# 인덱스 삭제
rm -rf data/indexes/faiss/*
rm -f data/active_index.json

# Step 6-7 재실행 (UI 또는 API)
```

### 4.3 지식 그래프만 재생성

```bash
# 그래프 삭제
rm -rf data/indexes/graph/*

# Step 8 재실행 (UI 또는 API)
```

---

## 5. 주의사항

1. **원본 문서 보존**: `/mnt/w2_project` (마운트된 네트워크 드라이브)의 원본 문서는 영향받지 않음
2. **백업 권장**: 중요한 설정(prompts, collections)은 초기화 전 백업 권장
3. **외래키 제약**: DB 테이블 삭제 시 순서 준수 필요 (자식 테이블 먼저)
4. **서비스 중단**: 초기화 중 서비스 일시 중단 권장
5. **Step 3 메타데이터 검수**: 검수 상태는 `document_metadata` 테이블에 저장됨. `data/reviews/`는 RAG 리뷰 API 저장소이며 Step 3과 무관함
6. **업로드 경로**: 실제 업로드 경로는 `./uploads` (backend/app/core/config.py 설정 기준)

---

## 6. 데이터 재생성 파이프라인

초기화 후 데이터 재생성 순서:

1. **Document Source 생성** (UI: Admin > Document Sources)
2. **Step 1**: 소스 스캔 (파일 목록 수집)
3. **Step 2**: 메타데이터 자동 추출
4. **Step 3**: 메타데이터 검토 (선택)
5. **Step 4**: 텍스트 추출/OCR
6. **Step 5**: 청킹
7. **Step 6**: 임베딩 생성
8. **Step 7**: FAISS 인덱스 빌드
9. **Step 8**: 지식 그래프 빌드
10. **Step 9**: LLM 위키 생성
11. **Step 10**: 검색 품질 테스트
12. **활성화**: 스냅샷 활성화

---

## 7. 관련 ID 필드 체계

| ID 유형 | 형식 예시 | 생성 시점 |
|---------|----------|----------|
| source_id | `src_20260630_101756_02b6aa` | Document Source 생성 |
| dataset_id | `dataset_src_20260630_101756_02b6aa_20260630_101756` | Dataset 생성 |
| snapshot_id | `snapshot_20260630_src_20260630_101756_02b6aa_V1` | FAISS 빌드 |
| document_id | `114477` | 문서 스캔 |
| document_uid | `1153e6853ff29932dd6315c3246a63f9af5e86a1` | 청킹 (SHA1 해시) |

---

*문서 끝*
