// Library entry point for the Tsumugin Workbench Tauri shell.
//
// No custom commands / IPC are defined here: the frontend (`frontend/`,
// served by the FastAPI backend at the configured devUrl/frontendDist origin)
// talks to the backend directly over HTTP (`src/api/client.ts`), same-origin,
// whether running under `cargo tauri dev` or as a packaged app. This file
// exists only as the conventional `tauri::Builder` bootstrap point for future
// native integration (file dialogs, OS notifications, etc.) if/when needed.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tsumugin workbench tauri application");
}
