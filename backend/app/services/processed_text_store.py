# OCR/파싱 결과 저장 모듈 - document_id 기준 결과 저장 및 조회
"""
OCR/파싱 결과를 document_id 기준으로 저장하고 관리합니다.

저장 구조 (source_id 지정 시 - 신규 통합 경로):
    data/source/{source_id}/step2_extract/documents/{document_id}/
    ├─ full_text.txt
    ├─ full_text.md
    ├─ pages.jsonl
    ├─ tables.jsonl
    ├─ ocr_report.json
    ├─ structured_data.json
    ├─ converted.pdf
    └─ assets/

저장 구조 (source_id 미지정 시 - 레거시 경로):
    data/documents/{document_id}/
    ├─ id_contract.json
    ├─ ocr/
    │  ├─ full_text.txt
    │  ├─ full_text.md
    │  ├─ pages.jsonl
    │  ├─ tables.jsonl
    │  ├─ ocr_report.json
    │  ├─ structured_data.json
    │  ├─ converted.pdf
    │  └─ assets/
    ├─ chunk/
    ├─ embedding/
    └─ run_config/

호환 경로:
    기존 data/processed_text/{document_id}/ 구조도 읽기 fallback으로 지원

사용 예시:
    # 신규 통합 경로 사용 (권장)
    store = ProcessedTextStore(source_id="src_20260711_090331_dda661")
    store.save_result(result)

    # 레거시 경로 사용
    store = ProcessedTextStore()
    store.save_result(result)
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class ProcessingResult:
    """OCR/파싱 처리 결과."""
    document_id: str
    file_name: str
    source_path: str = ""
    file_extension: str = ""
    source_id: str = ""
    dataset_id: str = ""
    document_uid: str = ""
    relative_path: str = ""
    project_name: str = ""
    organization: str = ""
    organization_type: str = ""
    client_type: str = ""
    project_type: str = ""

    # 처리 정보
    parser_type: str = ""          # hwp5txt, python-pptx, pdfplumber, tesseract, etc.
    ocr_required: bool = False
    ocr_engine: str = ""           # tesseract, easyocr, olmocr, etc.
    pdf_converted: bool = False

    # 처리 상태
    status: str = "pending"        # pending, running, done, failed, skipped
    error_message: str = ""

    # 텍스트 결과
    full_text: str = ""
    full_text_md: str = ""
    page_count: int = 0
    text_length: int = 0

    # 품질 정보
    quality: dict = field(default_factory=dict)

    # 페이지별 데이터
    pages: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    failed_pages: list[int] = field(default_factory=list)
    structured_data: dict = field(default_factory=dict)

    # 시간 정보
    created_at: str = ""
    updated_at: str = ""
    processing_time_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "file_name": self.file_name,
            "source_path": self.source_path,
            "file_extension": self.file_extension,
            "source_id": self.source_id,
            "dataset_id": self.dataset_id,
            "document_uid": self.document_uid,
            "relative_path": self.relative_path,
            "project_name": self.project_name,
            "organization": self.organization,
            "organization_type": self.organization_type,
            "client_type": self.client_type,
            "project_type": self.project_type,
            "parser_type": self.parser_type,
            "ocr_required": self.ocr_required,
            "ocr_engine": self.ocr_engine,
            "pdf_converted": self.pdf_converted,
            "status": self.status,
            "error_message": self.error_message,
            "page_count": self.page_count,
            "text_length": self.text_length,
            "quality": self.quality,
            "failed_pages": self.failed_pages,
            "structured_data": self.structured_data,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "processing_time_ms": self.processing_time_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProcessingResult":
        return cls(
            document_id=data.get("document_id", ""),
            file_name=data.get("file_name", ""),
            source_path=data.get("source_path", ""),
            file_extension=data.get("file_extension", ""),
            source_id=data.get("source_id", ""),
            dataset_id=data.get("dataset_id", ""),
            document_uid=data.get("document_uid", ""),
            relative_path=data.get("relative_path", ""),
            project_name=data.get("project_name", ""),
            organization=data.get("organization", ""),
            organization_type=data.get("organization_type", ""),
            client_type=data.get("client_type", ""),
            project_type=data.get("project_type", ""),
            parser_type=data.get("parser_type", ""),
            ocr_required=data.get("ocr_required", False),
            ocr_engine=data.get("ocr_engine", ""),
            pdf_converted=data.get("pdf_converted", False),
            status=data.get("status", "pending"),
            error_message=data.get("error_message", ""),
            full_text=data.get("full_text", ""),
            full_text_md=data.get("full_text_md", ""),
            page_count=data.get("page_count", 0),
            text_length=data.get("text_length", 0),
            quality=data.get("quality", {}),
            pages=data.get("pages", []),
            tables=data.get("tables", []),
            failed_pages=data.get("failed_pages", []),
            structured_data=data.get("structured_data", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            processing_time_ms=data.get("processing_time_ms", 0),
        )


class ProcessedTextStore:
    """OCR/파싱 결과 저장소."""

    def __init__(self, base_dir: Optional[str | Path] = None, source_id: Optional[str] = None):
        """
        저장소 초기화.

        Args:
            base_dir: 저장 기본 디렉토리 (기본값: data/documents)
            source_id: source_id 지정 시 통합 경로 사용
                       /data/source/{source_id}/step2_extract/documents/
        """
        project_root = Path(__file__).resolve().parents[3]
        self.source_id = source_id

        if source_id:
            # 신규 통합 경로: /data/source/{source_id}/step2_extract/documents/
            self.base_dir = project_root / "data" / "source" / source_id / "step2_extract" / "documents"
            self.use_unified_path = True
        elif base_dir:
            self.base_dir = Path(base_dir)
            self.use_unified_path = False
        else:
            # 레거시 경로: /data/documents/
            self.base_dir = project_root / "data" / "documents"
            self.use_unified_path = False

        # 레거시 fallback 경로
        self.legacy_base_dir = project_root / "data" / "processed_text"
        self.legacy_documents_dir = project_root / "data" / "documents"

        self.base_dir.mkdir(parents=True, exist_ok=True)
        if not self.use_unified_path:
            self.legacy_base_dir.mkdir(parents=True, exist_ok=True)

    def _doc_dir(self, document_id: str) -> Path:
        """document_id에 해당하는 디렉토리 경로."""
        return self.base_dir / document_id

    def _legacy_doc_dir(self, document_id: str) -> Path:
        """기존 processed_text 경로."""
        return self.legacy_base_dir / document_id

    def _legacy_documents_doc_dir(self, document_id: str) -> Path:
        """기존 documents 경로."""
        return self.legacy_documents_dir / document_id

    def get_document_root(self, document_id: str) -> Path:
        """현재 표준 문서 루트."""
        return self._doc_dir(document_id)

    def _stage_dir(self, document_id: str, stage: str) -> Path:
        if self.use_unified_path:
            # 통합 경로: document_id 폴더 바로 아래 (stage 무시, 플랫 구조)
            return self._doc_dir(document_id)
        return self._doc_dir(document_id) / stage

    def _ocr_dir(self, document_id: str) -> Path:
        if self.use_unified_path:
            # 통합 경로: document_id 폴더 바로 아래
            return self._doc_dir(document_id)
        return self._stage_dir(document_id, "ocr")

    def _chunk_dir(self, document_id: str) -> Path:
        return self._stage_dir(document_id, "chunk")

    def _embedding_dir(self, document_id: str) -> Path:
        return self._stage_dir(document_id, "embedding")

    def _metadata_dir(self, document_id: str) -> Path:
        return self._stage_dir(document_id, "metadata")

    def _keyword_dir(self, document_id: str) -> Path:
        return self._stage_dir(document_id, "keyword")

    def _graph_dir(self, document_id: str) -> Path:
        return self._stage_dir(document_id, "graph")

    def _wiki_dir(self, document_id: str) -> Path:
        return self._stage_dir(document_id, "wiki")

    def _run_config_dir(self, document_id: str) -> Path:
        return self._doc_dir(document_id) / "run_config"

    def _run_config_snapshot_dir(self, document_id: str) -> Path:
        return self._run_config_dir(document_id) / "snapshots"

    def _id_contract_path(self, document_id: str) -> Path:
        return self._doc_dir(document_id) / "id_contract.json"

    def _path_candidates(self, document_id: str, stage: str, file_name: str) -> list[Path]:
        """파일 검색을 위한 후보 경로 목록 반환 (우선순위 순서)."""
        candidates = []

        if self.use_unified_path:
            # 1순위: 통합 경로 (플랫 구조)
            candidates.append(self._doc_dir(document_id) / file_name)

        # 2순위: 현재 base_dir 기반 stage 경로
        candidates.append(self._stage_dir(document_id, stage) / file_name)

        # 3순위: 레거시 documents 경로
        candidates.append(self._legacy_documents_doc_dir(document_id) / stage / file_name)
        candidates.append(self._legacy_documents_doc_dir(document_id) / file_name)

        # 4순위: 레거시 processed_text 경로
        candidates.append(self._legacy_doc_dir(document_id) / stage / file_name)
        candidates.append(self._legacy_doc_dir(document_id) / file_name)

        # 중복 제거하면서 순서 유지
        seen = set()
        unique = []
        for c in candidates:
            key = str(c)
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique

    def _read_jsonl(self, path: Path) -> list[dict]:
        rows: list[dict] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _first_existing_path(self, candidates: list[Path]) -> Optional[Path]:
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def save_id_contract(self, document_id: str, payload: dict[str, Any]) -> Optional[Path]:
        doc_dir = self._doc_dir(document_id)
        doc_dir.mkdir(parents=True, exist_ok=True)
        current = {}
        path = self._id_contract_path(document_id)
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                current = {}
        merged = {
            **current,
            "document_id": str(document_id),
            "source_id": str(payload.get("source_id") or current.get("source_id") or ""),
            "dataset_id": str(payload.get("dataset_id") or current.get("dataset_id") or ""),
            "document_uid": str(payload.get("document_uid") or current.get("document_uid") or ""),
            "relative_path": str(payload.get("relative_path") or current.get("relative_path") or ""),
            "latest_snapshot_id": str(payload.get("snapshot_id") or payload.get("latest_snapshot_id") or current.get("latest_snapshot_id") or ""),
            "updated_at": datetime.now().isoformat(),
        }
        if not current.get("created_at"):
            merged["created_at"] = merged["updated_at"]
        else:
            merged["created_at"] = current.get("created_at")
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_run_config(self, document_id: str, payload: dict[str, Any], snapshot_id: Optional[str] = None) -> Optional[Path]:
        config_dir = self._run_config_dir(document_id)
        config_dir.mkdir(parents=True, exist_ok=True)
        latest_path = config_dir / "latest.json"
        current = {}
        if latest_path.exists():
            try:
                current = json.loads(latest_path.read_text(encoding="utf-8"))
            except Exception:
                current = {}

        merged = {
            **current,
            **payload,
            "document_id": str(document_id),
            "updated_at": datetime.now().isoformat(),
        }
        if not current.get("created_at"):
            merged["created_at"] = merged["updated_at"]
        else:
            merged["created_at"] = current.get("created_at")

        latest_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

        target_snapshot = str(snapshot_id or merged.get("snapshot_id") or "").strip()
        if target_snapshot:
            snap_dir = self._run_config_snapshot_dir(document_id)
            snap_dir.mkdir(parents=True, exist_ok=True)
            snap_path = snap_dir / f"{target_snapshot}.json"
            snap_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return latest_path

    def _assets_dir(self, document_id: str) -> Path:
        """assets 디렉토리 경로."""
        return self._ocr_dir(document_id) / "assets"

    def save_result(self, result: ProcessingResult) -> bool:
        """
        처리 결과 저장.

        Args:
            result: ProcessingResult 객체

        Returns:
            저장 성공 여부
        """
        try:
            doc_dir = self._ocr_dir(result.document_id)
            doc_dir.mkdir(parents=True, exist_ok=True)

            # 업데이트 시간 설정
            now = datetime.now().isoformat(timespec="seconds")
            if not result.created_at:
                result.created_at = now
            result.updated_at = now

            # 1. full_text.txt 저장
            if result.full_text:
                (doc_dir / "full_text.txt").write_text(
                    result.full_text, encoding="utf-8"
                )
                result.text_length = len(result.full_text)

            # 2. full_text.md 저장
            if result.full_text_md:
                (doc_dir / "full_text.md").write_text(
                    result.full_text_md, encoding="utf-8"
                )

            # 3. pages.jsonl 저장
            if result.pages:
                self._write_jsonl(doc_dir / "pages.jsonl", result.pages)
                result.page_count = len(result.pages)

            # 4. tables.jsonl 저장
            if result.tables:
                self._write_jsonl(doc_dir / "tables.jsonl", result.tables)

            # 5. ocr_report.json 저장
            report = result.to_dict()
            (doc_dir / "ocr_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            # 6. structured_data.json 저장
            if result.structured_data:
                (doc_dir / "structured_data.json").write_text(
                    json.dumps(result.structured_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            self.save_id_contract(result.document_id, result.to_dict())
            self.save_run_config(
                result.document_id,
                {
                    "source_id": result.source_id,
                    "dataset_id": result.dataset_id,
                    "document_uid": result.document_uid,
                    "relative_path": result.relative_path,
                    "snapshot_id": "",
                    "ocr": {
                        "engine": result.ocr_engine,
                        "parser_type": result.parser_type,
                    },
                },
            )

            return True

        except Exception as e:
            print(f"[ERROR] Failed to save result for {result.document_id}: {e}")
            return False

    def get_result(self, document_id: str) -> Optional[ProcessingResult]:
        """
        처리 결과 조회.

        Args:
            document_id: 문서 ID

        Returns:
            ProcessingResult 또는 None
        """
        report_path = self._first_existing_path(self._path_candidates(document_id, "ocr", "ocr_report.json"))

        if not report_path or not report_path.exists():
            return None

        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            result = ProcessingResult.from_dict(data)
            doc_dir = report_path.parent

            # full_text 로드
            text_path = self._first_existing_path(self._path_candidates(document_id, "ocr", "full_text.txt"))
            if text_path and text_path.exists():
                result.full_text = text_path.read_text(encoding="utf-8")

            # full_text_md 로드
            md_path = self._first_existing_path(self._path_candidates(document_id, "ocr", "full_text.md"))
            if md_path and md_path.exists():
                result.full_text_md = md_path.read_text(encoding="utf-8")

            # pages 로드
            pages_path = self._first_existing_path(self._path_candidates(document_id, "ocr", "pages.jsonl"))
            if pages_path and pages_path.exists():
                result.pages = self._read_jsonl(pages_path)

            # tables 로드
            tables_path = self._first_existing_path(self._path_candidates(document_id, "ocr", "tables.jsonl"))
            if tables_path and tables_path.exists():
                result.tables = self._read_jsonl(tables_path)

            structured_path = self._first_existing_path(self._path_candidates(document_id, "ocr", "structured_data.json"))
            if structured_path and structured_path.exists():
                result.structured_data = json.loads(structured_path.read_text(encoding="utf-8"))

            return result

        except Exception as e:
            print(f"[ERROR] Failed to load result for {document_id}: {e}")
            return None

    def get_report(self, document_id: str) -> Optional[dict]:
        """
        OCR 보고서만 조회 (텍스트 제외, 빠른 조회용).

        Args:
            document_id: 문서 ID

        Returns:
            보고서 dict 또는 None
        """
        report_path = self._first_existing_path(self._path_candidates(document_id, "ocr", "ocr_report.json"))
        if not report_path or not report_path.exists():
            return None

        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def get_text(self, document_id: str, format: str = "txt") -> Optional[str]:
        """
        텍스트만 조회.

        Args:
            document_id: 문서 ID
            format: "txt" 또는 "md"

        Returns:
            텍스트 또는 None
        """
        file_name = "full_text.md" if format == "md" else "full_text.txt"
        text_path = self._first_existing_path(self._path_candidates(document_id, "ocr", file_name))

        if not text_path or not text_path.exists():
            return None

        try:
            return text_path.read_text(encoding="utf-8")
        except Exception:
            return None

    def exists(self, document_id: str, check_unified_only: bool = True) -> bool:
        """
        처리 결과 존재 여부 확인.

        Args:
            document_id: 문서 ID
            check_unified_only: True이면 통합 경로(use_unified_path=True인 경우)만 확인,
                               False이면 레거시 경로까지 모두 확인

        Returns:
            처리 결과 존재 여부
        """
        if self.use_unified_path and check_unified_only:
            # 통합 경로만 확인 (레거시 경로 무시)
            report_path = self._doc_dir(document_id) / "ocr_report.json"
            return report_path.exists()

        # 레거시 경로 포함 전체 확인
        return self._first_existing_path(self._path_candidates(document_id, "ocr", "ocr_report.json")) is not None

    def get_structured_data(self, document_id: str) -> Optional[dict]:
        """구조화 데이터 조회."""
        structured_path = self._first_existing_path(self._path_candidates(document_id, "ocr", "structured_data.json"))
        if not structured_path or not structured_path.exists():
            return None
        try:
            return json.loads(structured_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def delete(self, document_id: str) -> bool:
        """처리 결과 삭제."""
        doc_dir = self._doc_dir(document_id)
        legacy_dir = self._legacy_doc_dir(document_id)
        ok = True
        if doc_dir.exists():
            try:
                shutil.rmtree(doc_dir)
            except Exception:
                ok = False
        if legacy_dir.exists():
            try:
                shutil.rmtree(legacy_dir)
            except Exception:
                ok = False
        return ok

    def list_documents(self, status: Optional[str] = None, limit: int = 100) -> list[dict]:
        """
        처리된 문서 목록 조회.

        Args:
            status: 상태 필터 (done, failed, pending 등)
            limit: 최대 반환 수

        Returns:
            보고서 목록
        """
        results = []

        seen: set[str] = set()
        all_dirs = []
        if self.base_dir.exists():
            all_dirs.extend(self.base_dir.iterdir())
        if self.legacy_base_dir.exists() and self.legacy_base_dir != self.base_dir:
            all_dirs.extend(self.legacy_base_dir.iterdir())

        for doc_dir in sorted(all_dirs, reverse=True):
            if not doc_dir.is_dir() or doc_dir.name in seen:
                continue
            seen.add(doc_dir.name)
            report = self.get_report(doc_dir.name)
            if report:
                if status and report.get("status") != status:
                    continue
                results.append(report)

            if len(results) >= limit:
                break

        return results

    def get_statistics(self) -> dict:
        """
        전체 통계 조회.

        Returns:
            {total, done, failed, pending, total_pages, total_chars}
        """
        stats = {
            "total": 0,
            "done": 0,
            "failed": 0,
            "pending": 0,
            "running": 0,
            "skipped": 0,
            "total_pages": 0,
            "total_chars": 0,
            "ocr_count": 0,
            "pdf_converted_count": 0,
        }

        for report in self.list_documents(limit=100000):
            if not report:
                continue

            stats["total"] += 1
            status = report.get("status", "pending")
            if status in stats:
                stats[status] += 1

            stats["total_pages"] += report.get("page_count", 0)
            stats["total_chars"] += report.get("text_length", 0)

            if report.get("ocr_required"):
                stats["ocr_count"] += 1
            if report.get("pdf_converted"):
                stats["pdf_converted_count"] += 1

        return stats

    def save_page_image(
        self,
        document_id: str,
        page_num: int,
        image_bytes: bytes,
        format: str = "png"
    ) -> Optional[str]:
        """
        페이지 이미지 저장.

        Args:
            document_id: 문서 ID
            page_num: 페이지 번호 (1-based)
            image_bytes: 이미지 바이트
            format: 이미지 포맷

        Returns:
            저장된 파일 경로 또는 None
        """
        assets_dir = self._assets_dir(document_id)
        assets_dir.mkdir(parents=True, exist_ok=True)

        file_name = f"page_{page_num:03d}.{format}"
        file_path = assets_dir / file_name

        try:
            file_path.write_bytes(image_bytes)
            return str(file_path)
        except Exception:
            return None

    def save_converted_pdf(self, document_id: str, pdf_bytes: bytes) -> Optional[str]:
        """
        변환된 PDF 저장.

        Args:
            document_id: 문서 ID
            pdf_bytes: PDF 바이트

        Returns:
            저장된 파일 경로 또는 None
        """
        doc_dir = self._ocr_dir(document_id)
        doc_dir.mkdir(parents=True, exist_ok=True)

        file_path = doc_dir / "converted.pdf"

        try:
            file_path.write_bytes(pdf_bytes)
            return str(file_path)
        except Exception:
            return None

    def get_stage_file_path(self, document_id: str, stage: str, file_name: str) -> Optional[Path]:
        return self._first_existing_path(self._path_candidates(document_id, stage, file_name))


# 싱글톤 인스턴스 (레거시 호환용)
try:
    import app.services.processed_text_store_extensions  # noqa: F401
except Exception:
    pass

processed_text_store = ProcessedTextStore()

# source_id별 store 캐시
_source_stores: dict[str, ProcessedTextStore] = {}


def get_processed_text_store(source_id: Optional[str] = None) -> ProcessedTextStore:
    """
    source_id에 맞는 ProcessedTextStore 인스턴스 반환.

    Args:
        source_id: source_id 지정 시 통합 경로 사용

    Returns:
        ProcessedTextStore 인스턴스
    """
    if not source_id:
        return processed_text_store

    if source_id not in _source_stores:
        _source_stores[source_id] = ProcessedTextStore(source_id=source_id)

    return _source_stores[source_id]


# ─────────────────────────────────────────────────────────────────────────────
# 테스트
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile

    # 임시 디렉토리에서 테스트
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProcessedTextStore(tmpdir)

        # 테스트 결과 생성
        result = ProcessingResult(
            document_id="doc_20260604_000001",
            file_name="테스트_문서.pdf",
            source_path="/data/test/테스트_문서.pdf",
            file_extension=".pdf",
            parser_type="pdfplumber",
            ocr_required=False,
            status="done",
            full_text="본 문서는 테스트용 문서입니다.\n정보화전략계획(ISP) 수립 사업입니다.",
            full_text_md="# 테스트 문서\n\n본 문서는 테스트용 문서입니다.",
            pages=[
                {"page_num": 1, "text": "본 문서는 테스트용 문서입니다.", "char_count": 16},
                {"page_num": 2, "text": "정보화전략계획(ISP) 수립 사업입니다.", "char_count": 20},
            ],
            quality={
                "quality_score": 0.85,
                "korean_ratio": 0.75,
                "decision": "use_direct_text",
            },
        )

        # 저장 테스트
        print("=== 저장 테스트 ===")
        success = store.save_result(result)
        print(f"저장 성공: {success}")

        # 존재 확인 테스트
        print("\n=== 존재 확인 ===")
        print(f"exists: {store.exists('doc_20260604_000001')}")
        print(f"not exists: {store.exists('doc_nonexistent')}")

        # 조회 테스트
        print("\n=== 조회 테스트 ===")
        loaded = store.get_result("doc_20260604_000001")
        if loaded:
            print(f"document_id: {loaded.document_id}")
            print(f"status: {loaded.status}")
            print(f"text_length: {loaded.text_length}")
            print(f"page_count: {loaded.page_count}")
            print(f"quality_score: {loaded.quality.get('quality_score')}")

        # 보고서만 조회
        print("\n=== 보고서 조회 ===")
        report = store.get_report("doc_20260604_000001")
        if report:
            print(f"file_name: {report.get('file_name')}")
            print(f"parser_type: {report.get('parser_type')}")

        # 텍스트만 조회
        print("\n=== 텍스트 조회 ===")
        text = store.get_text("doc_20260604_000001", "txt")
        if text:
            print(f"텍스트 (앞 50자): {text[:50]}...")

        # 목록 조회
        print("\n=== 목록 조회 ===")
        docs = store.list_documents()
        print(f"총 문서 수: {len(docs)}")

        # 통계 조회
        print("\n=== 통계 조회 ===")
        stats = store.get_statistics()
        print(f"통계: {stats}")

        # 삭제 테스트
        print("\n=== 삭제 테스트 ===")
        deleted = store.delete("doc_20260604_000001")
        print(f"삭제 성공: {deleted}")
        print(f"삭제 후 exists: {store.exists('doc_20260604_000001')}")
