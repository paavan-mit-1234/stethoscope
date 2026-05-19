//! Command Bar grammar (PRD 8.5.5). The canonical parser; the UI's
//! `command.ts` mirrors this exactly.
//!
//! ```text
//! help                       command list
//! clear                      clear scrollback
//! next | n                   advance one span
//! prev | p                   step back one span
//! step | s                   step into child spans
//! finish | f                 step out to parent
//! continue | c               run until next breakpoint (Phase 7)
//! where                      print current trace position
//! print <expr>               evaluate expr against the current span
//! break <predicate>          set a breakpoint (Phase 7)
//! delete <id>                delete a breakpoint (Phase 7)
//! branch <span_id>           branch from a span (Phase 5)
//! diff <a> <b>               open diff view (Phase 6)
//! watch <expr>               add a watch expression (Phase 6)
//! ```

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Command {
    Help,
    Clear,
    Next,
    Prev,
    Step,
    Finish,
    Continue,
    Where,
    Print(String),
    // Stubbed in their owning phases; parsed now so the grammar is stable.
    Break(String),
    Delete(String),
    Branch(String),
    Diff(String, String),
    Watch(String),
    Export(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParseError {
    Empty,
    MissingArg(&'static str),
    Unknown(String),
}

/// Parse one command line. Verb is case-insensitive; arguments are kept raw.
pub fn parse(line: &str) -> Result<Command, ParseError> {
    let line = line.trim();
    if line.is_empty() {
        return Err(ParseError::Empty);
    }
    let (verb, rest) = match line.split_once(char::is_whitespace) {
        Some((v, r)) => (v, r.trim()),
        None => (line, ""),
    };
    let arg = || -> Result<String, ParseError> {
        if rest.is_empty() {
            Err(ParseError::MissingArg("expression"))
        } else {
            Ok(rest.to_string())
        }
    };

    match verb.to_ascii_lowercase().as_str() {
        "help" | "?" => Ok(Command::Help),
        "clear" => Ok(Command::Clear),
        "next" | "n" => Ok(Command::Next),
        "prev" | "p" => Ok(Command::Prev),
        "step" | "s" => Ok(Command::Step),
        "finish" | "f" => Ok(Command::Finish),
        "continue" | "c" => Ok(Command::Continue),
        "where" | "bt" => Ok(Command::Where),
        "print" => Ok(Command::Print(arg()?)),
        "break" => Ok(Command::Break(arg()?)),
        "delete" => Ok(Command::Delete(arg()?)),
        // arg optional: empty => branch from the current span
        "branch" => Ok(Command::Branch(rest.to_string())),
        "watch" => Ok(Command::Watch(arg()?)),
        // arg optional: empty => export the selected trace
        "export" => Ok(Command::Export(rest.to_string())),
        "diff" => {
            // args optional: empty => shift-picked traces / branch-vs-parent
            let mut it = rest.split_whitespace();
            Ok(Command::Diff(
                it.next().unwrap_or("").to_string(),
                it.next().unwrap_or("").to_string(),
            ))
        }
        other => Err(ParseError::Unknown(other.to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verbs_and_aliases() {
        assert_eq!(parse("n").unwrap(), Command::Next);
        assert_eq!(parse("  NEXT ").unwrap(), Command::Next);
        assert_eq!(parse("p").unwrap(), Command::Prev);
        assert_eq!(parse("s").unwrap(), Command::Step);
        assert_eq!(parse("f").unwrap(), Command::Finish);
        assert_eq!(parse("where").unwrap(), Command::Where);
    }

    #[test]
    fn print_keeps_raw_expr() {
        assert_eq!(
            parse("print span.messages[-1]").unwrap(),
            Command::Print("span.messages[-1]".into())
        );
        assert_eq!(parse("print"), Err(ParseError::MissingArg("expression")));
    }

    #[test]
    fn diff_args_optional() {
        assert_eq!(parse("diff a b").unwrap(), Command::Diff("a".into(), "b".into()));
        assert_eq!(parse("diff").unwrap(), Command::Diff("".into(), "".into()));
    }

    #[test]
    fn unknown_is_reported() {
        assert_eq!(parse("frobnicate"), Err(ParseError::Unknown("frobnicate".into())));
        assert_eq!(parse("  "), Err(ParseError::Empty));
    }
}
