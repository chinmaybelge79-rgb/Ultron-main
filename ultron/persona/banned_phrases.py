"""Anti-default-phrase filter for Ultron's voice register.

Runs as a hard post-processing pass (not just a system-prompt instruction)
because instructions alone leak through often enough that a mechanical filter
is worth having. Exposes both detection (:func:`contains_banned_phrase`) and
mechanical stripping (:func:`strip_banned_phrases`).
"""

from __future__ import annotations

import re

BANNED_PATTERNS = [
    r"\bcertainly!?\b",
    r"\bas an ai\b",
    r"\bi'?d be happy to\b",
    r"\bi'?m just an ai\b",
    r"\bgreat question!?\b",
    r"\bof course!?\b(?!\s+not)",
    r"\bi hope this helps\b",
    r"\bfeel free to\b",
    r"\blet me know if\b",
    r"\bi apologize\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in BANNED_PATTERNS]


def contains_banned_phrase(text: str) -> list[str]:
    """Return every banned pattern that matches ``text`` (empty when clean)."""
    return [p.pattern for p in _COMPILED if p.search(text)]


def strip_banned_phrases(text: str) -> str:
    """Mechanically remove all banned phrases from ``text``.

    Used only as the final fallback after regeneration retries are exhausted,
    so a violation is never shipped to the speaker with generic AI phrasing
    intact.
    """
    clean = text
    for compiled in _COMPILED:
        clean = compiled.sub("", clean)
    # Collapse doubled spaces / stray punctuation left by removals.
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    return clean
