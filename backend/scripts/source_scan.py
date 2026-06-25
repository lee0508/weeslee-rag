# 원본 폴더 스캔하여 documents.jsonl 생성 및 SQLite 동기화 스크립트
"""
Source Scan Script for weeslee-rag (B안: JSONL + SQLite 동기화)

- 마운트된 네트워크 드라이브에서 RAG 소스 폴더를 스캔
- source_scan_result.jsonl 및 documents.jsonl 생성
- SQLite documents 테이블에 동기화 (관리자 수정 가능)
- 파일명/경로 기반 메타데이터 자동 추출 (2순위 기능)
"""

import os
import sys
import json
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from contextlib import contextmanager

# 프로젝트 루트 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# app.core 모듈에서 설정 및 매핑 로드
from app.core.config import settings
from app.core.mappings import mappings

# 설정 (config.py에서 로드)
RAG_SOURCE_ROOT = settings.rag_source_root
OUTPUT_DIR = PROJECT_ROOT / "data" / "metadata"
DB_PATH = PROJECT_ROOT / "data" / "metadata.db"

# 매핑 (entity_mappings.json에서 로드)
SOURCE_ID_MAP = mappings.SOURCE_ID_MAP
CATEGORY_ID_MAP = mappings.CATEGORY_ID_MAP
SUPPORTED_EXTENSIONS = mappings.SUPPORTED_EXTENSIONS

# ────────────────────────────────────────────────────────────────────────────
# 2순위: 파일명 접두사 분석 - 메타데이터 자동 추출 함수
# ────────────────────────────────────────────────────────────────────────────

# 문서 그룹 매핑 (entity_mappings.json에서 로드)
DOCUMENT_GROUP_MAP = mappings.DOCUMENT_GROUP_MAP

# 제안서 섹션 매핑
PROPOSAL_SECTION_MAP = {
    "01. 전략및방법론": "strategy_methodology",
    "02. 기술및기능": "technology_function",
    "03. 프로젝트관리": "project_management",
    "04. 프로젝트지원": "project_support",
    "05. 연구과제": "research",
    "06. 감리": "audit",
    "07. PMO": "pmo",
    "08. PoC": "poc",
}

# 산출물 섹션 매핑
DELIVERABLE_SECTION_MAP = {
    "01. 환경분석": "environment_analysis",
    "02. 현황분석": "current_state_analysis",
    "03. 목표모델": "target_model",
    "04. 이행계획": "implementation_plan",
    "05. 연구과제": "research_report",
    "06. 감리": "audit_report",
    "07. PMO": "pmo_report",
    "08. PoC": "poc_report",
}

# 태그 키워드 매핑
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

# 기관명 패턴
ORGANIZATION_PATTERNS = [
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
    (r"(행정안전부|행안부)", "행정안전부"),
    (r"(기획재정부|기재부)", "기획재정부"),
    (r"(고용노동부|고용부)", "고용노동부"),
    (r"(산업통상자원부|산업부)", "산업통상자원부"),
    (r"(중소벤처기업부|중기부)", "중소벤처기업부"),
    (r"(문화체육관광부|문체부)", "문화체육관광부"),
]


def detect_project_type(project_name: str) -> str:
    """프로젝트명에서 사업 유형을 추정한다."""
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
    if "PoC" in upper or "POC" in upper:
        return "PoC"

    return "unknown"


def detect_organization(project_name: str) -> Optional[str]:
    """프로젝트명에서 발주기관을 추출한다."""
    for pattern, org_name in ORGANIZATION_PATTERNS:
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
    year_match = re.search(r"20[12][0-9]", project_name + file_path)
    if year_match:
        return year_match.group()
    return None


def detect_business_domain(project_name: str, tags: List[str]) -> Optional[str]:
    """프로젝트명과 태그에서 사업 분야를 추출한다."""
    domain_map = {
        "보건의료": "healthcare",
        "교육": "education",
        "법무": "justice",
        "소방": "emergency",
        "농업": "agriculture",
        "수자원": "water",
        "통계": "statistics",
        "공간정보": "geospatial",
    }
    for tag in tags:
        if tag in domain_map:
            return domain_map[tag]
    return None


