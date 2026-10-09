"""M12 T8: TOPAS 段階解放エンジン。

`run_auto_rietveld` と同一の入出力契約を持つ兵行実装。段の受理/revert・失敗の縮退・
ledger 追記という**方針**は GSAS 経路と同じでなければならない (T7 で共通化する前段)。
"""

from __future__ import annotations

import math
import re
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


@pytest.fixture(scope="module")
def real_pbso4_default(tmp_path_factory):
    """既定レシピの実 PbSO4 を実 tc.exe で **1 度だけ**回す (同じ結果を検める gated テストで共有)。

    ``(結果, keep_project の置き場所)`` を返す。skip/deselect されたテストからは評価されない。
    """
    project = tmp_path_factory.mktemp("pbso4-default") / "proj"
    result = eng.run_topas_rietveld(
        [HistogramSpec(
            data_path=str(_PBSO4_XRA), instrument_path=str(_PBSO4_PRM),
            radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="GSAS",
        )],
        [PhaseSpec(structure_path=str(_PBSO4_CIF), phase_name="PbSO4")],
        keep_project=str(project),
    )
    return result, project


@pytest.mark.topas
@_real_data
def test_real_pbso4_refines_end_to_end(real_pbso4_default):
    """実データ (gitignore 対象) が要る — CI では `_real_data` で skip される。"""
    """実 CIF + 実データ + 実装置ファイル → 実 tc.exe で自動 Rietveld が回ること。

    GSAS-II 経路の X 線単独 Rwp は 11.0% (M7 T3 の内訳)。同等圏に入ることを見る。
    """
    result, project = real_pbso4_default
    assert result.backend == "topas"
    assert math.isfinite(result.final_rwp), "全段が失敗した"
    assert result.final_rwp < 20.0, f"Rwp {result.final_rwp} が高すぎる"
    assert any(not s.reverted for s in result.stage_results)
    assert project.is_dir()  # 成果物が残る
    _assert_n_params_is_topas_own_count(result)


@pytest.mark.topas
@_real_data
def test_real_pbso4_reports_the_mirror_coordinate_it_did_not_refine(real_pbso4_default):
    """**実 tc.exe で、精密化しない y = 1/4 が 0.0 でなく 0.25 で返る**。

    実測の再現: 以前は S が ``(0.06328548, 0.0, 0.68430616)`` で返り、esd は None だった。
    Pnma の鏡面上 (Pb/S/O1/O2) の y は対称で厳密に 1/4 — esd は GSAS 経路と同じ ``0.0``。
    一般位置の O3 は 3 軸とも精密化した esd を持つ。固定値の ``Out()`` を TOPAS が受け付けて
    値を書くこと (未精密化軸の値の出所) もこの実行で確かめる。
    """
    result, _ = real_pbso4_default
    assert math.isfinite(result.final_rwp)
    coords = result.atom_coords["PbSO4"]
    esd = result.atom_coord_esd["PbSO4"]
    assert set(coords) == {"Pb", "S", "O1", "O2", "O3"}, "原子が欠けている"
    assert coords["S"][1] == 0.25
    for label in ("Pb", "S", "O1", "O2"):
        assert coords[label][1] == 0.25, f"{label} の y = {coords[label][1]}"
        assert esd[label][1] == 0.0, f"{label} の y は対称固定なのに esd = {esd[label][1]}"
        assert esd[label][0] > 0.0 and esd[label][2] > 0.0, f"{label} の x/z が精密化されていない"
    assert all(e is not None and e > 0.0 for e in esd["O3"]), f"O3 の esd = {esd['O3']}"
    assert not any("atom_coords" in w for w in result.validity.warnings)


@pytest.mark.topas
@_real_data
def test_real_pbso4_each_stage_starts_from_the_last_accepted_out(tmp_path):
    """**実 tc.exe で、段 N の INP の値 = 直前に受理した段の ``.out`` の精密化値** (#218)。

    Issue の再現そのもの: 以前は 8 段すべて受理されても、どの段の INP も CIF の出発値
    (a=8.48, Pb x=0.1882) から始まっていた。格子・Pb の x/z・scale・背景・TCHZ を確かめる。
    """
    from tsumugin.topas.parse import background_values_from_out, named_refined_values_from_out

    project = tmp_path / "proj"
    result = eng.run_topas_rietveld(
        [HistogramSpec(
            data_path=str(_PBSO4_XRA), instrument_path=str(_PBSO4_PRM),
            radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="GSAS",
            two_theta_limits=(20.0, 90.0),
        )],
        [PhaseSpec(structure_path=str(_PBSO4_CIF), phase_name="PbSO4")],
        keep_project=str(project),
    )
    number = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
    carried: dict[str, float] = {}
    background: "tuple[float, ...]" = ()
    checked: set[str] = set()
    for index, stage in enumerate(result.stage_results):
        inp = (project / f"stage{index}.inp").read_text(encoding="utf-8")
        for name, expected in carried.items():
            found = re.search(rf"(?<![\w!])!?{re.escape(name)}(?:\s*,\s*|\s+)({number})", inp)
            assert found, f"stage{index}: {name} の宣言が INP に無い"
            assert float(found.group(1)) == expected, (
                f"stage{index}: {name} = {found.group(1)} (受理済み .out は {expected})"
            )
            checked.add(name)
        if background:
            line = next(x for x in inp.splitlines() if x.strip().startswith("bkg"))
            assert tuple(float(t) for t in line.split()[2:]) == background, f"stage{index}"
        if stage.reverted:
            continue  # 棄却した段の値は持ち越さない
        out = (project / f"stage{index}.out").read_text(encoding="utf-8")
        carried.update(named_refined_values_from_out(out))
        background = background_values_from_out(out)[0] or background
    for name in ("PbSO4_a", "PbSO4_b", "PbSO4_c", "PbSO4_Pb_x", "PbSO4_Pb_z",
                 "PbSO4_scale_h0", "pku0_PbSO4", "pkw0_PbSO4"):
        assert name in checked, f"{name} の持ち越しを一度も検算していない"
    assert background, "背景係数の持ち越しを一度も検算していない"
    assert math.isfinite(result.final_rwp)


