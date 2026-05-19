import { useEffect, useMemo, useRef, useState } from "react";
import { buildSpanRows, spanGlyph } from "../../data/tree";
import { useStore } from "../../store";

// PRD 8.5.1 — left rail. Traces are roots; selecting one loads + expands its
// span subtree (ASCII tree, colored glyphs). Windowed render for 10k+ spans.
const ROW_H = 18;
const OVERSCAN = 8;

type Row =
  | { kind: "trace"; id: string; label: string; status: string; spans: number; branch: boolean }
  | {
      kind: "span";
      id: string;
      prefix: string;
      name: string;
      glyph: { ch: string; color: string };
      selected: boolean;
    };

export function TraceTree() {
  const traces = useStore((s) => s.traces);
  const spans = useStore((s) => s.spans);
  const selectedTraceId = useStore((s) => s.selectedTraceId);
  const selectedSpanId = useStore((s) => s.selectedSpanId);
  const selectTrace = useStore((s) => s.selectTrace);
  const selectSpan = useStore((s) => s.selectSpan);
  const pickForDiff = useStore((s) => s.pickForDiff);
  const diffPick = useStore((s) => s.diffPick);
  const heatmap = useStore((s) => s.heatmap);
  const cycleHeatmap = useStore((s) => s.cycleHeatmap);

  const heat = useMemo(() => {
    const m = new Map<string, string>();
    if (heatmap === "off") return m;
    const val = (sp: (typeof spans)[number]) =>
      heatmap === "lat" ? sp.duration_ms : sp.cost_usd;
    const vals = spans
      .map(val)
      .filter((v): v is number => typeof v === "number" && v > 0)
      .sort((a, b) => a - b);
    if (vals.length === 0) return m;
    const lo = vals[Math.floor(vals.length / 3)];
    const hi = vals[Math.floor((2 * vals.length) / 3)];
    for (const sp of spans) {
      const v = val(sp);
      if (typeof v !== "number" || v <= 0) continue;
      m.set(
        sp.id,
        v <= lo ? "var(--signal-green)" : v <= hi ? "var(--signal-amber)" : "var(--signal-red)",
      );
    }
    return m;
  }, [spans, heatmap]);

  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [scrollTop, setScrollTop] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  const rows: Row[] = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const out: Row[] = [];
    for (const t of traces) {
      const label = t.label ?? t.id.slice(0, 12);
      out.push({
        kind: "trace",
        id: t.id,
        label,
        status: t.status,
        spans: t.span_count,
        branch: t.is_branch,
      });
      if (t.id === selectedTraceId) {
        for (const vm of buildSpanRows(spans, collapsed)) {
          const name = vm.span.name;
          if (f && !name.toLowerCase().includes(f)) continue;
          out.push({
            kind: "span",
            id: vm.span.id,
            prefix: vm.prefix,
            name,
            glyph: spanGlyph(vm.span),
            selected: vm.span.id === selectedSpanId,
          });
        }
      }
    }
    return out;
  }, [traces, spans, selectedTraceId, selectedSpanId, collapsed, filter]);

  // Keep the cursor visible when command/keyboard nav moves it (the row may
  // be virtualized out of the DOM, so scroll by computed index).
  useEffect(() => {
    if (!selectedSpanId || !boxRef.current) return;
    const idx = rows.findIndex(
      (r) => r.kind === "span" && r.id === selectedSpanId,
    );
    if (idx < 0) return;
    const box = boxRef.current;
    const top = idx * ROW_H;
    if (top < box.scrollTop || top + ROW_H > box.scrollTop + box.clientHeight) {
      box.scrollTop = Math.max(0, top - box.clientHeight / 2);
    }
  }, [selectedSpanId, rows]);

  const viewH = boxRef.current?.clientHeight ?? 480;
  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const end = Math.min(rows.length, Math.ceil((scrollTop + viewH) / ROW_H) + OVERSCAN);
  const slice = rows.slice(start, end);

  return (
    <div className="pane" style={{ flexDirection: "column" }}>
      <div className="pane-title">
        <span>TRACE TREE</span>
        <span>
          {rows.length ? `${traces.length} trace(s)  ` : ""}
          <span
            onClick={cycleHeatmap}
            title="cost/latency heatmap (PRD 4.7)"
            style={{ cursor: "default" }}
          >
            [heat:{heatmap}]
          </span>
        </span>
      </div>
      <div
        ref={boxRef}
        className="pane-body"
        style={{ padding: 0, position: "relative" }}
        onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
      >
        {rows.length === 0 ? (
          <div className="empty">
            (no traces yet — run an instrumented agent to begin)
          </div>
        ) : (
          <div style={{ height: rows.length * ROW_H, position: "relative" }}>
            {slice.map((r, i) => {
              const idx = start + i;
              const isSel =
                r.kind === "span"
                  ? r.selected
                  : r.id === selectedTraceId && !selectedSpanId;
              return (
                <div
                  key={`${r.kind}:${r.id}:${idx}`}
                  data-tid={r.kind === "trace" ? r.id : undefined}
                  data-sid={r.kind === "span" ? r.id : undefined}
                  onClick={(e) => {
                    if (r.kind !== "trace") {
                      selectSpan(r.id);
                    } else if (e.shiftKey || e.ctrlKey || e.metaKey) {
                      pickForDiff(r.id);
                    } else {
                      selectTrace(r.id);
                    }
                  }}
                  onDoubleClick={() => {
                    if (r.kind !== "span") return;
                    setCollapsed((prev) => {
                      const next = new Set(prev);
                      next.has(r.id) ? next.delete(r.id) : next.add(r.id);
                      return next;
                    });
                  }}
                  style={{
                    position: "absolute",
                    top: idx * ROW_H,
                    left: 0,
                    right: 0,
                    height: ROW_H,
                    lineHeight: `${ROW_H}px`,
                    padding: "0 6px",
                    whiteSpace: "pre",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    background: isSel
                      ? "var(--selection)"
                      : r.kind === "span"
                        ? heat.get(r.id)
                        : undefined,
                    color: isSel ? "var(--selection-text)" : undefined,
                  }}
                >
                  {r.kind === "trace" ? (
                    <>
                      <span>{r.id === selectedTraceId ? "▾ " : "▸ "}</span>
                      {diffPick.includes(r.id) && (
                        <span style={{ color: isSel ? undefined : "var(--signal-amber)" }}>
                          [{diffPick.indexOf(r.id) === 0 ? "A" : "B"}]{" "}
                        </span>
                      )}
                      <span style={{ color: isSel ? undefined : "var(--signal-blue)" }}>
                        {r.branch ? "⟲" : "◆"}
                      </span>{" "}
                      {r.label}
                      <span style={{ color: isSel ? undefined : "var(--chrome-dark)" }}>
                        {"  "}
                        {r.status} · {r.spans} spans
                      </span>
                    </>
                  ) : (
                    <>
                      <span style={{ color: "var(--chrome-dark)" }}>{r.prefix}</span>
                      <span style={{ color: isSel ? undefined : r.glyph.color }}>
                        {r.glyph.ch}
                      </span>{" "}
                      {r.name}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div style={{ color: "var(--chrome-dark)", fontSize: 12, padding: 4, background: "var(--chrome)" }}>
        ◆ llm&nbsp;&nbsp;▣ tool&nbsp;&nbsp;● node&nbsp;&nbsp;★ error&nbsp;&nbsp;⟲ branch&nbsp;&nbsp;◐ cache
      </div>
      <div style={{ padding: 2, background: "var(--chrome)" }}>
        <input
          className="sunken"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="filter spans ▼"
          style={{
            width: "100%",
            font: "inherit",
            background: "var(--canvas)",
            padding: "2px 4px",
            outline: "none",
            border: "none",
          }}
        />
      </div>
    </div>
  );
}