@contextmanager
def get_db_connection():
    """SQLite DB 연결 컨텍스트 매니저."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def generate_document_id(snapshot_id: str, index: int) -> str:
    """문서 ID 생성"""
    date_part = snapshot_id.replace("snap_", "").split("_")[0]
    return f"doc_{date_part}_{index:06d}"


def extract_project_name(filename: str, source_id: str) -> str:
    """파일명에서 프로젝트명 추출"""
    name = Path(filename).stem

    prefixes = [
        "RFP_", "전략및방법론_", "기술및기능_", "프로젝트관리_",
        "프로젝트지원_", "연구과제_", "감리_", "PMO_", "PoC_",
        "환경분석_", "현황분석_", "목표모델_", "이행계획_"
    ]

    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    # 언더스코어로 시작하는 경우 첫 부분 제거
    if "_" in name and not any(name.startswith(p) for p in prefixes):
        parts = name.split("_", 1)
        if len(parts) > 1 and len(parts[0]) < 10:
            name = parts[1]

    return name.strip()


def extract_rich_metadata(
    filepath: str,
    filename: str,
    source_folder: str,
    category_folder: Optional[str] = None
) -> Dict:
    """파일 경로와 이름에서 풍부한 메타데이터를 추출한다."""
    file_stem = Path(filename).stem
    project_name = extract_project_name(filename, source_folder)

    # 문서 그룹
    document_group = DOCUMENT_GROUP_MAP.get(source_folder, "unknown")

    # 섹션 (제안서/산출물)
    proposal_section = None
    deliverable_section = None
    if source_folder == "02. 제안서" and category_folder:
        proposal_section = PROPOSAL_SECTION_MAP.get(category_folder)
    elif source_folder == "03. 산출물" and category_folder:
        deliverable_section = DELIVERABLE_SECTION_MAP.get(category_folder)

    # 자동 추출 메타데이터
    tags = detect_tags(project_name)
    organization = detect_organization(project_name)
    project_type = detect_project_type(project_name)
    project_year = detect_year(project_name, filepath)
    business_domain = detect_business_domain(project_name, tags)

    return {
        "project_name": project_name,
        "document_group": document_group,
        "proposal_section": proposal_section,
        "deliverable_section": deliverable_section,
        "project_type": project_type,
        "organization": organization,
        "project_year": project_year,
        "business_domain": business_domain,
        "tags": tags,
    }


def get_file_info(filepath: str) -> Dict:
    """파일 메타정보 추출"""
    stat = os.stat(filepath)
    return {
        "file_size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "created_at": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
    }


def file_exists_in_db(conn, file_path: str) -> Optional[int]:
    """SQLite에서 file_path로 기존 레코드 ID 조회"""
    cursor = conn.execute(
        "SELECT id FROM documents WHERE file_path = ?", (file_path,)
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def ensure_schema_columns(conn) -> None:
    """필요한 컬럼이 없으면 추가한다."""
    new_columns = [
        ("project_type", "TEXT"),
        ("document_group", "TEXT"),
        ("proposal_section", "TEXT"),
        ("deliverable_section", "TEXT"),
        ("tags", "TEXT"),  # JSON 배열로 저장
    ]

    cursor = conn.execute("PRAGMA table_info(documents)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            try:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col_name} {col_type}")
                print(f"[INFO] Added column: {col_name}")
            except Exception as e:
                print(f"[WARN] Failed to add column {col_name}: {e}")


def sync_to_sqlite(documents: List[Dict], overwrite: bool = False) -> Dict:
    """문서 목록을 SQLite에 동기화 (2순위 메타데이터 포함)"""
    created = 0
    updated = 0
    skipped = 0
    failed = 0

    with get_db_connection() as conn:
        # 스키마 확장 (새 컬럼 추가)
        ensure_schema_columns(conn)

        for doc in documents:
            try:
                file_path = doc.get("full_path", "")
                existing_id = file_exists_in_db(conn, file_path)

                # 태그를 JSON 문자열로 변환
                tags_json = json.dumps(doc.get("tags", []), ensure_ascii=False)

                db_data = {
                    "file_name": doc.get("file_name"),
                    "file_path": file_path,
                    "file_type": doc.get("file_ext"),
                    "file_size": doc.get("file_size"),
                    "document_type": doc.get("document_type", "unknown"),
                    "project_name": doc.get("project_name", ""),
                    "organization": doc.get("organization"),
                    "project_year": doc.get("project_year"),
                    "business_domain": doc.get("business_domain"),
                    "project_type": doc.get("project_type"),
                    "document_group": doc.get("document_group"),
                    "proposal_section": doc.get("proposal_section"),
                    "deliverable_section": doc.get("deliverable_section"),
                    "tags": tags_json,
                    "status": "pending",
                    "meta_status": "auto_suggested",  # 자동 추출됨
                }

                if existing_id:
                    if overwrite:
                        # 기존 레코드 업데이트
                        updates = ", ".join([f"{k} = ?" for k in db_data.keys()])
                        updates += ", updated_at = CURRENT_TIMESTAMP"
                        params = list(db_data.values()) + [existing_id]
                        conn.execute(
                            f"UPDATE documents SET {updates} WHERE id = ?",
                            params
                        )
                        updated += 1
                    else:
                        skipped += 1
                else:
                    # 신규 레코드 생성
                    columns = ", ".join(db_data.keys())
                    placeholders = ", ".join(["?" for _ in db_data])
                    conn.execute(
                        f"INSERT INTO documents ({columns}) VALUES ({placeholders})",
                        list(db_data.values())
                    )
                    created += 1

            except Exception as e:
                print(f"[WARN] DB 동기화 실패: {doc.get('file_name')} - {e}")
                failed += 1

        conn.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "failed": failed
    }


def scan_rag_source(root_path: str, snapshot_id: str) -> List[Dict]:
    """RAG 소스 폴더 스캔 (2순위 메타데이터 자동 추출 포함)"""
    results = []
    doc_index = 1

    for source_folder in sorted(os.listdir(root_path)):
        source_path = os.path.join(root_path, source_folder)
        if not os.path.isdir(source_path):
            continue

        source_id = SOURCE_ID_MAP.get(source_folder, f"src_{source_folder}")

        # RFP는 하위 카테고리 없이 바로 파일
        if source_folder == "01. RFP":
            for filename in sorted(os.listdir(source_path)):
                filepath = os.path.join(source_path, filename)
                if not os.path.isfile(filepath):
                    continue

                ext = Path(filename).suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                file_info = get_file_info(filepath)
                relative_path = os.path.relpath(filepath, root_path)

                # 2순위: 풍부한 메타데이터 추출
                rich_meta = extract_rich_metadata(filepath, filename, source_folder, None)

                results.append({
                    "document_id": generate_document_id(snapshot_id, doc_index),
                    "snapshot_id": snapshot_id,
                    "source_id": source_id,
                    "source_label": source_folder,
                    "category_id": "cat_rfp",
                    "category_label": "RFP",
                    "document_type": "rfp",
                    "document_type_label": "RFP",
                    "file_name": filename,
                    "file_ext": ext.lstrip("."),
                    "file_size": file_info["file_size"],
                    "original_path": f"00. RAG 소스/{relative_path}",
                    "full_path": filepath,
                    "modified_at": file_info["modified_at"],
                    "status": "registered",
                    # 2순위 메타데이터
                    **rich_meta,
                })
                doc_index += 1

        else:
            # 제안서/산출물은 하위 카테고리 폴더 있음
            for category_folder in sorted(os.listdir(source_path)):
                category_path = os.path.join(source_path, category_folder)
                if not os.path.isdir(category_path):
                    continue

                category_id = CATEGORY_ID_MAP.get(category_folder, f"cat_{category_folder}")

                for dirpath, dirnames, filenames in os.walk(category_path):
                    for filename in sorted(filenames):
                        filepath = os.path.join(dirpath, filename)

                        ext = Path(filename).suffix.lower()
                        if ext not in SUPPORTED_EXTENSIONS:
                            continue

                        file_info = get_file_info(filepath)
                        relative_path = os.path.relpath(filepath, root_path)

                        # 2순위: 풍부한 메타데이터 추출
                        rich_meta = extract_rich_metadata(filepath, filename, source_folder, category_folder)

                        if source_id == "src_proposal":
                            doc_type = "proposal"
                            doc_type_label = "제안서"
                        else:
                            doc_type = "deliverable"
                            doc_type_label = "산출물"

                        results.append({
                            "document_id": generate_document_id(snapshot_id, doc_index),
                            "snapshot_id": snapshot_id,
                            "source_id": source_id,
                            "source_label": source_folder,
                            "category_id": category_id,
                            "category_label": category_folder,
                            "document_type": doc_type,
                            "document_type_label": doc_type_label,
                            "file_name": filename,
                            "file_ext": ext.lstrip("."),
                            "file_size": file_info["file_size"],
                            "original_path": f"00. RAG 소스/{relative_path}",
                            "full_path": filepath,
                            "modified_at": file_info["modified_at"],
                            "status": "registered",
                            # 2순위 메타데이터
                            **rich_meta,
                        })
                        doc_index += 1

    return results


def save_jsonl(data: List[Dict], filepath: Path):
    """JSONL 형식으로 저장"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def save_snapshot(snapshot_id: str, doc_count: int, db_result: Dict, output_dir: Path) -> Path:
    """스냅샷 메타정보 저장"""
    snapshot_info = {
        "snapshot_id": snapshot_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_root": RAG_SOURCE_ROOT,
        "document_count": doc_count,
        "sqlite_sync": db_result,
        "status": "completed"
    }

    filepath = output_dir / "snapshots" / f"{snapshot_id}.json"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot_info, ensure_ascii=False, indent=2, fp=f)

    return filepath


