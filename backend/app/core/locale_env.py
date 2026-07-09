from __future__ import annotations

import logging
import os
import subprocess
from functools import lru_cache
from typing import Mapping


logger = logging.getLogger(__name__)

_UTF8_LOCALE_CANDIDATES = (
    "ko_KR.UTF-8",
    "ko_KR.utf8",
    "C.UTF-8",
    "C.utf8",
    "en_US.UTF-8",
    "en_US.utf8",
)


def _is_valid_locale_value(value: str) -> bool:
    normalized = str(value or "").strip()
    return bool(normalized) and ":" not in normalized


@lru_cache(maxsize=1)
def _available_locales() -> set[str]:
    try:
        proc = subprocess.run(
            ["locale", "-a"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return set()

    locales: set[str] = set()
    for line in proc.stdout.splitlines():
        normalized = line.strip()
        if normalized:
            locales.add(normalized)
            locales.add(normalized.lower())
    return locales


@lru_cache(maxsize=2)
def detect_utf8_locale(prefer_korean: bool = True) -> str:
    available = _available_locales()
    if prefer_korean:
        candidates = _UTF8_LOCALE_CANDIDATES
    else:
        candidates = tuple(
            candidate for candidate in _UTF8_LOCALE_CANDIDATES
            if not candidate.lower().startswith("ko_kr")
        ) + tuple(
            candidate for candidate in _UTF8_LOCALE_CANDIDATES
            if candidate.lower().startswith("ko_kr")
        )

    for candidate in candidates:
        if candidate in available or candidate.lower() in available:
            return candidate
    return "C.UTF-8"


def build_utf8_locale_env(
    base_env: Mapping[str, str] | None = None,
    *,
    prefer_korean: bool = True,
) -> dict[str, str]:
    env = dict(base_env if base_env is not None else os.environ)
    locale_value = detect_utf8_locale(prefer_korean=prefer_korean)

    env["LANG"] = locale_value
    env["LC_ALL"] = locale_value
    env["LC_CTYPE"] = locale_value
    if prefer_korean and locale_value.lower().startswith("ko_kr"):
        env["LANGUAGE"] = "ko_KR:ko:en_US:en"
    else:
        env["LANGUAGE"] = "en_US:en"
    return env


def normalize_process_locale_env(*, prefer_korean: bool = True) -> str:
    current_lang = str(os.environ.get("LANG") or "").strip()
    current_lc_all = str(os.environ.get("LC_ALL") or "").strip()
    if _is_valid_locale_value(current_lang) and (not current_lc_all or _is_valid_locale_value(current_lc_all)):
        return current_lang or current_lc_all

    normalized = build_utf8_locale_env(prefer_korean=prefer_korean)
    changed: dict[str, str] = {}
    for key in ("LANG", "LC_ALL", "LC_CTYPE", "LANGUAGE"):
        next_value = normalized.get(key, "")
        if os.environ.get(key) != next_value:
            os.environ[key] = next_value
            changed[key] = next_value

    if changed:
        logger.warning("Normalized locale environment for UTF-8 font rendering: %s", changed)
    return os.environ.get("LANG", "")