@pytest.mark.topas
@_real_data
def test_real_pbso4_saves_the_project_by_default(tmp_path, monkeypatch):
    """★規定「全解析で成果物を保存する」(NFR-108) が **TOPAS でも** 実 tc.exe で成立する。

    GSAS の ``.gpx`` に対応するのは TOPAS では**プロジェクトディレクトリ** (INP/.out/
    results.txt)。``keep_project`` を渡さなくても既定で残り、``project_path`` がそれを指し、
    索引に ``backend="topas"`` の行が入ることを見る。

    データは tmp へコピーして使う — 既定の置き場所が**データ隣接**なので、追跡済みの
    ``docs/benchmark/testdata/`` を汚さないため。
    """
    import shutil

    from tsumugin.gpxstore import DEFAULT_DIR_NAME, ENV_VAR, read_manifest

    monkeypatch.delenv(ENV_VAR, raising=False)  # 隔離を外して**本番の既定**を見る
    for src in (_PBSO4_CIF, _PBSO4_XRA, _PBSO4_PRM):
        shutil.copyfile(src, tmp_path / src.name)
    hist = HistogramSpec(
        data_path=str(tmp_path / _PBSO4_XRA.name),
        instrument_path=str(tmp_path / _PBSO4_PRM.name),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="GSAS",
    )
    phase = PhaseSpec(structure_path=str(tmp_path / _PBSO4_CIF.name), phase_name="PbSO4")

    result = eng.run_topas_rietveld([hist], [phase])

    saved = Path(result.project_path)
    assert saved.is_dir(), result.project_path
    assert saved.parent.parent == tmp_path / DEFAULT_DIR_NAME
    assert saved.name == "PBSO4"  # データ名から決まる (どのデータの精密化か分かる)
    assert any(saved.iterdir()), "空のディレクトリしか残っていない"
    assert result.gpx_path == "", "TOPAS に .gpx は無い (project_path が成果物)"

    entries = read_manifest(str(saved.parent))
    assert len(entries) == 1
    assert entries[0]["backend"] == "topas"
    assert entries[0]["path"] == str(saved)
    assert entries[0]["rwp"] == pytest.approx(result.final_rwp)


@pytest.mark.topas
@_real_data
def test_real_pbso4_save_gpx_false_writes_nothing(tmp_path, monkeypatch):
    """TOPAS 経路でも opt-out (``save_gpx=False``) は 1 バイトも書かない。"""
    import shutil

    from tsumugin.gpxstore import DEFAULT_DIR_NAME, ENV_VAR

    monkeypatch.delenv(ENV_VAR, raising=False)
    for src in (_PBSO4_CIF, _PBSO4_XRA, _PBSO4_PRM):
        shutil.copyfile(src, tmp_path / src.name)
    hist = HistogramSpec(
        data_path=str(tmp_path / _PBSO4_XRA.name),
        instrument_path=str(tmp_path / _PBSO4_PRM.name),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="GSAS",
    )
    phase = PhaseSpec(structure_path=str(tmp_path / _PBSO4_CIF.name), phase_name="PbSO4")

    result = eng.run_topas_rietveld([hist], [phase], save_gpx=False)

    assert result.project_path == ""
    assert not (tmp_path / DEFAULT_DIR_NAME).exists()


def test_explicit_keep_project_survives_save_gpx_false(monkeypatch, tmp_path):
    """★明示 ``keep_project`` は ``save_gpx=False`` でもそのパスへ残る (2026-10-09 実測)。

    ``run_topas_rietveld(keep_project=<dir>, save_gpx=False)`` が <dir> に何も残さず、例外も
    出さなかった。opt-out が止めるのは既定保存であって名指しされた保存ではない (優先順位の
    正本は `gpxstore.plan_output`)。ここは **engine の配線**を縛る — 方針関数だけ直しても
    engine が ``save_gpx`` で先に分岐すれば、方針関数のテストは緑のまま同じ欠落が戻るため。

    スタブ driver は INP を書かないので、実 tc.exe と同じく INP を書く代役を使い、
    **中身が複製されたこと**まで見る (ディレクトリの有無だけでは「作っただけ」を見分けられない)。
    """

    def fake_run_tc(inp_text, *, workdir, basename, **kwargs):
        (Path(workdir) / f"{basename}.inp").write_text(inp_text, encoding="utf-8")
        return _FakeRun(30.0)

    monkeypatch.setattr(eng, "run_tc", fake_run_tc)
    keep = tmp_path / "kept-project"
    ledger = Ledger()

    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()], recipe=_stages(("S0", 0)), ledger=ledger,
        keep_project=str(keep), save_gpx=False,
    )

    assert result.project_path == str(keep)
    assert {p.name for p in keep.iterdir()} >= {"stage0.inp", "hist0.xye"}
    assert "m12_project_saved" in [e.kind for e in ledger.entries]


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


# ---------------- 段の間の精密化値の持ち越し (#218) ----------------


