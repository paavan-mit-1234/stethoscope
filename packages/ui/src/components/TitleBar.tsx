// Custom title bar (PRD 8.4). Tauri runs with native decorations off and
// renders this instead. Display (pixel) font per PRD 8.3.
export function TitleBar() {
  return (
    <div className="titlebar">
      <span className="t-title">Stethoscope</span>
      <span className="t-btns">
        <span className="t-btn">_</span>
        <span className="t-btn">□</span>
        <span className="t-btn">X</span>
      </span>
    </div>
  );
}
