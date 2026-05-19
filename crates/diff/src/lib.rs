//! Trace diff (PRD 4.5 / 6.1). Custom span-tree alignment + `similar` for
//! text. The runnable equivalent today is the TS mirror
//! `packages/ui/src/data/diff.ts`; both align spans by an LCS over the
//! pre-order span list keyed by `(kind, name)`, then mark aligned pairs
//! whose content diverged.

use serde::{Deserialize, Serialize};
use stethoscope_store::SpanRow;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AlignKind {
    /// Aligned, content identical.
    Equal,
    /// Aligned, but status/attributes/result diverged (highlight amber).
    Changed,
    /// Present only in A.
    Removed,
    /// Present only in B.
    Added,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AlignedPair {
    pub kind: AlignKind,
    pub a: Option<SpanRow>,
    pub b: Option<SpanRow>,
}

fn key(s: &SpanRow) -> (String, String) {
    (s.kind.clone(), s.name.clone())
}

// Replay bookkeeping is set on branch roots; not a meaningful divergence.
const IGNORE_ATTRS: [&str; 2] = [
    "stethoscope.parent_trace_id",
    "stethoscope.branch_point_span_id",
];

fn attrs_key(json: &Option<String>) -> String {
    let Some(j) = json else { return String::new() };
    match serde_json::from_str::<serde_json::Value>(j) {
        Ok(serde_json::Value::Object(mut m)) => {
            for k in IGNORE_ATTRS {
                m.remove(k);
            }
            // BTreeMap-style stable ordering for comparison.
            let sorted: std::collections::BTreeMap<_, _> = m.into_iter().collect();
            serde_json::to_string(&sorted).unwrap_or_default()
        }
        _ => j.clone(),
    }
}

fn content_diverged(a: &SpanRow, b: &SpanRow) -> bool {
    a.status != b.status || attrs_key(&a.attributes_json) != attrs_key(&b.attributes_json)
}

/// Align two pre-ordered span lists via LCS on `(kind, name)`. Spans in the
/// LCS become `Equal`/`Changed` pairs; the rest are `Removed`/`Added`.
pub fn align_spans(a: &[SpanRow], b: &[SpanRow]) -> Vec<AlignedPair> {
    let n = a.len();
    let m = b.len();
    // LCS DP table.
    let mut dp = vec![vec![0usize; m + 1]; n + 1];
    for i in (0..n).rev() {
        for j in (0..m).rev() {
            dp[i][j] = if key(&a[i]) == key(&b[j]) {
                dp[i + 1][j + 1] + 1
            } else {
                dp[i + 1][j].max(dp[i][j + 1])
            };
        }
    }
    let mut out = Vec::new();
    let (mut i, mut j) = (0, 0);
    while i < n && j < m {
        if key(&a[i]) == key(&b[j]) {
            let (sa, sb) = (a[i].clone(), b[j].clone());
            let kind = if content_diverged(&sa, &sb) {
                AlignKind::Changed
            } else {
                AlignKind::Equal
            };
            out.push(AlignedPair { kind, a: Some(sa), b: Some(sb) });
            i += 1;
            j += 1;
        } else if dp[i + 1][j] >= dp[i][j + 1] {
            out.push(AlignedPair { kind: AlignKind::Removed, a: Some(a[i].clone()), b: None });
            i += 1;
        } else {
            out.push(AlignedPair { kind: AlignKind::Added, a: None, b: Some(b[j].clone()) });
            j += 1;
        }
    }
    while i < n {
        out.push(AlignedPair { kind: AlignKind::Removed, a: Some(a[i].clone()), b: None });
        i += 1;
    }
    while j < m {
        out.push(AlignedPair { kind: AlignKind::Added, a: None, b: Some(b[j].clone()) });
        j += 1;
    }
    out
}

/// Index of the first non-`Equal` pair ("first divergence" jump, PRD 9.4).
pub fn first_divergence(pairs: &[AlignedPair]) -> Option<usize> {
    pairs.iter().position(|p| p.kind != AlignKind::Equal)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Seg {
    pub op: char, // '=', '-', '+'
    pub text: String,
}

/// Word-level text diff for the "why did they diverge" inspector (PRD 4.5).
pub fn word_diff(a: &str, b: &str) -> Vec<Seg> {
    use similar::{ChangeTag, TextDiff};
    let diff = TextDiff::from_words(a, b);
    diff
        .iter_all_changes()
        .map(|c| Seg {
            op: match c.tag() {
                ChangeTag::Equal => '=',
                ChangeTag::Delete => '-',
                ChangeTag::Insert => '+',
            },
            text: c.value().to_string(),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn span(kind: &str, name: &str, status: &str) -> SpanRow {
        SpanRow {
            id: name.into(),
            trace_id: "t".into(),
            parent_span_id: None,
            kind: kind.into(),
            name: name.into(),
            started_at: None,
            ended_at: None,
            duration_ms: None,
            status: status.into(),
            error_message: None,
            cost_usd: None,
            tokens_in: None,
            tokens_out: None,
            tokens_cached: None,
            model: None,
            provider: None,
            temperature: None,
            prompt_hash: None,
            cacheable: None,
            attributes_json: None,
        }
    }

    #[test]
    fn aligns_and_flags_divergence() {
        let a = vec![
            span("node_execution", "decide", "ok"),
            span("tool_call", "place_order", "error"),
        ];
        let b = vec![
            span("node_execution", "decide", "ok"),
            span("llm_call", "confirm", "ok"),
        ];
        let pairs = align_spans(&a, &b);
        assert_eq!(pairs[0].kind, AlignKind::Equal);
        // place_order only in A, confirm only in B
        assert!(pairs.iter().any(|p| p.kind == AlignKind::Removed));
        assert!(pairs.iter().any(|p| p.kind == AlignKind::Added));
        assert_eq!(first_divergence(&pairs), Some(1));
    }
}
