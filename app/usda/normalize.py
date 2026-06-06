from __future__ import annotations

import re
import unicodedata


_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def normalize_search_text(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return _NON_WORD_RE.sub(" ", ascii_value).strip()
