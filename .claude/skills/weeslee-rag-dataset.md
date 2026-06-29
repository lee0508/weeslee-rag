# weeslee-rag 데이터셋 관리 스킬

---
name: weeslee-rag-dataset
description: weeslee-rag 프로젝트의 데이터셋 구축 파이프라인 가이드. Document Source, Dataset Builder, Knowledge Graph, LLM Wiki, Publish 기능을 다룬다.
version: 1.0.0
---

## 개요

weeslee-rag 프로젝트에서 검색용 데이터셋을 구축하고 배포하는 전체 파이프라인을 설명한다.

## 1. Document Source

원본 문서 폴더를 등록하는 곳이다.

### 기능
- 네트워크 드라이브나 로컬 폴더 경로를 등록
- 등록된 폴더의 문서 목록 스캔 및 메타데이터 추출
- 지원 형식: PDF, HWP, HWPX, DOCX, XLSX

### 관련 파일
- `backend/app/api/admin.py` - 소스 등록 API
- `backend/app/services/rag_source_pipeline.py` - 문서 스캔 로직

### 주요 API
```
POST /api/admin/sources          # 소스 폴더 등록
GET  /api/admin/sources          # 등록된 소스 목록
GET  /api/admin/sources/{id}     # 소스 상세 정보
```

## 2. Dataset Builder

등록된 문서를 읽어서 검색 가능한 VectorDB/FAISS 데이터셋을 만드는 곳이다.

### 파이프라인 단계
1. **문서 추출** - 원본 문서에서 텍스트 추출
2. **청크 분할** - 검색 단위로 텍스트 분할
3. **임베딩 생성** - 벡터 임베딩 계산
4. **FAISS 인덱스 빌드** - 검색용 인덱스 생성

### 관련 파일
- `backend/app/api/admin_dataset_builder.py` - 빌더 API
- `backend/scripts/extract_manifest_batch.py` - 문서 추출
- `backend/scripts/build_chunk_batch.py` - 청크 생성
- `backend/scripts/build_faiss_index.py` - FAISS 인덱스 빌드

### 주요 API
```
POST /api/admin/dataset/build    # 데이터셋 빌드 시작
GET  /api/admin/dataset/status   # 빌드 상태 조회
GET  /api/admin/dataset/list     # 생성된 데이터셋 목록
```

## 3. Knowledge Graph

문서, 프로젝트, 기관, 기술, 키워드 관계를 노드와 엣지로 만드는 곳이다.

### 노드 타입
- `Document` - 문서
- `Project` - 프로젝트
- `Organization` - 기관
- `Technology` - 기술/솔루션
- `Keyword` - 키워드

### 엣지 타입
- `BELONGS_TO` - 문서 → 프로젝트
- `EXECUTED_BY` - 프로젝트 → 기관
- `USES` - 프로젝트 → 기술
- `TAGGED_WITH` - 문서 → 키워드

### 관련 파일
- `backend/app/api/graph.py` - 그래프 API
- `backend/app/services/knowledge_graph.py` - 그래프 서비스
- `backend/scripts/build_graph_jsonl.py` - 그래프 데이터 생성

### 주요 API
```
POST /api/graph/build            # 그래프 빌드
GET  /api/graph/summary          # 그래프 통계
GET  /api/graph/search           # 그래프 검색
```

## 4. LLM Wiki

문서 내용을 요약·구조화해서 AI가 참고할 수 있는 위키를 만드는 곳이다.

### 위키 구조
- 프로젝트별 요약 페이지
- 기관별 프로필 페이지
- 기술별 사용 사례 페이지

### 관련 파일
- `backend/app/api/wiki.py` - 위키 API
- `backend/scripts/build_wiki_pages.py` - 위키 페이지 생성
- `data/wiki/` - 생성된 위키 데이터

### 주요 API
```
POST /api/wiki/build             # 위키 빌드
GET  /api/wiki/pages             # 위키 페이지 목록
GET  /api/wiki/pages/{id}        # 위키 페이지 내용
```

## 5. Publish

생성된 Dataset, Knowledge Graph, LLM Wiki 중에서 사용자 검색 화면에 적용할 버전을 선택하는 곳이다.

### 버전 관리
- 각 빌드 결과물은 타임스탬프 기반 버전으로 저장
- 활성 버전(active)과 대기 버전(staged) 구분
- 롤백 기능 지원

### 관련 파일
- `backend/app/api/admin_publish.py` - 배포 API
- `backend/app/api/faiss_admin.py` - FAISS 인덱스 활성화

### 주요 API
```
GET  /api/admin/publish/versions # 버전 목록
POST /api/admin/publish/activate # 버전 활성화
POST /api/admin/publish/rollback # 이전 버전으로 롤백
```

## 워크플로우

### 전체 데이터셋 구축 순서
1. Document Source에서 문서 폴더 등록
2. Dataset Builder로 FAISS 인덱스 생성
3. Knowledge Graph로 관계 데이터 구축
4. LLM Wiki로 요약 위키 생성
5. Publish에서 원하는 버전 활성화

### 증분 업데이트
- 새 문서 추가 시 해당 문서만 처리
- 변경된 문서 감지 및 재처리
- 삭제된 문서 인덱스에서 제거

## 관리자 UI

`frontend/admin.html`에서 위 모든 기능을 GUI로 조작할 수 있다.

### 탭 구성
- **Document Source** 탭 - 소스 폴더 관리
- **Dataset Builder** 탭 - 빌드 실행 및 모니터링
- **Knowledge Graph** 탭 - 그래프 시각화 및 검색
- **LLM Wiki** 탭 - 위키 페이지 관리
- **Publish** 탭 - 버전 선택 및 배포
