//! Stethoscope ingestion service: an OTLP/gRPC receiver that maps
//! OpenTelemetry GenAI spans into the Stethoscope trace store (PRD section 3).

pub mod mapper;
mod otel;
pub mod service;

use std::net::SocketAddr;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use opentelemetry_proto::tonic::collector::trace::v1::trace_service_server::TraceServiceServer;
use stethoscope_store::Store;
use tonic::transport::Server;

use crate::service::StethoscopeTraceService;

pub const DEFAULT_OTLP_ADDR: &str = "127.0.0.1:4317";

/// Resolve `~/.stethoscope/projects/<project>/traces.db`.
pub fn default_db_path(project: &str) -> PathBuf {
    let home = std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    home.join(".stethoscope")
        .join("projects")
        .join(project)
        .join("traces.db")
}

/// Open the store at `db_path`, creating parent directories as needed.
pub fn open_store(db_path: &Path) -> Result<Store> {
    if let Some(parent) = db_path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("creating {}", parent.display()))?;
    }
    Store::open(db_path)
}

/// Run the OTLP/gRPC receiver until the process is signalled.
pub async fn run_server(addr: SocketAddr, db_path: PathBuf) -> Result<()> {
    let store = open_store(&db_path)?;
    let svc = StethoscopeTraceService::new(store);

    tracing::info!(%addr, db = %db_path.display(), "Stethoscope ingestion listening (OTLP/gRPC)");

    Server::builder()
        .add_service(TraceServiceServer::new(svc))
        .serve_with_shutdown(addr, async {
            let _ = tokio::signal::ctrl_c().await;
            tracing::info!("shutdown signal received");
        })
        .await
        .context("gRPC server error")?;
    Ok(())
}
