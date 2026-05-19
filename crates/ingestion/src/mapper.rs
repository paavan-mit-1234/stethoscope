//! OTel GenAI semantic conventions -> Stethoscope schema (PRD section 7.4).
//!
//! Known limitation (slice scope): large message/tool payloads are stored
//! inline rather than offloaded to monthly Parquet files. The `payload_ref`
//! path is wired in the schema and will be populated by the Parquet writer
//! in a later phase.

use anyhow::Result;
use chrono::{DateTime, Utc};
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use opentelemetry_proto::tonic::common::v1::KeyValue;
use opentelemetry_proto::tonic::trace::v1::Span as OtelSpan;
use std::collections::HashMap;
use stethoscope_store::{
    span_kind, trace_status, LlmCacheEntry, NewMessage, NewSpan, NewToolCall,
    NewTrace, Store,
};
use ulid::Ulid;

use crate::otel::{attrs_map, get_bool, get_f64, get_i64, get_str};

fn ts(nanos: u64) -> Option<DateTime<Utc>> {
    if nanos == 0 {
        return None;
    }
    let secs = (nanos / 1_000_000_000) as i64;
    let sub = (nanos % 1_000_000_000) as u32;
    DateTime::from_timestamp(secs, sub)
}

fn infer_kind(name: &str, attrs: &[KeyValue]) -> String {
    if let Some(k) = get_str(attrs, "stethoscope.kind") {
        return k.to_string();
    }
    if get_str(attrs, "gen_ai.request.model").is_some() {
        return span_kind::LLM_CALL.into();
    }
    if get_str(attrs, "gen_ai.tool.name").is_some() || name.starts_with("tool:") {
        return span_kind::TOOL_CALL.into();
    }
    if name.starts_with("node:") {
        return span_kind::NODE_EXECUTION.into();
    }
    span_kind::NODE_EXECUTION.into()
}

fn status_code(s: &OtelSpan) -> (String, Option<String>) {
    match s.status.as_ref().map(|st| (st.code, st.message.clone())) {
        Some((2, msg)) => ("error".into(), (!msg.is_empty()).then_some(msg)),
        Some((_, _)) => ("ok".into(), None),
        None => ("ok".into(), None),
    }
}

fn map_span(trace_id: &str, s: &OtelSpan) -> NewSpan {
    let a = &s.attributes;
    let started = ts(s.start_time_unix_nano);
    let ended = ts(s.end_time_unix_nano);
    let duration_ms = match (s.start_time_unix_nano, s.end_time_unix_nano) {
        (st, en) if en >= st && st != 0 && en != 0 => Some(((en - st) / 1_000_000) as i64),
        _ => None,
    };
    let (status, error_message) = status_code(s);
    let parent = (!s.parent_span_id.is_empty()).then(|| hex::encode(&s.parent_span_id));

    NewSpan {
        id: hex::encode(&s.span_id),
        trace_id: trace_id.to_string(),
        parent_span_id: parent,
        kind: infer_kind(&s.name, a),
        name: s.name.clone(),
        started_at: started,
        ended_at: ended,
        duration_ms,
        status,
        error_message,
        cost_usd: get_f64(a, "stethoscope.cost_usd"),
        tokens_in: get_i64(a, "gen_ai.usage.input_tokens"),
        tokens_out: get_i64(a, "gen_ai.usage.output_tokens"),
        tokens_cached: get_i64(a, "gen_ai.usage.cached_tokens"),
        model: get_str(a, "gen_ai.request.model").map(String::from),
        provider: get_str(a, "gen_ai.system").map(String::from),
        temperature: get_f64(a, "gen_ai.request.temperature"),
        payload_ref: None,
        prompt_hash: get_str(a, "stethoscope.prompt_hash").map(String::from),
        cacheable: get_bool(a, "stethoscope.cacheable"),
        redacted: get_bool(a, "stethoscope.redacted").unwrap_or(false),
        attributes_json: Some(
            serde_json::Value::Object(attrs_map(a)).to_string(),
        ),
    }
}

fn extract_messages(span_id: &str, a: &[KeyValue]) -> Vec<NewMessage> {
    let mut out = Vec::new();
    let mut seq = 0;
    for (prefix, default_role) in
        [("gen_ai.prompt", "user"), ("gen_ai.completion", "assistant")]
    {
        let mut i = 0;
        loop {
            let ck = format!("{prefix}.{i}.content");
            let Some(content) = get_str(a, &ck) else { break };
            let role = get_str(a, &format!("{prefix}.{i}.role"))
                .unwrap_or(default_role)
                .to_string();
            out.push(NewMessage {
                id: Ulid::new().to_string(),
                span_id: span_id.to_string(),
                seq,
                role,
                content_ref: None,
                content_inline: Some(content.to_string()),
                tool_call_id: get_str(a, &format!("{prefix}.{i}.tool_call_id"))
                    .map(String::from),
                metadata_json: None,
            });
            seq += 1;
            i += 1;
        }
    }
    out
}

