"""``dlg`` スタブの**副作用計測** (D4 / REQ-SAR-203, @pytest.mark.gsas)。

architecture.md D4 は「dlg を渡すと `GSASIIstrMain`:430 の ``if dlg: break`` により**特異行列時の
自動パラメータ削除+再試行を失う**」ことを既定 OFF の根拠に挙げていた。ソースを読むと:

* その「削除+再試行」は ``'Hessian' not in Controls['deriv type']`` の **else 分岐にしかない**
  (`GSASIIstrMain`:431-438)。
* 既定の ``analytic Hessian`` では ``result[1] is None`` が :326-329 で**先に break** するので、
  ``if dlg: break`` を含む except 節そのものに到達しない。
* 「弱い/特異な変数を落として続ける」処理は `GSASIImath.HessianLSQ` 内の ``dropTerms`` にあり、
  **dlg を参照しない**。

したがって D4 の懸念は**この経路には当てはまらない**はず — 本ファイルはそれを実測で固定する。
逆に言えば、GSAS-II 側が deriv type の既定を変えたり分岐を書き換えたら、ここが落ちて再検討を促す。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.autorietveld.model import RefinementStage, StabilityOptions
from tsumugin.store import Ledger

_DATA = Path("docs/benchmark/testdata")

pytestmark = pytest.mark.gsas

#: 拘束を有効化する設定 (= dlg スタブが Refine へ渡る唯一の入口)。
_ON = StabilityOptions(enable_restraints=True, prune_weak_vars=True)


def _data_present() -> bool:
    return (_DATA / "PBSO4.XRA").exists() and (_DATA / "PbSO4-Wyckoff.cif").exists()


def _hist() -> HistogramSpec:
    return HistogramSpec(
        data_path=str(_DATA / "PBSO4.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )


def _phase(name: str) -> PhaseSpec:
    return PhaseSpec(
        structure_path=str(_DATA / "PbSO4-Wyckoff.cif"), phase_name=name, format_hint="CIF"
    )


def _stages(*pairs):
    return tuple(RefinementStage(label=lb, flags=fl, note="") for lb, fl in pairs)


_SB = ("sb", {"scale": True, "background": {"coeffs": 6}})


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
def test_engine_uses_the_analytic_hessian_path() -> None:
    """D4 の議論の**前提**: engine が作る gpx の deriv type が ``analytic Hessian`` であること。

    これが変わると「``if dlg: break`` に到達しない」という結論ごと崩れる (別分岐に載る)。
    前提を暗黙にせず、明示的に固定しておく。
    """
    from GSASII import GSASIIscriptable as G2sc

    with tempfile.TemporaryDirectory() as tmp:
        keep = str(Path(tmp) / "d.gpx")
        run_auto_rietveld([_hist()], [_phase("pbso4")], recipe=_stages(_SB), max_cyc=2,
                          keep_gpx=keep)
        controls = G2sc.G2Project(keep).data["Controls"]["data"]
    assert "Hessian" in controls["deriv type"], controls["deriv type"]


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
def test_singular_parameter_is_still_dropped_automatically_with_the_stub() -> None:
    """★D4 の副作用計測①: **完全縮退**した母数でも自動ドロップが dlg の有無で変わらない。

    同一構造の 2 相に相分率和=1 を課すと、回折パターンからは分率が**原理的に決まらない**
    (完全縮退)。`HessianLSQ` はこれを検出して該当パラメータを落として続行する。

    実測 (2026-07-29, PbSO4 ×2): dlg 無/有ともに ``Error: 1 Parameter(s) dropped: ::constr0``、
    Rwp 40.34906 (ビット同一)、n_params 8、相分率 0.5/0.5 — **完全に同一**。
    自動ドロップは `HessianLSQ` 内にあり dlg を見ないので、当然そうなる。
    """
    from GSASII import GSASIIscriptable as G2sc

    from tsumugin.autorietveld.diagnostics import read_diagnostics

    recipe = _stages(_SB, ("frac", {"phase_fraction_sum": True}))
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for label, stab in (("off", None), ("on", _ON)):
            keep = str(Path(tmp) / f"deg_{label}.gpx")
            r = run_auto_rietveld(
                [_hist()], [_phase("a"), _phase("b")], recipe=recipe, max_cyc=12,
                keep_gpx=keep, stability=stab,
            )
            diag = read_diagnostics(G2sc.G2Project(keep))
            out[label] = (
                tuple(round(s.rwp, 8) for s in r.stage_results),
                tuple(s.n_params for s in r.stage_results),
                diag.message,
            )

    assert "dropped" in out["off"][2], "縮退が起きていない (テストが何も見ていない)"
    assert out["on"] == out["off"], (
        f"dlg スタブを渡すと縮退の扱いが変わった: {out['off']} vs {out['on']} — "
        "D4 の副作用 (自動パラメータ削除を失う) が現実になった可能性。既定 OFF の根拠を再評価せよ"
    )


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
def test_a_truly_singular_matrix_fails_identically_with_and_without_the_stub() -> None:
    """★D4 の副作用計測②: 共分散が返らない (真の特異行列) 場合も dlg で挙動が変わらない。

    `HessianLSQ` が ``cov=None`` を返す状況を**強制注入**して、``analytic Hessian`` 分岐の
    ``elif result[1] is None: … break`` (`GSASIIstrMain`:326-329) が dlg より先に効くことを見る。
    D4 が心配した「パラメータを 1 個消して再試行するループ」は non-Hessian 分岐にしか無いので、
    どちらでも **1 回で諦めて失敗を返す**のが正しい挙動。

    実測 (2026-07-29): dlg 無/有ともに ``HessianLSQ`` 呼び出しは 1 精密化あたり 1 回、
    ``RefinementFailedError`` → chi2=inf → revert。**失うものは無い**。
    """
    from GSASII import GSASIImath as G2mth

    original = G2mth.HessianLSQ
    results = {}
    for label, stab in (("off", None), ("on", _ON)):
        calls = {"n": 0}

        def fake(*args, _calls=calls, **kwargs):
            _calls["n"] += 1
            if _calls["n"] > 20:  # 再試行ループに落ちたら無限に回るので安全弁で止める
                raise AssertionError("HessianLSQ が 20 回を超えて呼ばれた = 再試行ループ")
            out = original(*args, **kwargs)
            return [out[0], None, out[2]]  # 特異行列 (covMatrix なし) を強制

        ledger = Ledger()
        G2mth.HessianLSQ = fake
        try:
            r = run_auto_rietveld(
                [_hist()], [_phase("pbso4")],
                recipe=_stages(_SB, ("cell", {"cell": True})),
                max_cyc=6, ledger=ledger, stability=stab,
            )
        finally:
            G2mth.HessianLSQ = original
        n_stages = sum(1 for e in ledger.entries if e.kind == "m7_stage")
        n_errors = sum(1 for e in ledger.entries if e.kind == "m7_stage_error")
        results[label] = (calls["n"], n_stages, n_errors,
                          tuple(s.reverted for s in r.stage_results))

    # 失敗は例外でなく chi2=inf → revert へ変換される (CLAUDE.md 不変条件) — 両経路で同じ。
    assert results["off"][2] == results["off"][1] > 0, "強制注入が効いていない"
    assert all(results["off"][3]), "特異行列の段が revert されていない"
    assert results["on"] == results["off"], (
        f"dlg の有無で特異行列の扱いが変わった: {results['off']} vs {results['on']}"
    )
    # 再試行ループは元から無い (1 精密化 = 1 呼び出し)。dlg でそれを「失う」ことはない。
    assert results["off"][0] == results["off"][1]
