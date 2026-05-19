import { useStore } from "../store";

// PRD 8.4 toolbar mockup:
// [▶][⏸][⏭][⏮] | [○ break][→ step][↓ into][↑ out] | Project: agent_v3 ▼
export function Toolbar() {
  const project = useStore((s) => s.project);
  return (
    <div className="toolbar">
      <span className="grp">
        <button className="btn" title="run">▶</button>
        <button className="btn" title="pause">⏸</button>
        <button className="btn" title="step over">⏭</button>
        <button className="btn" title="restart">⏮</button>
      </span>
      <span className="divider" />
      <span className="grp">
        <button className="btn" title="breakpoint">○ break</button>
        <button className="btn" title="step">→ step</button>
        <button className="btn" title="step into">↓ into</button>
        <button className="btn" title="step out">↑ out</button>
      </span>
      <span className="divider" />
      <span className="proj">
        Project: {project} <span className="raised" style={{ padding: "0 3px" }}>▼</span>
      </span>
      <span className="spacer" />
    </div>
  );
}
