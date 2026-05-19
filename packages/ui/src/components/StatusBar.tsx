import { useStore } from "../store";

// PRD 8.4 — always-visible status bar. Live ingestion/connection indicator
// (PRD 8.6: status updates live here, never toasts).
export function StatusBar() {
  const connected = useStore((s) => s.connected);
  const traces = useStore((s) => s.traces);
  const selectedTraceId = useStore((s) => s.selectedTraceId);
  const project = useStore((s) => s.project);
  const frameworkVersion = useStore((s) => s.frameworkVersion);
  const bpHit = useStore((s) => s.bpHit);

  return (
    <div className="statusbar">
      <span className="cell">
        <span className={connected ? "led" : "led idle"}>⬤</span>
        &nbsp;
        {connected
          ? `connected · ${traces.length} trace(s)`
          : "ingestion offline (127.0.0.1:4318)"}
      </span>
      {bpHit && (
        <span className="cell" style={{ color: "var(--signal-red)" }}>
          ⚑ breakpoint {bpHit.name}
        </span>
      )}
      <span className="cell grow">
        {selectedTraceId ? `trace ${selectedTraceId.slice(0, 16)}` : "(no trace selected)"}
      </span>
      <span className="cell">project: {project}</span>
      <span className="cell">{frameworkVersion}</span>
      <span className="cell">mem 0 MB</span>
    </div>
  );
}
