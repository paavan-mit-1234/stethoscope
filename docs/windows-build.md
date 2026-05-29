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
  heavy; needs a C++ compiler (the portable MinGW `g++`, or MSVC). Used
  in CI on Linux/macOS/Windows. **Default path for local Windows builds**
  since prebuilt `libduckdb.dll` distribution on Windows is awkward.
- **default (no feature)** — links a prebuilt `libduckdb`. Set
  `DUCKDB_LIB_DIR` and `DUCKDB_INCLUDE_DIR` to a downloaded DuckDB release.
  Preferred on Linux/macOS where the package manager has it.

### MSVC + bundled DuckDB on Windows: the `/EHsc` gotcha

`libduckdb-sys`'s build script does not pass `/EHsc` to MSVC's `cl.exe`,
which causes any C++ source that uses exceptions (re2's `bitstate.cc` is
the first to bite) to fail with warning C4530 promoted to errors. The
repo's `.cargo/config.toml` sets `CXXFLAGS_x86_64-pc-windows-msvc=/EHsc`
target-scoped so this is invisible on non-Windows builds.

If you ever delete that config file, the symptom is a wall of warnings
during the DuckDB compile followed by `linking with link.exe failed:
exit code: 1181, cannot open input file 'duckdb.lib'` — that message is
misleading; the real failure is upstream cl.exe exit 2 on the missing
exception-handling flag.

See the project README for the end-to-end vertical-slice commands.

## On a normal Windows machine

Install the **Visual Studio Build Tools** (VC++ workload) and use the
default MSVC Rust toolchain — everything above becomes unnecessary.
