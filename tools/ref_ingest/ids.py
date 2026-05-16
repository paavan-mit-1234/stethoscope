"""Minimal, dependency-free ULID (Crockford base32, 48-bit ms time + 80-bit
random). Lexicographically sortable, like the Rust `ulid` crate."""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def ulid() -> str:
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    return _encode(ms, 10) + _encode(rand, 16)
