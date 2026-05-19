// Stethoscope desktop shell. Window decorations are off — the Workbench
// renders its own Win32-style title bar (PRD 8.4). The OTLP/gRPC ingestion
// service runs embedded in this process (PRD 3.2).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use std::net::SocketAddr;
use std::sync::Mutex;

use stethoscope_ingestion::{default_db_path, run_server, DEFAULT_OTLP_ADDR};
use stethoscope_store::Store;

use crate::commands::AppState;

fn spawn_ingestion() {
    std::thread::spawn(|| {
        let rt = match tokio::runtime::Runtime::new() {
            Ok(rt) => rt,
            Err(e) => {
                eprintln!("ingestion runtime failed: {e}");
                return;
            }
        };
        rt.block_on(async {
            let addr: SocketAddr = DEFAULT_OTLP_ADDR.parse().expect("valid addr");
            if let Err(e) = run_server(addr, default_db_path("default")).await {
                eprintln!("ingestion service exited: {e}");
            }
        });
    });
}

fn main() {
    let store = Store::open(default_db_path("default"))
        .expect("open trace store");

    tauri::Builder::default()
        .manage(AppState {
            store: Mutex::new(store),
        })
        .invoke_handler(tauri::generate_handler![
            commands::list_projects,
            commands::list_traces,
            commands::get_spans,
            commands::get_span,
            commands::get_messages,
            commands::get_tool_call,
            commands::branch,
            commands::diff_traces,
            commands::set_breakpoint,
            commands::list_breakpoints,
            commands::delete_breakpoint,
            commands::export_steth,
        ])
        .setup(|_app| {
            spawn_ingestion();
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Stethoscope");
}
