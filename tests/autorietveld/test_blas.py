"""fit-then-judge P1-1B タスク 3: BLAS のスレッド数の固定 (`run_auto_rietveld(blas_threads=)`)。

悪条件の最小二乗は総和順序で結果が揺れる (TOPAS で実測した非決定性と同型)。テンプレートの再現性 (NFR-102)
のためにスレッド数を固定する。プロセス全体に効くので既定は無効。
"""

from __future__ import annotations

import inspect

import pytest

from tsumugin.autorietveld.blas import blas_thread_report, with_blas_threads


def test_the_limit_is_active_inside_and_released_after():
    threadpoolctl = pytest.importorskip("threadpoolctl")
    import numpy  # noqa: F401 — BLAS を読み込ませる

    seen: list[dict] = []

    @with_blas_threads
    def run(*, blas_threads=None):
        seen.append(blas_thread_report(blas_threads))
        return "ok"

    before = [i["num_threads"] for i in threadpoolctl.threadpool_info() if i["user_api"] == "blas"]
    assert run(blas_threads=1) == "ok"
    rep = seen[0]
    assert rep["requested"] == 1 and rep["observed"] and set(rep["observed"]) == {1}
    assert rep["ok"] is True
    after = [i["num_threads"] for i in threadpoolctl.threadpool_info() if i["user_api"] == "blas"]
    assert after == before


def test_none_does_not_touch_the_thread_pools():
    calls = []

    @with_blas_threads
    def run(*, blas_threads=None):
        calls.append(blas_threads)

    run()
    run(blas_threads=None)
    assert calls == [None, None]


@pytest.mark.parametrize("bad", [0, -1, 1.5, "1", True])
def test_invalid_thread_counts_are_refused(bad):
    @with_blas_threads
    def run(*, blas_threads=None):
        raise AssertionError("走ってはならない")

    with pytest.raises(ValueError):
        run(blas_threads=bad)


def test_a_report_without_a_detected_blas_is_not_ok(monkeypatch):
    """BLAS を検出できなかったら「固定できた」と答えない。"""
    import tsumugin.autorietveld.blas as blas

    monkeypatch.setattr(blas, "_blas_infos", lambda: [])
    rep = blas.blas_thread_report(1)
    assert rep["ok"] is False and rep["observed"] == []


def test_the_engine_exposes_the_argument():
    from tsumugin.autorietveld.engine import run_auto_rietveld

    assert inspect.signature(run_auto_rietveld).parameters["blas_threads"].default is None


def test_the_engine_refuses_a_bad_count_before_doing_anything():
    """engine が制限で包まれていること (引数だけあって効かない、を防ぐ)。"""
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation

    h = HistogramSpec(
        data_path="d.xye", instrument_path="i.instprm",
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
    )
    with pytest.raises(ValueError, match="blas_threads"):
        run_auto_rietveld([h], [PhaseSpec("a.cif", "A")], blas_threads=0, save_gpx=False)
