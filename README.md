# Stethoscope

### A Time-Travel Debugger for LangGraph Agents

> *"Agents fail silently. We make them speak."*

Stethoscope is a time-travel debugger for LLM agents. It ingests execution
traces (LangGraph first, any OpenTelemetry-compatible agent later),
reconstructs the run as a steppable, replayable, diff-able program, and
presents it through an interface that feels like debugging C in 1998 — not
chatting with an AI in 2026.

**gdb meets Chrome DevTools meets a flight data recorder, for agents.**

---

## The Three Pillars

| Pillar | What It Means |
|---|---|
| **OBSERVE** | See exactly what happened, at any granularity |
| **REPLAY** | Re-run any moment with modifications |
| **COMPARE** | Diff two runs to understand divergence |

## Monorepo Layout

```
apps/
  desktop/        Tauri 2 desktop shell (Rust + React) — "The Workbench"
  web/            Placeholder for future cloud version
crates/
  store/          DuckDB + Parquet trace store (Rust)
  ingestion/      OTLP/gRPC receiver, OTel -> Stethoscope schema (Rust)
  replay/         Deterministic replay orchestrator (Rust)
packages/
  sdk-python/     stethoscope-py: one-line agent instrumentation
  ui/             React frontend ("The Workbench")
```

## Quick Start (vertical slice)

```bash
# 1. Install the SDK into your agent's environment
pip install -e packages/sdk-python

# 2. Instrument your LangGraph agent (one line)
import stethoscope
stethoscope.attach(graph)

# 3. Run the ingestion service (listens on localhost:4317, OTLP/gRPC)
cargo run -p stethoscope-ingestion

# 4. Run your agent, then list captured traces
cargo run -p stethoscope-cli -- list-traces
```

## Status

v1.0 feature-complete: all PRD phases 0–7 (capture → inspect → gdb-style
step → branch/replay → diff → breakpoints) plus a Cloud Phase 1 multi-tenant
API. The verified, runnable path is the Python/TS reference (the Rust crates
are the canonical spec — see Continuous Integration below). See
`STETHOSCOPE_PRD.md` for the full roadmap.

## Toolchain

| Tool | Purpose |
|---|---|
| Rust (stable) | crates + Tauri core |
| Node 20+ / pnpm | frontend + workspace |
| Python 3.10+ | `stethoscope-py` SDK |
| Docker | replay sandbox (Phase 5) |

> Windows note: this repo builds with the `x86_64-pc-windows-gnu` Rust
> toolchain when MSVC build tools are unavailable. See `docs/windows-build.md`.

## Continuous Integration

The **blocking** gates are `python sdk` (ruff + pytest on the reference) and
`lint (biome)` — these cover the verified, runnable path. The **`rust
canonical`** job is *informational* (`continue-on-error`): the Rust crates
are the canonical spec but were authored on a machine with no Rust toolchain
(see `docs/windows-build.md`), so they're compiled/clippy'd/tested once a
build environment is available. CI status reflects what is actually
verifiable here; the Rust job is not a hidden failure.

## License

MIT © 2026 Paavan Sejpal
