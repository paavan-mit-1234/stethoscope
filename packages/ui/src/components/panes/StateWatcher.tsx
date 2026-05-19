// PRD 8.5.3 — right top. Timeline scrubber (ASCII ⬛/⬜ checkpoints), state
// tree, watch expressions. Phase 2: empty scaffold.
export function StateWatcher() {
  return (
    <div className="pane" style={{ flex: 1 }}>
      <div className="pane-title">
        <span>STATE WATCHER</span>
      </div>
      <div className="pane-body" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div className="sunken" style={{ padding: 4, color: "var(--chrome-dark)" }}>
          ⬜⬜⬜⬜⬜⬜⬜&nbsp;&nbsp;history scrubber
        </div>
        <div className="empty" style={{ flex: 1 }}>(no state captured)</div>
        <div className="pane-title" style={{ background: "var(--chrome)", color: "var(--ink)" }}>
          WATCH EXPRESSIONS
        </div>
        <div className="empty">(no watch expressions — add one with `watch &lt;expr&gt;`)</div>
      </div>
    </div>
  );
}
