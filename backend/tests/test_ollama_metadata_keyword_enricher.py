from backend.app.services.metadata_auto_generator import MetadataAutoGenerator
from backend.app.services.ollama_metadata_keyword_enricher import OllamaMetadataKeywordEnricher
from backend.app.services.tag_keyword_generator import TagKeywordGenerator


def _make_generator() -> TagKeywordGenerator:
    generator = TagKeywordGenerator.__new__(TagKeywordGenerator)
    generator.stopwords = {"기반", "위한", "수립", "관련", "및", "등"}
    generator.keyword_aliases = {
        "AI": ["AI", "인공지능"],
        "플랫폼": ["플랫폼"],
    }
    return generator


def test_ollama_enricher_extracts_json_object():
    raw = '```json\n{"keywords":["의사소통 관리"],"confidence":0.9}\n```'
    data = OllamaMetadataKeywordEnricher._extract_json_object(raw)
    assert data["keywords"] == ["의사소통 관리"]
    assert data["confidence"] == 0.9


def test_tag_keyword_generator_merges_rule_and_llm_keywords():
    generator = _make_generator()
    merged = generator._merge_keyword_candidates(
        ["AI", "플랫폼"],
        ["의사소통 관리", "플랫폼"],
        ["커뮤니케이션 관리"],
    )
    assert merged == ["AI", "플랫폼", "의사소통 관리", "커뮤니케이션 관리"]


def test_metadata_auto_generator_llm_merge_prefers_non_empty_values():
    generator = MetadataAutoGenerator()
    rule_result = generator.extract_metadata("프로젝트관리_테스트.pptx", "")
    llm_result = {
        "project_name": "공공 AI 플랫폼 구축 ISP",
        "organization": "행정안전부",
        "technology_tags": ["AI", "플랫폼"],
        "business_tags": ["ISP"],
        "summary": "공공기관 AI 플랫폼 구축 방향을 다룬 제안서다.",
        "confidence": 0.88,
        "reason": "LLM 기반 보강",
    }

    merged = {**rule_result}
    for key, value in llm_result.items():
        if key.endswith("_tags") and value:
            base_values = rule_result.get(key) or []
            merged[key] = list(dict.fromkeys([*base_values, *value]))[:8]
        elif key == "confidence":
            merged[key] = max(rule_result.get("confidence", 0.0), float(value or 0.0))
        elif key == "reason":
            merged[key] = value or "LLM 기반 추출 + 규칙 기반 보정"
        elif value not in ("", None, []):
            merged[key] = value

    assert merged["project_name"] == "공공 AI 플랫폼 구축 ISP"
    assert merged["organization"] == "행정안전부"
    assert "AI" in merged["technology_tags"]
    assert merged["confidence"] >= rule_result["confidence"]
