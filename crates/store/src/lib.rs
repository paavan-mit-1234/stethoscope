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

pub use models::{NewMessage, NewSpan, NewToolCall, NewTrace, TraceRow};
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
        if let Some(id) = self
            .conn
            .query_row(
                "SELECT id FROM projects WHERE name = ? LIMIT 1",
                params![name],
                |r| r.get::<_, String>(0),
            )
            .ok()
        {
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
                   (t.parent_trace_id IS NOT NULL) AS is_branch
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
