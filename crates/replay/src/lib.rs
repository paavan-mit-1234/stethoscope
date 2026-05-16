//! Deterministic replay orchestrator (PRD section 3.2, Phase 5).
//!
//! Reconstructs the execution context for a chosen span, pins LLM calls via
//! the replay cache (deterministic by default), applies a mutation, and
//! re-runs from that point as a new branch trace.
//!
//! This crate defines the stable API surface; the sandbox runtime
//! (Docker/venv) lands in Phase 5. Calls currently return
//! [`ReplayError::NotImplemented`] so the workspace builds and downstream
//! code can integrate against the final types.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ReplayError {
    #[error("replay sandbox not yet implemented (Phase 5)")]
    NotImplemented,
    #[error("span {0} not found")]
    SpanNotFound(String),
}

/// What the user edited before re-running (PRD section 4.4).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Mutation {
    UserMessage(String),
    SystemPrompt(String),
    ToolResponse { span_id: String, result: String },
    StateValue { key: String, value: serde_json::Value },
    ModelParam { name: String, value: serde_json::Value },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BranchSpec {
    pub source_trace_id: String,
    pub branch_point_span_id: String,
    pub mutation: Mutation,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplayOutcome {
    pub new_trace_id: String,
    pub span_count: usize,
}

/// Structural prompt hash used as the [`stethoscope_store`] `llm_cache` key
/// (PRD section 7.3): `sha256(model + system + messages + params)`.
pub fn prompt_hash(model: &str, system: &str, messages: &str, params: &str) -> String {
    let mut h = Sha256::new();
    h.update(model.as_bytes());
    h.update(b"\0");
    h.update(system.as_bytes());
    h.update(b"\0");
    h.update(messages.as_bytes());
    h.update(b"\0");
    h.update(params.as_bytes());
    hex::encode(h.finalize())
}

/// Replay `spec` in a sandbox, returning the new branch trace.
pub fn replay_from(_spec: &BranchSpec) -> Result<ReplayOutcome, ReplayError> {
    Err(ReplayError::NotImplemented)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prompt_hash_is_stable_and_sensitive() {
        let a = prompt_hash("claude", "sys", "msgs", "p");
        assert_eq!(a, prompt_hash("claude", "sys", "msgs", "p"));
        assert_ne!(a, prompt_hash("claude", "sys", "msgs", "p2"));
        assert_eq!(a.len(), 64);
    }
}
