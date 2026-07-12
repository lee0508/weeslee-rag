# CSV 페이지 파서(;[N] 마커) 단위 테스트
from app.services.page_source_loader import parse_csv_pages, load_csv_page_units


def test_parse_csv_pages_splits_on_marker():
    csv_text = "\n".join([
        ";[1]",
        "표지 제목",
        "발주기관",
        ";[2]",
        "1. 사업개요",
        "가. 배경",
        "나. 목적",
        ";[3]",
        "2. 추진방안",
    ])
    pages = parse_csv_pages(csv_text)

    assert [p["page_num"] for p in pages] == [1, 2, 3]
    assert pages[0]["text"] == "표지 제목\n발주기관"
    assert pages[1]["text"] == "1. 사업개요\n가. 배경\n나. 목적"
    assert pages[2]["text"] == "2. 추진방안"
    assert pages[1]["char_count"] == len(pages[1]["text"])


def test_parse_csv_pages_preserves_full_content_not_truncated():
    """페이지당 8줄 캡 없이 모든 줄이 보존되는지 확인 (원문 손실 방지 핵심)."""
    body_lines = [f"항목 {i}: 세부 내용을 담은 본문 라인" for i in range(1, 21)]  # 20줄
    csv_text = ";[5]\n" + "\n".join(body_lines)

    pages = parse_csv_pages(csv_text)

    assert len(pages) == 1
    assert pages[0]["page_num"] == 5
    # 20줄이 모두 남아야 한다 (8줄 요약이 아님)
    assert pages[0]["text"].count("\n") == 19
    for line in body_lines:
        assert line in pages[0]["text"]


def test_parse_csv_pages_multicell_row_merged_with_space():
    csv_text = ";[1]\n항목,값1,값2\n설명"
    pages = parse_csv_pages(csv_text)

    assert len(pages) == 1
    assert pages[0]["text"] == "항목 값1 값2\n설명"


def test_parse_csv_pages_returns_empty_without_marker():
    csv_text = "제목\n본문\n결론"
    assert parse_csv_pages(csv_text) == []


def test_parse_csv_pages_skips_empty_page_body():
    csv_text = ";[1]\n내용 A\n;[2]\n;[3]\n내용 C"
    pages = parse_csv_pages(csv_text)

    # 페이지 2는 본문이 없으므로 제외
    assert [p["page_num"] for p in pages] == [1, 3]


def test_load_csv_page_units_returns_none_for_missing(tmp_path):
    fake = tmp_path / "nonexistent.hwp"
    assert load_csv_page_units(str(fake)) is None
