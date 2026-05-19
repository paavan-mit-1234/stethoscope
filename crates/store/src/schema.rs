//! DuckDB schema (PRD section 7.1 + 7.3).
//!
//! Applied idempotently on [`crate::Store::open`]. Span kinds are documented
//! here but not DB-enforced, matching the PRD.
//!
//! Deliberate deviation from the PRD's literal DDL: the `REFERENCES`
//! foreign-key clauses are dropped. DuckDB cannot UPDATE/DELETE a row that is
//! FK-referenced by existing child rows (UPDATE is internally delete+insert
//! — a documented DuckDB limitation), which is irreconcilable with required
//! behaviour: live trace tail, status running->completed, multi-batch spans,
//! and branch upserts all re-write parent rows that already have children.
//! Columns, primary keys, and indexes are unchanged; referential integrity
//! is upheld by the ingestion layer (a trace is always written before its
//! spans).

/// Span kinds (PRD section 7.1). Not enforced by the DB.
pub mod span_kind {
    pub const LLM_CALL: &str = "llm_call";
    pub const TOOL_CALL: &str = "tool_call";
    pub const NODE_EXECUTION: &str = "node_execution";
    pub const STATE_MUTATION: &str = "state_mutation";
    pub const ROUTING_DECISION: &str = "routing_decision";
    pub const USER_MESSAGE: &str = "user_message";
    pub const SUB_AGENT: &str = "sub_agent";
    pub const CHECKPOINT: &str = "checkpoint";
}

/// Trace status values (PRD section 7.1, traces.status).
pub mod trace_status {
    pub const RUNNING: &str = "running";
    pub const COMPLETED: &str = "completed";
    pub const FAILED: &str = "failed";
    pub const ABORTED: &str = "aborted";
}

pub const SCHEMA_SQL: &str = r#"
CREATE TABLE IF NOT EXISTS projects (
    id              VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    settings_json   VARCHAR
);

CREATE TABLE IF NOT EXISTS traces (
    id                   VARCHAR PRIMARY KEY,
    project_id           VARCHAR NOT NULL,
    parent_trace_id      VARCHAR,
    branch_point_span_id VARCHAR,
    label                VARCHAR,
    status               VARCHAR NOT NULL,
    started_at           TIMESTAMP NOT NULL,
    ended_at             TIMESTAMP,
    total_cost_usd       DOUBLE,
    total_tokens_in      BIGINT,
    total_tokens_out     BIGINT,
    agent_framework      VARCHAR,
    framework_version    VARCHAR,
    metadata_json        VARCHAR
);
CREATE INDEX IF NOT EXISTS traces_project_idx ON traces(project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS traces_parent_idx  ON traces(parent_trace_id);

CREATE TABLE IF NOT EXISTS spans (
    id              VARCHAR PRIMARY KEY,
    trace_id        VARCHAR NOT NULL,
    parent_span_id  VARCHAR,
    kind            VARCHAR NOT NULL,
    name            VARCHAR NOT NULL,
    started_at      TIMESTAMP NOT NULL,
    ended_at        TIMESTAMP,
    duration_ms     BIGINT,
    status          VARCHAR NOT NULL,
    error_message   VARCHAR,
    cost_usd        DOUBLE,
    tokens_in       BIGINT,
    tokens_out      BIGINT,
    tokens_cached   BIGINT,
    model           VARCHAR,
    provider        VARCHAR,
    temperature     DOUBLE,
    payload_ref     VARCHAR,
    prompt_hash     VARCHAR,
    cacheable       BOOLEAN,
    redacted        BOOLEAN DEFAULT FALSE,
    attributes_json VARCHAR
);
CREATE INDEX IF NOT EXISTS spans_trace_idx       ON spans(trace_id, started_at);
CREATE INDEX IF NOT EXISTS spans_parent_idx      ON spans(parent_span_id);
CREATE INDEX IF NOT EXISTS spans_kind_idx        ON spans(kind);
CREATE INDEX IF NOT EXISTS spans_prompt_hash_idx ON spans(prompt_hash);

CREATE TABLE IF NOT EXISTS messages (
    id              VARCHAR PRIMARY KEY,
    span_id         VARCHAR NOT NULL,
    seq             INTEGER NOT NULL,
    role            VARCHAR NOT NULL,
    content_ref     VARCHAR,
    content_inline  VARCHAR,
    tool_call_id    VARCHAR,
    metadata_json   VARCHAR
);
CREATE INDEX IF NOT EXISTS messages_span_idx ON messages(span_id, seq);

CREATE TABLE IF NOT EXISTS tool_calls (
    span_id          VARCHAR PRIMARY KEY,
    tool_name        VARCHAR NOT NULL,
    arguments_ref    VARCHAR,
    arguments_inline VARCHAR,
    result_ref       VARCHAR,
    result_inline    VARCHAR,
    error            VARCHAR
);

CREATE TABLE IF NOT EXISTS state_snapshots (
    id              VARCHAR PRIMARY KEY,
    span_id         VARCHAR NOT NULL,
    captured_at     TIMESTAMP NOT NULL,
    state_ref       VARCHAR NOT NULL,
    state_hash      VARCHAR NOT NULL,
    schema_version  VARCHAR
);
CREATE INDEX IF NOT EXISTS state_snapshots_span_idx ON state_snapshots(span_id);

CREATE TABLE IF NOT EXISTS breakpoints (
    id              VARCHAR PRIMARY KEY,
    project_id      VARCHAR NOT NULL,
    name            VARCHAR,
    condition_dsl   VARCHAR NOT NULL,
    enabled         BOOLEAN DEFAULT TRUE,
    hit_count       BIGINT DEFAULT 0,
    -- Stethoscope extension (beyond PRD 7.1): last-hit pointer so the UI can
    -- focus the matching span (PRD 9.5 "focuses the matching span").
    last_hit_at       TIMESTAMP,
    last_hit_span_id  VARCHAR,
    last_hit_trace_id VARCHAR
);

CREATE TABLE IF NOT EXISTS saved_queries (
    id              VARCHAR PRIMARY KEY,
    project_id      VARCHAR NOT NULL,
    name            VARCHAR NOT NULL,
    query_dsl       VARCHAR NOT NULL,
    color           VARCHAR
);

-- Replay cache (PRD section 7.3): deterministic replay of LLM calls.
CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash     VARCHAR PRIMARY KEY,
    model           VARCHAR NOT NULL,
    response_ref    VARCHAR NOT NULL,
    tokens_in       BIGINT,
    tokens_out      BIGINT,
    captured_at     TIMESTAMP NOT NULL
);
"#;
