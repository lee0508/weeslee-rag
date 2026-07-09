# PDF/HWP 문서에서 표를 구조화하여 추출하는 서비스
"""
Table Extractor Service

PDF, HWP 문서에서 표를 추출하여 Markdown 또는 구조화된 형식으로 반환한다.
Camelot(lattice), Tabula(stream), pdfplumber를 조합하여 최적의 표 추출을 수행한다.
"""
from __future__ import annotations

import os
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
import logging

from app.core.locale_env import build_utf8_locale_env

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTable:
    """추출된 표 데이터."""
    page_number: int
    table_index: int  # 페이지 내 표 순서
    headers: List[str]
    rows: List[List[str]]
    markdown: str
    confidence: float  # 추출 신뢰도 (0-1)
    method: str  # 추출 방법 (camelot_lattice, tabula_stream, pdfplumber, etc.)
    bbox: Optional[Tuple[float, float, float, float]] = None  # (x0, y0, x1, y1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_number": self.page_number,
            "table_index": self.table_index,
            "headers": self.headers,
            "rows": self.rows,
            "markdown": self.markdown,
            "confidence": self.confidence,
            "method": self.method,
            "bbox": self.bbox,
        }


@dataclass
class TableExtractionResult:
    """표 추출 결과."""
    success: bool
    tables: List[ExtractedTable] = field(default_factory=list)
    total_tables: int = 0
    methods_used: List[str] = field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "tables": [t.to_dict() for t in self.tables],
            "total_tables": self.total_tables,
            "methods_used": self.methods_used,
            "error": self.error,
            "metadata": self.metadata,
        }


def _is_camelot_available() -> bool:
    """Camelot 사용 가능 여부 확인."""
    try:
        import camelot
        return True
    except ImportError:
        return False


def _is_tabula_available() -> bool:
    """Tabula 사용 가능 여부 확인."""
    try:
        import tabula
        return True
    except ImportError:
        return False


def _dataframe_to_markdown(df, include_index: bool = False) -> str:
    """DataFrame을 Markdown 표로 변환."""
    try:
        import pandas as pd
        if df is None or df.empty:
            return ""

        # 헤더
        headers = list(df.columns)
        header_row = "| " + " | ".join(str(h) for h in headers) + " |"
        separator = "| " + " | ".join(["---"] * len(headers)) + " |"

        # 데이터 행
        data_rows = []
        for _, row in df.iterrows():
            cells = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in row]
            data_rows.append("| " + " | ".join(cells) + " |")

        return "\n".join([header_row, separator] + data_rows)
    except Exception as e:
        logger.warning(f"DataFrame to Markdown 변환 실패: {e}")
        return ""


def _rows_to_markdown(headers: List[str], rows: List[List[str]]) -> str:
    """헤더와 행 리스트를 Markdown 표로 변환."""
    if not headers and not rows:
        return ""

    # 헤더가 없으면 첫 행을 헤더로 사용
    if not headers and rows:
        headers = rows[0]
        rows = rows[1:]

    if not headers:
        return ""

    header_row = "| " + " | ".join(str(h).replace("|", "\\|") for h in headers) + " |"
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"

    data_rows = []
    for row in rows:
        # 열 수 맞추기
        padded_row = row + [""] * (len(headers) - len(row))
        cells = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in padded_row[:len(headers)]]
        data_rows.append("| " + " | ".join(cells) + " |")

    return "\n".join([header_row, separator] + data_rows)


