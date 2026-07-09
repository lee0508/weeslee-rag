# -*- coding: utf-8 -*-
"""
Contextual retrieval helpers adapted from QA15.

The gate is deterministic, so the baseline stays reproducible even when the
context generation model changes later.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol, Tuple

from app.services.chunking import TextChunk

logger = logging.getLogger(__name__)


@dataclass
class EnrichedChunk:
    original: TextChunk
    is_meaningful: bool
    gate_reason: str
    context: str = ""
    embed_text: str = ""


class MeaningfulnessGate:
    _TOC_LEADER = re.compile(r"\.{4,}\s*\d+")
    _PAGE_MARKER = re.compile(r"^[\-\sp\.]*\d{1,4}\s*(페이지|쪽|page)?[\-\s]*$", re.IGNORECASE)
    _LETTER = re.compile(r"[가-힣A-Za-z]")

    def __init__(
        self,
        min_letters: int = 10,
        min_letter_ratio: float = 0.30,
        min_unique_char_ratio: float = 0.15,
        max_toc_leader_hits: int = 2,
    ):
        self.min_letters = min_letters
        self.min_letter_ratio = min_letter_ratio
        self.min_unique_char_ratio = min_unique_char_ratio
        self.max_toc_leader_hits = max_toc_leader_hits

    def is_meaningful(self, chunk: TextChunk) -> Tuple[bool, str]:
        text = (chunk.content or "").strip()
        if not text:
            return False, "empty"
        if self._PAGE_MARKER.match(text):
            return False, "page_marker"
        if len(self._TOC_LEADER.findall(text)) >= self.max_toc_leader_hits:
            return False, "toc_leader"

        letters = self._LETTER.findall(text)
        if len(letters) < self.min_letters:
            return False, f"too_few_letters({len(letters)})"

        total = len(text)
        letter_ratio = len(letters) / total if total else 0.0
        if letter_ratio < self.min_letter_ratio:
            return False, f"low_letter_ratio({letter_ratio:.2f})"

        unique_ratio = len(set(text)) / total if total else 0.0
        if unique_ratio < self.min_unique_char_ratio:
            return False, f"low_unique_ratio({unique_ratio:.2f})"

        return True, "ok"


class ContextLLM(Protocol):
    def generate(self, full_document: str, chunk_text: str) -> str:
        ...


class OllamaContextLLM:
    """Ollama-based context generator for on-prem contextual retrieval."""

    def __init__(self, model: str, host: str, max_document_chars: int = 6000):
        self.model = model
        self.host = host.rstrip("/")
        self.max_document_chars = max_document_chars

    def generate(self, full_document: str, chunk_text: str) -> str:
        import httpx

        doc_head = str(full_document or "")[: self.max_document_chars]
        prompt = (
            f"<document>\n{doc_head}\n</document>\n\n"
            f"<chunk>\n{chunk_text}\n</chunk>\n\n"
            "위 청크가 문서 전체에서 어떤 맥락에 위치하는지 1~2문장으로만 간결하게 설명하세요."
        )
        resp = httpx.post(
            f"{self.host}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=180.0,
        )
        resp.raise_for_status()
        return str(resp.json().get("response") or "").strip()


class ContextualEnricher:
    def __init__(
        self,
        gate: Optional[MeaningfulnessGate] = None,
        context_llm: Optional[ContextLLM] = None,
        drop_meaningless: bool = False,
        context_separator: str = "\n\n",
    ):
        self.gate = gate or MeaningfulnessGate()
        self.context_llm = context_llm
        self.drop_meaningless = drop_meaningless
        self.sep = context_separator

    def enrich(
        self,
        full_document: str,
        chunks: List[TextChunk],
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> List[EnrichedChunk]:
        results: List[EnrichedChunk] = []
        total = len(chunks)
        llm_calls = 0

        for i, chunk in enumerate(chunks):
            meaningful, reason = self.gate.is_meaningful(chunk)
            if not meaningful:
                if self.drop_meaningless:
                    if progress_cb:
                        progress_cb(i + 1, total)
                    continue
                results.append(
                    EnrichedChunk(
                        original=chunk,
                        is_meaningful=False,
                        gate_reason=reason,
                        context="",
                        embed_text=chunk.content,
                    )
                )
                if progress_cb:
                    progress_cb(i + 1, total)
                continue

            context = ""
            if self.context_llm is not None:
                try:
                    context = self.context_llm.generate(full_document, chunk.content)
                    llm_calls += 1
                except Exception as exc:
                    logger.warning("Context generation failed for chunk %s: %s", chunk.index, exc)
                    context = ""

            embed_text = f"{context}{self.sep}{chunk.content}" if context else chunk.content
            results.append(
                EnrichedChunk(
                    original=chunk,
                    is_meaningful=True,
                    gate_reason=reason,
                    context=context,
                    embed_text=embed_text,
                )
            )
            if progress_cb:
                progress_cb(i + 1, total)

        logger.info(
            "ContextualEnricher processed %d chunks, LLM calls=%d, skipped=%d",
            total,
            llm_calls,
            total - llm_calls,
        )
        return results
