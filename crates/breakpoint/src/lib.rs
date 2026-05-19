//! Breakpoint predicate DSL (PRD 4.3 / 8.5.5 / 9.5).
//!
//! ```text
//! expr       := or
//! or         := and ( "OR"  and )*
//! and        := not ( "AND" not )*
//! not        := "NOT" not | primary
//! primary    := "(" expr ")" | comparison
//! comparison := IDENT OP VALUE
//! OP         := == | != | > | < | >= | <= | contains
//! VALUE      := 'string' | number | true | false
//! ```
//!
//! Identifiers are span fields: kind, name, status, tool_name, model,
//! provider, duration_ms, tokens_in, tokens_out, cost_usd, error_message.
//! Keywords (AND/OR/NOT/contains/true/false) are case-insensitive.

use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Str(String),
    Num(f64),
    Bool(bool),
    Null,
}

pub type Ctx = HashMap<String, Value>;

#[derive(Debug, Clone, PartialEq)]
enum Tok {
    Ident(String),
    Str(String),
    Num(f64),
    Bool(bool),
    Op(String),
    And,
    Or,
    Not,
    LParen,
    RParen,
}

fn lex(src: &str) -> Result<Vec<Tok>, String> {
    let b: Vec<char> = src.chars().collect();
    let mut i = 0;
    let mut out = Vec::new();
    while i < b.len() {
        let c = b[i];
        if c.is_whitespace() {
            i += 1;
        } else if c == '(' {
            out.push(Tok::LParen);
            i += 1;
        } else if c == ')' {
            out.push(Tok::RParen);
            i += 1;
        } else if c == '\'' || c == '"' {
            let q = c;
            i += 1;
            let mut s = String::new();
            while i < b.len() && b[i] != q {
                s.push(b[i]);
                i += 1;
            }
            if i >= b.len() {
                return Err("unterminated string".into());
            }
            i += 1;
            out.push(Tok::Str(s));
        } else if "=!<>".contains(c) {
            let mut op = String::new();
            op.push(c);
            i += 1;
            if i < b.len() && b[i] == '=' {
                op.push('=');
                i += 1;
            }
            out.push(Tok::Op(op));
        } else {
            let start = i;
            while i < b.len() && !b[i].is_whitespace() && !"()='\"!<>".contains(b[i]) {
                i += 1;
            }
            let w: String = b[start..i].iter().collect();
            match w.to_ascii_lowercase().as_str() {
                "and" => out.push(Tok::And),
                "or" => out.push(Tok::Or),
                "not" => out.push(Tok::Not),
                "contains" => out.push(Tok::Op("contains".into())),
                "true" => out.push(Tok::Bool(true)),
                "false" => out.push(Tok::Bool(false)),
                _ => {
                    if let Ok(n) = w.parse::<f64>() {
                        out.push(Tok::Num(n));
                    } else {
                        out.push(Tok::Ident(w));
                    }
                }
            }
        }
    }
    Ok(out)
}

#[derive(Debug, Clone)]
pub enum Expr {
    And(Box<Expr>, Box<Expr>),
    Or(Box<Expr>, Box<Expr>),
    Not(Box<Expr>),
    Cmp { field: String, op: String, val: Value },
}

struct P {
    t: Vec<Tok>,
    i: usize,
}

