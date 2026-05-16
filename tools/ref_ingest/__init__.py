"""Stethoscope ingestion — Python reference implementation.

This package is a faithful, runnable mirror of the canonical Rust crates
(`crates/store`, `crates/ingestion`, `crates/cli`): same DuckDB schema (PRD
section 7), same OTel->Stethoscope mapping (section 7.4), same CLI surface.

It exists so the Phase 1 vertical slice runs *today* on a machine where the
Rust toolchain cannot be installed (no admin / no C++ compiler / AV-blocked
installers). When the Rust binaries are built, they drop in with no
behavioural change.
"""

from .server import DEFAULT_OTLP_ADDR, default_db_path, serve
from .store import Store, TraceRow

__all__ = ["serve", "Store", "TraceRow", "DEFAULT_OTLP_ADDR", "default_db_path"]
