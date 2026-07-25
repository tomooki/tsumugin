// Tsumugin Workbench desktop shell.
//
// This binary is intentionally thin: all business logic lives in the FastAPI
// backend (`tsumugin.workbench`, see docs/design/gui-workbench/architecture.md
// and ADR-0001). Tauri's role here is just to host a system WebView pointed
// at the backend's localhost origin (dev: `uv run python -m tsumugin.workbench`
// started separately; production: a bundled sidecar serving the same origin,
// see desktop/README.md "Sidecar / production packaging").
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tsumugin_workbench_lib::run()
}
