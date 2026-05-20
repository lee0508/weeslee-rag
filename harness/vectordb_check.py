"""
weeslee-rag VectorDB Check Script

목적:
- VectorDB 경로 존재 여부 확인
- FAISS index 파일 존재 여부 확인
- metadata 파일 존재 여부 확인
- Claude가 RAG 검색 오류를 분석할 때 기본 점검용으로 사용

사용:
python harness/vectordb_check.py
"""

from pathlib import Path
import json
import sys

# 프로젝트 환경에 맞게 수정 가능
VECTORDB_BASE_PATH = Path("data/indexes/faiss")


def check_path(path: Path, description: str) -> bool:
    """
    파일 또는 디렉토리 존재 여부 확인
    """

    if path.exists():
        print(f"[OK] {description}: {path}")
        return True

    print(f"[MISSING] {description}: {path}")
    return False


def main():
    """
    VectorDB 기본 구조 확인
    """

    results = []

    results.append(
        check_path(
            VECTORDB_BASE_PATH,
            "VectorDB Base Directory"
        )
    )

    # ------------------------------------------------------------
    # FAISS index 파일 검색
    # ------------------------------------------------------------
    index_files = list(VECTORDB_BASE_PATH.glob("*.index")) if VECTORDB_BASE_PATH.exists() else []

    if index_files:
        print(f"[OK] FAISS index files found: {len(index_files)}")
        for file in index_files[:5]:
            print(f"  - {file}")
        results.append(True)
    else:
        print("[MISSING] FAISS index file not found")
        results.append(False)

    # ------------------------------------------------------------
    # metadata 파일 검색
    # ------------------------------------------------------------
    metadata_files = (
        list(VECTORDB_BASE_PATH.glob("*.json")) + 
        list(VECTORDB_BASE_PATH.glob("*.jsonl"))
    )

    if metadata_files:
        print(f"[OK] Metadata files found: {len(metadata_files)}")
        for file in metadata_files[:5]:
            print(f"  - {file}")
        results.append(True)
    else:
        print("[WARNING] Metadata file not found")
        results.append(False)

    if all(results):
        print("\nVectorDB Check 성공")
        sys.exit(0)

    print("\nVectorDB Check 확인 필요")
    sys.exit(1)


if __name__ == "__main__":
    main()
