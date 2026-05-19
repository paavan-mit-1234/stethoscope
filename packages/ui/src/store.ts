import { create } from "zustand";
import { api, type Breakpoint, type Message, type Project, type Span, type ToolCall, type Trace } from "./data/api";
import { evaluatePredicate, parsePredicate } from "./data/breakpoint";
import { HELP_LINES, evalPath, parseCommand } from "./data/command";
import { type AlignedPair, alignSpans, firstDivergence } from "./data/diff";
import { pathTo, preorder, step } from "./data/nav";

export type Line = { text: string; kind: "in" | "out" | "info" | "err" };

type State = {
  // shell
  splashDone: boolean;
  project: string;
  frameworkVersion: string;
  scrollback: Line[];
  history: string[];

  // data (Phase 3)
  connected: boolean;
  projects: Project[];
  traces: Trace[];
  selectedTraceId: string | null;
  spans: Span[];
  selectedSpanId: string | null;
  messages: Message[];
  toolCall: ToolCall | null;

  dismissSplash: () => void;
  print: (text: string, kind?: Line["kind"]) => void;
  pushHistory: (cmd: string) => void;

  init: () => Promise<void>;
  refreshTraces: () => Promise<void>;
  selectTrace: (id: string) => Promise<void>;
  selectSpan: (id: string) => Promise<void>;

  // command bar (Phase 4)
  submit: (line: string) => void;
  runCommand: (line: string) => void;

  // branch + replay (Phase 5)
  branchModal: {
    open: boolean;
    spanId: string | null;
    toolName: string | null;
    value: string;
    busy: boolean;
  };
  openBranch: (spanId: string) => Promise<void>;
  closeBranch: () => void;
  setBranchValue: (v: string) => void;
  confirmBranch: () => Promise<void>;

  // diff (Phase 6)
  diffPick: string[];
  diff: {
    active: boolean;
    aId: string | null;
    bId: string | null;
    aLabel: string;
    bLabel: string;
    pairs: AlignedPair[];
    sel: number;
  };
  pickForDiff: (traceId: string) => void;
  openDiff: (aId: string, bId: string) => Promise<void>;
  closeDiff: () => void;
  setDiffSel: (i: number) => void;

  // breakpoints + polish (Phase 7)
  breakpoints: Breakpoint[];
  bpHit: { name: string; traceId: string; spanId: string } | null;
  heatmap: "off" | "lat" | "cost";
  _bpSig: string | null;
  refreshBreakpoints: () => Promise<void>;
  cycleHeatmap: () => void;
};

