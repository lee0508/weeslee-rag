# Dataset Builder 데이터 검증 스크립트
"""
원격 서버에서 실행하여 Step 1, 2의 결과를 검증합니다.

실행 방법:
cd /var/www/weeslee-rag/backend
python3 scripts/verify_dataset_builder.py
"""
import sys
import os
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


def verify_database():
    """데이터베이스 연결 및 데이터 검증"""

    # 데이터베이스 연결
    database_url = f"mysql+pymysql://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    print("=" * 60)
    print("Dataset Builder 데이터 검증")
    print("=" * 60)

    try:
        # 1. 전체 레코드 수
        result = session.execute(text("SELECT COUNT(*) FROM document_metadata"))
        total = result.scalar()
        print(f"\n✓ 총 레코드 수: {total}개")

        if total == 0:
            print("❌ 경고: 레코드가 없습니다. Step 1을 먼저 실행하세요.")
            return False

        # 2. 상태별 분포
        result = session.execute(text("""
            SELECT meta_status, COUNT(*) as count
            FROM document_metadata
            GROUP BY meta_status
        """))
        print("\n✓ 상태별 분포:")
        status_counts = {}
        for row in result:
            status, count = row
            status_counts[status] = count
            print(f"  - {status}: {count}개")

        # 3. Source별 분포
        result = session.execute(text("""
            SELECT source_id, COUNT(*) as count
            FROM document_metadata
            GROUP BY source_id
        """))
        print("\n✓ Source별 분포:")
        for row in result:
            source, count = row
            print(f"  - {source}: {count}개")

        # 4. 프로젝트명 추출 확인
        result = session.execute(text("""
            SELECT COUNT(*) FROM document_metadata
            WHERE project_name IS NOT NULL AND project_name != ''
        """))
        with_project_name = result.scalar()
        print(f"\n✓ 프로젝트명 추출: {with_project_name}/{total}개")

        if with_project_name == 0:
            print("❌ 경고: 프로젝트명이 없습니다. Step 2를 실행하세요.")
            return False

        # 5. 샘플 데이터
        result = session.execute(text("""
            SELECT document_id, source_id, project_name, meta_status
            FROM document_metadata
            LIMIT 5
        """))
        print("\n✓ 샘플 데이터 (최근 5건):")
        for row in result:
            doc_id, source, project, status = row
            print(f"  - ID {doc_id}: [{source}] {project} [{status}]")

        # 6. 검증 결과 요약
        print("\n" + "=" * 60)
        print("검증 결과 요약")
        print("=" * 60)

        step1_ok = total > 0
        step2_ok = with_project_name > 0
        metadata_suggested = status_counts.get('metadata_suggested', 0)

        print(f"Step 1 (Source Scan): {'✅ 완료' if step1_ok else '❌ 미완료'}")
        print(f"Step 2 (Metadata Auto): {'✅ 완료' if step2_ok else '❌ 미완료'}")
        print(f"Step 3 준비 완료: {'✅ {metadata_suggested}개 검수 대기' if metadata_suggested > 0 else '⚠️  검수 대기 문서 없음'}")

        if step1_ok and step2_ok:
            print("\n✅ Dataset Builder가 정상적으로 작동하고 있습니다!")
            print(f"   원격 웹 UI에서 Step 3: Metadata Review를 진행할 수 있습니다.")
            return True
        else:
            print("\n❌ Dataset Builder 설정이 완료되지 않았습니다.")
            return False

    except Exception as e:
        print(f"\n❌ 검증 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        session.close()


if __name__ == "__main__":
    success = verify_database()
    sys.exit(0 if success else 1)