def _topas_like_out(inp_text: str, rwp: float, refined: "dict[str, float]",
                    background: "tuple[float, ...] | list[tuple[float, ...]]" = ()) -> str:
    """tc.exe の ``.out`` 書き戻しを模す: **INP そのもの**に精密化値を ``value`_esd`` で埋める。

    ``refined`` の名前は INP 中で ``!`` 無しに宣言されているもの (= 解放されたもの) だけ
    書き換える (``!`` 付きは TOPAS も値を動かさない)。``background`` は ``bkg @`` 行の係数
    (タプルなら全行に同じ値、リストなら行ごと)。
    """
    text = inp_text
    for name, value in refined.items():
        text = re.sub(
            rf"(?<![\w!])({re.escape(name)})([ \t]*,[ \t]*|[ \t]+)"
            r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
            lambda m, v=value: f"{m.group(1)}{m.group(2)}{v!r}`_0.001",
            text,
        )
    if background:
        rows = iter(background if isinstance(background, list) else [])

        def coeffs(match):
            row = next(rows, None) if isinstance(background, list) else background
            return f"{match.group(1)}  " + "  ".join(f"{v!r}`_0.5" for v in row)

        text = re.sub(r"(?m)^(\s*bkg @).*$", coeffs, text)
    header = f"r_p 1.0 r_wp {rwp} r_exp 5.0 gof 1.5\n"
    return header + text


_OUT_CALL = re.compile(r'Out\(\s*([A-Za-z_]\w*)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)"\s*)?\)')
_NUMBER = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"


def _topas_like_results(out_text: str, rwp: float) -> str:
    """tc.exe の ``Out()`` を模す: 名前を ``.out`` (精密化後の INP) の**宣言の値**で評価する。

    実 TOPAS と同じく、固定値 (``!name 0.25``) でも名前で指せば値を書く。esd は値に
    ``value`_esd`` の印があればそれ、無ければ 0 (TOPAS は固定値の esd に 0 を書く)。
    式 (``Get(r_wp)``・``1-x``) と MVW の報告値は評価しない — この偽物が答えるのは
    「宣言された値」だけで、TOPAS が計算する量は固定のレコードで足す。
    """
    lines = [f"r_wp\t{rwp}", "gof\t1.5"]
    for name, fmt, esd_fmt in _OUT_CALL.findall(out_text):
        if name.startswith("mvw_"):
            continue
        found = re.search(
            rf"(?<![\w!.])!?{re.escape(name)}(?:[ \t]*,[ \t]*|[ \t]+)({_NUMBER})(?:`_({_NUMBER}))?",
            out_text,
        )
        if found is None:
            continue
        value = float(found.group(1))
        esd = float(found.group(2)) if found.group(2) else 0.0
        record = fmt.replace("%.8f", f"{value:.8f}", 1)
        if esd_fmt:
            record += esd_fmt.replace("%.8f", f"{esd:.8f}", 1)
        # INP の書式には**リテラルの** ``\t``/``\n`` (バックスラッシュ + 文字) が入っている。
        lines.append(record.replace("\\t", "\t").replace("\\n", "\n").rstrip("\n"))
    lines.append("wt_frac\tPbSO4\t100.0\t0.0")
    return "\n".join(lines) + "\n"


@pytest.fixture()
def topas_like_driver(monkeypatch):
    """段ごとに (rwp, 精密化値, 背景) を仕込み、受け取った INP を記録する偽 tc.exe。

    ``.out`` は INP に精密化値を埋めたもの、results は INP の ``Out()`` をその値で評価したもの。
    """
    seen: list[str] = []

    def make(script):
        it = iter(script)

        def fake_run_tc(inp_text, **kwargs):
            rwp, refined, background = next(it)
            seen.append(inp_text)

            class R:
                out_text = _topas_like_out(inp_text, rwp, refined, background)
                results_text = _topas_like_results(out_text, rwp)
                stdout = ""

            return R()

        monkeypatch.setattr(eng, "run_tc", fake_run_tc)
        return seen

    return make


_BKG = (111.459139, 13.479005, -5.96622276, -1.92068456, 5.79465128, -0.982759569)


def test_next_stage_starts_from_the_refined_values_of_the_accepted_stage(topas_like_driver):
    """**段 N の INP の値 = 段 N−1 (受理) の ``.out`` の精密化値** (#218 受入条件 1)。

    以前は毎段 CIF の出発値から INP を描き直しており、「段階解放」が実際には
    「累積フラグで出発値から解き直す」になっていた (実 PbSO4 で 8 段すべての INP が
    a=8.48 のままだった)。
    """
    seen = topas_like_driver([
        (30.0, {"PbSO4_scale_h0": 0.000232608191}, _BKG),
        (20.0, {"PbSO4_a": 8.482776, "PbSO4_scale_h0": 0.00024}, _BKG),
        (12.0, {"PbSO4_Pb_x": 0.18779}, ()),
    ])
    eng.run_topas_rietveld(
        [_histogram()], [_phase()],
        recipe=(
            RefinementStage(label="S0", flags={"background": {"coeffs": 6}, "scale": True}),
            RefinementStage(label="S1", flags={"cell": True}),
            RefinementStage(label="S2", flags={"coords": True}),
        ),
    )
    stage1, stage2 = seen[1], seen[2]
    assert "scale PbSO4_scale_h0 0.000232608191\n" in stage1
    assert "bkg @ " + " ".join(repr(v) for v in _BKG) + "\n" in stage1, "背景係数が持ち越されていない"
    assert "a PbSO4_a 8.482776\n" in stage2, "格子が CIF の出発値から解き直されている"
    assert "scale PbSO4_scale_h0 0.00024\n" in stage2


def test_stage_after_a_reverted_stage_starts_from_the_last_accepted_values(topas_like_driver):
    """**棄却された段の次段は、直前に受理した段の値から始まる** (#218 受入条件 2)。

    棄却段の値 (a=9.9) も、CIF の出発値も使わない。
    """
    seen = topas_like_driver([
        (30.0, {"PbSO4_scale_h0": 0.00025}, _BKG),
        (40.0, {"PbSO4_a": 9.9, "PbSO4_scale_h0": 0.0009}, (1.0,) * 6),  # 悪化 → revert
        (20.0, {}, ()),
    ])
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()],
        recipe=(
            RefinementStage(label="S0", flags={"background": {"coeffs": 6}, "scale": True}),
            RefinementStage(label="S1", flags={"cell": True}),
            RefinementStage(label="S2", flags={"coords": True}),
        ),
    )
    assert result.stage_results[1].reverted is True
    stage2 = seen[2]
    assert "scale PbSO4_scale_h0 0.00025\n" in stage2, "受理済みの値を捨てている"
    assert "9.9" not in stage2 and "0.0009" not in stage2, "棄却した段の値が漏れている"
    assert "bkg @ " + " ".join(repr(v) for v in _BKG) + "\n" in stage2