def main(overwrite: bool = False):
    """메인 실행"""
    today = datetime.now().strftime("%Y%m%d")
    snapshot_id = f"snap_{today}_rag_source_v1"

    print(f"[INFO] Source Scan 시작 (B안: JSONL + SQLite 동기화)")
    print(f"[INFO] Snapshot ID: {snapshot_id}")
    print(f"[INFO] Source Root: {RAG_SOURCE_ROOT}")
    print(f"[INFO] Output Dir: {OUTPUT_DIR}")
    print(f"[INFO] DB Path: {DB_PATH}")
    print(f"[INFO] Overwrite: {overwrite}")
    print()

    if not os.path.exists(RAG_SOURCE_ROOT):
        print(f"[ERROR] RAG 소스 폴더를 찾을 수 없습니다: {RAG_SOURCE_ROOT}")
        return {"success": False, "error": "RAG source folder not found"}

    # 스캔 실행
    print("[INFO] 폴더 스캔 중...")
    documents = scan_rag_source(RAG_SOURCE_ROOT, snapshot_id)
    print(f"[INFO] 총 {len(documents)}개 문서 발견")
    print()

    # 통계 출력
    source_stats = {}
    category_stats = {}
    ext_stats = {}

    for doc in documents:
        source_stats[doc["source_label"]] = source_stats.get(doc["source_label"], 0) + 1
        category_stats[doc["category_label"]] = category_stats.get(doc["category_label"], 0) + 1
        ext_stats[doc["file_ext"]] = ext_stats.get(doc["file_ext"], 0) + 1

    print("[INFO] Source별 문서 수:")
    for k, v in sorted(source_stats.items()):
        print(f"  - {k}: {v}개")
    print()

    print("[INFO] Category별 문서 수:")
    for k, v in sorted(category_stats.items()):
        print(f"  - {k}: {v}개")
    print()

    print("[INFO] 확장자별 문서 수:")
    for k, v in sorted(ext_stats.items()):
        print(f"  - {k}: {v}개")
    print()

    # JSONL 저장
    scan_result_path = OUTPUT_DIR / "source_scan_result.jsonl"
    documents_path = OUTPUT_DIR / "documents.jsonl"

    print(f"[INFO] source_scan_result.jsonl 저장 중...")
    save_jsonl(documents, scan_result_path)
    print(f"[INFO] 저장 완료: {scan_result_path}")

    print(f"[INFO] documents.jsonl 저장 중...")
    docs_for_export = []
    for doc in documents:
        doc_copy = doc.copy()
        del doc_copy["full_path"]
        docs_for_export.append(doc_copy)
    save_jsonl(docs_for_export, documents_path)
    print(f"[INFO] 저장 완료: {documents_path}")

    # SQLite 동기화
    print()
    print("[INFO] SQLite DB 동기화 중...")
    db_result = sync_to_sqlite(documents, overwrite=overwrite)
    print(f"[INFO] SQLite 동기화 완료:")
    print(f"  - 생성: {db_result['created']}개")
    print(f"  - 업데이트: {db_result['updated']}개")
    print(f"  - 건너뜀: {db_result['skipped']}개")
    print(f"  - 실패: {db_result['failed']}개")

    # 스냅샷 정보 저장
    snapshot_path = save_snapshot(snapshot_id, len(documents), db_result, OUTPUT_DIR)
    print(f"[INFO] 스냅샷 정보 저장: {snapshot_path}")

    print()
    print("[INFO] Source Scan 완료!")

    return {
        "success": True,
        "snapshot_id": snapshot_id,
        "document_count": len(documents),
        "source_stats": source_stats,
        "category_stats": category_stats,
        "ext_stats": ext_stats,
        "sqlite_sync": db_result,
        "files": {
            "scan_result": str(scan_result_path),
            "documents": str(documents_path),
            "snapshot": str(snapshot_path)
        }
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="RAG Source Scan Script")
    parser.add_argument("--overwrite", action="store_true", help="기존 레코드 덮어쓰기")
    args = parser.parse_args()

    result = main(overwrite=args.overwrite)
    if not result.get("success"):
        sys.exit(1)
