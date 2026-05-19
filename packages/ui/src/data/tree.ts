// Flatten a trace's spans (parent_span_id forest) into an ordered row list
// with ASCII tree prefixes, respecting collapsed nodes. Done once per
// spans/collapsed change so the virtualized list just slices the result.

import type { Span } from "./api";

export type SpanRowVM = {
  span: Span;
  depth: number;
  prefix: string; // "│  ├─ " style leader
  hasChildren: boolean;
};

export function buildSpanRows(
  spans: Span[],
  collapsed: ReadonlySet<string>,
): SpanRowVM[] {
  const childrenOf = new Map<string | null, Span[]>();
  const ids = new Set(spans.map((s) => s.id));
  for (const s of spans) {
    // a parent outside the set (shouldn't happen) is treated as a root
    const key =
      s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : null;
    const arr = childrenOf.get(key);
    if (arr) arr.push(s);
    else childrenOf.set(key, [s]);
  }

  const out: SpanRowVM[] = [];
  const walk = (parent: string | null, depth: number, ancestorsLast: boolean[]) => {
    const kids = childrenOf.get(parent) ?? [];
    kids.forEach((s, i) => {
      const last = i === kids.length - 1;
      let prefix = "";
      for (const al of ancestorsLast) prefix += al ? "   " : "│  ";
      if (depth > 0) prefix += last ? "└─ " : "├─ ";
      const hasChildren = (childrenOf.get(s.id) ?? []).length > 0;
      out.push({ span: s, depth, prefix, hasChildren });
      if (hasChildren && !collapsed.has(s.id)) {
        walk(s.id, depth + 1, [...ancestorsLast, last]);
      }
    });
  };
  walk(null, 0, []);
  return out;
}

// Single-char colored glyph per PRD 8.5.1.
export function spanGlyph(s: Span): { ch: string; color: string } {
  if (s.status === "error") return { ch: "★", color: "var(--signal-red)" };
  if (s.cacheable && (s.tokens_cached ?? 0) > 0)
    return { ch: "◐", color: "var(--signal-green)" };
  switch (s.kind) {
    case "llm_call":
      return { ch: "◆", color: "var(--signal-blue)" };
    case "tool_call":
      return { ch: "▣", color: "var(--signal-amber)" };
    case "node_execution":
      return { ch: "●", color: "var(--ink)" };
    case "routing_decision":
      return { ch: "◇", color: "var(--ink)" };
    case "user_message":
      return { ch: "▷", color: "var(--ink)" };
    case "sub_agent":
      return { ch: "◎", color: "var(--signal-blue)" };
    case "checkpoint":
      return { ch: "◍", color: "var(--chrome-dark)" };
    default:
      return { ch: "•", color: "var(--ink)" };
  }
}