def test_value_refined_earlier_survives_freezing(topas_like_driver):
    """段 1 で精密化した座標を ``freeze_others`` で凍結したとき、**精密化値で**凍結する。

    名前を付けずに描くと (固定の無名値) 名前で戻す先が無く、CIF の値へ黙って巻き戻る。
    """
    seen = topas_like_driver([
        (30.0, {"PbSO4_Pb_x": 0.18779, "PbSO4_Pb_z": 0.16743}, ()),
        (20.0, {}, ()),
    ])
    eng.run_topas_rietveld(
        [_histogram()], [_phase()],
        recipe=(
            RefinementStage(label="S0", flags={"coords": True}),
            RefinementStage(label="S1", flags={"freeze_others": True, "uiso": True}),
        ),
    )
    assert "site Pb x !PbSO4_Pb_x 0.18779 " in seen[1]
    assert " z !PbSO4_Pb_z 0.16743 " in seen[1]


def test_joint_carries_shared_structure_and_per_histogram_terms(topas_like_driver):
    """joint: 共有 ``prm`` (構造) は 1 本・scale/背景/ε は**ヒストグラムごと**に持ち越す。

    背景係数は名前を持たないので bkg 行の**順番**で xdd に対応させる。取り違えると
    X 線の背景が中性子側に入る (どちらも Rwp を見ただけでは分からない)。
    """
    bkg_x = (111.4, 13.5, -5.9, -1.9, 5.8, -0.98)
    bkg_n = (52.0, -3.1, 0.7, 0.2, -0.4, 0.1)
    seen = topas_like_driver([
        (30.0, {"PbSO4_scale_h0": 0.00025, "PbSO4_scale_h1": 0.0031}, [bkg_x, bkg_n]),
        (20.0, {"PbSO4_a": 8.4821}, [bkg_x, bkg_n]),
        (15.0, {"eps_PbSO4_a_h1": -0.00126}, [bkg_x, bkg_n]),
        (14.0, {}, ()),
    ])
    hist = _histogram()
    eng.run_topas_rietveld(
        [replace(hist, temperature=295.0), replace(hist, temperature=10.0)], [_phase()],
        recipe=(
            RefinementStage(label="S0", flags={"background": {"coeffs": 6}, "scale": True}),
            RefinementStage(label="S1", flags={"cell": True}),
            RefinementStage(label="S2", flags={"hydrostatic_strain": True}),
            RefinementStage(label="S3", flags={"coords": True}),
        ),
    )
    stage1, stage3 = seen[1], seen[3]
    bkg_lines = [line.strip() for line in stage1.splitlines() if line.strip().startswith("bkg")]
    assert bkg_lines == [
        "bkg @ " + " ".join(repr(v) for v in bkg_x),
        "bkg @ " + " ".join(repr(v) for v in bkg_n),
    ], "背景係数がヒストグラムの順に持ち越されていない"
    assert "scale PbSO4_scale_h0 0.00025\n" in stage1
    assert "scale PbSO4_scale_h1 0.0031\n" in stage1
    assert "prm PbSO4_a 8.4821\n" in stage3, "共有 prm に格子が持ち越されていない"
    assert stage3.count("a =PbSO4_a;") == 1, "先頭 xdd の参照式が書き換わった"
    assert "prm eps_PbSO4_a_h1 -0.00126 min" in stage3, "ε が持ち越されていない"


# ---------------- 精密化しなかった軸の座標 (atom_coords) ----------------
#
# 以前は ``coord`` レコード (= 解放した軸だけ) から三つ組を作り、**欠けた軸を 0.0 で埋めて
# いた**。実 PbSO4 で S (x, 1/4, z) が ``(0.0633, 0.0, 0.6843)`` と返る — CIF 出力・BVS・
# GSAS との一致判定がどれも黙って誤った座標を読む。GSAS 経路は原子行を読むので、精密化
# したかどうかによらず全原子の (x,y,z) が載り、esd は 3 状態 (`atomrows.coord_esd_states`)。
# 偽 tc.exe (`topas_like_driver`) は ``Out()`` を INP の宣言値で評価して results を書く。

_SCALE_ONLY = RefinementStage(label="S0", flags={"background": {"coeffs": 6}, "scale": True})
_COORDS = RefinementStage(label="S1", flags={"coords": True})
#: 合成 CIF (Pnma) の座標段で解放される軸 (Pb/S は鏡面上で y=1/4 固定、O1 は一般位置)。
_REFINED_COORDS = {
    "PbSO4_Pb_x": 0.18789637, "PbSO4_Pb_z": 0.1673483,
    "PbSO4_S_x": 0.06328548, "PbSO4_S_z": 0.68430616,
    "PbSO4_O1_x": 0.0951, "PbSO4_O1_y": 0.0262, "PbSO4_O1_z": 0.8061,
}


def test_unrefined_mirror_axis_reports_its_value_not_zero(topas_like_driver):
    """**解放しなかった軸は文書の値 (y=1/4) で返す** — 0.0 で埋めない。

    esd は GSAS 経路と同じ 3 状態: 解放した軸は su、サイト対称で固定される軸は ``0.0``
    (「厳密に 1/4」= 真の陳述)。None にすると GSAS との一致判定が「片方だけ対称固定 =
    対称性の仮定が違う」と誤った理由で INCOMPARABLE を出す (`agreement._verdict`)。
    """
    topas_like_driver([(30.0, {}, ()), (20.0, _REFINED_COORDS, ())])
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()], recipe=(_SCALE_ONLY, _COORDS),
    )
    coords = result.atom_coords["PbSO4"]
    esd = result.atom_coord_esd["PbSO4"]
    assert coords["S"] == (0.06328548, 0.25, 0.68430616)
    assert esd["S"] == (0.001, 0.0, 0.001)
    assert coords["Pb"] == (0.18789637, 0.25, 0.1673483)
    assert coords["O1"] == (0.0951, 0.0262, 0.8061)
    assert esd["O1"] == (0.001, 0.001, 0.001)


