# OCR/파싱 결과 저장 모듈 - document_id 기준 결과 저장 및 조회
"""
OCR/파싱 결과를 document_id 기준으로 저장하고 관리합니다.

저장 구조:
    data/processed_text/{document_id}/
    ├─ full_text.txt          # 최종 텍스트
    ├─ full_text.md           # 마크다운 형식
    ├─ pages.jsonl            # 페이지별 텍스트
    ├─ tables.jsonl           # 표 데이터
    ├─ ocr_report.json        # 처리 결과 보고서
    ├─ converted.pdf          # PDF 변환본 (필요 시)
    └─ assets/
       ├─ page_001.png
       └─ ...

사용 예시:
    store = ProcessedTextStore()
    store.save_result(document_id, result)
    result = store.get_result(document_id)
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


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
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            processing_time_ms=data.get("processing_time_ms", 0),
        )


class ProcessedTextStore:
    """OCR/파싱 결과 저장소."""

    def __init__(self, base_dir: Optional[str | Path] = None):
        """
        저장소 초기화.

        Args:
            base_dir: 저장 기본 디렉토리 (기본값: data/processed_text)
        """
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            # 프로젝트 루트 기준
            project_root = Path(__file__).resolve().parents[3]
            self.base_dir = project_root / "data" / "processed_text"

        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _doc_dir(self, document_id: str) -> Path:
        """document_id에 해당하는 디렉토리 경로."""
        return self.base_dir / document_id

    def _assets_dir(self, document_id: str) -> Path:
        """assets 디렉토리 경로."""
        return self._doc_dir(document_id) / "assets"

    def save_result(self, result: ProcessingResult) -> bool:
        """
        처리 결과 저장.

        Args:
            result: ProcessingResult 객체

        Returns:
            저장 성공 여부
        """
        try:
            doc_dir = self._doc_dir(result.document_id)
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
                with (doc_dir / "pages.jsonl").open("w", encoding="utf-8") as f:
                    for page in result.pages:
                        f.write(json.dumps(page, ensure_ascii=False) + "\n")
                result.page_count = len(result.pages)

            # 4. tables.jsonl 저장
            if result.tables:
                with (doc_dir / "tables.jsonl").open("w", encoding="utf-8") as f:
                    for table in result.tables:
                        f.write(json.dumps(table, ensure_ascii=False) + "\n")

            # 5. ocr_report.json 저장
            report = result.to_dict()
            (doc_dir / "ocr_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8"
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
        doc_dir = self._doc_dir(document_id)
        report_path = doc_dir / "ocr_report.json"

        if not report_path.exists():
            return None

        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            result = ProcessingResult.from_dict(data)

            # full_text 로드
            text_path = doc_dir / "full_text.txt"
            if text_path.exists():
                result.full_text = text_path.read_text(encoding="utf-8")

            # full_text_md 로드
            md_path = doc_dir / "full_text.md"
            if md_path.exists():
                result.full_text_md = md_path.read_text(encoding="utf-8")

            # pages 로드
            pages_path = doc_dir / "pages.jsonl"
            if pages_path.exists():
                result.pages = []
                with pages_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            result.pages.append(json.loads(line))

            # tables 로드
            tables_path = doc_dir / "tables.jsonl"
            if tables_path.exists():
                result.tables = []
                with tables_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            result.tables.append(json.loads(line))

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
        report_path = self._doc_dir(document_id) / "ocr_report.json"
        if not report_path.exists():
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
        doc_dir = self._doc_dir(document_id)
        file_name = "full_text.md" if format == "md" else "full_text.txt"
        text_path = doc_dir / file_name

        if not text_path.exists():
            return None

        try:
            return text_path.read_text(encoding="utf-8")
        except Exception:
            return None

    def exists(self, document_id: str) -> bool:
        """처리 결과 존재 여부 확인."""
        return (self._doc_dir(document_id) / "ocr_report.json").exists()

    def delete(self, document_id: str) -> bool:
        """처리 결과 삭제."""
        doc_dir = self._doc_dir(document_id)
        if doc_dir.exists():
            try:
                shutil.rmtree(doc_dir)
                return True
            except Exception:
                return False
        return True

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

        for doc_dir in sorted(self.base_dir.iterdir(), reverse=True):
            if not doc_dir.is_dir():
                continue

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

        for doc_dir in self.base_dir.iterdir():
            if not doc_dir.is_dir():
                continue

            report = self.get_report(doc_dir.name)
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
        doc_dir = self._doc_dir(document_id)
        doc_dir.mkdir(parents=True, exist_ok=True)

        file_path = doc_dir / "converted.pdf"

        try:
            file_path.write_bytes(pdf_bytes)
            return str(file_path)
        except Exception:
            return None


# 싱글톤 인스턴스
processed_text_store = ProcessedTextStore()


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
