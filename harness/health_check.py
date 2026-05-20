"""
weeslee-rag Health Check Script

목적:
- Claude가 코드 수정 후 서버 상태를 자동으로 점검하기 위한 스크립트
- Flask/FastAPI 서버가 정상 응답하는지 확인
- Ollama 연결 상태 확인
- 기본 API 상태 확인

사용:
python harness/health_check.py
"""

import requests
import sys

# ------------------------------------------------------------
# 기본 설정
# ------------------------------------------------------------
API_BASE_URL = "http://127.0.0.1:9284"
OLLAMA_URL = "http://127.0.0.1:11434"


def check_url(name: str, url: str) -> bool:
    """
    지정한 URL이 정상 응답하는지 확인한다.

    Parameters
    ----------
    name : str
        점검 대상 이름
    url : str
        점검할 URL

    Returns
    -------
    bool
        정상 응답 여부
    """

    try:
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            print(f"[OK] {name}: {url}")
            return True

        print(f"[FAIL] {name}: status_code={response.status_code}, url={url}")
        return False

    except Exception as e:
        print(f"[ERROR] {name}: {url}")
        print(f"  {e}")
        return False


def main():
    """
    전체 health check 실행
    """

    results = []

    # ------------------------------------------------------------
    # weeslee-rag API 서버 점검
    # ------------------------------------------------------------
    results.append(
        check_url(
            name="weeslee-rag API Health",
            url=f"{API_BASE_URL}/api/health"
        )
    )

    # ------------------------------------------------------------
    # Ollama 서버 점검
    # ------------------------------------------------------------
    results.append(
        check_url(
            name="Ollama API",
            url=f"{OLLAMA_URL}/api/tags"
        )
    )

    # ------------------------------------------------------------
    # 결과 판단
    # ------------------------------------------------------------
    if all(results):
        print("\n전체 Health Check 성공")
        sys.exit(0)

    print("\n일부 Health Check 실패")
    sys.exit(1)


if __name__ == "__main__":
    main()
