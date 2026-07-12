# 원문 CSV(;[N] 페이지 마커)를 페이지 단위 원문으로 로드하는 모듈
"""
Page Source Loader

`01. RFP` 폴더의 수동 변환 CSV는 각 페이지 경계를 첫 셀 `;[N]` 마커로 보존한다.
이 모듈은 그 CSV를 찾아 페이지 단위 원문 리스트로 파싱한다.

- 페이지 경계: 첫 셀이 `;[N]` 인 행 (N = 실제 페이지 번호, 1..N 순차)
- 페이지 본문: 다음 마커 전까지의 모든 행 (표 행은 셀을 공백으로 병합)
- 반환 형식은 Step4 `ProcessingResult.pages` 와 동일한 스키마를 따른다.

경로 해석은 preconverted_txt_fallback 의 후보 경로 로직을 재사용해
`/mnt/w2_project/...` 원본 경로를 `/data/weeslee/weeslee-mnt/...` 사본으로 매핑한다.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Optional

from app.extractors.preconverted_txt_fallback import (
    _candidate_artifact_paths,
    _read_text,
)

# 첫 셀이 정확히 ";[N]" 형태인 행을 페이지 마커로 인식한다.
_PAGE_MARKER_RE = re.compile(r"^\s*;\s*\[(\d+)\]\s*$")


def _row_to_line(row: list[str]) -> str:
    """CSV 한 행을 텍스트 한 줄로 변환한다. (다중 셀은 공백으로 병합)"""
    cells = [str(cell or "").strip() for cell in row if str(cell or "").strip()]
    return " ".join(cells).strip()


def parse_csv_pages(csv_text: str) -> list[dict[str, Any]]:
    """`;[N]` 마커 기준으로 CSV 텍스트를 페이지 단위로 분리한다.

    Returns:
        [{"page_num": int, "text": str, "char_count": int}, ...]
        마커가 하나도 없으면 빈 리스트.
    """
    rows = list(csv.reader(csv_text.splitlines()))

    # (row_index, page_num) 마커 위치 수집
    markers: list[tuple[int, int]] = []
    for idx, row in enumerate(rows):
        first_cell = str(row[0]) if row else ""
        match = _PAGE_MARKER_RE.match(first_cell)
        if match:
            markers.append((idx, int(match.group(1))))

    if not markers:
        return []

    pages: list[dict[str, Any]] = []
    for marker_pos, (row_idx, page_num) in enumerate(markers):
        next_row_idx = markers[marker_pos + 1][0] if marker_pos + 1 < len(markers) else len(rows)
        body_rows = rows[row_idx + 1:next_row_idx]
        lines = [line for line in (_row_to_line(row) for row in body_rows) if line]
        page_text = "\n".join(lines).strip()
        if not page_text:
            continue
        pages.append({
            "page_num": page_num,
            "text": page_text,
            "char_count": len(page_text),
        })

    return pages


def load_csv_page_units(file_path: str) -> Optional[dict[str, Any]]:
    """원본 파일 경로에 대응하는 preconverted CSV를 찾아 페이지 단위로 로드한다.

    Returns:
        {
            "pages": [{"page_num", "text", "char_count"}, ...],
            "full_text": "페이지 원문 결합",
            "csv_path": "사용한 CSV 경로",
            "page_count": int,
        }
        대응 CSV가 없거나 페이지 마커가 없으면 None.
    """
    for candidate in _candidate_artifact_paths(file_path, ".csv"):
        if not candidate.is_file():
            continue

        raw_text = _read_text(candidate)
        if not raw_text.strip():
            continue

        pages = parse_csv_pages(raw_text)
        if not pages:
            continue

        full_text = "\n".join(page["text"] for page in pages).strip()
        return {
            "pages": pages,
            "full_text": full_text,
            "csv_path": str(candidate),
            "page_count": len(pages),
        }

    return None
