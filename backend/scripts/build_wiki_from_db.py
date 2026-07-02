#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DB 기반 Wiki 생성 스크립트

Document Source ROOT 폴더의 디렉토리 구조와 메타데이터를 DB에서 조회하여
Wiki 마크다운 파일을 생성합니다.

Usage:
    python backend/scripts/build_wiki_from_db.py --source-id src_20260702_141532_3a5a53
    python backend/scripts/build_wiki_from_db.py --source-id src_20260702_141532_3a5a53 --max-wikis 10
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

# 프로젝트 루트 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.database import get_db
from app.models.document_metadata import DocumentMetadata
from sqlalchemy import func

# 경로 설정
DATA_DIR = PROJECT_ROOT / "data"
WIKI_DIR = DATA_DIR / "wiki"
PROCESSED_TEXT_DIR = DATA_DIR / "processed_text"

# 문서 타입 매핑
CATEGORY_KO = {
    "rfp": "제안요청서 (RFP)",
    "proposal": "제안서",
    "kickoff": "착수보고",
    "final_report": "최종보고",
    "presentation": "발표자료",
    "deliverable": "산출물",
}

SECTION_TYPE_KO = {
    "rfp": "제안요청서",
    "proposal": "제안서",
    "kickoff": "착수보고",
    "final_report": "최종보고",
    "presentation": "발표자료",
    "전략및방법론": "전략 및 방법론",
    "현황분석": "현황 분석",
    "목표모델": "목표 모델",
    "기술및기능": "기술 및 기능",
    "프로젝트관리": "프로젝트 관리",
    "프로젝트지원": "프로젝트 지원",
    "이행계획": "이행 계획",
    "환경분석": "환경 분석",
    "연구과제": "연구 과제",
}


def get_project_folder_name(relative_path: str) -> Optional[str]:
    """relative_path에서 프로젝트 폴더명 추출 (최상위 폴더)"""
    if not relative_path:
        return None
    parts = Path(relative_path).parts
    return parts[0] if parts else None


def get_text_snippet(document_id: int, max_length: int = 500) -> str:
    """document_id로 OCR 텍스트 조각 가져오기"""
    text_path = PROCESSED_TEXT_DIR / str(document_id) / "full_text.txt"
    if not text_path.exists():
        return ""

    try:
        full_text = text_path.read_text(encoding='utf-8', errors='replace')
        # 앞부분 일부만 추출
        snippet = full_text[:max_length].strip()
        if len(full_text) > max_length:
            snippet += "..."
        return snippet
    except Exception as e:
        print(f"  [WARN] Failed to read text for doc {document_id}: {e}")
        return ""