def test_atoms_whose_coordinates_were_never_refined_are_still_reported(topas_like_driver):
    """座標段を一度も受理していなくても**全原子が CIF (吸着後) の値で載る** (GSAS と同じ)。

    GSAS は原子行を読むので精密化の有無によらず全原子を返す。片方のバックエンドだけ原子が
    欠けると、一致判定はその原子を黙って比較対象から外す。esd は対称固定が ``0.0``、
    動かせたのに動かさなかった軸は ``None`` (この精密化では決まっていない)。
    """
    topas_like_driver([(30.0, {}, ())])
    result = eng.run_topas_rietveld([_histogram()], [_phase()], recipe=(_SCALE_ONLY,))
    assert result.atom_coords["PbSO4"] == {
        "Pb": (0.188, 0.25, 0.167),
        "S": (0.063, 0.25, 0.686),
        "O1": (0.095, 0.026, 0.806),
    }
    assert result.atom_coord_esd["PbSO4"] == {
        "Pb": (None, 0.0, None),
        "S": (None, 0.0, None),
        "O1": (None, None, None),
    }


def test_coordinates_frozen_after_refinement_keep_the_carried_value(topas_like_driver):
    """段 1 で精密化し後段で凍結した座標は**持ち越した精密化値**で返す (CIF 値でも 0 でもない)。

    最後に受理した段では解放していないので esd は ``None`` — GSAS も最終の共分散に載らない
    変数の su は持たない。
    """
    topas_like_driver([
        (30.0, _REFINED_COORDS, ()),
        (20.0, {}, ()),
    ])
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()],
        recipe=(
            RefinementStage(label="S0", flags={"coords": True}),
            RefinementStage(label="S1", flags={"freeze_others": True, "uiso": True}),
        ),
    )
    assert result.atom_coords["PbSO4"]["S"] == (0.06328548, 0.25, 0.68430616)
    assert result.atom_coord_esd["PbSO4"]["S"] == (None, 0.0, None)


def test_joint_reports_unrefined_coordinates_through_the_shared_names(topas_like_driver):
    """joint では座標が共有 ``prm`` に持ち上がる。**持ち上げ先の名前で**値を回収する。"""
    topas_like_driver([(30.0, {}, ())])
    hist = _histogram()
    result = eng.run_topas_rietveld(
        [replace(hist, temperature=295.0), replace(hist, temperature=10.0)], [_phase()],
        recipe=(_SCALE_ONLY,),
    )
    assert result.atom_coords["PbSO4"]["S"] == (0.063, 0.25, 0.686)
    assert result.atom_coord_esd["PbSO4"]["S"] == (None, 0.0, None)


def test_coordinate_assembly_never_invents_a_value_or_a_zero_esd():
    """組み立て側の規律 (レコードが欠けた・壊れた場合):

    - 3 軸そろわない原子は**載せず、名前を返す** — 欠けた軸を 0.0 で埋めると実在しない位置に
      なり、黙って落とすと原子が消えたことが見えない。
    - 精密化した軸の esd が 0 でも、対称固定でなければ ``None`` (0.0 =「厳密に固定」を捏造
      しない; GSAS の `coord_esd_states` が偽ゼロを落とすのと同じ)。未精密化のレコードは
      値に何が付いていても su を持たない。
    - 同じ軸に両方のレコードがあれば精密化値 (``coord``) が勝つ。
    - **相名に ``/`` が入っても**相ごと消えない (キーは ``相/ラベル/軸`` を後ろから読む)。
    """
    from tsumugin.topas.inp import Param, TopasDocument, TopasHistogram, TopasPhase, TopasSite
    from tsumugin.topas.parse import parse_records

    sulfur = TopasSite("S", "S", Param(0.06), Param(0.25), Param(0.68),
                       free_coord_axes=("x", "z"), fixed_coord_axes=("y",))
    oxygen = TopasSite("O9", "O", Param(0.1), Param(0.2), Param(0.3),
                       free_coord_axes=("x", "y", "z"))
    doc = TopasDocument(
        histograms=(TopasHistogram(data_path="d.xye"),),
        phases=(TopasPhase(phase_name="Pb/S", space_group="Pnma", cell={},
                           sites=(sulfur, oxygen)),),
    )
    records = parse_records(
        "coord\tPb/S\tS\tx\t0.0633\t0.0\n"           # 精密化したが esd が 0
        "coord_unrefined\tPb/S\tS\tz\t0.5\n"          # ↓ 精密化値に負ける
        "coord\tPb/S\tS\tz\t0.6843\t0.0005\n"
        "coord_unrefined\tPb/S\tS\ty\t0.25\t0.01\n"   # 未精密化に付いた数値は su ではない
        "coord\tPb/S\tO9\tx\t0.1\t0.001\n"            # y/z のレコードが無い原子
    )
    coords, esd, gaps = eng._atom_coord_maps(records, doc)
    assert coords == {"Pb/S": {"S": (0.0633, 0.25, 0.6843)}}
    assert esd == {"Pb/S": {"S": (None, 0.0, 0.0005)}}
    assert gaps == ("Pb/S/O9 (y,z)",)


