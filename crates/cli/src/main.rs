//! `stethoscope` CLI. Phase 1 milestone: `stethoscope list-traces`.

use std::net::SocketAddr;
use std::path::PathBuf;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use comfy_table::{presets::ASCII_FULL, Cell, Table};
use stethoscope_ingestion::{default_db_path, run_server, DEFAULT_OTLP_ADDR};
use stethoscope_store::Store;

#[derive(Parser)]
#[command(name = "stethoscope", version, about = "Time-travel debugger for LLM agents")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// List captured traces in a table.
    ListTraces {
        /// Filter by project name.
        #[arg(long)]
        project: Option<String>,
        /// Path to traces.db (default: ~/.stethoscope/projects/default/traces.db).
        #[arg(long)]
        db: Option<PathBuf>,
    },
    /// List known projects.
    Projects {
        #[arg(long)]
        db: Option<PathBuf>,
    },
    /// Run the OTLP/gRPC ingestion endpoint.
    Serve {
        #[arg(long, default_value = DEFAULT_OTLP_ADDR)]
        addr: SocketAddr,
        #[arg(long)]
        db: Option<PathBuf>,
    },
}

fn db_or_default(db: Option<PathBuf>) -> PathBuf {
    db.unwrap_or_else(|| default_db_path("default"))
}

fn cmd_list_traces(project: Option<String>, db: Option<PathBuf>) -> Result<()> {
    let path = db_or_default(db);
    let store = Store::open(&path)
        .with_context(|| format!("opening store at {}", path.display()))?;

    let project_id = match project.as_deref() {
        Some(name) => Some(
            store
                .list_projects()?
                .into_iter()
                .find(|(_, n)| n == name)
                .map(|(id, _)| id)
                .with_context(|| format!("no project named '{name}'"))?,
        ),
        None => None,
    };

    let traces = store.list_traces(project_id.as_deref())?;
    if traces.is_empty() {
        println!("(no traces yet — run an instrumented agent to begin)");
        return Ok(());
    }

    let mut table = Table::new();
    table.load_preset(ASCII_FULL).set_header(vec![
        "TRACE ID", "LABEL", "STATUS", "SPANS", "TOK IN", "TOK OUT", "COST $",
        "FRAMEWORK", "STARTED", "BRANCH",
    ]);
    for t in &traces {
        table.add_row(vec![
            Cell::new(&t.id[..t.id.len().min(16)]),
            Cell::new(t.label.as_deref().unwrap_or("-")),
            Cell::new(&t.status),
            Cell::new(t.span_count),
            Cell::new(t.total_tokens_in.unwrap_or(0)),
            Cell::new(t.total_tokens_out.unwrap_or(0)),
            Cell::new(format!("{:.4}", t.total_cost_usd.unwrap_or(0.0))),
            Cell::new(t.agent_framework.as_deref().unwrap_or("-")),
            Cell::new(t.started_at.format("%Y-%m-%d %H:%M:%S")),
            Cell::new(if t.is_branch { "fork" } else { "" }),
        ]);
    }
    println!("{table}");
    println!("{} trace(s).", traces.len());
    Ok(())
}

fn cmd_projects(db: Option<PathBuf>) -> Result<()> {
    let path = db_or_default(db);
    let store = Store::open(&path)?;
    let projects = store.list_projects()?;
    if projects.is_empty() {
        println!("(no projects yet)");
    } else {
        for (id, name) in projects {
            println!("{id}  {name}");
        }
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    match Cli::parse().command {
        Command::ListTraces { project, db } => cmd_list_traces(project, db),
        Command::Projects { db } => cmd_projects(db),
        Command::Serve { addr, db } => {
            run_server(addr, db_or_default(db)).await
        }
    }
}