def generate_wiki_markdown(
    project_folder: str,
    project_name: str,
    organization: str,
    year: Optional[str],
    documents: List[DocumentMetadata],
    source_id: str,
    dataset_id: Optional[str]
) -> str:
    """Wiki 마크다운 생성"""

    # 문서 분류
    docs_by_type: Dict[str, List[DocumentMetadata]] = {}
    for doc in documents:
        section = doc.section_type or doc.document_group or "기타"
        if section not in docs_by_type:
            docs_by_type[section] = []
        docs_by_type[section].append(doc)

    # Document IDs 수집
    doc_ids = [str(doc.document_id) for doc in documents]

    # 마크다운 생성
    lines = []
    lines.append(f"# {project_name}")
    lines.append("")
    lines.append("## 기본 정보")
    lines.append("")
    lines.append("| 항목 | 내용 |")
    lines.append("|------|------|")
    lines.append(f"| 발주처 | {organization or '-'} |")
    lines.append(f"| 사업연도 | {year or '-'} |")
    lines.append(f"| 보유문서 | 총 {len(documents)}건 |")
    lines.append(f"| Source ID | `{source_id}` |")
    if dataset_id:
        lines.append(f"| Dataset ID | `{dataset_id}` |")
    lines.append(f"| 프로젝트 폴더 | `{project_folder}` |")
    lines.append(f"| Document IDs | `{', '.join(doc_ids)}` |")
    lines.append("")
    lines.append("")

    # 문서 인벤토리
    lines.append("## 보유 문서 인벤토리")
    lines.append("")
    lines.append("| 문서유형 | 건수 | Document IDs |")
    lines.append("|---------|------|--------------|")

    for section_type, docs in sorted(docs_by_type.items()):
        type_label = SECTION_TYPE_KO.get(section_type, section_type)
        doc_ids_str = ", ".join([str(d.document_id) for d in docs])
        lines.append(f"| {type_label} | {len(docs)}건 | {doc_ids_str} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 디렉토리 구조
    lines.append("## 디렉토리 구조")
    lines.append("")
    lines.append("```")
    lines.append(f"{project_folder}/")

    # relative_path로 디렉토리 트리 생성
    dir_tree: Dict[str, List[DocumentMetadata]] = {}
    for doc in documents:
        if not doc.relative_path:
            continue
        # 프로젝트 폴더 이후 경로 추출
        parts = Path(doc.relative_path).parts
        if len(parts) > 1:
            subdir = parts[1]  # 예: "01. 제안서"
            if subdir not in dir_tree:
                dir_tree[subdir] = []
            dir_tree[subdir].append(doc)

    for subdir, docs in sorted(dir_tree.items()):
        lines.append(f"├─ {subdir}/")
        for doc in docs:
            lines.append(f"│  └─ {doc.file_name} (ID: {doc.document_id})")

    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 문서별 상세 정보
    lines.append("## 문서 상세")
    lines.append("")

    for section_type, docs in sorted(docs_by_type.items()):
        type_label = SECTION_TYPE_KO.get(section_type, section_type)
        lines.append(f"### {type_label}")
        lines.append("")

        for doc in docs:
            lines.append(f"#### {doc.file_name}")
            lines.append("")
            lines.append("| 항목 | 값 |")
            lines.append("|------|-----|")
            lines.append(f"| Document ID | `{doc.document_id}` |")
            lines.append(f"| 파일 경로 | `{doc.relative_path}` |")
            lines.append(f"| 파일 크기 | {doc.file_size or 0:,} bytes |")
            if doc.ocr_page_count:
                lines.append(f"| 페이지 수 | {doc.ocr_page_count}p |")
            if doc.ocr_quality_score:
                lines.append(f"| OCR 품질 | {float(doc.ocr_quality_score):.2%} |")
            lines.append("")

            # 텍스트 스니펫
            snippet = get_text_snippet(doc.document_id, max_length=300)
            if snippet:
                lines.append("**텍스트 미리보기**:")
                lines.append("")
                lines.append("```")
                lines.append(snippet)
                lines.append("```")
                lines.append("")

    lines.append("---")
    lines.append("")

    # 메타데이터 푸터
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"*DB 기반 자동 생성: {now} | Source: {source_id}*")
    lines.append("")

    return "\n".join(lines)


