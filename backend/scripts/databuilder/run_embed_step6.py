# Step 6: 임베딩 생성 스크립트 (bge-m3 모델 사용)
"""
사용법:
    cd /data/weeslee/weeslee-rag/backend/databuilder
    python3 run_embed_step6.py

백그라운드 실행:
    nohup python3 run_embed_step6.py > embed_job.log 2>&1 &
    tail -f embed_job.log
"""
import sys
import time
import httpx

API_BASE = "http://localhost:8080"
EMBED_MODEL = "bge-m3:latest"
BATCH_SIZE = 8  # GPU 메모리에 따라 조절 (8~16 권장)
TIMEOUT = 7200  # 2시간


def main():
    print("=" * 60)
    print("Step 6: 임베딩 생성 시작")
    print(f"모델: {EMBED_MODEL}")
    print(f"배치 크기: {BATCH_SIZE}")
    print("=" * 60)

    start_time = time.time()

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            # 임베딩 생성 요청
            print("\n임베딩 생성 요청 중...")
            response = client.post(
                f"{API_BASE}/api/admin/dataset-builder/step6/embed",
                json={
                    "model": EMBED_MODEL,
                    "force_rebuild": True,
                    "batch_size": BATCH_SIZE,
                    "retry_count": 3
                }
            )

            if response.status_code == 200:
                result = response.json()
                elapsed = time.time() - start_time

                print("\n" + "=" * 60)
                print("임베딩 생성 완료!")
                print("=" * 60)
                print(f"처리된 문서: {result.get('processed', 0)}")
                print(f"실패한 문서: {result.get('failed', 0)}")
                print(f"건너뛴 문서: {result.get('skipped', 0)}")
                print(f"총 임베딩 수: {result.get('total_embeddings', 0)}")
                print(f"임베딩 차원: {result.get('embedding_dim', 0)}")
                print(f"모델: {result.get('model', EMBED_MODEL)}")
                print(f"소요 시간: {elapsed/60:.1f}분")
                print("=" * 60)

                return 0
            else:
                print(f"\n오류 발생: {response.status_code}")
                print(response.text)
                return 1

    except httpx.TimeoutException:
        print("\n타임아웃 발생. 작업이 아직 진행 중일 수 있습니다.")
        print("웹 UI에서 Step 6 상태를 확인하세요.")
        return 1
    except Exception as e:
        print(f"\n오류 발생: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