fn extract_tool_call(span_id: &str, a: &[KeyValue]) -> Option<NewToolCall> {
    let tool_name = get_str(a, "gen_ai.tool.name")
        .or_else(|| get_str(a, "stethoscope.tool_name"))?;
    Some(NewToolCall {
        span_id: span_id.to_string(),
        tool_name: tool_name.to_string(),
        arguments_ref: None,
        arguments_inline: get_str(a, "stethoscope.tool.arguments").map(String::from),
        result_ref: None,
        result_inline: get_str(a, "stethoscope.tool.result").map(String::from),
        error: get_str(a, "stethoscope.tool.error").map(String::from),
    })
}

/// Persist an OTLP export request. Returns the number of spans ingested.
pub fn ingest_request(store: &Store, req: &ExportTraceServiceRequest) -> Result<usize> {
    let mut span_count = 0;

    for rs in &req.resource_spans {
        let res_attrs: &[KeyValue] = rs
            .resource
            .as_ref()
            .map(|r| r.attributes.as_slice())
            .unwrap_or(&[]);

        let project_name = get_str(res_attrs, "stethoscope.project")
            .or_else(|| get_str(res_attrs, "service.name"))
            .unwrap_or("default");
        let project_id = store.ensure_project(project_name)?;
        let framework = get_str(res_attrs, "stethoscope.framework")
            .map(String::from);
        let framework_version =
            get_str(res_attrs, "stethoscope.framework_version").map(String::from);

        // Group spans by trace so we can write an aggregated trace row.
        let mut by_trace: HashMap<String, Vec<&OtelSpan>> = HashMap::new();
        for ss in &rs.scope_spans {
            for sp in &ss.spans {
                by_trace
                    .entry(hex::encode(&sp.trace_id))
                    .or_default()
                    .push(sp);
            }
        }

        for (trace_id, spans) in by_trace {
            // Map once; aggregate in pass 1, write in pass 2. The trace row
            // must be inserted before its spans (spans.trace_id FK).
            let pairs: Vec<(&OtelSpan, NewSpan)> = spans
                .iter()
                .map(|sp| (*sp, map_span(&trace_id, sp)))
                .collect();

            let mut min_start = u64::MAX;
            let mut max_end = 0u64;
            let mut any_error = false;
            let mut cost = 0.0;
            let mut tin = 0i64;
            let mut tout = 0i64;
            let mut root_name: Option<String> = None;
            let mut parent_trace_id: Option<String> = None;
            let mut branch_point: Option<String> = None;

            for (sp, mapped) in &pairs {
                if sp.start_time_unix_nano != 0 {
                    min_start = min_start.min(sp.start_time_unix_nano);
                }
                max_end = max_end.max(sp.end_time_unix_nano);
                any_error |= mapped.status == "error";
                cost += mapped.cost_usd.unwrap_or(0.0);
                tin += mapped.tokens_in.unwrap_or(0);
                tout += mapped.tokens_out.unwrap_or(0);
                if sp.parent_span_id.is_empty() {
                    root_name = Some(sp.name.clone());
                }
                if let Some(p) = get_str(&sp.attributes, "stethoscope.parent_trace_id") {
                    parent_trace_id = Some(p.to_string());
                }
                if let Some(b) =
                    get_str(&sp.attributes, "stethoscope.branch_point_span_id")
                {
                    branch_point = Some(b.to_string());
                }
            }

            let status = if any_error {
                trace_status::FAILED
            } else {
                trace_status::COMPLETED
            };

            store.upsert_trace(&NewTrace {
                id: trace_id.clone(),
                project_id: project_id.clone(),
                parent_trace_id,
                branch_point_span_id: branch_point,
                label: root_name,
                status: status.into(),
                started_at: ts(if min_start == u64::MAX { 0 } else { min_start })
                    .unwrap_or_else(Utc::now),
                ended_at: ts(max_end),
                total_cost_usd: (cost > 0.0).then_some(cost),
                total_tokens_in: (tin > 0).then_some(tin),
                total_tokens_out: (tout > 0).then_some(tout),
                agent_framework: framework.clone(),
                framework_version: framework_version.clone(),
                metadata_json: None,
            })?;

            for (sp, mapped) in &pairs {
                store.upsert_span(mapped)?;
                for m in extract_messages(&mapped.id, &sp.attributes) {
                    store.insert_message(&m)?;
                }
                if mapped.kind == span_kind::TOOL_CALL {
                    if let Some(tc) = extract_tool_call(&mapped.id, &sp.attributes) {
                        store.insert_tool_call(&tc)?;
                    }
                }
                // Replay cache (PRD 7.3): pin deterministic LLM responses.
                if mapped.kind == span_kind::LLM_CALL {
                    if let Some(hash) = &mapped.prompt_hash {
                        if let Some(resp) =
                            get_str(&sp.attributes, "gen_ai.completion.0.content")
                        {
                            store.upsert_llm_cache(&LlmCacheEntry {
                                prompt_hash: hash.clone(),
                                model: mapped.model.clone(),
                                response_ref: resp.to_string(),
                                tokens_in: mapped.tokens_in,
                                tokens_out: mapped.tokens_out,
                                captured_at: mapped
                                    .started_at
                                    .unwrap_or_else(Utc::now),
                            })?;
                        }
                    }
                }
                span_count += 1;
            }
        }
    }

    Ok(span_count)
}
