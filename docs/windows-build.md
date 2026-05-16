# Building on Windows

The PRD targets macOS/Linux first; Windows is best-effort (PRD sections 5.4,
11). This repo was bootstrapped on a Windows box **without** MSVC build tools
and **without** admin rights, so it uses the GNU Rust toolchain plus a
portable MinGW-w64.

## Toolchain (no admin required)

1. **Portable MinGW-w64** (WinLibs UCRT build) — extracted to
   `./.toolchain/mingw64`, its `bin/` added to `PATH` for the session. No
   installer, no admin.
2. **rustup**, GNU host:
   ```
   rustup-init.exe -y --default-host x86_64-pc-windows-gnu --default-toolchain stable
   ```
3. **protoc**: not required — `tonic`/`prost` build via the bundled
   `protoc` from `protoc-bin-vendored` when needed; the OTLP types come
   prebuilt from the `opentelemetry-proto` crate (`gen-tonic`), so no
   `build.rs` protobuf compilation is performed here.

## DuckDB

`stethoscope-store` links DuckDB. Two modes:

- **`bundled` feature** — compiles DuckDB's C++ amalgamation. Correct but
  heavy; needs a C++ compiler (the portable MinGW `g++`). Used in CI on
  Linux/macOS/Windows.
- **default (no feature)** — links a prebuilt `libduckdb`. Set
  `DUCKDB_LIB_DIR` and `DUCKDB_INCLUDE_DIR` to a downloaded DuckDB release.
  Preferred locally on Windows to avoid the long C++ compile.

See the project README for the end-to-end vertical-slice commands.

## On a normal Windows machine

Install the **Visual Studio Build Tools** (VC++ workload) and use the
default MSVC Rust toolchain — everything above becomes unnecessary.
