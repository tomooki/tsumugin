"""規定の標準経路 (手順最適化 → 初期値摂動による収束確認) の**実データ配線**。

判断ロジックは `test_confirm.py` / `test_agreement.py` / `test_coord_jitter.py` で固定済み。
ここで測るのは、それらが**実 GSAS・実データの上で本当に動いているか**である:

1. 座標ジッタが実際の対称性 (`GetCSxinel`) を通って**実データの原子を動かす**
2. 一致判定が**実 esd** の上で判定できている (esd 抽出が壊れると全部 `UNDETERMINED` へ
   落ちて収束確認が**空虚に通る/空虚に落ちる**。Rwp には一切現れない)
3. `structure_is_corroborated` と `undetermined_by_initial_values` が**互いに整合**する

⚠ コスト: 開始点は並列 (`jobs = n_starts`) なので壁時計は 1 開始点分だが、Phase A + Phase B で
T1 ≈ 6 分 / T3 ≈ 8 分。候補は各データの Phase A 実測優勝手順 1 本に絞る
(T1=`polish` / T3=`sizestrain_last`)。

⚠ **開始点は 5 から減らさないこと。** 3 で試して実際に壊れた: T1 は valid な開始点が悪い
ベイスン (結晶子サイズが潰れた解) に偏って座標まで割れ、T3 は valid が 1 点しか残らず
一致判定が 1 件も成立しなかった (`insufficient_valid_starts`)。既定 5 は
`PHASE-B-FINDINGS.md` の測定条件そのものであり、期待値もそこから来ている。
到達 Rwp とベイスン構造の網羅測定は `tools/measure_jitter.py` の仕事。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.agreement import CELL, COORD, is_agreement
from tsumugin.autorietveld.confirm import STRUCTURE_CLASSES, optimize_then_confirm

_DATA = Path("docs/benchmark/testdata")

pytestmark = pytest.mark.gsas


def _t1_present() -> bool:
    d = _DATA / "m7/labdata"
    return (d / "FAP.XRA").exists() and (d / "FAP.EXP").exists()


def _t3_present() -> bool:
    d = _DATA / "m7/cwcombined"
    return (d / "PBSO4.XRA").exists() and (_DATA / "PbSO4-Wyckoff.cif").exists()


def _t1_inputs():
    d = _DATA / "m7/labdata"
    return (
        [HistogramSpec(data_path=str(d / "FAP.XRA"),
                       instrument_path=str(d / "INST_XRY.PRM"),
                       radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                       data_format="GSAS")],
        [PhaseSpec(structure_path=str(d / "FAP.EXP"), phase_name="fap", format_hint="EXP")],
    )


def _t3_inputs():
    d = _DATA / "m7/cwcombined"
    return (
        [HistogramSpec(data_path=str(d / "PBSO4.XRA"),
                       instrument_path=str(d / "INST_XRY.PRM"),
                       radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                       data_format="GSAS", temperature=295.0),
         HistogramSpec(data_path=str(d / "PBSO4.CWN"),
                       instrument_path=str(d / "inst_d1a.prm"),
                       radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER,
                       data_format="GSAS", temperature=10.0)],
        [PhaseSpec(structure_path=str(_DATA / "PbSO4-Wyckoff.cif"), phase_name="PbSO4",
                   format_hint="CIF")],
    )


def _assert_report_is_self_consistent(report) -> None:
    """出力どうしが矛盾しないこと (実データでしか壊れ方が出ない不変条件)。"""
    ms = report.multistart
    assert ms is not None and ms.n_starts >= 2

    # (a) 判定が**実際に行われた**こと。全クラスが欠落/`UNDETERMINED` なら esd 抽出か
    #     結果フィールドが壊れており、収束確認は空虚に通る (Rwp には現れない)。
    assert ms.class_convergence, (
        "クラス別判定が空 = 比較が 1 件も成立していない "
        f"({ms.corroboration_reason}; valid な開始点が 2 点未満なら n_starts を減らしていないか)"
    )
    judged = {c: v for c, v in ms.class_convergence.items() if v != "UNDETERMINED"}
    assert judged, f"全クラスが UNDETERMINED = 判断材料が取れていない: {ms.class_convergence}"

    # (b) `structure_is_corroborated` は構造クラスの判定と一致すること (別々に作らない)。
    structure_ok = all(
        is_agreement(ms.class_convergence[c])
        for c in STRUCTURE_CLASSES
        if c in ms.class_convergence
    ) and any(c in ms.class_convergence for c in STRUCTURE_CLASSES)
    assert report.structure_is_corroborated is structure_ok

    # (c) 割れたクラスがあるなら**名指し**もあること。「割れた」と言いながら何が割れたか
    #     言えないと、③ は出版してよい値と駄目な値を区別できない。
    diverged = [c for c, v in ms.class_convergence.items()
                if v not in ("UNDETERMINED",) and not is_agreement(v)]
    if diverged:
        assert report.undetermined_by_initial_values, (
            f"{diverged} が割れているのに未決定パラメータが 1 つも名指されていない"
        )


@pytest.mark.skipif(not _t1_present(), reason="T1 実データ未配置")
def test_t1_confirmation_moves_real_atoms_and_judges_on_real_esd():
    """★T1: 座標ジッタが実データの原子を動かし、実 esd の上で一致判定が成立する。

    非トートロジー: `coord_jitter_ang` を受け取っても、対称性判定 (`GetCSxinel`) が全軸を
    固定と誤判定すれば**1 軸も動かないまま「収束した」**と報告される。`n_axes_jittered` が
    0 でないことが、この経路が実データで生きている唯一の証拠である。
    """
    hists, phases = _t1_inputs()
    report = optimize_then_confirm(
        hists, phases, candidates=("polish",),
        n_starts=5, coord_jitter_ang=0.05, jobs=5,
    )

    assert report.adopted_recipe == "polish"
    assert report.best is not None and report.best.final_rwp < 25.0
    ms = report.multistart
    assert ms.n_axes_jittered > 0, "実データの自由座標が 1 軸も動いていない"
    _assert_report_is_self_consistent(report)

    # 実測 (PHASE-B-FINDINGS §2.4): 0.05 Å 動かしても**座標は戻ってくる**。判定を分けて
    # いるのは座標ではない (T1 は歪で割れる)。
    assert is_agreement(ms.class_convergence.get(COORD, "AGREE")), (
        f"座標が 0.05 Å の摂動から戻ってこない (PHASE-B-FINDINGS §2.4 と不一致): "
        f"{ms.class_convergence}"
    )


@pytest.mark.skipif(not _t1_present(), reason="T1 実データ未配置")
def test_t1_is_reachable_from_the_mcp_layer_with_json_only():
    """★② 経由 (JSON スカラだけ) で実データの収束確認が回ること。

    非トートロジー: Python から呼べることは「呼び手が存在する」ことを意味しない。③ は
    JSON しか送れないので、この経路が実データで通らなければ機能は存在しないに等しい。
    """
    from tsumugin.mcp.rietveld_tools import auto_rietveld

    hists, phases = _t1_inputs()
    out = auto_rietveld(
        [h.to_dict() for h in hists], [p.to_dict() for p in phases],
        search=["polish"],
        multistart={"n_starts": 5, "coord_jitter_ang": 0.05, "jobs": 5},
    )

    assert "error" not in out, out.get("error")
    conv = out["convergence"]
    assert conv["adopted_recipe"] == "polish"
    assert conv["class_convergence"], "② の返り値にクラス別判定が載っていない"
    assert isinstance(conv["structure_is_corroborated"], bool)
    assert isinstance(conv["undetermined_by_initial_values"], list)
    # 収束確認の最良フィットが返る (単発ではない)。
    assert out["final_rwp"] == pytest.approx(conv["final_rwp"])


@pytest.mark.skipif(not _t3_present(), reason="T3 実データ未配置")
def test_t3_joint_confirmation_is_self_consistent():
    """★T3 (X線+中性子 joint): 複数ヒストグラムでも収束確認が成立し出力が整合する。

    非トートロジー: joint は per-histogram の Dij/プロファイルを持つので、パラメータの
    ラベル空間が単相 X 線より広い。ラベルの取り違えは「比較したつもりで別物を比べた」
    という形で現れ、Rwp からは絶対に見えない。

    ⚠ `cell` が割れるのは**実測された既知の性質** (Rwp 差 0.1 ポイントで格子が割れる =
    目的関数が平坦, PHASE-B-FINDINGS §2.1)。ここでは割れること自体を期待値にはせず、
    「割れたなら名指しされる」という整合だけを固定する — 情報が増えて収束するようになったら
    それは改善であり、テストが落ちるべきではない。
    """
    hists, phases = _t3_inputs()
    report = optimize_then_confirm(
        hists, phases, candidates=("sizestrain_last",),
        n_starts=5, coord_jitter_ang=0.05, jobs=5,
    )

    assert report.adopted_recipe == "sizestrain_last"
    assert report.best is not None and report.best.final_rwp < 15.0
    ms = report.multistart
    assert ms.n_axes_jittered > 0
    _assert_report_is_self_consistent(report)
    assert CELL in ms.class_convergence, "joint で格子クラスが比較されていない"
    assert is_agreement(ms.class_convergence.get(COORD, "AGREE")), (
        f"座標が 0.05 Å の摂動から戻ってこない (PHASE-B-FINDINGS §2.4 と不一致): "
        f"{ms.class_convergence}"
    )
