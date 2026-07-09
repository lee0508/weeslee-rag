# -*- coding: utf-8 -*-
"""wiki_slug.py — Wiki slug 단일 규칙 모듈

생성기(build_project_wiki.py)와 조회기(wiki.py)가 동일 규칙을 공유한다.
규칙: 조회용 정규식 ^[a-z0-9][a-z0-9\-]{0,79}$ 을 '항상' 통과하는 slug 생성.
한글 원문 이름은 손실 없이 index.json의 project_name 필드에 보관한다.

[2026-07-08] 작업지시서에 따라 신규 생성
"""
import re
import hashlib

# 조회기(wiki.py)의 _SLUG_RE와 반드시 동일하게 유지할 것
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,79}$")


def make_wiki_slug(name: str, existing: set[str] | None = None) -> str:
    """한글 포함 이름을 URL-safe ASCII slug로 변환한다.

    1) 영문/숫자 토큰 추출: "202212. k-water 데이터허브" → "202212-k-water"
    2) 원문 md5 앞 8자리를 붙여 한글 부분의 고유성 보장
    3) existing 집합으로 같은 빌드 내 충돌 방지
    """
    tokens = re.findall(r"[a-zA-Z0-9]+", name.lower())
    base = "-".join(tokens)[:40].strip("-")
    h = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    slug = f"{base}-{h}" if base else f"w-{h}"

    if existing is not None:
        n, final = 2, slug
        while final in existing:
            final = f"{slug}-{n}"
            n += 1
        existing.add(final)
        slug = final

    # 개발 중 즉시 검출용 assertion (production에서는 assert가 비활성화될 수 있음)
    if not SLUG_RE.match(slug):
        raise ValueError(f"slug 규칙 위반: {slug}")
    return slug


def normalize_doc_ids(values) -> list[int]:
    """"DOC-000123" 같은 레거시 문자열 ID와 정수 ID를 모두 정수로 변환한다.

    wiki_search.py에서 document_ids 필드가 List[int]로 선언되어 있으므로,
    레거시 문자열 ID가 남아 있어도 검색이 죽지 않도록 방어한다.
    """
    result = []
    for v in values or []:
        m = re.search(r"(\d+)$", str(v))
        if m:
            result.append(int(m.group(1)))
    return result
