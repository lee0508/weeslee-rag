# -*- coding: utf-8 -*-
"""
Text Chunking Service for RAG preprocessing
Splits documents into optimal chunks for embedding and retrieval
"""
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


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

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        min_chunk_size: int = 100,
        separators: Optional[List[str]] = None
    ):
        """
        Initialize chunking service

        Args:
            chunk_size: Target chunk size in tokens
            chunk_overlap: Number of overlapping tokens between chunks
            min_chunk_size: Minimum chunk size (smaller chunks are merged)
            separators: List of separators for splitting (in priority order)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
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
        # Count other characters (English, numbers, symbols)
        other_chars = len(text) - korean_chars

        # Estimate tokens
        korean_tokens = korean_chars / self.KOREAN_CHARS_PER_TOKEN
        # For non-Korean, count words approximately
        other_text = re.sub(r'[가-힣]', '', text)
        other_tokens = len(other_text.split()) * self.ENGLISH_WORDS_PER_TOKEN

        return int(korean_tokens + other_tokens)

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

        # Split into chunks
        raw_chunks = self._recursive_split(text, self.separators, self.chunk_size)

        # Filter out empty/small chunks
        raw_chunks = [c.strip() for c in raw_chunks if c.strip()]
        raw_chunks = [c for c in raw_chunks if self.estimate_tokens(c) >= self.min_chunk_size]

        # Add overlap
        overlapped_chunks = self._add_overlap(raw_chunks)

        # Create TextChunk objects
        result = []
        char_position = 0

        for i, chunk_text in enumerate(overlapped_chunks):
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
