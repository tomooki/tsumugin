"""RestrictUiso SafeAction + 診断規則 (REQ-004/105) の決定論テスト。"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.refine_loop.action import AnalysisInput, RestrictUiso
from tsumugin.refine_loop.diagnostics import ResidualFeatures, propose_next_actions


def _inp(*phase_names: str) -> AnalysisInput:
    hist = HistogramSpec("d.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")
    phases = tuple(PhaseSpec(f"{n}.cif", n) for n in phase_names)
    return AnalysisInput((hist,), phases)


def test_restrict_uiso_sets_free_uiso_labels():
    out = RestrictUiso(("Cu", "Ow")).apply(_inp("P1"))
    assert out.phases[0].free_uiso_labels == ("Cu", "Ow")


def test_restrict_uiso_phase_specific():
    out = RestrictUiso(("Cu",), phase="P2").apply(_inp("P1", "P2"))
    assert out.phases[0].free_uiso_labels is None    # P1 は不変 (未指定のまま = 全原子解放)
    assert out.phases[1].free_uiso_labels == ("Cu",)  # P2 のみ設定


def test_restrict_uiso_with_no_labels_freezes_uiso():
    """空指定は「1 原子も解放しない」= docstring どおり (#189 前は逆に全原子が解放されていた)。"""
    out = RestrictUiso(()).apply(_inp("P1"))
    assert out.phases[0].free_uiso_labels == ()


def test_restrict_uiso_never_unfreezes_a_frozen_phase():
    """限定は解放集合を広げない — ``()`` で凍結した相 (#189/#211 の少数相 ADP 凍結) は、
    提案を経ずに直接適用されても (③・相を名指ししない呼び出し) 凍結のまま。"""
    hist = _inp("x").histograms
    phases = (PhaseSpec("main.cif", "Main"),
              PhaseSpec("minor.cif", "Minor", free_uiso_labels=()))
    out = RestrictUiso(("Ca", "F")).apply(AnalysisInput(hist, phases))
    assert out.phases[0].free_uiso_labels == ("Ca", "F")  # 未指定の相には張る
    assert out.phases[1].free_uiso_labels == ()


def test_restrict_uiso_narrows_an_explicit_release_list():
    hist = _inp("x").histograms
    phases = (PhaseSpec("p.cif", "P1", free_uiso_labels=("Pb", "O1")),)
    out = RestrictUiso(("Pb", "S"), phase="P1").apply(AnalysisInput(hist, phases))
    assert out.phases[0].free_uiso_labels == ("Pb",)  # S は解放集合に無かったので足さない


def test_restrict_uiso_is_safe():
    assert RestrictUiso(("Cu",)).is_safe


def test_diverged_uiso_proposes_restrict_to_complement():
    # 発散原子 (C1,O2A) を除いた残り (Cu,Ow) に限定する提案。
    result = AutoRietveldResult(
        stage_results=(StageResult("final", rwp=12.0, gof=1.3, n_params=8, converged=True),),
        final_rwp=12.0, final_gof=1.3, refined_cells={"P1": (5.0,) * 3 + (90.0,) * 3},
        validity=ValidityReport(passed=True),
        atom_uiso={"P1": {"Cu": 0.01, "Ow": 0.05, "C1": -0.3, "O2A": 5e6}},
    )
    feats = [ResidualFeatures(hist_id=0, diverged_uiso_labels=("C1", "O2A"))]
    props = [p for p in propose_next_actions(result, feats, phases=_inp("P1").phases)
             if p.evidence.get("signal") == "uiso_diverged"]
    assert len(props) == 1
    act = props[0].action
    assert isinstance(act, RestrictUiso)
    assert act.labels == ("Cu", "Ow")  # 決定論 (昇順)
    assert act.phase == "P1"
    assert props[0].safe


# ---------------- 多相: 提案は相ごと (相の取り違え・凍結解除を起こさない) ----------------


def _res(atom_uiso, atom_occupancy=None) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=12.0, gof=1.3, n_params=8, converged=True),),
        final_rwp=12.0, final_gof=1.3,
        refined_cells={name: (5.0,) * 3 + (90.0,) * 3 for name in atom_uiso},
        validity=ValidityReport(passed=True),
        atom_uiso=atom_uiso,
        atom_occupancy=atom_occupancy or {},
    )


