// Command Bar grammar + safe `print` evaluator (Phase 4).
// Mirrors crates/command/src/lib.rs exactly (same verbs/aliases).

export type Command =
  | { t: "help" }
  | { t: "clear" }
  | { t: "next" }
  | { t: "prev" }
  | { t: "step" }
  | { t: "finish" }
  | { t: "continue" }
  | { t: "where" }
  | { t: "print"; expr: string }
  | { t: "break"; arg: string }
  | { t: "delete"; arg: string }
  | { t: "branch"; arg: string }
  | { t: "diff"; a: string; b: string }
  | { t: "watch"; arg: string }
  | { t: "export"; arg: string }
  | { t: "error"; msg: string };

export const HELP_LINES = [
  "next / n                   advance one span",
  "prev / p                   step back one span",
  "step / s                   step into child spans",
  "finish / f                 step out to parent",
  "continue / c               run until next breakpoint (Phase 7)",
  "where / bt                 print current trace position",
  "print <expr>               eval against current span",
  "                           e.g. print span.name | print messages[-1]",
  "branch <span_id>           branch from a span (Phase 5)",
  "diff <a> <b>               open diff view (Phase 6)",
  "break <predicate>          set a breakpoint",
  "break list                 list breakpoints",
  "delete <id>                delete a breakpoint",
  "export [trace_id]          export a .steth bundle",
  "clear                      clear scrollback",
  "help                       this list",
  "# keys: n p s f c work when focus is outside the prompt (Esc to blur)",
];

export function parseCommand(line: string): Command {
  const s = line.trim();
  if (!s) return { t: "error", msg: "empty" };
  const m = s.match(/^(\S+)\s*([\s\S]*)$/);
  const verb = (m?.[1] ?? "").toLowerCase();
  const rest = (m?.[2] ?? "").trim();
  const need = (kind: Command["t"], what: string): Command =>
    rest ? ({ t: kind, arg: rest } as Command) : { t: "error", msg: `${verb}: missing ${what}` };

  switch (verb) {
    case "help":
    case "?":
      return { t: "help" };
    case "clear":
      return { t: "clear" };
    case "next":
    case "n":
      return { t: "next" };
    case "prev":
    case "p":
      return { t: "prev" };
    case "step":
    case "s":
      return { t: "step" };
    case "finish":
    case "f":
      return { t: "finish" };
    case "continue":
    case "c":
      return { t: "continue" };
    case "where":
    case "bt":
      return { t: "where" };
    case "print":
      return rest ? { t: "print", expr: rest } : { t: "error", msg: "print: missing expression" };
    case "break":
      return need("break", "predicate");
    case "delete":
      return need("delete", "breakpoint id");
    case "branch":
      // arg optional: empty => branch from the currently selected span
      return { t: "branch", arg: rest };
    case "watch":
      return need("watch", "expression");
    case "export":
      // arg optional: empty => export the selected trace
      return { t: "export", arg: rest };
    case "diff": {
      // args optional: 0 => use shift-picked traces or branch-vs-parent
      const parts = rest.split(/\s+/).filter(Boolean);
      return { t: "diff", a: parts[0] ?? "", b: parts[1] ?? "" };
    }
    default:
      return { t: "error", msg: `unknown command: ${verb} — try 'help'` };
  }
}

// ---- safe path evaluator for `print` ---------------------------------
// Supports `key`, `.key`, and `[index]` (negative allowed). No eval().

type Seg = { key: string } | { idx: number };

function tokenize(expr: string): Seg[] | null {
  const segs: Seg[] = [];
  let i = 0;
  const e = expr.trim();
  while (i < e.length) {
    if (e[i] === ".") {
      i++;
      continue;
    }
    if (e[i] === "[") {
      const close = e.indexOf("]", i);
      if (close < 0) return null;
      const n = Number(e.slice(i + 1, close));
      if (!Number.isInteger(n)) return null;
      segs.push({ idx: n });
      i = close + 1;
      continue;
    }
    const m = e.slice(i).match(/^[A-Za-z_$][\w$]*/);
    if (!m) return null;
    segs.push({ key: m[0] });
    i += m[0].length;
  }
  return segs;
}

export function evalPath(ctx: Record<string, unknown>, expr: string): string {
  const segs = tokenize(expr);
  if (!segs || segs.length === 0) return `(bad expression: ${expr})`;
  let cur: unknown = ctx;
  for (const seg of segs) {
    if (cur == null) return "undefined";
    if ("key" in seg) {
      cur = (cur as Record<string, unknown>)[seg.key];
    } else {
      if (!Array.isArray(cur)) return "undefined";
      cur = cur[seg.idx < 0 ? cur.length + seg.idx : seg.idx];
    }
  }
  if (cur === undefined) return "undefined";
  if (typeof cur === "string") return cur;
  try {
    return JSON.stringify(cur, null, 2);
  } catch {
    return String(cur);
  }
}
