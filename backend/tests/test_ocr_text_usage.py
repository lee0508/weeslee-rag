from pathlib import Path

from backend.app.services.tag_keyword_generator import TagKeywordGenerator
from backend.scripts import build_project_wiki


def _make_generator() -> TagKeywordGenerator:
    generator = TagKeywordGenerator.__new__(TagKeywordGenerator)
    generator.stopwords = {
        "기반", "위한", "수립", "사업", "용역", "구축", "고도화",
        "컨설팅", "연구", "활용", "도입", "방안", "강화", "통합",
        "재구축", "정보화전략계획", "정보전략계획", "및", "을", "를",
        "의", "에", "대한", "관련", "등", "년", "차", "단계",
        "문서", "자료", "내용", "구성", "작성", "검토", "추진",
    }
    generator.keyword_aliases = {
        "AI": ["AI", "인공지능"],
        "LLM": ["LLM", "거대언어모델"],
        "플랫폼": ["플랫폼", "Platform"],
    }
    return generator


def test_tag_keyword_generator_extracts_ocr_section_and_keywords():
    generator = _make_generator()
    text = """
    프로젝트관리 섹션에서는 의사소통 관리와 품질관리 절차를 정의한다.
    기술및기능 장에서는 AI 플랫폼과 LLM 기반 검색 기능을 설명한다.
    """

    section_tags = generator._extract_section_tags(text)
    keywords = generator._extract_keywords(text)

    assert "프로젝트관리" in section_tags
    assert "기술및기능" in section_tags
    assert "AI" in keywords
    assert "LLM" in keywords
    assert "의사소통" in "".join(keywords) or "의사소통관리" in "".join(keywords)


def test_collect_ocr_evidence_reads_processed_text_by_folder(tmp_path, monkeypatch):
    processed_dir = tmp_path / "processed_text"
    doc_dir = processed_dir / "101"
    doc_dir.mkdir(parents=True)

    (doc_dir / "ocr_report.json").write_text(
        """
        {
          "document_id": "101",
          "file_name": "프로젝트관리_테스트.pptx",
          "source_id": "src_test",
          "relative_path": "00. RAG 소스/프로젝트A/프로젝트관리_테스트.pptx"
        }
        """.strip(),
        encoding="utf-8",
    )
    (doc_dir / "full_text.txt").write_text(
        "프로젝트관리 섹션에서는 의사소통 관리 계획과 보고 체계를 설명한다. "
        "기술및기능 섹션에서는 AI 플랫폼 구조를 정리한다.",
        encoding="utf-8",
    )

    monkeypatch.setattr(build_project_wiki, "PROCESSED_TEXT_DIR", processed_dir)

    snippets = build_project_wiki.collect_ocr_evidence(
        "프로젝트A",
        {"source_id": "src_test"},
        limit=4,
    )

    assert snippets
    assert snippets[0].startswith("[OCR:프로젝트관리_테스트.pptx]")
    assert "의사소통 관리" in snippets[0]