def test_no_accepted_stage_reports_the_starting_coordinates(stub_driver):
    """**全段が失敗/revert しても全原子が出発値で載る** (GSAS は精密化前の原子行を返す)。

    受理した run が無いので TOPAS の評価値は無いが、持ち越しも起きていないので各サイトの
    値がそのまま TOPAS に渡した値である。`refined_cells` が参照セルへ戻るのと同じ扱い。
    """
    stub_driver([TopasRunError("Abnormal program termination")])
    result = eng.run_topas_rietveld([_histogram()], [_phase()], recipe=_stages(("S0", 0)))
    assert math.isinf(result.final_rwp)
    assert result.atom_coords["PbSO4"] == {
        "Pb": (0.188, 0.25, 0.167),
        "S": (0.063, 0.25, 0.686),
        "O1": (0.095, 0.026, 0.806),
    }
    assert result.atom_coord_esd["PbSO4"]["S"] == (None, 0.0, None)
    assert not any("atom_coords" in w for w in result.validity.warnings)


def test_atoms_without_a_full_coordinate_triple_are_reported_not_dropped_silently(
    monkeypatch,
):
    """3 軸そろわない原子は結果から外すが、**外したことを validity と ledger に残す**。"""

    class _Run:
        out_text = "r_p 1.0 r_wp 12.0 r_exp 5.0 gof 2.4\n"
        results_text = (
            "r_wp\t12.0\ngof\t2.4\n"
            "coord_unrefined\tPbSO4\tPb\tx\t0.188\n"
            "coord_unrefined\tPbSO4\tPb\ty\t0.25\n"
            "coord_unrefined\tPbSO4\tPb\tz\t0.167\n"
            "coord_unrefined\tPbSO4\tS\tx\t0.063\n"
        )
        stdout = ""

    monkeypatch.setattr(eng, "run_tc", lambda *a, **k: _Run())
    ledger = Ledger()
    result = eng.run_topas_rietveld(
        [_histogram()], [_phase()], recipe=_stages(("S0", 12.0)), ledger=ledger,
    )
    assert set(result.atom_coords["PbSO4"]) == {"Pb"}
    warning = next(w for w in result.validity.warnings if "atom_coords" in w)
    assert "PbSO4/S (y,z)" in warning and "PbSO4/O1 (x,y,z)" in warning
    gaps = [e for e in ledger.entries if e.kind == "m12_topas_coord_gaps"]
    assert len(gaps) == 1 and gaps[0].payload["atoms"] == [
        "PbSO4/S (y,z)", "PbSO4/O1 (x,y,z)",
    ]


# ---------------- 対称操作の補完失敗 (#219) ----------------


def test_symop_completion_failure_stops_the_run_instead_of_freezing_coordinates(
    tmp_path, stub_driver, monkeypatch
):
    """CIF に対称操作が無く補完にも失敗したら、**座標を黙って凍結したまま完走しない** (#219)。

    以前は空タプルで続行し、座標段は「無言 no-op」としか ledger に残らなかった。
    特殊位置の吸着 (#172) も効かないので単位胞の原子数まで変わりうる。
    """
    from tsumugin.errors import TopasRunError, TsumuginError
    from tsumugin.topas import symmetry

    cif = tmp_path / "nosymops.cif"
    cif.write_text(
        "\n".join(
            line
            for line in Path(_SYNTHETIC.structure_path).read_text(encoding="ascii").splitlines()
            if "_symmetry_equiv_pos" not in line and not line.strip().startswith("'")
        )
        + "\n",
        encoding="ascii",
    )

    def boom(space_group):
        raise TopasRunError("Cannot locate lam from riet_app_3 in data structures")

    monkeypatch.setattr(symmetry, "read_sg_symops", lambda sg, home=None: ())
    monkeypatch.setattr(symmetry, "_generate_sg_file", boom)
    stub_driver([30.0, 20.0])
    with pytest.raises(TsumuginError) as excinfo:
        eng.run_topas_rietveld(
            [_histogram()],
            [PhaseSpec(structure_path=str(cif), phase_name="PbSO4")],
            recipe=_stages(("S0", 0), ("S1", 0)),
        )
    assert type(excinfo.value).__name__ == "TopasSymmetryError"


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
    _assert_n_params_is_topas_own_count(result)


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
    _assert_n_params_is_topas_own_count(result)


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


# ---------------- 解放パラメータ数: 報告値を数えない ----------------

