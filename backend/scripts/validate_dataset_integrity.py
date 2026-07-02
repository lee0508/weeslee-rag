#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
데이터셋 무결성 검증 스크립트

7개 핵심 질문 기반으로 데이터셋의 무결성을 검증합니다:
1. OCR/파싱: 문서 수, 성공률, 실패 원인
2. 청킹/임베딩: 청크 수, 벡터 수, 일관성
3. 메타데이터: 프로젝트명/기관명/산출물 유형 품질
4. 키워드 데이터: 생성 여부, 품질
5. 지식그래프: 노드/엣지 수, 파일 존재
6. Wiki 데이터: 생성 여부, document_id/source_id 추적
7. 전문검색(FTS5): 인덱싱 상태, source_id 설정

Usage:
    python backend/scripts/validate_dataset_integrity.py --source-id src_20260702_141532_3a5a53
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.database import get_db
from app.models.document_metadata import DocumentMetadata
from sqlalchemy import func

# 경로 설정
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
FAISS_DIR = DATA_DIR / "indexes" / "faiss"
GRAPH_DIR = DATA_DIR / "graph"
WIKI_DIR = DATA_DIR / "wiki"
PROCESSED_TEXT_DIR = DATA_DIR / "processed_text"
METADATA_DB = DATA_DIR / "metadata.db"


