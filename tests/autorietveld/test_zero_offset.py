"""fit-then-judge P1a タスク 4: ゼロ点の独立解放 (`zero_offset` 段フラグ) — 決定論。

現行は Zero を Lorentzian X,Y と同じ段 (`profile_lorentzian`) で一緒に解放する。テンプレートは
位置を決める項 (格子 + オフセット 1 つ) を幅より先に解くので、Zero を X,Y から切り離す:

- ``zero_offset: True`` — Zero だけを解放する新フラグ
- ``profile_lorentzian`` のキー列 (``["X","Y"]``) — Zero を束ねずに Lorentzian だけ解放する
- 既存の ``profile_lorentzian: True`` は従来どおり X,Y,Zero (既定経路は不変)
- Zero を `CORRELATION_GROUPS` の群にする (群が唯一の出所という規則の内側に入れる)
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.engine import _apply_stage
from tsumugin.autorietveld.model import Radiation, RefinementStage
from tsumugin.autorietveld.recipe import (
    CORRELATION_GROUPS,
    CorrelationGroupViolation,
    released_group_members,
    validate_correlation_groups,
)


class _RecHist:
    def __init__(self):
        self.instr_calls = []

    def set_refinements(self, spec):
        if "Instrument Parameters" in spec:
            self.instr_calls.append(list(spec["Instrument Parameters"]))


def _run(flags, radiation=Radiation.XRAY_LAB, fixed=False):
    h = _RecHist()
    _apply_stage(None, [h], [], [], [], [radiation], RefinementStage("s", flags), [fixed])
    return h.instr_calls


def test_zero_offset_releases_only_zero():
    assert _run({"zero_offset": True}) == [["Zero"]]


def test_zero_offset_is_skipped_for_tof_and_fixed_profile():
    assert _run({"zero_offset": True}, radiation=Radiation.NEUTRON_TOF) == []
    assert _run({"zero_offset": True}, fixed=True) == []


def test_zero_offset_applies_to_cw_neutron():
    """ゼロ点は CW なら放射源によらず位置の項 (Lorentzian の除外とは理由が違う)。"""
    assert _run({"zero_offset": True}, radiation=Radiation.NEUTRON_CW) == [["Zero"]]


def test_lorentzian_key_list_releases_xy_without_zero():
    assert _run({"profile_lorentzian": ["X", "Y"]}) == [["X", "Y"]]


def test_lorentzian_true_keeps_the_legacy_xy_zero():
    assert _run({"profile_lorentzian": True}) == [["X", "Y", "Zero"]]


def test_zero_is_a_correlation_group():
    assert CORRELATION_GROUPS["zero_offset"] == ("Zero",)
    assert released_group_members({"zero_offset": True}, "zero_offset") == {"Zero"}
    assert released_group_members({"profile_lorentzian": True}, "zero_offset") == {"Zero"}
    assert released_group_members({"profile_lorentzian": ["X", "Y"]}, "zero_offset") == set()
    assert released_group_members({"profile": ["U", "V", "W", "Zero"]}, "zero_offset") == {
        "Zero"
    }


def test_lorentzian_key_list_counts_toward_the_xy_group():
    assert released_group_members({"profile_lorentzian": ["X", "Y"]}, "lorentzian_profile") == {
        "X",
        "Y",
    }


def test_splitting_x_from_y_is_refused():
    with pytest.raises(CorrelationGroupViolation):
        validate_correlation_groups([RefinementStage("l", {"profile_lorentzian": ["X"]})])


def test_layer_two_accepts_the_new_flag_and_key_list():
    from tsumugin.mcp._recipe_spec import stage_from_dict

    assert stage_from_dict({"label": "z", "flags": {"zero_offset": True}}).flags == {
        "zero_offset": True
    }
    assert stage_from_dict({"label": "l", "flags": {"profile_lorentzian": ["X", "Y"]}}).flags == {
        "profile_lorentzian": ["X", "Y"]
    }


@pytest.mark.parametrize(
    "flags",
    [{"profile_lorentzian": ["X", "Q"]}, {"profile_lorentzian": []}, {"zero_offset": "yes"}],
)
def test_layer_two_refuses_values_the_engine_would_misread(flags):
    from tsumugin.mcp._recipe_spec import stage_from_dict

    with pytest.raises(ValueError):
        stage_from_dict({"label": "bad", "flags": flags})


def test_false_values_release_nothing():
    """値の真偽で判定する — false を「解放する」と読むと検証や TOPAS と解釈が食い違う (M2)。"""
    assert _run({"zero_offset": False}) == []
    assert _run({"profile_lorentzian": False}) == []


class _ClearHist:
    def __init__(self):
        self.cleared = []

    def clear_refinements(self, spec):
        if "Instrument Parameters" in spec:
            self.cleared.extend(spec["Instrument Parameters"])


def test_freeze_others_can_keep_zero_without_keeping_widths():
    """`zero_offset` を残す名前にすると Zero だけ残り、U,V,W,X,Y は凍結される (M7)。"""
    from tsumugin.autorietveld.engine import _freeze_all

    h = _ClearHist()
    _freeze_all([h], [], [], [Radiation.XRAY_LAB], {"zero_offset"})
    assert "Zero" not in h.cleared and {"U", "V", "W", "X", "Y"} <= set(h.cleared)
    h2 = _ClearHist()
    _freeze_all([h2], [], [], [Radiation.XRAY_LAB], set())
    assert "Zero" in h2.cleared


@pytest.mark.parametrize("names", [["cell", "zero"], ["coords"]])
def test_layer_two_refuses_unknown_keep_names(names):
    """語彙外の名前は engine が黙って「残さない」と読む — 残したつもりで凍る (M7)。"""
    from tsumugin.mcp._recipe_spec import stage_from_dict

    with pytest.raises(ValueError, match="未知の名前"):
        stage_from_dict({"label": "s", "flags": {"freeze_others": names}})
