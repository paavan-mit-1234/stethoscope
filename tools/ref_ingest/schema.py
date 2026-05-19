"""DuckDB schema (PRD section 7.1 + 7.3).

Same DDL as crates/store/src/schema.rs so the Rust store is a drop-in
replacement for this reference implementation.

Deliberate deviation from the PRD's literal DDL: the `REFERENCES` foreign-key
clauses are dropped. DuckDB cannot UPDATE or DELETE a row that is
FK-referenced by existing child rows (its UPDATE is internally delete+insert
— a documented DuckDB limitation). That is irreconcilable with required
behaviour: live trace tail, status running->completed, spans arriving across
batches, and branch upserts all re-write parent rows that already have
children. Columns, primary keys, and indexes are unchanged; the logical
relationships still hold and are enforced at the ingestion layer, which
always writes a trace before its spans.
"""

SPAN_KIND = {
    "LLM_CALL": "llm_call",
    "TOOL_CALL": "tool_call",
    "NODE_EXECUTION": "node_execution",
    "STATE_MUTATION": "state_mutation",
    "ROUTING_DECISION": "routing_decision",
    "USER_MESSAGE": "user_message",
    "SUB_AGENT": "sub_agent",
    "CHECKPOINT": "checkpoint",
}

TRACE_STATUS = {
    "RUNNING": "running",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "ABORTED": "aborted",
}

SCHEMA_SQL = r"""
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

CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash     VARCHAR PRIMARY KEY,
    model           VARCHAR NOT NULL,
    response_ref    VARCHAR NOT NULL,
    tokens_in       BIGINT,
    tokens_out      BIGINT,
    captured_at     TIMESTAMP NOT NULL
);
"""