class DatasetValidator:
    """데이터셋 무결성 검증기"""

    def __init__(self, source_id: str):
        self.source_id = source_id
        self.db = next(get_db())
        self.results: Dict[str, Any] = {
            "source_id": source_id,
            "validated_at": datetime.now().isoformat(),
            "questions": []
        }

    def close(self):
        """DB 연결 종료"""
        self.db.close()

    def question_1_ocr_parsing(self) -> Dict[str, Any]:
        """질문 1: OCR/파싱은 정상적으로 완료되었는가?"""
        print("\n=== [질문 1] OCR/파싱 검증 ===")

        # DB에서 문서 수 조회
        total_docs = self.db.query(DocumentMetadata).filter(
            DocumentMetadata.source_id == self.source_id
        ).count()

        # OCR 완료된 문서 수
        ocr_completed = self.db.query(DocumentMetadata).filter(
            DocumentMetadata.source_id == self.source_id,
            DocumentMetadata.ocr_quality_score.isnot(None)
        ).count()

        # 실패한 문서
        failed_docs = self.db.query(DocumentMetadata).filter(
            DocumentMetadata.source_id == self.source_id,
            DocumentMetadata.ocr_quality_score.is_(None)
        ).all()

        success_rate = (ocr_completed / total_docs * 100) if total_docs > 0 else 0

        # processed_text 디렉토리 확인
        processed_count = 0
        if PROCESSED_TEXT_DIR.exists():
            for doc_dir in PROCESSED_TEXT_DIR.iterdir():
                if doc_dir.is_dir() and (doc_dir / "full_text.txt").exists():
                    processed_count += 1

        result = {
            "question": "OCR/파싱은 정상적으로 완료되었는가?",
            "status": "✅ 정상" if success_rate >= 95 else "⚠️ 주의" if success_rate >= 80 else "❌ 문제",
            "total_documents": total_docs,
            "ocr_completed": ocr_completed,
            "ocr_failed": len(failed_docs),
            "success_rate": f"{success_rate:.1f}%",
            "processed_text_files": processed_count,
            "failed_document_ids": [doc.document_id for doc in failed_docs[:10]]  # 최대 10개
        }

        print(f"  총 문서: {total_docs}개")
        print(f"  OCR 완료: {ocr_completed}개")
        print(f"  실패: {len(failed_docs)}개")
        print(f"  성공률: {success_rate:.1f}%")
        print(f"  Processed Text 파일: {processed_count}개")

        return result

    def question_2_chunking_embedding(self) -> Dict[str, Any]:
        """질문 2: 청킹/임베딩은 정상적으로 완료되었는가?"""
        print("\n=== [질문 2] 청킹/임베딩 검증 ===")

        # Snapshot manifest 찾기
        snapshot_files = list(SNAPSHOT_DIR.glob(f"*{self.source_id}*.json"))
        if not snapshot_files:
            return {
                "question": "청킹/임베딩은 정상적으로 완료되었는가?",
                "status": "❌ Snapshot 파일 없음",
                "error": "Snapshot manifest not found"
            }

        # 가장 최근 snapshot 읽기
        snapshot_file = max(snapshot_files, key=lambda p: p.stat().st_mtime)
        snapshot_data = json.loads(snapshot_file.read_text(encoding='utf-8'))

        chunk_count = snapshot_data.get("rag_build", {}).get("chunk_count", 0)
        vector_count = snapshot_data.get("rag_build", {}).get("vector_count", 0)

        # FAISS 파일 확인
        snapshot_id = snapshot_data.get("snapshot_id")
        faiss_index = FAISS_DIR / f"{snapshot_id}_ollama.index"
        faiss_metadata = FAISS_DIR / f"{snapshot_id}_ollama_metadata.jsonl"

        faiss_exists = faiss_index.exists() and faiss_metadata.exists()
        faiss_size = faiss_index.stat().st_size if faiss_index.exists() else 0

        # 메타데이터 JSONL에서 실제 청크 수 확인
        actual_chunks = 0
        if faiss_metadata.exists():
            with open(faiss_metadata, 'r', encoding='utf-8') as f:
                actual_chunks = sum(1 for _ in f)

        consistency_check = (chunk_count == vector_count == actual_chunks)

        result = {
            "question": "청킹/임베딩은 정상적으로 완료되었는가?",
            "status": "✅ 정상" if consistency_check and chunk_count > 0 else "❌ 문제",
            "snapshot_id": snapshot_id,
            "chunk_count": chunk_count,
            "vector_count": vector_count,
            "actual_chunks_in_metadata": actual_chunks,
            "consistency": consistency_check,
            "faiss_index_exists": faiss_exists,
            "faiss_index_size_mb": f"{faiss_size / (1024*1024):.2f}"
        }

        print(f"  Snapshot ID: {snapshot_id}")
        print(f"  청크 수: {chunk_count}")
        print(f"  벡터 수: {vector_count}")
        print(f"  실제 청크 (JSONL): {actual_chunks}")
        print(f"  일관성: {'✅ 일치' if consistency_check else '❌ 불일치'}")
        print(f"  FAISS 인덱스: {'✅ 있음' if faiss_exists else '❌ 없음'}")

        return result

    def question_3_metadata_quality(self) -> Dict[str, Any]:
        """질문 3: 메타데이터 품질은 정상적인가?"""
        print("\n=== [질문 3] 메타데이터 품질 검증 ===")

        docs = self.db.query(DocumentMetadata).filter(
            DocumentMetadata.source_id == self.source_id
        ).all()

        total = len(docs)
        if total == 0:
            return {
                "question": "메타데이터 품질은 정상적인가?",
                "status": "❌ 문서 없음",
                "total_documents": 0
            }

        # 프로젝트명
        project_names = [d.project_name for d in docs if d.project_name]
        project_coverage = len(project_names) / total * 100

        # 문장 일부 감지
        sentence_fragments = [
            name for name in project_names
            if any(name.endswith(end) for end in ['다.', '요.', '습니다.', '을', '를', '의', '에'])
        ]

        # 기관명
        organizations = [d.organization for d in docs if d.organization]
        org_coverage = len(organizations) / total * 100

        # 블랙리스트 단어
        blacklist_orgs = [org for org in organizations if org in ["출처", "참조", "참고"]]

        # 산출물 유형
        section_types = [d.section_type for d in docs if d.section_type]
        section_coverage = len(section_types) / total * 100

        quality_ok = (
            project_coverage >= 80 and
            len(sentence_fragments) == 0 and
            org_coverage >= 90 and
            len(blacklist_orgs) == 0 and
            section_coverage >= 95
        )

        result = {
            "question": "메타데이터 품질은 정상적인가?",
            "status": "✅ 우수" if quality_ok else "⚠️ 개선 필요",
            "total_documents": total,
            "project_name": {
                "coverage": f"{project_coverage:.1f}%",
                "sentence_fragments": len(sentence_fragments),
                "examples": sentence_fragments[:3]
            },
            "organization": {
                "coverage": f"{org_coverage:.1f}%",
                "blacklist_found": len(blacklist_orgs),
                "examples": blacklist_orgs[:3]
            },
            "section_type": {
                "coverage": f"{section_coverage:.1f}%"
            }
        }

        print(f"  프로젝트명 커버리지: {project_coverage:.1f}%")
        print(f"  문장 일부 감지: {len(sentence_fragments)}개")
        print(f"  기관명 커버리지: {org_coverage:.1f}%")
        print(f"  블랙리스트 단어: {len(blacklist_orgs)}개")
        print(f"  산출물 유형 커버리지: {section_coverage:.1f}%")

        return result

    def question_4_keyword_data(self) -> Dict[str, Any]:
        """질문 4: 키워드 데이터가 정상적으로 생성되었는가?"""
        print("\n=== [질문 4] 키워드 데이터 검증 ===")

        # TODO: 키워드 데이터 경로 및 테이블 확인
        # 현재는 파일 시스템 기반으로 확인

        keyword_dir = DATA_DIR / "tag_keyword" / self.source_id / "latest"
        keyword_exists = keyword_dir.exists() if keyword_dir else False
        keyword_files = list(keyword_dir.glob("*.json")) if keyword_exists else []

        result = {
            "question": "키워드 데이터가 정상적으로 생성되었는가?",
            "status": "✅ 있음" if keyword_files else "⚠️ 없음",
            "keyword_dir_exists": keyword_exists,
            "keyword_files_count": len(keyword_files)
        }

        print(f"  키워드 디렉토리: {'✅ 있음' if keyword_exists else '❌ 없음'}")
        print(f"  키워드 파일 수: {len(keyword_files)}개")

        return result

    def question_5_knowledge_graph(self) -> Dict[str, Any]:
        """질문 5: 지식그래프가 정상적으로 생성되었는가?"""
        print("\n=== [질문 5] 지식그래프 검증 ===")

        # Graph 파일 찾기
        graph_source_dir = GRAPH_DIR / self.source_id
        nodes_file = graph_source_dir / "graph_nodes.jsonl" if graph_source_dir.exists() else None
        edges_file = graph_source_dir / "graph_edges.jsonl" if graph_source_dir.exists() else None
        manifest_file = graph_source_dir / "graph_manifest.json" if graph_source_dir.exists() else None

        nodes_exist = nodes_file and nodes_file.exists()
        edges_exist = edges_file and edges_file.exists()
        manifest_exist = manifest_file and manifest_file.exists()

        node_count = 0
        edge_count = 0

        if nodes_exist:
            with open(nodes_file, 'r', encoding='utf-8') as f:
                node_count = sum(1 for _ in f)

        if edges_exist:
            with open(edges_file, 'r', encoding='utf-8') as f:
                edge_count = sum(1 for _ in f)

        graph_ok = nodes_exist and edges_exist and node_count > 0 and edge_count > 0

        result = {
            "question": "지식그래프가 정상적으로 생성되었는가?",
            "status": "✅ 정상" if graph_ok else "❌ 없음",
            "nodes_file_exists": nodes_exist,
            "edges_file_exists": edges_exist,
            "manifest_exists": manifest_exist,
            "node_count": node_count,
            "edge_count": edge_count
        }

        print(f"  노드 파일: {'✅ 있음' if nodes_exist else '❌ 없음'}")
        print(f"  엣지 파일: {'✅ 있음' if edges_exist else '❌ 없음'}")
        print(f"  매니페스트: {'✅ 있음' if manifest_exist else '❌ 없음'}")
        print(f"  노드 수: {node_count}개")
        print(f"  엣지 수: {edge_count}개")

        return result

    def question_6_wiki_data(self) -> Dict[str, Any]:
        """질문 6: Wiki 데이터가 정상적으로 생성되었는가? (document_id, source_id 추적 가능)"""
        print("\n=== [질문 6] Wiki 데이터 검증 ===")

        wiki_source_dir = WIKI_DIR / self.source_id
        wiki_projects_dir = wiki_source_dir / "projects" if wiki_source_dir.exists() else None
        build_info = wiki_source_dir / "build_info.json" if wiki_source_dir.exists() else None
        index_file = wiki_source_dir / "index.json" if wiki_source_dir.exists() else None

        wiki_files = list(wiki_projects_dir.glob("*.md")) if wiki_projects_dir and wiki_projects_dir.exists() else []

        # build_info.json 읽기
        build_data = {}
        if build_info and build_info.exists():
            build_data = json.loads(build_info.read_text(encoding='utf-8'))

        # index.json 읽기
        index_data = []
        if index_file and index_file.exists():
            index_data = json.loads(index_file.read_text(encoding='utf-8'))

        # Wiki 파일 샘플 읽어서 document_id, source_id 확인
        has_document_ids = False
        has_source_id = False

        if wiki_files:
            sample_wiki = wiki_files[0].read_text(encoding='utf-8')
            has_document_ids = "Document IDs" in sample_wiki or "document_id" in sample_wiki.lower()
            has_source_id = "Source ID" in sample_wiki or self.source_id in sample_wiki

        wiki_ok = (
            len(wiki_files) > 0 and
            build_info and build_info.exists() and
            index_file and index_file.exists() and
            has_document_ids and
            has_source_id
        )

        result = {
            "question": "Wiki 데이터가 정상적으로 생성되었는가? (document_id, source_id 추적 가능)",
            "status": "✅ 정상" if wiki_ok else "⚠️ 일부 누락",
            "wiki_files_count": len(wiki_files),
            "build_info_exists": build_info and build_info.exists(),
            "index_exists": index_file and index_file.exists(),
            "has_document_ids": has_document_ids,
            "has_source_id": has_source_id,
            "projects_in_index": len(index_data)
        }

        print(f"  Wiki 파일 수: {len(wiki_files)}개")
        print(f"  build_info.json: {'✅ 있음' if build_info and build_info.exists() else '❌ 없음'}")
        print(f"  index.json: {'✅ 있음' if index_file and index_file.exists() else '❌ 없음'}")
        print(f"  document_id 추적: {'✅ 가능' if has_document_ids else '❌ 불가'}")
        print(f"  source_id 추적: {'✅ 가능' if has_source_id else '❌ 불가'}")

        return result

    def question_7_fulltext_search(self) -> Dict[str, Any]:
        """질문 7: 전문검색(FTS5) 인덱싱이 정상적으로 완료되었는가?"""
        print("\n=== [질문 7] 전문검색(FTS5) 검증 ===")

        import sqlite3

        if not METADATA_DB.exists():
            return {
                "question": "전문검색(FTS5) 인덱싱이 정상적으로 완료되었는가?",
                "status": "❌ metadata.db 없음",
                "error": "metadata.db not found"
            }

        conn = sqlite3.connect(METADATA_DB)
        cursor = conn.cursor()

        # FTS5 테이블에 source_id로 인덱싱된 문서 수 확인
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM documents_fts WHERE source_id = ?",
                (self.source_id,)
            )
            indexed_count = cursor.fetchone()[0]
        except Exception as e:
            conn.close()
            return {
                "question": "전문검색(FTS5) 인덱싱이 정상적으로 완료되었는가?",
                "status": "❌ FTS5 테이블 오류",
                "error": str(e)
            }

        # DB에서 총 문서 수
        total_docs = self.db.query(DocumentMetadata).filter(
            DocumentMetadata.source_id == self.source_id
        ).count()

        coverage = (indexed_count / total_docs * 100) if total_docs > 0 else 0
        fts_ok = coverage >= 95

        result = {
            "question": "전문검색(FTS5) 인덱싱이 정상적으로 완료되었는가?",
            "status": "✅ 정상" if fts_ok else "⚠️ 부분 인덱싱" if indexed_count > 0 else "❌ 미인덱싱",
            "total_documents": total_docs,
            "indexed_documents": indexed_count,
            "coverage": f"{coverage:.1f}%"
        }

        conn.close()

        print(f"  총 문서 수: {total_docs}개")
        print(f"  인덱싱된 문서: {indexed_count}개")
        print(f"  커버리지: {coverage:.1f}%")

        return result

    def run_validation(self) -> Dict[str, Any]:
        """전체 검증 실행"""
        print(f"\n{'='*60}")
        print(f"데이터셋 무결성 검증 시작")
        print(f"Source ID: {self.source_id}")
        print(f"{'='*60}")

        # 7개 질문 순차 실행
        self.results["questions"].append(self.question_1_ocr_parsing())
        self.results["questions"].append(self.question_2_chunking_embedding())
        self.results["questions"].append(self.question_3_metadata_quality())
        self.results["questions"].append(self.question_4_keyword_data())
        self.results["questions"].append(self.question_5_knowledge_graph())
        self.results["questions"].append(self.question_6_wiki_data())
        self.results["questions"].append(self.question_7_fulltext_search())

        # 전체 평가
        statuses = [q.get("status", "") for q in self.results["questions"]]
        all_ok = all("✅" in status for status in statuses)
        some_issues = any("⚠️" in status for status in statuses)
        critical_issues = any("❌" in status for status in statuses)

        if all_ok:
            overall = "✅ 전체 정상"
        elif critical_issues:
            overall = "❌ 심각한 문제 발견"
        elif some_issues:
            overall = "⚠️ 일부 개선 필요"
        else:
            overall = "✅ 대체로 양호"

        self.results["overall_status"] = overall

        return self.results


def main():
    parser = argparse.ArgumentParser(description="데이터셋 무결성 검증")
    parser.add_argument("--source-id", required=True, help="Source ID")
    parser.add_argument("--output", help="결과 저장 경로 (JSON)")

    args = parser.parse_args()

    validator = DatasetValidator(args.source_id)

    try:
        results = validator.run_validation()

        # 결과 요약 출력
        print(f"\n{'='*60}")
        print("검증 결과 요약")
        print(f"{'='*60}")

        for i, question in enumerate(results["questions"], 1):
            print(f"{i}. {question['status']} {question['question']}")

        print(f"\n종합 평가: {results['overall_status']}")
        print(f"{'='*60}\n")

        # JSON 파일 저장
        if args.output:
            output_path = Path(args.output)
        else:
            output_path = PROJECT_ROOT / "docs" / f"validation_{args.source_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

        print(f"✅ 검증 결과 저장: {output_path}")

        sys.exit(0 if "✅" in results["overall_status"] else 1)

    except Exception as e:
        print(f"\n❌ 검증 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        validator.close()


if __name__ == "__main__":
    main()
