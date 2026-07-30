"""M12 T5b: tc.exe ドライバ。

**T0 実測の 2 つの罠**を構造的に潰すことがこのモジュールの主目的:
1. tc.exe は INP の構文エラーで異常終了しても**終了コード 0** を返す。
2. TOPAS は空間群生成で **sgcom6.exe を子プロセス起動**し、PATH からしか引かない。

実 tc.exe を要するテストは 1 本だけ (`@pytest.mark.topas`)。残りは subprocess をスタブ化して
どの機械でも動く。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tsumugin.errors import TopasRunError
from tsumugin.topas import driver as drv


@pytest.fixture()
def fake_topas(tmp_path, monkeypatch):
    """偽 tc.exe を用意し、driver がそれを解決するようにする。"""
    home = tmp_path / "TOPAS7"
    home.mkdir()
    exe = home / "tc.exe"
    exe.write_text("stub")
    # 【TOPAS の目印】: 名前だけでは Linux の /sbin/tc (traffic control) と区別できないため、
    #   マクロ定義ファイルの同居を確認する実装になっている。
    (home / "topas.inc").write_text("' stub macros")
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", str(exe))
    return home, exe


def _stub_run(monkeypatch, *, stdout="Rwp 10.0\n", writes=None, returncode=0, capture=None):
    """subprocess.run をスタブ化し、TOPAS が書くファイルを模擬する。"""

    def fake(cmd, **kwargs):
        if capture is not None:
            capture["cmd"] = cmd
            capture["kwargs"] = kwargs
        cwd = Path(kwargs["cwd"])
        for name, text in (writes or {}).items():
            (cwd / name).write_text(text, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(drv.subprocess, "run", fake)


def test_writes_inp_and_returns_outputs(tmp_path, monkeypatch, fake_topas):
    _stub_run(
        monkeypatch,
        writes={"refine.out": "r_wp 9.5\n", "results.txt": "r_wp\t9.5\n"},
    )
    run = drv.run_tc("iters 1\n", workdir=tmp_path, basename="refine")
    assert (tmp_path / "refine.inp").read_text(encoding="utf-8") == "iters 1\n"
    assert run.out_text == "r_wp 9.5\n"
    assert run.results_text == "r_wp\t9.5\n"


def test_invokes_tc_with_the_basename_only(tmp_path, monkeypatch, fake_topas):
    """tc は拡張子なしのベース名を取る (batch.bat の作法)。"""
    _, exe = fake_topas
    cap: dict = {}
    _stub_run(monkeypatch, writes={"refine.out": "x"}, capture=cap)
    drv.run_tc("iters 1\n", workdir=tmp_path, basename="refine")
    assert cap["cmd"][0] == str(exe)
    assert cap["cmd"][1] == "refine"


def test_topas_home_is_prepended_to_path(tmp_path, monkeypatch, fake_topas):
    """【sgcom6 教訓】: これが無いと空間群生成の子プロセスが引けず異常終了する。"""
    home, _ = fake_topas
    cap: dict = {}
    _stub_run(monkeypatch, writes={"refine.out": "x"}, capture=cap)
    drv.run_tc("iters 1\n", workdir=tmp_path, basename="refine")
    assert cap["kwargs"]["env"]["PATH"].startswith(str(home))


def test_runs_in_the_workdir(tmp_path, monkeypatch, fake_topas):
    """cwd を作業ディレクトリにする (データも results.txt も相対解決される)。"""
    cap: dict = {}
    _stub_run(monkeypatch, writes={"refine.out": "x"}, capture=cap)
    drv.run_tc("iters 1\n", workdir=tmp_path, basename="refine")
    assert Path(cap["kwargs"]["cwd"]) == tmp_path


def test_shell_is_never_used(tmp_path, monkeypatch, fake_topas):
    """リスト形式・shell=False を維持する (インジェクション回避)。"""
    cap: dict = {}
    _stub_run(monkeypatch, writes={"refine.out": "x"}, capture=cap)
    drv.run_tc("iters 1\n", workdir=tmp_path, basename="refine")
    assert isinstance(cap["cmd"], list)
    assert cap["kwargs"].get("shell", False) is False


# ---------------- 失敗検出 (T0 の核心) ----------------


def test_abnormal_termination_raises_even_with_exit_code_zero(tmp_path, monkeypatch, fake_topas):
    """**tc.exe は異常終了でも終了コード 0 を返す** — 終了コードを信じてはならない。

    GSAS-II の `G2Project.refine` が `Refine` の失敗戻り値を捨てる問題と同じクラスの罠。
    """
    _stub_run(
        monkeypatch,
        stdout="Loading topas.inc\n *** Error loading sstring_in\n \nAbnormal program termination.",
        writes={},
        returncode=0,
    )
    with pytest.raises(TopasRunError) as excinfo:
        drv.run_tc("bogus\n", workdir=tmp_path, basename="refine")
    assert "Abnormal program termination" in str(excinfo.value)


def test_missing_sg_file_is_reported_as_failure(tmp_path, monkeypatch, fake_topas):
    """sgcom6 が引けなかったときの典型メッセージも失敗として扱う。"""
    _stub_run(
        monkeypatch,
        stdout=" Cannot open file c:\\topas7\\sg\\r-3c.sg\n \nAbnormal program termination.",
        returncode=0,
    )
    with pytest.raises(TopasRunError, match="Cannot open file"):
        drv.run_tc("x\n", workdir=tmp_path, basename="refine")


def test_missing_out_file_is_a_failure(tmp_path, monkeypatch, fake_topas):
    """異常終了マーカーが無くても .out が生まれていなければ失敗 (二重の網)。"""
    _stub_run(monkeypatch, stdout="something quiet\n", writes={}, returncode=0)
    with pytest.raises(TopasRunError, match="出力"):
        drv.run_tc("x\n", workdir=tmp_path, basename="refine")


def test_nonzero_exit_code_is_a_failure(tmp_path, monkeypatch, fake_topas):
    _stub_run(monkeypatch, writes={"refine.out": "x"}, returncode=3)
    with pytest.raises(TopasRunError):
        drv.run_tc("x\n", workdir=tmp_path, basename="refine")


def test_timeout_is_converted_to_the_domain_error(tmp_path, monkeypatch, fake_topas):
    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(drv.subprocess, "run", boom)
    with pytest.raises(TopasRunError, match="タイムアウト"):
        drv.run_tc("x\n", workdir=tmp_path, basename="refine", timeout=5)


def test_unavailable_topas_raises_the_unavailable_error(tmp_path, monkeypatch):
    from tsumugin.errors import TopasUnavailableError

    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", "none")
    with pytest.raises(TopasUnavailableError):
        drv.run_tc("x\n", workdir=tmp_path, basename="refine")


def test_stdout_is_kept_for_diagnosis(tmp_path, monkeypatch, fake_topas):
    _stub_run(monkeypatch, stdout="  1 Time 0.1 Rwp 12.3\n", writes={"refine.out": "x"})
    run = drv.run_tc("x\n", workdir=tmp_path, basename="refine")
    assert "Rwp 12.3" in run.stdout


def test_missing_results_file_is_tolerated(tmp_path, monkeypatch, fake_topas):
    """results.txt は任意 (.out から指標を拾える)。空文字で返し例外にしない。"""
    _stub_run(monkeypatch, writes={"refine.out": "r_wp 5.0\n"})
    run = drv.run_tc("x\n", workdir=tmp_path, basename="refine")
    assert run.results_text == ""


# ---------------- 実 tc.exe ----------------


@pytest.mark.topas
def test_real_tc_runs_a_minimal_refinement(tmp_path):
    """実 tc.exe で INP → .out/results.txt の往復が成立すること。"""
    import numpy as np

    # 決定論的な合成パターン (単一ガウスピーク + 背景) を .xye で与える
    two_theta = np.arange(20.0, 60.0, 0.02)
    intensity = 100.0 + 5000.0 * np.exp(-0.5 * ((two_theta - 30.0) / 0.15) ** 2)
    lines = [f"{x:.4f} {y:.4f} {max(np.sqrt(y), 1.0):.4f}" for x, y in zip(two_theta, intensity)]
    (tmp_path / "synth.xye").write_text("\n".join(lines) + "\n", encoding="utf-8")

    inp = (
        "r_p 0 r_wp 0 r_exp 0 gof 0\n"
        "iters 20\n"
        'xdd "synth.xye"\n'
        "   bkg @ 0 0\n"
        '   out "results.txt"\n'
        '   Out(Get(r_wp), "r_wp\\t%.8f\\n")\n'
    )
    run = drv.run_tc(inp, workdir=tmp_path, basename="synth_refine")
    from tsumugin.topas.parse import parse_records

    assert "r_wp" in parse_records(run.results_text).scalars
    assert run.out_text  # .out が書き戻されている
