"""相分率連動の自動セル凍結 (auto_freeze_minor_cells, Issue #80: #47/#50 の自動化) のテスト。

`_should_refine_cell` (純関数の判定ヘルパ) と `_apply_stage` の "cell" 段への配線を
GSAS 非依存のスタブ/モックで検証する。numpy-only。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _apply_stage, _should_refine_cell
from tsumugin.autorietveld.model import RefinementStage, Radiation


def _info(refine_cell: bool = True) -> dict:
    return {
        "refine_cell": refine_cell,
        "labels": [], "coord_atoms": [], "mixed": set(),
        "free_occ": set(), "equiv_occ": set(), "uiso_labels": [],
    }


# --- _should_refine_cell (純関数の判定ヘルパ) ---


def test_threshold_none_ignores_fraction_current_behaviour():
    # auto_freeze_minor_cells=None → 従来動作 (fraction に関わらず解放)。
    assert _should_refine_cell(_info(), fraction=0.01, threshold=None) is True
    assert _should_refine_cell(_info(), fraction=None, threshold=None) is True


def test_below_threshold_freezes():
    assert _should_refine_cell(_info(), fraction=0.1, threshold=0.2) is False


def test_above_threshold_refines():
    assert _should_refine_cell(_info(), fraction=0.5, threshold=0.2) is True


def test_equal_threshold_refines():
    # fraction == threshold は「未満」に該当しないので解放する境界仕様。
    assert _should_refine_cell(_info(), fraction=0.2, threshold=0.2) is True


def test_manual_false_wins_even_with_auto_enabled():
    # 明示 refine_cell=False は分率が閾値以上でも常に優先し凍結する。
    assert _should_refine_cell(_info(refine_cell=False), fraction=0.9, threshold=0.2) is False


def test_manual_false_wins_when_auto_disabled():
    # 従来の Issue #47 挙動 (auto 無効でも手動凍結は効く)。
    assert _should_refine_cell(_info(refine_cell=False), fraction=None, threshold=None) is False


def test_single_phase_fraction_never_frozen():
    # 単相は分率 1.0 なので、閾値がどうであれ凍結されない (全凍結ガード)。
    assert _should_refine_cell(_info(), fraction=1.0, threshold=0.2) is True
    assert _should_refine_cell(_info(), fraction=1.0, threshold=0.99) is True


def test_fraction_unavailable_fails_open():
    # 分率不明 (None) は自動閾値が有効でも凍結しない (fail open)。
    assert _should_refine_cell(_info(), fraction=None, threshold=0.2) is True


# --- _apply_stage 統合 (cell 段への配線) ---


class _RecPhase:
    """set_refinements を記録し getHAPvalues で相分率を返す相モック。"""

    def __init__(self, name: str, scale: float | None = None):
        self.name = name
        self._scale = scale
        self.calls: list[dict] = []

    def set_refinements(self, d):
        self.calls.append(d)

    def set_HAP_refinements(self, *a, **k):
        pass

    def getHAPvalues(self, hist):
        if self._scale is None:
            raise RuntimeError("scale unavailable")
        return {"Scale": [self._scale]}

    def cell_refined(self) -> bool:
        return any(c.get("Cell") is True for c in self.calls)


def _stage() -> RefinementStage:
    return RefinementStage("cell", {"cell": True})


def _phase_infos(n: int) -> list[dict]:
    return [_info() for _ in range(n)]


def test_apply_stage_auto_freeze_disabled_refines_all():
    # auto_freeze_minor_cells=None (既定) → 現行動作そのまま (非回帰)。
    dominant, minor = _RecPhase("dominant", 0.9), _RecPhase("minor", 0.1)
    _apply_stage(
        gpx=None, hists=[object()], phases=[dominant, minor],
        phase_infos=_phase_infos(2), atom_flag_maps=[{}, {}],
        radiations=[Radiation.XRAY_SYNCHROTRON], stage=_stage(),
        auto_freeze_minor_cells=None,
    )
    assert dominant.cell_refined() is True
    assert minor.cell_refined() is True


def test_apply_stage_freezes_minor_phase_below_threshold():
    dominant, minor = _RecPhase("dominant", 0.9), _RecPhase("minor", 0.1)
    auto_frozen = _apply_stage(
        gpx=None, hists=[object()], phases=[dominant, minor],
        phase_infos=_phase_infos(2), atom_flag_maps=[{}, {}],
        radiations=[Radiation.XRAY_SYNCHROTRON], stage=_stage(),
        auto_freeze_minor_cells=0.2,
    )
    assert dominant.cell_refined() is True
    assert minor.cell_refined() is False
    assert auto_frozen == ["minor"]


def test_apply_stage_refines_phase_above_threshold():
    a, b = _RecPhase("a", 0.6), _RecPhase("b", 0.4)
    auto_frozen = _apply_stage(
        gpx=None, hists=[object()], phases=[a, b],
        phase_infos=_phase_infos(2), atom_flag_maps=[{}, {}],
        radiations=[Radiation.XRAY_SYNCHROTRON], stage=_stage(),
        auto_freeze_minor_cells=0.2,
    )
    assert a.cell_refined() is True
    assert b.cell_refined() is True
    assert auto_frozen == []


def test_apply_stage_manual_freeze_wins_over_auto():
    dominant = _RecPhase("dominant", 0.9)
    minor = _RecPhase("minor", 0.5)  # 分率は閾値以上だが手動凍結
    phase_infos = [_info(), _info(refine_cell=False)]
    auto_frozen = _apply_stage(
        gpx=None, hists=[object()], phases=[dominant, minor],
        phase_infos=phase_infos, atom_flag_maps=[{}, {}],
        radiations=[Radiation.XRAY_SYNCHROTRON], stage=_stage(),
        auto_freeze_minor_cells=0.2,
    )
    assert dominant.cell_refined() is True
    assert minor.cell_refined() is False
    # 手動凍結は auto_frozen (自動判定による凍結) には計上しない。
    assert auto_frozen == []


def test_apply_stage_single_phase_never_auto_frozen():
    only = _RecPhase("only", 1.0)
    auto_frozen = _apply_stage(
        gpx=None, hists=[object()], phases=[only],
        phase_infos=_phase_infos(1), atom_flag_maps=[{}],
        radiations=[Radiation.XRAY_SYNCHROTRON], stage=_stage(),
        auto_freeze_minor_cells=0.5,
    )
    assert only.cell_refined() is True
    assert auto_frozen == []


def test_apply_stage_fraction_unavailable_fails_open():
    # hists=[] → _phase_fraction_map が空 dict を返し、全相の分率が None (fail open)。
    dominant, minor = _RecPhase("dominant", 0.9), _RecPhase("minor", 0.1)
    auto_frozen = _apply_stage(
        gpx=None, hists=[], phases=[dominant, minor],
        phase_infos=_phase_infos(2), atom_flag_maps=[{}, {}],
        radiations=[Radiation.XRAY_SYNCHROTRON], stage=_stage(),
        auto_freeze_minor_cells=0.2,
    )
    assert dominant.cell_refined() is True
    assert minor.cell_refined() is True
    assert auto_frozen == []
