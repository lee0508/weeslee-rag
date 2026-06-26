# 문서 내 검색어 위치 탐색 및 하이라이트 서비스
"""
Highlight Service
- 검색 결과에서 검색어가 등장하는 위치를 찾아 강조 표시
- 매칭 전략: exact → normalized → fuzzy

Usage:
    from app.services.highlight import find_highlights, Highlight

    highlights = find_highlights("스마트시티 플랫폼", document_text, max_hits=3)
    for hl in highlights:
        print(f"[{hl.match_type}] {hl.marked_snippet}")
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional


@dataclass
class Highlight:
    """문서 내에서 검색어와 매칭된 한 구간"""
    start: int                  # 매칭 시작 문자 위치
    end: int                    # 매칭 끝 문자 위치
    matched_text: str           # 실제 매칭된 원문 텍스트
    snippet: str                # 전후 문맥 포함 스니펫(plain)
    marked_snippet: str         # 매칭부를 «»로 강조한 스니펫
    score: float                # 매칭 신뢰도(0~1)
    match_type: str             # exact | normalized | fuzzy
    page: Optional[int] = None  # 페이지 번호 (있는 경우)


# 문장 분리 (한/영 종결부호 기준)
_SENT_SPLIT = re.compile(r"(?<=[.!?。!?])\s+|\n+")


def _make_snippet(text: str, start: int, end: int,
                  context: int = 60) -> tuple[str, str]:
    """
    매칭 구간 [start,end] 전후로 context 글자만큼 잘라 스니펫을 만든다.
    Returns:
        (plain_snippet, marked_snippet)  — marked는 «검색어» 형태로 강조
    """
    s = max(0, start - context)
    e = min(len(text), end + context)

    prefix = ("…" if s > 0 else "") + text[s:start]
    match = text[start:end]
    suffix = text[end:e] + ("…" if e < len(text) else "")

    plain = f"{prefix}{match}{suffix}"
    marked = f"{prefix}«{match}»{suffix}"
    # 스니펫 내 줄바꿈을 공백으로 정리(표시 편의)
    plain = re.sub(r"\s+", " ", plain).strip()
    marked = re.sub(r"\s+", " ", marked).strip()
    return plain, marked


def _normalize_ws(s: str) -> str:
    """공백 정규화 (연속 공백/줄바꿈 → 단일 공백)"""
    return re.sub(r"\s+", " ", s).strip()


def find_highlights(query: str, text: str,
                    max_hits: int = 3,
                    context: int = 60,
                    fuzzy_threshold: float = 0.6,
                    page: Optional[int] = None) -> List[Highlight]:
    """
    문서 텍스트에서 검색어 위치를 찾아 하이라이트 목록을 반환한다.

    Args:
        query           : 검색어/문구
        text            : 대상 문서 텍스트(청크 또는 정규화 전문)
        max_hits        : 최대 반환 개수
        context         : 스니펫 전후 문맥 글자 수
        fuzzy_threshold : 퍼지 매칭 최소 유사도
        page            : 페이지 번호 (하이라이트에 포함)
    Returns:
        Highlight 리스트 (score 내림차순)
    """
    if not query.strip() or not text.strip():
        return []

    # ---- 1) 정확 매칭 (대소문자 무시) ----
    hits = _exact_matches(query, text, context, max_hits, page)
    if hits:
        return hits[:max_hits]

    # ---- 2) 공백 정규화 매칭 ----
    hit = _normalized_match(query, text, context, page)
    if hit:
        return [hit]

    # ---- 3) 퍼지 매칭 (문장 단위) ----
    fuzzy_hits = _fuzzy_matches(query, text, context, fuzzy_threshold, max_hits, page)
    return fuzzy_hits[:max_hits]


def _exact_matches(query: str, text: str, context: int,
                   max_hits: int, page: Optional[int]) -> List[Highlight]:
    """검색어가 그대로 등장하는 모든 위치 (대소문자 무시)"""
    results = []
    low_text, low_q = text.lower(), query.lower()
    start = 0
    while len(results) < max_hits:
        idx = low_text.find(low_q, start)
        if idx == -1:
            break
        end = idx + len(query)
        plain, marked = _make_snippet(text, idx, end, context)
        results.append(Highlight(
            start=idx, end=end, matched_text=text[idx:end],
            snippet=plain, marked_snippet=marked,
            score=1.0, match_type="exact", page=page,
        ))
        start = end
    return results


def _normalized_match(query: str, text: str, context: int,
                      page: Optional[int]) -> Optional[Highlight]:
    """
    공백 차이를 무시한 매칭.
    - 검색어와 본문을 공백 정규화하여 위치를 찾고,
      원문 좌표로 환산해 스니펫 생성
    """
    norm_q = _normalize_ws(query).lower()
    if not norm_q:
        return None

    # 원문 각 문자 → 정규화 문자열에서의 위치 매핑 구축
    norm_chars = []      # 정규화된 문자
    orig_index = []      # 각 정규화 문자에 대응하는 원문 인덱스
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            norm_chars.append(" ")
            orig_index.append(i)
            prev_space = True
        else:
            norm_chars.append(ch.lower())
            orig_index.append(i)
            prev_space = False
    norm_text = "".join(norm_chars).strip()
    # strip으로 앞 공백 제거된 만큼 보정
    lead = len("".join(norm_chars)) - len("".join(norm_chars).lstrip())

    pos = norm_text.find(norm_q)
    if pos == -1:
        return None

    if pos + lead >= len(orig_index):
        return None
    real_start = orig_index[pos + lead]
    end_idx = min(pos + lead + len(norm_q) - 1, len(orig_index) - 1)
    real_end = orig_index[end_idx] + 1
    plain, marked = _make_snippet(text, real_start, real_end, context)
    return Highlight(
        start=real_start, end=real_end, matched_text=text[real_start:real_end],
        snippet=plain, marked_snippet=marked,
        score=0.9, match_type="normalized", page=page,
    )


def _fuzzy_matches(query: str, text: str, context: int,
                   threshold: float, max_hits: int,
                   page: Optional[int]) -> List[Highlight]:
    """
    문장 단위 퍼지 매칭 (토큰 포함률 기반).
    - 본문을 문장으로 분리하고, 검색어 토큰이 문장에 얼마나 포함되는지 측정
    - 한국어 조사 차이 대응: 문장 토큰이 검색 토큰을 '포함'하면 매칭으로 인정
      (예: 검색 '로드맵' ↔ 본문 '로드맵을' 매칭)
    - 점수 = 토큰 포함률(recall) 위주 + 시퀀스 유사도 보정
    """
    sentences = _split_sentences(text)
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    q_set = set(q_tokens)

    scored = []
    cursor = 0
    for sent in sentences:
        s_idx = text.find(sent, cursor)
        if s_idx == -1:
            s_idx = text.find(sent)
        cursor = s_idx + len(sent) if s_idx != -1 else cursor

        s_tokens = _tokenize(sent)
        if not s_tokens:
            continue

        # 검색 토큰이 문장 토큰에 포함되는지 (조사/어미 변형 대응)
        matched = 0
        for qt in q_set:
            for st in s_tokens:
                # 정확 일치 또는 부분 포함(접두/포함)
                if qt == st or st.startswith(qt) or qt in st:
                    matched += 1
                    break
        recall = matched / len(q_set)           # 검색어 토큰 포함률(핵심)
        seq = SequenceMatcher(None, query, sent).ratio()
        score = 0.8 * recall + 0.2 * seq         # 포함률 가중

        if score >= threshold and s_idx != -1:
            end = s_idx + len(sent)
            plain, marked = _make_snippet(text, s_idx, end, context)
            scored.append(Highlight(
                start=s_idx, end=end, matched_text=sent,
                snippet=plain, marked_snippet=marked,
                score=round(score, 3), match_type="fuzzy", page=page,
            ))

    scored.sort(key=lambda h: h.score, reverse=True)
    return scored


def _split_sentences(text: str) -> List[str]:
    """본문을 문장 단위로 분리"""
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def _tokenize(s: str) -> List[str]:
    """간단 토크나이저 (한글/영문/숫자 토큰 추출)"""
    return re.findall(r"[가-힣]+|[a-zA-Z]+|[0-9]+", s.lower())


# 편의 함수: 청크 리스트에서 하이라이트 추출
def highlight_in_chunks(query: str, chunks: List[dict],
                        max_per_chunk: int = 2) -> List[dict]:
    """
    여러 청크에서 검색어 하이라이트를 추출한다.

    Args:
        query: 검색어
        chunks: [{text, metadata: {page, chunk_index, ...}}, ...]
        max_per_chunk: 청크당 최대 하이라이트 수
    Returns:
        [{page, chunk_index, match_type, score, snippet, marked_snippet, char_offset}, ...]
    """
    results = []
    for chunk in chunks:
        text = chunk.get("text", "")
        meta = chunk.get("metadata", {})
        page = meta.get("page")
        chunk_index = meta.get("chunk_index")

        highlights = find_highlights(query, text, max_hits=max_per_chunk, page=page)
        for hl in highlights:
            results.append({
                "page": page,
                "chunk_index": chunk_index,
                "match_type": hl.match_type,
                "score": hl.score,
                "snippet": hl.snippet,
                "marked_snippet": hl.marked_snippet,
                "char_offset": [hl.start, hl.end],
            })

    # 점수순 정렬
    results.sort(key=lambda x: x["score"], reverse=True)
    return results
