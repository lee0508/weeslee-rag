# Step 7: FAISS 인덱스 빌드 스크립트
"""
사용법:
    cd /data/weeslee/weeslee-rag/backend/databuilder
    python3 run_index_step7.py

주의: Step 6 (임베딩)이 완료된 후 실행해야 합니다.
"""
import sys
import time
import os
import httpx

API_BASE = "http://localhost:8080"
COLLECTION_NAME = "weeslee_rag_main"
SOURCE_ID = os.environ.get("SOURCE_ID", "").strip()
SNAPSHOT_ID = os.environ.get("SNAPSHOT_ID", "").strip()
INDEX_TYPE = "flat"  # flat, ivf, hnsw
METRIC = "ip"  # ip (내적, 코사인 유사도), l2 (유클리드)
TIMEOUT = 1800  # 30분


def main():
    print("=" * 60)
    print("Step 7: FAISS 인덱스 빌드 시작")
    print(f"컬렉션: {COLLECTION_NAME}")
    print(f"Source ID: {SOURCE_ID or '(미지정)'}")
    print(f"Snapshot ID: {SNAPSHOT_ID or '(자동 생성)'}")
    print(f"인덱스 타입: {INDEX_TYPE}")
    print(f"메트릭: {METRIC}")
    print("=" * 60)

    start_time = time.time()

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            # FAISS 인덱스 빌드 요청
            print("\nFAISS 인덱스 빌드 요청 중...")
            payload = {
                "collection_name": COLLECTION_NAME,
                "index_type": INDEX_TYPE,
                "metric": METRIC,
                "normalize": True,
            }
            if SOURCE_ID:
                payload["source_id"] = SOURCE_ID
            if SNAPSHOT_ID:
                payload["snapshot_id"] = SNAPSHOT_ID
            response = client.post(
                f"{API_BASE}/api/admin/dataset-builder/step7/build",
                json=payload
            )

            if response.status_code == 200:
                result = response.json()
                elapsed = time.time() - start_time

                print("\n" + "=" * 60)
                print("FAISS 인덱스 빌드 완료!")
                print("=" * 60)
                print(f"컬렉션: {result.get('collection_name', COLLECTION_NAME)}")
                print(f"Source ID: {result.get('source_id', SOURCE_ID or '')}")
                print(f"Snapshot ID: {result.get('snapshot_id', SNAPSHOT_ID or '')}")
                print(f"총 벡터 수: {result.get('total_vectors', 0)}")
                print(f"인덱싱된 문서 수: {result.get('documents_indexed', 0)}")
                print(f"임베딩 차원: {result.get('embedding_dim', 0)}")
                print(f"인덱스 경로: {result.get('index_path', '')}")
                print(f"소요 시간: {elapsed:.1f}초")
                print("=" * 60)

                return 0
            else:
                print(f"\n오류 발생: {response.status_code}")
                print(response.text)
                return 1

    except Exception as e:
        print(f"\n오류 발생: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
