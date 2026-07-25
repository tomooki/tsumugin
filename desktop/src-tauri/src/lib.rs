// Tsumugin Workbench desktop shell.
//
// This binary is intentionally thin: all business logic lives in the FastAPI
// backend (`tsumugin.workbench`, see docs/design/gui-workbench/architecture.md
// and ADR-0001). Tauri's role is to host a system WebView pointed at the
// backend's localhost origin, and — in production builds only (V2c C1) — to
// spawn and supervise the PyInstaller-built backend sidecar so the app is
// self-contained.
//
// Dev workflow (`cargo tauri dev`) is unchanged from before this file existed:
// the backend is started manually (`uv run python -m tsumugin.workbench`,
// desktop/README.md "Dev で起動する") and `tauri.conf.json`'s `devUrl` points
// straight at it. We do not spawn the sidecar in debug builds, matching that
// workflow; the health-check/navigate logic below still runs so a manually
// started dev server is picked up the same way a production sidecar would be.
//
// Production (`cargo tauri build`): `setup()` spawns the sidecar exe staged by
// `desktop/sidecar/build_sidecar.ps1` at
// `desktop/src-tauri/binaries/tsumugin-workbench-sidecar-<target-triple>.exe`
// (bundled via `tauri.conf.json`'s `bundle.resources` — see that file and the
// build script for why this uses `resources` + a plain `std::process::Command`
// spawn rather than `tauri-plugin-shell`'s `externalBin`/`sidecar()`: the
// PyInstaller output is a one-dir payload [exe + `_internal/` dependency
// folder], and `externalBin` is designed around a single relocatable binary —
// splitting the exe out under that convention would strand `_internal` and
// break the sidecar at runtime). It then polls `GET /api/state` for up to 30s;
// on success the main window is navigated to the backend origin, on failure
// (or if spawning itself failed — GSAS-II being absent is *not* a failure
// mode here, see `status.gsas_available` in the API contract; only "the
// server never came up" is) an error dialog is shown so the failure is never
// silent.
//
// 【孤児化 / 二重起動対策 (V2c レビュー指摘)】: 素の `std::process::Command` spawn は Windows の
// ジョブオブジェクト等に紐付けないため、タスクマネージャでこのアプリだけを強制終了した場合
// sidecar 子プロセスが取り残される (孤児化) おそれがある。対策として自 PID を `--parent-pid` で
// 子に渡し、子側 (`desktop/sidecar/tsumugin_workbench_sidecar.py`) が Windows API で親の終了を
// 監視して自ら `os._exit(0)` する (`kill_sidecar` の通常終了経路と独立な安全網)。また spawn 前に
// ポート 8770 が既に応答していないか確認し、応答していれば (別インスタンス、または前回セッションの
// 残存プロセス) 新規 spawn をやめて警告ダイアログを出してから既存バックエンドへ接続する
// (サイレントな相乗りをやめる — `show_existing_backend_dialog`)。

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};

const SIDECAR_HOST: &str = "127.0.0.1";
const SIDECAR_PORT: u16 = 8770;
const HEALTHCHECK_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTHCHECK_POLL_INTERVAL: Duration = Duration::from_millis(300);

