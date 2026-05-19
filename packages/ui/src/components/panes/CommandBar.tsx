import { useEffect, useRef, useState } from "react";
import { useStore } from "../../store";
import { Cursor } from "../Splash";

// PRD 8.5.5 — the gdb-style REPL. Parsing + execution live in the store
// (shared with the global keybindings); this is just the terminal surface.
const COLOR: Record<string, string> = {
  in: "var(--ink)",
  out: "var(--ink)",
  info: "var(--signal-blue)",
  err: "var(--signal-red)",
};

export function CommandBar() {
  const scrollback = useStore((s) => s.scrollback);
  const history = useStore((s) => s.history);
  const submit = useStore((s) => s.submit);

  const [value, setValue] = useState("");
  const [hIdx, setHIdx] = useState(-1);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView();
  }, [scrollback]);

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      submit(value);
      setValue("");
      setHIdx(-1);
    } else if (e.key === "Escape") {
      inputRef.current?.blur(); // hand control to the gdb keybindings
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!history.length) return;
      const i = hIdx < 0 ? history.length - 1 : Math.max(0, hIdx - 1);
      setHIdx(i);
      setValue(history[i]);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (hIdx < 0) return;
      const i = hIdx + 1;
      if (i >= history.length) {
        setHIdx(-1);
        setValue("");
      } else {
        setHIdx(i);
        setValue(history[i]);
      }
    }
  };

  return (
    <div className="pane" style={{ height: "100%" }}>
      <div className="pane-title">
        <span>COMMAND</span>
      </div>
      <div className="pane-body" style={{ display: "flex", flexDirection: "column", padding: 4 }}>
        <div style={{ flex: 1, overflow: "auto" }}>
          {scrollback.map((l, i) => (
            <div key={i} style={{ color: COLOR[l.kind], whiteSpace: "pre-wrap" }}>
              {l.text}
            </div>
          ))}
          <div ref={endRef} />
        </div>
        <div style={{ display: "flex", alignItems: "center" }}>
          <span style={{ color: "var(--signal-green)" }}>(steth)&nbsp;</span>
          <input
            ref={inputRef}
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKey}
            spellCheck={false}
            style={{
              flex: 1,
              font: "inherit",
              color: "var(--ink)",
              background: "transparent",
              border: "none",
              outline: "none",
            }}
          />
          {value === "" && <Cursor />}
        </div>
      </div>
    </div>
  );
}
