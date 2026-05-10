# 작업계획 — Rerank 구현 + Project Wiki 확장 + 시연회 준비

**작업일**: 2026-05-08 (오후 13:00~)  
**시연회**: 2026-05-12 (화)  
**작업자**: 이동현  
**참조 문서**: 260507_개발고도방안.md, 260507_품질개선안.md

---

## 현재 상태 요약

| 항목 | 상태 |
|------|------|
| Search Mode (general/bid_project/rfp_analysis) | ✅ 완료 |
| query expansion (expand_bid_query / expand_rfp_query) | ✅ 완료 |
| Graph View → RAG 검색 연결 | ✅ 완료 |
| Answer Review 저장/조회 | ✅ 완료 |
| Wiki API + 빌드 스크립트 | ✅ 완료 |
| Benchmark search-only 고정 | ✅ 완료 |
| **Rerank 키워드 가산점** | ❌ 미구현 |
| **Project Wiki 데이터** | ⚠️ 3개만 존재 (91개 프로젝트 중) |

---

## 작업 1: Rerank 구현 (13:00~14:30)

### 목표

`/api/rag/query` 응답 결과를 키워드 관련성 점수로 재정렬.  
query expansion으로 검색 범위를 넓힌 뒤, 핵심 키워드 매칭 문서를 상위로 올린다.

### 구현 위치

```
backend/app/services/reranker.py  ← 신규 생성
backend/app/api/rag.py            ← rerank 호출 추가
```

### reranker.py 설계

```python
# 키워드 도메인 가중치 테이블
_DOMAIN_WEIGHTS = {
    "isp": 2.0, "ismp": 2.0, "oda": 1.5,
    "ai": 1.5, "ax": 1.5, "gpt": 1.5, "llm": 1.5,
    "고도화": 1.2, "플랫폼": 1.2, "클라우드": 1.0,
    "빅데이터": 1.0, "스마트": 1.0,
}

def rerank(query: str, chunks: list[dict]) -> list[dict]:
    """
    각 chunk의 text에서 query 키워드 매칭 횟수 × 도메인 가중치로 score 계산.
    기존 FAISS distance score와 결합하여 최종 정렬.
    """
```

### rag.py 변경 포인트

```python
# mode=bid_project / rfp_analysis 일 때만 rerank 적용
from app.services.reranker import rerank

if request.mode in ("bid_project", "rfp_analysis"):
    chunks = rerank(effective_query, chunks)
```

### 검증 방법

```bash
# 서버에서 직접 테스트
curl -s http://localhost:8080/api/rag/query -H "Content-Type: application/json" \
  -d '{"query":"Tech-GPT ISP 고도화","mode":"bid_project","category":"proposal","top_k":5}'
```

기대 결과: ISP/AI/GPT 포함 문서가 상위 정렬됨.

---

## 작업 2: Project Wiki 대량 생성 (14:30~16:00)

### 목표

현재 3개(ax-ismp, k-water-isp, moj-digital-platform)에서 주요 프로젝트 전체로 확장.  
Graph View에서 Wiki 버튼이 활성화되도록 한다.

### 대상 프로젝트 선정 기준

Graph View에 표시된 91개 프로젝트 중 **문서 3개 이상** 프로젝트 우선:

```
- 농정원 AGRIX (4개 문서)
- 통계청 통계지리정보서비스 ISP (4개 문서)
- 법무부_디지털플랫폼 교육강화 (4개 문서)
- 국토지리정보원 (8개 문서)
- AI 기반 지능형 진로교육정보망 (4개 문서)
- K-water 데이터허브 (4개 문서)
- 범죄예방정책_거대언어모델 도입활용방안 (5개 문서)
- 스토킹 전자장치 부과제도 관련 ISP (5개 문서)
- 농정원 수준진단 사업 (5개 문서)
- 소방출동 데이터 AI빅데이터 분석시스템 ISP (5개 문서)
- (이하 3개 이상 프로젝트 전체)
```

### 실행 방법

```bash
# 전체 프로젝트 일괄 빌드 (POST /api/wiki/build, slug 없이 호출)
curl -s -X POST http://localhost:8080/api/wiki/build | python3 -m json.tool

# 또는 특정 slug 지정
curl -s -X POST "http://localhost:8080/api/wiki/build?slug=농정원-agrix" | python3 -m json.tool
```

### 검증 방법

