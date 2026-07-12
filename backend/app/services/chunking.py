# -*- coding: utf-8 -*-
"""
Text Chunking Service for RAG preprocessing
Splits documents into optimal chunks for embedding and retrieval

개선사항 (2026-07-09):
- 한국어 문장 단위 청킹 (kss 라이브러리) 지원
- 임베딩 모델 최대 토큰 제한 검증
- 토큰 초과 시 경고 로깅
"""
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# kss 라이브러리 (한국어 문장 분리) - 선택적 의존성
try:
    import kss
    KSS_AVAILABLE = True
except ImportError:
    KSS_AVAILABLE = False
    logger.info("kss 라이브러리 미설치 - 한국어 문장 단위 청킹 비활성화")


@dataclass
class TextChunk:
    """Represents a single text chunk"""
    content: str
    index: int
    start_char: int
    end_char: int
    token_count: int
    page_number: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class ChunkingService:
    """Service for splitting text into chunks optimized for RAG"""

    # Korean characters per token (approximate)
    # Korean uses about 1.5-2 characters per token on average
    KOREAN_CHARS_PER_TOKEN = 1.8
    # English words per token (approximate)
    ENGLISH_WORDS_PER_TOKEN = 0.75
    # 임베딩 모델 최대 토큰 (BGE-M3 기준 8192)
    MAX_EMBEDDING_TOKENS = 8192

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        min_chunk_size: int = 100,
        separators: Optional[List[str]] = None,
        use_korean_sentence_split: bool = True,
        max_embedding_tokens: int = 8192,
    ):
        """
        Initialize chunking service

        Args:
            chunk_size: Target chunk size in tokens
            chunk_overlap: Number of overlapping tokens between chunks
            min_chunk_size: Minimum chunk size (smaller chunks are merged)
            separators: List of separators for splitting (in priority order)
            use_korean_sentence_split: 한국어 문장 단위 분리 사용 여부 (kss)
            max_embedding_tokens: 임베딩 모델 최대 토큰 수 (초과 시 경고)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        # [2026-07-12] Kiwi 또는 kss 중 하나라도 있으면 문장 분리 사용 (Kiwi 우선, kss보다 빠름)
        self.use_korean_sentence_split = use_korean_sentence_split
        self.max_embedding_tokens = max_embedding_tokens
        self.separators = separators or [
            "\n\n\n",      # Multiple newlines (section breaks)
            "\n\n",        # Paragraph breaks
            "\n",          # Line breaks
            ". ",          # Sentence endings
            "。",          # Korean/Chinese sentence endings
            "! ",          # Exclamation
            "? ",          # Question
            "; ",          # Semicolon
            ", ",          # Comma
            " ",           # Space
            ""             # Character level (last resort)
        ]

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text (supports Korean and English)

        Args:
            text: Input text

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        # Count Korean characters
        korean_chars = len(re.findall(r'[가-힣]', text))

        # Estimate tokens
        korean_tokens = korean_chars / self.KOREAN_CHARS_PER_TOKEN
        # For non-Korean, count words approximately
        other_text = re.sub(r'[가-힣]', '', text)
        other_tokens = len(other_text.split()) * self.ENGLISH_WORDS_PER_TOKEN

        return int(korean_tokens + other_tokens)

    def _split_korean_sentences(self, text: str) -> List[str]:
        """
        한국어 문장 단위 분리.
        [2026-07-12] Kiwi 우선 사용(kss보다 수십 배 빠름) → kss → 원문 순으로 폴백.
        """
        if not self.use_korean_sentence_split:
            return [text]

        # 1) Kiwi (빠름)
        try:
            from app.services import korean_tokenizer
            kiwi_sents = korean_tokenizer.split_sentences(text)
            if kiwi_sents:
                return kiwi_sents
        except Exception as e:
            logger.debug("Kiwi 문장 분리 실패, kss로 폴백: %s", e)

        # 2) kss (느림, Kiwi 미설치 시)
        if KSS_AVAILABLE:
            try:
                sentences = kss.split_sentences(text)
                return sentences if sentences else [text]
            except Exception as e:
                logger.warning("kss 문장 분리 실패, fallback 사용: %s", e)

        # 3) 원문 그대로
        return [text]

    def _validate_chunk_tokens(self, chunk: str, chunk_index: int) -> str:
        """
        청크가 임베딩 모델 최대 토큰을 초과하는지 검증하고 경고 로깅
        """
        token_count = self.estimate_tokens(chunk)
        if token_count > self.max_embedding_tokens:
            logger.warning(
                "⚠️ 청크 #%d가 임베딩 모델 최대 토큰(%d)을 초과합니다: %d 토큰. "
                "임베딩 시 뒷부분이 잘릴 수 있습니다. 청크 앞부분: %s...",
                chunk_index,
                self.max_embedding_tokens,
                token_count,
                chunk[:100].replace('\n', ' ')
            )
        return chunk

    def _split_text(self, text: str, separator: str) -> List[str]:
        """Split text by separator"""
        if separator:
            return text.split(separator)
        # Character-level split for empty separator
        return list(text)

    def _merge_splits(
        self,
        splits: List[str],
        separator: str,
        chunk_size: int
    ) -> List[str]:
        """Merge splits into chunks of appropriate size"""
        chunks = []
        current_chunk = []
        current_size = 0

        for split in splits:
            split_size = self.estimate_tokens(split)

            # If single split is larger than chunk_size, need to recursively split
            if split_size > chunk_size:
                # First, save current chunk if any
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                    current_chunk = []
                    current_size = 0

                # Add large split as its own chunk(s)
                chunks.append(split)
                continue

            # Check if adding this split would exceed chunk_size
            potential_size = current_size + split_size
            if current_chunk:
                potential_size += self.estimate_tokens(separator)

            if potential_size <= chunk_size:
                current_chunk.append(split)
                current_size = potential_size
            else:
                # Save current chunk and start new one
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [split]
                current_size = split_size

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(separator.join(current_chunk))

        return chunks

    def _recursive_split(
        self,
        text: str,
        separators: List[str],
        chunk_size: int
    ) -> List[str]:
        """Recursively split text using separators in order"""
        if not text:
            return []

        # Base case: text fits in chunk
        if self.estimate_tokens(text) <= chunk_size:
            return [text]

        # Try each separator
        for i, separator in enumerate(separators):
            splits = self._split_text(text, separator)

            if len(splits) > 1:
                # Merge splits into appropriately sized chunks
                merged = self._merge_splits(splits, separator, chunk_size)

                # Check if any chunks are still too large
                final_chunks = []
                remaining_separators = separators[i + 1:]

                for chunk in merged:
                    if self.estimate_tokens(chunk) > chunk_size and remaining_separators:
                        # Recursively split with remaining separators
                        sub_chunks = self._recursive_split(
                            chunk, remaining_separators, chunk_size
                        )
                        final_chunks.extend(sub_chunks)
                    else:
                        final_chunks.append(chunk)

                return final_chunks

        # Last resort: just return the text as is
        return [text]

    def _add_overlap(self, chunks: List[str]) -> List[str]:
        """Add overlap between chunks"""
        if len(chunks) <= 1 or self.chunk_overlap <= 0:
            return chunks

        overlapped_chunks = []

        for i, chunk in enumerate(chunks):
            if i == 0:
                # First chunk - add text from next chunk at the end
                if i + 1 < len(chunks):
                    next_chunk = chunks[i + 1]
                    overlap_text = self._get_overlap_text(next_chunk, from_start=True)
                    # Don't add overlap to first chunk (it would duplicate at start of second)
                overlapped_chunks.append(chunk)
            else:
                # Get overlap from previous chunk
                prev_chunk = chunks[i - 1]
                overlap_text = self._get_overlap_text(prev_chunk, from_start=False)
                if overlap_text:
                    chunk = overlap_text + " " + chunk
                overlapped_chunks.append(chunk)

        return overlapped_chunks

    def _get_overlap_text(self, text: str, from_start: bool = True) -> str:
        """Get overlap text from start or end of text"""
        target_tokens = self.chunk_overlap

        if from_start:
            # Get first N tokens worth of text
            words = text.split()
            overlap_words = []
            current_tokens = 0

            for word in words:
                word_tokens = self.estimate_tokens(word)
                if current_tokens + word_tokens > target_tokens:
                    break
                overlap_words.append(word)
                current_tokens += word_tokens

            return " ".join(overlap_words)
        else:
            # Get last N tokens worth of text
            words = text.split()
            overlap_words = []
            current_tokens = 0

            for word in reversed(words):
                word_tokens = self.estimate_tokens(word)
                if current_tokens + word_tokens > target_tokens:
                    break
                overlap_words.insert(0, word)
                current_tokens += word_tokens

            return " ".join(overlap_words)

    def chunk_text(
        self,
        text: str,
        page_number: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[TextChunk]:
        """
        Split text into chunks

        Args:
            text: Input text to chunk
            page_number: Optional page number for the text
            metadata: Optional metadata to attach to chunks

        Returns:
            List of TextChunk objects
        """
        if not text or not text.strip():
            return []

        # Clean text
        text = text.strip()
        text = re.sub(r'\s+', ' ', text)  # Normalize whitespace

        # 한국어 문장 단위 분리 (kss 사용 시)
        if self.use_korean_sentence_split:
            sentences = self._split_korean_sentences(text)
            # 문장들을 청크 크기에 맞게 병합
            raw_chunks = self._merge_splits(sentences, " ", self.chunk_size)
        else:
            # Split into chunks
            raw_chunks = self._recursive_split(text, self.separators, self.chunk_size)

        # Filter out empty/small chunks
        raw_chunks = [c.strip() for c in raw_chunks if c.strip()]
        raw_chunks = [c for c in raw_chunks if self.estimate_tokens(c) >= self.min_chunk_size]

        # Add overlap
        overlapped_chunks = self._add_overlap(raw_chunks)

        # Create TextChunk objects with token validation
        result = []
        char_position = 0

        for i, chunk_text in enumerate(overlapped_chunks):
            # 토큰 초과 경고 검증
            self._validate_chunk_tokens(chunk_text, i)

            chunk = TextChunk(
                content=chunk_text,
                index=i,
                start_char=char_position,
                end_char=char_position + len(chunk_text),
                token_count=self.estimate_tokens(chunk_text),
                page_number=page_number,
                metadata=metadata.copy() if metadata else None
            )
            result.append(chunk)
            char_position += len(chunk_text)

        return result

    def chunk_pages(
        self,
        pages: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[TextChunk]:
        """
        Chunk multiple pages of text

        Args:
            pages: List of dicts with 'page_number' and 'content' keys
            metadata: Optional metadata to attach to all chunks

        Returns:
            List of TextChunk objects
        """
        all_chunks = []
        chunk_index = 0

        for page in pages:
            page_number = page.get('page_number')
            content = page.get('content', '')

            page_chunks = self.chunk_text(
                content,
                page_number=page_number,
                metadata=metadata
            )

            # Update indices to be global
            for chunk in page_chunks:
                chunk.index = chunk_index
                chunk_index += 1

            all_chunks.extend(page_chunks)

        return all_chunks

    def chunk_semantic_sections(
        self,
        structured_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[TextChunk]:
        """
        구조화된 의미 섹션 기준으로 청킹한다.

        - 기본 단위는 subsection
        - subsection 내부의 세부 항목이 있으면 메타에 포함
        - 길이가 길면 기존 chunk_text로 fallback 분할
        """
        all_chunks: List[TextChunk] = []
        chunk_index = 0
        base_meta = metadata.copy() if metadata else {}
        semantic_tags = {
            "structure_mode": structured_data.get("structure_mode", "semantic_sections"),
            "document_type": structured_data.get("document_type", ""),
            "section_group": structured_data.get("section_group", ""),
        }

        for top in structured_data.get("sections", []):
            top_section = str(top.get("section_name") or "")
            for subsection in top.get("subsections", []):
                section_id = str(subsection.get("section_id") or "")
                section_name = str(subsection.get("section_name") or "")
                content_items = [str(item).strip() for item in subsection.get("content_items") or [] if str(item).strip()]
                leaf_sections = subsection.get("subsections") or []
                leaf_titles = [str(item.get("title") or "").strip() for item in leaf_sections if str(item.get("title") or "").strip()]
                slide_numbers = subsection.get("slide_numbers") or []
                slide_range = subsection.get("slide_range") or []
                page_or_slide = slide_numbers[0] if len(slide_numbers) == 1 else None
                section_keywords = [str(item).strip() for item in subsection.get("keywords") or [] if str(item).strip()]

                header_lines = [f"{section_id} {section_name}".strip()]
                if top_section:
                    header_lines.insert(0, f"상위섹션: {top_section}")
                if leaf_titles:
                    header_lines.append("세부항목:")
                    header_lines.extend(f"- {title}" for title in leaf_titles)
                if content_items:
                    header_lines.append("핵심내용:")
                    header_lines.extend(f"- {item}" for item in content_items)
                semantic_text = "\n".join(line for line in header_lines if line).strip()
                if not semantic_text:
                    continue

                section_meta = {
                    **base_meta,
                    **semantic_tags,
                    "chunk_type": "semantic_section",
                    "top_section": top_section,
                    "section_id": section_id,
                    "section_name": section_name,
                    "section_title": section_name,
                    "section_heading": section_name,
                    "section_label": f"{top_section} > {section_name}" if top_section else section_name,
                    "subsection_titles": leaf_titles,
                    "keywords": section_keywords,
                    "slide_range": slide_range,
                    "slide_numbers": slide_numbers,
                    "slide_no": page_or_slide,
                    "page_no": page_or_slide,
                    "methodology": "WIM2" if any("WIM2" in value for value in [top_section, section_name, semantic_text]) else base_meta.get("methodology", ""),
                    "phase": section_name if section_name in {"프로젝트 준비", "환경분석", "현황분석", "목표모델 수립", "이행계획 수립", "통합 실행계획 수립"} else "",
                    "domain": "감사" if "감사" in semantic_text else base_meta.get("domain", ""),
                    "technology": "AI" if ("AI" in semantic_text or "인공지능" in semantic_text) else base_meta.get("technology", ""),
                }

                section_chunks = self.chunk_text(
                    semantic_text,
                    page_number=page_or_slide,
                    metadata=section_meta,
                )
                if not section_chunks:
                    section_chunks = [
                        TextChunk(
                            content=semantic_text,
                            index=chunk_index,
                            start_char=0,
                            end_char=len(semantic_text),
                            token_count=self.estimate_tokens(semantic_text),
                            page_number=page_or_slide,
                            metadata=section_meta,
                        )
                    ]
                for chunk in section_chunks:
                    chunk.index = chunk_index
                    chunk_index += 1
                all_chunks.extend(section_chunks)

        return all_chunks

    def chunk_document(
        self,
        text: str,
        document_id: int,
        document_name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[TextChunk]:
        """
        Chunk a full document with document metadata

        Args:
            text: Full document text
            document_id: Document ID
            document_name: Document filename
            metadata: Additional metadata

        Returns:
            List of TextChunk objects with document metadata
        """
        doc_metadata = {
            'document_id': document_id,
            'document_name': document_name,
            **(metadata or {})
        }

        return self.chunk_text(text, metadata=doc_metadata)


# Singleton instance with default settings (512 tokens, 50 overlap)
chunking_service = ChunkingService(
    chunk_size=512,
    chunk_overlap=50,
    min_chunk_size=50
)


def get_chunking_service() -> ChunkingService:
    """Dependency to get chunking service"""
    return chunking_service