def _restricts(result, feats, phases) -> list[RestrictUiso]:
    acts = [p.action for p in propose_next_actions(result, feats, phases=phases)
            if p.evidence.get("signal") == "uiso_diverged"]
    assert all(isinstance(a, RestrictUiso) for a in acts)
    return acts


def _diverged(*pairs: tuple[str, str]) -> list[ResidualFeatures]:
    return [ResidualFeatures(hist_id=0, diverged_uiso_atoms=tuple(sorted(pairs)))]


def test_label_view_is_derived_from_phase_qualified_atoms():
    """相付きの組だけ渡せば、相を畳んだラベル列は同じ事実から導かれる (2 つの正本を持たない)。"""
    f = ResidualFeatures(hist_id=0, diverged_uiso_atoms=(("A", "O1"), ("B", "O1"), ("B", "O2")))
    assert f.diverged_uiso_labels == ("O1", "O2")


def test_disagreeing_label_view_is_refused():
    """食い違う 2 つの見え方は構築時に拒む — 提案は相付きを、読み手はラベル列を見るので、
    黙って受けると「O3 は発散した」と「O3 は限定しない」が同時に成り立つ。"""
    with pytest.raises(ValueError, match="diverged_uiso"):
        ResidualFeatures(hist_id=0, diverged_uiso_labels=("O1", "O3"),
                         diverged_uiso_atoms=(("A", "O1"),))


def _apply_all(acts, inp: AnalysisInput) -> AnalysisInput:
    for a in acts:
        inp = a.apply(inp)
    return inp


def test_restrict_is_proposed_per_phase_from_that_phase_own_labels():
    """他相のラベルを混ぜない — 混ぜると GSAS は ``No such atom`` で uiso 段ごと revert し
    (Uiso が 1 つも精密化されない)、相の指定のラベル検査は精密化前に拒否する。"""
    result = _res({
        "PbSO4": {"Pb": 0.01, "S": 0.01, "O1": 0.02, "O2": 0.9},
        "CaF2": {"Ca": 0.01, "F": 0.02},
    })
    inp = _inp("PbSO4", "CaF2")
    acts = _restricts(result, _diverged(("PbSO4", "O2")), inp.phases)

    assert acts == [RestrictUiso(("O1", "Pb", "S"), phase="PbSO4")]
    out = _apply_all(acts, inp)
    assert out.phases[1].free_uiso_labels is None  # 発散の無い相は触らない


def test_shared_label_diverged_in_one_phase_is_not_removed_from_the_other():
    """同名ラベル (両相に "O1") が片方でだけ発散しても、もう片方の O1 は解放したまま。"""
    result = _res({
        "A": {"Pb": 0.01, "O1": 0.9},
        "B": {"Ca": 0.01, "O1": 0.02, "O2": -0.1},
    })
    acts = _restricts(result, _diverged(("A", "O1"), ("B", "O2")), _inp("A", "B").phases)

    assert acts == [
        RestrictUiso(("Pb",), phase="A"),
        RestrictUiso(("Ca", "O1"), phase="B"),  # B の O1 は発散していない
    ]


def test_explicitly_frozen_phase_is_never_unfrozen():
    """``free_uiso_labels=()`` は少数相の ADP 凍結 (#189/#211)。発散を理由に解除しない。"""
    result = _res({
        "Main": {"Pb": 0.01, "O1": 0.9},
        # 凍結相でも初期値 (CIF 由来) が範囲外なら発散と判定されうる。
        "Minor": {"Ca": 0.01, "F": 0.7},
    })
    phases = (PhaseSpec("Main.cif", "Main"),
              PhaseSpec("Minor.cif", "Minor", free_uiso_labels=()))
    acts = _restricts(result, _diverged(("Main", "O1"), ("Minor", "F")), phases)

    assert acts == [RestrictUiso(("Pb",), phase="Main")]
    hist = _inp("x").histograms
    out = _apply_all(acts, AnalysisInput(hist, phases))
    assert out.phases[1].free_uiso_labels == ()


