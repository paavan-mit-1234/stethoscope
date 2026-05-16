"""Phase 1 vertical-slice smoke test (toolchain-free path).

  1. start the ingestion endpoint (OTLP/gRPC :4317)
  2. run the instrumented example agent
  3. `list-traces` and assert the trace was captured

Run from the repo root:  python scripts/smoke.py
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, ".stethoscope", "smoke", "traces.db")
ADDR = "127.0.0.1:4317"


def wait_port(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def main() -> int:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    for ext in ("", ".wal"):
        try:
            os.remove(DB + ext)
        except FileNotFoundError:
            pass

    env = {**os.environ, "STETHOSCOPE_ENDPOINT": ADDR}
    print("[smoke] starting ingestion service...")
    svc = subprocess.Popen(
        [sys.executable, "-m", "tools.ref_ingest", "serve", "--db", DB,
         "--addr", ADDR],
        cwd=ROOT, env=env,
    )
    try:
        host, port = ADDR.split(":")
        if not wait_port(host, int(port)):
            print("[smoke] FAIL: server never bound")
            return 1

        print("[smoke] running instrumented agent...")
        r = subprocess.run(
            [sys.executable, "examples/min_agent/agent.py"],
            cwd=ROOT, env=env,
        )
        if r.returncode != 0:
            print("[smoke] FAIL: agent exited non-zero")
            return 1
        time.sleep(2)  # let the batch exporter flush

        # DuckDB is single-writer per file across processes; stop the
        # ingestion service to release the lock before reading. (In the real
        # app the service + UI share one in-process connection.)
        print("[smoke] stopping ingestion service...")
        svc.terminate()
        try:
            svc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            svc.kill()

        print("[smoke] listing traces...")
        res = subprocess.run(
            [sys.executable, "-m", "tools.ref_ingest", "list-traces",
             "--db", DB],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        out = res.stdout
        print(out)
        if res.stderr.strip():
            print("[smoke] list-traces stderr:\n" + res.stderr)

        if "support-bot" in out and "trace(s)." in out:
            print("[smoke] PASS")
            return 0
        print("[smoke] FAIL: trace not captured")
        return 1
    finally:
        svc.terminate()
        try:
            svc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            svc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
