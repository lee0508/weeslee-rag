1. 현재 구조 분석 결과
현재 FastAPI 구조

main.py를 보면 현재 API 라우터 구조는 상당히 좋습니다.

현재 등록:

app.include_router(admin_router, prefix="/api", tags=["Admin"])
app.include_router(ocr_router, prefix="/api", tags=["OCR"])
app.include_router(knowledge_sources_router, prefix="/api", tags=["Knowledge Sources"])
app.include_router(rag_router, prefix="/api", tags=["RAG"])

이 구조는 이미:

Admin
OCR
Knowledge Source
RAG

분리가 되어 있어 향후 확장이 쉽습니다.

즉:

백엔드 구조는 재사용 가능

입니다.

2. 가장 중요한 문제

현재 가장 큰 문제는 이것입니다.

문제 1 — admin.html과 RAG가 서로 다른 저장소 사용

현재 admin.html은:

문서 처리
→ MySQL
→ ChromaDB

방향으로 설계되었습니다.

하지만 실제 운영 중인 RAG는:

manifest
→ metadata jsonl
→ chunk
→ nomic embedding
→ FAISS

입니다.

즉:

admin 처리 결과
≠
RAG 검색 결과

입니다.

이건 반드시 통합해야 합니다.

문제 2 — 진행률이 실제 작업과 연결 안 됨

현재 코드:

updateProgress(100, 'completed', 'Processing complete!');

즉 실제로는:

한 번 기다렸다가
마지막에만 100%

입니다.

하지만 실제 파이프라인은:

extract
metadata
chunk
embedding
FAISS

로 시간이 오래 걸립니다.

문제 3 — admin.html은 현재 "문서 DB 관리자"

현재 UI는 사실상:

Document Pipeline Admin

입니다.

하지만 지금 프로젝트 핵심은:

FAISS RAG 운영

입니다.

즉 admin 역할 자체를 바꿔야 합니다.

3. 최종 개발 방향
반드시 Option A

추천 방향:

admin.html
=
FAISS RAG 운영 콘솔

입니다.

4. admin.html을 어떻게 바꿔야 하는가?

현재 UI는 상당히 잘 만들었습니다.

따라서 전체 재작성할 필요는 없습니다.

유지할 부분

유지 추천:

✓ Sidebar
✓ File Browser
✓ Stats Panel
✓ Results Panel
✓ Progress UI
✓ Selected File UI
변경할 부분
기존
Target Collection
변경
Target Batch Name

예:

snapshot_2026-05-07_batch-004
기존
Store
변경
FAISS Index
기존 Progress
Extract → Analyze → Chunk → Embed → Store
변경 추천
Manifest
→ Extract
→ Metadata
→ Chunk
→ Embed
→ FAISS
→ Activate
5. 가장 중요한 구조 변경
기존
POST /api/admin/documents/process
변경 추천
POST /api/admin/faiss/jobs
요청 예시
{
  "batch_name": "snapshot_2026-05-07_batch-004",
  "files": [
    "ISP/project1/file1.pdf",
    "ISP/project1/file2.hwpx"
  ],
  "options": {
    "use_ocr": true,
    "build_category_indexes": true,
    "activate_after_build": true
  }
}
6. 가장 중요한 구현 포인트
실제 shell/python script 연결

지금 가장 좋은 구조는:

admin UI
→ FastAPI Job
→ subprocess 실행
→ 기존 python scripts 호출

입니다.

즉 기존 코드 재사용.

추천 구조
# backend/app/services/faiss_job_service.py

async def run_faiss_pipeline(job_id, payload):

    # 1. manifest
    subprocess.run([
        "python3",
        "backend/scripts/extract_manifest_batch.py",
        "--batch", payload["batch_name"]
    ])

    # 2. chunk
    subprocess.run([
        "python3",
        "backend/scripts/build_chunk_batch.py"
    ])

    # 3. embedding
    subprocess.run([
        "python3",
        "backend/scripts/build_faiss_index.py"
    ])

    # 4. category indexes
    subprocess.run([
        "python3",
        "backend/scripts/build_category_indexes.py"
    ])
7. SSE 반드시 연결

현재 구조에서 가장 중요한 추가 작업입니다.

왜 필요한가?

현재 embedding 작업은:

2,000~7,000 chunk

수준이라 시간이 걸립니다.

사용자는:

멈춘 것처럼 보임

현상이 발생합니다.

추천 구현
# backend/app/api/admin_faiss.py

@router.get("/admin/faiss/jobs/{job_id}/stream")
async def stream_job(job_id: str):

    async def event_generator():
        while True:
            status = get_job_status(job_id)

            yield {
                "event": "progress",
                "data": json.dumps(status)
            }

            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())
프론트 연결
const evt = new EventSource(
  `${API_BASE}/admin/faiss/jobs/${jobId}/stream`
);

evt.onmessage = (event) => {
    const data = JSON.parse(event.data);

    updateProgress(
        data.percent,
        data.stage,
        data.message
    );
};
8. active index 개념 추가 필요

현재 매우 중요합니다.

추천 파일
data/indexes/faiss/active_index.json
예시
{
  "active_index": "snapshot_2026-05-06_batch-003_combined.index",
  "metadata": "snapshot_2026-05-06_batch-003_combined_metadata.jsonl",
  "activated_at": "2026-05-06T11:20:00"
}
왜 중요한가?

현재 batch-002, batch-003가 동시에 존재합니다.

rag.py가 무엇을 읽을지
명확히 해야 함

입니다.

9. admin.html에서 추가해야 할 기능
반드시 추천
기능 1 — Active Index 표시
Current Active Index:
snapshot_2026-05-06_batch-003
기능 2 — Index Switch
[Activate]
[Rollback]
기능 3 — Benchmark Run
Run Retrieval Benchmark
기능 4 — Category Index 상태
✓ rfp
✓ proposal
✓ kickoff
⚠ final_report
⚠ presentation
기능 5 — Ollama 상태

현재 timeout 문제 때문에 매우 중요합니다.

Model: gemma4
Status: running
Queue: 2
Timeout: 300s
10. 현재 가장 좋은 개발 순서
Step 1
API_BASE 수정
Step 2
admin.html 용어를 FAISS 기준으로 변경
Step 3
POST /api/admin/faiss/jobs 구현
Step 4
기존 Python scripts 연결
Step 5
SSE progress 구현
Step 6
active_index.json 구현
Step 7
rag.py active index 자동 로드
가장 중요한 최종 판단

현재 구조는:

새 시스템을 만들 단계 ❌

가 아니라,

이미 검증된 FAISS RAG 시스템을
운영 가능한 관리 콘솔로 연결하는 단계 ⭕

입니다.

그리고 업로드한 admin.html은 UI 자체는 매우 좋습니다.

핵심은:

MySQL/ChromaDB 방향을 제거하고
FAISS 운영 파이프라인에 연결

하는 것입니다.