impl P {
    fn peek(&self) -> Option<&Tok> {
        self.t.get(self.i)
    }
    fn next(&mut self) -> Option<Tok> {
        let t = self.t.get(self.i).cloned();
        self.i += 1;
        t
    }
    fn or(&mut self) -> Result<Expr, String> {
        let mut e = self.and()?;
        while matches!(self.peek(), Some(Tok::Or)) {
            self.next();
            e = Expr::Or(Box::new(e), Box::new(self.and()?));
        }
        Ok(e)
    }
    fn and(&mut self) -> Result<Expr, String> {
        let mut e = self.not()?;
        while matches!(self.peek(), Some(Tok::And)) {
            self.next();
            e = Expr::And(Box::new(e), Box::new(self.not()?));
        }
        Ok(e)
    }
    fn not(&mut self) -> Result<Expr, String> {
        if matches!(self.peek(), Some(Tok::Not)) {
            self.next();
            Ok(Expr::Not(Box::new(self.not()?)))
        } else {
            self.primary()
        }
    }
    fn primary(&mut self) -> Result<Expr, String> {
        if matches!(self.peek(), Some(Tok::LParen)) {
            self.next();
            let e = self.or()?;
            if !matches!(self.next(), Some(Tok::RParen)) {
                return Err("expected )".into());
            }
            return Ok(e);
        }
        let field = match self.next() {
            Some(Tok::Ident(s)) => s,
            _ => return Err("expected field name".into()),
        };
        let op = match self.next() {
            Some(Tok::Op(o)) => o,
            _ => return Err("expected operator".into()),
        };
        let val = match self.next() {
            Some(Tok::Str(s)) => Value::Str(s),
            Some(Tok::Num(n)) => Value::Num(n),
            Some(Tok::Bool(b)) => Value::Bool(b),
            _ => return Err("expected value".into()),
        };
        Ok(Expr::Cmp { field, op, val })
    }
}

pub fn parse(src: &str) -> Result<Expr, String> {
    let toks = lex(src)?;
    if toks.is_empty() {
        return Err("empty predicate".into());
    }
    let mut p = P { t: toks, i: 0 };
    let e = p.or()?;
    if p.i != p.t.len() {
        return Err("trailing tokens".into());
    }
    Ok(e)
}

fn cmp(a: &Value, op: &str, b: &Value) -> bool {
    match op {
        "==" => a == b,
        "!=" => a != b,
        "contains" => match (a, b) {
            (Value::Str(x), Value::Str(y)) => x.contains(y.as_str()),
            _ => false,
        },
        ">" | "<" | ">=" | "<=" => {
            let (x, y) = match (a, b) {
                (Value::Num(x), Value::Num(y)) => (*x, *y),
                _ => return false,
            };
            match op {
                ">" => x > y,
                "<" => x < y,
                ">=" => x >= y,
                _ => x <= y,
            }
        }
        _ => false,
    }
}

pub fn evaluate(e: &Expr, ctx: &Ctx) -> bool {
    match e {
        Expr::And(a, b) => evaluate(a, ctx) && evaluate(b, ctx),
        Expr::Or(a, b) => evaluate(a, ctx) || evaluate(b, ctx),
        Expr::Not(x) => !evaluate(x, ctx),
        Expr::Cmp { field, op, val } => {
            cmp(ctx.get(field).unwrap_or(&Value::Null), op, val)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx() -> Ctx {
        let mut c = Ctx::new();
        c.insert("kind".into(), Value::Str("tool_call".into()));
        c.insert("tool_name".into(), Value::Str("web_search".into()));
        c.insert("duration_ms".into(), Value::Num(6000.0));
        c.insert("status".into(), Value::Str("ok".into()));
        c
    }

    #[test]
    fn prd_example_predicate() {
        let e = parse(
            "kind=='tool_call' AND tool_name=='web_search' AND duration_ms > 5000",
        )
        .unwrap();
        assert!(evaluate(&e, &ctx()));
    }

    #[test]
    fn not_and_or_and_contains() {
        assert!(evaluate(&parse("NOT status=='error'").unwrap(), &ctx()));
        assert!(evaluate(
            &parse("status=='error' OR kind=='tool_call'").unwrap(),
            &ctx()
        ));
        assert!(evaluate(&parse("tool_name contains 'search'").unwrap(), &ctx()));
        assert!(!evaluate(&parse("duration_ms < 100").unwrap(), &ctx()));
    }

    #[test]
    fn errors() {
        assert!(parse("").is_err());
        assert!(parse("kind ==").is_err());
    }
}