def build_wiki_for_source(source_id: str, max_wikis: int = 0) -> Dict[str, Any]:
    """source_id 기준으로 Wiki 생성"""

    db = next(get_db())

    try:
        print(f"\n=== Wiki 생성 시작 ===")
        print(f"Source ID: {source_id}")

        # 1. 프로젝트 목록 조회 (프로젝트 폴더명 기준)
        print("\n[1/4] 프로젝트 목록 조회 중...")

        # relative_path에서 최상위 폴더를 추출하여 그룹핑
        documents = db.query(DocumentMetadata).filter(
            DocumentMetadata.source_id == source_id,
            DocumentMetadata.relative_path.isnot(None)
        ).all()

        if not documents:
            print(f"  ⚠️  문서가 없습니다.")
            return {"success": False, "message": "No documents found", "wiki_count": 0}

        print(f"  총 {len(documents)}개 문서 발견")

        # 프로젝트 폴더별로 그룹핑
        projects: Dict[str, List[DocumentMetadata]] = {}
        for doc in documents:
            folder = get_project_folder_name(doc.relative_path)
            if folder:
                if folder not in projects:
                    projects[folder] = []
                projects[folder].append(doc)

        print(f"  {len(projects)}개 프로젝트 폴더 발견")

        # 2. Wiki 생성
        print("\n[2/4] Wiki 마크다운 생성 중...")

        wiki_output_dir = WIKI_DIR / source_id / "projects"
        wiki_output_dir.mkdir(parents=True, exist_ok=True)

        generated_wikis = []
        wiki_count = 0

        for project_folder, docs in sorted(projects.items()):
            if max_wikis > 0 and wiki_count >= max_wikis:
                print(f"  최대 생성 수({max_wikis})에 도달, 중단")
                break

            # 대표 메타데이터 추출 (가장 많이 등장하는 값 사용)
            project_names = [d.project_name for d in docs if d.project_name]
            organizations = [d.organization for d in docs if d.organization]
            years = [str(d.year) for d in docs if d.year]
            dataset_ids = [d.dataset_id for d in docs if d.dataset_id]

            project_name = max(set(project_names), key=project_names.count) if project_names else project_folder
            organization = max(set(organizations), key=organizations.count) if organizations else ""
            year = max(set(years), key=years.count) if years else None
            dataset_id = max(set(dataset_ids), key=dataset_ids.count) if dataset_ids else None

            print(f"\n  프로젝트: {project_name}")
            print(f"    폴더: {project_folder}")
            print(f"    문서 수: {len(docs)}개")

            # Wiki 생성
            wiki_content = generate_wiki_markdown(
                project_folder=project_folder,
                project_name=project_name,
                organization=organization,
                year=year,
                documents=docs,
                source_id=source_id,
                dataset_id=dataset_id
            )

            # 파일명 생성 (프로젝트 폴더명 기반)
            safe_name = project_folder.replace("/", "-").replace("\\", "-")
            wiki_filename = f"{safe_name}.md"
            wiki_path = wiki_output_dir / wiki_filename

            wiki_path.write_text(wiki_content, encoding='utf-8')
            generated_wikis.append(wiki_filename)
            wiki_count += 1

            print(f"    ✓ Wiki 생성 완료: {wiki_filename}")

        # 3. build_info.json 생성
        print("\n[3/4] build_info.json 생성 중...")

        build_info = {
            "source_id": source_id,
            "dataset_id": dataset_id,
            "built_at": datetime.now().isoformat(),
            "wiki_count": wiki_count,
            "total_documents": len(documents),
            "total_projects": len(projects),
            "generated_wikis": generated_wikis
        }

        build_info_path = WIKI_DIR / source_id / "build_info.json"
        build_info_path.write_text(json.dumps(build_info, ensure_ascii=False, indent=2), encoding='utf-8')

        print(f"  ✓ build_info.json 저장 완료")

        # 4. index.json 생성 (검색용)
        print("\n[4/4] index.json 생성 중...")

        index_data = []
        for project_folder, docs in sorted(projects.items()):
            project_names = [d.project_name for d in docs if d.project_name]
            project_name = max(set(project_names), key=project_names.count) if project_names else project_folder

            safe_name = project_folder.replace("/", "-").replace("\\", "-")

            index_data.append({
                "project_folder": project_folder,
                "project_name": project_name,
                "wiki_file": f"{safe_name}.md",
                "document_count": len(docs),
                "document_ids": [d.document_id for d in docs]
            })

        index_path = WIKI_DIR / source_id / "index.json"
        index_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding='utf-8')

        print(f"  ✓ index.json 저장 완료")

        print(f"\n=== Wiki 생성 완료 ===")
        print(f"총 {wiki_count}개 Wiki 생성")
        print(f"출력 경로: {wiki_output_dir}")

        return {
            "success": True,
            "message": f"{wiki_count} wikis generated",
            "wiki_count": wiki_count,
            "output_dir": str(wiki_output_dir),
            "generated_wikis": generated_wikis
        }

    except Exception as e:
        print(f"\n❌ Wiki 생성 실패: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": str(e),
            "wiki_count": 0
        }

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="DB 기반 Wiki 생성")
    parser.add_argument("--source-id", required=True, help="Source ID")
    parser.add_argument("--max-wikis", type=int, default=0, help="최대 생성 수 (0=무제한)")

    args = parser.parse_args()

    result = build_wiki_for_source(args.source_id, args.max_wikis)

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
