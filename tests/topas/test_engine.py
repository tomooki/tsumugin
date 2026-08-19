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


def test_silent_noop_stage_is_detected_not_swallowed(stub_driver):
    """**指標がビット同一で `reverted` も立たない段**を、区別できる事実として残す (M12 T7)。

    GSAS 経路にしか無かった検出 (REQ-SAR-102) を共有の段方針から受け取る。T4 実測で
    S3 phase_fractions / S5 occupancy がこの状態のまま完走していた — 最終 Rwp からは
    「効かなかった」のか「無言で失敗した」のかを区別できない。
    """
    ledger = Ledger()
    stub_driver([30.0, 30.0])
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()],
        recipe=_stages(("S0", 30.0), ("S1", 30.0)), ledger=ledger,
    )
    second = result.stage_results[1]
    assert not second.reverted, "no-op は revert しない (検出のみ)"
    assert "no-op" in second.note, f"note に出ていない: {second.note!r}"
    entries = [e for e in ledger.entries if e.kind == "m12_topas_stage"]
    assert entries[1].payload["noop"] is True
    assert entries[0].payload["noop"] is False, "初段まで no-op と誤報している"


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


@pytest.mark.topas
def test_hydrostatic_strain_produces_inp_that_tc_actually_accepts():
    """`hydrostatic_strain` は **joint 専用**なので上のパラメータ表には載せられない。

    同じ観測を 2 本にした最小の joint で、``a = <共有> * (1 + ε);`` を実 tc.exe が
    受理する (= 段が rwp=inf に落ちない) ことを確かめる。
    """
    hist = _histogram()
    result = eng.run_topas_rietveld(
        [replace(hist, temperature=295.0), replace(hist, temperature=10.0)],
        [_phase()],
        recipe=(
            RefinementStage(label="S0", flags={"background": {"coeffs": 6}, "scale": True}),
            RefinementStage(label="S1 cell", flags={"cell": True}),
            RefinementStage(label="S2 strain", flags={"hydrostatic_strain": True}),
        ),
    )
    stage = result.stage_results[-1]
    assert math.isfinite(stage.rwp), "tc.exe が INP を受理していない (rwp=inf)"
    assert stage.n_params > result.stage_results[-2].n_params, (
        "ε が 1 つも増えていない — 段が無言 no-op になっている"
    )


# ---------------- joint の総合指標 (#174) ----------------

#: 実測: joint (X 線 + CW 中性子 PbSO4) の ``.out`` 先頭行は**全ヒストグラム込み**の r_wp、
#: xdd0 の中に置いた ``Out(Get(r_wp))`` は**その xdd だけ**の r_wp を返す。
_JOINT_OUT = "r_p 8.08 r_wp 10.7719291 r_exp 4.99 gof 2.15572354\n"
_JOINT_RESULTS = "r_wp\t8.63512963\ngof\t1.75145516\nhist_rwp\th0\t8.63512963\n"


def test_joint_metrics_come_from_the_global_out_header():
    """**joint では ``results.txt`` の r_wp は第 1 ヒストグラムのものでしかない**。

    `Out(Get(r_wp))` は書かれた ``xdd`` ブロックの値を返す。これを総合値として使うと、
    第 2 ヒストグラムの当てはまりが悪化していても段が受理され、しかも**報告された数字が
    名乗っている量と違う**ことになる (実 PbSO4 joint で 8.635 と 10.772)。
    """
    rwp, gof, _ = eng._metrics(_JOINT_OUT, _JOINT_RESULTS)
    assert rwp == pytest.approx(10.7719291)
    assert gof == pytest.approx(2.15572354)


def test_single_histogram_metrics_are_unchanged():
    """単一ヒストグラムでは両者が一致するので、切り替えても値は変わらない (非回帰)。"""
    out = "r_p 6.18 r_wp 8.09334778 r_exp 4.93 gof 1.64156606\n"
    rwp, gof, _ = eng._metrics(out, "r_wp\t8.09334778\ngof\t1.64156606\n")
    assert rwp == pytest.approx(8.09334778)


