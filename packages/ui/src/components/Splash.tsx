import { useEffect, useState } from "react";
import { useStore } from "../store";

// PRD 8.8 — 1.5s splash, black bg, pixel wordmark in green phosphor,
// LOADING lines drawn line-by-line, then "PRESS ANY KEY TO BEGIN".
// No gradients/transparency (PRD 8.2) so no CRT scanline overlay.

const LINES = [
  "LOADING TRACE STORE.........[ OK ]",
  "LOADING REPLAY ENGINE.......[ OK ]",
  "LOADING WORKBENCH...........[ OK ]",
];

export function Splash() {
  const dismiss = useStore((s) => s.dismissSplash);
  const [shown, setShown] = useState(0);

  useEffect(() => {
    const timers = LINES.map((_, i) =>
      window.setTimeout(() => setShown(i + 1), 250 + i * 280),
    );
    const auto = window.setTimeout(dismiss, 1500);
    const key = () => dismiss();
    window.addEventListener("keydown", key);
    window.addEventListener("mousedown", key);
    return () => {
      timers.forEach(clearTimeout);
      clearTimeout(auto);
      window.removeEventListener("keydown", key);
      window.removeEventListener("mousedown", key);
    };
  }, [dismiss]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "#000",
        color: "var(--phosphor)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 14,
      }}
    >
      <div style={{ fontFamily: "var(--display)", fontSize: 28, letterSpacing: 2 }}>
        STETHOSCOPE
      </div>
      <div style={{ fontFamily: "var(--display)", fontSize: 9, letterSpacing: 1 }}>
        A TIME-TRAVEL DEBUGGER FOR AGENTS
      </div>
      <div style={{ fontFamily: "var(--mono)", fontSize: 12 }}>
        v1.0.0 — © Paavan Sejpal 2026
      </div>
      <pre
        style={{
          fontFamily: "var(--mono)",
          fontSize: 13,
          lineHeight: 1.5,
          margin: "10px 0 0",
          minHeight: 72,
        }}
      >
        {LINES.slice(0, shown).join("\n")}
      </pre>
      <div style={{ fontFamily: "var(--mono)", fontSize: 13, height: 16 }}>
        {shown >= LINES.length && (
          <>
            PRESS ANY KEY TO BEGIN<Cursor />
          </>
        )}
      </div>
    </div>
  );
}

// Hard 500ms toggle, no smooth fade (PRD 8.5.4).
export function Cursor() {
  const [on, setOn] = useState(true);
  useEffect(() => {
    const id = window.setInterval(() => setOn((v) => !v), 500);
    return () => clearInterval(id);
  }, []);
  return <span style={{ visibility: on ? "visible" : "hidden" }}>█</span>;
}
