# FAISS 인덱스 활성화 스크립트
"""
사용법:
    cd /data/weeslee/weeslee-rag/backend/databuilder
    python3 activate_index.py

Step 7 완료 후 새 인덱스를 활성화합니다.
"""
import sys
import httpx

API_BASE = "http://localhost:8080"


def list_indexes():
    """사용 가능한 인덱스 목록 조회"""
    with httpx.Client(timeout=30) as client:
        response = client.get(f"{API_BASE}/api/admin/faiss/indexes")
        if response.status_code == 200:
            return response.json().get("indexes", [])
    return []


def activate_index(snapshot: str):
    """인덱스 활성화"""
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{API_BASE}/api/admin/faiss/activate",
            json={"snapshot": snapshot}
        )
        return response.status_code == 200, response.json()


def check_health():
    """시스템 상태 확인"""
    with httpx.Client(timeout=30) as client:
        response = client.get(f"{API_BASE}/api/health/all")
        if response.status_code == 200:
            return response.json()
    return None


def main():
    print("=" * 60)
    print("FAISS 인덱스 활성화")
    print("=" * 60)

    # 인덱스 목록 조회
    print("\n사용 가능한 인덱스 목록:")
    indexes = list_indexes()

    if not indexes:
        print("  (없음)")
        return 1

    for i, idx in enumerate(indexes):
        active = " [활성]" if idx.get("is_active") else ""
        print(f"  {i+1}. {idx.get('snapshot') or '(이름없음)'} - {idx.get('chunk_count', 0)} chunks{active}")

    # 사용자 선택
    print("\n활성화할 인덱스 번호를 입력하세요 (0: 취소):")
    try:
        choice = int(input("> "))
        if choice == 0:
            print("취소되었습니다.")
            return 0
        if choice < 1 or choice > len(indexes):
            print("잘못된 선택입니다.")
            return 1

        selected = indexes[choice - 1]
        snapshot = selected.get("snapshot", "")

        print(f"\n'{snapshot}' 인덱스를 활성화합니다...")
        success, result = activate_index(snapshot)

        if success:
            print("\n" + "=" * 60)
            print("인덱스 활성화 완료!")
            print("=" * 60)
            stats = result.get("stats", {})
            print(f"스냅샷: {result.get('snapshot')}")
            print(f"청크 수: {stats.get('chunk_count', 0)}")
            print(f"인덱스 크기: {stats.get('index_size_mb', 0):.1f} MB")

            # 상태 확인
            print("\n시스템 상태 확인 중...")
            health = check_health()
            if health:
                status = health.get("status", "unknown")
                faiss = health.get("components", {}).get("faiss", {})
                print(f"전체 상태: {status}")
                print(f"FAISS 상태: {faiss.get('status', 'unknown')}")

            return 0
        else:
            print(f"\n활성화 실패: {result}")
            return 1

    except ValueError:
        print("숫자를 입력하세요.")
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
