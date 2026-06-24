# 확장 Knowledge Graph 스키마 및 동의어 매핑 정의
# -*- coding: utf-8 -*-
"""
Knowledge Graph schema definitions and synonym mappings.

확장 노드 타입:
- organization: 발주기관 (동의어 지원)
- technology: 기술 키워드 (계층 구조)
- methodology: 방법론 (ISP, ISMP 등)
- domain: 도메인/분야

확장 엣지 타입:
- 발주: organization → project
- 적용기술: project → technology
- 사용방법론: project → methodology
- 관련도메인: project → domain
- 동의어: entity ↔ entity
- 유사기술: technology ↔ technology

설정 파일 기반:
- data/config/entity_mappings.json에서 동의어/계층 구조 로드
- 코드 수정 없이 설정 파일만 변경하여 확장 가능
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from functools import lru_cache

# 설정 파일 경로
_CONFIG_DIR = Path(__file__).resolve().parents[3] / "data" / "config"
_ENTITY_MAPPINGS_PATH = _CONFIG_DIR / "entity_mappings.json"


# ── 설정 파일 로드 ─────────────────────────────────────────────────────────


def _load_entity_mappings() -> Dict[str, Any]:
    """entity_mappings.json 설정 파일 로드."""
    if not _ENTITY_MAPPINGS_PATH.exists():
        return _get_default_mappings()
    try:
        with open(_ENTITY_MAPPINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to load entity_mappings.json: {e}")
        return _get_default_mappings()


def _get_default_mappings() -> Dict[str, Any]:
    """기본 매핑 반환 (설정 파일이 없을 경우)."""
    return {
        "organization_synonyms": {},
        "technology_hierarchy": {},
        "methodology_synonyms": {},
        "domain_synonyms": {},
    }


def reload_entity_mappings() -> None:
    """설정 파일을 강제로 다시 로드."""
    global _cached_mappings, _cached_synonym_maps
    _cached_mappings = None
    _cached_synonym_maps = {}
    # 캐시 초기화
    _build_synonym_to_canonical.cache_clear()


# 캐시된 매핑 데이터
_cached_mappings: Optional[Dict[str, Any]] = None
_cached_synonym_maps: Dict[str, Dict[str, str]] = {}


def _get_mappings() -> Dict[str, Any]:
    """캐시된 매핑 데이터 반환."""
    global _cached_mappings
    if _cached_mappings is None:
        _cached_mappings = _load_entity_mappings()
    return _cached_mappings


# ── 동의어 역방향 매핑 빌드 ─────────────────────────────────────────────────


@lru_cache(maxsize=4)
def _build_synonym_to_canonical(mapping_type: str) -> Dict[str, str]:
    """동의어 → 정규 이름 역방향 매핑 빌드."""
    mappings = _get_mappings()
    result: Dict[str, str] = {}

    if mapping_type == "organization":
        data = mappings.get("organization_synonyms", {})
        for canonical, synonyms in data.items():
            if canonical.startswith("_"):
                continue
            result[canonical.lower()] = canonical
            if isinstance(synonyms, list):
                for syn in synonyms:
                    result[syn.lower()] = canonical

    elif mapping_type == "technology":
        data = mappings.get("technology_hierarchy", {})
        for canonical, info in data.items():
            if canonical.startswith("_"):
                continue
            result[canonical.lower()] = canonical
            if isinstance(info, dict):
                for syn in info.get("synonyms", []):
                    result[syn.lower()] = canonical

    elif mapping_type == "methodology":
        data = mappings.get("methodology_synonyms", {})
        for canonical, synonyms in data.items():
            if canonical.startswith("_"):
                continue
            result[canonical.lower()] = canonical
            if isinstance(synonyms, list):
                for syn in synonyms:
                    result[syn.lower()] = canonical

    elif mapping_type == "domain":
        data = mappings.get("domain_synonyms", {})
        for canonical, synonyms in data.items():
            if canonical.startswith("_"):
                continue
            result[canonical.lower()] = canonical
            if isinstance(synonyms, list):
                for syn in synonyms:
                    result[syn.lower()] = canonical

    return result


# ── 외부 호환성을 위한 전역 변수 (하위 호환) ─────────────────────────────────


def _get_organization_synonyms() -> Dict[str, List[str]]:
    """organization_synonyms 반환 (하위 호환용)."""
    data = _get_mappings().get("organization_synonyms", {})
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _get_technology_hierarchy() -> Dict[str, Dict]:
    """technology_hierarchy 반환 (하위 호환용)."""
    data = _get_mappings().get("technology_hierarchy", {})
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _get_methodology_synonyms() -> Dict[str, List[str]]:
    """methodology_synonyms 반환 (하위 호환용)."""
    data = _get_mappings().get("methodology_synonyms", {})
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _get_domain_synonyms() -> Dict[str, List[str]]:
    """domain_synonyms 반환 (하위 호환용)."""
    data = _get_mappings().get("domain_synonyms", {})
    return {k: v for k, v in data.items() if not k.startswith("_")}


# 하위 호환성을 위한 전역 변수 (property로 동적 로드)
class _LazyDict(dict):
    """Lazy loading dictionary for backward compatibility."""
    def __init__(self, loader):
        self._loader = loader
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.update(self._loader())
            self._loaded = True

    def __getitem__(self, key):
        self._ensure_loaded()
        return super().__getitem__(key)

    def __iter__(self):
        self._ensure_loaded()
        return super().__iter__()

    def items(self):
        self._ensure_loaded()
        return super().items()

    def get(self, key, default=None):
        self._ensure_loaded()
        return super().get(key, default)


# 하위 호환용 전역 변수
ORGANIZATION_SYNONYMS = _LazyDict(_get_organization_synonyms)
TECHNOLOGY_HIERARCHY = _LazyDict(_get_technology_hierarchy)
METHODOLOGY_SYNONYMS = _LazyDict(_get_methodology_synonyms)
DOMAIN_SYNONYMS = _LazyDict(_get_domain_synonyms)


# ── 기관명 처리 ─────────────────────────────────────────────────────────


def normalize_organization(name: str) -> str:
    """기관명을 정규화된 이름으로 변환."""
    if not name:
        return ""
    syn_map = _build_synonym_to_canonical("organization")
    return syn_map.get(name.lower().strip(), name)


def get_organization_synonyms(name: str) -> List[str]:
    """기관명의 모든 동의어 반환 (정규 이름 포함)."""
    canonical = normalize_organization(name)
    org_synonyms = _get_organization_synonyms()
    if canonical in org_synonyms:
        return [canonical] + org_synonyms[canonical]
    return [name]


# ── 기술 키워드 처리 ─────────────────────────────────────────────────────


def normalize_technology(name: str) -> str:
    """기술명을 정규화된 이름으로 변환."""
    if not name:
        return ""
    syn_map = _build_synonym_to_canonical("technology")
    return syn_map.get(name.lower().strip(), name)


def get_technology_info(name: str) -> Dict[str, Any]:
    """기술명에 대한 전체 정보 반환 (동의어, 부모, 자식, 색상)."""
    canonical = normalize_technology(name)
    tech_hierarchy = _get_technology_hierarchy()
    return tech_hierarchy.get(canonical, {})


def get_related_technologies(name: str) -> List[str]:
    """기술명과 관련된 기술 목록 (부모, 자식, 동의어)."""
    canonical = normalize_technology(name)
    info = get_technology_info(canonical)

    related = [canonical]
    related.extend(info.get("synonyms", []))
    related.extend(info.get("children", []))
    if info.get("parent"):
        related.append(info["parent"])

    return list(set(related))


def get_technology_color(name: str) -> str:
    """기술명에 대한 색상 코드 반환."""
    info = get_technology_info(name)
    return info.get("color", "#8b5cf6")  # 기본 보라색


# ── 방법론 처리 ─────────────────────────────────────────────────────────


def normalize_methodology(name: str) -> str:
    """방법론명을 정규화된 이름으로 변환."""
    if not name:
        return ""
    syn_map = _build_synonym_to_canonical("methodology")
    return syn_map.get(name.lower().strip(), name)


def get_methodology_synonyms(name: str) -> List[str]:
    """방법론명의 모든 동의어 반환 (정규 이름 포함)."""
    canonical = normalize_methodology(name)
    method_synonyms = _get_methodology_synonyms()
    if canonical in method_synonyms:
        return [canonical] + method_synonyms[canonical]
    return [name]


# ── 도메인 처리 ─────────────────────────────────────────────────────────


def normalize_domain(name: str) -> str:
    """도메인명을 정규화된 이름으로 변환."""
    if not name:
        return ""
    syn_map = _build_synonym_to_canonical("domain")
    return syn_map.get(name.lower().strip(), name)


def get_domain_synonyms(name: str) -> List[str]:
    """도메인명의 모든 동의어 반환 (정규 이름 포함)."""
    canonical = normalize_domain(name)
    dom_synonyms = _get_domain_synonyms()
    if canonical in dom_synonyms:
        return [canonical] + dom_synonyms[canonical]
    return [name]


# ── 텍스트에서 엔티티 추출 ─────────────────────────────────────────────────


def extract_organizations(text: str) -> List[str]:
    """텍스트에서 기관명 추출."""
    found = []
    text_lower = text.lower()
    org_synonyms = _get_organization_synonyms()
    for canonical, synonyms in org_synonyms.items():
        if canonical.lower() in text_lower:
            found.append(canonical)
            continue
        for syn in synonyms:
            if syn.lower() in text_lower:
                found.append(canonical)
                break
    return list(set(found))


def extract_technologies(text: str) -> List[str]:
    """텍스트에서 기술 키워드 추출."""
    found = []
    text_lower = text.lower()
    tech_hierarchy = _get_technology_hierarchy()
    for canonical, info in tech_hierarchy.items():
        if canonical.lower() in text_lower:
            found.append(canonical)
            continue
        for syn in info.get("synonyms", []):
            if syn.lower() in text_lower:
                found.append(canonical)
                break
    return list(set(found))


def extract_methodologies(text: str) -> List[str]:
    """텍스트에서 방법론 추출."""
    found = []
    text_lower = text.lower()
    method_synonyms = _get_methodology_synonyms()
    for canonical, synonyms in method_synonyms.items():
        if canonical.lower() in text_lower:
            found.append(canonical)
            continue
        for syn in synonyms:
            if syn.lower() in text_lower:
                found.append(canonical)
                break
    return list(set(found))


def extract_domains(text: str) -> List[str]:
    """텍스트에서 도메인 추출."""
    found = []
    text_lower = text.lower()
    dom_synonyms = _get_domain_synonyms()
    for canonical, synonyms in dom_synonyms.items():
        if canonical.lower() in text_lower:
            found.append(canonical)
            continue
        for syn in synonyms:
            if syn.lower() in text_lower:
                found.append(canonical)
                break
    return list(set(found))


def extract_all_entities(text: str) -> Dict[str, List[str]]:
    """텍스트에서 모든 유형의 엔티티 추출."""
    return {
        "organizations": extract_organizations(text),
        "technologies": extract_technologies(text),
        "methodologies": extract_methodologies(text),
        "domains": extract_domains(text),
    }


# ── 설정 파일 관리 API ─────────────────────────────────────────────────────


def get_entity_mappings_path() -> Path:
    """설정 파일 경로 반환."""
    return _ENTITY_MAPPINGS_PATH


def save_entity_mappings(data: Dict[str, Any]) -> bool:
    """설정 파일 저장."""
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_ENTITY_MAPPINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        reload_entity_mappings()
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save entity_mappings.json: {e}")
        return False


def get_all_mappings() -> Dict[str, Any]:
    """전체 매핑 데이터 반환 (API용)."""
    return _get_mappings()


# ── 기관유형 분류 (organization_types) ─────────────────────────────────────


def _get_organization_types() -> Dict[str, Dict]:
    """organization_types 반환."""
    data = _get_mappings().get("organization_types", {})
    return {k: v for k, v in data.items() if not k.startswith("_")}


def get_organization_type(org_name: str) -> Optional[str]:
    """기관명으로 기관유형 반환 (공공기관, 공기업, 연구기관 등)."""
    org_types = _get_organization_types()
    normalized = normalize_organization(org_name)

    for type_name, info in org_types.items():
        if normalized in info.get("members", []):
            return type_name
    return None


def get_organizations_by_type(type_name: str) -> List[str]:
    """기관유형별 소속 기관 목록 반환."""
    org_types = _get_organization_types()
    if type_name in org_types:
        return org_types[type_name].get("members", [])
    return []


def get_all_organization_types() -> List[str]:
    """모든 기관유형 목록 반환."""
    return list(_get_organization_types().keys())


# ── 사업유형 분류 (project_types) ─────────────────────────────────────────


def _get_project_types() -> Dict[str, Dict]:
    """project_types 반환."""
    data = _get_mappings().get("project_types", {})
    return {k: v for k, v in data.items() if not k.startswith("_")}


def classify_project_type(text: str) -> List[str]:
    """텍스트에서 사업유형 분류 (ISP수립, 시스템구축 등)."""
    found = []
    text_lower = text.lower()
    project_types = _get_project_types()

    for type_name, info in project_types.items():
        patterns = info.get("patterns", [])
        for pattern in patterns:
            if pattern.lower() in text_lower:
                found.append(type_name)
                break
    return list(set(found))


def get_project_type_patterns(type_name: str) -> List[str]:
    """특정 사업유형의 패턴 목록 반환."""
    project_types = _get_project_types()
    if type_name in project_types:
        return project_types[type_name].get("patterns", [])
    return []


def get_all_project_types() -> List[str]:
    """모든 사업유형 목록 반환."""
    return list(_get_project_types().keys())


# ── 문서 섹션 분류 (document_sections) ─────────────────────────────────────


def _get_document_sections() -> Dict[str, Dict]:
    """document_sections 반환."""
    data = _get_mappings().get("document_sections", {})
    return {k: v for k, v in data.items() if not k.startswith("_")}


def classify_document_section(text: str, doc_category: str = None) -> List[str]:
    """
    텍스트에서 문서 섹션 분류.

    Args:
        text: 분류할 텍스트
        doc_category: 문서 카테고리 (proposal/deliverable). 없으면 양쪽 모두 검색.
    """
    found = []
    text_lower = text.lower()
    doc_sections = _get_document_sections()

    sections_to_check = []
    if doc_category == "proposal" or doc_category == "제안서":
        sections_to_check = [("proposal_sections", doc_sections.get("proposal_sections", {}))]
    elif doc_category in ("deliverable", "산출물", "final_report"):
        sections_to_check = [("deliverable_sections", doc_sections.get("deliverable_sections", {}))]
    else:
        # 카테고리 미지정시 양쪽 모두 검색
        sections_to_check = [
            ("proposal_sections", doc_sections.get("proposal_sections", {})),
            ("deliverable_sections", doc_sections.get("deliverable_sections", {})),
        ]

    for section_type, sections in sections_to_check:
        for section_name, patterns in sections.items():
            if isinstance(patterns, list):
                for pattern in patterns:
                    if pattern.lower() in text_lower:
                        found.append(section_name)
                        break

    return list(set(found))


def get_all_document_sections() -> Dict[str, List[str]]:
    """모든 문서 섹션 목록 반환 (proposal_sections, deliverable_sections 분리)."""
    doc_sections = _get_document_sections()
    return {
        "proposal_sections": list(doc_sections.get("proposal_sections", {}).keys()),
        "deliverable_sections": list(doc_sections.get("deliverable_sections", {}).keys()),
    }


# ── 문서 키워드 분류 (document_keywords) ─────────────────────────────────────


def _get_document_keywords() -> Dict[str, Dict]:
    """document_keywords 반환."""
    data = _get_mappings().get("document_keywords", {})
    return {k: v for k, v in data.items() if not k.startswith("_")}


def extract_document_keywords(text: str) -> List[str]:
    """텍스트에서 문서 키워드 추출 (보안, 의사소통관리 등)."""
    found = []
    text_lower = text.lower()
    doc_keywords = _get_document_keywords()

    for keyword_name, info in doc_keywords.items():
        patterns = info.get("patterns", [])
        for pattern in patterns:
            if pattern.lower() in text_lower:
                found.append(keyword_name)
                break

    return list(set(found))


def get_keyword_rfp_codes(keyword: str) -> List[str]:
    """특정 키워드의 RFP 코드 목록 반환."""
    doc_keywords = _get_document_keywords()
    if keyword in doc_keywords:
        return doc_keywords[keyword].get("rfp_codes", [])
    return []


def get_all_document_keywords() -> List[str]:
    """모든 문서 키워드 목록 반환."""
    return list(_get_document_keywords().keys())


# ── 통합 엔티티 추출 (확장) ─────────────────────────────────────────────────


def extract_all_entities_extended(text: str, doc_category: str = None) -> Dict[str, Any]:
    """
    텍스트에서 모든 유형의 엔티티 추출 (확장 버전).

    기존 extract_all_entities()에 추가로 사업유형, 문서섹션, 문서키워드 추출.
    """
    base_entities = extract_all_entities(text)

    # 기관유형 추가
    org_types = []
    for org in base_entities.get("organizations", []):
        org_type = get_organization_type(org)
        if org_type:
            org_types.append(org_type)

    return {
        **base_entities,
        "organization_types": list(set(org_types)),
        "project_types": classify_project_type(text),
        "document_sections": classify_document_section(text, doc_category),
        "document_keywords": extract_document_keywords(text),
    }