/// Holds the spawned sidecar child process (production builds only), so it can be killed when
/// the app exits (`RunEvent::Exit`/`ExitRequested`). `None` in dev builds, or if spawning failed
/// and the health check happened to succeed against an already-running backend anyway.
struct SidecarProcess(Mutex<Option<Child>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(SidecarProcess(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            // 【ブロッキング処理を setup 外へ】: TCP ポーリング (最大 30s) は setup() の
            //   同期コンテキストで直接行うとイベントループを止めてしまうため別スレッドに出す。
            std::thread::spawn(move || bootstrap_backend(&handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tsumugin workbench tauri application")
        .run(|app_handle, event| {
            if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
                kill_sidecar(app_handle);
            }
        });
}

/// production ビルドのみ sidecar を spawn し、いずれの場合も (dev/prod, spawn 成功/失敗を問わず)
/// health check → 成功なら window を navigate、失敗ならエラーダイアログ、という筋を通す。
fn bootstrap_backend(app: &AppHandle) {
    if !cfg!(debug_assertions) {
        // 【二重起動ガード (V2c レビュー指摘)】: spawn する前にポート 8770 が既に 200 を返すか
        //   確認する。既に何か動いていれば (別インスタンス、または前回セッションの残存プロセス)
        //   新しい sidecar をさらに spawn せず、警告ダイアログで利用者に明示してから既存のものへ
        //   接続する — 以前はここを確認せず常に spawn していたため、失敗時のフォールバック
        //   (下の Err 節) でのみ暗黙に「既存バックエンドへ相乗り」していた。それをサイレントに
        //   させず、正常系でも明示的な警告を出す。
        if http_get_is_200(SIDECAR_HOST, SIDECAR_PORT, "/api/state") {
            eprintln!(
                "tsumugin workbench: a backend is already responding on \
                 http://{SIDECAR_HOST}:{SIDECAR_PORT}; not spawning a new sidecar"
            );
            show_existing_backend_dialog(app);
        } else {
            match spawn_sidecar(app) {
                Ok(child) => {
                    if let Some(state) = app.try_state::<SidecarProcess>() {
                        *state.0.lock().unwrap() = Some(child);
                    }
                }
                Err(err) => {
                    // 【sidecar 不在時フォールバック】: 起動できなくても即エラーにはしない — 既に
                    //   ポート 8770 で何か (例えば手動起動したバックエンド) が動いていれば、続く
                    //   health check がそれを拾って正常に window を navigate する。この分岐に来る
                    //   時点では上の事前チェックで「まだ応答していない」ことを確認済みなので、
                    //   ここで拾えるのは spawn 失敗の間に別プロセスが後から立ち上がった場合のみ —
                    //   稀なので警告ダイアログは出さない (エラーダイアログ側でカバーされる)。
                    eprintln!(
                        "tsumugin workbench: sidecar spawn failed ({err}); \
                         falling back to polling for an already-running backend"
                    );
                }
            }
        }
    }

    if wait_for_health(SIDECAR_HOST, SIDECAR_PORT, HEALTHCHECK_TIMEOUT) {
        if let Some(window) = app.get_webview_window("main") {
            let url = format!("http://{SIDECAR_HOST}:{SIDECAR_PORT}");
            match url.parse() {
                Ok(parsed) => {
                    let _ = window.navigate(parsed);
                }
                Err(err) => eprintln!("tsumugin workbench: could not parse backend url: {err}"),
            }
        }
    } else {
        show_backend_unreachable_dialog(app);
    }
}

fn show_backend_unreachable_dialog(app: &AppHandle) {
    app.dialog()
        .message(format!(
            "Tsumugin Workbench backend did not respond within {}s \
             (http://{SIDECAR_HOST}:{SIDECAR_PORT}/api/state).\n\n\
             If this is a dev build, start the backend manually:\n\
             `uv run python -m tsumugin.workbench`\n\n\
             If this is a packaged build, the bundled sidecar failed to start — \
             see desktop/README.md.",
            HEALTHCHECK_TIMEOUT.as_secs()
        ))
        .title("Tsumugin Workbench")
        .kind(MessageDialogKind::Error)
        .blocking_show();
}

/// 【二重起動ガード (V2c レビュー指摘)】: spawn 前チェックで既に何かがポート 8770 に応答して
/// いた場合に表示する警告。エラーではなく続行可能な状態 (この後の health check は既存バックエンド
/// を拾ってそのまま navigate する) なので `MessageDialogKind::Warning`。
fn show_existing_backend_dialog(app: &AppHandle) {
    app.dialog()
        .message(format!(
            "A backend is already responding at http://{SIDECAR_HOST}:{SIDECAR_PORT} — \
             connecting to it instead of starting a new one.\n\n\
             This may be a separate running instance of Tsumugin Workbench, or a leftover \
             process from a previous session that did not shut down cleanly."
        ))
        .title("Tsumugin Workbench")
        .kind(MessageDialogKind::Warning)
        .blocking_show();
}

/// `desktop/src-tauri/binaries/tsumugin-workbench-sidecar-<triple>.exe` を spawn する
/// (`app.path().resource_dir()` 配下, `tauri.conf.json` の `bundle.resources` 経由で
/// バンドルされる — 詳細は desktop/sidecar/build_sidecar.ps1 のコメントを参照)。
///
/// `--parent-pid` に自分自身 (このシェルプロセス) の PID を渡す — sidecar 側 (V2c レビュー指摘)
/// がこれを Windows API で監視し、親 (このプロセス) が強制終了された場合でも自ら終了して孤児化
/// を防ぐ (`kill_sidecar` による通常終了経路とは独立な安全網)。
fn spawn_sidecar(app: &AppHandle) -> Result<Child, String> {
    let exe_path = sidecar_exe_path(app)?;
    Command::new(&exe_path)
        .arg("--host")
        .arg(SIDECAR_HOST)
        .arg("--port")
        .arg(SIDECAR_PORT.to_string())
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .spawn()
        .map_err(|e| format!("failed to spawn {}: {e}", exe_path.display()))
}

fn sidecar_exe_path(app: &AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("could not resolve resource_dir: {e}"))?;
    let exe_name = format!("tsumugin-workbench-sidecar-{}.exe", host_target_triple());
    let path = resource_dir.join("sidecar").join(exe_name);
    if !path.is_file() {
        return Err(format!("sidecar exe not found at {}", path.display()));
    }
    Ok(path)
}

/// `rustc -vV` の host triple 命名と一致させる (`build_sidecar.ps1` が同じ規則で exe をリネーム
/// する)。Tier1 は Windows のみ検証済み (desktop/README.md) — 他プラットフォームは今後の拡張。
fn host_target_triple() -> &'static str {
    if cfg!(all(target_os = "windows", target_arch = "x86_64")) {
        "x86_64-pc-windows-msvc"
    } else if cfg!(all(target_os = "windows", target_arch = "aarch64")) {
        "aarch64-pc-windows-msvc"
    } else if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        "aarch64-apple-darwin"
    } else if cfg!(all(target_os = "macos", target_arch = "x86_64")) {
        "x86_64-apple-darwin"
    } else if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        "x86_64-unknown-linux-gnu"
    } else {
        "unknown"
    }
}

