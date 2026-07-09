# 기존 분산 데이터를 통합 source_id 구조로 마이그레이션하는 스크립트
"""
데이터 마이그레이션 스크립트: 분산 구조 → 통합 source_id 구조

기존 구조:
  /data/documents/{document_id}/        → step2_extract
  /data/staged/chunks/{snapshot}_chunks.jsonl  → step3_chunk
  /data/tag_keyword/{source_id}/        → step5_tag_keyword
  /data/indexes/faiss/{snapshot}_*      → step6_embedding

통합 구조:
  /data/source/{source_id}/
  ├── step1_scan/
  ├── step2_extract/documents/{document_id}/
  ├── step3_chunk/
  ├── step4_metadata/
  ├── step5_tag_keyword/
  ├── step6_embedding/
  └── active/

실행:
    python backend/scripts/migrate_to_unified_paths.py --source-id src_20260709_...
    python backend/scripts/migrate_to_unified_paths.py --all --dry-run

작성일: 2026-07-09
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.source_data_paths import (
    SourceDataPaths,
    get_source_paths,
    list_all_sources,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def get_documents_for_source(source_id: str) -> list[dict]:
    """source_id의 documents.jsonl에서 문서 목록 조회"""
    docs_path = DATA_DIR / "source" / source_id / "documents.jsonl"
    if not docs_path.exists():
        print(f"  ⚠️ documents.jsonl 없음: {docs_path}")
        return []

    docs = []
    for line in docs_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            docs.append(json.loads(line))
    return docs


def migrate_step2_extract(
    paths: SourceDataPaths,
    documents: list[dict],
    dry_run: bool = False,
) -> dict:
    """step2: 기존 /data/documents/{document_id}/ → step2_extract/documents/"""
    old_base = DATA_DIR / "documents"
    migrated = 0
    skipped = 0
    not_found = 0

    for doc in documents:
        document_id = str(doc.get("document_id", ""))
        if not document_id:
            continue

        old_dir = old_base / document_id
        new_dir = paths.document_dir(document_id)

        if new_dir.exists():
            skipped += 1
            continue

        if not old_dir.exists():
            not_found += 1
            continue

        if dry_run:
            print(f"    [DRY-RUN] {old_dir} → {new_dir}")
        else:
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            # 복사 (원본 보존)
            shutil.copytree(old_dir, new_dir)
        migrated += 1

    return {
        "step": "step2_extract",
        "migrated": migrated,
        "skipped": skipped,
        "not_found": not_found,
    }


def migrate_step3_chunk(
    paths: SourceDataPaths,
    source_id: str,
    dry_run: bool = False,
) -> dict:
    """step3: 기존 /data/staged/chunks/{snapshot}_chunks.jsonl → step3_chunk/"""
    old_chunks_dir = DATA_DIR / "staged" / "chunks"

    # source_id와 관련된 chunks.jsonl 찾기
    candidates = list(old_chunks_dir.glob(f"{source_id}*_chunks.jsonl"))

    # 또는 snapshot 기반
    snapshot_path = paths.latest_snapshot_json
    if snapshot_path.exists():
        try:
            snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot_id = snapshot_data.get("snapshot_id", "")
            if snapshot_id:
                candidates += list(old_chunks_dir.glob(f"{snapshot_id}*_chunks.jsonl"))
        except Exception:
            pass

    if not candidates:
        return {"step": "step3_chunk", "migrated": 0, "skipped": 0, "note": "청크 파일 없음"}

    new_path = paths.chunks_jsonl
    if new_path.exists():
        return {"step": "step3_chunk", "migrated": 0, "skipped": 1, "note": "이미 존재"}

    # 가장 최근 파일 선택
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    old_path = candidates[0]

    if dry_run:
        print(f"    [DRY-RUN] {old_path} → {new_path}")
        return {"step": "step3_chunk", "migrated": 1, "dry_run": True}

    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(old_path, new_path)

    return {"step": "step3_chunk", "migrated": 1, "source": str(old_path)}


def migrate_step5_tag_keyword(
    paths: SourceDataPaths,
    source_id: str,
    dry_run: bool = False,
) -> dict:
    """step5: 기존 /data/tag_keyword/{source_id}/ → step5_tag_keyword/"""
    old_dir = DATA_DIR / "tag_keyword" / source_id

    if not old_dir.exists():
        return {"step": "step5_tag_keyword", "migrated": 0, "note": "기존 데이터 없음"}

    new_dir = paths.step5_dir

    # latest 폴더의 tag_keyword_result.json 복사
    old_result = old_dir / "latest" / "tag_keyword_result.json"
    if not old_result.exists():
        # 다른 snapshot 폴더 확인
        for sub in old_dir.iterdir():
            if sub.is_dir():
                candidate = sub / "tag_keyword_result.json"
                if candidate.exists():
                    old_result = candidate
                    break

    if not old_result.exists():
        return {"step": "step5_tag_keyword", "migrated": 0, "note": "결과 파일 없음"}

    new_path = paths.tag_keyword_result_json
    if new_path.exists():
        return {"step": "step5_tag_keyword", "migrated": 0, "skipped": 1}

    if dry_run:
        print(f"    [DRY-RUN] {old_result} → {new_path}")
        return {"step": "step5_tag_keyword", "migrated": 1, "dry_run": True}

    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(old_result, new_path)

    return {"step": "step5_tag_keyword", "migrated": 1, "source": str(old_result)}


def migrate_step6_embedding(
    paths: SourceDataPaths,
    source_id: str,
    dry_run: bool = False,
) -> dict:
    """step6: 기존 /data/indexes/faiss/{snapshot}_* → step6_embedding/"""
    old_faiss_dir = DATA_DIR / "indexes" / "faiss"

    # snapshot_id 확인
    snapshot_path = paths.latest_snapshot_json
    snapshot_id = ""
    if snapshot_path.exists():
        try:
            snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot_id = snapshot_data.get("snapshot_id", "")
        except Exception:
            pass

    if not snapshot_id:
        # source_id로 직접 검색
        snapshot_id = source_id

    # FAISS 인덱스 파일 찾기
    index_candidates = list(old_faiss_dir.glob(f"{snapshot_id}*_ollama.index"))
    if not index_candidates:
        index_candidates = list(old_faiss_dir.glob(f"{snapshot_id}*.index"))

    if not index_candidates:
        return {"step": "step6_embedding", "migrated": 0, "note": "FAISS 인덱스 없음"}

    # 가장 최근 파일
    index_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    old_index = index_candidates[0]

    # 메타데이터 파일
    old_meta = old_index.with_suffix("").with_name(
        old_index.stem.replace(".index", "") + "_metadata.jsonl"
    )
    if not old_meta.exists():
        old_meta = Path(str(old_index).replace(".index", "_metadata.jsonl"))

    new_index = paths.faiss_index
    new_meta = paths.faiss_metadata_jsonl

    if new_index.exists():
        return {"step": "step6_embedding", "migrated": 0, "skipped": 1}

    if dry_run:
        print(f"    [DRY-RUN] {old_index} → {new_index}")
        if old_meta.exists():
            print(f"    [DRY-RUN] {old_meta} → {new_meta}")
        return {"step": "step6_embedding", "migrated": 1, "dry_run": True}

    new_index.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(old_index, new_index)

    if old_meta.exists():
        shutil.copy2(old_meta, new_meta)

    return {
        "step": "step6_embedding",
        "migrated": 1,
        "index": str(old_index),
        "metadata": str(old_meta) if old_meta.exists() else None,
    }


def create_active_symlinks(
    paths: SourceDataPaths,
    dry_run: bool = False,
) -> dict:
    """active/ 폴더에 최종 데이터 심볼릭 링크 또는 복사"""
    results = {}

    # chunks
    if paths.chunks_jsonl.exists() and not paths.active_chunks_jsonl.exists():
        if dry_run:
            print(f"    [DRY-RUN] Link {paths.chunks_jsonl} → {paths.active_chunks_jsonl}")
        else:
            paths.active_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paths.chunks_jsonl, paths.active_chunks_jsonl)
        results["chunks"] = "linked"

    # faiss index
    if paths.faiss_index.exists() and not paths.active_faiss_index.exists():
        if dry_run:
            print(f"    [DRY-RUN] Link {paths.faiss_index} → {paths.active_faiss_index}")
        else:
            paths.active_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paths.faiss_index, paths.active_faiss_index)
        results["faiss"] = "linked"

    # faiss metadata
    if paths.faiss_metadata_jsonl.exists() and not paths.active_metadata_jsonl.exists():
        if dry_run:
            print(f"    [DRY-RUN] Link {paths.faiss_metadata_jsonl} → {paths.active_metadata_jsonl}")
        else:
            paths.active_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paths.faiss_metadata_jsonl, paths.active_metadata_jsonl)
        results["metadata"] = "linked"

    return {"step": "active", "results": results}


def migrate_source(source_id: str, dry_run: bool = False) -> dict:
    """단일 source_id 마이그레이션"""
    print(f"\n{'='*60}")
    print(f"Source: {source_id}")
    print(f"{'='*60}")

    paths = get_source_paths(source_id)

    if not paths.exists():
        print(f"  ❌ Source 폴더가 존재하지 않습니다: {paths.base_dir}")
        return {"source_id": source_id, "error": "Source folder not found"}

    # 디렉토리 구조 생성
    if not dry_run:
        paths.ensure_dirs()

    # 문서 목록 로드
    documents = get_documents_for_source(source_id)
    print(f"  📄 문서 수: {len(documents)}")

    results = {
        "source_id": source_id,
        "document_count": len(documents),
        "steps": [],
    }

    # Step 2: Extract
    print("  ▶ Step 2: Extract 마이그레이션...")
    step2_result = migrate_step2_extract(paths, documents, dry_run)
    results["steps"].append(step2_result)
    print(f"    - Migrated: {step2_result.get('migrated', 0)}, "
          f"Skipped: {step2_result.get('skipped', 0)}, "
          f"Not found: {step2_result.get('not_found', 0)}")

    # Step 3: Chunk
    print("  ▶ Step 3: Chunk 마이그레이션...")
    step3_result = migrate_step3_chunk(paths, source_id, dry_run)
    results["steps"].append(step3_result)
    print(f"    - {step3_result}")

    # Step 5: Tag/Keyword
    print("  ▶ Step 5: Tag/Keyword 마이그레이션...")
    step5_result = migrate_step5_tag_keyword(paths, source_id, dry_run)
    results["steps"].append(step5_result)
    print(f"    - {step5_result}")

    # Step 6: Embedding
    print("  ▶ Step 6: Embedding 마이그레이션...")
    step6_result = migrate_step6_embedding(paths, source_id, dry_run)
    results["steps"].append(step6_result)
    print(f"    - {step6_result}")

    # Active 링크 생성
    print("  ▶ Active 링크 생성...")
    active_result = create_active_symlinks(paths, dry_run)
    results["steps"].append(active_result)
    print(f"    - {active_result}")

    # ID 계약 검증
    print("  ▶ ID 계약 검증...")
    validation = paths.validate_id_contract()
    results["validation"] = validation
    if validation["valid"]:
        print("    ✅ ID 계약 검증 통과")
    else:
        print(f"    ⚠️ ID 불일치 발견: {validation}")

    # 단계별 상태
    status = paths.get_step_status()
    results["step_status"] = status
    print(f"  📊 단계별 상태: {status}")

    return results


def main():
    parser = argparse.ArgumentParser(description="데이터 마이그레이션: 분산 구조 → 통합 source_id 구조")
    parser.add_argument("--source-id", help="마이그레이션할 source_id")
    parser.add_argument("--all", action="store_true", help="모든 source_id 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="실제 변경 없이 시뮬레이션")
    parser.add_argument("--output", help="결과 JSON 저장 경로")
    args = parser.parse_args()

    if args.dry_run:
        print("🔍 DRY-RUN 모드: 실제 변경 없음")

    if args.all:
        sources = list_all_sources()
        print(f"📦 전체 source 수: {len(sources)}")
    elif args.source_id:
        sources = [args.source_id]
    else:
        print("❌ --source-id 또는 --all 옵션을 지정하세요.")
        sys.exit(1)

    all_results = []
    for source_id in sources:
        result = migrate_source(source_id, dry_run=args.dry_run)
        all_results.append(result)

    # 요약
    print("\n" + "="*60)
    print("마이그레이션 요약")
    print("="*60)
    for result in all_results:
        source_id = result.get("source_id", "")
        valid = result.get("validation", {}).get("valid", False)
        status_icon = "✅" if valid else "⚠️"
        print(f"  {status_icon} {source_id}: {result.get('document_count', 0)} 문서")

    if args.output:
        Path(args.output).write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"\n결과 저장: {args.output}")


if __name__ == "__main__":
    main()
