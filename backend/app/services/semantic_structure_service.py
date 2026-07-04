# -*- coding: utf-8 -*-
"""
Semantic structure extraction and semantic chunk preparation.

현재는 PPTX 문서의 의미 섹션 구조화를 우선 지원한다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pptx import Presentation


TOP_SECTION_RULES = [
    ("사업이해도", ["사업이해도", "사업 이해", "사업환경", "사업 환경", "배경", "목적", "범위", "전제조건", "특장점", "특징", "장점", "목표시스템", "구성도", "구성체계"]),
    ("추진전략", ["추진전략", "핵심성공", "핵심 질의", "핵심질의", "추진조직", "추진체계", "협력방안", "품질 확보", "전문협업", "전략 1", "전략 2", "전략 3", "전략 4"]),
    ("컨설팅 방법론", ["방법론", "WIM2", "ISP 방법론", "ISMP 방법론", "프로젝트 준비", "환경분석", "현황분석", "목표모델", "이행계획", "실행계획", "산출물", "적용 사례", "절차 및 활동내용"]),
]

SUBSECTION_ALIASES = {
    "사업 환경의 이해": ["사업환경의 이해", "사업 환경의 이해", "사업환경의이해"],
    "사업의 배경 및 목적": ["사업의 배경 및 목적", "사업 배경 및 목적", "사업배경 및 목적", "배경 및 필요성", "사업목적", "추진목적", "추진방향"],
    "제안의 범위": ["제안의 범위", "사업수행범위", "제안 범위"],
    "전제조건": ["전제조건", "제안의 전제조건"],
    "제안의 특징 및 장점": ["제안의 특징 및 장점", "제안의 특장점", "특장점"],
    "목표시스템 구성도": ["목표시스템 구성도", "목표 구성도"],
    "목표시스템 구성체계": ["목표시스템 구성체계", "목표 구성체계"],
    "핵심 질의기반 사업 추진전략 도출": ["핵심 질의기반 사업 추진전략 도출", "핵심질의기반 사업 추진전략 도출", "핵심질의", "핵심성공요소 기반의 4대 사업추진전략"],
    "사업 추진전략": ["사업 추진전략", "사업추진전략", "전략 1", "전략 2", "전략 3", "전략 4"],
    "추진체계": ["추진체계", "추진조직", "사업수행 조직", "업무 분장", "협력방안", "역할 분담"],
    "품질 확보방안": ["품질 확보방안", "최종산출물의 품질 확보방안"],
    "방법론 특성": ["방법론 특성", "컨설팅 방법론", "사업추진 방법론", "WIM2 BPR/ISP 방법론", "WIM2방법론의 특장점", "WIM2 방법론의 특장점"],
    "제안사 방법론 주요 적용 사례": ["제안사 방법론 주요 적용 사례", "방법론을 적용한 수행 프로젝트", "유사 수행 프로젝트"],
    "WIM2 방법론 절차 개요": ["WIM2 방법론 절차", "ISP 방법론 절차", "ISMP 방법론 절차", "방법론 절차 개요"],
    "프로젝트 준비": ["프로젝트 준비", "프로젝트 준비절차 및 활동내용"],
    "환경분석": ["환경분석", "환경분석 절차 및 활동내용"],
    "현황분석": ["현황분석", "현황분석 절차 및 활동내용"],
    "목표모델 수립": ["목표모델 수립", "목표모델수립", "목표모델 수립 절차 및 활동내용"],
    "이행계획 수립": ["이행계획 수립", "이행계획수립", "통합 실행계획 수립", "통합 실행계획 수립절차 및 활동내용", "실행계획수립"],
    "방법론 절차에 따른 산출물 예시": ["방법론 절차에 따른 산출물 예시", "단계별 산출물 내역", "환경분석 산출물", "현황분석 산출물", "목표모델수립 산출물", "이행계획수립 산출물"],
    "산출물 제출": ["산출물 제출", "최종산출물 제출", "단계별 활동내역 및 산출물 정보"],
}

STOPWORDS = {
    "전략 및 방법론",
    "전략및 방법론",
    "전략및방법론",
    "예 시",
    "추후보완",
    "활용 도구",
    "및 기법",
}


def _normalize_space(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_line(text: str) -> str:
    text = _normalize_space(text)
    text = text.replace("\u3000", " ")
    return text.strip(" -\u2022\t")


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"[\s\-\u2022:()<>]", "", text).lower()


def _first_line(text: str) -> str:
    for line in text.split("\n"):
        cleaned = _clean_line(line)
        if cleaned:
            return cleaned
    return ""


def _extract_sequence_index(text: str) -> Optional[Tuple[int, int]]:
    match = re.search(r"\((\d+)\s*/\s*(\d+)\)", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _get_shape_text(shape) -> str:
    if not hasattr(shape, "text"):
        return ""
    return _clean_line(shape.text)


def _extract_slide_title(slide) -> str:
    if getattr(slide.shapes, "title", None) is not None:
        title_text = _get_shape_text(slide.shapes.title)
        if title_text:
            return _first_line(title_text)

    candidates: List[Tuple[int, int, str]] = []
    for shape in slide.shapes:
        text = _get_shape_text(shape)
        if not text:
            continue
        top = getattr(shape, "top", 10**9)
        left = getattr(shape, "left", 10**9)
        line = _first_line(text)
        if line:
            candidates.append((top, left, line))

    if not candidates:
        return "제목 미확인"

    candidates.sort(key=lambda item: (item[0], item[1], len(item[2])))
    return candidates[0][2]


def _extract_slide_items(slide, title: str) -> List[str]:
    items: List[str] = []
    seen = set()
    title_norm = _normalize_for_compare(title)

    for shape in slide.shapes:
        text = _get_shape_text(shape)
        if not text:
            continue
        lines = [_clean_line(line) for line in text.split("\n")]
        lines = [line for line in lines if line]
        for line in lines:
            line_norm = _normalize_for_compare(line)
            if not line_norm or line_norm == title_norm or line_norm in seen:
                continue
            seen.add(line_norm)
            items.append(line)

        if getattr(shape, "has_table", False):
            table = shape.table
            for row in table.rows:
                row_values = [_clean_line(cell.text) for cell in row.cells if _clean_line(cell.text)]
                if row_values:
                    line = " | ".join(row_values)
                    line_norm = _normalize_for_compare(line)
                    if line_norm and line_norm not in seen:
                        seen.add(line_norm)
                        items.append(line)

    return items


def _infer_top_section(title: str, section_name: str) -> str:
    title_norm = _normalize_for_compare(title)
    for label, keywords in TOP_SECTION_RULES:
        for keyword in keywords:
            if _normalize_for_compare(keyword) in title_norm:
                return label
    return section_name or "기타"


def _canonicalize_subsection(text: str) -> Optional[str]:
    cleaned = _clean_line(text)
    if not cleaned:
        return None
    cleaned = re.sub(r"\(\d+/\d+\)", "", cleaned).strip()
    cleaned = re.sub(r"^[0-9IVXⅠⅡⅢⅣⅤ]+\.*\s*", "", cleaned).strip()
    cleaned = re.sub(r"^[0-9]+\.[0-9]+\s*", "", cleaned).strip()
    cleaned_norm = _normalize_for_compare(cleaned)

    for canonical, aliases in SUBSECTION_ALIASES.items():
        for alias in [canonical] + aliases:
            if _normalize_for_compare(alias) in cleaned_norm:
                return canonical
    return None


def _extract_subsection_label(slide: Dict[str, Any]) -> str:
    candidates = [str(item) for item in slide["items"][:8]] + [str(slide["title"])]
    for candidate in candidates:
        label = _canonicalize_subsection(candidate)
        if label:
            return label
    return str(slide["title"])


def _extract_detail_label(slide: Dict[str, Any], subsection: str) -> str:
    candidates = [str(item) for item in slide["items"][:30]] + [str(slide["title"])]
    sequence = None
    for source in [str(item) for item in slide["items"][:5]] + [str(slide["title"])]:
        sequence = _extract_sequence_index(source)
        if sequence:
            break

    if subsection == "방법론 절차에 따른 산출물 예시":
        if sequence and sequence[1] == 4:
            labels = {
                1: "환경분석 산출물",
                2: "현황분석 산출물",
                3: "목표모델수립 산출물",
                4: "이행계획수립 산출물",
            }
            if sequence[0] in labels:
                return labels[sequence[0]]

    if subsection == "WIM2 방법론 절차 개요":
        if sequence and sequence[1] == 6:
            labels = {
                1: "WIM2 방법론 절차 개요",
                2: "프로젝트 준비",
                3: "환경분석",
                4: "현황분석",
                5: "목표모델 수립",
                6: "통합 실행계획 수립",
            }
            if sequence[0] in labels:
                return labels[sequence[0]]

    for candidate in candidates:
        cleaned = _clean_line(candidate)
        cleaned = re.sub(r"\(\d+/\d+\)", "", cleaned).strip()
        cleaned = re.sub(r"^[0-9IVXⅠⅡⅢⅣⅤ]+\.*\s*", "", cleaned).strip()
        cleaned = re.sub(r"^[0-9]+\.[0-9]+\s*", "", cleaned).strip()
        if cleaned and _normalize_for_compare(cleaned) != _normalize_for_compare(subsection):
            return cleaned
    return subsection


def _slide_number_list(slide_numbers: List[int]) -> List[int]:
    return sorted(set(int(num) for num in slide_numbers))


def _summarize_slide_numbers(slide_numbers: List[int]) -> str:
    if not slide_numbers:
        return "슬라이드 미상"
    numbers = _slide_number_list(slide_numbers)
    ranges: List[str] = []
    start = numbers[0]
    end = numbers[0]
    for num in numbers[1:]:
        if num == end + 1:
            end = num
            continue
        ranges.append(str(start) if start == end else f"{start}~{end}")
        start = end = num
    ranges.append(str(start) if start == end else f"{start}~{end}")
    return "슬라이드 " + ", ".join(ranges)


def _collect_keywords(texts: List[str], limit: int = 12) -> List[str]:
    seen = set()
    keywords: List[str] = []
    for text in texts:
        for raw_part in re.split(r"[,\|/]| - |:|;|\n", text):
            part = _clean_line(raw_part)
            if not part or part in STOPWORDS:
                continue
            part = re.sub(r"^\d+(\.\d+)*\s*", "", part).strip()
            part = re.sub(r"\(\d+/\d+\)", "", part).strip()
            if not part or len(part) < 2 or len(part) > 40 or part in STOPWORDS:
                continue
            key = _normalize_for_compare(part)
            if not key or key in seen:
                continue
            seen.add(key)
            keywords.append(part)
            if len(keywords) >= limit:
                return keywords
    return keywords


def _extract_slides(file_path: str) -> List[Dict[str, Any]]:
    prs = Presentation(file_path)
    slides: List[Dict[str, Any]] = []
    for idx, slide in enumerate(prs.slides, start=1):
        title = _extract_slide_title(slide)
        items = _extract_slide_items(slide, title)
        slides.append({"slide_no": idx, "title": title, "items": items})
    return slides


def _build_outline(slides: List[Dict[str, Any]], section_name: str) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for slide in slides:
        top_section = _infer_top_section(str(slide["title"]), section_name)
        if current is None or current["top_section"] != top_section:
            current = {"top_section": top_section, "slides": []}
            groups.append(current)
        current["slides"].append(slide)
    return groups


def _merge_group_slides(group_slides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for slide in group_slides:
        subsection = _extract_subsection_label(slide)
        if current is None or current["subsection"] != subsection:
            current = {
                "subsection": subsection,
                "slide_numbers": [],
                "items": [],
                "detail_entries": [],
                "_seen": set(),
                "_detail_seen": set(),
            }
            merged.append(current)

        current["slide_numbers"].append(int(slide["slide_no"]))
        detail_label = _extract_detail_label(slide, subsection)
        detail_key = (detail_label, int(slide["slide_no"]))
        if detail_key not in current["_detail_seen"]:
            current["_detail_seen"].add(detail_key)
            current["detail_entries"].append({"label": detail_label, "slide_no": int(slide["slide_no"])})
        for item in slide["items"]:
            norm = _normalize_for_compare(str(item))
            if not norm or norm in current["_seen"]:
                continue
            current["_seen"].add(norm)
            current["items"].append(item)

    for item in merged:
        item.pop("_seen", None)
        item.pop("_detail_seen", None)
    return merged


def build_pptx_structure(file_path: str, relative_path: str = "") -> Dict[str, Any]:
    path_obj = Path(file_path)
    rel_path = relative_path or path_obj.name
    rel_obj = Path(rel_path)
    section_name = rel_obj.parts[2] if len(rel_obj.parts) >= 3 else (rel_obj.parts[1] if len(rel_obj.parts) >= 2 else "기타")
    slides = _extract_slides(file_path)
    groups = _build_outline(slides, section_name)
    sections: List[Dict[str, Any]] = []

    for idx, group in enumerate(groups, start=1):
        top_section = str(group["top_section"])
        merged_slides = _merge_group_slides(group["slides"])
        top_slide_numbers: List[int] = []
        subsection_entries: List[Dict[str, Any]] = []
        top_keyword_texts = [top_section]

        for sub_idx, slide in enumerate(merged_slides, start=1):
            subsection = str(slide["subsection"])
            slide_numbers = _slide_number_list(list(slide["slide_numbers"]))
            items = [str(item) for item in slide["items"]]
            detail_entries = slide.get("detail_entries", [])
            top_slide_numbers.extend(slide_numbers)
            detail_titles = [str(entry["label"]) for entry in detail_entries]
            top_keyword_texts.extend([subsection] + items[:10] + detail_titles)
            subsection_entries.append({
                "section_id": f"{idx}.{sub_idx}",
                "section_name": subsection,
                "parent_section": f"{idx}. {top_section}",
                "slide_range": [slide_numbers[0], slide_numbers[-1]],
                "slide_numbers": slide_numbers,
                "slide_label": _summarize_slide_numbers(slide_numbers),
                "subsections": [{"title": title, "slide_numbers": [int(entry["slide_no"])]} for title, entry in zip(detail_titles, detail_entries)],
                "content_items": items,
                "keywords": _collect_keywords([subsection] + items + detail_titles),
            })

        top_slide_numbers = _slide_number_list(top_slide_numbers)
        sections.append({
            "section_id": str(idx),
            "section_name": top_section,
            "slide_range": [top_slide_numbers[0], top_slide_numbers[-1]] if top_slide_numbers else [],
            "slide_numbers": top_slide_numbers,
            "slide_label": _summarize_slide_numbers(top_slide_numbers),
            "keywords": _collect_keywords(top_keyword_texts),
            "subsections": subsection_entries,
        })

    return {
        "file_name": path_obj.name,
        "source_path": str(path_obj),
        "relative_path": rel_obj.as_posix(),
        "section_group": section_name,
        "document_type": "pptx",
        "total_slides": len(slides),
        "structure_mode": "semantic_sections",
        "sections": sections,
    }


def infer_semantic_tags(structured: Dict[str, Any]) -> Dict[str, Any]:
    joined = " ".join(structured.get("relative_path", "").split("/"))
    text_pool: List[str] = [joined]
    for top in structured.get("sections", []):
        text_pool.append(str(top.get("section_name") or ""))
        text_pool.extend(str(value) for value in top.get("keywords") or [])
        for sub in top.get("subsections", []):
            text_pool.append(str(sub.get("section_name") or ""))
            text_pool.extend(str(value) for value in sub.get("keywords") or [])
            for leaf in sub.get("subsections", []):
                text_pool.append(str(leaf.get("title") or ""))

    text = " ".join(text_pool)
    methodology = "WIM2" if "wim2" in text.lower() else ""
    domain = "감사" if "감사" in text else ""
    technology = "AI" if "AI" in text or "인공지능" in text else ""
    return {
        "methodology": methodology,
        "domain": domain,
        "technology": technology,
    }
