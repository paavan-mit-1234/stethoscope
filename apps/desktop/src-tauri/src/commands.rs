//! Canonical Tauri IPC surface (PRD 3.2, Phase 3). These mirror the
//! `tools/ref_ingest` HTTP routes 1:1, so the UI's data layer swaps transport
//! (fetch -> invoke) without touching components.
//!
//! Scaffolded for when the Rust toolchain is available; not compiled here.

use std::sync::Mutex;

use stethoscope_store::{
    BreakpointRow, MessageRow, SpanRow, Store, ToolCallRow, TraceRow,
};

/// Tauri-managed application state: the shared trace store.
pub struct AppState {
    pub store: Mutex<Store>,
}

type R<T> = Result<T, String>;

fn lock(state: &AppState) -> R<std::sync::MutexGuard<'_, Store>> {
    state.store.lock().map_err(|_| "store mutex poisoned".to_string())
}

#[tauri::command]
pub fn list_projects(state: tauri::State<AppState>) -> R<Vec<(String, String)>> {
    lock(&state)?.list_projects().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_traces(
    state: tauri::State<AppState>,
    project_id: Option<String>,
) -> R<Vec<TraceRow>> {
    lock(&state)?
        .list_traces(project_id.as_deref())
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_spans(state: tauri::State<AppState>, trace_id: String) -> R<Vec<SpanRow>> {
    lock(&state)?.get_spans(&trace_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_span(
    state: tauri::State<AppState>,
    span_id: String,
) -> R<Option<SpanRow>> {
    lock(&state)?.get_span(&span_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_messages(
    state: tauri::State<AppState>,
    span_id: String,
) -> R<Vec<MessageRow>> {
    lock(&state)?.get_messages(&span_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_tool_call(
    state: tauri::State<AppState>,
    span_id: String,
) -> R<Option<ToolCallRow>> {
    lock(&state)?.get_tool_call(&span_id).map_err(|e| e.to_string())
}

// ---- breakpoints + export (Phase 7) ---------------------------------

/// Set a breakpoint (PRD 4.3). Validates the predicate via the canonical
/// `stethoscope-breakpoint` grammar before persisting.
#[tauri::command]
pub fn set_breakpoint(
    state: tauri::State<AppState>,
    name: Option<String>,
    condition_dsl: String,
    project_id: String,
) -> R<String> {
    stethoscope_breakpoint::parse(&condition_dsl)
        .map_err(|e| format!("bad predicate: {e}"))?;
    lock(&state)?
        .add_breakpoint(&project_id, name.as_deref(), &condition_dsl)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_breakpoints(state: tauri::State<AppState>) -> R<Vec<BreakpointRow>> {
    lock(&state)?.list_breakpoints().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_breakpoint(state: tauri::State<AppState>, id: String) -> R<()> {
    lock(&state)?.delete_breakpoint(&id).map_err(|e| e.to_string())
}

/// Export a `.steth` portable bundle (PRD 4.11): trace + spans + messages +
/// tool calls + replay cache. The runnable equivalent today is the Python
/// `GET /traces/<id>/export` route.
#[tauri::command]
pub fn export_steth(
    state: tauri::State<AppState>,
    trace_id: String,
) -> R<serde_json::Value> {
    let s = lock(&state)?;
    let spans = s.get_spans(&trace_id).map_err(|e| e.to_string())?;
    let mut messages = serde_json::Map::new();
    let mut tool_calls = serde_json::Map::new();
    for sp in &spans {
        if let Ok(ms) = s.get_messages(&sp.id) {
            if !ms.is_empty() {
                messages.insert(sp.id.clone(), serde_json::to_value(ms).unwrap());
            }
        }
        if let Ok(Some(tc)) = s.get_tool_call(&sp.id) {
            tool_calls.insert(sp.id.clone(), serde_json::to_value(tc).unwrap());
        }
    }
    Ok(serde_json::json!({
        "steth_version": 1,
        "trace_id": trace_id,
        "spans": spans,
        "messages": messages,
        "tool_calls": tool_calls,
    }))
}

/// Diff two traces (PRD 4.5). Canonical path; the runnable equivalent today
/// is the TS mirror in packages/ui/src/data/diff.ts.
#[tauri::command]
pub fn diff_traces(
    state: tauri::State<AppState>,
    trace_a: String,
    trace_b: String,
) -> R<Vec<stethoscope_diff::AlignedPair>> {
    let s = lock(&state)?;
    let a = s.get_spans(&trace_a).map_err(|e| e.to_string())?;
    let b = s.get_spans(&trace_b).map_err(|e| e.to_string())?;
    Ok(stethoscope_diff::align_spans(&a, &b))
}

/// Branch + replay (PRD 4.4). Canonical path: Docker runtime. The runnable
/// equivalent today is the Python `POST /branch` route in tools/ref_ingest.
#[tauri::command]
pub fn branch(
    source_trace_id: String,
    branch_point_span_id: String,
    mutation: stethoscope_replay::Mutation,
) -> R<stethoscope_replay::ReplayOutcome> {
    let spec = stethoscope_replay::BranchSpec {
        source_trace_id,
        branch_point_span_id,
        mutation,
    };
    stethoscope_replay::replay_from(&spec, stethoscope_replay::ReplayRuntime::Docker)
        .map_err(|e| e.to_string())
}
