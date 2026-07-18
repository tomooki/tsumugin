"""② anchored_sequential (M10 アンカー基準双方向解析) の MCP 露出テスト (Issue #97)。

M10 anchor は 715 行の ① 実装があるのに ② ツール 0・skill 言及 0 だったため、実 operando 解析
(K2Mn[Fe(CN)6]) で使われず、M10 が既に解いている病理を ③ が再生産した。本ツールはその ②露出。

**runner/identifier は callable のため #93 と同型の JSON spec で到達可能にする**:
- runner → `instrument` spec (sequential_rietveld と共有ヘルパ `_runner_from_instrument`)
- identifier → `anchor_table` {frame_index: [phase_name]} (publication_m10.py の `_anchors.json` 方式)

決定論: runner はスタブ注入 (実 GSAS は @pytest.mark.gsas 側)。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.anchor.model import AnchorConfig
from tsumugin.insitu.model import FrameSpec
from tsumugin.mcp.anchor_tools import ANCHOR_TOOLS, anchored_sequential


def _phase(name: str) -> dict:
    return PhaseSpec(structure_path=f"{name}.cif", phase_name=name).to_dict()


def _frame(i: int) -> dict:
    return FrameSpec(data_path=f"f{i}.xye", axis_value=float(i)).to_dict()


def _stub_result(phases) -> AutoRietveldResult:
    """相集合を反映した決定論精密化結果 (アンカー確定に足る Rwp・出版値付き)。"""
    names = [p.phase_name for p in phases]
    frac = {n: 1.0 / len(names) for n in names}
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=7.0,
        final_gof=1.1,
        refined_cells={n: (10.4, 10.4, 10.4, 90.0, 90.0, 90.0) for n in names},
        validity=ValidityReport(passed=True),
        phase_fractions=frac,
        n_obs=1000,
        phase_weight_fractions=frac,
        phase_weight_fraction_esd={n: 0.006 for n in names},
        cell_esd={n: (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0) for n in names},
    )


def _runner(frame, phases, initial_cells):
    return _stub_result(phases)


def test_anchor_tools_registry_exposes_anchored_sequential():
    """ANCHOR_TOOLS が anchored_sequential を 1 ツールとして登録していること。"""
    assert ANCHOR_TOOLS == {"anchored_sequential": anchored_sequential}


def test_anchored_sequential_runs_with_anchor_table_and_stub_runner():
    """anchor_table (JSON identifier 代替) + スタブ runner で系列を解けること。"""
    frames = [_frame(i) for i in range(3)]
    phases = [_phase("mono"), _phase("cubic")]
    out = anchored_sequential(
        frames, phases,
        anchor_table={"0": ["mono"], "2": ["mono", "cubic"]},
        runner=_runner,
    )
    assert "error" not in out
    assert len(out["frames"]) == 3
    # アンカーは table のフレーム (0, 2) が確定していること
    anchor_frames = {a["frame"] for a in out["anchors"]}
    assert anchor_frames == {0, 2}


def test_anchored_sequential_exposes_per_segment_bic_for_phase_count_suppression():
    """★crossovers に total_bic を出すこと (「BIC で相数抑制」の存在を ③ に見せる = #97 の核心)。

    ユーザーが `frame_bic` を独立再導出してしまったのは、この値が ② に露出していなかったため。
    相集合の違う区間 (mono / mono+cubic) は Rwp でなく bic で選定される。
    """
    frames = [_frame(i) for i in range(3)]
    phases = [_phase("mono"), _phase("cubic")]
    out = anchored_sequential(
        frames, phases,
        anchor_table={"0": ["mono"], "2": ["mono", "cubic"]},
        runner=_runner,
    )
    assert out["crossovers"], "相集合が変わる区間があるのに crossover が 0"
    for c in out["crossovers"]:
        assert "total_bic" in c, "区間選定の bic が ③ から見えない"


def test_anchored_sequential_carries_publication_values_per_frame():
    """per-frame の出版値 (重量分率 ± esd) が届くこと (seq_result_to_dict 流用の確認)。"""
    frames = [_frame(i) for i in range(3)]
    out = anchored_sequential(
        frames, [_phase("mono")],
        anchor_table={"0": ["mono"], "2": ["mono"]},
        runner=_runner,
    )
    f0 = out["frames"][0]
    assert "phase_weight_fractions" in f0
    assert "phase_weight_fraction_esd" in f0
    assert "cell_esd" in f0


def test_anchored_sequential_without_anchor_table_falls_back_to_single_anchor():
    """anchor_table 省略 → identifier=None → M9 単一アンカー fallback に縮退 (REQ-1004)。"""
    frames = [_frame(i) for i in range(3)]
    out = anchored_sequential(frames, [_phase("mono")], runner=_runner)
    assert "error" not in out
    assert len(out["frames"]) == 3
    assert len(out["anchors"]) == 1
    assert out["anchors"][0]["fallback"] is True


def test_anchored_sequential_unknown_phase_in_table_returns_error_dict():
    """anchor_table が catalog に無い相名を参照 → error dict (③ の typo を黙って無視しない)。"""
    frames = [_frame(i) for i in range(3)]
    out = anchored_sequential(
        frames, [_phase("mono")],
        anchor_table={"0": ["nonexistent"]},
        runner=_runner,
    )
    assert "error" in out
    assert "error_type" in out
    assert "nonexistent" in out["error"]


def test_anchored_sequential_applies_anchor_config_from_json():
    """anchor_config (JSON) が適用されること: rwp 上限を厳しくするとアンカーが確定せず fallback。"""
    frames = [_frame(i) for i in range(3)]
    phases = [_phase("mono"), _phase("cubic")]
    # anchor_rwp_max=1.0 < stub rwp 7.0 → 段階 B で全候補が弾かれ fallback 単一アンカーへ
    out = anchored_sequential(
        frames, phases,
        anchor_table={"0": ["mono"], "2": ["mono", "cubic"]},
        anchor_config={"anchor_rwp_max": 1.0},
        runner=_runner,
    )
    assert "error" not in out
    assert len(out["anchors"]) == 1
    assert out["anchors"][0]["fallback"] is True


def test_anchored_sequential_bad_anchor_config_key_returns_error_dict():
    """anchor_config の未知キー → error dict (誤設定を黙って無視しない)。"""
    frames = [_frame(i) for i in range(3)]
    out = anchored_sequential(
        frames, [_phase("mono")],
        anchor_table={"0": ["mono"]},
        anchor_config={"typo_key": 1.0},
        runner=_runner,
    )
    assert "error" in out
    assert "typo_key" in out["error"]


def test_anchored_sequential_bad_instrument_returns_error_dict():
    """instrument の auto_freeze_minor_cells に bool → error dict (#80 の静かな全相凍結を拒否)。"""
    frames = [_frame(i) for i in range(2)]
    out = anchored_sequential(
        frames, [_phase("mono")],
        anchor_table={"0": ["mono"]},
        instrument={"path": "x.instprm", "auto_freeze_minor_cells": True},
    )
    assert "error" in out
    assert "error_type" in out


def test_anchored_sequential_reports_ledger_verification():
    """ledger のハッシュチェーン検証結果を返すこと (NFR-105; 追記型の健全性を ③ に見せる)。"""
    frames = [_frame(i) for i in range(3)]
    out = anchored_sequential(
        frames, [_phase("mono")],
        anchor_table={"0": ["mono"], "2": ["mono"]},
        runner=_runner,
    )
    assert out["ledger_verified"] is True


# --- ① AnchorConfig.from_dict (② の JSON 経路が依存するヘルパ) ---


def test_anchor_config_from_dict_empty_is_all_defaults():
    assert AnchorConfig.from_dict({}) == AnchorConfig()


def test_anchor_config_from_dict_coerces_types():
    cfg = AnchorConfig.from_dict(
        {"anchor_rwp_max": 15, "base_params": 40.0, "require_anchor_validity": True}
    )
    assert cfg.anchor_rwp_max == 15.0
    assert isinstance(cfg.anchor_rwp_max, float)
    assert cfg.base_params == 40
    assert isinstance(cfg.base_params, int)
    assert cfg.require_anchor_validity is True


def test_anchor_config_from_dict_rejects_unknown_keys():
    import pytest

    with pytest.raises(ValueError, match="unknown"):
        AnchorConfig.from_dict({"not_a_field": 1})
