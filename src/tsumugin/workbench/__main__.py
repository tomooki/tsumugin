"""``python -m tsumugin.workbench`` — workbench を配信する開発用エントリ。

【機能概要】: 既定 (引数なし) は空セッション (`WorkbenchSession.create_empty()`, source="none",
Welcome 画面 REQ-GUI-017) を配信する。``--demo`` でシードのデモセッション、``--project`` で実
プロジェクト spec (`load_project_spec`, 従来どおり in-memory ledger) を配信する。`frontend/dist`
(リポジトリ開発時の既定位置) が存在すれば静的配信し、無ければ API のみ。
【非目標】: 配布用エントリポイントではない (Tauri sidecar 梱包は desktop/ 側の責務)。
🟡 信頼性レベル: 開発用途の便宜エントリ (docs/design/gui-workbench/architecture.md §Tauri)。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .app import serve
from .project import load_project_spec
from .session import WorkbenchSession

# 【既定 dist 位置】: src layout のリポジトリ直下 frontend/dist (editable install 開発時のみ有効) 🟡
_DEFAULT_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def main() -> None:
    """CLI 引数を解釈してデモセッションを配信する (ブロッキング)。"""
    parser = argparse.ArgumentParser(description="Tsumugin workbench (demo session)")
    parser.add_argument("--host", default="127.0.0.1", help="バインドホスト (既定 localhost)")
    parser.add_argument("--port", type=int, default=8770, help="ポート (既定 8770)")
    parser.add_argument(
        "--static-dir",
        default=None,
        help="ビルド済み frontend の dist パス (省略時はリポジトリ既定位置を探す)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help=(
            "実プロジェクト spec (JSON, REQ-GUI-012)。省略時は既定で空セッション (Welcome 画面) を配信する。"
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="デモセッション (シード, ハンドオフのプロトタイプ相当) を配信する。--project と併用不可。",
    )
    args = parser.parse_args()
    static_dir: Path | None
    if args.static_dir is not None:
        static_dir = Path(args.static_dir)
    else:
        static_dir = _DEFAULT_DIST if _DEFAULT_DIST.exists() else None

    if args.project is not None:
        try:
            project = load_project_spec(args.project)
        except ValueError as exc:
            print(f"tsumugin workbench: 不正なプロジェクト spec です: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        session: WorkbenchSession = WorkbenchSession.from_project(project)
    elif args.demo:
        session = WorkbenchSession.create_demo()
    else:
        # 【既定 = Welcome (REQ-GUI-017)】: source="none" で起動し、frontend が
        #   新規作成/開く/サンプルの導線を表示する (2026-07-25 方針転換, V2_PLAN.md V2a)。
        session = WorkbenchSession.create_empty()

    serve(
        session,
        host=args.host,
        port=args.port,
        static_dir=static_dir,
    )


if __name__ == "__main__":
    main()
