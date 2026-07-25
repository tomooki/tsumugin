"""Tsumugin Workbench desktop sidecar — PyInstaller エントリポイント (V2c C1, ADR-0001)。

``python -m tsumugin.workbench`` (`src/tsumugin/workbench/__main__.py`) と同じ CLI 契約
(--host/--port/--project/--demo/--static-dir) をそのままパススルーする。差分は唯一
「凍結実行時 (``sys.frozen`` — PyInstaller ビルド後) の既定 static-dir 解決」だけ:

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
import sys
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
    args = parser.parse_args()

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