fn kill_sidecar(app: &AppHandle) {
    if let Some(state) = app.try_state::<SidecarProcess>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

/// `GET {host}:{port}/api/state` が 200 を返すまで最大 `timeout` ポーリングする。
///
/// 依存を増やさないため (reqwest/ureq 等の HTTP クライアントを新規追加せず) 素の
/// `std::net::TcpStream` で最小限の HTTP/1.1 リクエストを手組みする — ローカルループバックの
/// liveness 確認用途にはこれで十分 (レスポンスボディは見ず、ステータス行のみ確認)。
fn wait_for_health(host: &str, port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        if http_get_is_200(host, port, "/api/state") {
            return true;
        }
        if Instant::now() >= deadline {
            return false;
        }
        std::thread::sleep(HEALTHCHECK_POLL_INTERVAL);
    }
}

fn http_get_is_200(host: &str, port: u16, path: &str) -> bool {
    let addr = format!("{host}:{port}");
    let mut stream = match TcpStream::connect(&addr) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(3)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(3)));
    let request = format!("GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 32];
    match stream.read(&mut buf) {
        Ok(n) if n > 0 => {
            let head = String::from_utf8_lossy(&buf[..n]);
            head.starts_with("HTTP/1.1 200") || head.starts_with("HTTP/1.0 200")
        }
        _ => false,
    }
}
