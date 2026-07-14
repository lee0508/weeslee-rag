# 한글 2018 추출 파일 (txt/csv) 우선 참조 모듈
# 작업일: 2026-07-14 - 단순화된 구조로 재작성
"""
OCR 전에 한글 2018에서 미리 추출한 txt/csv 파일을 찾아 사용합니다.

경로 매핑:
- Document Source: /mnt/w2_project/00. RAG 소스/01. RFP/문서.hwp
- 전처리 파일:     /data/weeslee/weeslee-mnt/00. RAG 소스/01. RFP/문서.txt

사용법:
1. 로컬에서 한글 2018으로 hwp/pdf → txt/csv 변환
2. C:\xampp\htdocs\weeslee-mnt\ 파일을 서버 /data/weeslee/weeslee-mnt/로 복사
3. Dataset Builder에서 OCR 작업 시 자동으로 txt/csv 우선 사용
"""
from pathlib import Path
from typing import Any, Optional, Tuple

# 경로 매핑 설정
SOURCE_ROOT = "/mnt/w2_project/"
PRECONVERTED_ROOT = "/data/weeslee/weeslee-mnt/"

# 지원 확장자 및 인코딩
ARTIFACT_EXTENSIONS = (".txt", ".csv")
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "euc-kr")


def _read_text_file(file_path: Path) -> str:
    """다중 인코딩으로 텍스트 파일 읽기."""
    for encoding in TEXT_ENCODINGS:
        try:
            return file_path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        except OSError:
            return ""
    return ""


def _find_preconverted_path(source_path: str) -> Optional[Path]:
    """
    원본 파일 경로에서 전처리 파일 경로를 찾습니다.

    예시:
    - 입력: /mnt/w2_project/00. RAG 소스/01. RFP/문서.hwp
    - 출력: /data/weeslee/weeslee-mnt/00. RAG 소스/01. RFP/문서.txt
    """
    normalized = source_path.replace("\\", "/")

    # /mnt/w2_project/ → /data/weeslee/weeslee-mnt/ 매핑
    if normalized.startswith(SOURCE_ROOT):
        relative = normalized[len(SOURCE_ROOT):]
        base_path = Path(PRECONVERTED_ROOT + relative)

        for ext in ARTIFACT_EXTENSIONS:
            candidate = base_path.with_suffix(ext)
            if candidate.is_file():
                return candidate

    # 이미 /data/weeslee/weeslee-mnt/ 경로인 경우
    if normalized.startswith(PRECONVERTED_ROOT):
        base_path = Path(normalized)

        for ext in ARTIFACT_EXTENSIONS:
            candidate = base_path.with_suffix(ext)
            if candidate.is_file():
                return candidate

    return None


def load_preconverted_artifacts(file_path: str) -> Optional[dict[str, Any]]:
    """
    전처리된 txt/csv 파일이 있으면 내용을 반환합니다.

    Returns:
        {"text": 내용, "paths": [파일경로], "types": ["txt" or "csv"]}
        또는 None (파일 없음)
    """
    preconverted = _find_preconverted_path(file_path)
    if not preconverted:
        return None

    text = _read_text_file(preconverted)
    if not text or len(text.strip()) < 50:
        return None

    ext_type = preconverted.suffix.lstrip(".")

    return {
        "text": text.strip(),
        "paths": [str(preconverted)],
        "types": [ext_type],
    }


def load_preconverted_txt(file_path: str) -> Optional[Tuple[str, str]]:
    """간단한 인터페이스: (텍스트, 파일경로) 반환."""
    result = load_preconverted_artifacts(file_path)
    if result:
        return result["text"], result["paths"][0]
    return None
