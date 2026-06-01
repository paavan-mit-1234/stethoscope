//! Stethoscope trace store: DuckDB metadata layer (PRD section 7).
//!
//! Large payloads (messages, tool I/O, state) are referenced via `payload_ref`
//! and live in monthly Parquet files; this crate owns the structured metadata
//! and the deterministic-replay cache.

mod models;
mod schema;

use std::path::Path;

use anyhow::{Context, Result};
use duckdb::{params, Connection};
use ulid::Ulid;

pub use models::{
    BreakpointRow, LlmCacheEntry, MessageRow, NewMessage, NewSpan, NewToolCall,
    NewTrace, SpanRow, ToolCallRow, TraceRow,
};
pub use schema::{span_kind, trace_status, SCHEMA_SQL};

/// A handle to one project's trace store
/// (`~/.stethoscope/projects/<name>/traces.db`).
pub struct Store {
    conn: Connection,
}

impl Store {
    /// Open (creating if needed) the store at `path` and apply the schema
    /// idempotently.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let conn = Connection::open(path.as_ref())
            .with_context(|| format!("opening duckdb at {}", path.as_ref().display()))?;
        let store = Self { conn };
        store.init_schema()?;
        Ok(store)
    }

    /// In-memory store, used by tests and ephemeral tooling.
    pub fn open_in_memory() -> Result<Self> {
        let conn = Connection::open_in_memory().context("opening in-memory duckdb")?;
        let store = Self { conn };
        store.init_schema()?;
        Ok(store)
    }

    fn init_schema(&self) -> Result<()> {
        self.conn
            .execute_batch(SCHEMA_SQL)
            .context("applying schema")
    }

    /// Return the id of the project named `name`, creating it if absent.
    pub fn ensure_project(&self, name: &str) -> Result<String> {
        if let Ok(id) = self.conn.query_row(
            "SELECT id FROM projects WHERE name = ? LIMIT 1",
            params![name],
            |r| r.get::<_, String>(0),
        ) {
            return Ok(id);
        }
        let id = Ulid::new().to_string();
        self.conn
            .execute(
                "INSERT INTO projects (id, name) VALUES (?, ?)",
                params![id, name],
            )
            .context("inserting project")?;
        Ok(id)
    }

    /// Upsert a trace (keyed by W3C trace id). Uses ON CONFLICT DO UPDATE
    /// rather than INSERT OR REPLACE: REPLACE deletes the row first, which
    /// DuckDB blocks while child spans FK-reference it.
    pub fn upsert_trace(&self, t: &NewTrace) -> Result<()> {
        self.conn
            .execute(
                "INSERT INTO traces (
                    id, project_id, parent_trace_id, branch_point_span_id,
                    label, status, started_at, ended_at, total_cost_usd,
                    total_tokens_in, total_tokens_out, agent_framework,
                    framework_version, metadata_json
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
                    metadata_json=excluded.metadata_json",
                params![
                    t.id,
                    t.project_id,
                    t.parent_trace_id,
                    t.branch_point_span_id,
                    t.label,
                    t.status,
                    t.started_at,
                    t.ended_at,
                    t.total_cost_usd,
                    t.total_tokens_in,
                    t.total_tokens_out,
                    t.agent_framework,
                    t.framework_version,
                    t.metadata_json,
                ],
            )
            .context("upserting trace")?;
        Ok(())
    }

    /// Upsert a span (keyed by W3C span id).
    pub fn upsert_span(&self, s: &NewSpan) -> Result<()> {
        self.conn
            .execute(
                "INSERT INTO spans (
                    id, trace_id, parent_span_id, kind, name, started_at,
                    ended_at, duration_ms, status, error_message, cost_usd,
                    tokens_in, tokens_out, tokens_cached, model, provider,
                    temperature, payload_ref, prompt_hash, cacheable,
                    redacted, attributes_json
                 ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT (id) DO UPDATE SET
                    trace_id=excluded.trace_id,
                    parent_span_id=excluded.parent_span_id,
                    kind=excluded.kind, name=excluded.name,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    duration_ms=excluded.duration_ms,
                    status=excluded.status,
                    error_message=excluded.error_message,
                    cost_usd=excluded.cost_usd, tokens_in=excluded.tokens_in,
                    tokens_out=excluded.tokens_out,
                    tokens_cached=excluded.tokens_cached,
                    model=excluded.model, provider=excluded.provider,
                    temperature=excluded.temperature,
                    payload_ref=excluded.payload_ref,
                    prompt_hash=excluded.prompt_hash,
                    cacheable=excluded.cacheable, redacted=excluded.redacted,
                    attributes_json=excluded.attributes_json",
                params![
                    s.id,
                    s.trace_id,
                    s.parent_span_id,
                    s.kind,
                    s.name,
                    s.started_at,
                    s.ended_at,
                    s.duration_ms,
                    s.status,
                    s.error_message,
                    s.cost_usd,
                    s.tokens_in,
                    s.tokens_out,
                    s.tokens_cached,
                    s.model,
                    s.provider,
                    s.temperature,
                    s.payload_ref,
                    s.prompt_hash,
                    s.cacheable,
                    s.redacted,
                    s.attributes_json,
                ],
            )
            .context("upserting span")?;
        Ok(())
    }

    pub fn insert_message(&self, m: &NewMessage) -> Result<()> {
        self.conn
            .execute(
                "INSERT INTO messages (
                    id, span_id, seq, role, content_ref, content_inline,
                    tool_call_id, metadata_json
                 ) VALUES (?,?,?,?,?,?,?,?)
                 ON CONFLICT (id) DO UPDATE SET
                    span_id=excluded.span_id, seq=excluded.seq,
                    role=excluded.role, content_ref=excluded.content_ref,
                    content_inline=excluded.content_inline,
                    tool_call_id=excluded.tool_call_id,
                    metadata_json=excluded.metadata_json",
                params![
                    m.id,
                    m.span_id,
                    m.seq,
                    m.role,
                    m.content_ref,
                    m.content_inline,
                    m.tool_call_id,
                    m.metadata_json,
                ],
            )
            .context("inserting message")?;
        Ok(())
    }

    pub fn insert_tool_call(&self, c: &NewToolCall) -> Result<()> {
        self.conn
            .execute(
                "INSERT INTO tool_calls (
                    span_id, tool_name, arguments_ref, arguments_inline,
                    result_ref, result_inline, error
                 ) VALUES (?,?,?,?,?,?,?)
                 ON CONFLICT (span_id) DO UPDATE SET
                    tool_name=excluded.tool_name,
                    arguments_ref=excluded.arguments_ref,
                    arguments_inline=excluded.arguments_inline,
                    result_ref=excluded.result_ref,
                    result_inline=excluded.result_inline,
                    error=excluded.error",
                params![
                    c.span_id,
                    c.tool_name,
                    c.arguments_ref,
                    c.arguments_inline,
                    c.result_ref,
                    c.result_inline,
                    c.error,
                ],
            )
            .context("inserting tool_call")?;
        Ok(())
    }

    /// List traces, newest first. `project_id = None` lists across all projects.
    pub fn list_traces(&self, project_id: Option<&str>) -> Result<Vec<TraceRow>> {
        let sql = "
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
            ORDER BY t.started_at DESC";
        let mut stmt = self.conn.prepare(sql)?;
        let rows = stmt
            .query_map(params![project_id, project_id], |r| {
                Ok(TraceRow {
                    id: r.get(0)?,
                    project_id: r.get(1)?,
                    label: r.get(2)?,
                    status: r.get(3)?,
                    started_at: r.get(4)?,
                    ended_at: r.get(5)?,
                    span_count: r.get(6)?,
                    total_cost_usd: r.get(7)?,
                    total_tokens_in: r.get(8)?,
                    total_tokens_out: r.get(9)?,
                    agent_framework: r.get(10)?,
                    is_branch: r.get(11)?,
                    parent_trace_id: r.get(12)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    /// Project (id, name) pairs.
    pub fn list_projects(&self) -> Result<Vec<(String, String)>> {
        let mut stmt = self
            .conn
            .prepare("SELECT id, name FROM projects ORDER BY created_at")?;
        let rows = stmt
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    // ---- read API (Phase 3) — backs the Tauri IPC commands ------------

    const SPAN_COLS: &'static str = "id, trace_id, parent_span_id, kind, name, \
        started_at, ended_at, duration_ms, status, error_message, cost_usd, \
        tokens_in, tokens_out, tokens_cached, model, provider, temperature, \
        prompt_hash, cacheable, attributes_json";

    fn map_span_row(r: &duckdb::Row) -> duckdb::Result<SpanRow> {
        Ok(SpanRow {
            id: r.get(0)?,
            trace_id: r.get(1)?,
            parent_span_id: r.get(2)?,
            kind: r.get(3)?,
            name: r.get(4)?,
            started_at: r.get(5)?,
            ended_at: r.get(6)?,
            duration_ms: r.get(7)?,
            status: r.get(8)?,
            error_message: r.get(9)?,
            cost_usd: r.get(10)?,
            tokens_in: r.get(11)?,
            tokens_out: r.get(12)?,
            tokens_cached: r.get(13)?,
            model: r.get(14)?,
            provider: r.get(15)?,
            temperature: r.get(16)?,
            prompt_hash: r.get(17)?,
            cacheable: r.get(18)?,
            attributes_json: r.get(19)?,
        })
    }

    /// All spans for a trace, ordered for tree construction.
    pub fn get_spans(&self, trace_id: &str) -> Result<Vec<SpanRow>> {
        let sql = format!(
            "SELECT {} FROM spans WHERE trace_id = ? ORDER BY started_at, id",
            Self::SPAN_COLS
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt
            .query_map(params![trace_id], Self::map_span_row)?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    pub fn get_span(&self, span_id: &str) -> Result<Option<SpanRow>> {
        let sql = format!(
            "SELECT {} FROM spans WHERE id = ? LIMIT 1",
            Self::SPAN_COLS
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let mut rows = stmt
            .query_map(params![span_id], Self::map_span_row)?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows.pop())
    }

    pub fn get_messages(&self, span_id: &str) -> Result<Vec<MessageRow>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, span_id, seq, role, content_inline, content_ref, \
             tool_call_id FROM messages WHERE span_id = ? ORDER BY seq",
        )?;
        let rows = stmt
            .query_map(params![span_id], |r| {
                Ok(MessageRow {
                    id: r.get(0)?,
                    span_id: r.get(1)?,
                    seq: r.get(2)?,
                    role: r.get(3)?,
                    content_inline: r.get(4)?,
                    content_ref: r.get(5)?,
                    tool_call_id: r.get(6)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    /// Upsert a replay-cache entry (PRD 7.3).
    pub fn upsert_llm_cache(&self, c: &LlmCacheEntry) -> Result<()> {
        self.conn
            .execute(
                "INSERT INTO llm_cache (
                    prompt_hash, model, response_ref, tokens_in, tokens_out,
                    captured_at
                 ) VALUES (?,?,?,?,?,?)
                 ON CONFLICT (prompt_hash) DO UPDATE SET
                    model=excluded.model, response_ref=excluded.response_ref,
                    tokens_in=excluded.tokens_in,
                    tokens_out=excluded.tokens_out,
                    captured_at=excluded.captured_at",
                params![
                    c.prompt_hash,
                    c.model,
                    c.response_ref,
                    c.tokens_in,
                    c.tokens_out,
                    c.captured_at,
                ],
            )
            .context("upserting llm_cache")?;
        Ok(())
    }

    // ---- breakpoints (Phase 7, PRD 4.3 / 9.5) ------------------------

    pub fn add_breakpoint(
        &self,
        project_id: &str,
        name: Option<&str>,
        condition_dsl: &str,
    ) -> Result<String> {
        let id = ulid::Ulid::new().to_string();
        self.conn
            .execute(
                "INSERT INTO breakpoints (id, project_id, name, \
                 condition_dsl, enabled, hit_count) VALUES (?,?,?,?,TRUE,0)",
                params![id, project_id, name, condition_dsl],
            )
            .context("inserting breakpoint")?;
        Ok(id)
    }

    pub fn delete_breakpoint(&self, id: &str) -> Result<()> {
        self.conn
            .execute("DELETE FROM breakpoints WHERE id = ?", params![id])
            .context("deleting breakpoint")?;
        Ok(())
    }

    pub fn list_breakpoints(&self) -> Result<Vec<BreakpointRow>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, project_id, name, condition_dsl, enabled, hit_count, \
             last_hit_at, last_hit_span_id, last_hit_trace_id \
             FROM breakpoints ORDER BY id",
        )?;
        let rows = stmt
            .query_map([], |r| {
                Ok(BreakpointRow {
                    id: r.get(0)?,
                    project_id: r.get(1)?,
                    name: r.get(2)?,
                    condition_dsl: r.get(3)?,
                    enabled: r.get(4)?,
                    hit_count: r.get(5)?,
                    last_hit_at: r.get(6)?,
                    last_hit_span_id: r.get(7)?,
                    last_hit_trace_id: r.get(8)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    pub fn record_breakpoint_hit(
        &self,
        id: &str,
        span_id: &str,
        trace_id: &str,
    ) -> Result<()> {
        self.conn
            .execute(
                "UPDATE breakpoints SET hit_count = hit_count + 1, \
                 last_hit_at = now(), last_hit_span_id = ?, \
                 last_hit_trace_id = ? WHERE id = ?",
                params![span_id, trace_id, id],
            )
            .context("recording breakpoint hit")?;
        Ok(())
    }

    pub fn get_llm_cache(&self, prompt_hash: &str) -> Result<Option<LlmCacheEntry>> {
        let mut stmt = self.conn.prepare(
            "SELECT prompt_hash, model, response_ref, tokens_in, tokens_out, \
             captured_at FROM llm_cache WHERE prompt_hash = ? LIMIT 1",
        )?;
        let mut rows = stmt
            .query_map(params![prompt_hash], |r| {
                Ok(LlmCacheEntry {
                    prompt_hash: r.get(0)?,
                    model: r.get(1)?,
                    response_ref: r.get(2)?,
                    tokens_in: r.get(3)?,
                    tokens_out: r.get(4)?,
                    captured_at: r.get(5)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows.pop())
    }

    pub fn get_tool_call(&self, span_id: &str) -> Result<Option<ToolCallRow>> {
        let mut stmt = self.conn.prepare(
            "SELECT span_id, tool_name, arguments_inline, result_inline, \
             error FROM tool_calls WHERE span_id = ? LIMIT 1",
        )?;
        let mut rows = stmt
            .query_map(params![span_id], |r| {
                Ok(ToolCallRow {
                    span_id: r.get(0)?,
                    tool_name: r.get(1)?,
                    arguments_inline: r.get(2)?,
                    result_inline: r.get(3)?,
                    error: r.get(4)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows.pop())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    #[test]
    fn schema_applies_and_roundtrips() {
        let s = Store::open_in_memory().unwrap();
        let pid = s.ensure_project("agent_v3").unwrap();
        // ensure_project is idempotent
        assert_eq!(pid, s.ensure_project("agent_v3").unwrap());

        s.upsert_trace(&NewTrace {
            id: "trace-1".into(),
            project_id: pid.clone(),
            parent_trace_id: None,
            branch_point_span_id: None,
            label: Some("first run".into()),
            status: trace_status::COMPLETED.into(),
            started_at: Utc::now(),
            ended_at: Some(Utc::now()),
            total_cost_usd: Some(0.0124),
            total_tokens_in: Some(824),
            total_tokens_out: Some(92),
            agent_framework: Some("langgraph".into()),
            framework_version: Some("0.2.0".into()),
            metadata_json: None,
        })
        .unwrap();

        s.upsert_span(&NewSpan {
            id: "span-1".into(),
            trace_id: "trace-1".into(),
            kind: span_kind::NODE_EXECUTION.into(),
            name: "node:planner".into(),
            started_at: Some(Utc::now()),
            status: "ok".into(),
            ..Default::default()
        })
        .unwrap();

        let traces = s.list_traces(Some(&pid)).unwrap();
        assert_eq!(traces.len(), 1);
        assert_eq!(traces[0].span_count, 1);
        assert!(!traces[0].is_branch);
        assert_eq!(traces[0].agent_framework.as_deref(), Some("langgraph"));
    }
}
