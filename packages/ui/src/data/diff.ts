// Trace diff (Phase 6) — mirrors crates/diff: LCS over the pre-ordered span
// list keyed by (kind,name); aligned pairs whose status/attributes diverged
// are flagged. Plus a word-level text diff for the "why" inspector.

import type { Span } from "./api";
import { preorder } from "./nav";

export type AlignKind = "equal" | "changed" | "removed" | "added";
export type AlignedPair = { kind: AlignKind; a: Span | null; b: Span | null };

const key = (s: Span) => `${s.kind} ${s.name}`;

// Replay bookkeeping is set on branch roots, not a meaningful divergence —
// ignore it so "first divergence" lands on the real change.
const IGNORE = new Set([
  "stethoscope.parent_trace_id",
  "stethoscope.branch_point_span_id",
]);

function attrsKey(json: string | null): string {
  if (!json) return "";
  try {
    const o = JSON.parse(json) as Record<string, unknown>;
    for (const k of IGNORE) delete o[k];
    return JSON.stringify(
      Object.keys(o)
        .sort()
        .reduce<Record<string, unknown>>((acc, k) => {
          acc[k] = o[k];
          return acc;
        }, {}),
    );
  } catch {
    return json;
  }
}

const diverged = (a: Span, b: Span) =>
  a.status !== b.status ||
  attrsKey(a.attributes_json) !== attrsKey(b.attributes_json);

export function alignSpans(aSpans: Span[], bSpans: Span[]): AlignedPair[] {
  const a = preorder(aSpans);
  const b = preorder(bSpans);
  const n = a.length;
  const m = b.length;
  // LCS DP on (kind,name).
  const dp: number[][] = Array.from({ length: n + 1 }, () =>
    new Array(m + 1).fill(0),
  );
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] =
        key(a[i]) === key(b[j])
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: AlignedPair[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (key(a[i]) === key(b[j])) {
      out.push({
        kind: diverged(a[i], b[j]) ? "changed" : "equal",
        a: a[i],
        b: b[j],
      });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ kind: "removed", a: a[i], b: null });
      i++;
    } else {
      out.push({ kind: "added", a: null, b: b[j] });
      j++;
    }
  }
  while (i < n) out.push({ kind: "removed", a: a[i++], b: null });
  while (j < m) out.push({ kind: "added", a: null, b: b[j++] });
  return out;
}

export function firstDivergence(pairs: AlignedPair[]): number {
  return pairs.findIndex((p) => p.kind !== "equal");
}

export type Seg = { op: "=" | "-" | "+"; text: string };

// Word-level LCS diff (mirrors crates/diff::word_diff via `similar`).
export function wordDiff(a: string, b: string): Seg[] {
  const aw = a.split(/(\s+)/).filter((x) => x !== "");
  const bw = b.split(/(\s+)/).filter((x) => x !== "");
  const n = aw.length;
  const m = bw.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () =>
    new Array(m + 1).fill(0),
  );
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] =
        aw[i] === bw[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);

  const segs: Seg[] = [];
  const push = (op: Seg["op"], text: string) => {
    const last = segs[segs.length - 1];
    if (last && last.op === op) last.text += text;
    else segs.push({ op, text });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (aw[i] === bw[j]) {
      push("=", aw[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push("-", aw[i++]);
    } else {
      push("+", bw[j++]);
    }
  }
  while (i < n) push("-", aw[i++]);
  while (j < m) push("+", bw[j++]);
  return segs;
}
