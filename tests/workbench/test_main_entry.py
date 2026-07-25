"""``python -m tsumugin.workbench`` の CLI エントリ (`tsumugin.workbench.__main__.main`) のテスト。

`serve` を呼び出す副作用を monkeypatch で潰し、CLI 引数 → `serve()` 呼び出し引数の写像だけを
検証する (実 uvicorn は起動しない)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.workbench import __main__ as entry


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