class PDFTableExtractor:
    """PDF 표 추출기."""

    def __init__(
        self,
        use_camelot: bool = True,
        use_tabula: bool = True,
        use_pdfplumber: bool = True,
        min_confidence: float = 0.5,
    ):
        self.use_camelot = use_camelot and _is_camelot_available()
        self.use_tabula = use_tabula and _is_tabula_available()
        self.use_pdfplumber = use_pdfplumber
        self.min_confidence = min_confidence

    def extract_tables(self, pdf_path: str, pages: str = "all") -> TableExtractionResult:
        """
        PDF에서 모든 표를 추출한다.

        Args:
            pdf_path: PDF 파일 경로
            pages: 추출할 페이지 ("all", "1-3", "1,3,5" 등)

        Returns:
            TableExtractionResult
        """
        if not os.path.exists(pdf_path):
            return TableExtractionResult(
                success=False,
                error=f"File not found: {pdf_path}"
            )

        all_tables: List[ExtractedTable] = []
        methods_used: List[str] = []

        # 1. Camelot (lattice mode) - 테두리가 있는 표에 최적
        if self.use_camelot:
            camelot_tables = self._extract_with_camelot_lattice(pdf_path, pages)
            if camelot_tables:
                all_tables.extend(camelot_tables)
                methods_used.append("camelot_lattice")

        # 2. Camelot (stream mode) - 테두리 없는 표
        if self.use_camelot:
            stream_tables = self._extract_with_camelot_stream(pdf_path, pages)
            # 중복 제거: 같은 페이지에서 lattice로 이미 추출한 표는 제외
            existing_pages = {(t.page_number, t.table_index) for t in all_tables}
            new_tables = [t for t in stream_tables
                         if (t.page_number, t.table_index) not in existing_pages]
            if new_tables:
                all_tables.extend(new_tables)
                methods_used.append("camelot_stream")

        # 3. Tabula - Camelot이 놓친 표 보완
        if self.use_tabula and len(all_tables) == 0:
            tabula_tables = self._extract_with_tabula(pdf_path, pages)
            if tabula_tables:
                all_tables.extend(tabula_tables)
                methods_used.append("tabula")

        # 4. pdfplumber - 최후의 수단
        if self.use_pdfplumber and len(all_tables) == 0:
            plumber_tables = self._extract_with_pdfplumber(pdf_path)
            if plumber_tables:
                all_tables.extend(plumber_tables)
                methods_used.append("pdfplumber")

        # 신뢰도 기준으로 필터링
        filtered_tables = [t for t in all_tables if t.confidence >= self.min_confidence]

        return TableExtractionResult(
            success=len(filtered_tables) > 0,
            tables=filtered_tables,
            total_tables=len(filtered_tables),
            methods_used=methods_used,
            metadata={
                "source": pdf_path,
                "pages": pages,
                "raw_table_count": len(all_tables),
                "filtered_table_count": len(filtered_tables),
            }
        )

    def _extract_with_camelot_lattice(
        self, pdf_path: str, pages: str
    ) -> List[ExtractedTable]:
        """Camelot lattice mode로 표 추출 (테두리 있는 표)."""
        try:
            import camelot

            tables = camelot.read_pdf(pdf_path, pages=pages, flavor='lattice')
            result = []

            for i, table in enumerate(tables):
                df = table.df
                if df is None or df.empty:
                    continue

                # 첫 행을 헤더로 사용
                headers = [str(h) for h in df.iloc[0].tolist()]
                rows = [[str(cell) for cell in row] for row in df.iloc[1:].values.tolist()]

                markdown = _rows_to_markdown(headers, rows)

                result.append(ExtractedTable(
                    page_number=table.page,
                    table_index=i,
                    headers=headers,
                    rows=rows,
                    markdown=markdown,
                    confidence=table.accuracy / 100.0 if hasattr(table, 'accuracy') else 0.8,
                    method="camelot_lattice",
                    bbox=table._bbox if hasattr(table, '_bbox') else None,
                ))

            return result

        except Exception as e:
            logger.warning(f"Camelot lattice extraction failed: {e}")
            return []

    def _extract_with_camelot_stream(
        self, pdf_path: str, pages: str
    ) -> List[ExtractedTable]:
        """Camelot stream mode로 표 추출 (테두리 없는 표)."""
        try:
            import camelot

            tables = camelot.read_pdf(pdf_path, pages=pages, flavor='stream')
            result = []

            for i, table in enumerate(tables):
                df = table.df
                if df is None or df.empty:
                    continue

                headers = [str(h) for h in df.iloc[0].tolist()]
                rows = [[str(cell) for cell in row] for row in df.iloc[1:].values.tolist()]

                markdown = _rows_to_markdown(headers, rows)

                # stream mode는 일반적으로 lattice보다 정확도가 낮음
                confidence = (table.accuracy / 100.0 * 0.8) if hasattr(table, 'accuracy') else 0.6

                result.append(ExtractedTable(
                    page_number=table.page,
                    table_index=i,
                    headers=headers,
                    rows=rows,
                    markdown=markdown,
                    confidence=confidence,
                    method="camelot_stream",
                    bbox=table._bbox if hasattr(table, '_bbox') else None,
                ))

            return result

        except Exception as e:
            logger.warning(f"Camelot stream extraction failed: {e}")
            return []

    def _extract_with_tabula(self, pdf_path: str, pages: str) -> List[ExtractedTable]:
        """Tabula로 표 추출."""
        try:
            import tabula

            # pages 파라미터 변환 ("all" -> "all", "1-3" -> "1-3")
            dfs = tabula.read_pdf(pdf_path, pages=pages, multiple_tables=True)
            result = []

            for i, df in enumerate(dfs):
                if df is None or df.empty:
                    continue

                headers = [str(h) for h in df.columns.tolist()]
                rows = [[str(cell) for cell in row] for row in df.values.tolist()]

                markdown = _rows_to_markdown(headers, rows)

                result.append(ExtractedTable(
                    page_number=1,  # Tabula는 페이지 정보를 정확히 제공하지 않음
                    table_index=i,
                    headers=headers,
                    rows=rows,
                    markdown=markdown,
                    confidence=0.7,  # Tabula 기본 신뢰도
                    method="tabula",
                ))

            return result

        except Exception as e:
            logger.warning(f"Tabula extraction failed: {e}")
            return []

    def _extract_with_pdfplumber(self, pdf_path: str) -> List[ExtractedTable]:
        """pdfplumber로 표 추출."""
        try:
            import pdfplumber

            result = []

            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    tables = page.extract_tables()

                    for table_idx, table in enumerate(tables):
                        if not table or len(table) < 2:
                            continue

                        headers = [str(cell or "") for cell in table[0]]
                        rows = [[str(cell or "") for cell in row] for row in table[1:]]

                        markdown = _rows_to_markdown(headers, rows)

                        result.append(ExtractedTable(
                            page_number=page_num,
                            table_index=table_idx,
                            headers=headers,
                            rows=rows,
                            markdown=markdown,
                            confidence=0.6,  # pdfplumber 기본 신뢰도
                            method="pdfplumber",
                        ))

            return result

        except Exception as e:
            logger.warning(f"pdfplumber extraction failed: {e}")
            return []


