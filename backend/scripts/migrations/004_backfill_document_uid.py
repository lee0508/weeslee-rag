# 기존 documents/document_metadata 레코드에 document_uid backfill
"""
Migration: Backfill document_uid for existing records
Date: 2026-06-12
Description: 기존 레코드에 source_id + relative_path 기반 document_uid 채우기

Usage:
    cd /data/weeslee/weeslee-rag/backend
    python scripts/migrations/004_backfill_document_uid.py [--dry-run]

Options:
    --dry-run: 실제 업데이트 없이 미리보기만 수행
"""
import sys
import argparse
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from sqlalchemy import text
from app.core.database import engine, SessionLocal
from app.services.document_uid import make_document_uid


def backfill_document_metadata(dry_run: bool = False):
    """document_metadata 테이블 backfill."""
    print("\n[1/2] document_metadata 테이블 backfill")
    print("-" * 50)

    db = SessionLocal()
    try:
        # document_uid가 없는 레코드 조회
        query = text("""
            SELECT id, document_id, source_id, file_path, relative_path
            FROM document_metadata
            WHERE document_uid IS NULL
              AND source_id IS NOT NULL
        """)
        rows = db.execute(query).fetchall()

        print(f"  대상 레코드: {len(rows)}건")

        if not rows:
            print("  [SKIP] 업데이트 대상 없음")
            return 0

        updated = 0
        for row in rows:
            record_id = row[0]
            document_id = row[1]
            source_id = row[2] or ""
            file_path = row[3] or ""
            relative_path = row[4]

            # relative_path가 없으면 file_path에서 추출 시도
            if not relative_path and file_path:
                # 단순히 파일명만 사용 (정확한 relative_path는 재스캔 필요)
                relative_path = Path(file_path).name

            if not source_id or not relative_path:
                print(f"  [SKIP] id={record_id}: source_id 또는 relative_path 없음")
                continue

            doc_uid = make_document_uid(source_id, relative_path)

            if dry_run:
                print(f"  [DRY-RUN] id={record_id}, document_id={document_id}")
                print(f"            source_id={source_id}, relative_path={relative_path}")
                print(f"            → document_uid={doc_uid}")
            else:
                update_query = text("""
                    UPDATE document_metadata
                    SET document_uid = :uid, relative_path = :rel_path
                    WHERE id = :id
                """)
                db.execute(update_query, {"uid": doc_uid, "rel_path": relative_path, "id": record_id})

            updated += 1

        if not dry_run:
            db.commit()
            print(f"  [OK] {updated}건 업데이트 완료")
        else:
            print(f"  [DRY-RUN] {updated}건 업데이트 예정")

        return updated

    except Exception as e:
        db.rollback()
        print(f"  [ERROR] {e}")
        return 0
    finally:
        db.close()


def backfill_documents(dry_run: bool = False):
    """documents 테이블 backfill."""
    print("\n[2/2] documents 테이블 backfill")
    print("-" * 50)

    db = SessionLocal()
    try:
        # document_uid가 없는 레코드 조회
        query = text("""
            SELECT d.id, d.filename, d.original_path, d.source_id,
                   dm.source_id as dm_source_id, dm.relative_path as dm_relative_path
            FROM documents d
            LEFT JOIN document_metadata dm ON d.id = dm.document_id
            WHERE d.document_uid IS NULL
        """)
        rows = db.execute(query).fetchall()

        print(f"  대상 레코드: {len(rows)}건")

        if not rows:
            print("  [SKIP] 업데이트 대상 없음")
            return 0

        updated = 0
        for row in rows:
            doc_id = row[0]
            filename = row[1]
            original_path = row[2]
            source_id = row[3] or row[4]  # documents.source_id 또는 metadata.source_id
            relative_path = row[5]  # metadata.relative_path

            # source_id가 없으면 기본값 사용
            if not source_id:
                source_id = "rag_source"

            # relative_path가 없으면 original_path 또는 filename 사용
            if not relative_path:
                if original_path:
                    relative_path = Path(original_path).name
                else:
                    relative_path = filename

            if not relative_path:
                print(f"  [SKIP] id={doc_id}: relative_path 결정 불가")
                continue

            doc_uid = make_document_uid(source_id, relative_path)

            if dry_run:
                print(f"  [DRY-RUN] id={doc_id}, filename={filename}")
                print(f"            source_id={source_id}, relative_path={relative_path}")
                print(f"            → document_uid={doc_uid}")
            else:
                update_query = text("""
                    UPDATE documents
                    SET document_uid = :uid, source_id = :source_id, relative_path = :rel_path
                    WHERE id = :id
                """)
                db.execute(update_query, {
                    "uid": doc_uid,
                    "source_id": source_id,
                    "rel_path": relative_path,
                    "id": doc_id
                })

            updated += 1

        if not dry_run:
            db.commit()
            print(f"  [OK] {updated}건 업데이트 완료")
        else:
            print(f"  [DRY-RUN] {updated}건 업데이트 예정")

        return updated

    except Exception as e:
        db.rollback()
        print(f"  [ERROR] {e}")
        return 0
    finally:
        db.close()


def run(dry_run: bool = False):
    """마이그레이션 실행."""
    print("=" * 60)
    print("Migration 004: Backfill document_uid")
    if dry_run:
        print("MODE: DRY-RUN (실제 업데이트 없음)")
    print("=" * 60)

    total = 0
    total += backfill_document_metadata(dry_run)
    total += backfill_documents(dry_run)

    print("\n" + "=" * 60)
    if dry_run:
        print(f"DRY-RUN 완료: 총 {total}건 업데이트 예정")
        print("실제 실행하려면 --dry-run 옵션 없이 실행하세요.")
    else:
        print(f"Migration 004 완료: 총 {total}건 업데이트")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill document_uid for existing records")
    parser.add_argument("--dry-run", action="store_true", help="Preview without actual updates")
    args = parser.parse_args()

    run(dry_run=args.dry_run)
