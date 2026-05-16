//! Row models for the Stethoscope trace store.
//!
//! `New*` structs are write payloads; `*Row` structs are read projections.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewTrace {
    pub id: String,
    pub project_id: String,
    pub parent_trace_id: Option<String>,
    pub branch_point_span_id: Option<String>,
    pub label: Option<String>,
    pub status: String,
    pub started_at: DateTime<Utc>,
    pub ended_at: Option<DateTime<Utc>>,
    pub total_cost_usd: Option<f64>,
    pub total_tokens_in: Option<i64>,
    pub total_tokens_out: Option<i64>,
    pub agent_framework: Option<String>,
    pub framework_version: Option<String>,
    pub metadata_json: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct NewSpan {
    pub id: String,
    pub trace_id: String,
    pub parent_span_id: Option<String>,
    pub kind: String,
    pub name: String,
    pub started_at: Option<DateTime<Utc>>,
    pub ended_at: Option<DateTime<Utc>>,
    pub duration_ms: Option<i64>,
    pub status: String,
    pub error_message: Option<String>,
    pub cost_usd: Option<f64>,
    pub tokens_in: Option<i64>,
    pub tokens_out: Option<i64>,
    pub tokens_cached: Option<i64>,
    pub model: Option<String>,
    pub provider: Option<String>,
    pub temperature: Option<f64>,
    pub payload_ref: Option<String>,
    pub prompt_hash: Option<String>,
    pub cacheable: Option<bool>,
    pub redacted: bool,
    pub attributes_json: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewMessage {
    pub id: String,
    pub span_id: String,
    pub seq: i32,
    pub role: String,
    pub content_ref: Option<String>,
    pub content_inline: Option<String>,
    pub tool_call_id: Option<String>,
    pub metadata_json: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewToolCall {
    pub span_id: String,
    pub tool_name: String,
    pub arguments_ref: Option<String>,
    pub arguments_inline: Option<String>,
    pub result_ref: Option<String>,
    pub result_inline: Option<String>,
    pub error: Option<String>,
}

/// Read projection for `stethoscope list-traces`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceRow {
    pub id: String,
    pub project_id: String,
    pub label: Option<String>,
    pub status: String,
    pub started_at: DateTime<Utc>,
    pub ended_at: Option<DateTime<Utc>>,
    pub span_count: i64,
    pub total_cost_usd: Option<f64>,
    pub total_tokens_in: Option<i64>,
    pub total_tokens_out: Option<i64>,
    pub agent_framework: Option<String>,
    pub is_branch: bool,
}
