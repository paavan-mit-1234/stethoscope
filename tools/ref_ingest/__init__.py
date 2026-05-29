"""Stethoscope ingestion — Python reference implementation.

This package is a faithful, runnable mirror of the canonical Rust crates
(`crates/store`, `crates/ingestion`, `crates/cli`): same DuckDB schema (PRD
section 7), same OTel->Stethoscope mapping (section 7.4), same CLI surface.

It exists so the Phase 1 vertical slice runs *today* on a machine where the
Rust toolchain cannot be installed (no admin / no C++ compiler / AV-blocked
installers). When the Rust binaries are built, they drop in with no
behavioural change.

Import-side-effect note: ``server`` pulls in ``grpcio`` for the OTLP-gRPC
listener, but the cloud API uses OTLP-HTTP and never needs grpc. We expose
``serve`` as a lazy attribute via ``__getattr__`` so ``import
tools.ref_ingest`` succeeds even when grpcio isn't installed.
"""

from .store import Store, TraceRow

__all__ = ["serve", "Store", "TraceRow", "DEFAULT_OTLP_ADDR", "default_db_path"]


def __getattr__(name):
    # PEP 562: only loaded on first access — keeps grpcio out of the
    # required dep tree for HTTP-only consumers (cloud API, tests).
    if name in ("serve", "DEFAULT_OTLP_ADDR", "default_db_path"):
        from . import server
        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
