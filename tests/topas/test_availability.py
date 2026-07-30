"""M12 T1: TOPAS 可用性境界 — tc.exe 解決と未導入時の縮退。

`gsasii_available()` / `_dysnomia_available()` と同型の「available + 専用例外」パターン。
**この機械に TOPAS が入っているかで結果が変わってはならない** (CLAUDE.md CI 教訓) ため、
全テストは偽の tc.exe を tmp_path に置き環境変数と探索パスを monkeypatch する。
"""

from __future__ import annotations

import pytest

from tsumugin.errors import TopasUnavailableError
from tsumugin.topas import availability as av


@pytest.fixture()
def fake_tc(tmp_path):
    """実行可能な体裁の偽 tc.exe を作り、その install dir を返す。"""
    home = tmp_path / "TOPAS7"
    home.mkdir()
    exe = home / "tc.exe"
    exe.write_text("stub")
    return home, exe


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """環境変数・既定インストール先・PATH 探索をすべて遮断した状態から始める。"""
    for var in av.TOPAS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(av, "_DEFAULT_INSTALL_DIRS", ())
    monkeypatch.setattr(av.shutil, "which", lambda _name: None)


def test_unavailable_when_nothing_is_found():
    assert av.resolve_tc_exe() is None
    assert av.topas_available() is False


def test_env_var_pointing_at_the_executable(monkeypatch, fake_tc):
    _, exe = fake_tc
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", str(exe))
    assert av.resolve_tc_exe() == exe
    assert av.topas_available() is True


def test_env_var_pointing_at_the_install_directory(monkeypatch, fake_tc):
    """ディレクトリを与えても中の tc.exe を見つける (利用者はどちらでも書く)。"""
    home, exe = fake_tc
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", str(home))
    assert av.resolve_tc_exe() == exe


def test_env_var_precedence(monkeypatch, tmp_path, fake_tc):
    """TSUMUGIN_TOPAS_PATH が TOPAS_PATH より優先される。"""
    _, preferred = fake_tc
    other_home = tmp_path / "TOPAS6"
    other_home.mkdir()
    (other_home / "tc.exe").write_text("stub")
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", str(preferred))
    monkeypatch.setenv("TOPAS_PATH", str(other_home))
    assert av.resolve_tc_exe() == preferred


def test_falls_back_to_default_install_dirs(monkeypatch, fake_tc):
    home, exe = fake_tc
    monkeypatch.setattr(av, "_DEFAULT_INSTALL_DIRS", (home,))
    assert av.resolve_tc_exe() == exe


def test_falls_back_to_path_lookup(monkeypatch, fake_tc):
    _, exe = fake_tc
    monkeypatch.setattr(av.shutil, "which", lambda name: str(exe) if name == "tc" else None)
    assert av.resolve_tc_exe() == exe


def test_stale_env_var_does_not_resolve(monkeypatch, tmp_path):
    """指定されたパスに tc.exe が無ければ None (存在しないパスを握って先へ進まない)。"""
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", str(tmp_path / "nope"))
    assert av.resolve_tc_exe() is None


def test_explicit_env_var_does_not_fall_back(monkeypatch, tmp_path, fake_tc):
    """【明示指定は権威的】: 環境変数が外れていても、別の TOPAS を黙って掴まない。

    フォールバックすると「指定したのと違う版で回っていた」が Rwp に現れないまま起きる。
    """
    home, _ = fake_tc
    monkeypatch.setattr(av, "_DEFAULT_INSTALL_DIRS", (home,))  # 既定は解決可能な状態にしておく
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", str(tmp_path / "nope"))
    assert av.resolve_tc_exe() is None


@pytest.mark.parametrize("value", ["none", "OFF", "0", "disabled"])
def test_env_var_can_force_disable(monkeypatch, fake_tc, value):
    """TOPAS 導入済みの機械でも未導入時の縮退経路を検証できること (skip ガードの実証手段)。"""
    home, _ = fake_tc
    monkeypatch.setattr(av, "_DEFAULT_INSTALL_DIRS", (home,))
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", value)
    assert av.resolve_tc_exe() is None
    assert av.topas_available() is False


def test_topas_home_is_the_directory_holding_tc(monkeypatch, fake_tc):
    """【sgcom6 教訓】: TOPAS は空間群生成で sgcom6.exe を子プロセス起動するため、
    driver は tc.exe と同じディレクトリを PATH へ足す必要がある。その解決を home が担う。
    """
    home, exe = fake_tc
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", str(exe))
    assert av.topas_home() == home


def test_topas_home_is_none_when_unavailable():
    assert av.topas_home() is None


def test_require_tc_exe_raises_the_dedicated_error():
    with pytest.raises(TopasUnavailableError) as excinfo:
        av.require_tc_exe()
    # 導入手順を案内する (GSASUnavailableError と同型の親切さ)
    assert "TSUMUGIN_TOPAS_PATH" in str(excinfo.value)


def test_require_tc_exe_returns_path_when_available(monkeypatch, fake_tc):
    _, exe = fake_tc
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", str(exe))
    assert av.require_tc_exe() == exe


def test_describe_is_json_safe_for_layer2(monkeypatch, fake_tc):
    """② の `list_refinement_backends` が返す素の dict (JSON 化可能・例外を出さない)。"""
    _, exe = fake_tc
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", str(exe))
    info = av.describe()
    assert info == {"available": True, "tc_path": str(exe), "home": str(exe.parent)}


def test_describe_when_unavailable_states_how_to_enable():
    info = av.describe()
    assert info["available"] is False
    assert info["tc_path"] is None
    assert "TSUMUGIN_TOPAS_PATH" in info["hint"]


def test_unavailable_error_is_a_tsumugin_error():
    from tsumugin.errors import TsumuginError

    assert issubclass(TopasUnavailableError, TsumuginError)