export const useStore = create<State>((set, get) => ({
  splashDone: false,
  project: "agent_v3",
  frameworkVersion: "langgraph 0.2.0",
  scrollback: [{ text: "# tip: run 'help' to see commands", kind: "info" }],
  history: [],

  connected: false,
  projects: [],
  traces: [],
  selectedTraceId: null,
  spans: [],
  selectedSpanId: null,
  messages: [],
  toolCall: null,

  branchModal: { open: false, spanId: null, toolName: null, value: "", busy: false },

  diffPick: [],
  diff: { active: false, aId: null, bId: null, aLabel: "", bLabel: "", pairs: [], sel: 0 },

  breakpoints: [],
  bpHit: null,
  heatmap: "off",
  _bpSig: null,

  dismissSplash: () => set({ splashDone: true }),
  print: (text, kind = "out") =>
    set((s) => ({ scrollback: [...s.scrollback, { text, kind }] })),
  pushHistory: (cmd) => set((s) => ({ history: [...s.history, cmd] })),

  init: async () => {
    const ok = await api.health();
    set({ connected: ok });
    if (!ok) return;
    try {
      const [projects] = await Promise.all([api.listProjects()]);
      set({ projects });
      await get().refreshTraces();
    } catch {
      set({ connected: false });
    }
  },

  refreshTraces: async () => {
    try {
      const traces = await api.listTraces();
      set({ traces, connected: true });
      await get().refreshBreakpoints();
    } catch {
      set({ connected: false });
    }
  },

  refreshBreakpoints: async () => {
    let bps: Breakpoint[];
    try {
      bps = await api.listBreakpoints();
    } catch {
      return;
    }
    // Detect a new hit (PRD 9.5): newest last_hit signature changed.
    const hit = bps
      .filter((b) => b.last_hit_at && b.last_hit_span_id)
      .sort((a, b) => (a.last_hit_at! < b.last_hit_at! ? 1 : -1))[0];
    const sig = hit ? `${hit.id}@${hit.last_hit_at}` : null;
    set({ breakpoints: bps });
    if (sig && sig !== get()._bpSig) {
      set({
        _bpSig: sig,
        bpHit: {
          name: hit!.name || hit!.condition_dsl,
          traceId: hit!.last_hit_trace_id!,
          spanId: hit!.last_hit_span_id!,
        },
      });
      get().print(`⚑ breakpoint hit: ${hit!.name || hit!.condition_dsl}`, "err");
      // Focus the matching span.
      await get().selectTrace(hit!.last_hit_trace_id!);
      void get().selectSpan(hit!.last_hit_span_id!);
    } else if (!get()._bpSig) {
      set({ _bpSig: sig });
    }
  },

  cycleHeatmap: () =>
    set((s) => ({
      heatmap:
        s.heatmap === "off" ? "lat" : s.heatmap === "lat" ? "cost" : "off",
    })),

  selectTrace: async (id) => {
    set({ selectedTraceId: id, spans: [], selectedSpanId: null, messages: [], toolCall: null });
    try {
      const spans = await api.getSpans(id);
      set({ spans });
    } catch {
      set({ connected: false });
    }
  },

  selectSpan: async (id) => {
    set({ selectedSpanId: id, messages: [], toolCall: null });
    try {
      const [messages, toolCall] = await Promise.all([
        api.getMessages(id),
        api.getToolCall(id),
      ]);
      set({ messages, toolCall });
    } catch {
      set({ connected: false });
    }
  },

  // Echo + history, then execute. Shared by the prompt and the gdb keys.
  submit: (line) => {
    const cmd = line.trim();
    get().print(`(steth) ${cmd}`, "in");
    if (cmd) get().pushHistory(cmd);
    get().runCommand(cmd);
  },

  runCommand: (line) => {
    const s = get();
    const p = s.print;
    const cmd = parseCommand(line);

    switch (cmd.t) {
      case "help":
        HELP_LINES.forEach((l) => p(l, "out"));
        return;
      case "clear":
        set({ scrollback: [] });
        return;
      case "next":
      case "prev":
      case "step":
      case "finish": {
        if (!s.selectedTraceId) {
          p("(no trace selected — click a trace first)", "err");
          return;
        }
        const order = preorder(s.spans);
        const mv = step(order, s.spans, s.selectedSpanId, cmd.t);
        if ("id" in mv) {
          const idx = order.findIndex((x) => x.id === mv.id);
          const sp = s.spans.find((x) => x.id === mv.id);
          if (sp) p(`→ ${sp.name}  [${sp.kind}]  ${idx + 1}/${order.length}`, "out");
          void s.selectSpan(mv.id);
        } else {
          p(mv.msg, "info");
        }
        return;
      }
      case "continue": {
        if (!s.selectedTraceId) {
          p("(no trace selected)", "err");
          return;
        }
        const enabled = s.breakpoints.filter((b) => b.enabled);
        const preds = enabled
          .map((b) => {
            try {
              return { b, e: parsePredicate(b.condition_dsl) };
            } catch {
              return null;
            }
          })
          .filter((x): x is { b: Breakpoint; e: ReturnType<typeof parsePredicate> } => !!x);
        const order = preorder(s.spans);
        const start = order.findIndex((x) => x.id === s.selectedSpanId);
        for (let k = start + 1; k < order.length; k++) {
          const sp = order[k];
          const ctx = {
            kind: sp.kind,
            name: sp.name,
            status: sp.status,
            duration_ms: sp.duration_ms,
            model: sp.model,
            provider: sp.provider,
            tokens_in: sp.tokens_in,
            tokens_out: sp.tokens_out,
            cost_usd: sp.cost_usd,
            error_message: sp.error_message,
            tool_name: sp.name.startsWith("tool:") ? sp.name.slice(5) : null,
          };
          const hit = preds.find((pp) => evaluatePredicate(pp.e, ctx));
          if (hit) {
            p(
              `⚑ breakpoint hit: ${hit.b.name || hit.b.condition_dsl} @ ${sp.name}`,
              "err",
            );
            void get().selectSpan(sp.id);
            return;
          }
        }
        const last = order[order.length - 1];
        if (last) void get().selectSpan(last.id);
        p("continue: no breakpoint hit — end of trace", "info");
        return;
      }
      case "where": {
        if (!s.selectedSpanId) {
          p("(no span selected — use next/step)", "info");
          return;
        }
        pathTo(s.spans, s.selectedSpanId).forEach((sp, i) =>
          p(
            `#${i} ${"  ".repeat(i)}${sp.name} [${sp.kind}]` +
              (sp.id === s.selectedSpanId ? "   <-- current" : ""),
            "out",
          ),
        );
        return;
      }
      case "print": {
        const span = s.spans.find((x) => x.id === s.selectedSpanId) ?? null;
        if (!span) {
          p("(no span selected)", "err");
          return;
        }
        let attributes: Record<string, unknown> = {};
        try {
          attributes = span.attributes_json ? JSON.parse(span.attributes_json) : {};
        } catch {
          /* leave empty */
        }
        const ctx = { span, messages: s.messages, tool: s.toolCall, attributes };
        evalPath(ctx, cmd.expr)
          .split("\n")
          .forEach((l) => p(l, "out"));
        return;
      }
      case "branch": {
        const id = cmd.arg || s.selectedSpanId;
        if (!id) {
          p("branch: select a tool span first, or `branch <span_id>`", "err");
          return;
        }
        void get().openBranch(id);
        return;
      }
      case "diff": {
        if (cmd.a && cmd.b) {
          void get().openDiff(cmd.a, cmd.b);
          return;
        }
        if (s.diffPick.length === 2) {
          void get().openDiff(s.diffPick[0], s.diffPick[1]);
          return;
        }
        const sel = s.traces.find((t) => t.id === s.selectedTraceId);
        if (sel?.parent_trace_id) {
          void get().openDiff(sel.parent_trace_id, sel.id);
          return;
        }
        p(
          "diff: shift-click two traces, or select a branch, or `diff <a> <b>`",
          "err",
        );
        return;
      }
      case "watch":
        p(`watch ${cmd.arg}: watch expressions land with State (Phase 6)`, "info");
        return;
      case "break": {
        if (cmd.arg.trim().toLowerCase() === "list") {
          if (s.breakpoints.length === 0) p("(no breakpoints)", "info");
          for (const b of s.breakpoints)
            p(
              `${b.id.slice(0, 8)}  ${b.enabled ? "●" : "○"}  hits=${b.hit_count}  ${b.condition_dsl}`,
              "out",
            );
          return;
        }
        void api
          .addBreakpoint({ condition_dsl: cmd.arg })
          .then((r) => {
            if (r.error) p(`break: ${r.error}`, "err");
            else {
              p(`Breakpoint ${r.id?.slice(0, 8)} set: ${cmd.arg}`, "out");
              void get().refreshBreakpoints();
            }
          });
        return;
      }
      case "delete":
        void api.deleteBreakpoint(cmd.arg).then(() => {
          p(`deleted breakpoint ${cmd.arg}`, "out");
          void get().refreshBreakpoints();
        });
        return;
      case "export": {
        const tid = cmd.arg || s.selectedTraceId;
        if (!tid) {
          p("export: select a trace or `export <trace_id>`", "err");
          return;
        }
        void api
          .exportTrace(tid)
          .then((bundle) => {
            const blob = new Blob([JSON.stringify(bundle, null, 2)], {
              type: "application/json",
            });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = `${tid.slice(0, 12)}.steth`;
            a.click();
            URL.revokeObjectURL(a.href);
            p(`exported ${tid.slice(0, 12)}.steth`, "out");
          })
          .catch((e) => p(`export: ${String(e)}`, "err"));
        return;
      }
      case "error":
        if (cmd.msg !== "empty") p(cmd.msg, "err");
        return;
    }
  },

  openBranch: async (spanId) => {
    const span = get().spans.find((x) => x.id === spanId);
    if (!span || span.kind !== "tool_call") {
      get().print(
        "branch: that span is not a tool call (Phase 5 mutates tool responses)",
        "err",
      );
      return;
    }
    let value = "";
    try {
      const tc = await api.getToolCall(spanId);
      value = tc?.result_inline ?? "";
    } catch {
      /* offline — leave blank */
    }
    set({
      branchModal: {
        open: true,
        spanId,
        toolName: span.name.replace(/^tool:/, ""),
        value,
        busy: false,
      },
    });
  },

  closeBranch: () =>
    set((s) => ({ branchModal: { ...s.branchModal, open: false, busy: false } })),

  setBranchValue: (v) =>
    set((s) => ({ branchModal: { ...s.branchModal, value: v } })),

  confirmBranch: async () => {
    const { branchModal: bm, selectedTraceId, print } = get();
    if (!bm.spanId || !selectedTraceId) return;
    set((s) => ({ branchModal: { ...s.branchModal, busy: true } }));
    print(`(branch) replaying from ${bm.spanId.slice(0, 8)}…`, "info");
    try {
      const r = await api.branch({
        source_trace_id: selectedTraceId,
        branch_point_span_id: bm.spanId,
        mutation: { type: "tool_response", span_id: bm.spanId, value: bm.value },
      });
      if (r.ok) {
        print(`(branch) replay ok — ${(r.stdout ?? []).join(" ")}`, "out");
        await get().refreshTraces();
      } else {
        print(`(branch) replay failed: ${r.error ?? (r.stderr ?? []).join(" ")}`, "err");
      }
    } catch (e) {
      print(`(branch) error: ${String(e)}`, "err");
    } finally {
      set((s) => ({ branchModal: { ...s.branchModal, open: false, busy: false } }));
    }
  },

  pickForDiff: (traceId) =>
    set((s) => {
      const cur = s.diffPick.filter((x) => x !== traceId);
      const next = s.diffPick.includes(traceId)
        ? cur // toggle off
        : [...cur, traceId].slice(-2); // keep last two
      return { diffPick: next };
    }),

  openDiff: async (aId, bId) => {
    try {
      const [as_, bs] = await Promise.all([
        api.getSpans(aId),
        api.getSpans(bId),
      ]);
      const pairs = alignSpans(as_, bs);
      const tr = get().traces;
      const lab = (id: string) => {
        const t = tr.find((x) => x.id === id);
        return t ? `${t.label ?? id.slice(0, 8)} [${t.status}]` : id.slice(0, 8);
      };
      set({
        diff: {
          active: true,
          aId,
          bId,
          aLabel: lab(aId),
          bLabel: lab(bId),
          pairs,
          sel: Math.max(0, firstDivergence(pairs)),
        },
      });
    } catch (e) {
      get().print(`diff: ${String(e)}`, "err");
    }
  },

  closeDiff: () => set((s) => ({ diff: { ...s.diff, active: false } })),
  setDiffSel: (i) => set((s) => ({ diff: { ...s.diff, sel: i } })),
}));
