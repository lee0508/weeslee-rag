# Kiwi 형태소 분석 기반 한국어 키워드 추출 모듈
"""
Korean Tokenizer

한국어는 교착어이므로 공백 분리로는 `계약일로부터` 같은 어절이 통째로 잡혀
`계약일로부`처럼 잘린 파편이 키워드가 된다. Kiwi 형태소 분석으로
의미 있는 품사(명사·고유명사·영문)만 추출해 키워드 품질을 높인다.

- Kiwi 인스턴스는 지연 로딩 싱글턴 (모델 로드 비용 1회)
- kiwipiepy 미설치/로드 실패 시 빈 리스트 반환 → 호출부가 기존 방식으로 폴백
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)

_KIWI = None
_KIWI_FAILED = False

# 키워드로 채택할 품사: 일반명사, 고유명사, 외국어(영문), 한자
_KEYWORD_POS = {"NNG", "NNP", "SL", "SH"}
# 복합명사를 이루는 품사 (연속 시 하나로 결합)
_NOUN_POS = {"NNG", "NNP", "SL", "SH", "SN"}
# 복합명사 최대 길이 (초과 시 개별 명사만 사용)
_MAX_COMPOUND_LEN = 12


def _get_kiwi():
    """Kiwi 싱글턴 반환. 미설치/실패 시 None."""
    global _KIWI, _KIWI_FAILED
    if _KIWI is not None:
        return _KIWI
    if _KIWI_FAILED:
        return None
    try:
        from kiwipiepy import Kiwi

        _KIWI = Kiwi()
        logger.info("Kiwi 형태소 분석기 로드 완료")
        return _KIWI
    except Exception as e:  # noqa: BLE001
        logger.warning("Kiwi 형태소 분석기 로드 실패, 규칙 기반 폴백 사용: %s", e)
        _KIWI_FAILED = True
        return None


def is_available() -> bool:
    """Kiwi 사용 가능 여부."""
    return _get_kiwi() is not None


def extract_keywords(text: str, min_len: int = 2, max_tokens: int = 200) -> List[str]:
    """
    Kiwi로 의미 있는 명사/복합명사/영문 키워드를 추출한다.

    - 개별 명사(NNG/NNP)와 영문(SL) 형태소
    - 연속한 명사는 복합명사로 결합 (예: 축산 + 유통 → 축산유통)
    - Kiwi 미설치 시 빈 리스트 반환 (호출부 폴백)
    """
    kiwi = _get_kiwi()
    if kiwi is None or not text or not text.strip():
        return []

    try:
        tokens = kiwi.tokenize(text)
    except Exception as e:  # noqa: BLE001
        logger.debug("Kiwi tokenize 실패: %s", e)
        return []

    results: List[str] = []
    compound: List[str] = []

    def flush_compound() -> None:
        # 연속 명사가 정확히 2개일 때만 복합어로 채택한다.
        # 3개 이상 무한 결합은 `AI기반빅데이터플랫폼구축` 같은 거대 단어를 만들어
        # 오히려 노이즈가 되므로 개별 명사만 남긴다.
        if len(compound) == 2:
            merged = "".join(compound)
            if len(merged) <= _MAX_COMPOUND_LEN:
                results.append(merged)

    for token in tokens:
        form = token.form
        tag = token.tag

        # 복합명사 누적
        if tag in _NOUN_POS:
            compound.append(form)
        else:
            flush_compound()
            compound = []

        # 개별 의미 형태소
        if tag in _KEYWORD_POS and len(form) >= min_len:
            results.append(form)

    flush_compound()

    # 순서 보존 중복 제거
    seen: set[str] = set()
    unique: List[str] = []
    for kw in results:
        if kw in seen:
            continue
        seen.add(kw)
        unique.append(kw)
        if len(unique) >= max_tokens:
            break
    return unique