class HWPTableExtractor:
    """HWP 표 추출기."""

    def __init__(self, libreoffice_path: Optional[str] = None):
        self.libreoffice_path = libreoffice_path or self._find_libreoffice()

    def _find_libreoffice(self) -> str:
        """LibreOffice 경로 찾기."""
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            "/usr/bin/soffice",
            "/usr/local/bin/soffice",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return "soffice"

    def extract_tables(self, hwp_path: str) -> TableExtractionResult:
        """
        HWP에서 표를 추출한다.

        HWP → PDF 변환 후 PDF 표 추출기를 사용한다.
        """
        if not os.path.exists(hwp_path):
            return TableExtractionResult(
                success=False,
                error=f"File not found: {hwp_path}"
            )

        # HWP → PDF 변환
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                cmd = [
                    self.libreoffice_path,
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", tmpdir,
                    hwp_path
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=120,
                    env=build_utf8_locale_env(),
                )

                if result.returncode != 0:
                    stderr = result.stderr.decode("utf-8", errors="replace")
                    return TableExtractionResult(
                        success=False,
                        error=f"LibreOffice conversion failed: {stderr[:500]}"
                    )

                # 변환된 PDF 찾기
                pdf_files = list(Path(tmpdir).glob("*.pdf"))
                if not pdf_files:
                    return TableExtractionResult(
                        success=False,
                        error="PDF conversion produced no output"
                    )

                pdf_path = str(pdf_files[0])

                # PDF 표 추출
                pdf_extractor = PDFTableExtractor()
                pdf_result = pdf_extractor.extract_tables(pdf_path)

                # 메타데이터 업데이트
                pdf_result.metadata["original_file"] = hwp_path
                pdf_result.metadata["converted_pdf"] = pdf_path
                pdf_result.methods_used = [f"hwp_to_pdf_{m}" for m in pdf_result.methods_used]

                return pdf_result

            except subprocess.TimeoutExpired:
                return TableExtractionResult(
                    success=False,
                    error="LibreOffice conversion timed out (>120s)"
                )
            except Exception as e:
                return TableExtractionResult(
                    success=False,
                    error=str(e)
                )


class TableExtractorService:
    """통합 표 추출 서비스."""

    def __init__(self):
        self.pdf_extractor = PDFTableExtractor()
        self.hwp_extractor = HWPTableExtractor()

    def extract_tables(self, file_path: str, pages: str = "all") -> TableExtractionResult:
        """
        파일에서 표를 추출한다.

        Args:
            file_path: 파일 경로
            pages: 추출할 페이지 (PDF만 해당)

        Returns:
            TableExtractionResult
        """
        ext = Path(file_path).suffix.lower()

        if ext == ".pdf":
            return self.pdf_extractor.extract_tables(file_path, pages)
        elif ext in [".hwp", ".hwpx"]:
            return self.hwp_extractor.extract_tables(file_path)
        else:
            return TableExtractionResult(
                success=False,
                error=f"Unsupported file type: {ext}"
            )

    def extract_tables_as_markdown(self, file_path: str, pages: str = "all") -> str:
        """
        파일에서 표를 추출하여 Markdown 문자열로 반환한다.

        Args:
            file_path: 파일 경로
            pages: 추출할 페이지 (PDF만 해당)

        Returns:
            모든 표를 포함한 Markdown 문자열
        """
        result = self.extract_tables(file_path, pages)

        if not result.success or not result.tables:
            return ""

        parts = []
        for table in result.tables:
            header = f"### Table (Page {table.page_number}, #{table.table_index + 1})"
            parts.append(f"{header}\n\n{table.markdown}")

        return "\n\n".join(parts)


# 싱글톤 인스턴스
table_extractor_service = TableExtractorService()


def get_table_extractor_service() -> TableExtractorService:
    """TableExtractorService 싱글톤 반환."""
    return table_extractor_service
