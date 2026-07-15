"""_apply_initial_fractions の決定論テスト (Issue #82 再スコープ: 分率ウォームスタート seeding)。

run_sequential_rietveld の warm_start は格子のみを引き継ぎ相分率は毎フレーム既定 HAP Scale から
再出発するため、転移ドーム域で分率精密化が既定値に張り付くフレームが生じる (実測、issue #82 参照)。
`run_auto_rietveld(initial_fractions=)` が呼ぶ `_apply_initial_fractions` を GSAS 非依存のスタブ
(getHAPvalues/setHAPvalues を模した最小 G2Phase 代替) で検証する。numpy-only。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _apply_initial_fractions


class _StubHAPPhase:
    """getHAPvalues/setHAPvalues を持つ最小スタブ (GSAS G2Phase の代替)。

    HAP (Histogram-And-Phase) 値は「ヒストグラムオブジェクト→{'Scale': [value, refine_flag], ...}」
    の dict として保持する (実 GSAS の ph.data['Histograms'][histname] 相当)。
    """

    def __init__(self, name: str, hap_by_hist: dict[object, dict[str, list]]) -> None:
        self.name = name
        self._hap = hap_by_hist
        self.set_calls: list[tuple[dict, list]] = []

    def getHAPvalues(self, hist):
        return self._hap[hist]

    def setHAPvalues(self, hap_dict, targethistlist):
        self.set_calls.append((dict(hap_dict), list(targethistlist)))
        for hist in targethistlist:
            self._hap[hist].update(hap_dict)


def _phase(name: str, hist, scale=1.0, refine=False) -> _StubHAPPhase:
    return _StubHAPPhase(name, {hist: {"Scale": [scale, refine]}})


def test_seeds_hap_scale_from_fractions():
    """initial_fractions が与えられると各相の HAP Scale の値がそれで置き換わる。"""
    hist = object()
    alpha = _phase("alpha", hist, scale=1.0, refine=True)
    delta = _phase("delta", hist, scale=1.0, refine=True)

    _apply_initial_fractions([alpha, delta], [hist], {"alpha": 0.6, "delta": 0.4})

    assert alpha.getHAPvalues(hist)["Scale"][0] == 0.6
    assert delta.getHAPvalues(hist)["Scale"][0] == 0.4
    assert len(alpha.set_calls) == 1
    assert len(delta.set_calls) == 1


def test_preserves_existing_refine_flag():
    """値のみ差し替え、既存の refine フラグ (解放/固定) は変更しない。"""
    hist = object()
    alpha = _phase("alpha", hist, scale=1.0, refine=False)

    _apply_initial_fractions([alpha], [hist], {"alpha": 0.7})

    scale = alpha.getHAPvalues(hist)["Scale"]
    assert scale == [0.7, False]


def test_none_or_empty_fractions_skips_seeding():
    """fractions が None/空なら setHAPvalues を一切呼ばない (非回帰の既定動作)。"""
    hist = object()
    alpha = _phase("alpha", hist)

    _apply_initial_fractions([alpha], [hist], {})
    assert alpha.set_calls == []

    _apply_initial_fractions([alpha], [hist], None)  # type: ignore[arg-type]
    assert alpha.set_calls == []


def test_unknown_phase_names_are_ignored():
    """fractions にない相名 (未知の相) は無視され seeding も呼ばれない。"""
    hist = object()
    alpha = _phase("alpha", hist, scale=1.0)

    _apply_initial_fractions([alpha], [hist], {"beta": 0.5, "gamma": 0.5})

    assert alpha.set_calls == []
    assert alpha.getHAPvalues(hist)["Scale"][0] == 1.0


def test_all_zero_fractions_are_skipped_fail_open():
    """全値がゼロなら fail-open でシーディングを丸ごとスキップする (全相 0 分率の事故防止)。"""
    hist = object()
    alpha = _phase("alpha", hist, scale=1.0)
    delta = _phase("delta", hist, scale=1.0)

    _apply_initial_fractions([alpha, delta], [hist], {"alpha": 0.0, "delta": 0.0})

    assert alpha.set_calls == []
    assert delta.set_calls == []


def test_non_finite_fractions_are_skipped_fail_open():
    """全値が非有限 (nan/inf) なら fail-open でスキップする。"""
    hist = object()
    alpha = _phase("alpha", hist, scale=1.0)

    _apply_initial_fractions([alpha], [hist], {"alpha": float("nan")})
    assert alpha.set_calls == []

    _apply_initial_fractions([alpha], [hist], {"alpha": float("inf")})
    assert alpha.set_calls == []
