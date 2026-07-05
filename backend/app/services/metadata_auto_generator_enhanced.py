# 강화된 문서 메타데이터 자동 생성 서비스
"""
metadata_auto_generator_enhanced.py

기존 metadata_auto_generator를 확장하여 RFP 패턴 분석 기능을 통합합니다.

기능:
1. 기존 규칙 기반 메타데이터 추출 (metadata_auto_generator.py)
2. RFP 패턴 기반 메타데이터 추출 (rfp_pattern_analyzer.py)
3. 두 결과를 병합하여 최종 메타데이터 생성
4. LLM 기반 보강 (선택적)
"""

import re
import asyncio
from typing import Dict, List, Any, Optional
from pathlib import Path

from app.services.metadata_auto_generator import MetadataAutoGenerator
from app.services.rfp_pattern_analyzer import RFPPatternAnalyzer


class MetadataAutoGeneratorEnhanced:
    """RFP 패턴 분석 기능이 통합된 메타데이터 자동 생성기"""

    def __init__(self, ollama_host: str = "http://localhost:11434", data_dir: str = "data"):
        # 기존 생성기
        self.base_generator = MetadataAutoGenerator(ollama_host=ollama_host)

        # RFP 패턴 분석기
        self.rfp_analyzer = RFPPatternAnalyzer(data_dir=data_dir)

    def extract_metadata(
        self,
        file_name: str,
        file_content: str = "",
        relative_path: str = "",
        use_rfp_patterns: bool = True
    ) -> Dict[str, Any]:
        """
        파일명, 내용, 경로를 종합하여 메타데이터 추출

        Args:
            file_name: 파일명
            file_content: 파일 본문 (OCR/파싱 결과)
            relative_path: 상대 경로
            use_rfp_patterns: RFP 패턴 분석 사용 여부

        Returns:
            추출된 메타데이터
        """
        # 1. 기존 규칙 기반 추출
        base_metadata = self.base_generator.extract_metadata(file_name, file_content)

        # 2. RFP 패턴 분석 (선택적)
        rfp_metadata = {}
        if use_rfp_patterns:
            rfp_metadata = self.rfp_analyzer.extract_metadata_enhanced(
                filename=file_name,
                text_content=file_content,
                relative_path=relative_path
            )

        # 3. 두 결과 병합
        merged_metadata = self._merge_metadata(base_metadata, rfp_metadata)

        # 4. 추가 필드 보강
        merged_metadata = self._enrich_metadata(merged_metadata, file_name, relative_path)

        return merged_metadata

    def _merge_metadata(self, base: Dict, rfp: Dict) -> Dict:
        """
        기존 메타데이터와 RFP 패턴 분석 결과 병합

        병합 우선순위:
        1. RFP 패턴 분석 결과 (더 정확함)
        2. 기존 규칙 기반 결과

        단, 신뢰도가 낮은 경우 기존 결과 유지
        """
        merged = {**base}  # 기본값은 기존 결과

        if not rfp:
            return merged

        # RFP 분석 결과가 더 신뢰도가 높으면 우선 사용
        rfp_confidence = rfp.get("confidence", 0.0)
        base_confidence = base.get("confidence", 0.0)

        # 프로젝트명
        if rfp.get("project_name") and rfp_confidence >= base_confidence:
            merged["project_name"] = rfp["project_name"]

        # 기관명
        if rfp.get("organization"):
            merged["organization"] = rfp["organization"]

        # 연도
        if rfp.get("year"):
            merged["year"] = rfp["year"]

        # 문서 유형
        if rfp.get("document_type"):
            merged["document_type"] = rfp["document_type"]

        # 프로젝트 유형 (ISP, ISMP 등)
        if rfp.get("project_type"):
            merged["project_type"] = rfp["project_type"]
            # business_tags에 추가
            if rfp["project_type"] not in merged.get("business_tags", []):
                merged.setdefault("business_tags", []).append(rfp["project_type"])

        # 기술 키워드 병합
        if rfp.get("technology_keywords"):
            base_tech = set(merged.get("technology_tags", []))
            rfp_tech = set(rfp["technology_keywords"])
            merged["technology_tags"] = list(base_tech | rfp_tech)[:8]

        # 도메인
        if rfp.get("domain"):
            merged["domain"] = rfp["domain"]
            # business_domain에 추가
            merged.setdefault("business_domain", rfp["domain"])

        # 감지된 섹션 추가
        if rfp.get("detected_sections"):
            merged["detected_sections"] = rfp["detected_sections"][:10]

        # 키워드 병합 (중복 제거)
        base_keywords = set(rfp.get("keywords", []))
        merged_keywords = set(merged.get("keywords", []))
        all_keywords = list(base_keywords | merged_keywords)[:30]
        merged["keywords"] = all_keywords

        # 요약 (RFP 우선)
        if rfp.get("summary"):
            merged["summary"] = rfp["summary"]

        # 표지(Cover Page) 정보 추가
        if rfp.get("cover_page"):
            merged["cover_page"] = rfp["cover_page"]
            # 표지에서 추출한 정보를 최우선으로 사용
            cover_page = rfp["cover_page"]
            if cover_page.get("title") and not merged.get("title"):
                merged["title"] = cover_page["title"]
            if cover_page.get("organization") and cover_page.get("confidence", 0) > 0.5:
                merged["organization"] = cover_page["organization"]
            if cover_page.get("project_name") and cover_page.get("confidence", 0) > 0.5:
                merged["project_name"] = cover_page["project_name"]

        # 목차(TOC) 정보 추가
        if rfp.get("toc"):
            merged["toc"] = rfp["toc"]
            # 목차에서 추출한 섹션을 detected_sections에 병합
            toc_sections = rfp["toc"].get("section_titles", [])
            if toc_sections:
                existing_sections = set(merged.get("detected_sections", []))
                existing_sections.update(toc_sections)
                merged["detected_sections"] = list(existing_sections)[:20]

        # 신뢰도 재계산 (더 높은 값 사용)
        merged["confidence"] = max(base_confidence, rfp_confidence)

        # 메타데이터 소스 표시
        merged["metadata_source"] = "enhanced"
        if rfp_confidence > base_confidence:
            merged["primary_source"] = "rfp_pattern"
        else:
            merged["primary_source"] = "rule_based"

        return merged

    def _enrich_metadata(self, metadata: Dict, file_name: str, relative_path: str) -> Dict:
        """
        메타데이터 추가 보강

        - 문서 그룹 분류 (RFP, 제안서, 산출물)
        - 카테고리 세분화
        - 재사용 레벨 추정
        - 폴더명 추가 (relative_path에서 추출)
        - 표지/목차 정보 포함
        """
        # 문서 그룹 및 카테고리 분류
        document_group, category = self.rfp_analyzer.classify_document_group(file_name, relative_path)
        metadata["document_group"] = document_group
        metadata["category"] = category

        # 폴더명 추출 (relative_path에서 디렉토리 부분)
        if relative_path:
            folder_name = str(Path(relative_path).parent)
            metadata["folder_name"] = folder_name
        else:
            metadata["folder_name"] = ""

        # 재사용 레벨 추정
        metadata["reuse_level"] = self._estimate_reuse_level(metadata)

        # 판단 근거 보강
        reason_parts = []
        if metadata.get("primary_source") == "rfp_pattern":
            reason_parts.append("RFP 패턴 분석 기반")
        else:
            reason_parts.append("규칙 기반 분석")

        if metadata.get("document_group"):
            reason_parts.append(f"문서 그룹: {metadata['document_group']}")
        if metadata.get("detected_sections"):
            section_count = len(metadata["detected_sections"])
            reason_parts.append(f"감지된 섹션: {section_count}개")

        # 표지/목차 정보 포함 여부
        if metadata.get("cover_page"):
            reason_parts.append("표지 정보 포함")
        if metadata.get("toc"):
            reason_parts.append("목차 정보 포함")

        metadata["reason"] = "; ".join(reason_parts)

        return metadata

    def _estimate_reuse_level(self, metadata: Dict) -> str:
        """
        재사용 가능성 레벨 추정

        - high: RFP, 제안서 (재사용 가치 높음)
        - medium: 산출물, 보고서
        - low: 임시 문서, 초안
        """
        doc_type = metadata.get("document_type", "").lower()
        doc_group = metadata.get("document_group", "").lower()

        if "rfp" in doc_type or "rfp" in doc_group:
            return "high"
        elif "제안서" in doc_type or "제안서" in doc_group or "proposal" in doc_type:
            return "high"
        elif "최종" in doc_type or "final" in doc_type:
            return "medium"
        elif "임시" in doc_type or "draft" in doc_type or "초안" in doc_type:
            return "low"
        else:
            return "medium"

    async def extract_with_llm(
        self,
        file_name: str,
        file_content: str,
        relative_path: str = "",
        model: str = "gemma4:latest"
    ) -> Dict[str, Any]:
        """
        LLM을 사용하여 메타데이터를 추출 (강화 버전)

        Args:
            file_name: 파일명
            file_content: 파일 본문
            relative_path: 상대 경로
            model: Ollama 모델명

        Returns:
            LLM이 추출한 메타데이터
        """
        # 먼저 강화된 규칙 기반 추출
        rule_result = self.extract_metadata(file_name, file_content, relative_path)

        try:
            # LLM 호출 (기존 base_generator 사용)
            llm_result = await asyncio.to_thread(
                self.base_generator.enricher.enrich_metadata,
                file_name=file_name,
                file_content=file_content[:3000],
                rule_result=rule_result,
                model=model,
            )

            if llm_result:
                # LLM 결과와 병합
                merged = {**rule_result}
                for key, value in llm_result.items():
                    if key.endswith("_tags") and value:
                        base_values = rule_result.get(key) or []
                        merged[key] = list(dict.fromkeys([*base_values, *value]))[:8]
                    elif key == "confidence":
                        merged[key] = max(rule_result.get("confidence", 0.0), float(value or 0.0))
                    elif key == "reason":
                        merged[key] = f"{rule_result.get('reason', '')}; LLM 보강"
                    elif value not in ("", None, []):
                        merged[key] = value

                merged["metadata_source"] = "enhanced_with_llm"
                return merged

        except Exception as e:
            rule_result["reason"] += f"; LLM 호출 실패: {str(e)[:50]}"

        return rule_result

    def extract_keywords_batch(
        self,
        file_list: List[Dict[str, str]]
    ) -> Dict[str, List[str]]:
        """
        여러 파일의 키워드를 일괄 추출

        Args:
            file_list: [{"file_name": "...", "file_content": "...", "relative_path": "..."}, ...]

        Returns:
            {
                "all_keywords": ["AI", "ISP", ...],
                "technology_keywords": ["AI", "빅데이터", ...],
                "business_keywords": ["ISP", "컨설팅", ...],
                "domain_keywords": ["감사", "교육", ...]
            }
        """
        all_tech = set()
        all_business = set()
        all_domains = set()
        all_keywords = set()

        for file_info in file_list:
            metadata = self.extract_metadata(
                file_name=file_info.get("file_name", ""),
                file_content=file_info.get("file_content", ""),
                relative_path=file_info.get("relative_path", "")
            )

            all_tech.update(metadata.get("technology_tags", []))
            all_business.update(metadata.get("business_tags", []))
            if metadata.get("domain"):
                all_domains.add(metadata["domain"])
            all_keywords.update(metadata.get("keywords", []))

        return {
            "all_keywords": list(all_keywords)[:50],
            "technology_keywords": list(all_tech)[:20],
            "business_keywords": list(all_business)[:20],
            "domain_keywords": list(all_domains)[:20]
        }


# 싱글톤 인스턴스
metadata_auto_generator_enhanced = MetadataAutoGeneratorEnhanced()
