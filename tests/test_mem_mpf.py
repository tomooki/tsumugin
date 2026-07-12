"""mem.mpf (実データ MEM-Rietveld 反復 / MPF) の TDD テスト (REQ-024/025/026/107)。

numpy-only の決定論コア (設定 / 停止判定 / 相対変化 / 既定オフ) を GSAS 非依存で検証し、
実 MPF ループ (Rietveld 再精密化 → 実 Dysnomia MEM → 収束判定) は @pytest.mark.gsas +
Dysnomia/データ存在で gate する。
"""
from __future__ import annotations

import dataclasses
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from tsumugin.mem.mpf import (
    MPFConfig,
    MPFCycle,
    MPFResult,
    _decide_stop,
    _relative_change,
    run_mem_rietveld_gpx,
)


# ---------------------------------------------------------------------------
# (A) MPFConfig / dataclasses
# ---------------------------------------------------------------------------


def test_config_defaults():
    c = MPFConfig()
    assert c.enabled is False          # 既定オフ (REQ-024)
    assert c.max_iter == 5
    assert c.rwp_tol == pytest.approx(1e-3)
    assert c.density_tol == pytest.approx(1e-3)
    assert c.refine_max_cyc == 5
    assert c.unmodeled_distance == pytest.approx(0.8)


def test_config_frozen():
    assert dataclasses.is_dataclass(MPFConfig)
    with pytest.raises(FrozenInstanceError):
        MPFConfig().max_iter = 9  # type: ignore[misc]


def test_cycle_and_result_frozen():
    cyc = MPFCycle(iteration=0, gpx_path="a.gpx", rwp=10.0, density_max=5.0,
                   density_min=-1.0, mem_r_factor=None, n_unmodeled=0)
    with pytest.raises(FrozenInstanceError):
        cyc.rwp = 1.0  # type: ignore[misc]
    res = MPFResult(cycles=(cyc,), stop_reason="converged")
    with pytest.raises(FrozenInstanceError):
        res.stop_reason = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# (B) _relative_change
# ---------------------------------------------------------------------------


def test_relative_change_basic():
    assert _relative_change(10.0, 10.0) == pytest.approx(0.0)
    assert _relative_change(10.0, 11.0) == pytest.approx(0.1)


def test_relative_change_zero_prev():
    # prev=0 は分母クランプで発散しない
    v = _relative_change(0.0, 1.0)
    assert np.isfinite(v)


# ---------------------------------------------------------------------------
# (C) _decide_stop (収束/発散/継続の純判定)
# ---------------------------------------------------------------------------


def _cyc(it, rwp, dmax):
    return MPFCycle(iteration=it, gpx_path=f"{it}.gpx", rwp=rwp, density_max=dmax,
                    density_min=-1.0, mem_r_factor=None, n_unmodeled=0)


def test_decide_stop_converged():
    cfg = MPFConfig(rwp_tol=1e-2, density_tol=1e-2)
    prev = _cyc(0, 10.0, 5.0)
    cur = _cyc(1, 10.02, 5.01)   # 両方 < tol
    assert _decide_stop(prev, cur, cfg) == "converged"


def test_decide_stop_continue_when_rwp_moving():
    cfg = MPFConfig(rwp_tol=1e-3, density_tol=1e-3)
    prev = _cyc(0, 10.0, 5.0)
    cur = _cyc(1, 9.0, 5.0)      # Rwp 改善中 (>tol) → 継続
    assert _decide_stop(prev, cur, cfg) is None


def test_decide_stop_diverged_on_rwp_worsening():
    cfg = MPFConfig(rwp_tol=1e-3, density_tol=1e-3, worsen_eps=1e-3)
    prev = _cyc(0, 10.0, 5.0)
    cur = _cyc(1, 10.5, 5.0)     # Rwp 悪化 → 発散
    assert _decide_stop(prev, cur, cfg) == "diverged"


def test_decide_stop_density_not_converged():
    cfg = MPFConfig(rwp_tol=1e-2, density_tol=1e-3)
    prev = _cyc(0, 10.0, 5.0)
    cur = _cyc(1, 10.0, 6.0)     # Rwp 収束だが密度変化大 → 継続
    assert _decide_stop(prev, cur, cfg) is None


# ---------------------------------------------------------------------------
# (D) 既定オフ (REQ-024): enabled=False は即 disabled で子スナップショットなし
# ---------------------------------------------------------------------------


def test_disabled_returns_immediately(tmp_path):
    fake = tmp_path / "x.gpx"
    fake.write_text("stub")
    res = run_mem_rietveld_gpx(str(fake), config=MPFConfig(enabled=False))
    assert res.stop_reason == "disabled"
    assert res.cycles == ()


# ---------------------------------------------------------------------------
# (E) @gsas: 実 MPF smoke (T1 実データ)
# ---------------------------------------------------------------------------

_T1 = Path("docs/benchmark/testdata/m7/labdata")


def _dysnomia_present() -> bool:
    from tsumugin.mem.gsas import resolve_dysnomia_binary

    return resolve_dysnomia_binary() is not None


@pytest.mark.gsas
@pytest.mark.skipif(not _dysnomia_present(), reason="Dysnomia バイナリ未検出")
@pytest.mark.skipif(not (_T1 / "FAP.XRA").exists(), reason="M7 T1 データ未取得")
def test_real_mpf_smoke(tmp_path):
    from tsumugin.autorietveld import (
        Geometry, HistogramSpec, PhaseSpec, Radiation,
    )
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.store.ledger import Ledger

    gpx = tmp_path / "t1.gpx"
    hist = HistogramSpec(
        data_path=str(_T1 / "FAP.XRA"), instrument_path=str(_T1 / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="GSAS",
    )
    phase = PhaseSpec(structure_path=str(_T1 / "FAP.EXP"), phase_name="fap",
                      format_hint="EXP")
    run_auto_rietveld([hist], [phase], keep_gpx=str(gpx))

    ledger = Ledger()
    res = run_mem_rietveld_gpx(
        str(gpx), config=MPFConfig(enabled=True, max_iter=3, refine_max_cyc=3),
        snapshot_dir=str(tmp_path / "mpf"), ledger=ledger,
    )
    assert isinstance(res, MPFResult)
    assert res.stop_reason in ("converged", "max_iter", "diverged")
    assert len(res.cycles) >= 1
    # 各サイクルは独立の子スナップショット gpx (P2: 上書きしない)
    paths = [c.gpx_path for c in res.cycles]
    assert len(set(paths)) == len(paths)
    for c in res.cycles:
        assert Path(c.gpx_path).exists()
        assert np.isfinite(c.rwp) and np.isfinite(c.density_max)
    # ledger 追記 (verify 保持)
    assert ledger.verify()
