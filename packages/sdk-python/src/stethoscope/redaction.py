"""Regex-based redaction, enforced at the SDK level (PRD section 5.3).

Data never leaves the agent process unredacted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_REPLACEMENT = "[REDACTED]"


class Redactor:
    def __init__(self, patterns: Iterable[str]):
        self._regexes = [re.compile(p) for p in patterns]

    def __call__(self, text: str | None) -> str | None:
        if text is None or not self._regexes:
            return text
        out = text
        for rx in self._regexes:
            out = rx.sub(_REPLACEMENT, out)
        return out
