"""② `identify_and_add_phase` (手動投入経路) の異方セル補正 (Issue #20 続き) の純テスト。

【なぜこの節が要るか (実測)】: MP(DFT) 格子は軸別に数 % ずれる (CaTeO3 delta: c 軸 +3.42%) 一方、
Rietveld の収束半径は ~2%。自動追加経路 (`insitu.engine._default_phase_finder`) は
`make_residual_cell_refiner` で**既知相減算残差**へ整合させてこれを吸収するが、手動投入経路である
② `identify_and_add_phase` は `cell_refiner` を渡しておらず、③ は DFT 格子のままの CIF を
受け取っていた (Rwp が高止まりする理由が ③ に見えない)。整合先の実測 (CaTeO3 frame180):

    整合先              delta 最大軸誤差    二相 Rwp
    (補正なし)           3.42 %             32.24
    生パターン           4.21 %             27.58   ← 出発点より**悪化**
    既知相減算残差        0.51 %             10.65   ← 実測 CIF (10.70) と並ぶ

ゆえに「既知相が渡されないなら補正しない」(生パターンへ落ちない) が安全側の契約である。

GSAS/MP/pymatgen 非依存 (stub provider/materializer + プリアライン記録スタブ)。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.model import FrameSpec
from tsumugin.mcp.insitu_tools import identify_and_add_phase, sequential_rietveld
from tsumugin.reference.model import ReferencePhase
from tsumugin.search.peaks import Peak


class _StubProvider:
    def __init__(self, phases):
        self._phases = tuple(phases)

    def fetch(self, elements):
        return self._phases


class _StubMaterializer:
    """物質化スタブ。``cell=`` に何が渡ったか (= 異方補正が効いたか) を記録する。"""

    def __init__(self):
        self.calls: list[str] = []
        self.cells: list[object] = []

    def materialize(self, phase_id, elements, out_path, strain=0.0, cell=None):
        self.calls.append(phase_id)
        self.cells.append(cell)
        Path(out_path).write_text(f"# dummy CIF {phase_id} cell={cell}\n", encoding="utf-8")
        return out_path


class _Sol:
    def __init__(self, cell):
        self.cell = cell
        self.n_used = 12


def _ref(phase_id, formula, peaks, elements):
    return ReferencePhase(
        phase_id=phase_id, formula=formula, element_system=tuple(sorted(elements)),
        peaks=tuple(Peak(position=p, height=h) for p, h in peaks), energy_above_hull=0.0,
    )


def _pattern(centers, heights=None, fwhm=0.2, counts=1500.0):
    """合成パターン (`tests/insitu/test_phaseid.py` と同じ範。S/N 停止を超える計数にする)。"""
    tt = np.arange(15.0, 60.0, 0.02)
    inten = np.zeros_like(tt)
    hs = heights or [1.0] * len(centers)
    sigma = fwhm / 2.3548
    for c, h in zip(centers, hs):
        inten += counts * h * np.exp(-0.5 * ((tt - c) / sigma) ** 2)
    return tt, inten


def _prealign_recorder(monkeypatch, cell=(5.0, 6.0, 7.0, 90.0, 90.0, 90.0)):
    """プリアラインを記録スタブへ差し替える (pymatgen 非依存)。"""
    seen: list[dict] = []

    def fake_prealign(structure_path, two_theta, intensity, **kwargs):
        seen.append({"path": structure_path, "tt": np.asarray(two_theta),
                     "intensity": np.asarray(intensity), **kwargs})
        return _Sol(cell) if cell is not None else None

    monkeypatch.setattr(
        "tsumugin.autorietveld.cell_refine.prealign_cell_from_structure", fake_prealign
    )
    return seen


def _stub_conversion(monkeypatch, mapping):
    """PhaseSpec→ReferencePhase 変換 (CIF 読込) を差し替え、渡った引数を記録する。"""
    seen: list[dict] = []

    def fake(spec, *, refined_cell=None, wavelength=1.5406, two_theta_range=(10.0, 90.0)):
        seen.append({"phase_name": spec.phase_name, "structure_path": spec.structure_path,
                     "refined_cell": refined_cell, "wavelength": wavelength})
        return mapping.get(spec.phase_name)

    monkeypatch.setattr("tsumugin.insitu.phaseid.phasespec_to_reference", fake)
    return seen


def _height(tt, vec, pos, half_width=0.5):
    return float(np.asarray(vec)[np.abs(tt - pos) <= half_width].max())


def test_prealigns_against_known_phase_residual(tmp_path, monkeypatch):
    """★ known_phases を渡すと、返る CIF の格子が**既知相減算残差**へ整合した異方セルになる。

    これが無いと ③ が手で足した相は DFT 格子 (軸別 3% 級のずれ) のまま精密化に入る。
    整合先が残差であること (生パターンでない) までを見る — 生パターン整合は実測で有害 (上表)。
    """
    tt, inten = _pattern([20.0, 30.0], heights=[10.0, 1.0])
    alpha = _ref("alpha", "CaTeO3H2O", [(20.0, 1.0)], ["Ca", "Te", "O"])
    delta = _ref("mp-delta", "CaTeO3", [(30.0, 1.0)], ["Ca", "Te", "O"])
    conv = _stub_conversion(monkeypatch, {"alpha": alpha})
    seen = _prealign_recorder(monkeypatch)
    mat = _StubMaterializer()

    out = identify_and_add_phase(
        tt.tolist(), inten.tolist(), ["Ca", "Te", "O"], str(tmp_path),
        provider=_StubProvider([delta]), materializer=mat, subtract_bg=False,
        known_phases=[{
            "structure_path": str(tmp_path / "alpha.cif"), "phase_name": "alpha",
            "refined_cell": [14.8, 6.8, 8.0, 90.0, 90.0, 90.0],
        }],
        wavelength=0.8,
    )

    assert out["n_candidates"] == 1
    assert out["candidates"][0]["refined_cell"] == [5.0, 6.0, 7.0, 90.0, 90.0, 90.0]
    assert out["prealign_basis"] == "residual"
    assert out["n_known_phases_used"] == 1
    # 補正セルで**再物質化**されている (CIF の中身が補正後の格子になる)。
    assert mat.cells[-1] == (5.0, 6.0, 7.0, 90.0, 90.0, 90.0)
    # 精密化格子と波長が warm-start 変換へ伝わる (DFT 素の格子で既知相ピークを立てない)。
    assert conv[0]["refined_cell"] == (14.8, 6.8, 8.0, 90.0, 90.0, 90.0)
    assert conv[0]["wavelength"] == 0.8
    # 整合先は残差: 既知相 20° は消え、新相 30° は残る。
    assert len(seen) == 1
    resid = seen[0]["intensity"]
    assert _height(tt, resid, 20.0) < 0.1 * _height(tt, inten, 20.0)
    assert _height(tt, resid, 30.0) > 0.5 * _height(tt, inten, 30.0)
    assert seen[0]["wavelength"] == 0.8
    json.dumps(out, allow_nan=False)


def test_known_phases_are_subtracted_before_identification(tmp_path, monkeypatch):
    """★ known_phases は同定そのものの起点にもなる (自動追加経路と同一プリミティブ)。

    支配相 (20°, 高さ 10) の陰にいる少数相 (30°, 高さ 1) は、生パターンからは受理されない。
    既知相を先に引いて初めて拾える — 手動投入は「自動が拾えなかった相」を探す手順なので、
    ここが効かないとツールは ③ が最も必要とする場面で候補ゼロを返す。
    """
    tt, inten = _pattern([20.0, 30.0], heights=[10.0, 1.0])
    alpha = _ref("alpha", "CaTeO3H2O", [(20.0, 1.0)], ["Ca", "Te", "O"])
    delta = _ref("mp-delta", "CaTeO3", [(30.0, 1.0)], ["Ca", "Te", "O"])
    _stub_conversion(monkeypatch, {"alpha": alpha})
    _prealign_recorder(monkeypatch)
    spec = {"structure_path": str(tmp_path / "alpha.cif"), "phase_name": "alpha"}

    with_known = identify_and_add_phase(
        tt.tolist(), inten.tolist(), ["Ca", "Te", "O"], str(tmp_path),
        provider=_StubProvider([delta]), materializer=_StubMaterializer(),
        subtract_bg=False, known_phases=[spec],
    )
    without = identify_and_add_phase(
        tt.tolist(), inten.tolist(), ["Ca", "Te", "O"], str(tmp_path),
        provider=_StubProvider([delta]), materializer=_StubMaterializer(),
        subtract_bg=False,
    )

    assert with_known["n_candidates"] == 1
    assert with_known["candidates"][0]["phase_id"] == "mp-delta"
    assert without["n_candidates"] == 0  # 同じ入力・同じ供給元でも生パターンからは拾えない


def test_without_known_phases_does_not_prealign(tmp_path, monkeypatch):
    """★ known_phases 無しでは補正しない (生パターン整合へ**落ちない**)。

    生パターンへ整合させると FoM が支配相のピークに占められ、少数相のセルは出発点より悪化する
    (実測 3.42%→4.21%)。既知相を引けない呼び出しは等方 strain のまま返すのが安全側 (提案≠適用)。
    """
    # 既知相を渡さない呼び出しなので、候補がパターン全体を説明する系にする (同定自体は論点でない)。
    tt, inten = _pattern([20.0, 30.0], heights=[10.0, 1.0])
    delta = _ref("mp-delta", "CaTeO3", [(20.0, 1.0), (30.0, 0.1)], ["Ca", "Te", "O"])
    seen = _prealign_recorder(monkeypatch)
    mat = _StubMaterializer()

    out = identify_and_add_phase(
        tt.tolist(), inten.tolist(), ["Ca", "Te", "O"], str(tmp_path),
        provider=_StubProvider([delta]), materializer=mat, subtract_bg=False,
    )

    assert out["n_candidates"] == 1
    assert seen == []  # プリアラインを一度も呼ばない
    assert out["candidates"][0]["refined_cell"] is None
    assert out["prealign_basis"] == "skipped"
    assert out["n_known_phases_used"] == 0
    assert mat.cells == [None]  # 等方 strain 版のまま (cell 置換なし)
    json.dumps(out, allow_nan=False)


def test_reports_skipped_when_known_phases_unconvertible(tmp_path, monkeypatch):
    """★ known_phases を渡しても CIF が読めなければ補正せず、③ に "skipped" と告げる。

    黙って生パターン整合に落ちるのも "residual" と偽るのも禁止 — ③ は Rwp 高止まりの原因を
    「相のセル誤差」と「残差の説明力」のどちらに帰すか、この 1 語で決める。
    """
    tt, inten = _pattern([20.0, 30.0], heights=[10.0, 1.0])
    delta = _ref("mp-delta", "CaTeO3", [(20.0, 1.0), (30.0, 0.1)], ["Ca", "Te", "O"])
    _stub_conversion(monkeypatch, {})  # 変換不能 (pymatgen 不在 / CIF 破損)
    seen = _prealign_recorder(monkeypatch)

    out = identify_and_add_phase(
        tt.tolist(), inten.tolist(), ["Ca", "Te", "O"], str(tmp_path),
        provider=_StubProvider([delta]), materializer=_StubMaterializer(), subtract_bg=False,
        known_phases=[{"structure_path": str(tmp_path / "alpha.cif"), "phase_name": "alpha"}],
    )

    assert seen == []
    assert out["prealign_basis"] == "skipped"
    assert out["n_known_phases_used"] == 0
    assert out["candidates"][0]["refined_cell"] is None
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param("alpha", id="known_phases が str"),
        pytest.param([{"phase_name": "alpha"}], id="structure_path 欠落"),
        pytest.param(["alpha.cif"], id="要素が dict でない"),
        pytest.param(
            [{"structure_path": "a.cif", "phase_name": "alpha", "refined_cell": [1, 2, 3]}],
            id="refined_cell が短い",
        ),
        pytest.param(
            [{"structure_path": "a.cif", "phase_name": "alpha",
              "refined_cell": [4.0, 5.0, 6.0, 90.0, 90.0, 90.0, 1.0]}],
            id="refined_cell が長い (余りを黙って捨てない)",
        ),
        pytest.param(
            [{"structure_path": "a.cif", "phase_name": "alpha",
              "refined_cell": [4.0, 5.0, 6.0, 90.0, 90.0, float("nan")]}],
            id="refined_cell に非有限値",
        ),
        pytest.param(
            [{"structure_path": "a.cif", "phase_name": "alpha",
              "refined_cell": [1, 2, 3, 4, 5, "x"]}],
            id="refined_cell が数値でない",
        ),
    ],
)
def test_malformed_known_phases_degrades_to_error_dict(tmp_path, monkeypatch, malformed):
    """★不正な known_phases は error dict へ縮退する (例外を送出しない・黙って補正を捨てない)。

    壊れた refined_cell を握り潰して "skipped" を返すと、③ は「既知相を引けなかった」と読み違え、
    自分が渡した格子が捨てられたことに気づけない (② 縮退契約 + 偽の正常応答の禁止)。
    """
    tt, inten = _pattern([20.0, 30.0])
    delta = _ref("mp-delta", "CaTeO3", [(30.0, 1.0)], ["Ca", "Te", "O"])
    seen = _prealign_recorder(monkeypatch)

    out = identify_and_add_phase(
        tt.tolist(), inten.tolist(), ["Ca", "Te", "O"], str(tmp_path),
        provider=_StubProvider([delta]), materializer=_StubMaterializer(),
        known_phases=malformed,
    )

    assert "error" in out and "error_type" in out
    assert "candidates" not in out  # 「候補ゼロ」と読める形で返さない
    assert seen == []
    json.dumps(out, allow_nan=False)


def test_known_phases_reachable_from_sequential_rietveld_output(tmp_path, monkeypatch):
    """★§4.5 到達可能性: known_phases は ② の出力だけから組める (③ は JSON しか持たない)。

    `sequential_rietveld` の `frames[].refined_cells` と、③ が渡した `initial_phases` の dict を
    そのまま合成する経路を実際に通す。ここが通らない引数は全テスト green でも ③ から呼び手が
    存在しない (dead on arrival)。
    """
    frames = [FrameSpec(str(tmp_path / "f0.xrdml"), axis_value=300.0).to_dict()]
    initial_phases = [PhaseSpec(str(tmp_path / "alpha.cif"), "alpha").to_dict()]

    def runner(frame, phases, initial_cells):
        return AutoRietveldResult(
            stage_results=(), final_rwp=9.0, final_gof=1.0,
            refined_cells={"alpha": (14.8, 6.8, 8.0, 90.0, 90.0, 90.0)},
            validity=ValidityReport(passed=True), phase_fractions={"alpha": 1.0},
        )

    seq = sequential_rietveld(frames, initial_phases, runner=runner)

    # ③ が実際に書く合成: initial_phases の dict に refined_cells を足すだけ。
    cells = seq["frames"][-1]["refined_cells"]
    known_phases = [
        dict(p, refined_cell=cells[p["phase_name"]])
        for p in initial_phases if p["phase_name"] in cells
    ]
    assert known_phases[0]["refined_cell"] == [14.8, 6.8, 8.0, 90.0, 90.0, 90.0]

    tt, inten = _pattern([20.0, 30.0], heights=[10.0, 1.0])
    alpha = _ref("alpha", "CaTeO3H2O", [(20.0, 1.0)], ["Ca", "Te", "O"])
    delta = _ref("mp-delta", "CaTeO3", [(30.0, 1.0)], ["Ca", "Te", "O"])
    conv = _stub_conversion(monkeypatch, {"alpha": alpha})
    _prealign_recorder(monkeypatch)

    out = identify_and_add_phase(
        tt.tolist(), inten.tolist(), ["Ca", "Te", "O"], str(tmp_path),
        provider=_StubProvider([delta]), materializer=_StubMaterializer(),
        subtract_bg=False, known_phases=known_phases,
    )
    assert out["prealign_basis"] == "residual"
    assert conv[0]["refined_cell"] == (14.8, 6.8, 8.0, 90.0, 90.0, 90.0)
    json.dumps(out, allow_nan=False)


# --- 波長不明 (None) の扱い: 波長依存段を止める (code-review PR #155) --------------------


def test_unknown_wavelength_disables_anisotropic_rerank(tmp_path, monkeypatch):
    """★``wavelength=None`` は「不明」— **波長依存の段をすべて止める** (推測しない)。

    **なぜ必要か (code-review PR #155)**: 呼び手が波長を知らないとき、`wavelength` を省略すると
    ② の既定 Cu Kα1 (1.5406) が使われ、それが `rerank_wavelength` に流れて**異方 re-score が
    誤波長で走る** (`rerank_top_k` は全階層で既定 5 = ON)。波長は hkl→2θ 変換に直接効くので、
    λ=0.7996 の放射光を 1.5406 と扱うと 2θ が数度ずれ `match_tol_deg` 既定 0.15° を大きく
    超える → **候補の順位付けそのものが壊れる** (「順位が少し変わる」ではない)。

    既知相の残差減算だけを止めても不十分だった、というのが指摘の要点。不変条件は
    「**波長を知らないなら波長に依存する計算を一切しない**」であり、それを呼び手ごとに
    覚えさせるのではなく ② 境界に置く。
    """
    tt, inten = _pattern([20.0, 30.0], heights=[10.0, 1.0])
    delta = _ref("mp-delta", "CaTeO3", [(30.0, 1.0)], ["Ca", "Te", "O"])
    seen: dict = {}

    def spy(two_theta, intensity, **kw):
        seen.update(kw)
        return ()

    monkeypatch.setattr("tsumugin.insitu.phaseid.identify_new_phases", spy)

    out = identify_and_add_phase(
        tt.tolist(), inten.tolist(), ["Ca", "Te", "O"], str(tmp_path),
        wavelength=None,
        known_phases=[{"structure_path": str(tmp_path / "a.cif"), "phase_name": "alpha"}],
        provider=_StubProvider([delta]), materializer=_StubMaterializer(),
    )

    assert "error" not in out, out
    # 異方 re-score を止める (誤波長で hkl→2θ を引かない)
    assert seen.get("rerank_top_k") == 0, (
        f"波長不明でも異方 re-score が走る (rerank_top_k={seen.get('rerank_top_k')!r})"
    )
    # 既知相の残差減算も行わない (既存契約)
    assert not seen.get("known_phases"), "波長不明で既知相を残差減算に使っている"
    assert seen.get("cell_refiner") is None, "波長不明でセル補正器を作っている"
    assert out["prealign_basis"] == "skipped"
    assert out["n_known_phases_used"] == 0
    json.dumps(out, allow_nan=False)


def test_known_wavelength_still_reranks(tmp_path, monkeypatch):
    """非回帰: 波長が判っていれば異方 re-score は既定どおり有効 (上の修正で殺していない)。"""
    tt, inten = _pattern([20.0, 30.0], heights=[10.0, 1.0])
    delta = _ref("mp-delta", "CaTeO3", [(30.0, 1.0)], ["Ca", "Te", "O"])
    seen: dict = {}

    def spy(two_theta, intensity, **kw):
        seen.update(kw)
        return ()

    monkeypatch.setattr("tsumugin.insitu.phaseid.identify_new_phases", spy)

    identify_and_add_phase(
        tt.tolist(), inten.tolist(), ["Ca", "Te", "O"], str(tmp_path),
        wavelength=0.7996,
        provider=_StubProvider([delta]), materializer=_StubMaterializer(),
    )

    assert seen.get("rerank_top_k") != 0, "波長が判っているのに re-score を止めている"
    assert seen.get("rerank_wavelength") == pytest.approx(0.7996)
