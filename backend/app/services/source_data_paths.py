# source_id 기반 통합 데이터 경로 관리 모듈
"""
Source Data Paths - 단일 source_id 기준 모든 데이터 경로 통합 관리

설계 원칙:
1. source_id 하나로 모든 단계별 데이터에 접근 가능
2. 각 단계(step1~step6)의 데이터가 한 폴더 내에 구조화
3. ID 계약 관계 검증이 한 곳에서 완결
4. LLM이 사용하는 최종 데이터셋은 active/ 폴더에 명확히 정의

폴더 구조:
/data/source/{source_id}/
├── source.json              # Source 정의
├── documents.jsonl          # 문서 목록 (document_id 포함)
├── snapshots.json           # 스냅샷 히스토리
├── latest_snapshot.json     # 활성 스냅샷
│
├── step1_scan/              # Document Source Scan 결과
│   └── scan_result.json
│
├── step2_extract/           # OCR/텍스트 추출 결과
│   ├── documents/           # 문서별 하위 폴더
│   │   └── {document_id}/
│   │       ├── full_text.txt
│   │       ├── ocr_report.json
│   │       └── structured.json
│   └── summary.json
│
├── step3_chunk/             # 청킹 결과
│   ├── chunks.jsonl
│   └── chunk_summary.json
│
├── step4_metadata/          # 메타데이터 생성 결과
│   └── metadata_result.json
│
├── step5_tag_keyword/       # 태그/키워드 결과
│   └── tag_keyword_result.json
│
├── step6_embedding/         # 임베딩/인덱스 결과
│   ├── faiss.index
│   ├── faiss_metadata.jsonl
│   └── embedding_summary.json
│
└── active/                  # LLM이 사용하는 최종 데이터셋
    ├── chunks.jsonl
    ├── faiss.index
    ├── metadata.jsonl
    └── config.json

작성일: 2026-07-09
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings

# 프로젝트 루트
PROJECT_ROOT = Path(settings.data_dir).parent


@dataclass
class SourceDataPaths:
    """source_id 기준 모든 데이터 경로를 제공하는 클래스"""

    source_id: str
    base_dir: Path = None

    def __post_init__(self):
        if self.base_dir is None:
            self.base_dir = Path(settings.data_dir) / "source" / self.source_id

    # === 루트 레벨 파일 ===

    @property
    def source_json(self) -> Path:
        """Source 정의 파일"""
        return self.base_dir / "source.json"

    @property
    def documents_jsonl(self) -> Path:
        """문서 목록 (document_id 매핑)"""
        return self.base_dir / "documents.jsonl"

    @property
    def snapshots_json(self) -> Path:
        """스냅샷 히스토리"""
        return self.base_dir / "snapshots.json"

    @property
    def latest_snapshot_json(self) -> Path:
        """활성 스냅샷 정보"""
        return self.base_dir / "latest_snapshot.json"

    # === Step 1: Scan ===

    @property
    def step1_dir(self) -> Path:
        return self.base_dir / "step1_scan"

    @property
    def scan_result_json(self) -> Path:
        return self.step1_dir / "scan_result.json"

    # === Step 2: Extract (OCR/텍스트 추출) ===

    @property
    def step2_dir(self) -> Path:
        return self.base_dir / "step2_extract"

    @property
    def step2_documents_dir(self) -> Path:
        return self.step2_dir / "documents"

    def document_dir(self, document_id: str) -> Path:
        """특정 문서의 추출 결과 폴더"""
        return self.step2_documents_dir / document_id

    def document_full_text(self, document_id: str) -> Path:
        """문서 전체 텍스트"""
        return self.document_dir(document_id) / "full_text.txt"

    def document_ocr_report(self, document_id: str) -> Path:
        """문서 OCR 리포트"""
        return self.document_dir(document_id) / "ocr_report.json"

    def document_structured_json(self, document_id: str) -> Path:
        """문서 구조화 JSON"""
        return self.document_dir(document_id) / "structured.json"

    @property
    def extract_summary_json(self) -> Path:
        """추출 단계 요약"""
        return self.step2_dir / "summary.json"

    # === Step 3: Chunk ===

    @property
    def step3_dir(self) -> Path:
        return self.base_dir / "step3_chunk"

    @property
    def chunks_jsonl(self) -> Path:
        """청크 데이터 (전체 문서 통합)"""
        return self.step3_dir / "chunks.jsonl"

    @property
    def chunk_summary_json(self) -> Path:
        """청킹 단계 요약"""
        return self.step3_dir / "chunk_summary.json"

    # === Step 4: Metadata ===

    @property
    def step4_dir(self) -> Path:
        return self.base_dir / "step4_metadata"

    @property
    def metadata_result_json(self) -> Path:
        """메타데이터 생성 결과"""
        return self.step4_dir / "metadata_result.json"

    # === Step 5: Tag/Keyword ===

    @property
    def step5_dir(self) -> Path:
        return self.base_dir / "step5_tag_keyword"

    @property
    def tag_keyword_result_json(self) -> Path:
        """태그/키워드 생성 결과"""
        return self.step5_dir / "tag_keyword_result.json"

    # === Step 6: Embedding/Index ===

    @property
    def step6_dir(self) -> Path:
        return self.base_dir / "step6_embedding"

    @property
    def faiss_index(self) -> Path:
        """FAISS 인덱스 파일"""
        return self.step6_dir / "faiss.index"

    @property
    def faiss_metadata_jsonl(self) -> Path:
        """FAISS 메타데이터 (벡터 번호 ↔ chunk_id 매핑)"""
        return self.step6_dir / "faiss_metadata.jsonl"

    @property
    def embedding_summary_json(self) -> Path:
        """임베딩 단계 요약"""
        return self.step6_dir / "embedding_summary.json"

    # === Active (LLM 사용 데이터셋) ===

    @property
    def active_dir(self) -> Path:
        return self.base_dir / "active"

    @property
    def active_chunks_jsonl(self) -> Path:
        """LLM이 참조하는 청크 데이터"""
        return self.active_dir / "chunks.jsonl"

    @property
    def active_faiss_index(self) -> Path:
        """LLM이 사용하는 FAISS 인덱스"""
        return self.active_dir / "faiss.index"

    @property
    def active_metadata_jsonl(self) -> Path:
        """LLM이 참조하는 메타데이터"""
        return self.active_dir / "metadata.jsonl"

    @property
    def active_config_json(self) -> Path:
        """활성 데이터셋 설정"""
        return self.active_dir / "config.json"

    # === 유틸리티 메서드 ===

    def ensure_dirs(self) -> None:
        """모든 단계별 디렉토리 생성"""
        dirs = [
            self.base_dir,
            self.step1_dir,
            self.step2_dir,
            self.step2_documents_dir,
            self.step3_dir,
            self.step4_dir,
            self.step5_dir,
            self.step6_dir,
            self.active_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def ensure_document_dir(self, document_id: str) -> Path:
        """문서별 디렉토리 생성 후 경로 반환"""
        doc_dir = self.document_dir(document_id)
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir

    def exists(self) -> bool:
        """source_id 폴더 존재 여부"""
        return self.base_dir.exists()

    def get_step_status(self) -> Dict[str, bool]:
        """각 단계별 완료 상태 확인"""
        return {
            "step1_scan": self.scan_result_json.exists(),
            "step2_extract": self.extract_summary_json.exists(),
            "step3_chunk": self.chunks_jsonl.exists(),
            "step4_metadata": self.metadata_result_json.exists(),
            "step5_tag_keyword": self.tag_keyword_result_json.exists(),
            "step6_embedding": self.faiss_index.exists(),
            "active": self.active_faiss_index.exists(),
        }

    def load_json(self, path: Path) -> Optional[Dict[str, Any]]:
        """JSON 파일 로드"""
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_json(self, path: Path, data: Dict[str, Any]) -> None:
        """JSON 파일 저장"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def load_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        """JSONL 파일 로드"""
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def save_jsonl(self, path: Path, rows: List[Dict[str, Any]]) -> None:
        """JSONL 파일 저장"""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(row, ensure_ascii=False) for row in rows]
        path.write_text("\n".join(lines), encoding="utf-8")

    def get_document_ids(self) -> List[str]:
        """documents.jsonl에서 모든 document_id 목록 조회"""
        docs = self.load_jsonl(self.documents_jsonl)
        return [str(doc.get("document_id", "")) for doc in docs if doc.get("document_id")]

    def validate_id_contract(self) -> Dict[str, Any]:
        """
        ID 계약 관계 검증
        - documents.jsonl의 document_id
        - step2_extract/documents/ 하위 폴더
        - step3_chunk/chunks.jsonl의 document_id
        - step6_embedding/faiss_metadata.jsonl의 document_id
        """
        doc_ids = set(self.get_document_ids())

        # step2 폴더 확인
        step2_doc_ids = set()
        if self.step2_documents_dir.exists():
            step2_doc_ids = {d.name for d in self.step2_documents_dir.iterdir() if d.is_dir()}

        # step3 청크의 document_id
        step3_doc_ids = set()
        for chunk in self.load_jsonl(self.chunks_jsonl):
            doc_id = chunk.get("document_id") or (chunk.get("metadata") or {}).get("document_id")
            if doc_id:
                step3_doc_ids.add(str(doc_id))

        # step6 FAISS 메타데이터의 document_id
        step6_doc_ids = set()
        for meta in self.load_jsonl(self.faiss_metadata_jsonl):
            doc_id = meta.get("document_id")
            if doc_id:
                step6_doc_ids.add(str(doc_id))

        # 불일치 검출
        missing_in_step2 = doc_ids - step2_doc_ids if step2_doc_ids else set()
        missing_in_step3 = doc_ids - step3_doc_ids if step3_doc_ids else set()
        missing_in_step6 = doc_ids - step6_doc_ids if step6_doc_ids else set()

        orphan_in_step2 = step2_doc_ids - doc_ids if step2_doc_ids else set()
        orphan_in_step3 = step3_doc_ids - doc_ids if step3_doc_ids else set()
        orphan_in_step6 = step6_doc_ids - doc_ids if step6_doc_ids else set()

        all_valid = (
            not missing_in_step2 and not missing_in_step3 and not missing_in_step6 and
            not orphan_in_step2 and not orphan_in_step3 and not orphan_in_step6
        )

        return {
            "valid": all_valid,
            "document_count": len(doc_ids),
            "step2_extract_count": len(step2_doc_ids),
            "step3_chunk_count": len(step3_doc_ids),
            "step6_embedding_count": len(step6_doc_ids),
            "missing": {
                "step2": list(missing_in_step2)[:10],
                "step3": list(missing_in_step3)[:10],
                "step6": list(missing_in_step6)[:10],
            },
            "orphan": {
                "step2": list(orphan_in_step2)[:10],
                "step3": list(orphan_in_step3)[:10],
                "step6": list(orphan_in_step6)[:10],
            },
        }


def get_source_paths(source_id: str) -> SourceDataPaths:
    """source_id로 경로 객체 생성"""
    return SourceDataPaths(source_id=source_id)


def list_all_sources() -> List[str]:
    """등록된 모든 source_id 목록"""
    source_dir = Path(settings.data_dir) / "source"
    if not source_dir.exists():
        return []
    return [
        d.name for d in source_dir.iterdir()
        if d.is_dir() and d.name.startswith("src_")
    ]


def get_active_source_id() -> Optional[str]:
    """현재 활성화된 source_id 조회"""
    active_file = Path(settings.data_dir) / "active_source.txt"
    if active_file.exists():
        return active_file.read_text().strip()
    # 가장 최근 source_id 반환
    sources = list_all_sources()
    return sources[-1] if sources else None


def set_active_source_id(source_id: str) -> None:
    """활성 source_id 설정"""
    active_file = Path(settings.data_dir) / "active_source.txt"
    active_file.write_text(source_id)


class UnifiedDocumentStore:
    """
    source_id 기반 통합 문서 저장소.

    기존 ProcessedTextStore와 호환되면서 통합 경로 구조를 사용합니다.
    source_id가 지정되면 통합 경로를, 아니면 기존 경로를 사용합니다.
    """

    def __init__(self, source_id: Optional[str] = None):
        self.source_id = source_id
        self._paths = get_source_paths(source_id) if source_id else None
        # 기존 경로 (fallback)
        self._legacy_base = Path(settings.data_dir) / "documents"

    def get_document_dir(self, document_id: str) -> Path:
        """문서 디렉토리 경로"""
        if self._paths:
            return self._paths.document_dir(document_id)
        return self._legacy_base / document_id

    def get_full_text_path(self, document_id: str) -> Path:
        """전체 텍스트 파일 경로"""
        if self._paths:
            return self._paths.document_full_text(document_id)
        return self._legacy_base / document_id / "ocr" / "full_text.txt"

    def get_ocr_report_path(self, document_id: str) -> Path:
        """OCR 리포트 경로"""
        if self._paths:
            return self._paths.document_ocr_report(document_id)
        return self._legacy_base / document_id / "ocr" / "ocr_report.json"

    def get_structured_json_path(self, document_id: str) -> Path:
        """구조화 JSON 경로"""
        if self._paths:
            return self._paths.document_structured_json(document_id)
        return self._legacy_base / document_id / "ocr" / "structured_data.json"

    def ensure_document_dir(self, document_id: str) -> Path:
        """문서 디렉토리 생성 후 경로 반환"""
        if self._paths:
            return self._paths.ensure_document_dir(document_id)
        doc_dir = self._legacy_base / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir

    def get_chunks_path(self) -> Path:
        """청크 파일 경로 (source_id 전체)"""
        if self._paths:
            return self._paths.chunks_jsonl
        return Path(settings.staged_chunks_dir) / "chunks.jsonl"

    def get_faiss_index_path(self) -> Path:
        """FAISS 인덱스 경로"""
        if self._paths:
            return self._paths.faiss_index
        return Path(settings.faiss_index_dir) / "default.index"

    def get_faiss_metadata_path(self) -> Path:
        """FAISS 메타데이터 경로"""
        if self._paths:
            return self._paths.faiss_metadata_jsonl
        return Path(settings.faiss_index_dir) / "default_metadata.jsonl"

    def get_tag_keyword_path(self) -> Path:
        """태그/키워드 결과 경로"""
        if self._paths:
            return self._paths.tag_keyword_result_json
        return Path(settings.data_dir) / "tag_keyword" / "result.json"

    def get_active_chunks_path(self) -> Path:
        """LLM이 사용하는 청크 경로"""
        if self._paths:
            return self._paths.active_chunks_jsonl
        return self.get_chunks_path()

    def get_active_faiss_path(self) -> Path:
        """LLM이 사용하는 FAISS 경로"""
        if self._paths:
            return self._paths.active_faiss_index
        return self.get_faiss_index_path()


def get_unified_store(source_id: Optional[str] = None) -> UnifiedDocumentStore:
    """통합 문서 저장소 인스턴스 반환"""
    return UnifiedDocumentStore(source_id=source_id)
