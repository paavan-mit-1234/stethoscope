"""Breakpoint predicate DSL — Python mirror of crates/breakpoint.

Used by the ingestion path to test enabled breakpoints against each span as
it lands (PRD 9.5 live hit detection). Same grammar/keywords as the Rust
canonical and the TS UI mirror.
"""

from __future__ import annotations

import re
from typing import Any

_OP_RE = re.compile(r"^(==|!=|>=|<=|>|<)")


def _lex(src: str) -> list[tuple[str, Any]]:
    toks: list[tuple[str, Any]] = []
    i = 0
    while i < len(src):
        c = src[i]
        if c.isspace():
            i += 1
        elif c == "(":
            toks.append(("(", None))
            i += 1
        elif c == ")":
            toks.append((")", None))
            i += 1
        elif c in "'\"":
            i += 1
            s = ""
            while i < len(src) and src[i] != c:
                s += src[i]
                i += 1
            if i >= len(src):
                raise ValueError("unterminated string")
            i += 1
            toks.append(("str", s))
        elif c in "=!<>":
            m = _OP_RE.match(src[i:])
            if not m:
                raise ValueError(f"bad operator at {i}")
            toks.append(("op", m.group(1)))
            i += len(m.group(1))
        else:
            j = i
            while j < len(src) and not src[j].isspace() and src[j] not in "()='\"!<>":
                j += 1
            w = src[i:j]
            i = j
            lw = w.lower()
            if lw == "and":
                toks.append(("and", None))
            elif lw == "or":
                toks.append(("or", None))
            elif lw == "not":
                toks.append(("not", None))
            elif lw == "contains":
                toks.append(("op", "contains"))
            elif lw == "true":
                toks.append(("bool", True))
            elif lw == "false":
                toks.append(("bool", False))
            else:
                try:
                    toks.append(("num", float(w)))
                except ValueError:
                    toks.append(("id", w))
    return toks


class _P:
    def __init__(self, t: list[tuple[str, Any]]):
        self.t = t
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def eat(self):
        tok = self.peek()
        self.i += 1
        return tok

    def or_(self):
        e = self.and_()
        while self.peek()[0] == "or":
            self.eat()
            e = ("or", e, self.and_())
        return e

    def and_(self):
        e = self.not_()
        while self.peek()[0] == "and":
            self.eat()
            e = ("and", e, self.not_())
        return e

    def not_(self):
        if self.peek()[0] == "not":
            self.eat()
            return ("not", self.not_())
        return self.primary()

    def primary(self):
        if self.peek()[0] == "(":
            self.eat()
            e = self.or_()
            if self.eat()[0] != ")":
                raise ValueError("expected )")
            return e
        f = self.eat()
        if f[0] != "id":
            raise ValueError("expected field name")
        o = self.eat()
        if o[0] != "op":
            raise ValueError("expected operator")
        v = self.eat()
        if v[0] not in ("str", "num", "bool"):
            raise ValueError("expected value")
        return ("cmp", f[1], o[1], v[1])


def parse(src: str):
    toks = _lex(src)
    if not toks:
        raise ValueError("empty predicate")
    p = _P(toks)
    e = p.or_()
    if p.i != len(p.t):
        raise ValueError("trailing tokens")
    return e


def _cmp(a: Any, op: str, b: Any) -> bool:
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == "contains":
        return isinstance(a, str) and isinstance(b, str) and b in a
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return False
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]


def evaluate(e, ctx: dict[str, Any]) -> bool:
    tag = e[0]
    if tag == "and":
        return evaluate(e[1], ctx) and evaluate(e[2], ctx)
    if tag == "or":
        return evaluate(e[1], ctx) or evaluate(e[2], ctx)
    if tag == "not":
        return not evaluate(e[1], ctx)
    # ("cmp", field, op, val)
    return _cmp(ctx.get(e[1]), e[2], e[3])
