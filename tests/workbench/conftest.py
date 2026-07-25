"""workbench テスト共通 fixture。

【背景】: recent プロジェクト一覧は ``Path.home()/.tsumugin`` に書かれる。個別テストの
monkeypatch 漏れが 1 つでもあると**実ユーザーの home を汚す** (実害: pytest tmp パスが
実 ``workbench_recent.json`` に混入し Welcome 画面の recent に露出した)。テスト側の規律に
依存せず、autouse fixture で workbench テスト全体の home を tmp へ隔離する。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """全 workbench テストで ``Path.home()`` をテスト専用ディレクトリへ差し替える。"""
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    return fake_home
