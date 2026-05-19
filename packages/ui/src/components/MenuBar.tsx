// PRD 8.4 — menu bar. Stub menus (Phase 2 shell): hover highlight only,
// no dropdowns yet. Order matches the PRD mockup exactly.
const MENUS = [
  "File", "Edit", "View", "Trace", "Run", "Debug", "Window", "Help",
];

export function MenuBar() {
  return (
    <div className="menubar">
      {MENUS.map((m) => (
        <span key={m} className="m-item">
          {m}
        </span>
      ))}
    </div>
  );
}
