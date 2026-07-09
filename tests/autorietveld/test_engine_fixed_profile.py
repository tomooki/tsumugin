"""装置プロファイル固定の engine 配線 (TASK-0003) の決定論テスト。

_fixed_profile_flags と _apply_stage の per-hist skip を GSAS 非依存モックで検証。numpy-only。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _apply_stage, _fixed_profile_flags
from tsumugin.autorietveld.model import (
    Geometry,
    HistogramSpec,
    InstrumentProfile,
    Radiation,
    RefinementStage,
)


def _hist(profile=None):
    return HistogramSpec("d.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
                         instrument_profile=profile)


class _RecHist:
    """set_refinements の呼び出しを記録するモックヒストグラム。"""

    def __init__(self):
        self.instr_calls = []

    def set_refinements(self, spec):
        if "Instrument Parameters" in spec:
            self.instr_calls.append(list(spec["Instrument Parameters"]))


_X = [Radiation.XRAY_SYNCHROTRON, Radiation.XRAY_SYNCHROTRON]


def _run(stage, fixed):
    h0, h1 = _RecHist(), _RecHist()
    _apply_stage(None, [h0, h1], [], [], [], _X, stage, fixed)
    return h0, h1


# --- _fixed_profile_flags ---

def test_fixed_profile_flags():
    ip = InstrumentProfile(values={"U": 1.0})
    hs = [_hist(ip), _hist(None), _hist(ip)]
    assert _fixed_profile_flags(hs) == [True, False, True]


def test_fixed_profile_flags_all_none():
    assert _fixed_profile_flags([_hist(), _hist()]) == [False, False]


# --- _apply_stage profile skip (U,V,W) ---

def test_profile_stage_skips_fixed_hist():
    h0, h1 = _run(RefinementStage("p", {"profile": ["U", "V", "W"]}), [True, False])
    assert h0.instr_calls == []             # 固定 → 解放しない
    assert h1.instr_calls == [["U", "V", "W"]]  # 非固定 → 従来どおり


def test_lorentzian_stage_skips_fixed_hist():
    h0, h1 = _run(RefinementStage("l", {"profile_lorentzian": True}), [True, False])
    assert h0.instr_calls == []
    assert h1.instr_calls == [["X", "Y", "Zero"]]


def test_asymmetry_stage_skips_fixed_hist():
    h0, h1 = _run(RefinementStage("a", {"profile_asymmetry": True}), [True, False])
    assert h0.instr_calls == []
    assert h1.instr_calls == [["SH/L"]]


def test_default_none_releases_all_backward_compat():
    # fixed_profile 未指定 → 全解放 (後方互換, T1〜T4 非回帰)
    h0, h1 = _RecHist(), _RecHist()
    _apply_stage(None, [h0, h1], [], [], [], _X, RefinementStage("p", {"profile": ["U", "V", "W"]}))
    assert h0.instr_calls == [["U", "V", "W"]]
    assert h1.instr_calls == [["U", "V", "W"]]
