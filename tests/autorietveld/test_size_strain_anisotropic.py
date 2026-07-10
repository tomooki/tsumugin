"""size_strain の mustrain type 選択 + 異方性の X 線限定ターゲティングのテスト。

GSAS 非依存モック (set_HAP_refinements 記録) で _apply_stage の size_strain 分岐を検証する。
- True → isotropic (後方互換), targets = non_lowres。
- "generalized"/"uniaxial" → 当該 type, targets = X 線のみ (中性子除外; ND 発散回避)。
- 未知文字列 → isotropic フォールバック。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _apply_stage
from tsumugin.autorietveld.model import Radiation, RefinementStage


class _Phase:
    def __init__(self):
        self.hap_calls = []

    def set_HAP_refinements(self, spec, histograms=None):
        self.hap_calls.append((spec, histograms))


def _run(size_strain_val, hists, radiations):
    ph = _Phase()
    stage = RefinementStage("ss", {"size_strain": size_strain_val})
    # phase_infos / atom_flag_maps は size_strain 分岐では未使用 (ダミー)。
    _apply_stage(None, hists, [ph], [{}], [{}], radiations, stage)
    # size_strain 由来の HAP 呼び出しを取り出す (Mustrain キーを含むもの)。
    ms = [(spec, hg) for spec, hg in ph.hap_calls if "Mustrain" in spec]
    assert len(ms) == 1
    return ms[0]


def test_true_is_isotropic_nonlowres():
    hx, hn = "XRAY", "NDTOF"
    spec, targets = _run(True, [hx, hn], [Radiation.XRAY_SYNCHROTRON, Radiation.NEUTRON_TOF])
    assert spec["Mustrain"]["type"] == "isotropic"
    # TOF は non_lowres に含まれる → 両方対象。
    assert set(targets) == {hx, hn}


def test_generalized_targets_xray_only():
    hx, hn = "XRAY", "NDTOF"
    spec, targets = _run("generalized", [hx, hn],
                         [Radiation.XRAY_SYNCHROTRON, Radiation.NEUTRON_TOF])
    assert spec["Mustrain"]["type"] == "generalized"
    assert targets == [hx]  # 中性子 (TOF) を除外


def test_uniaxial_targets_xray_only():
    hx, hn = "XRAY", "NDTOF"
    spec, targets = _run("uniaxial", [hx, hn],
                         [Radiation.XRAY_LAB, Radiation.NEUTRON_TOF])
    assert spec["Mustrain"]["type"] == "uniaxial"
    assert targets == [hx]


def test_unknown_string_falls_back_isotropic():
    hx = "XRAY"
    spec, _ = _run("bogus", [hx], [Radiation.XRAY_SYNCHROTRON])
    assert spec["Mustrain"]["type"] == "isotropic"


def test_generalized_no_xray_falls_back():
    # X 線が無い場合は non_lowres フォールバック (単一 TOF → その 1 本)。
    hn = "NDTOF"
    spec, targets = _run("generalized", [hn], [Radiation.NEUTRON_TOF])
    assert targets == [hn]  # フォールバックで対象になる (revert ガードが安全網)
