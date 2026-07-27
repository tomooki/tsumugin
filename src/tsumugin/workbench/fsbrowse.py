"""アプリ内ファイル選択ウィンドウ用の fs 列挙 API (`docs/design/gui-workbench/api-contract.md`
§ファイル選択 (Welcome のファイル選択ウィンドウ))。

Web ページからは OS のファイルダイアログを開いてもパスを取得できない (``<input type=file>`` は
内容だけでパスを返さない) ため、**バックエンドがディレクトリを列挙し**アプリ内にファイル選択
ウィンドウを描く方式にする。読み取り専用・localhost 前提 — プロジェクトの作成/開くが既に
任意パスを受ける以上、能力の種類は増えない。

numpy 非依存の純標準ライブラリ (コア import 非汚染)。**エージェント境界**: 本モジュールは
``agent_mcp`` から呼ばない (ファイルシステム閲覧はエージェントに渡さない — CLAUDE.md
「②MCP の到達可能性」とは別種の境界で、意図的に非露出)。
"""

from __future__ import annotations

import os
import string
from pathlib import Path
from typing import Any

__all__ = ["list_roots", "list_dir"]


def list_roots() -> list[dict[str, str]]:
    """ホーム + (Windows) 存在するドライブレター / (POSIX) ``/`` を返す。

    ``Path.home()`` は呼び出し時に解決する (テストで monkeypatch 可)。
    """
    roots: list[dict[str, str]] = [{"path": str(Path.home()), "label": "Home"}]
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                roots.append({"path": drive, "label": drive})
    else:
        roots.append({"path": "/", "label": "/"})
    return roots


def _is_project_dir(path: Path) -> bool:
    """``path`` 直下に ``project.json`` があるか (開く先の目印)。

    列挙不能 (権限エラー等) は false に倒す — 個別 entry の判定失敗で一覧全体を落とさない。
    """
    try:
        return (path / "project.json").is_file()
    except OSError:
        return False


def list_dir(path: str) -> dict[str, Any]:
    """``path`` 直下のディレクトリと ``.json`` ファイルのみを列挙する (中身は返さない)。

    :returns: ``{"path": 絶対パス文字列, "parent": 親 or None (ルートなら None), "entries": [...]}``。
        entries はディレクトリ優先・名前昇順。各 entry は
        ``{"name", "path", "is_dir", "is_project"}`` (``is_project`` はファイル entry では常に false)。
    :raises FileNotFoundError: ``path`` が存在しないとき。
    :raises NotADirectoryError: ``path`` がディレクトリでない (ファイル) とき。
    :raises PermissionError: ``path`` 自体の列挙に権限が無いとき (呼び出し側が 422 へ縮退)。
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"パスが存在しません: {path}")
    if not target.is_dir():
        raise NotADirectoryError(f"ディレクトリではありません: {path}")

    resolved = target.resolve()
    parent = resolved.parent
    parent_str = str(parent) if parent != resolved else None

    entries: list[dict[str, Any]] = []
    for child in resolved.iterdir():
        try:
            is_dir = child.is_dir()
        except OSError:
            # 【個別 entry の失敗は握りつぶす】: シンボリックリンク切れ等で 1 件失敗しても
            #   一覧全体を落とさない (契約上の要求)。
            continue
        if is_dir:
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_dir": True,
                    "is_project": _is_project_dir(child),
                }
            )
        elif child.suffix == ".json":
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_dir": False,
                    "is_project": False,
                }
            )
        # 隠しファイル (先頭 ".") も除外しない — .json ファイルは判別可能なので UI 側で
        # 気にせず表示させる方針 (レポート参照)。

    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))

    # 【現在地の is_project】: 「上へ」やルート経由で入ったディレクトリは entry を経由しないため、
    #   entry 側の is_project だけでは UI が「今いる場所がプロジェクトか」を判定できず、
    #   **プロジェクトを開けるのに SELECT が押せない**状態になる (実装レビューで判明)。
    #   現在地についても同じ判定を返す。
    try:
        current_is_project = (resolved / "project.json").is_file()
    except OSError:
        current_is_project = False

    return {
        "path": str(resolved),
        "parent": parent_str,
        "is_project": current_is_project,
        "entries": entries,
    }