```bash
# 생성된 wiki 목록 확인
curl -s http://localhost:8080/api/wiki/projects | python3 -m json.tool

# admin.html Graph View에서 Wiki 버튼 활성화 확인
# → 프로젝트 클릭 시 우측 Wiki 버튼 표시 여부
```

---

## 작업 3: 통합 검증 (16:00~17:00)

### 체크리스트

#### Rerank 검증
- [ ] `mode=bid_project`로 "Tech-GPT ISP 고도화" 검색 → ISP/AI 문서 상위 정렬
- [ ] `mode=general`로 동일 쿼리 → rerank 미적용 (기존 FAISS 순서)
- [ ] `mode=rfp_analysis`로 "RFP 과업지시서 요구사항 분석" 검색 → rfp/kickoff 문서 상위

#### Wiki 검증
- [ ] `/api/wiki/projects` 목록에 신규 wiki 10개 이상 표시
- [ ] admin.html Graph View → 프로젝트 클릭 → Wiki 버튼 표시 → 모달 정상 로드
- [ ] wiki 내용에 프로젝트명 / 카테고리 / 참조 문서 정보 포함

#### 회귀 검증
- [ ] `/api/health` healthy
- [ ] `mode=general` 기존 RAG 검색 정상 동작
- [ ] Answer Review 저장/불러오기 정상
- [ ] Benchmark (evaluation.py) 실행 시 100% PASS 유지

---

## 결과물

| 산출물 | 경로 |
|--------|------|
| reranker.py | `backend/app/services/reranker.py` |
| rag.py 수정 | `backend/app/api/rag.py` |
| wiki 파일들 | `data/wiki/projects/*.md` (10개 이상) |
| 작업 결과 문서 | `260508_작업결과_Rerank_Wiki확장.md` |

---

---

## 시연회 일정 (2026-05-12)

### 전체 개발 일정

| 날짜 | 작업 | 내용 |
| --- | --- | --- |
| **5/8(목) 오후** | 개발 | Rerank 구현 + Wiki 대량 생성 |
| **5/9(금)** | 검증 + 리허설 | 통합 검증, 시연 시나리오 리허설, 품질 조정 |
| **5/10~11(토~일)** | 버퍼 | Rerank 품질 조정 / Wiki 내용 검토 (필요 시) |
| **5/12(화)** | **시연회** | — |

### 시연 가능 여부 판단

**가능** — 핵심 기능 80% 완료 상태이며, 오늘 작업으로 나머지 완성 예정.  
5/9 금요일이 안전 버퍼로 작동한다.

### 시연 핵심 플로우 (권장 시나리오)

```text
1. rag-assistant.html 접속
2. Search Mode: "Bid Project Search" 선택
3. 사업명 입력 (예: "Tech-GPT 성능 고도화 ISP")
   → 키워드 자동 확장 확인 (ISP / AI / GPT / AX / 정보화전략계획 …)
4. 검색 실행 → 관련 제안서 / 최종보고서 상위 노출 확인
5. 검색 결과 파일 다운로드
6. admin.html → Graph View 전환
   → 91개 프로젝트 시각화 확인
   → 프로젝트 클릭 → RAG 검색 / Wiki 보기 버튼 동작 확인
7. Answer Review 탭 → 저장된 검색 이력 확인
```

### 시연 전 사전 점검 항목 (5/12 오전)

- [ ] `https://server.weeslee.co.kr/weeslee-rag/frontend/rag-assistant.html` 외부 접속 속도 확인
- [ ] `/api/health` 응답 확인
- [ ] Graph View 프로젝트 목록 91개 정상 표시 확인
- [ ] bid_project 모드 검색 1회 테스트
- [ ] Wiki 모달 1개 이상 정상 로드 확인

### 위험 요소 및 대응

| 위험 | 대응 |
| --- | --- |
| Wiki 생성 내용 품질 미흡 | 시연 전 3~5개 수동 검토 후 내용 보완 |
| 외부 네트워크 속도 저하 | 사전 접속 테스트, 필요 시 내부망 기준 시연 |
| Rerank 결과 순서 부자연스러움 | 가중치 테이블 조정 (5/9 금요일 버퍼 활용) |

---

## 참고: 미적용 항목 (후순위)

아래는 260507_개발고도방안.md 기준 후순위로 이번 작업에서 제외:

- Next.js 전환
- MySQL 기반 관리자 기능
- 사용자 로그인 / 권한 관리
- Neo4j 도입
- Organization 노드 추가 (Graph 2차)
- LLM 기반 Graph Edge 보정 (Graph 2차)
