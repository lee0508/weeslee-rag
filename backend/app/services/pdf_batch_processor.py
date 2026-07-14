# 대용량 PDF 분할 처리 서비스 - 100만+ 페이지 PDF를 청크 단위로 OCR 처리
"""
PDF Batch Processor - 대용량 PDF 분할 OCR 처리

대용량 PDF (100+ 페이지)를 청크 단위로 분할하여 처리하고,
체크포인트를 저장하여 중단 시 이어서 처리할 수 있습니다.

사용법:
    processor = PDFBatchProcessor(
        pdf_path="/path/to/large.pdf",
        output_dir="/path/to/output",
        pages_per_chunk=100,
    )

    # 전체 처리 (체크포인트 자동 저장/복구)
    result = await processor.process_all()

    # 또는 청크 단위 처리
    for chunk_result in processor.process_chunks():
        print(f"Chunk {chunk_result['chunk_id']} done")
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ChunkConfig:
    """PDF 청크 분할 설정."""

    pages_per_chunk: int = 100  # 청크당 페이지 수
    max_concurrent_chunks: int = 2  # 동시 처리 청크 수
    checkpoint_interval: int = 1  # N개 청크마다 체크포인트 저장
    retry_failed_chunks: int = 2  # 실패한 청크 재시도 횟수

    # 대용량 파일 기준
    large_file_pages: int = 200  # 이 페이지 이상이면 분할 처리
    very_large_file_pages: int = 500  # 이 페이지 이상이면 더 작은 청크 사용

    @classmethod
    def from_db(cls) -> "ChunkConfig":
        """DB 시스템 설정에서 청크 설정 로드."""
        def get_setting(key: str, default: Any) -> Any:
            try:
                from app.services.system_settings_service import get_system_setting
                return get_system_setting("ocr", key, default)
            except Exception:
                return default

        return cls(
            pages_per_chunk=int(get_setting("ocr_chunk_pages", 100)),
            max_concurrent_chunks=int(get_setting("ocr_concurrent_chunks", 2)),
            checkpoint_interval=int(get_setting("ocr_checkpoint_interval", 1)),
            retry_failed_chunks=int(get_setting("ocr_retry_failed", 2)),
            large_file_pages=int(get_setting("ocr_large_file_pages", 200)),
            very_large_file_pages=int(get_setting("ocr_very_large_file_pages", 500)),
        )


@dataclass
class ChunkResult:
    """청크 처리 결과."""

    chunk_id: int
    start_page: int
    end_page: int
    status: str  # pending, processing, completed, failed
    text: str = ""
    page_texts: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    processing_time_sec: float = 0.0
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BatchCheckpoint:
    """분할 처리 체크포인트 - 중단 시 복구용."""

    pdf_path: str
    total_pages: int
    pages_per_chunk: int
    total_chunks: int
    completed_chunks: List[int] = field(default_factory=list)
    failed_chunks: List[int] = field(default_factory=list)
    chunk_results: Dict[int, Dict] = field(default_factory=dict)
    started_at: str = ""
    last_updated: str = ""
    status: str = "running"  # running, completed, failed, interrupted

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "BatchCheckpoint":
        return cls(
            pdf_path=data.get("pdf_path", ""),
            total_pages=data.get("total_pages", 0),
            pages_per_chunk=data.get("pages_per_chunk", 100),
            total_chunks=data.get("total_chunks", 0),
            completed_chunks=data.get("completed_chunks", []),
            failed_chunks=data.get("failed_chunks", []),
            chunk_results=data.get("chunk_results", {}),
            started_at=data.get("started_at", ""),
            last_updated=data.get("last_updated", ""),
            status=data.get("status", "running"),
        )

    def get_pending_chunks(self) -> List[int]:
        """아직 처리되지 않은 청크 ID 목록."""
        all_chunks = set(range(self.total_chunks))
        done = set(self.completed_chunks)
        return sorted(all_chunks - done)

    def get_progress(self) -> float:
        """진행률 (0.0 ~ 1.0)."""
        if self.total_chunks == 0:
            return 0.0
        return len(self.completed_chunks) / self.total_chunks


class PDFBatchProcessor:
    """대용량 PDF 분할 OCR 처리기."""

    def __init__(
        self,
        pdf_path: str,
        output_dir: Optional[str] = None,
        config: Optional[ChunkConfig] = None,
        ocr_engine: str = "easyocr",
        ocr_use_gpu: bool = True,
        ocr_dpi: int = 200,
        ocr_language: str = "kor+eng",
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ):
        self.pdf_path = Path(pdf_path)
        self.output_dir = Path(output_dir) if output_dir else self.pdf_path.parent / f".ocr_chunks_{self.pdf_path.stem}"
        self.config = config or ChunkConfig.from_db()
        self.ocr_engine = ocr_engine
        self.ocr_use_gpu = ocr_use_gpu
        self.ocr_dpi = ocr_dpi
        self.ocr_language = ocr_language
        self.progress_callback = progress_callback

        # 내부 상태
        self._checkpoint: Optional[BatchCheckpoint] = None
        self._total_pages: int = 0

    def _get_checkpoint_path(self) -> Path:
        """체크포인트 파일 경로."""
        return self.output_dir / "checkpoint.json"

    def _get_chunk_output_dir(self, chunk_id: int) -> Path:
        """청크별 출력 디렉토리."""
        return self.output_dir / f"chunk_{chunk_id:04d}"

    def _get_total_pages(self) -> int:
        """PDF 총 페이지 수 조회."""
        if self._total_pages > 0:
            return self._total_pages

        try:
            import fitz
            with fitz.open(str(self.pdf_path)) as doc:
                self._total_pages = doc.page_count
        except ImportError:
            # PyMuPDF 없으면 pdfplumber 사용
            import pdfplumber
            with pdfplumber.open(str(self.pdf_path)) as pdf:
                self._total_pages = len(pdf.pages)

        return self._total_pages

    def _calculate_chunks(self) -> List[Tuple[int, int, int]]:
        """청크 범위 계산. [(chunk_id, start_page, end_page), ...]"""
        total_pages = self._get_total_pages()
        pages_per_chunk = self.config.pages_per_chunk

        # 초대용량 파일은 더 작은 청크 사용
        if total_pages > self.config.very_large_file_pages:
            pages_per_chunk = min(50, pages_per_chunk)
            logger.info(f"[PDFBatch] 초대용량 PDF ({total_pages}p), 청크 크기 축소: {pages_per_chunk}p/chunk")

        chunks = []
        chunk_id = 0
        for start in range(0, total_pages, pages_per_chunk):
            end = min(start + pages_per_chunk - 1, total_pages - 1)
            chunks.append((chunk_id, start, end))
            chunk_id += 1

        return chunks

    def needs_chunking(self) -> bool:
        """분할 처리가 필요한지 확인."""
        return self._get_total_pages() > self.config.large_file_pages

    def load_checkpoint(self) -> Optional[BatchCheckpoint]:
        """체크포인트 로드 (중단된 작업 복구용)."""
        checkpoint_path = self._get_checkpoint_path()
        if not checkpoint_path.exists():
            return None

        try:
            data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self._checkpoint = BatchCheckpoint.from_dict(data)
            logger.info(
                f"[PDFBatch] 체크포인트 로드: {len(self._checkpoint.completed_chunks)}/{self._checkpoint.total_chunks} 청크 완료"
            )
            return self._checkpoint
        except Exception as e:
            logger.warning(f"[PDFBatch] 체크포인트 로드 실패: {e}")
            return None

    def save_checkpoint(self) -> None:
        """체크포인트 저장."""
        if not self._checkpoint:
            return

        self._checkpoint.last_updated = datetime.now().isoformat()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        checkpoint_path = self._get_checkpoint_path()
        checkpoint_path.write_text(
            json.dumps(self._checkpoint.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _init_checkpoint(self) -> BatchCheckpoint:
        """새 체크포인트 초기화."""
        chunks = self._calculate_chunks()
        self._checkpoint = BatchCheckpoint(
            pdf_path=str(self.pdf_path),
            total_pages=self._get_total_pages(),
            pages_per_chunk=self.config.pages_per_chunk,
            total_chunks=len(chunks),
            started_at=datetime.now().isoformat(),
            last_updated=datetime.now().isoformat(),
        )
        self.save_checkpoint()
        return self._checkpoint

    def _split_pdf_chunk(self, chunk_id: int, start_page: int, end_page: int) -> Path:
        """PDF에서 특정 페이지 범위를 추출하여 별도 파일로 저장."""
        chunk_dir = self._get_chunk_output_dir(chunk_id)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_pdf = chunk_dir / f"chunk_{chunk_id:04d}.pdf"

        if chunk_pdf.exists():
            return chunk_pdf

        try:
            import fitz
            with fitz.open(str(self.pdf_path)) as src_doc:
                new_doc = fitz.open()
                # PyMuPDF는 0-indexed
                new_doc.insert_pdf(src_doc, from_page=start_page, to_page=end_page)
                new_doc.save(str(chunk_pdf))
                new_doc.close()
        except ImportError:
            # PyMuPDF 없으면 PyPDF2 사용
            from PyPDF2 import PdfReader, PdfWriter
            reader = PdfReader(str(self.pdf_path))
            writer = PdfWriter()
            for page_num in range(start_page, end_page + 1):
                writer.add_page(reader.pages[page_num])
            with open(chunk_pdf, "wb") as f:
                writer.write(f)

        logger.debug(f"[PDFBatch] 청크 PDF 생성: {chunk_pdf.name} (p{start_page+1}-{end_page+1})")
        return chunk_pdf

    async def _process_chunk(self, chunk_id: int, start_page: int, end_page: int) -> ChunkResult:
        """단일 청크 OCR 처리."""
        result = ChunkResult(
            chunk_id=chunk_id,
            start_page=start_page,
            end_page=end_page,
            status="processing",
        )

        start_time = time.time()

        try:
            # 1. 청크 PDF 분할
            chunk_pdf = self._split_pdf_chunk(chunk_id, start_page, end_page)

            # 2. OCR 처리
            from app.extractors.pdf_extractor import PDFExtractor

            extractor = PDFExtractor(
                use_ocr=True,
                ocr_use_gpu=self.ocr_use_gpu,
                ocr_dpi=self.ocr_dpi,
                ocr_language=self.ocr_language,
                ocr_engine=self.ocr_engine,
            )

            extract_result = await extractor.extract(str(chunk_pdf))

            if extract_result.get("success"):
                result.status = "completed"
                result.text = extract_result.get("content", "")

                # 페이지별 텍스트 파싱 (--- Page N --- 패턴)
                pages = []
                content = result.text
                import re
                page_pattern = r'--- Page (\d+) ---\n(.*?)(?=--- Page \d+ ---|$)'
                matches = re.findall(page_pattern, content, re.DOTALL)

                for page_num_str, page_text in matches:
                    # 청크 내 상대 페이지 -> 전체 PDF 절대 페이지로 변환
                    relative_page = int(page_num_str)
                    absolute_page = start_page + relative_page
                    pages.append({
                        "page_num": absolute_page,
                        "text": page_text.strip(),
                        "char_count": len(page_text.strip()),
                    })

                result.page_texts = pages
            else:
                result.status = "failed"
                result.error = extract_result.get("error", "Unknown OCR error")

        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            logger.exception(f"[PDFBatch] 청크 {chunk_id} 처리 실패")

        result.processing_time_sec = round(time.time() - start_time, 2)
        return result

    async def process_chunks_async(
        self,
        chunk_ids: Optional[List[int]] = None,
    ) -> Iterator[ChunkResult]:
        """
        청크들을 비동기로 처리하고 결과를 yield.

        Args:
            chunk_ids: 처리할 청크 ID 목록. None이면 미완료 청크 모두 처리.
        """
        if not self._checkpoint:
            existing = self.load_checkpoint()
            if existing:
                self._checkpoint = existing
            else:
                self._init_checkpoint()

        chunks = self._calculate_chunks()

        if chunk_ids is None:
            chunk_ids = self._checkpoint.get_pending_chunks()

        logger.info(f"[PDFBatch] {len(chunk_ids)}개 청크 처리 시작")

        for idx, chunk_id in enumerate(chunk_ids):
            if chunk_id >= len(chunks):
                continue

            _, start_page, end_page = chunks[chunk_id]

            # 진행률 콜백
            if self.progress_callback:
                self.progress_callback(
                    idx + 1,
                    len(chunk_ids),
                    f"청크 {chunk_id} 처리 중 (p{start_page+1}-{end_page+1})"
                )

            # 청크 처리
            result = await self._process_chunk(chunk_id, start_page, end_page)

            # 결과 저장
            if result.status == "completed":
                self._checkpoint.completed_chunks.append(chunk_id)
                if chunk_id in self._checkpoint.failed_chunks:
                    self._checkpoint.failed_chunks.remove(chunk_id)
            elif result.status == "failed":
                if chunk_id not in self._checkpoint.failed_chunks:
                    self._checkpoint.failed_chunks.append(chunk_id)

            self._checkpoint.chunk_results[chunk_id] = result.to_dict()

            # 체크포인트 저장 (설정된 간격마다)
            if (idx + 1) % self.config.checkpoint_interval == 0:
                self.save_checkpoint()

            yield result

        # 최종 체크포인트 저장
        self._checkpoint.status = "completed" if not self._checkpoint.failed_chunks else "partial"
        self.save_checkpoint()

    async def process_all(self) -> Dict[str, Any]:
        """전체 PDF를 분할 처리하고 결과 병합."""
        start_time = time.time()

        # 분할이 필요없으면 일반 처리
        if not self.needs_chunking():
            logger.info(f"[PDFBatch] 소형 PDF ({self._get_total_pages()}p), 일반 처리")
            from app.extractors.pdf_extractor import PDFExtractor
            extractor = PDFExtractor(
                use_ocr=True,
                ocr_use_gpu=self.ocr_use_gpu,
                ocr_dpi=self.ocr_dpi,
                ocr_language=self.ocr_language,
                ocr_engine=self.ocr_engine,
            )
            return await extractor.extract(str(self.pdf_path))

        # 분할 처리
        logger.info(f"[PDFBatch] 대용량 PDF ({self._get_total_pages()}p), 분할 처리 시작")

        all_results: List[ChunkResult] = []
        async for result in self.process_chunks_async():
            all_results.append(result)

        # 결과 병합
        merged_text_parts = []
        merged_pages = []
        failed_chunks = []

        for result in sorted(all_results, key=lambda r: r.chunk_id):
            if result.status == "completed":
                merged_text_parts.append(result.text)
                merged_pages.extend(result.page_texts)
            else:
                failed_chunks.append({
                    "chunk_id": result.chunk_id,
                    "start_page": result.start_page,
                    "end_page": result.end_page,
                    "error": result.error,
                })

        total_time = round(time.time() - start_time, 2)

        return {
            "success": len(failed_chunks) == 0,
            "content": "\n\n".join(merged_text_parts),
            "pages": merged_pages,
            "metadata": {
                "source": str(self.pdf_path),
                "filename": self.pdf_path.name,
                "total_pages": self._get_total_pages(),
                "total_chunks": len(all_results),
                "completed_chunks": len([r for r in all_results if r.status == "completed"]),
                "failed_chunks": failed_chunks,
                "processing_time_sec": total_time,
                "batch_processed": True,
                "pages_per_chunk": self.config.pages_per_chunk,
            },
            "method": "pdf_batch_ocr",
        }

    def cleanup(self, keep_checkpoint: bool = False) -> None:
        """임시 파일 정리."""
        if self.output_dir.exists():
            if keep_checkpoint:
                # 체크포인트만 유지하고 청크 PDF 삭제
                for chunk_dir in self.output_dir.glob("chunk_*"):
                    shutil.rmtree(chunk_dir, ignore_errors=True)
            else:
                shutil.rmtree(self.output_dir, ignore_errors=True)

    @staticmethod
    def estimate_processing_time(total_pages: int, pages_per_sec: float = 2.0) -> Dict[str, Any]:
        """예상 처리 시간 계산."""
        total_sec = total_pages / pages_per_sec
        hours = int(total_sec // 3600)
        minutes = int((total_sec % 3600) // 60)

        return {
            "total_pages": total_pages,
            "estimated_seconds": round(total_sec),
            "estimated_time": f"{hours}시간 {minutes}분" if hours > 0 else f"{minutes}분",
            "pages_per_second": pages_per_sec,
        }


# 편의 함수
async def process_large_pdf(
    pdf_path: str,
    output_dir: Optional[str] = None,
    pages_per_chunk: int = 100,
    ocr_engine: str = "easyocr",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    """
    대용량 PDF를 분할 처리하는 편의 함수.

    Args:
        pdf_path: PDF 파일 경로
        output_dir: 출력 디렉토리 (기본: PDF 위치에 .ocr_chunks_{파일명})
        pages_per_chunk: 청크당 페이지 수
        ocr_engine: OCR 엔진 (easyocr, tesseract)
        progress_callback: 진행률 콜백 (current, total, message)

    Returns:
        추출 결과 딕셔너리
    """
    config = ChunkConfig(pages_per_chunk=pages_per_chunk)
    processor = PDFBatchProcessor(
        pdf_path=pdf_path,
        output_dir=output_dir,
        config=config,
        ocr_engine=ocr_engine,
        progress_callback=progress_callback,
    )

    try:
        return await processor.process_all()
    finally:
        processor.cleanup(keep_checkpoint=True)
