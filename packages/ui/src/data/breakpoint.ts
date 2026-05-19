// Breakpoint predicate DSL — mirrors crates/breakpoint exactly (same
// grammar/keywords). Used by `continue` to run the cursor to the next span
// that matches an enabled breakpoint.

export type Val = string | number | boolean | null;
export type Ctx = Record<string, Val>;

type Tok =
  | { k: "id"; v: string }
  | { k: "str"; v: string }
  | { k: "num"; v: number }
  | { k: "bool"; v: boolean }
  | { k: "op"; v: string }
  | { k: "and" }
  | { k: "or" }
  | { k: "not" }
  | { k: "(" }
  | { k: ")" };

function lex(src: string): Tok[] {
  const t: Tok[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) {
      i++;
    } else if (c === "(") {
      t.push({ k: "(" });
      i++;
    } else if (c === ")") {
      t.push({ k: ")" });
      i++;
    } else if (c === "'" || c === '"') {
      const q = c;
      i++;
      let s = "";
      while (i < src.length && src[i] !== q) s += src[i++];
      if (i >= src.length) throw new Error("unterminated string");
      i++;
      t.push({ k: "str", v: s });
    } else if ("=!<>".includes(c)) {
      let op = c;
      i++;
      if (src[i] === "=") {
        op += "=";
        i++;
      }
      t.push({ k: "op", v: op });
    } else {
      let w = "";
      while (i < src.length && !/\s/.test(src[i]) && !"()='\"!<>".includes(src[i]))
        w += src[i++];
      const lw = w.toLowerCase();
      if (lw === "and") t.push({ k: "and" });
      else if (lw === "or") t.push({ k: "or" });
      else if (lw === "not") t.push({ k: "not" });
      else if (lw === "contains") t.push({ k: "op", v: "contains" });
      else if (lw === "true") t.push({ k: "bool", v: true });
      else if (lw === "false") t.push({ k: "bool", v: false });
      else if (w !== "" && !Number.isNaN(Number(w)))
        t.push({ k: "num", v: Number(w) });
      else t.push({ k: "id", v: w });
    }
  }
  return t;
}

export type Expr =
  | { t: "and"; a: Expr; b: Expr }
  | { t: "or"; a: Expr; b: Expr }
  | { t: "not"; e: Expr }
  | { t: "cmp"; field: string; op: string; val: Val };

export function parsePredicate(src: string): Expr {
  const toks = lex(src);
  if (toks.length === 0) throw new Error("empty predicate");
  let i = 0;
  const peek = () => toks[i];
  const eat = () => toks[i++];

  const orE = (): Expr => {
    let e = andE();
    while (peek()?.k === "or") {
      eat();
      e = { t: "or", a: e, b: andE() };
    }
    return e;
  };
  const andE = (): Expr => {
    let e = notE();
    while (peek()?.k === "and") {
      eat();
      e = { t: "and", a: e, b: notE() };
    }
    return e;
  };
  const notE = (): Expr => {
    if (peek()?.k === "not") {
      eat();
      return { t: "not", e: notE() };
    }
    return primary();
  };
  const primary = (): Expr => {
    if (peek()?.k === "(") {
      eat();
      const e = orE();
      if (eat()?.k !== ")") throw new Error("expected )");
      return e;
    }
    const f = eat();
    if (f?.k !== "id") throw new Error("expected field name");
    const o = eat();
    if (o?.k !== "op") throw new Error("expected operator");
    const v = eat();
    let val: Val;
    if (v?.k === "str") val = v.v;
    else if (v?.k === "num") val = v.v;
    else if (v?.k === "bool") val = v.v;
    else throw new Error("expected value");
    return { t: "cmp", field: f.v, op: o.v, val };
  };

  const e = orE();
  if (i !== toks.length) throw new Error("trailing tokens");
  return e;
}

function cmp(a: Val, op: string, b: Val): boolean {
  if (op === "==") return a === b;
  if (op === "!=") return a !== b;
  if (op === "contains")
    return typeof a === "string" && typeof b === "string" && a.includes(b);
  if (typeof a !== "number" || typeof b !== "number") return false;
  if (op === ">") return a > b;
  if (op === "<") return a < b;
  if (op === ">=") return a >= b;
  if (op === "<=") return a <= b;
  return false;
}

export function evaluatePredicate(e: Expr, ctx: Ctx): boolean {
  if (e.t === "and") return evaluatePredicate(e.a, ctx) && evaluatePredicate(e.b, ctx);
  if (e.t === "or") return evaluatePredicate(e.a, ctx) || evaluatePredicate(e.b, ctx);
  if (e.t === "not") return !evaluatePredicate(e.e, ctx);
  return cmp(ctx[e.field] ?? null, e.op, e.val);
}