#: 実 tc.exe の ``.out`` (GSAS-II チュートリアル PbSO4, 公開データ) の S2 (cell+displacement)。
#: 精密化したのは ze0 + 背景 6 + scale + 格子 3 + TCHZ 3 = **14** で、TOPAS 自身の相関行列
#: ``C_matrix_normalized`` も 14 行。``MVW(...)`` の体積 ``318.521`_0.008`` と重量分率
#: ``100.000`_0.000`` は TOPAS が計算して書き戻す**報告値**だが、同じ ``value`_esd`` 記法を持つ。
_S2_OUT = r"""' generated by tsumugin (do not edit by hand)
r_p  11.2402923 r_wp  14.4391214 r_exp  4.93892969 gof  2.9235325
r_wp_dash  19.8124404 r_exp_dash  6.77688395
do_errors
iters 1200
xdd "hist0.xye"
   prm ze0 -0.046862591`_0.000483029713 min -0.5 max 0.5 del = .01 Yobs_dx_at(X1);
   th2_offset = ze0;
   One_on_X(!oox0, 0)
   bkg @  141.563014`_0.727519294  39.9097028`_1.17939629  15.4348254`_1.06701539  14.44522`_1.05791364 -8.02849886`_0.943640831 -9.40639641`_0.93028814
   str
      phase_name "PbSO4"
      space_group Pnma
      a PbSO4_a  8.479139`_0.000126
      b PbSO4_b  5.398019`_0.000082
      c PbSO4_c  6.959088`_0.000106
      site Pb x !PbSO4_Pb_x 0.1882 y !PbSO4_Pb_y 0.25 z !PbSO4_Pb_z 0.167 occ Pb !PbSO4_Pb_occ 1.0 beq !PbSO4_Pb_beq 0.7895683520871487
      TCHZ_Peak_Type(pku0_PbSO4, 0.0435481457`_0.00173722982, pkv0_PbSO4,-0.0357996052`_0.00212763159, pkw0_PbSO4, 0.0183637685`_0.00054885659, !pkz0_PbSO4, 0.0, !pkx0_PbSO4, 0.0, !pky0_PbSO4, 0.03)
      scale PbSO4_scale_h0  0.000197388971`_5.812e-07
      MVW( 1213.050, 318.521`_0.008, mvw_wt_PbSO4_h0  100.000`_0.000)
      Out(mvw_wt_PbSO4_h0, "wt_frac\tPbSO4\t%.8f", "\t%.8f\n")
C_matrix_normalized
{
                             1   2   3   4   5   6   7   8   9  10  11  12  13  14
ze0                    1:  100  -1  -0  -1  -1   0  -0  -0  52  53  56  -3   1   4
bkg2630385173784       2:   -1 100  37  45  23  27   6 -35   0  -0  -0  -6   3  -3
bkg2630385174000       3:   -0  37 100  36  53  20  33 -10  -1   1  -1  -4   3  -2
bkg2630385174216       4:   -1  45  36 100  30  46  16  10  -2   1  -1  -1   3  -3
bkg2630385174432       5:   -1  23  53  30 100  26  47  -4  -1   0  -1   4  -3   1
bkg2630385174648       6:    0  27  20  46  26 100  17   2  -0   1   0   2  -4   5
bkg2630385174864       7:   -0   6  33  16  47  17 100   1  -0   1  -1  -3   4  -5
PbSO4_scale_h0         8:   -0 -35 -10  10  -4   2   1 100  -1   1  -1   6  -2   3
PbSO4_a                9:   52   0  -1  -2  -1  -0  -0  -1 100   9  12  -2  -1   6
PbSO4_b               10:   53  -0   1   1   0   1   1   1   9 100   9  -3   1   1
PbSO4_c               11:   56  -0  -1  -1  -1   0  -1  -1  12   9 100   1  -2   5
pku0_PbSO4            12:   -3  -6  -4  -1   4   2  -3   6  -2  -3   1 100 -93  78
pkv0_PbSO4            13:    1   3   3   3  -3  -4   4  -2  -1   1  -2 -93 100 -94
pkw0_PbSO4            14:    4  -3  -2  -3   1   5  -5   3   6   1   5  78 -94 100
}
"""


def _correlation_matrix_size(out_text: str) -> int:
    """TOPAS 自身が数えた精密化パラメータ数 (``C_matrix_normalized`` の行数)。

    行は ``名前  番号:  相関…`` (列見出しは空白始まり、``{``/``}`` に ``:`` は無い)。名前が
    列幅を超えて番号と接しても数えられるよう、名前と番号の間の空白は要求しない。
    """
    _, _, matrix = out_text.partition("C_matrix_normalized")
    return len(re.findall(r"(?m)^\S[^\n:]*\d:", matrix))


def _assert_n_params_is_topas_own_count(result) -> None:
    """**実 tc.exe の全段で ``n_params`` = TOPAS 自身の相関行列の行数**。

    数える側は既知の報告値 (``MVW``) を除いているだけなので、報告値を書き戻す macro が INP に
    増えると黙って過大計数に戻る。実 tc.exe を回すテストの成果物で毎回これを検算する
    (追加の精密化はしない — 段の ``.out`` は成果物として既に残っている)。
    """
    project = Path(result.project_path)
    assert project.is_dir(), f"成果物が無い: {result.project_path!r}"
    checked = 0
    for index, stage in enumerate(result.stage_results):
        if not math.isfinite(stage.rwp):
            continue  # tc.exe が失敗した段には相関行列が無い
        out = (project / f"stage{index}.out").read_text(encoding="utf-8")
        expected = _correlation_matrix_size(out)
        assert expected > 0, f"stage{index}: 相関行列が無い (do_errors が外れた?)"
        assert stage.n_params == expected, (
            f"{stage.label}: n_params={stage.n_params} だが TOPAS が精密化したのは {expected}"
        )
        checked += 1
    assert checked, "比べた段が無い (精密化が回っていない)"


def test_n_params_does_not_count_the_values_mvw_reports():
    """**``MVW`` の体積・重量分率は解放パラメータではない**。

    数えると相 × ヒストグラムごとに 1–2 個の過大計数になる。``n_params`` は無言 no-op 検出と
    BIC (``χ² + n_params·ln n_obs``) に入るので、相数の違うモデルの比較が相の数だけ偏る。
    実 PbSO4 の S0 (背景 6 + scale 1) が 8 と報告されていた。
    """
    _, _, n_params = eng._metrics(_S2_OUT, "")
    assert _correlation_matrix_size(_S2_OUT) == 14  # fixture の前提 (TOPAS 自身の計数)
    assert n_params == 14, f"n_params={n_params}: MVW の報告値を精密化パラメータと数えている"


