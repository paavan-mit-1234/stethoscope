import { useStore } from "../store";

// PRD 4.4 + 8.6 — branch dialog as a Win32 message box. No transparency tint
// (the backdrop is an invisible click-capture layer); no rounded corners;
// text progress bar while replaying, never a spinner.
const MUTATIONS = [
  ["tool_response", "Tool response", true],
  ["user_message", "User message", false],
  ["system_prompt", "System prompt", false],
  ["state_value", "State value", false],
  ["model_param", "Model parameter", false],
] as const;

export function BranchModal() {
  const bm = useStore((s) => s.branchModal);
  const setBranchValue = useStore((s) => s.setBranchValue);
  const confirmBranch = useStore((s) => s.confirmBranch);
  const closeBranch = useStore((s) => s.closeBranch);

  if (!bm.open) return null;

  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 1000 }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !bm.busy) closeBranch();
      }}
    >
      <div
        className="raised-2"
        role="dialog"
        style={{
          position: "absolute",
          top: "28%",
          left: "50%",
          transform: "translateX(-50%)",
          width: 520,
          background: "var(--window-bg)",
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape" && !bm.busy) closeBranch();
        }}
      >
        <div className="pane-title">
          <span>Branch from here</span>
          <span
            className="t-btn"
            onClick={() => !bm.busy && closeBranch()}
            style={{ cursor: "default" }}
          >
            X
          </span>
        </div>

        <div style={{ padding: 10, display: "flex", flexDirection: "column", gap: 8 }}>
          <div>
            Replay from tool span{" "}
            <b>{bm.toolName ?? "?"}</b> with one mutated input. Everything else
            is pinned (LLM via cache, other tools snapshotted) so the only
            variable is your edit.
          </div>

          <fieldset className="sunken" style={{ border: "1px solid", padding: 6 }}>
            <legend style={{ padding: "0 4px" }}>Mutation</legend>
            {MUTATIONS.map(([id, label, enabled]) => (
              <label
                key={id}
                style={{
                  display: "block",
                  color: enabled ? "var(--ink)" : "var(--chrome-dark)",
                }}
              >
                <input
                  type="radio"
                  name="mut"
                  defaultChecked={enabled}
                  disabled={!enabled}
                />{" "}
                {label}
                {!enabled && "  (later phase)"}
              </label>
            ))}
          </fieldset>

          <div>tool response (JSON):</div>
          <textarea
            className="sunken"
            value={bm.value}
            spellCheck={false}
            disabled={bm.busy}
            onChange={(e) => setBranchValue(e.target.value)}
            style={{
              height: 110,
              font: "inherit",
              background: "var(--canvas)",
              padding: 6,
              outline: "none",
              border: "none",
              resize: "none",
            }}
          />

          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ flex: 1, color: "var(--signal-blue)" }}>
              {bm.busy ? "[████████░░] replaying…" : ""}
            </span>
            <button className="btn" disabled={bm.busy} onClick={() => confirmBranch()}>
              OK
            </button>
            <button className="btn" disabled={bm.busy} onClick={() => closeBranch()}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
