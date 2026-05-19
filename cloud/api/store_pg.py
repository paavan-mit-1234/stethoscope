"""Postgres trace store — the cloud multi-tenant CANON (RDS deploy target).

Drop-in for tools/ref_ingest.store.Store: identical method surface, so
mapper.ingest_request / ref_replay / the breakpoint path / the API work
against it unchanged. Every row is scoped by `tenant_id`; the API binds one
PgStore per request-tenant.

NOT executed on the build machine (no Postgres / cloud here) — same status
as the uncompiled Rust crates. psycopg 3. To switch the API from per-tenant
DuckDB to this, swap `tenancy.store_for` to return `PgStore(pool, tenant)`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from tools.ref_ingest.ids import ulid
from tools.ref_ingest.store import TraceRow

try:  # psycopg is a cloud-only dep (in cloud/requirements.txt)
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # not installed on the build machine — that's expected
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore


class PgStore:
    def __init__(self, conn: "psycopg.Connection", tenant_id: str):
        self._c = conn
        self._t = tenant_id

    # --- helpers -------------------------------------------------------
    def _rows(self, sql: str, params: list) -> list[dict[str, Any]]:
        with self._c.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _exec(self, sql: str, params: list) -> None:
        with self._c.cursor() as cur:
            cur.execute(sql, params)
        self._c.commit()

    # --- write path (used by mapper.ingest_request) --------------------
    def ensure_project(self, name: str) -> str:
        rows = self._rows(
            "SELECT id FROM projects WHERE tenant_id=%s AND name=%s LIMIT 1",
            [self._t, name],
        )
        if rows:
            return rows[0]["id"]
        pid = ulid()
        self._exec(
            "INSERT INTO projects (id, tenant_id, name) VALUES (%s,%s,%s)",
            [pid, self._t, name],
        )
        return pid

    def upsert_trace(self, t: dict[str, Any]) -> None:
        self._exec(
            """INSERT INTO traces (id,tenant_id,project_id,parent_trace_id,
                 branch_point_span_id,label,status,started_at,ended_at,
                 total_cost_usd,total_tokens_in,total_tokens_out,
                 agent_framework,framework_version,metadata_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (tenant_id,id) DO UPDATE SET
                 project_id=EXCLUDED.project_id,
                 parent_trace_id=EXCLUDED.parent_trace_id,
                 branch_point_span_id=EXCLUDED.branch_point_span_id,
                 label=EXCLUDED.label,status=EXCLUDED.status,
                 started_at=EXCLUDED.started_at,ended_at=EXCLUDED.ended_at,
                 total_cost_usd=EXCLUDED.total_cost_usd,
                 total_tokens_in=EXCLUDED.total_tokens_in,
                 total_tokens_out=EXCLUDED.total_tokens_out,
                 agent_framework=EXCLUDED.agent_framework,
                 framework_version=EXCLUDED.framework_version,
                 metadata_json=EXCLUDED.metadata_json""",
            [
                t["id"], self._t, t["project_id"], t.get("parent_trace_id"),
                t.get("branch_point_span_id"), t.get("label"), t["status"],
                t["started_at"], t.get("ended_at"), t.get("total_cost_usd"),
                t.get("total_tokens_in"), t.get("total_tokens_out"),
                t.get("agent_framework"), t.get("framework_version"),
                t.get("metadata_json"),
            ],
        )

    def upsert_span(self, s: dict[str, Any]) -> None:
        cols = ("id,tenant_id,trace_id,parent_span_id,kind,name,started_at,"
                "ended_at,duration_ms,status,error_message,cost_usd,tokens_in,"
                "tokens_out,tokens_cached,model,provider,temperature,"
                "payload_ref,prompt_hash,cacheable,redacted,attributes_json")
        upd = ",".join(
            f"{c}=EXCLUDED.{c}"
            for c in cols.split(",")
            if c not in ("id", "tenant_id")
        )
        self._exec(
            f"INSERT INTO spans ({cols}) VALUES ({','.join(['%s']*23)}) "
            f"ON CONFLICT (tenant_id,id) DO UPDATE SET {upd}",
            [
                s["id"], self._t, s["trace_id"], s.get("parent_span_id"),
                s["kind"], s["name"], s.get("started_at"), s.get("ended_at"),
                s.get("duration_ms"), s["status"], s.get("error_message"),
                s.get("cost_usd"), s.get("tokens_in"), s.get("tokens_out"),
                s.get("tokens_cached"), s.get("model"), s.get("provider"),
                s.get("temperature"), s.get("payload_ref"),
                s.get("prompt_hash"), s.get("cacheable"),
                s.get("redacted", False), s.get("attributes_json"),
            ],
        )

    def insert_message(self, m: dict[str, Any]) -> None:
        self._exec(
            """INSERT INTO messages (id,tenant_id,span_id,seq,role,
                 content_ref,content_inline,tool_call_id,metadata_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (tenant_id,id) DO UPDATE SET
                 span_id=EXCLUDED.span_id,seq=EXCLUDED.seq,role=EXCLUDED.role,
                 content_ref=EXCLUDED.content_ref,
                 content_inline=EXCLUDED.content_inline,
                 tool_call_id=EXCLUDED.tool_call_id,
                 metadata_json=EXCLUDED.metadata_json""",
            [
                m["id"], self._t, m["span_id"], m["seq"], m["role"],
                m.get("content_ref"), m.get("content_inline"),
                m.get("tool_call_id"), m.get("metadata_json"),
            ],
        )

    def insert_tool_call(self, c: dict[str, Any]) -> None:
        self._exec(
            """INSERT INTO tool_calls (span_id,tenant_id,tool_name,
                 arguments_ref,arguments_inline,result_ref,result_inline,error)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (tenant_id,span_id) DO UPDATE SET
                 tool_name=EXCLUDED.tool_name,
                 arguments_ref=EXCLUDED.arguments_ref,
                 arguments_inline=EXCLUDED.arguments_inline,
                 result_ref=EXCLUDED.result_ref,
                 result_inline=EXCLUDED.result_inline,error=EXCLUDED.error""",
            [
                c["span_id"], self._t, c["tool_name"], c.get("arguments_ref"),
                c.get("arguments_inline"), c.get("result_ref"),
                c.get("result_inline"), c.get("error"),
            ],
        )

    def upsert_llm_cache(self, c: dict[str, Any]) -> None:
        self._exec(
            """INSERT INTO llm_cache (prompt_hash,tenant_id,model,
                 response_ref,tokens_in,tokens_out,captured_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (tenant_id,prompt_hash) DO UPDATE SET
                 model=EXCLUDED.model,response_ref=EXCLUDED.response_ref,
                 tokens_in=EXCLUDED.tokens_in,tokens_out=EXCLUDED.tokens_out,
                 captured_at=EXCLUDED.captured_at""",
            [
                c["prompt_hash"], self._t, c.get("model"),
                c.get("response_ref"), c.get("tokens_in"),
                c.get("tokens_out"), c["captured_at"],
            ],
        )

    # --- breakpoints ---------------------------------------------------
    def enabled_breakpoints(self) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT id,condition_dsl FROM breakpoints "
            "WHERE tenant_id=%s AND enabled=TRUE",
            [self._t],
        )

    def record_breakpoint_hit(self, bp_id, span_id, trace_id, when) -> None:
        self._exec(
            """UPDATE breakpoints SET hit_count=hit_count+1,last_hit_at=%s,
                 last_hit_span_id=%s,last_hit_trace_id=%s
               WHERE tenant_id=%s AND id=%s""",
            [when, span_id, trace_id, self._t, bp_id],
        )

    def add_breakpoint(self, project_id, name, condition_dsl) -> str:
        bid = ulid()
        self._exec(
            """INSERT INTO breakpoints (id,tenant_id,project_id,name,
                 condition_dsl,enabled,hit_count)
               VALUES (%s,%s,%s,%s,%s,TRUE,0)""",
            [bid, self._t, project_id, name, condition_dsl],
        )
        return bid

    def delete_breakpoint(self, bp_id: str) -> None:
        self._exec(
            "DELETE FROM breakpoints WHERE tenant_id=%s AND id=%s",
            [self._t, bp_id],
        )

    def list_breakpoints(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT id,project_id,name,condition_dsl,enabled,hit_count,
                 last_hit_at,last_hit_span_id,last_hit_trace_id
               FROM breakpoints WHERE tenant_id=%s ORDER BY id""",
            [self._t],
        )

    # --- reads ---------------------------------------------------------
    def list_projects(self) -> list[tuple[str, str]]:
        return [
            (r["id"], r["name"])
            for r in self._rows(
                "SELECT id,name FROM projects WHERE tenant_id=%s "
                "ORDER BY created_at",
                [self._t],
            )
        ]

    def list_traces(self, project_id: str | None) -> list[TraceRow]:
        rows = self._rows(
            """SELECT t.id,t.project_id,t.label,t.status,t.started_at,
                 t.ended_at,
                 (SELECT COUNT(*) FROM spans s
                    WHERE s.tenant_id=t.tenant_id AND s.trace_id=t.id) span_count,
                 t.total_cost_usd,t.total_tokens_in,t.total_tokens_out,
                 t.agent_framework,(t.parent_trace_id IS NOT NULL) is_branch,
                 t.parent_trace_id
               FROM traces t
               WHERE t.tenant_id=%s AND (%s IS NULL OR t.project_id=%s)
               ORDER BY t.started_at DESC""",
            [self._t, project_id, project_id],
        )
        return [
            TraceRow(
                id=r["id"], project_id=r["project_id"], label=r["label"],
                status=r["status"], started_at=r["started_at"],
                ended_at=r["ended_at"], span_count=r["span_count"],
                total_cost_usd=r["total_cost_usd"],
                total_tokens_in=r["total_tokens_in"],
                total_tokens_out=r["total_tokens_out"],
                agent_framework=r["agent_framework"],
                is_branch=bool(r["is_branch"]),
                parent_trace_id=r["parent_trace_id"],
            )
            for r in rows
        ]

    _SPAN_COLS = ("id,trace_id,parent_span_id,kind,name,started_at,ended_at,"
                  "duration_ms,status,error_message,cost_usd,tokens_in,"
                  "tokens_out,tokens_cached,model,provider,temperature,"
                  "prompt_hash,cacheable,attributes_json")

    def get_spans(self, trace_id: str) -> list[dict[str, Any]]:
        return self._rows(
            f"SELECT {self._SPAN_COLS} FROM spans "
            f"WHERE tenant_id=%s AND trace_id=%s ORDER BY started_at,id",
            [self._t, trace_id],
        )

    def get_span(self, span_id: str) -> dict[str, Any] | None:
        r = self._rows(
            f"SELECT {self._SPAN_COLS} FROM spans "
            f"WHERE tenant_id=%s AND id=%s LIMIT 1",
            [self._t, span_id],
        )
        return r[0] if r else None

    def get_messages(self, span_id: str) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT id,span_id,seq,role,content_inline,content_ref,
                 tool_call_id FROM messages
               WHERE tenant_id=%s AND span_id=%s ORDER BY seq""",
            [self._t, span_id],
        )

    def get_tool_call(self, span_id: str) -> dict[str, Any] | None:
        r = self._rows(
            "SELECT * FROM tool_calls WHERE tenant_id=%s AND span_id=%s",
            [self._t, span_id],
        )
        return r[0] if r else None

    def get_state(self, span_id: str) -> list[dict[str, Any]]:
        return []  # state snapshots not captured (same as the embedded store)

    def get_llm_cache(self, prompt_hash: str) -> dict[str, Any] | None:
        r = self._rows(
            "SELECT * FROM llm_cache WHERE tenant_id=%s AND prompt_hash=%s",
            [self._t, prompt_hash],
        )
        return r[0] if r else None

    def export_trace(self, trace_id: str) -> dict[str, Any]:
        spans = self.get_spans(trace_id)
        b: dict[str, Any] = {
            "steth_version": 1, "trace_id": trace_id, "spans": spans,
            "messages": {}, "tool_calls": {}, "llm_cache": {},
        }
        for s in spans:
            ms = self.get_messages(s["id"])
            if ms:
                b["messages"][s["id"]] = ms
            tc = self.get_tool_call(s["id"])
            if tc:
                b["tool_calls"][s["id"]] = tc
            if s.get("prompt_hash"):
                hit = self.get_llm_cache(s["prompt_hash"])
                if hit:
                    b["llm_cache"][s["prompt_hash"]] = hit
        return b
