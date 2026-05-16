//! OTLP/gRPC `TraceService` implementation.

use std::sync::{Arc, Mutex};

use opentelemetry_proto::tonic::collector::trace::v1::{
    trace_service_server::TraceService, ExportTraceServiceRequest,
    ExportTraceServiceResponse,
};
use stethoscope_store::Store;
use tonic::{Request, Response, Status};

use crate::mapper::ingest_request;

#[derive(Clone)]
pub struct StethoscopeTraceService {
    store: Arc<Mutex<Store>>,
}

impl StethoscopeTraceService {
    pub fn new(store: Store) -> Self {
        Self {
            store: Arc::new(Mutex::new(store)),
        }
    }
}

#[tonic::async_trait]
impl TraceService for StethoscopeTraceService {
    async fn export(
        &self,
        request: Request<ExportTraceServiceRequest>,
    ) -> Result<Response<ExportTraceServiceResponse>, Status> {
        let req = request.into_inner();
        let store = self.store.clone();

        // DuckDB writes are blocking; keep them off the async reactor.
        let count = tokio::task::spawn_blocking(move || {
            let guard = store.lock().map_err(|_| "store mutex poisoned".to_string())?;
            ingest_request(&guard, &req).map_err(|e| e.to_string())
        })
        .await
        .map_err(|e| Status::internal(format!("join error: {e}")))?
        .map_err(|e| Status::internal(format!("ingest error: {e}")))?;

        tracing::info!(spans = count, "ingested OTLP batch");
        // Full success: empty partial_success.
        Ok(Response::new(ExportTraceServiceResponse {
            partial_success: None,
        }))
    }
}
