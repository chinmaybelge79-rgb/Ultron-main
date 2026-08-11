"""Persona engine: gives every Ultron reply a consistent, dry, commanding
register and mechanically prevents generic AI-assistant phrasing from ever
reaching ``voice/speaker.py``.

Modules:
    style_rules: persona traits and the system-prompt addendum.
    banned_phrases: the anti-default-phrase filter (detect + strip).
    engine: PersonaEngine that enforces (regenerates) rather than only detects.
"""

from ultron.persona.banned_phrases import contains_banned_phrase, strip_banned_phrases
from ultron.persona.engine import PersonaEngine
from ultron.persona.style_rules import PERSONA_TRAITS, SYSTEM_PROMPT_ADDENDUM

__all__ = [
    "PERSONA_TRAITS",
    "SYSTEM_PROMPT_ADDENDUM",
    "PersonaEngine",
    "contains_banned_phrase",
    "strip_banned_phrases",
]
