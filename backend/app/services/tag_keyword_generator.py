# Tag/Keyword 자동 생성 서비스 - document_metadata 기반 태그/키워드 생성
"""
Tag/Keyword Generator Service

현재 선택된 source_id 기준으로 document_metadata에 등록된 문서를 조회하고,
document_group, section_type, project_name, file_name에서 태그와 키워드를 추출합니다.

QA2 문서 기반 구현 (2026-06-15)
"""
import re
import json
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from app.models.document_metadata import DocumentMetadata
from app.services.dataset_build_settings import get_step_config
from app.services.ollama_metadata_keyword_enricher import OllamaMetadataKeywordEnricher
from app.services.processed_text_store import ProcessedTextStore
from app.services.structured_content_resolver import StructuredContentResolver
import app.services.processed_text_store_extensions  # noqa: F401


class TagKeywordGenerator:
    """
    현재 선택된 source_id / snapshot_id를 기준으로
    Tag / Keyword / 문서별 매핑을 생성하는 서비스입니다.

    핵심 원칙:
    - Root 경로를 직접 하드코딩하지 않습니다.
    - document_metadata에 등록된 문서를 기준으로 처리합니다.
    - document_id는 문서별 매핑에 사용합니다.
    - source_id는 원본 Document Source 구분에 사용합니다.
    - snapshot_id는 결과 버전 기록에 사용합니다.
    """

    def __init__(
        self,
        db: Session,
        source_id: str,
        snapshot_id: Optional[str] = None,
        overwrite: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.db = db
        self.source_id = source_id
        self.snapshot_id = snapshot_id
        self.overwrite = overwrite
        self.config = config or get_step_config(source_id, "5")
        self.processed_text_store = ProcessedTextStore()
        self.ollama_enricher = OllamaMetadataKeywordEnricher()
        self.structured_resolver = StructuredContentResolver(self.config)

        # 불용어 (stopwords)
        self.stopwords = {
            "기반", "위한", "수립", "사업", "용역", "구축", "고도화",
            "컨설팅", "연구", "활용", "도입", "방안", "강화", "통합",
            "재구축", "정보화전략계획", "정보전략계획", "및", "을", "를",
            "의", "에", "대한", "관련", "등", "년", "차", "단계",
            "문서", "자료", "내용", "구성", "작성", "검토", "추진",
            "개요", "목적", "분석", "지원", "계획", "관리", "전략", "프로젝트",
            "사업내용", "추진내용", "공통내용", "요구사항", "산출물",
            "표지", "목차", "페이지", "page", "붙임", "별첨", "일반사항",
            "제안요청서", "제안서", "사업개요", "주요내용", "세부내용",
            "상위섹션", "핵심내용", "hwp", "hwpx", "pdf", "ppt", "pptx", "doc", "docx",
            "파일명", "경로명", "상대경로", "섹션분류", "총슬라이드수", "슬라이드",
            "표지내용", "제목", "사업명", "주관기관", "기관명", "발주기관", "년도", "년월", "연월",
            "소스",
            "structured", "json", "txt", "metadata", "pattern", "cover", "toc",
            "xampp", "htdocs", "weeslee", "mnt", "source", "rag",
        }

        # 키워드 동의어 그룹 (대표 키워드로 정규화)
        self.keyword_aliases = {
            "AI": ["AI", "인공지능", "생성형 AI", "초거대 AI", "생성형AI", "초거대AI"],
            "AX": ["AX", "인공지능 전환", "인공지능전환"],
            "ISP": ["ISP", "정보화전략계획", "정보전략계획"],
            "ISMP": ["ISMP", "정보시스템마스터플랜"],
            "BPR/ISP": ["BPRISP", "BPR/ISP", "BPR ISP", "BPR-ISP"],
            "LLM": ["LLM", "거대언어모델", "대규모언어모델"],
            "빅데이터": ["빅데이터", "BigData", "Big Data"],
            "디지털트윈": ["Digital Twin", "디지털트윈", "디지털 트윈"],
            "ODA": ["ODA", "공적개발원조"],
            "RAG": ["RAG", "검색증강생성"],
            "GraphRAG": ["GraphRAG", "그래프RAG"],
            "클라우드": ["클라우드", "Cloud", "AWS", "Azure", "GCP"],
            "데이터허브": ["데이터허브", "DataHub", "Data Hub"],
            "플랫폼": ["플랫폼", "Platform"],
        }

    def run(self) -> Dict[str, Any]:
        """Tag/Keyword 생성 메인 함수."""
        documents = self._load_documents()

        if not documents:
            return {
                "success": False,
                "message": f"source_id={self.source_id} 기준 등록 문서가 없습니다. Source Scan을 먼저 실행하세요.",
                "source_id": self.source_id,
                "snapshot_id": self.snapshot_id,
                "document_count": 0,
            }

        tag_counter = Counter()
        keyword_counter = Counter()
        document_tag_map = defaultdict(list)
        document_keyword_map = defaultdict(list)

        fixed_tags = self._build_fixed_tags()

        for doc in documents:
            relative_path = doc.relative_path or ""
            file_name = doc.file_name or Path(doc.file_path or "").name
            project_name = doc.project_name or self._extract_project_name(file_name)
            structured_hints = self.structured_resolver.extract_structured_hints(doc)
            text_context = self._build_text_context(
                doc,
                project_name,
                file_name,
                relative_path,
                structured_hints=structured_hints,
            )

            # 문서 분류값 (이미 DB에 있으면 사용, 없으면 계산)
            document_group = doc.document_group or ""
            section_type = (
                doc.section_type
                or doc.final_document_category
                or doc.ocr_document_category
                or doc.scan_document_category
                or ""
            )

            # 태그 후보 생성
            tags_for_doc = []

            if document_group:
                tags_for_doc.append(("document_group", document_group))

            if document_group == "제안서" and section_type:
                tags_for_doc.append(("proposal_section", section_type))

            if document_group == "산출물" and section_type:
                tags_for_doc.append(("deliverable_section", section_type))

            if document_group == "RFP":
                tags_for_doc.append(("rfp_section", "RFP"))

            # 프로젝트 유형 태그
            project_type_tags = self._extract_project_type_tags(text_context)
            for tag in project_type_tags:
                tags_for_doc.append(("project_type", tag))

            # 기술 태그
            technology_tags = self._extract_technology_tags(text_context)
            for tag in technology_tags:
                tags_for_doc.append(("technology", tag))

            # OCR/청크 섹션 기반 문서 구조 태그 보강
            section_tags = self._extract_section_tags(text_context)
            for tag in section_tags:
                if document_group == "제안서":
                    tags_for_doc.append(("proposal_section", tag))
                elif document_group == "산출물":
                    tags_for_doc.append(("deliverable_section", tag))

            tags_for_doc = list(dict.fromkeys(tags_for_doc))

            # 키워드 후보 생성: 파일명/폴더명/프로젝트명 + OCR 본문을 함께 사용
            keywords = self._merge_keyword_candidates(
                self._extract_path_keywords(file_name, relative_path, project_name),
                self._extract_structured_keyword_candidates(structured_hints),
                self._extract_keywords(text_context),
            )
            llm_enrichment = self._enrich_keywords_with_ollama(
                file_name=file_name,
                text_context=text_context,
                existing_keywords=keywords,
                document_group=document_group,
                section_type=section_type,
            )

            extra_section_tags = llm_enrichment.get("section_tags") or []
            for tag in extra_section_tags:
                if document_group == "제안서":
                    tags_for_doc.append(("proposal_section", tag))
                elif document_group == "산출물":
                    tags_for_doc.append(("deliverable_section", tag))

            tags_for_doc = list(dict.fromkeys(tags_for_doc))
            keywords = self._merge_keyword_candidates(
                keywords,
                llm_enrichment.get("keywords") or [],
                llm_enrichment.get("synonyms") or [],
            )

            # 카운터 및 문서별 매핑 구성
            for tag_type, tag_name in tags_for_doc:
                tag_key = f"{tag_type}:{tag_name}"
                tag_counter[tag_key] += 1

                document_tag_map[doc.document_id].append({
                    "tag_type": tag_type,
                    "tag_name": tag_name,
                    "confidence": 0.9,
                    "source": "ocr_text_rule" if text_context else "folder_filename_rule",
                })

            for keyword in keywords:
                keyword_counter[keyword] += 1
                keyword_source = "ocr_text_rule"
                if keyword in (llm_enrichment.get("keywords") or []) or keyword in (llm_enrichment.get("synonyms") or []):
                    keyword_source = "ollama_expansion"

                document_keyword_map[doc.document_id].append({
                    "keyword": keyword,
                    "confidence": 0.75,
                    "source": keyword_source if text_context else "filename_rule",
                })

        # 태그/키워드 payload 생성
        tags = self._make_tag_payloads(tag_counter, fixed_tags)
        keywords_list = self._make_keyword_payloads(keyword_counter)

        # DocumentMetadata의 tags, keywords JSON 필드 업데이트
        self._update_document_metadata(document_tag_map, document_keyword_map)

        self.db.commit()

        # Snapshot JSON 저장
        output_path = self._write_snapshot_json(
            tags=tags,
            keywords=keywords_list,
            document_tag_map=document_tag_map,
            document_keyword_map=document_keyword_map,
        )

        return {
            "success": True,
            "message": "Tag/Keyword 생성이 완료되었습니다.",
            "source_id": self.source_id,
            "snapshot_id": self.snapshot_id,
            "config_applied": {
                "use_structured_txt": bool(self.config.get("use_structured_txt", True)),
                "use_structured_json": bool(self.config.get("use_structured_json", True)),
                "structured_txt_root": self.config.get("structured_txt_root"),
                "structured_json_root": self.config.get("structured_json_root"),
                **self.structured_resolver.get_resolution_summary(),
            },
            "document_count": len(documents),
            "tag_count": len(tags),
            "keyword_count": len(keywords_list),
            "document_tag_mapping_count": sum(len(v) for v in document_tag_map.values()),
            "document_keyword_mapping_count": sum(len(v) for v in document_keyword_map.values()),
            "output_path": output_path,
            "next_action": "Metadata Review에서 자동 생성된 태그와 키워드를 검수하세요.",
            "tag_summary": self._summarize_tags(tags),
            "tag_clusters_top10": self._summarize_tag_clusters(tags),
            "keyword_top10": [k["keyword"] for k in keywords_list[:10]],
            "keyword_clusters_top10": self._summarize_keyword_clusters(keywords_list),
        }

    def _load_documents(self) -> List[DocumentMetadata]:
        """현재 source_id에 해당하는 문서 목록을 조회합니다."""
        query = self.db.query(DocumentMetadata).filter(
            DocumentMetadata.source_id == self.source_id,
            DocumentMetadata.removed_at.is_(None),
        )
        return query.all()

    def _build_fixed_tags(self) -> List[Dict[str, str]]:
        """기본 태그 사전."""
        return [
            {"tag_type": "document_group", "tag_name": "RFP"},
            {"tag_type": "document_group", "tag_name": "제안서"},
            {"tag_type": "document_group", "tag_name": "산출물"},

            {"tag_type": "proposal_section", "tag_name": "전략및방법론"},
            {"tag_type": "proposal_section", "tag_name": "기술및기능"},
            {"tag_type": "proposal_section", "tag_name": "프로젝트관리"},
            {"tag_type": "proposal_section", "tag_name": "프로젝트지원"},
            {"tag_type": "proposal_section", "tag_name": "연구과제"},

            {"tag_type": "deliverable_section", "tag_name": "환경분석"},
            {"tag_type": "deliverable_section", "tag_name": "현황분석"},
            {"tag_type": "deliverable_section", "tag_name": "목표모델"},
            {"tag_type": "deliverable_section", "tag_name": "이행계획"},
            {"tag_type": "deliverable_section", "tag_name": "연구과제"},

            {"tag_type": "project_type", "tag_name": "ISP"},
            {"tag_type": "project_type", "tag_name": "ISMP"},
            {"tag_type": "project_type", "tag_name": "BPR/ISP"},

            {"tag_type": "technology", "tag_name": "AI"},
            {"tag_type": "technology", "tag_name": "LLM"},
            {"tag_type": "technology", "tag_name": "RAG"},
            {"tag_type": "technology", "tag_name": "GraphRAG"},
            {"tag_type": "technology", "tag_name": "빅데이터"},
            {"tag_type": "technology", "tag_name": "디지털트윈"},
        ]

    def _build_text_context(
        self,
        doc: DocumentMetadata,
        project_name: str,
        file_name: str,
        relative_path: str,
        structured_hints: Optional[Dict[str, Any]] = None,
    ) -> str:
        parts: List[str] = []
        for value in (
            project_name,
            file_name,
            doc.section_type,
            doc.final_document_category,
            doc.ocr_document_category,
            doc.scan_document_category,
            doc.project_name,
            doc.organization,
        ):
            text = str(value or "").strip()
            if text:
                parts.append(text)

        structured_content = self.structured_resolver.resolve_document_content(doc)
        structured_hints = structured_hints or self.structured_resolver.extract_structured_hints(doc)
        structured_text = structured_content.get("combined_text") or ""
        if structured_text:
            parts.append(structured_text[: self.structured_resolver.max_text_chars])
        for value in (
            structured_hints.get("title"),
            structured_hints.get("project_name"),
            structured_hints.get("organization"),
            " ".join(structured_hints.get("section_titles") or []),
            " ".join(structured_hints.get("keywords") or []),
        ):
            text = str(value or "").strip()
            if text:
                parts.append(text)

        chunk_file = self.processed_text_store.load_chunk_file(doc.document_id)
        if chunk_file:
            for chunk in (chunk_file.get("chunks") or [])[:10]:
                meta = chunk.get("metadata") or {}
                section_title = str(meta.get("section_title") or "").strip()
                content = str(chunk.get("content") or "").strip()
                if section_title:
                    parts.append(section_title)
                if content:
                    parts.append(content[:600])

        if len(parts) < 8:
            full_text = self.processed_text_store.get_text(str(doc.document_id), format="txt") or ""
            if full_text.strip():
                parts.append(full_text[:8000])

        return "\n".join(part for part in parts if part).strip()

    def _extract_project_name(self, filename: str) -> str:
        """파일명에서 prefix를 제거하고 프로젝트명을 추출합니다."""
        name = Path(filename).stem

        prefixes = [
            "RFP_", "전략및방법론_", "기술및기능_", "프로젝트관리_",
            "프로젝트지원_", "연구과제_", "감리_", "PMO_", "PoC_",
            "환경분석_", "현황분석_", "목표모델_", "이행계획_"
        ]

        for prefix in prefixes:
            if name.startswith(prefix):
                return name[len(prefix):].strip()

        if "_" in name:
            left, right = name.split("_", 1)
            if len(left) < 12:
                return right.strip()

        return name.strip()

    def _extract_project_type_tags(self, text: str) -> List[str]:
        """ISP / ISMP / BPRISP 등 프로젝트 유형 태그를 추출합니다."""
        tags = []
        text_upper = text.upper()

        if "BPRISP" in text_upper or "BPR/ISP" in text or "BPR ISP" in text:
            tags.append("BPR/ISP")
        if "ISMP" in text_upper or "정보시스템마스터플랜" in text:
            tags.append("ISMP")
        if "ISP" in text_upper or "정보화전략계획" in text or "정보전략계획" in text:
            if "BPR/ISP" not in tags:  # 중복 방지
                tags.append("ISP")

        return list(dict.fromkeys(tags))

    def _extract_technology_tags(self, text: str) -> List[str]:
        """파일명/프로젝트명에서 기술 태그를 추출합니다."""
        tags = []

        for normalized, aliases in self.keyword_aliases.items():
            for alias in aliases:
                if alias.lower() in text.lower() or alias in text:
                    tags.append(normalized)
                    break

        return list(dict.fromkeys(tags))

    def _extract_section_tags(self, text: str) -> List[str]:
        """OCR 본문/청크 섹션에서 문서 구조 태그를 추출합니다."""
        lowered = text.lower()
        rules = {
            "전략및방법론": ["전략및방법론", "방법론", "추진전략"],
            "기술및기능": ["기술및기능", "기술 기능", "기능 요구", "기능정의"],
            "프로젝트관리": ["프로젝트관리", "사업관리", "관리방안", "의사소통 관리", "의사소통관리"],
            "프로젝트지원": ["프로젝트지원", "사업지원", "지원방안"],
            "환경분석": ["환경분석", "내외부환경", "내외부 환경"],
            "현황분석": ["현황분석", "현행업무", "as-is", "업무현황"],
            "목표모델": ["목표모델", "to-be", "목표 모델"],
            "이행계획": ["이행계획", "로드맵", "추진계획"],
        }
        found: List[str] = []
        for tag_name, aliases in rules.items():
            if any(alias.lower() in lowered for alias in aliases):
                found.append(tag_name)
        return found

    def _extract_keywords(self, text: str) -> List[str]:
        """OCR 본문을 포함한 텍스트에서 일반 키워드를 추출합니다."""
        keywords = []

        # 동의어 기반 대표 키워드 추출
        for normalized, aliases in self.keyword_aliases.items():
            for alias in aliases:
                if alias.lower() in text.lower() or alias in text:
                    keywords.append(normalized)
                    break

        # 일반 단어 추출 (특수문자 제거 후 토큰화)
        clean = re.sub(r"[()\[\],·‧+/\-:>]", " ", text)
        tokens = clean.split()

        for token in tokens:
            normalized = self._normalize_keyword_token(token, max_len=30)
            if not normalized:
                continue
            keywords.append(normalized)

        return list(dict.fromkeys(keywords))[:40]

    def _extract_path_keywords(self, file_name: str, relative_path: str, project_name: str) -> List[str]:
        """파일명/폴더명/프로젝트명에서 직접 검색에 유용한 키워드를 추출합니다."""
        text = " ".join([file_name or "", project_name or ""]).strip()
        if not text:
            return []

        clean = re.sub(r"[._()\[\],·‧+/\-:>]", " ", text)
        keywords: List[str] = []
        for token in clean.split():
            normalized = self._normalize_keyword_token(token, max_len=40)
            if not normalized:
                continue
            keywords.append(normalized)

        return list(dict.fromkeys(keywords))[:20]

    def _extract_structured_keyword_candidates(self, structured_hints: Dict[str, Any]) -> List[str]:
        keywords: List[str] = []
        if not structured_hints:
            return keywords

        raw_groups = [
            structured_hints.get("project_name"),
            structured_hints.get("organization"),
            structured_hints.get("document_type"),
            *(structured_hints.get("section_titles") or [])[:12],
            *(structured_hints.get("keywords") or [])[:20],
        ]
        for value in raw_groups:
            text = str(value or "").strip()
            if not text:
                continue
            for token in re.split(r"[\s,()_/·‧:\-\[\]<>]+", text):
                normalized = self._normalize_keyword_token(token, max_len=40)
                if not normalized:
                    continue
                keywords.append(normalized)
        return list(dict.fromkeys(keywords))[:30]

    def _should_use_ollama_keyword_enrichment(
        self,
        text_context: str,
        existing_keywords: List[str],
    ) -> bool:
        if len(text_context.strip()) < 200:
            return False
        if len(existing_keywords) >= 8:
            return False
        return True

    def _enrich_keywords_with_ollama(
        self,
        *,
        file_name: str,
        text_context: str,
        existing_keywords: List[str],
        document_group: str,
        section_type: str,
    ) -> Dict[str, Any]:
        if not self._should_use_ollama_keyword_enrichment(text_context, existing_keywords):
            return {}
        return self.ollama_enricher.enrich_keywords(
            file_name=file_name,
            text_context=text_context,
            existing_keywords=existing_keywords,
            document_group=document_group,
            section_type=section_type,
        )

    def _merge_keyword_candidates(self, *groups: List[str]) -> List[str]:
        merged: List[str] = []
        for group in groups:
            for keyword in group:
                token = self._normalize_keyword_token(keyword, max_len=40)
                if not token:
                    continue
                if token not in merged:
                    merged.append(token)
                if len(merged) >= 40:
                    return merged
        return merged

    def _normalize_keyword_token(self, token: Any, max_len: int = 40) -> str:
        value = str(token or "").strip()
        if not value:
            return ""

        value = Path(value).stem if "." in value and len(value) < 80 else value
        value = re.sub(r"^[#\-•·]+", "", value).strip()
        value = re.sub(r"^RFP_", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"^\d+(\.\d+)*\.?$", "", value).strip()
        value = re.sub(r"^[0-9]+(\.[0-9]+)*$", "", value).strip()
        value = re.sub(r"^page$", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"^<+|>+$", "", value).strip()
        value = re.sub(r"[.]+$", "", value).strip()
        value = re.sub(r"\s{2,}", " ", value).strip()
        value = value.replace("\\", " ").replace("/", " ").strip()
        value = re.sub(r"\s{2,}", " ", value).strip()

        if len(value) < 2:
            return ""
        if len(value) > max_len:
            return ""
        if value.startswith("<") or value.endswith(">"):
            return ""
        if value in self.stopwords:
            return ""
        if value.lower() in self.stopwords:
            return ""
        if value.isdigit():
            return ""
        if re.search(r"[:\\]", value):
            return ""
        if re.search(r"\bmnt\b", value, flags=re.IGNORECASE):
            return ""
        if re.fullmatch(r"소스\s*\d*", value):
            return ""
        if re.fullmatch(r"[A-Za-z]{2,4}", value) and value.upper() not in {"AI", "AX", "ISP", "ISMP", "LLM", "RAG", "ODA", "NIA"}:
            return ""
        if re.search(r"(xampp|htdocs|weeslee|structured|document_id|source_id|snapshot_id)", value, flags=re.IGNORECASE):
            return ""
        if re.fullmatch(r"[A-Za-z]{1}", value):
            return ""
        if re.fullmatch(r"[{}]+".format(re.escape("<>[]=()")), value):
            return ""
        if re.search(r"(페이지|page)\s*\d+$", value, flags=re.IGNORECASE):
            return ""
        return value

    def _guess_keyword_type(self, keyword: str) -> str:
        """키워드 유형을 규칙 기반으로 추정합니다."""
        if keyword in {"AI", "LLM", "RAG", "GraphRAG", "빅데이터", "디지털트윈", "클라우드"}:
            return "technology"

        if keyword in {"ISP", "ISMP", "BPR/ISP"}:
            return "methodology"

        if "시스템" in keyword or "플랫폼" in keyword or "정보망" in keyword:
            return "business_system"

        if "청" in keyword or "부" in keyword or "공사" in keyword or "원" in keyword:
            return "organization_candidate"

        return "general"

    def _make_tag_payloads(self, tag_counter: Counter, fixed_tags: List[Dict]) -> List[Dict]:
        """태그 저장용 payload를 생성합니다."""
        merged = {}

        for tag in fixed_tags:
            key = f"{tag['tag_type']}:{tag['tag_name']}"
            merged[key] = {
                "source_id": self.source_id,
                "snapshot_id": self.snapshot_id,
                "tag_type": tag["tag_type"],
                "tag_name": tag["tag_name"],
                "frequency": tag_counter.get(key, 0),
                "source": "default_rule",
                "enabled": True,
            }

        for key, count in tag_counter.items():
            tag_type, tag_name = key.split(":", 1)
            if key not in merged:
                merged[key] = {
                    "source_id": self.source_id,
                    "snapshot_id": self.snapshot_id,
                    "tag_type": tag_type,
                    "tag_name": tag_name,
                    "frequency": count,
                    "source": "document_metadata",
                    "enabled": True,
                }
            else:
                merged[key]["frequency"] = count

        return list(merged.values())

    def _make_keyword_payloads(self, keyword_counter: Counter) -> List[Dict]:
        """키워드 저장용 payload를 생성합니다."""
        result = []

        for keyword, count in keyword_counter.most_common():
            result.append({
                "source_id": self.source_id,
                "snapshot_id": self.snapshot_id,
                "keyword": keyword,
                "keyword_type": self._guess_keyword_type(keyword),
                "frequency": count,
                "weight": self._calc_weight(count),
                "source": "filename_project_name",
                "enabled": True,
            })

        return result

    def _calc_weight(self, count: int) -> float:
        """빈도 기반 키워드 가중치."""
        if count >= 10:
            return 1.0
        if count >= 5:
            return 0.8
        if count >= 2:
            return 0.6
        return 0.4

    def _update_document_metadata(
        self,
        document_tag_map: Dict[int, List],
        document_keyword_map: Dict[int, List]
    ):
        """DocumentMetadata의 tags, keywords JSON 필드를 업데이트합니다."""
        all_doc_ids = set(document_tag_map.keys()) | set(document_keyword_map.keys())

        for doc_id in all_doc_ids:
            doc = self.db.query(DocumentMetadata).filter(
                DocumentMetadata.document_id == doc_id
            ).first()

            if not doc:
                continue

            # 기존 manual 태그 보존 (있으면)
            existing_tags = doc.tags or []
            manual_tags = [t for t in existing_tags if isinstance(t, dict) and t.get("source") == "manual"]

            # 자동 생성 태그 + manual 태그 병합
            new_tags = document_tag_map.get(doc_id, [])
            doc.tags = manual_tags + new_tags

            # 키워드도 동일하게 처리
            existing_keywords = doc.keywords or []
            manual_keywords = [k for k in existing_keywords if isinstance(k, dict) and k.get("source") == "manual"]

            new_keywords = document_keyword_map.get(doc_id, [])
            doc.keywords = manual_keywords + new_keywords

    def _summarize_tags(self, tags: List[Dict]) -> Dict[str, int]:
        """태그 유형별 요약."""
        summary = defaultdict(int)
        for tag in tags:
            if tag.get("frequency", 0) > 0:
                summary[tag["tag_type"]] += 1
        return dict(summary)

    def _summarize_tag_clusters(self, tags: List[Dict]) -> List[Dict[str, Any]]:
        """빈도가 있는 태그 군집 상위 목록을 반환합니다."""
        rows = []
        for tag in tags:
            frequency = int(tag.get("frequency") or 0)
            if frequency <= 0:
                continue
            rows.append({
                "tag_type": tag.get("tag_type") or "unknown",
                "tag_name": tag.get("tag_name") or "",
                "frequency": frequency,
            })
        rows.sort(key=lambda item: (-item["frequency"], str(item["tag_type"]), str(item["tag_name"])))
        return rows[:10]

    def _summarize_keyword_clusters(self, keywords: List[Dict]) -> List[Dict[str, Any]]:
        """키워드 군집 상위 목록을 반환합니다."""
        rows = []
        for keyword in keywords[:10]:
            rows.append({
                "keyword": keyword.get("keyword") or "",
                "keyword_type": keyword.get("keyword_type") or "general",
                "frequency": int(keyword.get("frequency") or 0),
            })
        return rows

    def _write_snapshot_json(
        self,
        tags: List[Dict],
        keywords: List[Dict],
        document_tag_map: Dict,
        document_keyword_map: Dict,
    ) -> str:
        """Snapshot 기준 결과 JSON을 저장합니다."""
        # 프로젝트 루트 찾기
        current_file = Path(__file__).resolve()
        project_root = current_file.parents[3]  # backend/app/services -> project root

        base_dir = project_root / "data" / "tag_keyword"

        if self.snapshot_id:
            output_dir = base_dir / self.source_id / self.snapshot_id
        else:
            output_dir = base_dir / self.source_id / "latest"

        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "tag_keyword_result.json"

        payload = {
            "generated_at": datetime.now().isoformat(),
            "source_id": self.source_id,
            "snapshot_id": self.snapshot_id,
            "tags": tags,
            "keywords": keywords,
            "document_tag_map": {
                str(k): v for k, v in document_tag_map.items()
            },
            "document_keyword_map": {
                str(k): v for k, v in document_keyword_map.items()
            },
        }

        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        return str(output_path)