def test_metrics_fall_back_to_the_records_when_the_out_header_is_missing():
    """``.out`` が壊れていても results.txt があれば段の判定はできる。"""
    rwp, gof, _ = eng._metrics("iters 0\n", "r_wp\t9.0\ngof\t1.2\n")
    assert rwp == pytest.approx(9.0) and gof == pytest.approx(1.2)


def test_per_histogram_rwp_is_reported():
    """総合値だけでなく**ヒストグラムごと**の r_wp も残す (どちらが悪いか分からないと直せない)。"""
    result = eng._per_histogram_rwp(_JOINT_RESULTS)
    assert result == {0: pytest.approx(8.63512963)}


def test_validity_receives_phase_fractions_as_a_sequence():
    """**`check_validity` は相分率を「値の並び」で取る** — dict を渡すと和がキー文字列になる。

    単相では和=1 検査が (要素 1 つなので) たまたま通り、**多相で初めて TypeError になる**。
    T4 (NAC+CaF2) を回して露見した。
    """
    report = eng._validity(
        refined_cells={"A": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        reference_cells={},
        atom_uiso={"A": {"X": 0.01}},
        atom_occupancy={"A": {"X": 1.0}},
        weight_fractions={"A": 60.0, "B": 40.0},
        converged=True,
    )
    assert isinstance(report.passed, bool)
    assert any("fraction" in name or "分率" in note for name, _, note in report.checks)


# ---------------- ベンチマーク回帰ガード (#172-#174) ----------------

_M7 = Path("docs/benchmark/testdata/m7")

#: T4 の実測 Rwp (**GSAS T4 と同一のデータリミット**で測った値, 2026-08-19)。
#: **合格基準ではない** — 合格基準は ≤15% (GSAS ~12.8%) で、W2 で TOF のピーク形状を
#: 詰めてから課す。
#:
#: ⚠ 以前記録されていた 30.9% は**リミットが違う**測定 (11BM 2-40° / PG3 7000-100000・
#: 26500-200000 µs) の値で、GSAS の 12.8% とは比較できない。同一条件での初回測定は 68.61% で、
#: **既定設定 (背景 6 項・種付けなし) の決定論値**である。調整済み設定 (背景 20 項 + 放射光の
#: profile 種付け) は下の `test_benchmark_t4_tuned_configuration` で 19.25% — そちらが到達点。
#: ⚠ 一時 43.49% と記録したが、それは **tc.exe のスレッド依存の非決定性**を引いた値だった
#: (同一入力が 43.49/67.62/43.49/29.29% に散らばる)。`driver` が 1 スレッドに固定してからは
#: この値でビット同一に再現する。
_T4_RWP_MEASURED = 67.62
_T4_RWP_CEILING = 69.0
#: 同条件での観測点数 (11BM 2.5-32° + PG3-1066 11750-103794 µs + PG3-2665 全域)。
_T4_N_OBS = 40150


def _benchmark_available(*paths: Path) -> bool:
    return all(p.is_file() for p in paths)


@pytest.mark.topas
@pytest.mark.skipif(
    not _benchmark_available(_M7 / "labdata" / "FAP.cif", _M7 / "labdata" / "FAP.XRA"),
    reason="M7 実データが無い (gitignore 対象)",
)
def test_benchmark_t1_fluoroapatite():
    """**六方晶の相対強度**の回帰ガード (#172)。

    特殊位置の座標が 1e-8 精度で書けていないと 4f サイトが一般位置へ化け、単位胞に存在しない
    原子が増えて Rwp 42% になる。ピーク位置は正しいままなので Rwp だけでは原因が分からない。
    """
    d = _M7 / "labdata"
    result = eng.run_topas_rietveld(
        [HistogramSpec(
            data_path=str(d / "FAP.XRA"), instrument_path=str(d / "INST_XRY.PRM"),
            radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
        )],
        [PhaseSpec(structure_path=str(d / "FAP.cif"), phase_name="FAP")],
    )
    assert result.final_rwp < 12.0, f"Rwp {result.final_rwp:.2f} (実測 10.45, GSAS 9.83)"
    assert result.validity.passed, "Uiso/占有率が非物理 (Rwp だけで合格にしない)"


@pytest.mark.topas
@pytest.mark.skipif(
    not _benchmark_available(
        _M7 / "cwneutron" / "garnet.raw", _M7 / "cwneutron" / "garnet_YFeAlO.cif"
    ),
    reason="M7 実データが無い (gitignore 対象)",
)
def test_benchmark_t2_garnet_cw_neutron():
    """**CW 中性子の Lorentz 因子**の回帰ガード (#174)。

    ``1/(sin²θ·cosθ)`` を落とすと強度の 2θ 依存が系統的にずれ、Rwp が 12% で頭打ちになる。
    混合占有が GSAS と同じ値 (16a Fe≈0.58) に落ちることも見る — **両エンジンが同じ構造へ
    収束するか**が M12 で最も重要な観測点。
    """
    d = _M7 / "cwneutron"
    result = eng.run_topas_rietveld(
        [HistogramSpec(
            data_path=str(d / "garnet.raw"), instrument_path=str(d / "inst_d1a.prm"),
            radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER,
        )],
        [PhaseSpec(
            structure_path=str(d / "garnet_YFeAlO.cif"), phase_name="garnet",
            mixed_occupancy_groups=(("Fe1", "Al1"), ("Al2", "Fe2")),
        )],
    )
    assert result.final_rwp < 6.5, f"Rwp {result.final_rwp:.2f} (実測 5.54, GSAS 4.33)"
    assert result.validity.passed
    assert result.atom_occupancy["garnet"]["Fe1"] == pytest.approx(0.58, abs=0.05)


@pytest.mark.topas
@pytest.mark.skipif(
    not _benchmark_available(
        _M7 / "cwcombined" / "PBSO4.XRA", _M7 / "cwcombined" / "PBSO4.CWN"
    ),
    reason="M7 実データが無い (gitignore 対象)",
)
def test_benchmark_t3_joint_reports_the_global_rwp():
    """**joint の総合 Rwp** の回帰ガード (#174)。

    ``Out(Get(r_wp))`` は書かれた ``xdd`` の値なので、それを総合値と名乗ると第 2
    ヒストグラムが悪化していても段が受理される。総合値が内訳の**いずれよりも小さくない**
    ことを見る (hist0 だけを報告していたら破れる)。
    """
    d = _M7 / "cwcombined"
    result = eng.run_topas_rietveld(
        [
            # 【温度は測定条件】: GSAS T3 は X 線 295 K / 中性子 10 K で、その差を
            #   per-histogram Dij で吸収して 6.66% を出している。温度を与えないと
            #   TOPAS 側は共有セル 1 本で両方を説明しようとする (#173/#178)。
            HistogramSpec(
                data_path=str(d / "PBSO4.XRA"), instrument_path=str(d / "INST_XRY.PRM"),
                radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                temperature=295.0,
            ),
            HistogramSpec(
                data_path=str(d / "PBSO4.CWN"), instrument_path=str(d / "inst_d1a.prm"),
                radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER,
                temperature=10.0,
            ),
        ],
        [PhaseSpec(
            structure_path="docs/benchmark/testdata/PbSO4-Wyckoff.cif", phase_name="PbSO4"
        )],
    )
    assert len(result.histogram_rwp) == 2, "内訳が取れていない"
    assert result.final_rwp >= min(result.histogram_rwp) - 1e-9
    assert result.final_rwp < 8.0, f"Rwp {result.final_rwp:.2f} (実測 7.19, GSAS 6.66)"
    assert result.validity.passed
    # 【段が実際に走ったことを見る】: 温度差の段が落ちて revert されても総合 Rwp は
    #   8.29% で「基準の近く」に見えてしまう (実測: ε の箱が広すぎると tc.exe が
    #   `Invalid d spacing` で異常終了する)。**Rwp だけを見るガードでは検出できない**。
    strain = [s for s in result.stage_results if "hydrostatic_strain" in s.label]
    assert strain, "温度差があるのに歪み段がレシピに出ていない"
    assert not strain[0].reverted, f"歪み段が revert された: {strain[0].note}"


def _t4_histograms(d: Path) -> list[HistogramSpec]:
    """GSAS T4 と**同一の測定条件** (リミット / 温度) のヒストグラム 3 本。

    ``data_format`` は測定条件ではなく「どのローダで読むか」である。GSAS 経路は GSAS-II の
    importer が形式を自分で判別するので ``"GSAS"`` で通るが、TOPAS 経路は
    `reference.io.load_pattern` が読む。PG3 の ``.gsa`` は BANK レコードが ``SLOG … FXYE``
    = **自由形式 X Y E の対数ビン**なので FXYE ローダが正しい (``parse_gsas_powder`` は
    CONST 固定ビンしか読めず SLOG を拒否する = Issue #181)。
    """
    return [
        HistogramSpec(
            data_path=str(d / "11BM_NAC.fxye"), instrument_path=str(d / "11bm_gsas.prm"),
            radiation=Radiation.XRAY_SYNCHROTRON, geometry=Geometry.DEBYE_SCHERRER,
            data_format="FXYE", two_theta_limits=(2.5, 32.0), temperature=298.0,
        ),
        HistogramSpec(
            data_path=str(d / "PG3_22048.gsa"), instrument_path=str(d / "POWGEN_1066.instprm"),
            radiation=Radiation.NEUTRON_TOF, geometry=Geometry.DEBYE_SCHERRER,
            data_format="FXYE", two_theta_limits=(11750.0, 103794.0), temperature=298.0,
        ),
        HistogramSpec(
            data_path=str(d / "PG3_22049.gsa"), instrument_path=str(d / "POWGEN_2665.instprm"),
            radiation=Radiation.NEUTRON_TOF, geometry=Geometry.DEBYE_SCHERRER,
            data_format="FXYE", temperature=298.0,
        ),
    ]


@pytest.mark.topas
@pytest.mark.skipif(
    not _benchmark_available(
        _M7 / "tofcw" / "11BM_NAC.fxye",
        _M7 / "tofcw" / "PG3_22048.gsa",
        _M7 / "tofcw" / "PG3_22049.gsa",
        _M7 / "tofcw" / "NAC.cif",
    ),
    reason="M7 実データが無い (gitignore 対象)",
)
def test_benchmark_t4_multiphase_tof_synchrotron():
    """T4 (NAC+CaF2 / TOF×2 + 放射光 多相) を **GSAS T4 と同一条件**で測る (#179)。

    仕様は `tests/autorietveld/test_engine_t4.py` と**同じ `HistogramSpec`** にする。
    データリミットが違うまま両者の Rwp を並べても比較にならない — M7 で「T4 非収束の主因は
    データリミット未設定」と実測で結論づけている以上、**リミットは測定条件そのもの**である。

    閾値は現時点の実測を固定した**悪化検出**であり、合格基準 (≤15%) はまだ課していない
    (W2 で TOF のピーク形状を詰めてから締める)。
    """
    d = _M7 / "tofcw"
    histograms = _t4_histograms(d)
    phases = [
        PhaseSpec(structure_path=str(d / "NAC.cif"), phase_name="NAC"),
        PhaseSpec(structure_path=str(d / "CaF2.cif"), phase_name="CaF2"),
    ]
    result = eng.run_topas_rietveld(histograms, phases, max_cyc=10)

    assert len(result.histogram_rwp) == 3, "内訳が取れていない (3 ヒストグラム)"
    # 【条件そのものを固定する】: Rwp の上限だけを見るガードは、**リミットを広げて
    #   都合のよい値を出す**変更を検出できない (実測: 11BM 2-40° へ広げると 30.3% と
    #   「良く」なるが GSAS の 12.8% とは比較できない値になる)。精密化に使った観測点数を
    #   固定して、測定条件が動いたら落ちるようにする。
    assert result.n_obs == _T4_N_OBS, (
        f"観測点数が {result.n_obs} (期待 {_T4_N_OBS}) — データリミットが動いている。"
        "条件が変われば Rwp は比較できない"
    )
    assert result.final_rwp < _T4_RWP_CEILING, (
        f"Rwp {result.final_rwp:.2f} が実測 {_T4_RWP_MEASURED} から悪化 "
        f"(内訳 {[round(v, 2) for v in result.histogram_rwp]})"
    )
    # 格子は Rwp が未達でも妥当な位置に留まること (NAC 立方 a~10.25 / CaF2 蛍石 a~5.46)。
    assert 10.20 < result.refined_cells["NAC"][0] < 10.30
    assert 5.42 < result.refined_cells["CaF2"][0] < 5.50


@pytest.mark.topas
@pytest.mark.skipif(
    not _benchmark_available(
        _M7 / "tofcw" / "11BM_NAC.fxye",
        _M7 / "tofcw" / "PG3_22048.gsa",
        _M7 / "tofcw" / "PG3_22049.gsa",
        _M7 / "tofcw" / "NAC.cif",
    ),
    reason="M7 実データが無い (gitignore 対象)",
)
def test_benchmark_t4_tuned_configuration():
    """T4 の**到達点** — 放射光のプロファイル種付け + 背景 20 項 (#179)。

    既定 (43.5%) から効いた 2 手を固定する:

    - ``seed_profile``: TOPAS は装置ファイルのプロファイルを読まないので、汎用初期値から
      遠い放射光では**桁で効く** (11BM 43.9% → 8.7%)。**CW 中性子では悪化する**ので既定 OFF。
    - 背景 20 項: 11BM は 6 項では背景を表せない (M9 CaTeO3 で 24 項が要った前例と同型)。
      ⚠ 24 項にすると X 線 Lorentzian 段が revert されて総合 67% へ跳ねる — **多ければ
      良いのではない**。

    ⚠ **物理妥当性は現在落ちる**: CaF2 の Ca が Uiso < 0 になる (少数相の未モデル寄与を
    吸っている疑い)。`assert not passed` は**既知の状態の記録**であり、直ったらこのテストが
    落ちて記録の更新を強制する。**Rwp だけで合格にしない**規律のための明示的な赤旗である。
    """
    d = _M7 / "tofcw"
    result = eng.run_topas_rietveld(
        _t4_histograms(d),
        [
            PhaseSpec(structure_path=str(d / "NAC.cif"), phase_name="NAC"),
            PhaseSpec(structure_path=str(d / "CaF2.cif"), phase_name="CaF2"),
        ],
        max_cyc=10,
        background_coeffs=20,
        seed_profile=True,
    )
    assert result.final_rwp < 21.0, f"Rwp {result.final_rwp:.2f} (実測 19.25, GSAS ~12.8)"
    assert result.histogram_rwp[0] < 10.0, "放射光の種付けが効いていない (実測 8.67)"
    assert not result.validity.passed, (
        "CaF2 の Uiso が負でなくなった — 記録を更新すること (この赤旗は既知の状態の固定)"
    )

def test_cell_strain_is_reported_from_the_records(stub_driver, monkeypatch):
    """段が効いた理由 (ε がいくつだったか) を結果から読めること。

    ``refined_cells`` は**構造としての 1 本のセル**なので、温度差をどれだけ吸収したかは
    そこからは読めない。出さないと「段が効いた」も「ε が箱に張り付いた (非物理)」も
    結果に現れない。
    """
    class _Run:
        out_text = "r_p 1.0 r_wp 12.0 r_exp 5.0 gof 2.4\n"
        results_text = (
            "r_wp\t12.0\ngof\t2.4\n"
            "cell_strain\tPbSO4\ta\th1\t0.0031\t0.0002\n"
        )
        stdout = ""

    monkeypatch.setattr(eng, "run_tc", lambda *a, **k: _Run())
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()], recipe=_stages(("S0", 12.0)),
    )
    assert result.cell_strain == {"PbSO4": {"a_h1": 0.0031}}
