"""マルチスタートの初期値摂動は**精密化するパラメータだけ**に掛ける — engine 側。

摂動の意味は「精密化が初期値から同じ解へ戻ってくるか」の試験である。精密化しない
パラメータ (``PhaseSpec.refine_cell=False`` の格子・``frozen_coord_labels`` の原子) を摂動すると、
**摂動値がそのまま最終解になる**。開始点ごとに違う値で固定されるので、Phase B は副相の
凍結格子や凍結原子の差を**偽のベイスン分岐**として報告し、その相のフィットも摂動値で劣化する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld.engine import _apply_initial_cell_scale
from tsumugin.autorietveld.model import PhaseSpec


class _NamedPhase:
    def __init__(self, name: str) -> None:
        self.name = name


def test_cell_scale_skips_phases_whose_cell_is_frozen():
    """★`refine_cell=False` の相 (Issue #47 の副相格子固定) の格子は摂動しない。

    非トートロジー: cell 段は凍結相に Cell フラグを立てない (`_should_refine_cell`) ので、
    摂動した格子が**そのまま最終格子**になる。認証値で固定した標準試料 (`resolution`) なら
    固定値そのものを壊す。
    """
    calls: list[tuple[str, tuple[float, float, float]]] = []
    phases = [
        PhaseSpec(structure_path="a.cif", phase_name="main"),
        PhaseSpec(structure_path="b.cif", phase_name="minor", refine_cell=False),
    ]
    done = _apply_initial_cell_scale(
        [_NamedPhase("main"), _NamedPhase("minor")],
        phases,
        {"main": (1.01, 1.01, 1.01), "minor": (1.01, 1.01, 1.01)},
        perturb=lambda ph, scale: calls.append((ph.name, scale)),
    )

    assert calls == [("main", (1.01, 1.01, 1.01))], "凍結相の格子を摂動している"
    assert done == ("main",)


def test_cell_scale_ignores_phases_it_was_not_asked_to_scale():
    """【対照】倍率が無い相は触らない (従来動作)。"""
    calls: list[str] = []
    done = _apply_initial_cell_scale(
        [_NamedPhase("main")],
        [PhaseSpec(structure_path="a.cif", phase_name="main")],
        {"other": (1.01, 1.01, 1.01)},
        perturb=lambda ph, scale: calls.append(ph.name),
    )
    assert calls == [] and done == ()


# ---------------------------------------------------------------------------
# 実 GSAS (engine の配線まで): 凍結したものは摂動前の値のまま最後まで残る
# ---------------------------------------------------------------------------

_DATA = Path("docs/benchmark/testdata/m7/labdata")


@pytest.mark.gsas
@pytest.mark.skipif(not (_DATA / "FAP.XRA").exists(), reason="M7 T1 データ未取得")
def test_engine_leaves_frozen_cell_and_frozen_atom_unperturbed():
    """★実 GSAS で `run_auto_rietveld` の配線ごと確かめる (ヘルパー単体では呼び忘れが見えない)。

    背景だけの 1 段で回すので**何も精密化しない** — 最終値 = 摂動後の初期値になる。
    凍結格子・凍結原子は無摂動の run とビット同一、凍結していない原子は動いている (対照)。
    """
    from tsumugin.autorietveld import (
        Geometry,
        HistogramSpec,
        Radiation,
        RefinementStage,
        run_auto_rietveld,
    )

    hist = HistogramSpec(
        data_path=str(_DATA / "FAP.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )
    phase = PhaseSpec(
        structure_path=str(_DATA / "FAP.EXP"),
        phase_name="fap",
        format_hint="EXP",
        refine_cell=False,
        frozen_coord_labels=("O7",),
    )
    recipe = [RefinementStage(label="bg", flags={"background": {"coeffs": 3}})]

    def run(**kw: object):
        return run_auto_rietveld(
            [hist], [phase], recipe=recipe, max_cyc=1, save_gpx=False, **kw
        )

    base = run()
    pert = run(
        initial_cell_scale={"fap": (1.01, 1.01, 1.01)},
        initial_coord_jitter={"fap": 0.05},
        jitter_seed=3,
    )

    assert pert.refined_cells["fap"] == base.refined_cells["fap"], "凍結格子が摂動された"
    assert pert.atom_coords["fap"]["O7"] == base.atom_coords["fap"]["O7"], "凍結原子が摂動された"
    assert pert.atom_coords["fap"]["O5"] != base.atom_coords["fap"]["O5"], (
        "対照: 凍結していない原子は摂動される (摂動そのものが無効化されていないこと)"
    )
