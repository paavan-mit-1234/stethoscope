"""`stethoscope` CLI — Python reference mirroring crates/cli.

Phase 1 milestone (PRD section 10): `stethoscope list-traces` prints a table
of captured traces.
"""

from __future__ import annotations

import argparse
import logging

from .server import DEFAULT_OTLP_ADDR, default_db_path, serve
from .store import Store, TraceRow


def _ascii_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    bar = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def fmt(cells: list[str]) -> str:
        return "| " + " | ".join(
            c.ljust(widths[i]) for i, c in enumerate(cells)
        ) + " |"

    out = [bar, fmt(headers), bar]
    out += [fmt(r) for r in rows]
    out.append(bar)
    return "\n".join(out)


def _print_traces(traces: list[TraceRow]) -> None:
    if not traces:
        print("(no traces yet — run an instrumented agent to begin)")
        return
    headers = [
        "TRACE ID", "LABEL", "STATUS", "SPANS", "TOK IN", "TOK OUT",
        "COST $", "FRAMEWORK", "STARTED", "BRANCH",
    ]
    rows = [
        [
            t.id[:16],
            t.label or "-",
            t.status,
            str(t.span_count),
            str(t.total_tokens_in or 0),
            str(t.total_tokens_out or 0),
            f"{t.total_cost_usd or 0.0:.4f}",
            t.agent_framework or "-",
            t.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "fork" if t.is_branch else "",
        ]
        for t in traces
    ]
    print(_ascii_table(headers, rows))
    print(f"{len(traces)} trace(s).")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(
        prog="stethoscope", description="Time-travel debugger for LLM agents"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list-traces", help="list captured traces")
    pl.add_argument("--project")
    pl.add_argument("--db")

    pp = sub.add_parser("projects", help="list known projects")
    pp.add_argument("--db")

    ps = sub.add_parser("serve", help="run the OTLP/gRPC ingestion endpoint")
    ps.add_argument("--addr", default=DEFAULT_OTLP_ADDR)
    ps.add_argument("--db")

    args = p.parse_args(argv)
    db = args.db or default_db_path()

    if args.cmd == "serve":
        serve(args.addr, db)
        return 0

    store = Store.open(db)
    if args.cmd == "projects":
        projects = store.list_projects()
        if not projects:
            print("(no projects yet)")
        for pid, name in projects:
            print(f"{pid}  {name}")
        return 0

    # list-traces
    project_id = None
    if args.project:
        match = [i for i, n in store.list_projects() if n == args.project]
        if not match:
            print(f"no project named '{args.project}'")
            return 1
        project_id = match[0]
    _print_traces(store.list_traces(project_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
