import { Cursor } from "../Splash";

// PRD 8.5.4 — bottom-center. Token-by-token replay with hard 500ms cursor
// and a blocky inter-token latency histogram. Phase 2: controls + empty.
export function TokenStream() {
  return (
    <div className="pane" style={{ height: "100%" }}>
      <div className="pane-title">
        <span>TOKEN STREAM</span>
        <span>
          <button className="btn">▶ replay 1x</button> <button className="btn">2x</button>{" "}
          <button className="btn">10x</button>
          &nbsp;&nbsp;0 / 0 tokens
        </span>
      </div>
      <div className="pane-body" style={{ display: "flex", flexDirection: "column" }}>
        <div style={{ flex: 1, color: "var(--chrome-dark)" }}>
          (no token stream — select an llm span)
          <Cursor />
        </div>
        <div className="sunken" style={{ height: 22, color: "var(--chrome-dark)", padding: 2 }}>
          ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁ inter-token latency
        </div>
      </div>
    </div>
  );
}
