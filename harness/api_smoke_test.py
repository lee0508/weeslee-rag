"""
weeslee-rag API Smoke Test

목적:
- Claude가 코드 수정 후 주요 API가 죽지 않았는지 빠르게 확인
- 프론트엔드 연결 전에 백엔드 응답 구조 확인

사용:
python harness/api_smoke_test.py
"""

import requests
import sys

API_BASE_URL = "http://127.0.0.1:9284"

TEST_ENDPOINTS = [
    {
        "name": "Health Check",
        "method": "GET",
        "url": "/api/health"
    },
    {
        "name": "Document List",
        "method": "GET",
        "url": "/api/documents"
    },
    {
        "name": "Admin Documents",
        "method": "GET",
        "url": "/api/admin/documents"
    }
]


def request_endpoint(endpoint: dict) -> bool:
    """
    단일 API endpoint를 테스트한다.
    """

    url = API_BASE_URL + endpoint["url"]

    try:
        if endpoint["method"] == "GET":
            response = requests.get(url, timeout=10)
        else:
            print(f"[SKIP] Unsupported method: {endpoint['method']}")
            return True

        if response.status_code in [200, 204]:
            print(f"[OK] {endpoint['name']} - {url}")
            return True

        print(f"[FAIL] {endpoint['name']} - {url}")
        print(f"  status_code={response.status_code}")
        print(f"  response={response.text[:500]}")
        return False

    except Exception as e:
        print(f"[ERROR] {endpoint['name']} - {url}")
        print(f"  {e}")
        return False


def main():
    """
    전체 smoke test 실행
    """

    results = []

    for endpoint in TEST_ENDPOINTS:
        result = request_endpoint(endpoint)
        results.append(result)

    if all(results):
        print("\nAPI Smoke Test 성공")
        sys.exit(0)

    print("\nAPI Smoke Test 실패")
    sys.exit(1)


if __name__ == "__main__":
    main()
