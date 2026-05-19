import { useEffect, useState } from "react";
import { api, type Span } from "../../data/api";
import { firstDivergence, wordDiff } from "../../data/diff";
import { useStore } from "../../store";

// PRD 4.5 / 9.4 — replaces the Inspector while a diff is active. Aligned
// pairs side-by-side; divergence amber; "first divergence" jump; word-level
// token diff of the selected pair (the "why did they diverge" inspector).

const ROW_BG: Record<string, string> = {
  equal: "transparent",
  changed: "var(--signal-amber)",
  removed: "var(--signal-red)",
  added: "var(--signal-green)",
};

async function salientText(span: Span | null): Promise<string> {
  if (!span) return "";
  if (span.kind === "tool_call") {
    const tc = await api.getToolCall(span.id);
    return tc?.result_inline ?? tc?.error ?? "";
  }
  if (span.kind === "llm_call") {
    const ms = await api.getMessages(span.id);
    const asst = ms.filter((m) => m.role === "assistant").pop();
    return asst?.content_inline ?? "";
  }
  return span.attributes_json ?? span.name;
}

function half(s: Span | null): string {
  return s ? `${s.name}  ·  ${s.status}` : "—";
}

export function DiffView() {
  const { active, aLabel, bLabel, pairs, sel } = useStore((s) => s.diff);
  const setDiffSel = useStore((s) => s.setDiffSel);
  const closeDiff = useStore((s) => s.closeDiff);
  const [seg, setSeg] = useState<{ op: string; text: string }[]>([]);

  useEffect(() => {
    if (!active) return;
    const pair = pairs[sel];
    if (!pair) {
      setSeg([]);
      return;
    }
    let live = true;
    Promise.all([salientText(pair.a), salientText(pair.b)]).then(([a, b]) => {
      if (live) setSeg(wordDiff(a, b));
    });
    return () => {
      live = false;
    };
  }, [active, pairs, sel]);

  if (!active) return null;

  return (
    <div className="pane" style={{ flex: 1 }}>
      <div className="pane-title">
        <span>
          DIFF&nbsp;&nbsp;{aLabel}&nbsp;&nbsp;⇄&nbsp;&nbsp;{bLabel}
        </span>
        <span>
          <button
            className="btn"
            onClick={() => setDiffSel(Math.max(0, firstDivergence(pairs)))}
          >
            ⌖ first divergence
          </button>{" "}
          <button className="btn" onClick={closeDiff}>
            ✕ close
          </button>
        </span>
      </div>
      <div className="pane-body" style={{ marginTop: 0, padding: 0, display: "flex", flexDirection: "column" }}>
        <div style={{ flex: 1, overflow: "auto" }}>
          {pairs.map((p, i) => {
            const onSel = i === sel;
            return (
              <div
                key={i}
                onClick={() => setDiffSel(i)}
                style={{
                  display: "flex",
                  borderBottom: "1px solid var(--chrome)",
                  outline: onSel ? "1px solid var(--ink)" : undefined,
                }}
              >
                <div
                  style={{
                    flex: 1,
                    padding: "1px 6px",
                    whiteSpace: "pre",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    background:
                      p.kind === "removed" || p.kind === "changed"
                        ? ROW_BG[p.kind]
                        : "transparent",
                    color:
                      p.kind === "removed" ? "var(--selection-text)" : undefined,
                  }}
                >
                  {half(p.a)}
                </div>
                <div style={{ width: 1, background: "var(--chrome-dark)" }} />
                <div
                  style={{
                    flex: 1,
                    padding: "1px 6px",
                    whiteSpace: "pre",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    background:
                      p.kind === "added" || p.kind === "changed"
                        ? ROW_BG[p.kind]
                        : "transparent",
                    color:
                      p.kind === "added" ? "var(--selection-text)" : undefined,
                  }}
                >
                  {half(p.b)}
                </div>
              </div>
            );
          })}
        </div>
        <div
          className="sunken"
          style={{ height: 120, margin: 2, background: "var(--canvas)", overflow: "auto", padding: 4 }}
        >
          <div style={{ color: "var(--chrome-dark)" }}>
            why diverged — token diff of selected pair:
          </div>
          <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {seg.length === 0 ? (
              <span className="empty">(identical / no content)</span>
            ) : (
              seg.map((s, i) => (
                <span
                  key={i}
                  style={{
                    color:
                      s.op === "-"
                        ? "var(--signal-red)"
                        : s.op === "+"
                          ? "var(--signal-green)"
                          : "var(--ink)",
                    textDecoration: s.op === "-" ? "line-through" : undefined,
                  }}
                >
                  {s.text}
                </span>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
