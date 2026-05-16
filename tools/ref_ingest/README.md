# ref_ingest — Python reference ingestion

> **Why this exists:** the canonical ingestion/store/CLI are the Rust crates
> in `crates/`. This package is a faithful, runnable mirror so the Phase 1
> vertical slice works *today* on a locked-down Windows box where the Rust
> toolchain can't be installed (no admin, no C/C++ compiler, no package
> manager, AV blocks the rustup installer — see `docs/windows-build.md`).
>
> Same DuckDB schema (PRD §7), same OTel→Stethoscope mapping (§7.4), same CLI
> surface as the Rust binaries. When the Rust toolchain is available,
> `stethoscope-ingestion` + `stethoscope-cli` replace this with no
> behavioural change.

## Run the vertical slice

```
pip install duckdb grpcio opentelemetry-proto
pip install -e packages/sdk-python

# terminal 1 — ingestion endpoint (OTLP/gRPC on :4317)
python -m tools.ref_ingest serve --db .stethoscope/dev/traces.db

# terminal 2 — run the instrumented example agent
python examples/min_agent/agent.py

# then: list captured traces (Phase 1 milestone)
python -m tools.ref_ingest list-traces --db .stethoscope/dev/traces.db
```

Or run the one-shot smoke test: `python scripts/smoke.py`.

## Parity map

| Rust (canonical)              | Python (this reference) |
|-------------------------------|-------------------------|
| `crates/store/src/schema.rs`  | `schema.py`             |
| `crates/store/src/lib.rs`     | `store.py`              |
| `crates/ingestion/src/otel.rs`| `mapper.py` (helpers)   |
| `crates/ingestion/src/mapper.rs` | `mapper.py`          |
| `crates/ingestion/src/service.rs`| `server.py`          |
| `crates/cli/src/main.rs`      | `cli.py`                |
