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


@pytest.fixture(autouse=True)
def _isolated_dotenv_mp_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` の MP キーをテストから隔離する (既定は「未設定」)。

    【背景】: `settings.mp_api_key_status` は ``MPRestClient`` と同じ順序で env → `.env` を
    見る。隔離しないと**開発者のリポジトリに .env があるかどうかでテスト結果が変わる**
    (実際に「未設定」を期待するテストが実 .env を拾って落ちた)。`.env` 由来の挙動を検証したい
    テストは自分で ``monkeypatch.setattr(settings, "_read_dotenv_mp_key", ...)`` を上書きする。
    """
    from tsumugin.workbench import settings as _settings

    monkeypatch.setattr(_settings, "_read_dotenv_mp_key", lambda: None)
