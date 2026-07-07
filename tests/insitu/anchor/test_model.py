"""M10 anchor/model.py の dataclass 群テスト (numpy 決定論・不変性)。"""

from __future__ import annotations

import dataclasses

import pytest

from tsumugin.autorietveld.model import PhaseSpec
from tsumugin.insitu.anchor.model import (
    Anchor,
    AnchorConfig,
    CrossoverChoice,
    Segment,
    SegmentPass,
)
from tsumugin.insitu.model import FrameRietveldResult


def _anchor(frame=0, phases=("alpha",), fallback=False):
    specs = tuple(PhaseSpec(structure_path=f"{p}.cif", phase_name=p) for p in phases)
    cells = {p: (5.0, 5.0, 5.0, 90.0, 90.0, 90.0) for p in phases}
    return Anchor(frame_index=frame, axis_value=float(frame * 10), phase_specs=specs,
                  refined_cells=cells, rwp=10.0, gof=1.2, confidence=0.8, fallback=fallback)


def test_config_defaults():
    cfg = AnchorConfig()
    assert cfg.anchor_confidence_min == 0.5
    assert cfg.anchor_rwp_max == 20.0
    assert cfg.per_phase_params > 0 and cfg.base_params > 0
    assert cfg.bond_tol_lo < 1.0 < cfg.bond_tol_hi


def test_config_frozen():
    cfg = AnchorConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.anchor_rwp_max = 5.0  # type: ignore[misc]


def test_anchor_phase_names():
    a = _anchor(phases=("alpha", "new_delta"))
    assert a.phase_names == ("alpha", "new_delta")
    assert a.frame_index == 0


def test_anchor_frozen():
    a = _anchor()
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.rwp = 1.0  # type: ignore[misc]


def test_segment_endpoint_one_sided():
    a = _anchor(frame=3)
    seg = Segment(left=None, right=a, frame_indices=(0, 1, 2), one_sided=True)
    assert seg.left is None
    assert seg.right is a
    assert seg.one_sided is True
    assert seg.frame_indices == (0, 1, 2)


def test_segment_pass_default_results():
    sp = SegmentPass(direction="forward")
    assert sp.direction == "forward"
    assert sp.results == {}
    # 別インスタンスが同じ dict を共有しない (default_factory)
    sp2 = SegmentPass(direction="backward")
    assert sp.results is not sp2.results


def test_segment_pass_holds_results():
    fr = FrameRietveldResult(frame_index=1, axis_value=10.0, data_path="f1.xye", rwp=9.0,
                             gof=1.1, refined_cells={}, phase_fractions={"alpha": 1.0},
                             phase_names=("alpha",))
    sp = SegmentPass(direction="forward", results={1: fr})
    assert sp.results[1].rwp == 9.0


def test_crossover_choice_defaults():
    c = CrossoverChoice(crossover_frame=5, total_bic=123.4)
    assert c.crossover_frame == 5
    assert c.onset_frame is None
    assert c.monotonic is True
    assert c.reason == ""


def test_dataclasses_deterministic_equality():
    assert _anchor() == _anchor()
    assert AnchorConfig() == AnchorConfig()
    assert CrossoverChoice(1, 2.0) == CrossoverChoice(1, 2.0)
