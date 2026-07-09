# RFP 문서 패턴 분석 서비스
"""
rfp_pattern_analyzer.py

RFP 문서 구조 패턴을 분석하여 메타데이터 및 키워드를 추출합니다.
- RFP 문서 구조 분석 데이터 활용 (data/rfp_document_structure_analysis.json)
- RFP 용어 사전 활용 (data/rfp_terminology_dictionary.json)
- 파일명 패턴 분석
- 텍스트 내용 분석 (OCR 결과 활용)
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import Counter


class RFPPatternAnalyzer:
    """RFP 문서 패턴 분석기"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.structure_data = self._load_structure_data()
        self.terminology_data = self._load_terminology_data()
        self.metadata_data = self._load_metadata_data()
        self.control_marker_prefixes = (
            "경로명:",
            "파일명:",
            "상대경로:",
            "섹션분류:",
            "총슬라이드수:",
            "표지내용",
            "표지 내용",
            "목차",
            "목차 내용",
        )
        self.control_marker_keywords = {
            "경로명", "파일명", "상대경로", "섹션분류", "총슬라이드수",
            "표지내용", "표지", "목차", "내용", "년도", "년월",
        }
        self.cover_label_prefixes = ("제목:", "사업명:", "주관기관:", "기관명:", "년월:", "년도:")

    def _load_structure_data(self) -> Dict:
        """RFP 문서 구조 분석 데이터 로드"""
        structure_file = self.data_dir / "rfp_document_structure_analysis.json"
        if structure_file.exists():
            with open(structure_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_terminology_data(self) -> Dict:
        """RFP 용어 사전 데이터 로드"""
        terminology_file = self.data_dir / "rfp_terminology_dictionary.json"
        if terminology_file.exists():
            with open(terminology_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_metadata_data(self) -> Dict:
        """RFP 파일 메타데이터 로드"""
        metadata_file = self.data_dir / "rfp_all_files_metadata.json"
        if metadata_file.exists():
            with open(metadata_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def analyze_filename(self, filename: str) -> Dict[str, Any]:
        """
        파일명 패턴 분석

        패턴 예시:
        - RFP_AI 기반 e-감사시스템 재구축 ISP 컨설팅.hwp
        - RFP_AFSIS 협력사업 활용실태 조사 및 개선방안 도출 용역.hwp

        Returns:
            {
                "project_name": "AI 기반 e-감사시스템 재구축",
                "project_type": "ISP",
                "category": "AI 시스템",
                "keywords": ["AI", "e-감사시스템", "재구축", "ISP"],
                "technology_keywords": ["AI"],
                "domain": "감사",
                "document_type": "RFP"
            }
        """
        result = {
            "project_name": "",
            "project_type": "",
            "category": "",
            "keywords": [],
            "technology_keywords": [],
            "domain": "",
            "document_type": "",
            "organization": "",
            "year": None,
            "confidence": 0.0
        }

        # 파일명에서 확장자 제거
        name_without_ext = Path(filename).stem

        # 1. Document Type 추출 (RFP_, 제안서_, 산출물_ 등)
        doc_type_match = re.match(r'^(RFP|제안서|산출물|환경분석|전략및방법론)_', name_without_ext)
        if doc_type_match:
            result["document_type"] = doc_type_match.group(1)

        # 2. 프로젝트 유형 추출 (ISP, ISMP, BPRISP, 용역, 연구 등)
        project_types = self.terminology_data.get("keyword_patterns", {}).get("project_types", {}).get("keywords", [])
        for ptype in project_types:
            if ptype in name_without_ext:
                result["project_type"] = ptype
                break

        # 3. 기술 키워드 추출
        tech_keywords = self.terminology_data.get("keyword_patterns", {}).get("technology_keywords", {}).get("keywords", [])
        found_tech = []
        for tech in tech_keywords:
            if tech in name_without_ext:
                found_tech.append(tech)
        result["technology_keywords"] = found_tech

        # 4. 도메인 키워드 추출
        domain_keywords = self.terminology_data.get("keyword_patterns", {}).get("domain_keywords", {}).get("keywords", [])
        for domain in domain_keywords:
            if domain in name_without_ext:
                result["domain"] = domain
                break

        # 5. 프로젝트명 추출 (RFP_ 이후 ~ 프로젝트 유형 이전)
        if result["document_type"] and result["project_type"]:
            # RFP_AI 기반 e-감사시스템 재구축 ISP 컨설팅.hwp
            # -> "AI 기반 e-감사시스템 재구축"
            prefix_removed = name_without_ext.replace(f"{result['document_type']}_", "")
            # ISP, 컨설팅, 용역 등 제거
            for ptype in project_types:
                prefix_removed = prefix_removed.replace(f" {ptype}", "").replace(ptype, "")
            result["project_name"] = prefix_removed.strip()
        elif result["document_type"]:
            result["project_name"] = name_without_ext.replace(f"{result['document_type']}_", "").strip()
        else:
            result["project_name"] = name_without_ext

        # 6. 일반 키워드 추출 (공백 기준 분리)
        words = re.findall(r'[가-힣A-Za-z]+', name_without_ext)
        result["keywords"] = [w for w in words if len(w) > 1][:10]

        # 7. 신뢰도 계산
        result["confidence"] = self._calculate_filename_confidence(result)

        return result

    def _clean_manual_structure_lines(self, text: str, max_chars: int) -> List[str]:
        """수동 구조화 txt 포맷에서 메타 추출에 유용한 라인만 정리한다."""
        lines = []
        for raw_line in str(text or "")[:max_chars].splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(("경로명:", "파일명:", "상대경로:", "섹션분류:", "총슬라이드수:")):
                continue
            lines.append(line)
        return lines

    def _strip_control_prefix(self, line: str) -> str:
        cleaned = str(line or "").strip()
        cleaned = re.sub(r'^\d+\.\s*', "", cleaned)
        cleaned = re.sub(r'^\d+\s+', "", cleaned)
        for prefix in self.control_marker_prefixes:
            if cleaned.startswith(prefix):
                return cleaned[len(prefix):].strip(" :-")
        return cleaned

    def _filter_keywords(self, keywords: List[str]) -> List[str]:
        filtered: List[str] = []
        seen = set()
        for keyword in keywords:
            normalized = str(keyword or "").strip()
            if not normalized:
                continue
            if normalized in self.control_marker_keywords:
                continue
            if normalized.lower() in {"page", "tel", "fax"}:
                continue
            if normalized not in seen:
                seen.add(normalized)
                filtered.append(normalized)
        return filtered

    def _extract_value_after_label(self, line: str) -> str:
        cleaned = self._strip_control_prefix(line)
        for prefix in self.cover_label_prefixes:
            if cleaned.startswith(prefix):
                return cleaned[len(prefix):].strip()
        return cleaned

    def extract_cover_page_metadata(self, text: str, max_chars: int = 2000) -> Dict[str, Any]:
        """
        표지(Cover Page) 메타데이터 추출

        표지에서 추출하는 정보:
        - 제목 (큰 글씨체, 문서 상단)
        - 발주기관/주관기관
        - 사업명/프로젝트명
        - 작성일/발주일
        - 문서 유형

        Args:
            text: 표지 페이지 텍스트 (보통 첫 1~2페이지)
            max_chars: 분석할 최대 문자 수

        Returns:
            {
                "title": "AI 기반 e-감사시스템 재구축 정보화전략계획(ISP) 수립",
                "organization": "한국수자원공사",
                "project_name": "AI 기반 e-감사시스템 재구축",
                "date": "2024년 3월",
                "document_type": "제안요청서",
                "keywords": ["AI", "감사시스템", "ISP"]
            }
        """
        result = {
            "title": "",
            "organization": "",
            "project_name": "",
            "date": "",
            "document_type": "",
            "keywords": [],
            "confidence": 0.0
        }

        # 표지 페이지 텍스트 제한
        cover_text = text[:max_chars]
        cleaned_lines = self._clean_manual_structure_lines(cover_text, max_chars)
        cleaned_text = "\n".join(cleaned_lines)

        # 1. 제목 추출 (첫 줄 또는 "제안요청서", "제안서" 등이 포함된 줄)
        lines = cleaned_lines
        if lines:
            # 수동 구조화 포맷에서는 "표지내용" 줄을 건너뛴다.
            candidate_lines = []
            for line in lines:
                stripped = self._strip_control_prefix(line)
                if not stripped:
                    continue
                if stripped == line and line.startswith(("표지내용", "표지 내용", "목차")):
                    continue
                candidate_lines.append(stripped)
            if candidate_lines:
                result["title"] = candidate_lines[0]

            # "제안요청서", "제안서", "사업계획서" 등이 포함된 줄 찾기
            for line in candidate_lines[:8]:
                numbered_match = re.search(r'(?:제목|사업명)\s*[:\-]?\s*([^\n]+)', line)
                if numbered_match:
                    result["title"] = numbered_match.group(1).strip()
                    if "제안요청서" in result["title"] or "ISP" in result["title"]:
                        break
                if any(keyword in line for keyword in ["제안요청서", "제안서", "사업계획서", "정보화전략계획", "ISP", "ISMP"]):
                    result["title"] = line
                    break

        # 2. 기관명 추출 (발주기관, 주관기관 등)
        org_patterns = [
            r'(?:발주|주관|의뢰)기관\s*[:\-]?\s*([^\n]{2,80})',
            r'기관명\s*[:\-]?\s*([^\n]{2,80})',
        ]
        for pattern in org_patterns:
            org_match = re.search(pattern, cleaned_text)
            if org_match:
                result["organization"] = org_match.group(1).strip(" ,")
                break

        if not result["organization"]:
            for line in lines[:12]:
                candidate = self._extract_value_after_label(line)
                if ":" in candidate:
                    continue
                if re.fullmatch(r'[가-힣A-Za-z() ]{2,50}(?:공사|공단|청|처|부|원|협회|센터|재단)', candidate):
                    result["organization"] = candidate.strip()
                    break

        # 3. 사업명/프로젝트명 추출
        project_patterns = [
            r'(?:사업명|프로젝트명|과제명)\s*[:\-]?\s*([^\n]{10,100})',
            r'([가-힣A-Z]{5,50}(?:구축|개발|도입|재구축))',
        ]
        for pattern in project_patterns:
            project_match = re.search(pattern, cleaned_text)
            if project_match:
                result["project_name"] = project_match.group(1).strip()
                break

        if not result["project_name"] and result["title"]:
            title_without_doc_type = re.sub(r'\b(제안요청서|제안서|사업계획서)\b', "", result["title"]).strip(" -:")
            result["project_name"] = title_without_doc_type.strip()

        # 4. 날짜 추출
        date_patterns = [
            r'(202[0-9]|203[0-9])년\s*([0-9]{1,2})월',
            r'(202[0-9]|203[0-9])\.\s*([0-9]{1,2})\.',
            r'(202[0-9]|203[0-9])-([0-9]{1,2})-',
        ]
        for pattern in date_patterns:
            date_match = re.search(pattern, cleaned_text)
            if date_match:
                year = date_match.group(1)
                month = date_match.group(2)
                result["date"] = f"{year}년 {month}월"
                break

        # 5. 문서 유형 추출
        doc_types = ["제안요청서", "제안서", "사업계획서", "최종보고서", "중간보고서", "정보화전략계획", "ISP", "ISMP"]
        for doc_type in doc_types:
            if doc_type in cleaned_text:
                result["document_type"] = doc_type
                break

        # 6. 키워드 추출 (제목에서)
        if result["title"]:
            title_words = re.findall(r'[가-힣A-Za-z]{2,}', result["title"])
            result["keywords"] = self._filter_keywords([w for w in title_words if len(w) > 1])[:10]

        # 7. 신뢰도 계산
        score = 0.0
        if result["title"]:
            score += 0.30
        if result["organization"]:
            score += 0.25
        if result["project_name"]:
            score += 0.20
        if result["date"]:
            score += 0.15
        if result["document_type"]:
            score += 0.10

        result["confidence"] = round(min(score, 1.0), 2)

        return result

    def extract_toc_sections(self, text: str, max_chars: int = 3000) -> Dict[str, Any]:
        """
        목차(Table of Contents) 추출

        목차에서 추출하는 정보:
        - 섹션 구조 (계층 구조)
        - 섹션명 목록
        - 페이지 번호 매핑

        Args:
            text: 목차 페이지 텍스트
            max_chars: 분석할 최대 문자 수

        Returns:
            {
                "sections": [
                    {"level": 1, "title": "사업개요", "page": 3},
                    {"level": 2, "title": "추진배경", "page": 5}
                ],
                "section_titles": ["사업개요", "추진배경", "요구사항"],
                "keywords": ["사업개요", "추진배경", "요구사항"]
            }
        """
        result = {
            "sections": [],
            "section_titles": [],
            "keywords": [],
            "confidence": 0.0
        }

        # 목차 텍스트 제한
        toc_text = text[:max_chars]
        cleaned_lines = self._clean_manual_structure_lines(toc_text, max_chars)
        toc_candidate_lines = []
        for line in cleaned_lines:
            stripped = self._strip_control_prefix(line)
            if not stripped:
                continue
            if any(stripped.startswith(prefix) for prefix in self.cover_label_prefixes):
                continue
            toc_candidate_lines.append(line)
        toc_text = "\n".join(toc_candidate_lines)

        # "목차" 또는 "Contents" 이후 텍스트만 분석
        toc_match = re.search(r'(?:목\s*차|Contents|차\s*례)', toc_text, re.IGNORECASE)
        if toc_match:
            toc_text = toc_text[toc_match.end():]

        # 1. 섹션 패턴 감지
        # 패턴: "1. 사업개요 ............... 3", "I. 사업개요 3", "가. 추진배경 5"
        section_patterns = [
            r'([IVX]{1,4}|[0-9]{1,2}|[가-힣])\.\s*([^\n\.]{3,50})[\s\.]*([0-9]{1,4})?',  # "1. 사업개요 ... 3"
            r'([0-9]{1,2})-([0-9]{1,2})\s*([^\n\.]{3,50})[\s\.]*([0-9]{1,4})?',  # "1-1 추진배경 ... 5"
            r'([가-다])\.\s*([^\n\.]{3,50})[\s\.]*([0-9]{1,4})?',  # "가. 목적 ... 7"
        ]

        sections = []
        for pattern in section_patterns:
            matches = re.finditer(pattern, toc_text)
            for match in matches:
                if len(match.groups()) >= 2:
                    section_num = match.group(1)
                    section_title = match.group(2).strip()
                    page_num = match.group(3) if len(match.groups()) >= 3 else None

                    # 레벨 판단
                    level = 1
                    if re.match(r'^[0-9]{1,2}$', section_num):
                        level = 1
                    elif re.match(r'^[가-힣]$', section_num):
                        level = 2
                    elif re.match(r'^[IVX]+$', section_num):
                        level = 1

                    sections.append({
                        "level": level,
                        "title": section_title,
                        "page": int(page_num) if page_num and page_num.isdigit() else None
                    })

        # 수동 구조화 txt 포맷: "사업 개요 - page 4", "  - 추진 배경 및 필요성 - page 4"
        manual_sections: List[Dict[str, Any]] = []
        for raw_line in toc_candidate_lines:
            line = raw_line.strip()
            if not line or line.startswith(("표지내용", "표지 내용")):
                continue
            if line.startswith("목차"):
                continue
            if "page" not in line.lower():
                continue
            if any(self._extract_value_after_label(line) != line and line.lstrip().startswith(prefix) for prefix in self.cover_label_prefixes):
                continue
            if ":" in line and re.match(r'^\d+\.', line):
                continue

            page_match = re.search(r'page\s+([0-9]{1,4})', line, re.IGNORECASE)
            page_num = int(page_match.group(1)) if page_match else None
            title = re.sub(r'\s*-\s*page\s+[0-9]{1,4}(?:\s*-\s*[0-9]{1,4})?\s*$', "", line, flags=re.IGNORECASE).strip()
            title = re.sub(r'^\-\s*', "", title).strip()
            title = self._strip_control_prefix(title)
            if len(title) < 2:
                continue
            manual_sections.append({
                "level": 2 if raw_line.lstrip().startswith("-") else 1,
                "title": title,
                "page": page_num,
            })

        # 2. 중복 제거 및 정렬
        seen_titles = set()
        unique_sections = []
        for section in sections + manual_sections:
            title = section["title"]
            if title not in seen_titles and len(title) >= 3:
                seen_titles.add(title)
                unique_sections.append(section)

        result["sections"] = unique_sections[:30]
        result["section_titles"] = [
            title for title in [s["title"] for s in unique_sections]
            if title not in {"목차", "목차 내용"}
        ]

        # 3. 섹션명에서 키워드 추출
        keywords = set()
        for title in result["section_titles"]:
            words = re.findall(r'[가-힣A-Za-z]{2,}', title)
            keywords.update(words)
        result["keywords"] = self._filter_keywords(list(keywords))[:20]

        # 4. 신뢰도 계산
        score = 0.0
        if len(result["sections"]) >= 5:
            score += 0.50
        if len(result["section_titles"]) >= 3:
            score += 0.30
        if len(result["keywords"]) >= 5:
            score += 0.20

        result["confidence"] = round(min(score, 1.0), 2)

        return result

    def analyze_text_content(self, text: str, max_chars: int = 5000) -> Dict[str, Any]:
        """
        텍스트 내용 분석 (OCR 결과 또는 파싱 결과)

        표지, 목차, 본문을 모두 포함한 종합 분석

        Args:
            text: 분석할 텍스트
            max_chars: 분석할 최대 문자 수

        Returns:
            {
                "detected_sections": ["사업개요", "추진배경", "요구사항"],
                "keywords": ["AI", "ISP", "컨설팅"],
                "organization": "한국수자원공사",
                "year": 2024,
                "summary": "...",
                "cover_page": {...},  # 표지 정보
                "toc": {...},  # 목차 정보
                "confidence": 0.8
            }
        """
        result = {
            "detected_sections": [],
            "keywords": [],
            "organization": "",
            "year": None,
            "summary": "",
            "cover_page": {},
            "toc": {},
            "confidence": 0.0
        }

        # 분석할 텍스트 제한
        analysis_text = text[:max_chars]
        normalized_lines = self._clean_manual_structure_lines(text, max_chars)
        normalized_text = "\n".join(normalized_lines)

        # 0. 표지 추출 (첫 2000자)
        cover_page_data = self.extract_cover_page_metadata(text, max_chars=2000)
        result["cover_page"] = cover_page_data

        # 표지에서 추출한 정보 우선 사용
        if cover_page_data.get("organization"):
            result["organization"] = cover_page_data["organization"]
        if cover_page_data.get("date"):
            year_match = re.search(r'(202[0-9]|203[0-9])', cover_page_data["date"])
            if year_match:
                result["year"] = int(year_match.group(1))

        # 0-1. 목차 추출 (2000~5000자 범위)
        toc_data = self.extract_toc_sections(text, max_chars=4000)
        result["toc"] = toc_data

        # 목차에서 추출한 섹션 정보 사용
        if toc_data.get("section_titles"):
            result["detected_sections"].extend(toc_data["section_titles"])

        # 1. 본문 섹션 감지 (기존 로직 유지)
        section_types = self.terminology_data.get("terminology_categories", {})
        for category, data in section_types.items():
            if isinstance(data, dict) and "terms" in data:
                for term in data["terms"]:
                    if term in normalized_text:
                        result["detected_sections"].append(term)

        # 중복 제거
        result["detected_sections"] = list(dict.fromkeys(result["detected_sections"]))[:20]

        # 2. 기관명 감지 (표지에서 못 찾은 경우에만)
        if not result["organization"]:
            org_keywords = self.terminology_data.get("keyword_patterns", {}).get("organizational_types", {}).get("keywords", [])
            for org in org_keywords:
                if len(str(org or "").strip()) < 2:
                    continue
                if org in normalized_text:
                    result["organization"] = org
                    break

        # 3. 연도 추출 (표지에서 못 찾은 경우에만)
        if not result["year"]:
            year_match = re.search(r'(202[0-9]|203[0-9])년?', normalized_text)
            if year_match:
                try:
                    result["year"] = int(year_match.group(1))
                except:
                    pass

        # 4. 키워드 추출 (빈도 기반 + 표지 + 목차)
        words = re.findall(r'[가-힣A-Za-z]{2,}', normalized_text)
        word_counts = Counter(words)
        # 상위 20개 키워드
        top_words = [word for word, count in word_counts.most_common(20) if count >= 2]

        # 표지/목차 키워드 병합
        all_keywords = set(top_words)
        all_keywords.update(cover_page_data.get("keywords", []))
        all_keywords.update(toc_data.get("keywords", []))
        result["keywords"] = self._filter_keywords(list(all_keywords))[:30]

        # 5. 요약 생성 (표지 제목 + 첫 200자)
        summary_parts = []
        if cover_page_data.get("project_name"):
            summary_parts.append(cover_page_data["project_name"])
        elif cover_page_data.get("title"):
            summary_parts.append(cover_page_data["title"])
        summary_lines = []
        for line in normalized_lines:
            cleaned_line = self._strip_control_prefix(line)
            if not cleaned_line:
                continue
            if any(cleaned_line.startswith(prefix) for prefix in self.cover_label_prefixes):
                cleaned_line = self._extract_value_after_label(cleaned_line)
            cleaned_line = re.sub(r'\bpage\s+\d+(?:\s*-\s*\d+)?\b', "", cleaned_line, flags=re.IGNORECASE).strip(" -")
            if cleaned_line:
                summary_lines.append(cleaned_line)
        summary_body = " ".join(summary_lines)[:200].strip()
        if summary_body:
            summary_parts.append(summary_body)
        result["summary"] = " | ".join(summary_parts)[:300]

        # 6. 신뢰도 계산
        result["confidence"] = self._calculate_text_confidence(result)

        return result

    def extract_metadata_enhanced(
        self,
        filename: str,
        text_content: str = "",
        relative_path: str = ""
    ) -> Dict[str, Any]:
        """
        파일명 + 텍스트 내용 + 경로를 종합하여 강화된 메타데이터 추출

        Args:
            filename: 파일명
            text_content: OCR/파싱 결과 텍스트
            relative_path: 상대 경로

        Returns:
            종합 메타데이터
        """
        # 파일명 분석
        filename_meta = self.analyze_filename(filename)

        # 텍스트 분석
        text_meta = {}
        if text_content:
            text_meta = self.analyze_text_content(text_content)

        # 통합 메타데이터
        merged = {
            "project_name": filename_meta.get("project_name") or "",
            "project_type": filename_meta.get("project_type") or "",
            "category": filename_meta.get("category") or "",
            "document_type": filename_meta.get("document_type") or "",
            "organization": text_meta.get("organization") or filename_meta.get("organization") or "",
            "year": text_meta.get("year") or filename_meta.get("year"),
            "technology_keywords": filename_meta.get("technology_keywords", []),
            "domain": filename_meta.get("domain") or "",
            "detected_sections": text_meta.get("detected_sections", []),
            "keywords": self._merge_keywords(
                filename_meta.get("keywords", []),
                text_meta.get("keywords", [])
            ),
            "summary": text_meta.get("summary") or "",
            "confidence": max(
                filename_meta.get("confidence", 0.0),
                text_meta.get("confidence", 0.0)
            ),
            "metadata_source": "rfp_pattern_analyzer"
        }

        # 표지(Cover Page) 정보 추가
        if text_meta.get("cover_page"):
            merged["cover_page"] = text_meta["cover_page"]

        # 목차(TOC) 정보 추가
        if text_meta.get("toc"):
            merged["toc"] = text_meta["toc"]

        return merged

    def extract_keywords_from_sections(self, sections: List[str]) -> List[str]:
        """
        감지된 섹션에서 키워드 추출

        Args:
            sections: 감지된 섹션 목록

        Returns:
            추출된 키워드 목록
        """
        keywords = set()

        # 섹션명 자체를 키워드로 추가
        for section in sections:
            words = re.findall(r'[가-힣A-Za-z]{2,}', section)
            keywords.update(words)

        return list(keywords)[:20]

    def _merge_keywords(self, keywords1: List[str], keywords2: List[str]) -> List[str]:
        """두 키워드 리스트 병합 (중복 제거)"""
        merged = list(dict.fromkeys(keywords1 + keywords2))
        return self._filter_keywords(merged)[:30]

    def _calculate_filename_confidence(self, result: Dict) -> float:
        """파일명 분석 신뢰도 계산"""
        score = 0.0

        if result.get("document_type"):
            score += 0.25
        if result.get("project_name"):
            score += 0.25
        if result.get("project_type"):
            score += 0.20
        if result.get("technology_keywords"):
            score += 0.15
        if result.get("domain"):
            score += 0.15

        return round(min(score, 1.0), 2)

    def _calculate_text_confidence(self, result: Dict) -> float:
        """텍스트 분석 신뢰도 계산"""
        score = 0.0

        if result.get("detected_sections"):
            score += 0.30
        if result.get("organization"):
            score += 0.25
        if result.get("year"):
            score += 0.20
        if len(result.get("keywords", [])) >= 10:
            score += 0.25

        return round(min(score, 1.0), 2)

    def classify_document_group(self, filename: str, relative_path: str) -> Tuple[str, str]:
        """
        문서 그룹 분류 (RFP, 제안서, 산출물)

        Returns:
            (document_group, category)
        """
        path_lower = relative_path.lower()
        filename_lower = filename.lower()

        # 경로 기반 분류
        if "rfp" in path_lower or filename_lower.startswith("rfp_"):
            return ("RFP", "제안요청서")
        elif "제안서" in path_lower or "proposal" in path_lower:
            if "전략" in path_lower or "방법론" in path_lower:
                return ("제안서", "전략및방법론")
            else:
                return ("제안서", "일반")
        elif "산출물" in path_lower or "deliverable" in path_lower or "output" in path_lower:
            if "환경분석" in path_lower or filename_lower.startswith("환경분석_"):
                return ("산출물", "환경분석")
            elif "현황분석" in path_lower:
                return ("산출물", "현황분석")
            else:
                return ("산출물", "일반")

        # 파일명 기반 분류
        if filename_lower.startswith("rfp_"):
            return ("RFP", "제안요청서")
        elif filename_lower.startswith("전략및방법론_"):
            return ("제안서", "전략및방법론")
        elif filename_lower.startswith("환경분석_"):
            return ("산출물", "환경분석")

        return ("일반", "미분류")


# 싱글톤 인스턴스
rfp_pattern_analyzer = RFPPatternAnalyzer()
