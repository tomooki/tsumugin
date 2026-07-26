"""``python -m tsumugin.workbench`` の CLI エントリ (`tsumugin.workbench.__main__.main`) のテスト。

`serve` を呼び出す副作用を monkeypatch で潰し、CLI 引数 → `serve()` 呼び出し引数の写像だけを
検証する (実 uvicorn は起動しない)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.workbench import __main__ as entry
from tsumugin.workbench.session import WorkbenchSession


@pytest.fixture()
def fake_serve(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []

    def _fake_serve(session, *, host: str, port: int, static_dir):
        calls.append({"session": session, "host": host, "port": port, "static_dir": static_dir})

    monkeypatch.setattr(entry, "serve", _fake_serve)
    return calls


def test_main_uses_default_host_and_port(monkeypatch: pytest.MonkeyPatch, fake_serve):
    monkeypatch.setattr("sys.argv", ["tsumugin-workbench"])
    # 既定 dist が存在する環境依存を避けるため、常に無い扱いに固定する。
    monkeypatch.setattr(entry, "_DEFAULT_DIST", Path("no-such-dist-dir"))

    entry.main()

    assert len(fake_serve) == 1
    assert fake_serve[0]["host"] == "127.0.0.1"
    assert fake_serve[0]["port"] == 8770


def test_main_passes_static_dir_as_path_when_specified(
    monkeypatch: pytest.MonkeyPatch, fake_serve, tmp_path
):
    monkeypatch.setattr("sys.argv", ["tsumugin-workbench", "--static-dir", str(tmp_path)])

    entry.main()

    assert len(fake_serve) == 1
    static_dir = fake_serve[0]["static_dir"]
    assert isinstance(static_dir, Path)
    assert static_dir == tmp_path


def test_main_uses_default_dist_when_it_exists_and_unspecified(
    monkeypatch: pytest.MonkeyPatch, fake_serve, tmp_path
):
    monkeypatch.setattr("sys.argv", ["tsumugin-workbench"])
    monkeypatch.setattr(entry, "_DEFAULT_DIST", tmp_path)  # tmp_path exists

    entry.main()

    assert len(fake_serve) == 1
    assert fake_serve[0]["static_dir"] == tmp_path


def test_main_uses_none_static_dir_when_default_dist_missing_and_unspecified(
    monkeypatch: pytest.MonkeyPatch, fake_serve
):
    monkeypatch.setattr("sys.argv", ["tsumugin-workbench"])
    monkeypatch.setattr(entry, "_DEFAULT_DIST", Path("no-such-dist-dir-either"))

    entry.main()

    assert len(fake_serve) == 1
    assert fake_serve[0]["static_dir"] is None


# ---------------------------------------------------------------------------
# セッション既定 (V2a: 引数なし = 空 (Welcome) / --demo = デモ / --project = 実プロジェクト)
# ---------------------------------------------------------------------------


def test_main_without_args_serves_empty_session(monkeypatch: pytest.MonkeyPatch, fake_serve):
    monkeypatch.setattr("sys.argv", ["tsumugin-workbench"])
    monkeypatch.setattr(entry, "_DEFAULT_DIST", Path("no-such-dist-dir"))

    entry.main()

    assert len(fake_serve) == 1
    session = fake_serve[0]["session"]
    assert isinstance(session, WorkbenchSession)
    assert session.source == "none"


def test_main_with_demo_flag_serves_demo_session(monkeypatch: pytest.MonkeyPatch, fake_serve):
    monkeypatch.setattr("sys.argv", ["tsumugin-workbench", "--demo"])
    monkeypatch.setattr(entry, "_DEFAULT_DIST", Path("no-such-dist-dir"))

    entry.main()

    assert len(fake_serve) == 1
    session = fake_serve[0]["session"]
    assert session.source == "demo"


# ---------------------------------------------------------------------------
# アプリ設定 (資格情報): 起動時に保存済み MP キーをプロセス env へ反映する
# (api-contract.md §アプリ設定「保存時にプロセスの環境変数へも反映」— 起動時も同じ扱い)
# ---------------------------------------------------------------------------


def test_main_applies_saved_mp_api_key_to_env_at_startup(
    monkeypatch: pytest.MonkeyPatch, fake_serve, _isolated_home
):
    # 【home 隔離】: `tests/workbench/conftest.py` の autouse fixture (`_isolated_home`) が
    #   ``Path.home()`` を既に隔離済み — ここでは同じ隔離先を明示依存として受け取るだけでよい。
    monkeypatch.delenv("MATERIALS_PROJECT_API", raising=False)

    from tsumugin.workbench import settings as settings_module

    settings_module.save_setting("mp_api_key", "sk-startup-applied")

    monkeypatch.setattr("sys.argv", ["tsumugin-workbench"])
    monkeypatch.setattr(entry, "_DEFAULT_DIST", Path("no-such-dist-dir"))

    entry.main()

    import os

    assert os.environ.get("MATERIALS_PROJECT_API") == "sk-startup-applied"
