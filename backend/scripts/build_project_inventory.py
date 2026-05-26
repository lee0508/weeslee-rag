#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Document Source별 project_inventory.json 자동 생성 스크립트
"""
build_project_inventory.py

Document Source에 등록된 파일들로부터 source_id별 project_inventory.json을 생성한다.
metadata.db의 documents 테이블과 staged/chunks JSONL을 기반으로
폴더별 문서 인벤토리를 자동 생성한다.

Usage:
    # 모든 source_id에 대해 inventory 생성
    python backend/scripts/build_project_inventory.py --all

    # 특정 source_id에 대해 inventory 생성
    python backend/scripts/build_project_inventory.py --source-id rag_source

    # 현재 활성 snapshot 기준으로 inventory 생성
    python backend/scripts/build_project_inventory.py --from-chunks

출력:
    data/staged/{source_id}_inventory.json
    또는 data/staged/project_inventory.json (--from-chunks 사용 시)
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
STAGED_DIR = DATA_DIR / "staged"
CHUNKS_DIR = STAGED_DIR / "chunks"
MANIFEST_DIR = STAGED_DIR / "manifest"
DB_PATH = DATA_DIR / "metadata.db"
PLATFORM_STORE_PATH = DATA_DIR / "platform_store.json"

# 카테고리 매핑 (document_group → category)
CATEGORY_MAP = {
    "RFP": "rfp",
    "rfp": "rfp",
    "제안서": "proposal",
    "proposal": "proposal",
    "산출물": "deliverable",
    "deliverable": "deliverable",
    "착수보고": "kickoff",
    "kickoff": "kickoff",
    "최종보고": "final_report",
    "final_report": "final_report",
    "발표자료": "presentation",
    "presentation": "presentation",
}


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_platform_store() -> dict:
    if not PLATFORM_STORE_PATH.exists():
        return {}
    try:
        return json.loads(PLATFORM_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_document_sources() -> list[dict]:
    """platform_store.json에서 document_sources 목록을 반환한다."""
    store = load_platform_store()
    return store.get("document_sources", [])


def get_active_snapshot() -> Optional[str]:
    """활성 스냅샷 이름을 반환한다."""
    active_index_path = DATA_DIR / "active_index.json"
    if not active_index_path.exists():
        return None
    try:
        content = json.loads(active_index_path.read_text(encoding="utf-8"))
        return content.get("snapshot")
    except Exception:
        return None


def extract_folder_name(file_path: str) -> str:
    """파일 경로에서 프로젝트 폴더명을 추출한다."""
    normalized = file_path.replace("\\", "/")
    parts = normalized.split("/")

    # W2_프로젝트폴더 하위 구조에서 프로젝트 폴더 추출
    for i, part in enumerate(parts):
        if "프로젝트폴더" in part or "RAG" in part.upper():
            # 다음 2-3레벨 중 숫자. 또는 YYYYMM. 패턴을 찾음
            for j in range(i + 1, min(i + 4, len(parts))):
                candidate = parts[j]
                # 프로젝트 폴더 패턴: "YYYYMM. 프로젝트명" 또는 "숫자. 프로젝트명"
                if re.match(r"^\d{6}\.", candidate) or re.match(r"^\d+\.\s*", candidate):
                    return candidate

    # fallback: 파일명의 부모 디렉토리
    if len(parts) >= 2:
        return parts[-2]
    return "unknown"


def normalize_category(raw: str) -> str:
    """document_group을 표준 category로 변환한다."""
    return CATEGORY_MAP.get(raw, "unknown")


def build_inventory_from_db(source_id: str = "rag_source") -> dict[str, Any]:
    """metadata.db의 documents 테이블에서 source_id에 해당하는 문서로 inventory를 생성한다."""
    store = load_platform_store()
    source_record = None
    for rec in store.get("document_sources", []):
        if rec.get("source_id") == source_id:
            source_record = rec
            break

    if not source_record:
        print(f"[WARN] source_id '{source_id}' not found in platform_store.json")
        mount_path = None
    else:
        mount_path = source_record.get("mount_path") or source_record.get("source_uri")

    inventory: dict[str, dict] = {}
    conn = get_db_connection()
    try:
        cursor = conn.execute("SELECT * FROM documents")
        rows = cursor.fetchall()
    finally:
        conn.close()

    for row in rows:
        file_path = row["file_path"] or ""

        # source_id 경로 필터링 (mount_path가 있는 경우)
        if mount_path:
            normalized_file = file_path.replace("\\", "/")
            normalized_mount = mount_path.replace("\\", "/")
            if not normalized_file.startswith(normalized_mount):
                continue

        folder_name = extract_folder_name(file_path)
        doc_id = f"DOC-{row['id']:06d}"

        # document_type을 category로 매핑
        doc_type = row["document_type"] or "unknown"
        category = normalize_category(doc_type)

        if folder_name not in inventory:
            inventory[folder_name] = {
                "folder_name": folder_name,
                "organization": row["organization"] or "",
                "folder_year": row["project_year"] or "",
                "doc_count": 0,
                "categories": defaultdict(list),
            }

        inventory[folder_name]["doc_count"] += 1
        inventory[folder_name]["categories"][category].append(doc_id)

        # organization, year 업데이트 (빈 값이면 채움)
        if not inventory[folder_name]["organization"] and row["organization"]:
            inventory[folder_name]["organization"] = row["organization"]
        if not inventory[folder_name]["folder_year"] and row["project_year"]:
            inventory[folder_name]["folder_year"] = row["project_year"]

    # defaultdict를 일반 dict로 변환
    for folder_name in inventory:
        inventory[folder_name]["categories"] = dict(inventory[folder_name]["categories"])

    return {
        "source_id": source_id,
        "mount_path": mount_path,
        "generated_at": datetime.now().isoformat(),
        "total_folders": len(inventory),
        "total_documents": sum(inv["doc_count"] for inv in inventory.values()),
        "inventory": inventory,
    }


def build_inventory_from_chunks(snapshot: Optional[str] = None) -> dict[str, Any]:
    """staged/chunks의 JSONL 파일에서 inventory를 생성한다."""
    if not snapshot:
        snapshot = get_active_snapshot()
    if not snapshot:
        # 가장 최근 chunks 파일 사용
        chunks_files = sorted(CHUNKS_DIR.glob("*_chunks.jsonl"), reverse=True)
        if not chunks_files:
            raise FileNotFoundError("No chunks JSONL files found")
        chunks_path = chunks_files[0]
        snapshot = chunks_path.stem.replace("_chunks", "")
    else:
        chunks_path = CHUNKS_DIR / f"{snapshot}_chunks.jsonl"

    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")

    inventory: dict[str, dict] = {}
    seen_doc_ids: dict[str, set] = defaultdict(set)  # folder → set of doc_ids

    with chunks_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            chunk = json.loads(line)

            # 청크의 metadata에서 정보 추출
            metadata = chunk.get("metadata", {})
            source_path = metadata.get("source_path") or chunk.get("source_path") or ""
            folder_name = metadata.get("folder_name") or extract_folder_name(source_path)
            doc_id = chunk.get("document_id") or metadata.get("document_id") or ""

            # category 추출
            raw_category = chunk.get("category") or metadata.get("document_group") or "unknown"
            category = normalize_category(raw_category)

            if not folder_name or folder_name == "unknown":
                continue

            if folder_name not in inventory:
                inventory[folder_name] = {
                    "folder_name": folder_name,
                    "organization": metadata.get("organization", ""),
                    "folder_year": metadata.get("folder_year", ""),
                    "doc_count": 0,
                    "categories": defaultdict(list),
                }

            # 중복 doc_id 방지
            if doc_id and doc_id not in seen_doc_ids[folder_name]:
                seen_doc_ids[folder_name].add(doc_id)
                inventory[folder_name]["doc_count"] += 1
                inventory[folder_name]["categories"][category].append(doc_id)

            # organization, year 업데이트
            if not inventory[folder_name]["organization"] and metadata.get("organization"):
                inventory[folder_name]["organization"] = metadata["organization"]
            if not inventory[folder_name]["folder_year"] and metadata.get("folder_year"):
                inventory[folder_name]["folder_year"] = metadata["folder_year"]

    # defaultdict를 일반 dict로 변환
    for folder_name in inventory:
        inventory[folder_name]["categories"] = dict(inventory[folder_name]["categories"])

    return {
        "source": "chunks",
        "snapshot": snapshot,
        "chunks_file": str(chunks_path),
        "generated_at": datetime.now().isoformat(),
        "total_folders": len(inventory),
        "total_documents": sum(inv["doc_count"] for inv in inventory.values()),
        "inventory": inventory,
    }


def save_inventory(data: dict, output_path: Path) -> None:
    """inventory를 JSON 파일로 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # inventory 부분만 추출해서 기존 형식과 호환되게 저장
    inventory_only = data.get("inventory", data)

    output_path.write_text(
        json.dumps(inventory_only, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 메타 정보는 별도 파일로 저장
    meta_path = output_path.with_suffix(".meta.json")
    meta_data = {k: v for k, v in data.items() if k != "inventory"}
    meta_path.write_text(
        json.dumps(meta_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build source-specific project inventory")
    parser.add_argument("--source-id", default=None, help="Document Source ID")
    parser.add_argument("--all", action="store_true", help="Process all document sources")
    parser.add_argument("--from-chunks", action="store_true", help="Build from chunks JSONL instead of DB")
    parser.add_argument("--snapshot", default=None, help="Snapshot name (with --from-chunks)")
    parser.add_argument("--output", default=None, help="Output path (default: data/staged/{source_id}_inventory.json)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    STAGED_DIR.mkdir(parents=True, exist_ok=True)

    if args.from_chunks:
        print("Building inventory from chunks JSONL...")
        data = build_inventory_from_chunks(args.snapshot)
        output_path = Path(args.output) if args.output else STAGED_DIR / "project_inventory.json"
        save_inventory(data, output_path)
        print(f"Generated: {output_path}")
        print(f"  Folders: {data['total_folders']}")
        print(f"  Documents: {data['total_documents']}")
        return 0

    sources = get_document_sources()

    if args.all:
        source_ids = [s["source_id"] for s in sources if s.get("source_id")]
    elif args.source_id:
        source_ids = [args.source_id]
    else:
        # 기본: rag_source만 처리
        source_ids = ["rag_source"]

    for source_id in source_ids:
        print(f"\nBuilding inventory for source_id: {source_id}")
        try:
            data = build_inventory_from_db(source_id)
            output_path = Path(args.output) if args.output else STAGED_DIR / f"{source_id}_inventory.json"
            save_inventory(data, output_path)
            print(f"  Generated: {output_path}")
            print(f"  Folders: {data['total_folders']}")
            print(f"  Documents: {data['total_documents']}")
        except Exception as e:
            print(f"  [ERROR] Failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