def test_frozen_uiso_labels_are_not_put_back_in_the_release_list():
    result = _res({"P1": {"Pb": 0.01, "O1": 0.9, "D1": 0.02}})
    phases = (PhaseSpec("P1.cif", "P1", frozen_uiso_labels=("D1",)),)
    acts = _restricts(result, _diverged(("P1", "O1")), phases)
    assert acts == [RestrictUiso(("Pb",), phase="P1")]


def test_diverged_atom_that_is_not_released_proposes_nothing():
    """凍結済みの原子 (初期値が範囲外) を「限定」しても何も変わらない — 無駄な 1 反復を使わない。"""
    result = _res({"P1": {"Pb": 0.01, "D1": 0.9}})
    phases = (PhaseSpec("P1.cif", "P1", frozen_uiso_labels=("D1",)),)
    assert _restricts(result, _diverged(("P1", "D1")), phases) == []


def test_explicit_release_list_is_narrowed_not_widened():
    """明示の解放集合から発散原子を除くだけ。限定しているのに解放原子を増やさない。"""
    result = _res({"P1": {"Pb": 0.01, "S": 0.01, "O1": 0.9, "O2": 0.02}})
    phases = (PhaseSpec("P1.cif", "P1", free_uiso_labels=("Pb", "O1")),)
    acts = _restricts(result, _diverged(("P1", "O1")), phases)
    assert acts == [RestrictUiso(("Pb",), phase="P1")]


def test_all_released_atoms_diverged_freezes_the_phase():
    """解放中の原子が全て発散した相 (少数相の幽霊化, #209) は相ごと凍結を提案する。
    #189 以降 ``()`` は「1 原子も解放しない」なので、空の限定は意味のある手になった。"""
    result = _res({
        "Main": {"Pb": 0.01, "O1": 0.02},
        "Minor": {"Ca": 3e8, "F": 1e9},
    })
    acts = _restricts(result, _diverged(("Minor", "Ca"), ("Minor", "F")),
                      _inp("Main", "Minor").phases)
    assert acts == [RestrictUiso((), phase="Minor")]


def test_anisotropic_atoms_keep_their_release():
    """異方性原子は ``atom_uiso`` に現れない (Uiso を持たない) が相の原子ではある。
    未指定 (全原子解放) の相を限定するとき、発散していない異方性原子まで凍結しない。"""
    result = _res(
        {"P1": {"Pb": 0.01, "O1": 0.9}},
        atom_occupancy={"P1": {"Pb": 1.0, "O1": 1.0, "Zr": 1.0}},
    )
    acts = _restricts(result, _diverged(("P1", "O1")), _inp("P1").phases)
    assert acts == [RestrictUiso(("Pb", "Zr"), phase="P1")]


def test_without_phase_specs_no_restriction_is_proposed():
    """相の指定を知らずに解放集合を書き換えると凍結を解いてしまう — 提案しない。"""
    result = _res({"P1": {"Pb": 0.01, "O1": 0.9}})
    acts = [p for p in propose_next_actions(result, _diverged(("P1", "O1")))
            if p.evidence.get("signal") == "uiso_diverged"]
    assert acts == []


def test_label_only_features_attribute_to_every_phase_with_that_label():
    """相を運ばない旧形式 (ラベルのみ) は、そのラベルを持つ全相に帰属させる。共有ラベルは
    どちらの相で発散したか判別できないので、両相で限定する (解放し続けるより保守的)。"""
    result = _res({
        "A": {"Pb": 0.01, "O1": 0.9},
        "B": {"Ca": 0.01, "O1": 0.02},
    })
    feats = [ResidualFeatures(hist_id=0, diverged_uiso_labels=("O1",))]
    acts = _restricts(result, feats, _inp("A", "B").phases)
    assert acts == [RestrictUiso(("Pb",), phase="A"), RestrictUiso(("Ca",), phase="B")]
