"""Stethoscope replay engine — Python reference (PRD 3.2, 4.4, 7.3).

Reconstructs a deterministic replay manifest from a stored trace, applies one
mutation, and re-runs the agent in a subprocess (the PRD's sanctioned venv
runtime fallback; Docker is the spec'd primary). The re-run exports a fresh
trace over OTLP tagged as a branch of the source.

Canonical contract lives in crates/replay (uncompiled here).
"""

from .engine import branch

__all__ = ["branch"]
