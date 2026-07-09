# -*- coding: utf-8 -*-
"""
Late chunking helpers adapted for the current Dataset Builder pipeline.

This module keeps the QA15 design goal, but exposes a practical API for the
existing Step 5/6 flow:

- Step 5 still produces normal chunks.
- Step 6 can embed the full normalized document once, then pool token ranges
  that correspond to existing chunks.
- If token-span reconstruction is unreliable or the model runtime is missing,
  callers should fall back to the standard chunk embedding path.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from app.services.chunking import TextChunk

logger = logging.getLogger(__name__)


def normalize_text_for_matching(text: str) -> str:
    """Match ChunkingService text normalization for stable span reconstruction."""
    clean = str(text or "").strip()
    if not clean:
        return ""
    return re.sub(r"\s+", " ", clean)


@dataclass
class LateChunkVector:
    chunk_index: int
    start_char: int
    end_char: int
    start_token: int
    end_token: int
    embedding: List[float]


class LateChunkingEmbedder:
    """Full-document token embedding + chunk-span pooling."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: Optional[str] = None,
        model_max_length: int = 8192,
        macro_overlap_tokens: int = 128,
        normalize: bool = True,
    ):
        self.model_name = model_name
        self.model_max_length = model_max_length
        self.macro_overlap_tokens = macro_overlap_tokens
        self.normalize = normalize
        self._device = device
        self._tokenizer = None
        self._model = None

    def _ensure_loaded(self):
        if self._model is not None:
            return

        import torch
        from transformers import AutoModel, AutoTokenizer

        if self._device is None:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModel.from_pretrained(self.model_name)
        self._model.to(self._device)
        self._model.eval()
        logger.info("LateChunking model loaded: %s (%s)", self.model_name, self._device)

    def _encode_document_tokens(self, text: str):
        import torch

        self._ensure_loaded()
        tok = self._tokenizer
        encoded = tok(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        input_ids: List[int] = encoded["input_ids"]
        offsets: List[Tuple[int, int]] = encoded["offset_mapping"]
        n_tokens = len(input_ids)
        if n_tokens == 0:
            return torch.empty((0, self._model.config.hidden_size)), []

        hidden = self._model.config.hidden_size
        acc = torch.zeros((n_tokens, hidden), dtype=torch.float32)
        cnt = torch.zeros((n_tokens, 1), dtype=torch.float32)

        win = self.model_max_length - 2
        step = max(1, win - self.macro_overlap_tokens)
        cls_id = tok.cls_token_id
        sep_id = tok.sep_token_id

        start = 0
        while start < n_tokens:
            end = min(start + win, n_tokens)
            window_ids = input_ids[start:end]
            ids = [cls_id] + window_ids + [sep_id] if cls_id is not None else window_ids
            ids_tensor = torch.tensor([ids], device=self._device)
            attn = torch.ones_like(ids_tensor)
            with torch.no_grad():
                out = self._model(input_ids=ids_tensor, attention_mask=attn)
            hs = out.last_hidden_state[0].to("cpu", dtype=torch.float32)
            offset_head = 1 if cls_id is not None else 0
            body = hs[offset_head:offset_head + (end - start)]
            acc[start:end] += body
            cnt[start:end] += 1.0
            if end >= n_tokens:
                break
            start += step

        token_embeddings = acc / cnt.clamp(min=1.0)
        return token_embeddings, offsets

    def _char_range_to_token_span(
        self,
        offsets: Sequence[Tuple[int, int]],
        start_char: int,
        end_char: int,
    ) -> Tuple[int, int]:
        start_token = None
        end_token = None
        for idx, (tok_start, tok_end) in enumerate(offsets):
            if start_token is None and tok_end > start_char:
                start_token = idx
            if tok_start < end_char:
                end_token = idx + 1
            if tok_start >= end_char and start_token is not None:
                break
        if start_token is None:
            start_token = 0
        if end_token is None:
            end_token = len(offsets)
        return start_token, max(start_token + 1, end_token)

    def locate_chunk_ranges(self, text: str, chunks: Sequence[TextChunk]) -> List[Tuple[int, int]]:
        """
        Rebuild chunk character spans from the normalized full text.

        Existing chunks may include overlap, so the search window allows a small
        backwards look from the current cursor.
        """
        normalized = normalize_text_for_matching(text)
        ranges: List[Tuple[int, int]] = []
        cursor = 0
        for chunk in chunks:
            content = normalize_text_for_matching(chunk.content)
            if not content:
                ranges.append((cursor, cursor))
                continue

            search_start = max(0, cursor - 2000)
            found_at = normalized.find(content, search_start)
            if found_at < 0:
                found_at = normalized.find(content)
            if found_at < 0:
                raise ValueError(f"Late chunk span reconstruction failed for chunk {chunk.index}")

            start_char = found_at
            end_char = found_at + len(content)
            ranges.append((start_char, end_char))
            cursor = max(cursor, end_char)
        return ranges

    def embed_query(self, text: str) -> List[float]:
        import torch

        normalized = normalize_text_for_matching(text)
        token_embeddings, _ = self._encode_document_tokens(normalized)
        if token_embeddings.shape[0] == 0:
            return []
        pooled = token_embeddings.mean(dim=0)
        if self.normalize:
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=0)
        return pooled.tolist()

    def embed_existing_chunks(
        self,
        text: str,
        chunks: Sequence[TextChunk],
        contextual_texts: Optional[Sequence[Optional[str]]] = None,
        contextual_weight: float = 0.35,
    ) -> List[LateChunkVector]:
        """
        Pool chunk vectors from one full-document encoding.

        If contextual_texts are supplied, combine the late chunk vector with an
        extra single-text embedding generated from the same model.
        """
        import torch

        normalized = normalize_text_for_matching(text)
        token_embeddings, offsets = self._encode_document_tokens(normalized)
        if token_embeddings.shape[0] == 0:
            return []

        char_ranges = self.locate_chunk_ranges(normalized, chunks)
        results: List[LateChunkVector] = []

        for idx, chunk in enumerate(chunks):
            start_char, end_char = char_ranges[idx]
            start_token, end_token = self._char_range_to_token_span(offsets, start_char, end_char)
            pooled = token_embeddings[start_token:end_token].mean(dim=0)

            contextual_text = None
            if contextual_texts and idx < len(contextual_texts):
                contextual_text = (contextual_texts[idx] or "").strip()
            if contextual_text:
                contextual_vec = self.embed_query(contextual_text)
                if contextual_vec:
                    ctx_tensor = torch.tensor(contextual_vec, dtype=pooled.dtype)
                    pooled = ((1.0 - contextual_weight) * pooled) + (contextual_weight * ctx_tensor)

            if self.normalize:
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=0)

            results.append(
                LateChunkVector(
                    chunk_index=chunk.index,
                    start_char=start_char,
                    end_char=end_char,
                    start_token=start_token,
                    end_token=end_token,
                    embedding=pooled.tolist(),
                )
            )
        return results


def supports_late_chunking(model_name: str) -> bool:
    """Return True for models we intentionally map to HF late-chunking flow."""
    name = str(model_name or "").strip().lower()
    return "bge-m3" in name or name == "baai/bge-m3"


def resolve_late_chunk_model_name(model_name: str) -> str:
    """Map runtime model names to the HF identifier used by transformers."""
    if supports_late_chunking(model_name):
        return "BAAI/bge-m3"
    return model_name
