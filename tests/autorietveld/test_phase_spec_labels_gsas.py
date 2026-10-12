"""相の指定のラベル検査 — **実 GSAS-II** で (@pytest.mark.gsas, PbSO4 実データ)。

速いティア (`test_phase_spec_labels.py`) は偽の GSAS で配線を測る。ここでは GSAS の CIF
インポータが実際に読んだラベルと突き合わせること、② が JSON 引数だけで error dict を返すこと、
そして**拒否しない側** (1 原子を 2 つの占有率拘束に入れる) を GSAS が両方満たすことを固定する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.autorietveld.model import RefinementStage
from tsumugin.errors import InvalidPhaseSpecError

_DATA = Path("docs/benchmark/testdata")

pytestmark = [
    pytest.mark.gsas,
    pytest.mark.skipif(
        not ((_DATA / "PBSO4.XRA").exists() and (_DATA / "PbSO4-Wyckoff.cif").exists()),
        reason="PbSO4 データ未取得",
    ),
]


def _hist() -> HistogramSpec:
    return HistogramSpec(
        data_path=str(_DATA / "PBSO4.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )


def _phase(**kw) -> PhaseSpec:
    return PhaseSpec(
        structure_path=str(_DATA / "PbSO4-Wyckoff.cif"), phase_name="PbSO4", **kw
    )


def test_real_gsas_refuses_a_misspelled_freeze_before_refinement():
    """綴り違いの凍結 (``"Pb "``) は以前は**何も凍結せずに完走**していた (Pb の Uiso が精密化
    される)。エラー文に GSAS が読んだ原子ラベルが並ぶ (③ はそれを見て直す)。"""
    with pytest.raises(InvalidPhaseSpecError) as excinfo:
        run_auto_rietveld([_hist()], [_phase(frozen_uiso_labels=("Pb ",))], save_gpx=False)
    message = str(excinfo.value)
    assert "'Pb '" in message
    assert "['Pb', 'S', 'O1', 'O2', 'O3']" in message


def test_layer_two_degrades_the_refusal_on_the_default_backend():
    """③ が実際に通る経路 (**JSON 引数だけ**・既定バックエンド) で error dict になる。"""
    from tsumugin.mcp import rietveld_tools

    hist = _hist().to_dict()
    phase = _phase(position_equiv_groups=(("O1", "Ox"),)).to_dict()
    for tool, args in (
        (rietveld_tools.auto_rietveld, ([hist], [phase])),
        (rietveld_tools.refine_with_revisions, ([hist], [phase], [])),
    ):
        out = tool(*args, save_gpx=False)
        assert out.get("error_type") == "InvalidPhaseSpecError", (tool.__name__, out)
        assert "Ox" in out["error"]


def test_real_gsas_keeps_an_atom_in_two_occupancy_constraints():
    """拒否しない側: GSAS は混合占有 (O1 + O2 = 1) と等値 (O1 = O3) を**同時に**満たす
    (equivalence を constraint に変換する)。TOPAS の INP は原子ごとに占有率を 1 つの式で書くので
    この形は TOPAS だけが拒否する — この規則をエンジン共通の検査へ上げると、GSAS で意味の決まる
    指定を壊す (`deuterium.place_hd_mix` の親水 O が 2 つの和の組の親になる形は、TOPAS も
    最後の子を「親 − 他の子」の式にして張る)。

    PbSO4 の O 占有率に物理的な意味は無い (拘束の機構の試験)。O は本来満占有なので O1 + O2 = 1 を
    課すと Rwp は悪化し、段は revert される — 悪化判定を外して拘束の解を読む (``worsen_eps``)。
    """
    stages = (
        RefinementStage(label="sb", flags={"scale": True, "background": {"coeffs": 6}}),
        RefinementStage(label="occ", flags={"occupancy": True}),
    )
    result = run_auto_rietveld(
        [_hist()],
        [_phase(mixed_occupancy_groups=(("O1", "O2"),), occupancy_equiv_groups=(("O1", "O3"),))],
        recipe=stages,
        save_gpx=False,
        worsen_eps=1e9,
    )
    occ = result.atom_occupancy["PbSO4"]
    occ_stage = next(s for s in result.stage_results if s.label == "occ")
    assert not occ_stage.reverted, occ_stage.note
    assert occ["O1"] != pytest.approx(1.0, abs=1e-3), "占有率が動いていない (拘束の試験にならない)"
    assert occ["O1"] + occ["O2"] == pytest.approx(1.0, abs=1e-6)
    assert occ["O1"] == pytest.approx(occ["O3"], abs=1e-6)


_CWCOMBINED = _DATA / "m7" / "cwcombined"


@pytest.mark.skipif(
    not all((_CWCOMBINED / name).is_file()
            for name in ("PBSO4.XRA", "INST_XRY.PRM", "PBSO4.CWN", "inst_d1a.prm")),
    reason="PbSO4 X 線 + CW 中性子の実データが無い (gitignore 対象)",
)
def test_real_gsas_shared_parent_sum_groups_keep_variables_minus_constraints(tmp_path):
    """**自由度の照合の GSAS 側**: `deuterium.place_hd_mix` の形 (親水 O が 2 つの和の組の親) で、
    占有率段が足す母数が 5 原子 − 2 拘束 = 3 であり、両方の和が成り立つ。

    TOPAS 側は `tests/topas/test_phase_spec_fields.py::test_real_tc_holds_both_sums_of_a_shared_parent`
    が同じ入力の S0 → 占有率段の母数増で 3 を固定している (TOPAS 側は持ち越しを見るために後ろへ
    もう 1 段足してあるので、最終の n_params や Rwp は比べない)。両方を固定しないと
    「GSAS と同じ自由度」は式の上の主張でしかなく、`n_params` が入る BIC (相数・モデル比較) が
    エンジンで食い違っても気づけない。
    PbSO4 に水素は無い — 拘束の機構の試験 (X 線では D と H が区別できないので中性子と joint)。
    """
    from tsumugin.autorietveld.deuterium import place_hd_mix

    cif, pos_equiv, occ_sum = place_hd_mix(
        _DATA / "PbSO4-Wyckoff.cif", ["O1"], tmp_path / "hd.cif", deuteration=0.7,
        phase_name="PbSO4",
    )
    result = run_auto_rietveld(
        [
            HistogramSpec(data_path=str(_CWCOMBINED / "PBSO4.XRA"),
                          instrument_path=str(_CWCOMBINED / "INST_XRY.PRM"),
                          radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                          data_format="GSAS"),
            HistogramSpec(data_path=str(_CWCOMBINED / "PBSO4.CWN"),
                          instrument_path=str(_CWCOMBINED / "inst_d1a.prm"),
                          radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER,
                          data_format="GSAS"),
        ],
        [PhaseSpec(str(cif), "PbSO4", position_equiv_groups=pos_equiv,
                   occupancy_sum_groups=occ_sum)],
        recipe=(
            RefinementStage(label="S0", flags={"scale": True, "background": {"coeffs": 6}}),
            RefinementStage(label="S1 occupancy", flags={"occupancy": True}),
        ),
        save_gpx=False,
        worsen_eps=1e9,  # 機構の試験 — 悪化判定で revert させず拘束の解を読む
    )
    base, occ_stage = result.stage_results
    assert not occ_stage.reverted, occ_stage.note
    occ = result.atom_occupancy["PbSO4"]
    assert occ["DO12"] != pytest.approx(0.7, abs=1e-4), "占有率が動いていない"
    assert occ["O1"] == pytest.approx(occ["DO11"] + occ["HO11"], abs=1e-6)
    assert occ["O1"] == pytest.approx(occ["DO12"] + occ["HO12"], abs=1e-6)
    assert occ_stage.n_params - base.n_params == 3
