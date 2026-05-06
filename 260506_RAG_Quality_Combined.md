# RAG 품질 평가 보고서 — Combined Index

**날짜**: 2026-05-06  
**인덱스**: `snapshot_2026-05-06_combined-v1` (batch-002 + batch-003)  
**벡터 수**: 6,760 (batch-002: 2,054 + batch-003: 4,706)  
**문서 수**: 61 (batch-002: 27 + batch-003: 34)  
**임베딩**: nomic-embed-text (768-dim), FAISS IndexFlatIP

---

## 핵심 지표 비교

| 지표 | batch-002 (27 docs) | combined (61 docs) | 변화 |
|------|--------------------|--------------------|------|
| 평균 키워드 적중률 | **95.0%** | **95.0%** | → 유지 |
| 평균 검색 문서 수 | **3.2개** | **3.2개** | → 유지 |
| 평균 답변 길이 | 1,525자 | 1,545자 | ↑ 소폭 증가 |
| 100% 적중 쿼리 수 | 8/10 | 8/10 | → 유지 |

**핵심 결론**: 기존 ISP/ISMP 쿼리 품질 **회귀 없음**. batch-003 추가로 인한 노이즈 없음.

---

## 신규 추가된 기능 효과

### project_name 추출 (rerank)
이제 검색 결과에 `project_name` 필드가 포함됩니다:

| 쿼리 | 반환된 프로젝트 (예시) |
|------|----------------------|
| AX 전환 전략 | 법무부_성범죄백서이행, AX기반 차세대 ISMP |
| ISP 최종 산출물 | k-water 데이터허브플랫폼_ISP, AX기반 ISMP |
| 착수보고 일정 | 법무부_성범죄백서이행, AX기반 ISMP |

→ project_name 기반 rerank가 활성화 (source_path 파싱으로 추출)

### max_chunks_per_doc=3 (default)
- DOC-20260506-000004 (595청크)의 결과 지배 방지
- hit_count 최대 3으로 제한됨 (이전: 제한 없음)

---

## 주요 관찰

### 긍정
- **회귀 없음**: batch-003 추가 (34 docs, 4,706 chunks)에도 기존 쿼리 품질 유지
- **project_name 포함**: 검색 결과에 프로젝트명 노출 → Wiki 준비 완료
- **RFP 쿼리 개선 가능성**: 새로운 rfp 문서 (NCPF-외부용 제안요청서, 발췌본 정성적제안서 등) 추가됨

### 관찰 사항
- ISP 중심 10개 테스트 쿼리에서 수치 변화 없음 → batch-003 도메인(법무부, 과기정통부, 재난정신건강)은 별도 평가 필요
- Q8 (final_report 검색): 여전히 2개 문서만 반환 — rfp/kickoff 카테고리 문서 수 아직 부족

---

## 내일(5/7) 예정 작업

| 작업 | 설명 |
|------|------|
| Category pre-filter | `build_category_indexes.py` 실행 → rfp/proposal/kickoff/final_report/presentation 서브 인덱스 빌드 |
| 신규 도메인 쿼리 테스트 | batch-003 추가 도메인 (법무부, 과기정통부, 재난정신건강) 대상 새 테스트 쿼리 |
| Project Wiki 스크립트 | 각 프로젝트의 상위 청크 → LLM으로 구조화된 wiki.md 생성 |

---

## 오늘(5/6) 완료 항목

| 항목 | 상태 |
|------|------|
| P1-1: max_chunks_per_doc | ✅ 서버 배포 |
| P1-2: metadata 정규화 (project_name, folder_year) | ✅ 코드 완성 |
| P1-3: category filter (post-filter → pre-filter 자동 선택) | ✅ API 구현 |
| P1-4: project_name rerank 보너스 | ✅ 서버 배포 |
| batch-003 추출 | ✅ 34 success, 4 failed |
| batch-003 청킹 | ✅ 4,706 chunks |
| combined FAISS 인덱스 빌드 | ✅ 6,760 vectors, 61 docs |
| .env 업데이트 + uvicorn 재시작 | ✅ |
| build_category_indexes.py 작성 | ✅ 내일 실행 예정 |
