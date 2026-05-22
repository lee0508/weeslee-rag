# 00. RAG 소스 폴더 기반 메타데이터 JSONL 생성 스크립트
"""
build_rag_source_metadata.py

목적:
    /mnt/w2_project/00. RAG 소스/ 하위의
    01. RFP / 02. 제안서 / 03. 산출물 파일 목록을 읽어서
    weeslee-rag용 metadata JSONL을 생성한다.

입력:
    data/rag_filelist.txt

출력:
    data/rag_source_metadata.jsonl

사용:
    python backend/scripts/build_rag_source_metadata.py
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_FILE = PROJECT_ROOT / "data" / "rag_filelist.txt"
OUTPUT_FILE = PROJECT_ROOT / "data" / "rag_source_metadata.jsonl"


# ────────────────────────────────────────────────────────────────────────────
# 폴더-메타데이터 매핑 정의
# ────────────────────────────────────────────────────────────────────────────

# 1차 폴더 (root_group) 매핑
ROOT_GROUP_MAP = {
    "01. RFP": {
        "document_group": "rfp",
        "document_type": "rfp",
        "category": "rfp",
    },
    "02. 제안서": {
        "document_group": "proposal",
        "document_type": "proposal_section",
        "category": "proposal",
    },
    "03. 산출물": {
        "document_group": "deliverable",
        "document_type": "deliverable_section",
        "category": "deliverable",
    },
}

ROOT_GROUP_KEY_MAP = {
    "01. RFP": "rfp",
    "02. 제안서": "proposal",
    "03. 산출물": "deliverable",
}

# 2차 폴더 (sub_group) 매핑 - 제안서
PROPOSAL_SECTION_MAP = {
    "01. 전략및방법론": ("strategy_methodology", "proposal_strategy"),
    "02. 기술및기능": ("technology_function", "proposal_technology"),
    "03. 프로젝트관리": ("project_management", "proposal_pm"),
    "04. 프로젝트지원": ("project_support", "proposal_support"),
    "05. 연구과제": ("research", "proposal_research"),
    "06. 감리": ("audit", "proposal_audit"),
    "07. PMO": ("pmo", "proposal_pmo"),
    "08. PoC": ("poc", "proposal_poc"),
}

# 2차 폴더 (sub_group) 매핑 - 산출물
DELIVERABLE_SECTION_MAP = {
    "01. 환경분석": ("environment_analysis", "deliverable_environment"),
    "02. 현황분석": ("current_state_analysis", "deliverable_current"),
    "03. 목표모델": ("target_model", "deliverable_target"),
    "04. 이행계획": ("implementation_plan", "deliverable_plan"),
    "05. 연구과제": ("research_report", "deliverable_research"),
    "06. 감리": ("audit_report", "deliverable_audit"),
    "07. PMO": ("pmo_report", "deliverable_pmo"),
    "08. PoC": ("poc_report", "deliverable_poc"),
}

SECTION_LABEL_MAP = {
    "strategy_methodology": "전략및방법론",
    "technology_function": "기술및기능",
    "project_management": "프로젝트관리",
    "project_support": "프로젝트지원",
    "research": "연구과제",
    "audit": "감리",
    "pmo": "PMO",
    "poc": "PoC",
    "environment_analysis": "환경분석",
    "current_state_analysis": "현황분석",
    "target_model": "목표모델",
    "implementation_plan": "이행계획",
    "research_report": "연구과제",
    "audit_report": "감리",
    "pmo_report": "PMO",
    "poc_report": "PoC",
}

# 태그 자동 추출용 키워드 맵
TAG_KEYWORD_MAP = {
    "AI": ["AI", "인공지능", "생성형", "초거대", "LLM", "GPT", "딥러닝"],
    "AX": ["AX", "인공지능 전환", "AI전환"],
    "ISP": ["ISP", "정보화전략계획", "정보전략계획"],
    "ISMP": ["ISMP"],
    "BPRISP": ["BPRISP", "BPR/ISP"],
    "빅데이터": ["빅데이터", "데이터랩", "데이터 플랫폼", "데이터플랫폼", "데이터허브"],
    "디지털트윈": ["Digital Twin", "디지털트윈"],
    "보건의료": ["보건의료", "의료", "병원", "의약품", "정신건강", "건강보험"],
    "법무": ["법무", "검찰", "재판", "범죄예방", "교정"],
    "소방": ["소방", "119", "응급"],
    "수자원": ["K-water", "수도", "해양환경", "홍수", "하천"],
    "교육": ["교육", "진로", "디지털캠퍼스", "학교", "대학"],
    "농업": ["농업", "축산", "AFSIS", "농업협력", "농정원"],
    "클라우드": ["클라우드", "Cloud", "SaaS", "IaaS", "PaaS"],
    "통계": ["통계", "통계청", "조사"],
    "공간정보": ["공간정보", "GIS", "지리정보", "지도"],
}


def normalize_path(path: str) -> str:
    """경로를 정규화한다."""
    return path.strip().replace("\\", "/")


def split_path(path: str) -> List[str]:
    """경로를 슬래시 기준으로 분리한다."""
    return [p for p in path.split("/") if p]


def extract_project_name(file_stem: str) -> str:
    """
    파일명에서 접두어를 제거하여 프로젝트명을 추출한다.

    예시:
        RFP_과기정통부 AI-NEXT 고도화 ISP -> 과기정통부 AI-NEXT 고도화 ISP
        전략및방법론_과기정통부 AI-NEXT 고도화 ISP -> 과기정통부 AI-NEXT 고도화 ISP
    """
    prefixes = [
        "RFP_", "전략및방법론_", "기술및기능_", "프로젝트관리_", "프로젝트지원_",
        "환경분석_", "현황분석_", "목표모델_", "이행계획_", "연구과제_",
        "감리_", "PMO_", "PoC_",
    ]

    for prefix in prefixes:
        if file_stem.startswith(prefix):
            return file_stem[len(prefix):].strip()

    if "_" in file_stem:
        return file_stem.split("_", 1)[1].strip()

    return file_stem.strip()


def detect_root_group(parts: List[str]) -> Optional[str]:
    """00. RAG 소스 바로 아래 1차 폴더명을 찾는다."""
    try:
        idx = next(i for i, p in enumerate(parts) if "RAG 소스" in p)
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except StopIteration:
        pass
    return None


def detect_sub_group(parts: List[str]) -> Optional[str]:
    """02. 제안서 또는 03. 산출물 아래 2차 폴더명을 찾는다."""
    try:
        idx = next(i for i, p in enumerate(parts) if "RAG 소스" in p)
        if idx + 2 < len(parts):
            return parts[idx + 2]
    except StopIteration:
        pass
    return None


def detect_document_metadata(root_group: str, sub_group: str) -> Dict:
    """폴더 구조를 기준으로 문서 그룹/유형/섹션을 분류한다."""

    base_meta = ROOT_GROUP_MAP.get(root_group, {
        "document_group": "unknown",
        "document_type": "unknown",
        "category": "unknown",
    })

    result = {
        "document_group": base_meta["document_group"],
        "document_type": base_meta["document_type"],
        "category": base_meta["category"],
        "proposal_section": None,
        "deliverable_section": None,
    }

    if root_group == "02. 제안서" and sub_group:
        section_info = PROPOSAL_SECTION_MAP.get(sub_group)
        if section_info:
            result["proposal_section"] = section_info[0]
            result["category"] = section_info[1]

    elif root_group == "03. 산출물" and sub_group:
        section_info = DELIVERABLE_SECTION_MAP.get(sub_group)
        if section_info:
            result["deliverable_section"] = section_info[0]
            result["category"] = section_info[1]

    return result


def root_group_key(root_group: Optional[str]) -> str:
    return ROOT_GROUP_KEY_MAP.get(root_group or "", "unknown")


def section_label(doc_meta: Dict) -> str:
    proposal_section = doc_meta.get("proposal_section") or ""
    deliverable_section = doc_meta.get("deliverable_section") or ""
    section_key = proposal_section or deliverable_section
    return SECTION_LABEL_MAP.get(section_key, "")


def sub_group_key(root_group: Optional[str], sub_group: Optional[str], doc_meta: Optional[Dict] = None) -> str:
    if not sub_group:
        return ""
    if doc_meta is None:
        doc_meta = detect_document_metadata(root_group or "", sub_group or "")
    proposal_section = doc_meta.get("proposal_section") or ""
    deliverable_section = doc_meta.get("deliverable_section") or ""
    return proposal_section or deliverable_section or ""


def detect_project_type(project_name: str) -> str:
    """프로젝트명에서 ISP, ISMP, BPRISP, 연구과제 유형을 추정한다."""
    upper = project_name.upper()

    if "BPRISP" in upper or "BPR/ISP" in upper:
        return "BPRISP"
    if "ISMP" in upper:
        return "ISMP"
    if "ISP" in upper or "정보화전략계획" in project_name or "정보전략계획" in project_name:
        return "ISP"
    if "연구" in project_name:
        return "research"
    if "컨설팅" in project_name:
        return "consulting"
    if "PMO" in upper:
        return "PMO"
    if "감리" in project_name:
        return "audit"

    return "unknown"


def detect_organization(project_name: str) -> Optional[str]:
    """프로젝트명에서 발주기관을 추출한다."""
    org_patterns = [
        (r"(과기정통부|과학기술정보통신부)", "과학기술정보통신부"),
        (r"(법무부|검찰청|법원)", "법무부"),
        (r"(보건복지부|복지부)", "보건복지부"),
        (r"(통계청)", "통계청"),
        (r"(K-water|수자원공사)", "K-water"),
        (r"(농정원|농림부|농림축산식품부)", "농림축산식품부"),
        (r"(교육부|KICE|교육과정평가원)", "교육부"),
        (r"(소방청|소방본부)", "소방청"),
        (r"(국토부|국토교통부|국토지리정보원)", "국토교통부"),
        (r"(환경부|해양환경)", "환경부"),
        (r"(심평원|건강보험심사평가원)", "건강보험심사평가원"),
        (r"(KOFIH|국제보건의료재단)", "한국국제보건의료재단"),
        (r"(경찰청|경찰)", "경찰청"),
    ]

    for pattern, org_name in org_patterns:
        if re.search(pattern, project_name):
            return org_name

    return None


def detect_tags(project_name: str) -> List[str]:
    """프로젝트명 기반 자동 태그 생성."""
    tags = []

    for tag, keywords in TAG_KEYWORD_MAP.items():
        for keyword in keywords:
            if keyword.lower() in project_name.lower():
                tags.append(tag)
                break

    return sorted(set(tags))


def detect_year(project_name: str, file_path: str) -> Optional[str]:
    """프로젝트명 또는 경로에서 연도를 추출한다."""
    # 20XX 형식 찾기
    year_match = re.search(r"20[12][0-9]", project_name + file_path)
    if year_match:
        return year_match.group()
    return None


def build_search_keywords(
    *,
    root_group: Optional[str],
    sub_group: Optional[str],
    project_name: str,
    document_group: str,
    proposal_section: Optional[str],
    deliverable_section: Optional[str],
    tags: Optional[List[str]] = None,
    organization: Optional[str] = None,
    file_name: str = "",
) -> List[str]:
    values = [
        "00. RAG 소스",
        root_group or "",
        sub_group or "",
        document_group or "",
        proposal_section or "",
        deliverable_section or "",
        section_label({
            "proposal_section": proposal_section or "",
            "deliverable_section": deliverable_section or "",
        }),
        project_name,
        organization or "",
        file_name,
    ]
    if tags:
        values.extend(tags)
    keywords: List[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        lower = cleaned.lower()
        if lower in seen:
            continue
        seen.add(lower)
        keywords.append(cleaned)
    return keywords


def build_metadata():
    """rag_filelist.txt를 읽어서 metadata JSONL을 생성한다."""

    if not INPUT_FILE.exists():
        print(f"입력 파일 없음: {INPUT_FILE}")
        return

    raw = INPUT_FILE.read_bytes()

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp949", errors="ignore")

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    stats = {
        "total": 0,
        "rfp": 0,
        "proposal": 0,
        "deliverable": 0,
        "by_extension": {},
        "by_category": {},
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for source_path in lines:
            source_path = normalize_path(source_path)
            parts = split_path(source_path)

            if not parts:
                continue

            file_name = parts[-1]
            file_stem = Path(file_name).stem
            file_ext = Path(file_name).suffix.lower().replace(".", "")

            root_group = detect_root_group(parts)
            sub_group = detect_sub_group(parts)

            doc_meta = detect_document_metadata(root_group, sub_group)
            project_name = extract_project_name(file_stem)

            # Windows UNC 경로로 변환
            windows_path = source_path.replace(
                "/mnt/w2_project",
                "\\\\diskstation\\W2_프로젝트폴더"
            ).replace("/", "\\")

            metadata = {
                # 소스 정보
                "source_root": "00. RAG 소스",
                "collection": "rag_source",
                "source_path": windows_path,
                "original_source_path": source_path,
                "linux_path": source_path,
                "relative_path": "/".join(parts[parts.index(root_group):]) if root_group in parts else file_name,
                "file_name": file_name,
                "file_ext": file_ext,

                # 폴더 구조 정보
                "root_group": root_group,
                "root_group_key": root_group_key(root_group),
                "sub_group": sub_group,

                # 프로젝트 정보
                "project_name": project_name,
                "project_type": detect_project_type(project_name),
                "organization": detect_organization(project_name),
                "project_year": detect_year(project_name, source_path),

                # 문서 분류
                **doc_meta,
                "section_label": section_label(doc_meta),
                "sub_group_key": sub_group_key(root_group, sub_group, doc_meta),

                # 태그
                "tags": detect_tags(project_name),
                "search_keywords": build_search_keywords(
                    root_group=root_group,
                    sub_group=sub_group,
                    project_name=project_name,
                    document_group=doc_meta["document_group"],
                    proposal_section=doc_meta.get("proposal_section"),
                    deliverable_section=doc_meta.get("deliverable_section"),
                    tags=detect_tags(project_name),
                    organization=detect_organization(project_name),
                    file_name=file_name,
                ),

                # RAG 정책
                "index_policy": "index",
                "search_priority": "high",
                "rag_scope": "document_rag",
                "use_as_company_reference": True,
                "use_for_proposal_reuse": "allowed",
                "confidential_level": "internal",

                # 처리 상태
                "parse_status": "pending",
                "embedding_status": "pending",
                "graph_status": "pending",
            }

            out.write(json.dumps(metadata, ensure_ascii=False) + "\n")

            # 통계 수집
            stats["total"] += 1
            stats["by_extension"][file_ext] = stats["by_extension"].get(file_ext, 0) + 1
            stats["by_category"][doc_meta["category"]] = stats["by_category"].get(doc_meta["category"], 0) + 1

            if doc_meta["document_group"] == "rfp":
                stats["rfp"] += 1
            elif doc_meta["document_group"] == "proposal":
                stats["proposal"] += 1
            elif doc_meta["document_group"] == "deliverable":
                stats["deliverable"] += 1

    print(f"✅ metadata 생성 완료: {OUTPUT_FILE}")
    print(f"   총 파일 수: {stats['total']}")
    print(f"   - RFP: {stats['rfp']}")
    print(f"   - 제안서: {stats['proposal']}")
    print(f"   - 산출물: {stats['deliverable']}")
    print(f"   확장자별: {stats['by_extension']}")
    print(f"   카테고리별: {stats['by_category']}")


if __name__ == "__main__":
    build_metadata()
