"""DuckDB trace store — Python reference mirroring crates/store/src/lib.rs.

Same schema, same method surface, same query semantics. When the Rust
toolchain is available, `stethoscope-store` replaces this with no behavioural
change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import duckdb

from .ids import ulid
from .schema import SCHEMA_SQL


@dataclass
class TraceRow:
    id: str
    project_id: str
    label: str | None
    status: str
    started_at: datetime
    ended_at: datetime | None
    span_count: int
    total_cost_usd: float | None
    total_tokens_in: int | None
    total_tokens_out: int | None
    agent_framework: str | None
    is_branch: bool
    parent_trace_id: str | None


class Store:
    def __init__(self, con: duckdb.DuckDBPyConnection):
        self._con = con
        self._con.execute(SCHEMA_SQL)

    @classmethod
    def open(cls, path: str) -> Store:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return cls(duckdb.connect(path))

    @classmethod
    def open_in_memory(cls) -> Store:
        return cls(duckdb.connect(":memory:"))

    def ensure_project(self, name: str) -> str:
        row = self._con.execute(
            "SELECT id FROM projects WHERE name = ? LIMIT 1", [name]
        ).fetchone()
        if row:
            return row[0]
        pid = ulid()
        self._con.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)", [pid, name]
        )
        return pid

    # ON CONFLICT DO UPDATE (not INSERT OR REPLACE): REPLACE deletes the row
    # first, which DuckDB blocks while child rows FK-reference it.
    def upsert_trace(self, t: dict[str, Any]) -> None:
        self._con.execute(
            """INSERT INTO traces (
                id, project_id, parent_trace_id, branch_point_span_id, label,
                status, started_at, ended_at, total_cost_usd, total_tokens_in,
                total_tokens_out, agent_framework, framework_version,
                metadata_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (id) DO UPDATE SET
                project_id=excluded.project_id,
                parent_trace_id=excluded.parent_trace_id,
                branch_point_span_id=excluded.branch_point_span_id,
                label=excluded.label, status=excluded.status,
                started_at=excluded.started_at, ended_at=excluded.ended_at,
                total_cost_usd=excluded.total_cost_usd,
                total_tokens_in=excluded.total_tokens_in,
                total_tokens_out=excluded.total_tokens_out,
                agent_framework=excluded.agent_framework,
                framework_version=excluded.framework_version,
                metadata_json=excluded.metadata_json""",
            [
                t["id"], t["project_id"], t.get("parent_trace_id"),
                t.get("branch_point_span_id"), t.get("label"), t["status"],
                t["started_at"], t.get("ended_at"), t.get("total_cost_usd"),
                t.get("total_tokens_in"), t.get("total_tokens_out"),
                t.get("agent_framework"), t.get("framework_version"),
                t.get("metadata_json"),
            ],
        )

    def upsert_span(self, s: dict[str, Any]) -> None:
        self._con.execute(
            """INSERT INTO spans (
                id, trace_id, parent_span_id, kind, name, started_at,
                ended_at, duration_ms, status, error_message, cost_usd,
                tokens_in, tokens_out, tokens_cached, model, provider,
                temperature, payload_ref, prompt_hash, cacheable, redacted,
                attributes_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (id) DO UPDATE SET
                trace_id=excluded.trace_id,
                parent_span_id=excluded.parent_span_id, kind=excluded.kind,
                name=excluded.name, started_at=excluded.started_at,
                ended_at=excluded.ended_at, duration_ms=excluded.duration_ms,
                status=excluded.status, error_message=excluded.error_message,
                cost_usd=excluded.cost_usd, tokens_in=excluded.tokens_in,
                tokens_out=excluded.tokens_out,
                tokens_cached=excluded.tokens_cached, model=excluded.model,
                provider=excluded.provider, temperature=excluded.temperature,
                payload_ref=excluded.payload_ref,
                prompt_hash=excluded.prompt_hash,
                cacheable=excluded.cacheable, redacted=excluded.redacted,
                attributes_json=excluded.attributes_json""",
            [
                s["id"], s["trace_id"], s.get("parent_span_id"), s["kind"],
                s["name"], s.get("started_at"), s.get("ended_at"),
                s.get("duration_ms"), s["status"], s.get("error_message"),
                s.get("cost_usd"), s.get("tokens_in"), s.get("tokens_out"),
                s.get("tokens_cached"), s.get("model"), s.get("provider"),
                s.get("temperature"), s.get("payload_ref"),
                s.get("prompt_hash"), s.get("cacheable"),
                s.get("redacted", False), s.get("attributes_json"),
            ],
        )

    def insert_message(self, m: dict[str, Any]) -> None:
        self._con.execute(
            """INSERT INTO messages (
                id, span_id, seq, role, content_ref, content_inline,
                tool_call_id, metadata_json
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT (id) DO UPDATE SET
                span_id=excluded.span_id, seq=excluded.seq,
                role=excluded.role, content_ref=excluded.content_ref,
                content_inline=excluded.content_inline,
                tool_call_id=excluded.tool_call_id,
                metadata_json=excluded.metadata_json""",
            [
                m["id"], m["span_id"], m["seq"], m["role"],
                m.get("content_ref"), m.get("content_inline"),
                m.get("tool_call_id"), m.get("metadata_json"),
            ],
        )

    def insert_tool_call(self, c: dict[str, Any]) -> None:
        self._con.execute(
            """INSERT INTO tool_calls (
                span_id, tool_name, arguments_ref, arguments_inline,
                result_ref, result_inline, error
            ) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT (span_id) DO UPDATE SET
                tool_name=excluded.tool_name,
                arguments_ref=excluded.arguments_ref,
                arguments_inline=excluded.arguments_inline,
                result_ref=excluded.result_ref,
                result_inline=excluded.result_inline,
                error=excluded.error""",
            [
                c["span_id"], c["tool_name"], c.get("arguments_ref"),
                c.get("arguments_inline"), c.get("result_ref"),
                c.get("result_inline"), c.get("error"),
            ],
        )

    def list_traces(self, project_id: str | None) -> list[TraceRow]:
        rows = self._con.execute(
            """
            SELECT t.id, t.project_id, t.label, t.status, t.started_at,
                   t.ended_at, COUNT(s.id) AS span_count, t.total_cost_usd,
                   t.total_tokens_in, t.total_tokens_out, t.agent_framework,
                   (t.parent_trace_id IS NOT NULL) AS is_branch,
                   t.parent_trace_id
            FROM traces t
            LEFT JOIN spans s ON s.trace_id = t.id
            WHERE (? IS NULL OR t.project_id = ?)
            GROUP BY t.id, t.project_id, t.label, t.status, t.started_at,
                     t.ended_at, t.total_cost_usd, t.total_tokens_in,
                     t.total_tokens_out, t.agent_framework, t.parent_trace_id
            ORDER BY t.started_at DESC
            """,
            [project_id, project_id],
        ).fetchall()
        return [
            TraceRow(
                id=r[0], project_id=r[1], label=r[2], status=r[3],
                started_at=r[4], ended_at=r[5], span_count=r[6],
                total_cost_usd=r[7], total_tokens_in=r[8],
                total_tokens_out=r[9], agent_framework=r[10],
                is_branch=bool(r[11]), parent_trace_id=r[12],
            )
            for r in rows
        ]

    def list_projects(self) -> list[tuple[str, str]]:
        return [
            (r[0], r[1])
            for r in self._con.execute(
                "SELECT id, name FROM projects ORDER BY created_at"
            ).fetchall()
        ]

    # ---- read API (Phase 3) -------------------------------------------
    # Returns JSON-friendly dicts; the HTTP layer serializes datetimes.

    def _rows(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        cur = self._con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def get_spans(self, trace_id: str) -> list[dict[str, Any]]:
        """All spans for a trace, ordered for tree construction."""
        return self._rows(
            """SELECT id, trace_id, parent_span_id, kind, name, started_at,
                      ended_at, duration_ms, status, error_message, cost_usd,
                      tokens_in, tokens_out, tokens_cached, model, provider,
                      temperature, prompt_hash, cacheable, attributes_json
               FROM spans WHERE trace_id = ?
               ORDER BY started_at, id""",
            [trace_id],
        )

    def get_span(self, span_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM spans WHERE id = ?", [span_id])
        return rows[0] if rows else None

    def get_messages(self, span_id: str) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT id, span_id, seq, role, content_inline, content_ref,
                      tool_call_id
               FROM messages WHERE span_id = ? ORDER BY seq""",
            [span_id],
        )

    def get_tool_call(self, span_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            "SELECT * FROM tool_calls WHERE span_id = ?", [span_id]
        )
        return rows[0] if rows else None

    def get_state(self, span_id: str) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT id, span_id, captured_at, state_ref, state_hash,
                      schema_version
               FROM state_snapshots WHERE span_id = ? ORDER BY captured_at""",
            [span_id],
        )

    # ---- replay cache (PRD 7.3) ---------------------------------------
    # response_ref holds the response inline (consistent with the documented
    # "inline, not Parquet yet" slice limitation).

    def upsert_llm_cache(self, c: dict[str, Any]) -> None:
        self._con.execute(
            """INSERT INTO llm_cache (
                prompt_hash, model, response_ref, tokens_in, tokens_out,
                captured_at
            ) VALUES (?,?,?,?,?,?)
            ON CONFLICT (prompt_hash) DO UPDATE SET
                model=excluded.model, response_ref=excluded.response_ref,
                tokens_in=excluded.tokens_in, tokens_out=excluded.tokens_out,
                captured_at=excluded.captured_at""",
            [
                c["prompt_hash"], c.get("model"), c.get("response_ref"),
                c.get("tokens_in"), c.get("tokens_out"), c["captured_at"],
            ],
        )

    def get_llm_cache(self, prompt_hash: str) -> dict[str, Any] | None:
        rows = self._rows(
            "SELECT * FROM llm_cache WHERE prompt_hash = ?", [prompt_hash]
        )
        return rows[0] if rows else None

    # ---- breakpoints (Phase 7, PRD 4.3 / 9.5) -------------------------

    def add_breakpoint(
        self, project_id: str, name: str | None, condition_dsl: str
    ) -> str:
        bid = ulid()
        self._con.execute(
            """INSERT INTO breakpoints (id, project_id, name, condition_dsl,
               enabled, hit_count) VALUES (?,?,?,?,TRUE,0)""",
            [bid, project_id, name, condition_dsl],
        )
        return bid

    def delete_breakpoint(self, bp_id: str) -> None:
        self._con.execute("DELETE FROM breakpoints WHERE id = ?", [bp_id])

    def list_breakpoints(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT id, project_id, name, condition_dsl, enabled,
                      hit_count, last_hit_at, last_hit_span_id,
                      last_hit_trace_id
               FROM breakpoints ORDER BY id""",
            [],
        )

    def enabled_breakpoints(self) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT id, condition_dsl FROM breakpoints WHERE enabled = TRUE",
            [],
        )

    def record_breakpoint_hit(
        self, bp_id: str, span_id: str, trace_id: str, when
    ) -> None:
        self._con.execute(
            """UPDATE breakpoints
               SET hit_count = hit_count + 1, last_hit_at = ?,
                   last_hit_span_id = ?, last_hit_trace_id = ?
               WHERE id = ?""",
            [when, span_id, trace_id, bp_id],
        )

    # ---- .steth portable bundle (Phase 7, PRD 4.11) -------------------

    def export_trace(self, trace_id: str) -> dict[str, Any]:
        spans = self.get_spans(trace_id)
        bundle: dict[str, Any] = {
            "steth_version": 1,
            "trace_id": trace_id,
            "spans": spans,
            "messages": {},
            "tool_calls": {},
            "llm_cache": {},
        }
        for s in spans:
            sid = s["id"]
            ms = self.get_messages(sid)
            if ms:
                bundle["messages"][sid] = ms
            tc = self.get_tool_call(sid)
            if tc:
                bundle["tool_calls"][sid] = tc
            if s.get("prompt_hash"):
                hit = self.get_llm_cache(s["prompt_hash"])
                if hit:
                    bundle["llm_cache"][s["prompt_hash"]] = hit
        return bundle
