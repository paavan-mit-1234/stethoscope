//! Standalone OTLP/gRPC ingestion endpoint.
//!
//! In the desktop app this runs embedded in the Tauri process; the standalone
//! binary backs the vertical-slice workflow and CI smoke tests.
//!
//! Env overrides:
//!   STETHOSCOPE_OTLP_ADDR   default 127.0.0.1:4317
//!   STETHOSCOPE_DB          default ~/.stethoscope/projects/default/traces.db

use std::net::SocketAddr;
use std::path::PathBuf;

use anyhow::{Context, Result};
use stethoscope_ingestion::{default_db_path, run_server, DEFAULT_OTLP_ADDR};

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "stethoscope_ingestion=info,info".into()),
        )
        .init();

    let addr: SocketAddr = std::env::var("STETHOSCOPE_OTLP_ADDR")
        .unwrap_or_else(|_| DEFAULT_OTLP_ADDR.to_string())
        .parse()
        .context("parsing STETHOSCOPE_OTLP_ADDR")?;

    let db_path = std::env::var_os("STETHOSCOPE_DB")
        .map(PathBuf::from)
        .unwrap_or_else(|| default_db_path("default"));

    run_server(addr, db_path).await
}
