import { useEffect, useState } from "react";
import { useStore } from "../store";
import { BranchModal } from "./BranchModal";
import { MenuBar } from "./MenuBar";
import { Splitter } from "./Splitter";
import { StatusBar } from "./StatusBar";
import { TitleBar } from "./TitleBar";
import { Toolbar } from "./Toolbar";
import { CommandBar } from "./panes/CommandBar";
import { Inspector } from "./panes/Inspector";
import { StateWatcher } from "./panes/StateWatcher";
import { TokenStream } from "./panes/TokenStream";
import { TraceTree } from "./panes/TraceTree";

const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v));

// PRD 8.4 — five-pane Workbench. Three columns on top
// (Trace Tree | Inspector | State Watcher), then full-width Token Stream and
// Command Bar bands, all separated by 3px drag handles.
export function Workbench() {
  const [leftW, setLeftW] = useState(230);
  const [rightW, setRightW] = useState(260);
  const [tokenH, setTokenH] = useState(108);
  const [cmdH, setCmdH] = useState(132);

  const init = useStore((s) => s.init);
  const refreshTraces = useStore((s) => s.refreshTraces);
  const submit = useStore((s) => s.submit);

  useEffect(() => {
    init();
    const id = window.setInterval(refreshTraces, 3000);
    return () => clearInterval(id);
  }, [init, refreshTraces]);

  // gdb keybindings (PRD 4.3 / 8.5.5). Inert while typing in a field so the
  // prompt and filter still accept these letters; Esc in the prompt blurs.
  useEffect(() => {
    const KEYS: Record<string, string> = {
      n: "n", p: "p", s: "s", f: "f", c: "c",
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || el?.isContentEditable) return;
      const cmd = KEYS[e.key];
      if (cmd) {
        e.preventDefault();
        submit(cmd);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [submit]);

  return (
    <div className="app">
      <div className="app-window raised-2">
        <TitleBar />
        <MenuBar />
        <Toolbar />
        <div className="body">
          <div className="cols">
            <div style={{ width: leftW, display: "flex" }}>
              <TraceTree />
            </div>
            <Splitter
              axis="v"
              onDelta={(px) => setLeftW((w) => clamp(w + px, 140, 520))}
            />
            <div style={{ flex: 1, display: "flex", minWidth: 0 }}>
              <Inspector />
            </div>
            <Splitter
              axis="v"
              onDelta={(px) => setRightW((w) => clamp(w - px, 160, 560))}
            />
            <div style={{ width: rightW, display: "flex" }}>
              <StateWatcher />
            </div>
          </div>

          <Splitter
            axis="h"
            onDelta={(py) => setTokenH((h) => clamp(h - py, 60, 400))}
          />
          <div style={{ height: tokenH }}>
            <TokenStream />
          </div>

          <Splitter
            axis="h"
            onDelta={(py) => setCmdH((h) => clamp(h - py, 60, 400))}
          />
          <div style={{ height: cmdH }}>
            <CommandBar />
          </div>
        </div>
        <StatusBar />
      </div>
      <BranchModal />
    </div>
  );
}