#: 同じ S2 の INP から ``do_errors`` だけを外して実 tc.exe で回した ``.out`` (Rwp は同一)。
#: esd は付かず**バッククォートだけ**が精密化値 (と MVW の報告値) に残り、相関行列も出ない。
_S2_OUT_WITHOUT_ERRORS = r"""r_p  11.2402923 r_wp  14.4391214 r_exp  4.93892969 gof  2.9235325
iters 1200
xdd "hist0.xye"
   prm ze0 -0.046862591` min -0.5 max 0.5 del = .01 Yobs_dx_at(X1);
   bkg @  141.563014`  39.9097028`  15.4348254`  14.44522` -8.02849886` -9.40639641`
   str
      a PbSO4_a  8.479139`
      b PbSO4_b  5.398019`
      c PbSO4_c  6.959088`
      site Pb x !PbSO4_Pb_x 0.1882 y !PbSO4_Pb_y 0.25 z !PbSO4_Pb_z 0.167 occ Pb !PbSO4_Pb_occ 1.0 beq !PbSO4_Pb_beq 0.7895683520871487
      TCHZ_Peak_Type(pku0_PbSO4, 0.0435481457`, pkv0_PbSO4,-0.0357996052`, pkw0_PbSO4, 0.0183637685`, !pkz0_PbSO4, 0.0, !pkx0_PbSO4, 0.0, !pky0_PbSO4, 0.03)
      scale PbSO4_scale_h0  0.000197388971`
      MVW( 1213.050, 318.521`, mvw_wt_PbSO4_h0  100.000`)
      Out(mvw_wt_PbSO4_h0, "wt_frac\tPbSO4\t%.8f", "\t%.8f\n")
"""


def test_n_params_without_do_errors_counts_the_backticked_values():
    """**印はバッククォート** — esd を要求すると ``do_errors`` 無しで全段 ``n_params=0`` になる。

    0 が続くと無言 no-op 検出の「母数が増えない」が常に成立し、BIC から母数の項が消える。
    持ち越し (`named_refined_values_from_out`) は同じ ``.out`` をバッククォートで正しく読むので、
    2 つのパーサが「何が精密化されたか」で食い違うことにもなる。
    """
    _, _, n_params = eng._metrics(_S2_OUT_WITHOUT_ERRORS, "")
    assert n_params == 14, f"n_params={n_params} (do_errors 付きの同じ段は 14)"


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
#:
#: **2026-10-09 (#218) で 67.62 → 32.95%**。段の間で精密化値を持ち越すようになり、それまで
#: 「CIF の出発値から累積フラグで解き直して」発散 → revert されていた S4 coords / S6 uiso /
#: S7 Lorentzian / S8 非対称が受理されるようになった。⚠ その結果 **validity は fail に
#: なった** (CaF2 の Uiso < 0) — 以前 pass だったのは Uiso 段が revert されていたからで、
#: 調整済み設定と同じ既知の状態が既定でも表に出ただけである (Rwp だけで合格にしない)。
_T4_RWP_MEASURED = 32.95
_T4_RWP_CEILING = 34.0
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
    _assert_n_params_is_topas_own_count(result)


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
    assert result.final_rwp < 6.5, f"Rwp {result.final_rwp:.2f} (実測 5.56, GSAS 4.33)"
    assert result.validity.passed
    assert result.atom_occupancy["garnet"]["Fe1"] == pytest.approx(0.58, abs=0.05)
    _assert_n_params_is_topas_own_count(result)


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
    assert result.final_rwp < 8.0, f"Rwp {result.final_rwp:.2f} (実測 7.13, GSAS 6.66)"
    assert result.validity.passed
    # 【段が実際に走ったことを見る】: 温度差の段が落ちて revert されても総合 Rwp は
    #   8.29% で「基準の近く」に見えてしまう (実測: ε の箱が広すぎると tc.exe が
    #   `Invalid d spacing` で異常終了する)。**Rwp だけを見るガードでは検出できない**。
    strain = [s for s in result.stage_results if "hydrostatic_strain" in s.label]
    assert strain, "温度差があるのに歪み段がレシピに出ていない"
    assert not strain[0].reverted, f"歪み段が revert された: {strain[0].note}"
    # 【ε が実 tc.exe から返ること】: 単体テストは自作の results.txt を読ませているだけ
    #   なので、`Out(eps…)` を TOPAS が実際に受理して書くかは実データでしか分からない
    #   (tc.exe は構文エラーでも終了コード 0 を返す)。値は 10 K 側の収縮 (実測 -0.115%) で、
    #   熱膨張 α≈4e-6/K × 285 K ≈ 0.11% と一致し、箱 (±2%) からは 1 桁離れている。
    eps = result.cell_strain.get("PbSO4", {})
    assert set(eps) == {"a_h1", "b_h1", "c_h1"}, f"ε が返っていない: {result.cell_strain}"
    for axis, value in eps.items():
        assert -0.005 < value < 0.0, f"{axis}: {value} (10 K 側は縮むはず)"
    _assert_n_params_is_topas_own_count(result)


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
    # 【既知の赤旗】: #218 で Uiso 段が受理されるようになり、調整済み設定と同じく CaF2 の
    #   Uiso < 0 が表に出た。直ったら落ちて記録の更新を強制する (調整済み側と同じ規律)。
    assert not result.validity.passed, (
        "CaF2 の Uiso が負でなくなった — 記録を更新すること (この赤旗は既知の状態の固定)"
    )
    _assert_n_params_is_topas_own_count(result)


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

    既定 (#218 後 32.95%) から効いた 2 手を固定する:

    - ``seed_profile``: TOPAS は装置ファイルのプロファイルを読まないので、汎用初期値から
      遠い放射光では**桁で効く** (#218 後の実測: 背景 6 項で 11BM 31.2% → 9.35%)。
    - 背景 20 項: 11BM は 6 項では背景を表せない (M9 CaTeO3 で 24 項が要った前例と同型)。

    ⚠ #218 以前に記録した「24 項にすると X 線 Lorentzian 段が revert されて 67% へ跳ねる」
    「CW 中性子では種付けで悪化する (garnet 5.54 → 9.76%)」は、どちらも**段を出発値から解き
    直していた**ことの産物で、#218 後は再現しない (24 項 21.11% / garnet 5.557 → 5.557%)。

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
    assert result.histogram_rwp[0] < 10.0, "放射光の種付けが効いていない (実測 8.68)"
    assert not result.validity.passed, (
        "CaF2 の Uiso が負でなくなった — 記録を更新すること (この赤旗は既知の状態の固定)"
    )
    _assert_n_params_is_topas_own_count(result)

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
