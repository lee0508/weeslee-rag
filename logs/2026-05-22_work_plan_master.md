# 2026-05-22 작업 마스터 플랜

## 작업 진행자: Claude
## 작업 일자: 2026-05-22
## 상태: 진행 중

---

## 1. 전체 방향 (질문답변 기준)

### 1.1 핵심 원칙

1. FAISS Collection은 단일 통합 Collection (`weeslee_rag_main`)
2. 문서 분류는 metadata로 관리 (collection_key, document_group, document_category)
3. project_name은 파일명에서 추출 (폴더 아님)
4. LLM Wiki는 project_name 중심
5. GraphRAG는 관계 보조 엔진 (최종 답변 근거 아님)
6. 최종 답변은 원문 chunk + evidence_documents 기반

### 1.2 metadata 기준

```json
{
  "collection_name": "weeslee_rag_main",
  "collection_key": "제안서",
  "document_group": "제안서",
  "document_category": "전략및방법론",
  "project_name": "AI 기반 e-감사시스템 재구축 ISP 컨설팅",
  "file_name": "전략및방법론_AI 기반 e-감사시스템 재구축 ISP 컨설팅.pptx",
  "relative_path": "02. 제안서/01. 전략및방법론/..."
}
```

---

## 2. 작업 우선순위

| 순위 | Step | 작업 | 상태 | 담당 |
|------|------|------|------|------|
| 1 | 19 | rag-assistant.html 인코딩 추가 정리 | ✅ 완료 | Claude |
| 2 | 20 | collection_key 기준 수정 (직접상위폴더 → 문서대분류) | ✅ 완료 | Claude |
| 3 | 21 | metadata 파싱 기준 추가 (document_group, document_category, project_name) | ✅ 완료 | Claude |
| 4 | 22 | assemble_rag_response.py 중복 build_prompt() 정리 | ✅ 완료 | Claude |
| 5 | 23 | 브라우저 E2E 테스트 (샘플 쿼리 5건) | ⚠️ 부분완료 | Claude |
| 6 | 24 | Grounded Answer + Citation 형식 구현 | ✅ 완료 | Claude |

---

## 3. 완료된 작업 (Step 01~18)

| Step | 작업 | 완료일 |
|------|------|--------|
| 01-04 | admin.html Docs 레이아웃 | 2026-05-22 |
| 05-08 | Source Documents 페이지 | 2026-05-22 |
| 09-10 | FAISS Index, JSON Graph 연결 | 2026-05-22 |
| 11-12 | Wizard Collection 메타 동기화 | 2026-05-22 |
| 13-14 | 폴더 기준 Collection 생성 | 2026-05-22 |
| 15 | 답변 근거 파일 노출 | 2026-05-22 |
| 16 | 관리자 검색 테스트 경로 노출 | 2026-05-22 |
| 17 | 답변 프롬프트 근거 파일 강제 | 2026-05-22 |
| 18 | rag-assistant.html 인코딩 복구 (부분) | 2026-05-22 |

---

## 4. 테스트 쿼리 (검증용)

1. AI 기반 e-감사시스템 재구축 ISP 컨설팅 관련 문서를 찾아줘
2. K-water 고유플랫폼 구축 전략계획 수립 용역 관련 문서를 찾아줘
3. 소방출동 데이터 기반 AI빅데이터 분석시스템 구축 ISP 관련 산출물을 찾아줘
4. 전략및방법론 문서 중 AX 관련 사업을 찾아줘
5. 환경분석 산출물 중 인공지능 전환 AX 관련 문서를 찾아줘

---

## 5. 배포 기준

- 로컬 테스트 완료 후 원격 서버 배포
- 서버: weeslee@218.148.21.12:2222
- 경로: /data/weeslee/weeslee-rag

---

작성일: 2026-05-22
최종 수정: 2026-05-22
