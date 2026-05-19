import { useMemo, useState } from "react";
import { useStore } from "../../store";
import { DiffView } from "./DiffView";

// PRD 8.5.2 — center. Tabs as raised buttons; active sits 1px up. Wired to
// the selected span (Phase 3). Diff is Phase 6.
const TABS = ["Messages", "Tool I/O", "Attributes", "Raw JSON", "Diff"];

function Card({ title, body }: { title: string; body: string }) {
  return (
    <div className="sunken" style={{ margin: "0 0 6px", background: "var(--canvas)" }}>
      <div
        style={{
          background: "var(--chrome)",
          padding: "1px 6px",
          fontSize: 12,
          letterSpacing: 1,
          textTransform: "uppercase",
        }}
      >
        {title}
      </div>
      <pre style={{ margin: 0, padding: 6, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {body}
      </pre>
    </div>
  );
}

export function Inspector() {
  const [active, setActive] = useState(0);
  const spans = useStore((s) => s.spans);
  const selectedSpanId = useStore((s) => s.selectedSpanId);
  const messages = useStore((s) => s.messages);
  const toolCall = useStore((s) => s.toolCall);
  const openBranch = useStore((s) => s.openBranch);
  const diffActive = useStore((s) => s.diff.active);

  const span = useMemo(
    () => spans.find((s) => s.id === selectedSpanId) ?? null,
    [spans, selectedSpanId],
  );

  const attributes = useMemo(() => {
    if (!span?.attributes_json) return {};
    try {
      return JSON.parse(span.attributes_json) as Record<string, unknown>;
    } catch {
      return {};
    }
  }, [span]);

  // Diff replaces the Inspector while active (PRD 9.4).
  if (diffActive) return <DiffView />;

  return (
    <div className="pane" style={{ flex: 1 }}>
      <div className="pane-title">
        <span>INSPECTOR</span>
        <span>{span ? `${span.kind} · ${span.name}` : ""}</span>
      </div>
      <div style={{ display: "flex", gap: 2, padding: "3px 3px 0", background: "var(--chrome)" }}>
        {TABS.map((t, i) => (
          <button
            key={t}
            className="btn"
            onClick={() => setActive(i)}
            style={{
              transform: i === active ? "translateY(-1px)" : undefined,
              background: i === active ? "var(--canvas)" : "var(--chrome)",
            }}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="pane-body" style={{ marginTop: 0 }}>
        {!span ? (
          <div className="empty">(select a span in the trace tree to inspect)</div>
        ) : active === 0 ? (
          messages.length === 0 ? (
            <div className="empty">(no messages on this span)</div>
          ) : (
            messages.map((m) => (
              <Card key={m.id} title={m.role} body={m.content_inline ?? "(payload in Parquet)"} />
            ))
          )
        ) : active === 1 ? (
          !toolCall ? (
            <div className="empty">(not a tool call)</div>
          ) : (
            <>
              <Card title="tool" body={toolCall.tool_name} />
              <Card title="arguments" body={toolCall.arguments_inline ?? "—"} />
              <Card title="result" body={toolCall.result_inline ?? "—"} />
              {toolCall.error && <Card title="error" body={toolCall.error} />}
              {span && (
                <button
                  className="btn"
                  onClick={() => openBranch(span.id)}
                  style={{ marginTop: 4 }}
                >
                  ⟲ Branch from here…
                </button>
              )}
            </>
          )
        ) : active === 2 ? (
          Object.keys(attributes).length === 0 ? (
            <div className="empty">(no attributes)</div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <tbody>
                {Object.entries(attributes).map(([k, v]) => (
                  <tr key={k}>
                    <td
                      style={{
                        color: "var(--signal-blue)",
                        verticalAlign: "top",
                        padding: "1px 8px 1px 0",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {k}
                    </td>
                    <td style={{ wordBreak: "break-word" }}>
                      {typeof v === "string" ? v : JSON.stringify(v)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : active === 3 ? (
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {JSON.stringify({ span, messages, toolCall }, null, 2)}
          </pre>
        ) : (
          <div className="empty">(diff view — Phase 6)</div>
        )}
      </div>
      {span && (
        <div
          style={{
            background: "var(--chrome)",
            fontSize: 12,
            padding: "2px 6px",
            display: "flex",
            gap: 14,
          }}
        >
          <span>in {span.tokens_in ?? 0}</span>
          <span>out {span.tokens_out ?? 0}</span>
          <span>${(span.cost_usd ?? 0).toFixed(4)}</span>
          <span>{span.duration_ms ?? 0}ms</span>
          {span.model && <span>{span.model}</span>}
          <span
            style={{ color: span.status === "error" ? "var(--signal-red)" : "var(--signal-green)" }}
          >
            {span.status}
          </span>
        </div>
      )}
    </div>
  );
}
