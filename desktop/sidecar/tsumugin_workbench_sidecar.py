"""Tsumugin Workbench desktop sidecar — PyInstaller エントリポイント (V2c C1, ADR-0001)。

``python -m tsumugin.workbench`` (`src/tsumugin/workbench/__main__.py`) と同じ CLI 契約
(--host/--port/--project/--demo/--static-dir) をそのままパススルーする。差分は
「凍結実行時 (``sys.frozen`` — PyInstaller ビルド後) の既定 static-dir 解決」と
「``--parent-pid`` (V2c レビュー指摘): 親プロセス (Tauri シェル) の PID を受け取り、その終了を
Windows API で監視して自ら終了する孤児化防止ウォッチドッグ (``_watch_parent_pid`` 参照) 」の 2 点:

* 開発時 (``uv run python desktop/sidecar/tsumugin_workbench_sidecar.py``): リポジトリ直下
  ``frontend/dist`` を探す (``__main__.py`` の ``_DEFAULT_DIST`` と同じ探索)。
* 凍結実行時: PyInstaller が ``sidecar.spec`` の ``datas`` で同梱した
  ``frontend_dist/`` (one-dir 展開先, ``sys._MEIPASS`` 配下) を使う。

Tier1 = コア + web extra のみ同梱。GSAS-II はローカル導入前提 (desktop/README.md) —
本エントリ自体は GSAS の有無を問わない (未導入でも起動し、GET /api/state の
``status.gsas_available`` で可否を表明する。GSAS 必須ジョブは
``WorkbenchSession._guard_gsas_available`` が 422 へ縮退させる, `src/tsumugin/workbench/session.py`)。

配布用エントリポイントはこのファイル (``desktop/`` の責務)。開発用の
``python -m tsumugin.workbench`` は空/デモセッションの簡便な配信に留める従来どおりの役割
(`src/tsumugin/workbench/__main__.py` docstring 参照)。
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

# 【sys.path 補強】: PyInstaller は ``src/tsumugin`` を hiddenimports 経由でパッケージ化するため
#   通常は不要だが、開発時 (uv run で本ファイルを直接実行) に src layout の editable install が
#   無い環境でも動くよう保険で足す (副作用なし: 既に import 可能なら何もしない)。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path and (_SRC_DIR / "tsumugin").is_dir():
    sys.path.insert(0, str(_SRC_DIR))

from tsumugin.workbench.app import serve  # noqa: E402
from tsumugin.workbench.project import load_project_spec  # noqa: E402
from tsumugin.workbench.session import WorkbenchSession  # noqa: E402


def _default_static_dir() -> "Path | None":
    """既定 frontend dist を解決する (凍結実行時は同梱物、開発時はリポジトリ既定位置)。"""
    frozen = bool(getattr(sys, "frozen", False))
    meipass = getattr(sys, "_MEIPASS", None)
    if frozen and meipass is not None:
        bundled = Path(meipass) / "frontend_dist"
        if bundled.is_dir():
            return bundled
        return None
    dev_dist = _REPO_ROOT / "frontend" / "dist"
    return dev_dist if dev_dist.is_dir() else None


def _watch_parent_pid(pid: int) -> None:
    """親プロセス (Tauri シェル) の終了を監視し、検知したら即座に自プロセスを終了する。

    【背景 (V2c レビュー指摘: 孤児 sidecar)】: ``src-tauri/src/lib.rs`` は素の
    ``std::process::Command`` で本プロセスを spawn する (``tauri-plugin-shell`` の
    ``sidecar()`` は使わない — ファイル冒頭 docstring 参照)。この spawn 方式は Windows の
    ジョブオブジェクト等に紐付かないため、親 (Tauri シェル) をタスクマネージャ等で強制終了
    (通常の ``RunEvent::Exit``/``ExitRequested`` を経由しない終了) された場合、本プロセスは
    誰にも kill されず孤児化して起動し続けてしまう。この関数はその安全網: 親 PID を
    Windows API (``OpenProcess`` + ``WaitForSingleObject``) で直接監視し、親のプロセス
    ハンドルがシグナル状態になった (= 終了した) 時点で ``os._exit(0)`` する。

    ``os._exit`` を使う理由: 通常の ``sys.exit``/例外送出は Python の finally/atexit を
    経由し、uvicorn のシャットダウンハンドラ等でブロックしうる — 親が既に消えている状況で
    悠長なグレースフルシャットダウンを待つ意味は無く、即座に終わらせる。

    Windows 専用 (``ctypes.windll`` — Tier1 は Windows のみ検証対象, desktop/README.md)。
    別スレッド (daemon) から呼ばれる想定 — ``main()`` 参照。
    """
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    synchronize = 0x00100000  # SYNCHRONIZE アクセス権
    infinite = 0xFFFFFFFF
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        # 【親が既に不在】: 指定された pid が無効、または本プロセスの起動より先に親が終了して
        #   いた場合。監視対象が存在しないので、これ以上生き続ける理由も無い。
        print(
            f"tsumugin workbench sidecar: parent pid={pid} could not be opened "
            "(already exited?) — shutting down",
            file=sys.stderr,
            flush=True,
        )
        os._exit(0)
        return

    print(
        f"tsumugin workbench sidecar: watching parent pid={pid} for orphan detection",
        file=sys.stderr,
        flush=True,
    )
    kernel32.WaitForSingleObject(handle, infinite)
    kernel32.CloseHandle(handle)
    print(
        f"tsumugin workbench sidecar: parent pid={pid} exited — shutting down to avoid orphaning",
        file=sys.stderr,
        flush=True,
    )
    os._exit(0)


def main() -> None:
    """CLI 引数を解釈してワークベンチを配信する (ブロッキング)。

    ``tsumugin.workbench.__main__.main`` と同一の引数契約 (Tauri sidecar が
    ``--port``/``--project`` を渡す, ``src-tauri/src/lib.rs`` 参照)。
    """
    parser = argparse.ArgumentParser(
        description="Tsumugin Workbench desktop sidecar (PyInstaller entry, ADR-0001)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="バインドホスト (既定 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8770, help="ポート (既定 8770)")
    parser.add_argument(
        "--static-dir",
        default=None,
        help="ビルド済み frontend の dist パス (省略時は同梱物/リポジトリ既定位置を探す)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="実プロジェクト spec (JSON, REQ-GUI-012)。省略時は既定で空セッション (Welcome 画面)。",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="デモセッションを配信する。--project と併用不可。",
    )
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=None,
        help=(
            "親プロセス (Tauri シェル) の PID。指定すると Windows API で親の終了を監視し、"
            "強制終了などで親が消えた場合に自ら終了する (孤児化防止, V2c レビュー指摘, Windows 専用)。"
        ),
    )
    args = parser.parse_args()

    if args.parent_pid is not None:
        if sys.platform == "win32":
            threading.Thread(
                target=_watch_parent_pid, args=(args.parent_pid,), daemon=True
            ).start()
        else:
            print(
                "tsumugin workbench sidecar: --parent-pid is only supported on Windows "
                f"(sys.platform={sys.platform!r}); ignoring",
                file=sys.stderr,
            )

    static_dir: "Path | None"
    if args.static_dir is not None:
        static_dir = Path(args.static_dir)
    else:
        static_dir = _default_static_dir()

    if args.project is not None:
        try:
            project = load_project_spec(args.project)
        except ValueError as exc:
            print(f"tsumugin workbench sidecar: 不正なプロジェクト spec です: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        session: WorkbenchSession = WorkbenchSession.from_project(project)
    elif args.demo:
        session = WorkbenchSession.create_demo()
    else:
        session = WorkbenchSession.create_empty()

    # 【起動ログ】: Tauri 側のヘルスチェック (lib.rs) はポーリングのみで stdout を見ないが、
    #   手動起動デバッグ (検証手順 (b)) で凍結 exe の挙動を目視確認できるよう明示する。
    print(
        f"tsumugin workbench sidecar: listening on http://{args.host}:{args.port} "
        f"(static_dir={static_dir}, frozen={bool(getattr(sys, 'frozen', False))})",
        file=sys.stderr,
    )

    serve(session, host=args.host, port=args.port, static_dir=static_dir)


if __name__ == "__main__":
    main()
