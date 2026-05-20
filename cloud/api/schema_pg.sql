-- Stethoscope Cloud — Postgres schema (RDS), the multi-tenant canon.
-- Same logical model as tools/ref_ingest/schema.py; differences:
--   * DuckDB TIMESTAMP -> TIMESTAMPTZ, DOUBLE -> DOUBLE PRECISION
--   * tenant_id on every tenant-scoped, directly-queried table
--   * no FK enforcement (same deliberate deviation as the embedded store)
-- Apply once per environment (see cloud/README.md runbook).

CREATE TABLE IF NOT EXISTS tenants (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    api_key     VARCHAR NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Users (Cloud Phase 2). In production the AWS canon uses Cognito as the
-- identity store (see auth_cognito.py); this table is the local-reference
-- equivalent and stays in the schema for environments without Cognito.
CREATE TABLE IF NOT EXISTS users (
    id            VARCHAR PRIMARY KEY,
    tenant_id     VARCHAR NOT NULL,
    email         VARCHAR NOT NULL UNIQUE,
    password_hash VARCHAR NOT NULL,
    pw_salt       VARCHAR NOT NULL,
    role          VARCHAR NOT NULL DEFAULT 'member',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS users_tenant ON users(tenant_id);

CREATE TABLE IF NOT EXISTS projects (
    id            VARCHAR NOT NULL,
    tenant_id     VARCHAR NOT NULL,
    name          VARCHAR NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    settings_json VARCHAR,
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS traces (
    id                   VARCHAR NOT NULL,
    tenant_id            VARCHAR NOT NULL,
    project_id           VARCHAR NOT NULL,
    parent_trace_id      VARCHAR,
    branch_point_span_id VARCHAR,
    label                VARCHAR,
    status               VARCHAR NOT NULL,
    started_at           TIMESTAMPTZ NOT NULL,
    ended_at             TIMESTAMPTZ,
    total_cost_usd       DOUBLE PRECISION,
    total_tokens_in      BIGINT,
    total_tokens_out     BIGINT,
    agent_framework      VARCHAR,
    framework_version    VARCHAR,
    metadata_json        VARCHAR,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS traces_tenant_proj ON traces(tenant_id, project_id, started_at DESC);

CREATE TABLE IF NOT EXISTS spans (
    id              VARCHAR NOT NULL,
    tenant_id       VARCHAR NOT NULL,
    trace_id        VARCHAR NOT NULL,
    parent_span_id  VARCHAR,
    kind            VARCHAR NOT NULL,
    name            VARCHAR NOT NULL,
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    duration_ms     BIGINT,
    status          VARCHAR NOT NULL,
    error_message   VARCHAR,
    cost_usd        DOUBLE PRECISION,
    tokens_in       BIGINT,
    tokens_out      BIGINT,
    tokens_cached   BIGINT,
    model           VARCHAR,
    provider        VARCHAR,
    temperature     DOUBLE PRECISION,
    payload_ref     VARCHAR,
    prompt_hash     VARCHAR,
    cacheable       BOOLEAN,
    redacted        BOOLEAN DEFAULT FALSE,
    attributes_json VARCHAR,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS spans_tenant_trace ON spans(tenant_id, trace_id, started_at);

CREATE TABLE IF NOT EXISTS messages (
    id             VARCHAR NOT NULL,
    tenant_id      VARCHAR NOT NULL,
    span_id        VARCHAR NOT NULL,
    seq            INTEGER NOT NULL,
    role           VARCHAR NOT NULL,
    content_ref    VARCHAR,
    content_inline VARCHAR,
    tool_call_id   VARCHAR,
    metadata_json  VARCHAR,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS messages_tenant_span ON messages(tenant_id, span_id, seq);

CREATE TABLE IF NOT EXISTS tool_calls (
    span_id          VARCHAR NOT NULL,
    tenant_id        VARCHAR NOT NULL,
    tool_name        VARCHAR NOT NULL,
    arguments_ref    VARCHAR,
    arguments_inline VARCHAR,
    result_ref       VARCHAR,
    result_inline    VARCHAR,
    error            VARCHAR,
    PRIMARY KEY (tenant_id, span_id)
);

CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash  VARCHAR NOT NULL,
    tenant_id    VARCHAR NOT NULL,
    model        VARCHAR,
    response_ref VARCHAR NOT NULL,
    tokens_in    BIGINT,
    tokens_out   BIGINT,
    captured_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, prompt_hash)
);

CREATE TABLE IF NOT EXISTS breakpoints (
    id                VARCHAR NOT NULL,
    tenant_id         VARCHAR NOT NULL,
    project_id        VARCHAR NOT NULL,
    name              VARCHAR,
    condition_dsl     VARCHAR NOT NULL,
    enabled           BOOLEAN DEFAULT TRUE,
    hit_count         BIGINT DEFAULT 0,
    last_hit_at       TIMESTAMPTZ,
    last_hit_span_id  VARCHAR,
    last_hit_trace_id VARCHAR,
    PRIMARY KEY (tenant_id, id)
);

-- Large payloads / .steth bundles live in S3 (s3://<bucket>/<tenant_id>/...),
-- referenced by *_ref columns. Cloud Phase 2 wires the S3 offload; Phase 1
-- keeps payloads inline (same documented limitation as the embedded store).
