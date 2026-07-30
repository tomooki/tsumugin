"""M12 T8: TOPAS 段階解放エンジン。

`run_auto_rietveld` と同一の入出力契約を持つ兵行実装。段の受理/revert・失敗の縮退・
ledger 追記という**方針**は GSAS 経路と同じでなければならない (T7 で共通化する前段)。
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from tsumugin.autorietveld.model import (
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
)
from tsumugin.errors import TopasRunError
from tsumugin.store import Ledger
from tsumugin.topas import engine as eng

_DATA = Path("docs/benchmark/testdata")
_PBSO4_CIF = _DATA / "PbSO4-Wyckoff.cif"
_PBSO4_XRA = _DATA / "PBSO4.XRA"
_PBSO4_PRM = _DATA / "INST_XRY.PRM"


_DATA: "tuple[Path, Path] | None" = None


def _histogram() -> HistogramSpec:
    assert _DATA is not None, "synthetic_data フィクスチャが未適用"
    return HistogramSpec(
        data_path=str(_DATA[0]),
        instrument_path=str(_DATA[1]),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XYE",
    )


#: スタブ driver 経路は**実データを必要としない** — 構造ファイルは読めさえすればよい。
#: `docs/benchmark/testdata` は gitignore 対象で CI に無いため、合成 CIF を使って
#: CI でもこれらのテストが走るようにする (skip で逃げるとカバレッジが CI から消える)。
_SYNTHETIC: "PhaseSpec | None" = None


def _phase() -> PhaseSpec:
    assert _SYNTHETIC is not None, "synthetic_cif フィクスチャが未適用"
    return _SYNTHETIC


def _stages(*labels_rwp):
    return tuple(
        RefinementStage(label=label, flags={"background": {"coeffs": 6}})
        for label, _ in labels_rwp
    )


class _FakeRun:
    def __init__(self, rwp, gof=1.5, n_refined=3):
        vals = " ".join(f"p{i} 1.0`_0.01" for i in range(n_refined))
        self.out_text = f"r_p 1.0 r_wp {rwp} r_exp 5.0 gof {gof}\n{vals}\n"
        self.results_text = f"r_wp\t{rwp}\ngof\t{gof}\nwt_frac\tPbSO4\t100.0\t0.0\n"
        self.stdout = ""


@pytest.fixture(autouse=True)
def _use_synthetic_inputs(synthetic_cif, synthetic_data):
    """実データ非依存の入力を既定にする (CI で走らせるため)。"""
    global _SYNTHETIC, _DATA
    _SYNTHETIC = PhaseSpec(structure_path=str(synthetic_cif), phase_name="PbSO4")
    _DATA = synthetic_data
    yield
    _SYNTHETIC = _DATA = None


@pytest.fixture()
def stub_driver(monkeypatch):
    """tc.exe を呼ばずに段ごとの rwp を仕込む。"""
    calls: list[float] = []

    def make(sequence):
        it = iter(sequence)

        def fake_run_tc(inp_text, **kwargs):
            value = next(it)
            calls.append(value)
            if isinstance(value, Exception):
                raise value
            return _FakeRun(value)

        monkeypatch.setattr(eng, "run_tc", fake_run_tc)
        return calls

    return make


def test_improving_stages_are_accepted(stub_driver):
    stub_driver([30.0, 20.0, 12.0])
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()],
        recipe=_stages(("S0", 0), ("S1", 0), ("S2", 0)),
    )
    assert [s.rwp for s in result.stage_results] == [30.0, 20.0, 12.0]
    assert not any(s.reverted for s in result.stage_results)
    assert result.final_rwp == pytest.approx(12.0)


def test_worsening_stage_is_reverted(stub_driver):
    """悪化した段は revert され、最終 Rwp に影響しない (GSAS 経路と同じ方針)。"""
    stub_driver([30.0, 12.0, 25.0])
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()], recipe=_stages(("S0", 0), ("S1", 0), ("S2", 0))
    )
    assert result.stage_results[2].reverted is True
    assert result.final_rwp == pytest.approx(12.0)


def test_backend_failure_degrades_to_infinite_rwp_not_an_exception(stub_driver):
    """**不変条件**: バックエンドの失敗は例外でなく rwp=inf に変換しガードレールへ。"""
    stub_driver([30.0, TopasRunError("Abnormal program termination"), 25.0])
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()], recipe=_stages(("S0", 0), ("S1", 0), ("S2", 0))
    )
    failed = result.stage_results[1]
    assert math.isinf(failed.rwp) and failed.reverted is True
    assert "TopasRunError" in failed.note
    # 失敗段は基準を汚さない: 続く段は「最後に成功した 30.0」と比べて採否が決まる。
    assert result.final_rwp == pytest.approx(25.0)
    assert result.stage_results[2].reverted is False


def test_result_declares_the_backend(stub_driver):
    """Rwp/BIC を跨いで比較するときの前提なので出所を常に載せる。"""
    stub_driver([15.0])
    result = eng.run_topas_rietveld([_histogram()], [_phase()], recipe=_stages(("S0", 0)))
    assert result.backend == "topas"
    assert result.gpx_path == ""  # TOPAS に .gpx は無い (MEM 経路は適用不可)


def test_weight_fractions_are_normalised_to_unity(stub_driver):
    """TOPAS の MVW は百分率で返す。結果契約は 0-1 なので割る。"""
    stub_driver([15.0])
    result = eng.run_topas_rietveld([_histogram()], [_phase()], recipe=_stages(("S0", 0)))
    assert result.phase_weight_fractions["PbSO4"] == pytest.approx(1.0)


def test_ledger_records_every_stage(stub_driver):
    stub_driver([30.0, 40.0])
    ledger = Ledger()
    eng.run_topas_rietveld(
        [_histogram()], [_phase()], recipe=_stages(("S0", 0), ("S1", 0)), ledger=ledger
    )
    kinds = [e.kind for e in ledger.entries]
    assert kinds.count("m12_topas_stage") == 2
    assert ledger.verify()  # 追記専用ハッシュチェーンを壊さない (NFR-105)


def test_unsupported_flag_is_reported_not_ignored(stub_driver):
    """未対応フラグを黙って無視すると「解放されていない段」が完走する (無言 no-op 病理)。"""
    stub_driver([30.0])
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()],
        recipe=(RefinementStage(label="S0", flags={"hydrostatic_strain": True}),),
    )
    stage = result.stage_results[0]
    assert stage.reverted is True
    assert "UnsupportedStageFlagError" in stage.note


# ---------------- 実 tc.exe + 実データ ----------------


_real_data = pytest.mark.skipif(
    not (_PBSO4_CIF.exists() and _PBSO4_XRA.exists() and _PBSO4_PRM.exists()),
    reason="PbSO4 実データが無い",
)


@pytest.mark.topas
@_real_data
def test_real_pbso4_refines_end_to_end(tmp_path):
    """実データ (gitignore 対象) が要る — CI では `_real_data` で skip される。"""
    """実 CIF + 実データ + 実装置ファイル → 実 tc.exe で自動 Rietveld が回ること。

    GSAS-II 経路の X 線単独 Rwp は 11.0% (M7 T3 の内訳)。同等圏に入ることを見る。
    """
    real_hist = HistogramSpec(
        data_path=str(_PBSO4_XRA), instrument_path=str(_PBSO4_PRM),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="GSAS",
    )
    real_phase = PhaseSpec(structure_path=str(_PBSO4_CIF), phase_name="PbSO4")
    result = eng.run_topas_rietveld(
        [real_hist], [real_phase], keep_project=str(tmp_path / "proj")
    )
    assert result.backend == "topas"
    assert math.isfinite(result.final_rwp), "全段が失敗した"
    assert result.final_rwp < 20.0, f"Rwp {result.final_rwp} が高すぎる"
    assert any(not s.reverted for s in result.stage_results)
    assert (tmp_path / "proj").is_dir()  # 成果物が残る


def test_validity_gate_rejects_non_physical_uiso(stub_driver, monkeypatch):
    """**Rwp が下がっても Uiso が負なら不合格**にする (中立層の `check_validity` を共用)。

    これを繋がないと「Rwp 10% だが Uiso 負・占有率 1 超」が合格として返る。
    実 fluoroapatite で実際にそうなった (占有率を全解放していた頃)。
    """
    def runner(inp_text, **kwargs):
        class R:
            out_text = "r_p 1 r_wp 9.0 r_exp 5 gof 1.2\np 1.0`_0.01\n"
            results_text = (
                "r_wp\t9.0\ngof\t1.2\n"
                "beq\tPbSO4\tPb\t-2.5\t0.1\n"   # 負の beq → 負の Uiso
            )
            stdout = ""
        return R()

    monkeypatch.setattr(eng, "run_tc", runner)
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()], recipe=_stages(("S0", 0))
    )
    assert result.final_rwp == pytest.approx(9.0)
    assert result.validity.passed is False
    assert any(not ok and "uiso" in name for name, ok, _ in result.validity.checks)


def test_occupancy_is_released_only_for_declared_sites(synthetic_cif):
    """占有率はスケール因子と大域的に縮退するので**全サイト一斉解放をしない**。

    実 fluoroapatite で全解放すると occ 0.68-2.24 (1 超 = 非物理) に落ちながら
    Rwp だけは 10% に見えた。
    """
    from tsumugin.autorietveld.cif_normalize import read_structure_cif
    from tsumugin.autorietveld.model import PhaseSpec as PS
    from tsumugin.topas.flags import apply_stage
    from tsumugin.topas.inp import TopasDocument, TopasHistogram
    from tsumugin.topas.structure import structure_to_topas_phase

    structure = read_structure_cif(str(synthetic_cif))
    spec = PS(structure_path=str(synthetic_cif), phase_name="PbSO4",
              free_occupancy_labels=("O1",))
    phase = structure_to_topas_phase(structure, "PbSO4", spec=spec)
    doc = TopasDocument(histograms=(TopasHistogram(data_path="d.xye"),), phases=(phase,))
    out = apply_stage(doc, RefinementStage(label="occ", flags={"occupancy": True}))
    released = {s.label for s in out.phases[0].sites if s.occupancy.refine}
    assert released == {"O1"}


# ---------------- 新フラグの INP が実 tc.exe に受理されるか (#173) ----------------


@pytest.mark.topas
@pytest.mark.parametrize(
    ("label", "flags"),
    [
        ("preferred_orientation", {"preferred_orientation": 4}),
        ("absorption", {"absorption": True}),
    ],
)
def test_new_flags_produce_inp_that_tc_actually_accepts(label, flags):
    """**tc.exe は構文エラーでも終了コード 0 を返す** — 実行して受理を確かめる。

    翻訳表を「それらしく」書くだけでは、段が rwp=inf → revert に落ちて**黙って何も
    しなかった**ことになる。マニュアルが暗号化 PDF で読めない以上、1 フラグずつ実 tc.exe で
    検算するのが唯一の担保 (実際 `Cylindrical_I_Correction(=name;)` はこれで落ちた)。
    """
    hist = _histogram()
    if flags.get("absorption"):
        # 円筒吸収は反射光学系に当てられない (平板に円筒の式を当てない方針)。
        hist = replace(hist, geometry=Geometry.DEBYE_SCHERRER)
    result = eng.run_topas_rietveld(
        [hist],
        [_phase()],
        recipe=(
            RefinementStage(label="S0", flags={"background": {"coeffs": 6}, "scale": True}),
            RefinementStage(label=f"S1 {label}", flags=flags),
        ),
    )
    stage = result.stage_results[-1]
    assert math.isfinite(stage.rwp), f"{label}: tc.exe が INP を受理していない (rwp=inf)"
