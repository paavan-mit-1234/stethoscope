// Pure navigation over a trace's span forest (Phase 4). Traverses the real
// execution tree regardless of UI collapse state. Mirrors the ordering used
// by the Trace Tree (children by started_at, then id).

import type { Span } from "./api";

function childrenMap(spans: Span[]): Map<string | null, Span[]> {
  const ids = new Set(spans.map((s) => s.id));
  const m = new Map<string | null, Span[]>();
  for (const s of spans) {
    const key =
      s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : null;
    (m.get(key) ?? m.set(key, []).get(key)!).push(s);
  }
  const cmp = (a: Span, b: Span) =>
    (a.started_at ?? "").localeCompare(b.started_at ?? "") ||
    a.id.localeCompare(b.id);
  for (const arr of m.values()) arr.sort(cmp);
  return m;
}

/** DFS pre-order — the linear execution order `next`/`prev` walk. */
export function preorder(spans: Span[]): Span[] {
  const m = childrenMap(spans);
  const out: Span[] = [];
  const walk = (parent: string | null) => {
    for (const s of m.get(parent) ?? []) {
      out.push(s);
      walk(s.id);
    }
  };
  walk(null);
  return out;
}

export function parentOf(spans: Span[], id: string): Span | null {
  const me = spans.find((s) => s.id === id);
  if (!me?.parent_span_id) return null;
  return spans.find((s) => s.id === me.parent_span_id) ?? null;
}

export function firstChild(spans: Span[], id: string): Span | null {
  return childrenMap(spans).get(id)?.[0] ?? null;
}

/** Root → span ancestor chain (inclusive), for `where`. */
export function pathTo(spans: Span[], id: string): Span[] {
  const out: Span[] = [];
  let cur = spans.find((s) => s.id === id) ?? null;
  const seen = new Set<string>();
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    out.unshift(cur);
    cur = cur.parent_span_id
      ? spans.find((s) => s.id === cur!.parent_span_id) ?? null
      : null;
  }
  return out;
}

type Move = { id: string } | { msg: string };

export function step(
  order: Span[],
  spans: Span[],
  current: string | null,
  kind: "next" | "prev" | "step" | "finish",
): Move {
  if (order.length === 0) return { msg: "(no spans — select a trace first)" };
  const i = current ? order.findIndex((s) => s.id === current) : -1;

  if (kind === "next") {
    if (i < 0) return { id: order[0].id };
    return i + 1 < order.length
      ? { id: order[i + 1].id }
      : { msg: "(end of trace)" };
  }
  if (kind === "prev") {
    if (i < 0) return { id: order[0].id };
    return i > 0 ? { id: order[i - 1].id } : { msg: "(top of trace)" };
  }
  if (kind === "step") {
    if (i < 0) return { id: order[0].id };
    const c = firstChild(spans, current!);
    if (c) return { id: c.id };
    // no child: behaves like `next` (gdb steps to the next line)
    return i + 1 < order.length
      ? { id: order[i + 1].id }
      : { msg: "(end of trace)" };
  }
  // finish: step out to parent
  if (i < 0 || !current) return { msg: "(no current span)" };
  const p = parentOf(spans, current);
  return p ? { id: p.id } : { msg: "(top of trace — no parent)" };
}
