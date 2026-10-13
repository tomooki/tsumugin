"""テンプレートの静的コンパイル (proposal §4.2・§4.4, REQ-FTJ-1B-401〜404)。

pass 1 が決めた判断 (`TemplateDecisions`) を、**静的な `RefinementStage` 列 + `PhaseSpec` のフィールド +
ヒストグラム**だけで表す。結果は ``run_auto_rietveld(recipe=…)`` だけで再生できる (動的な実行の器を作らない)。
本モジュールは純関数のみ (GSAS を呼ばない)。

段の表 (proposal §4.2 を写したもの。要らない段は出さない):

| # | label | 解放 |
|---|---|---|
| 0 | scale+background | 全相スケール + 背景 (多相なら相分率) |
| 1 | lattice+offset | 凍結しない相の格子 + オフセット (BB: Shift / DS: Zero) |
| 2 | width-1 | 較正なし U,V,W / 較正あり Size+Mustrain |
| 3 | width-2 | 較正なし X,Y (Zero を束ねない) |
| 4 | asym | 較正なしのときだけ SH/L |
| R | lattice-retry | 全相の格子 (pass 1 で凍結した相の再試行 + 段 1 が棄却されたときの再試行) |
| 5 | coords | 対象相の自由座標 (非対象相は凍結・極性群は原点固定) |
| 6 | B | 対象相の Uiso (まとめ方は pass 1 の規則) |
| 7 | occupancy | 対象相に混合占有・部分占有があるときだけ |
| 8 | pref | Bragg-Brentano のときだけ (対象相・March–Dollase) |
| 8R | struct-retry | 座標 + Uiso をもう一度 (段 5/6 が棄却されていたら拾う) |
| 9 | final | 新しい解放なし (全受理パラメータの回し直し + 収束確認は候補の StabilityOptions) |

フラグは累積 (engine は enable のみ) なので、R・8R は「棄却された解放をもう一度試す」段で、既に受理済みなら
同じ解放の回し直しになる (期待する新しい自由度は 0 — note に ``expected_new_dof=0`` を残す)。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence

from ..autorietveld.model import Geometry, HistogramSpec, PhaseSpec, RefinementStage
from ..autorietveld.recipe import check_phase_scoped_flags, validate_correlation_groups

__all__ = [
    "TEMPLATE_VERSION",
    "CompiledTemplate",
    "TemplateDecisions",
    "compile_template",
    "pass1_stages",
]

#: テンプレートの版。段順・規則を変えたら上げる (P1.5 の凍結は版とハッシュで行う)。
TEMPLATE_VERSION = "fit-then-judge/1B/1"

#: R・8R・9 の note に付ける印 (期待する新しい自由度が 0 の段 — no-op の判定から外して読む)。
NO_NEW_DOF = "expected_new_dof=0"


@dataclass(frozen=True)
class TemplateDecisions:
    """pass 1 が決めること (コンパイルで固定するもの, proposal §4.4)。

    :param target_phase: 対象相 (構造を精密化する 1 相)
    :param phase_labels: 相名 → 原子ラベル (非対象相の構造を凍結するのに使う。pass 1 の結果から)
    :param frozen_cell_phases: pass 1 で格子を凍結した相 (段 1 から外し、段 R でもう一度試す)
    :param background_coeffs: 背景の項数
    :param uiso_groups: 対象相の Uiso の等値の組 (2 原子以上の組だけ)
    :param calibrated: 装置関数が較正済みか (宣言または `HistogramSpec.instrument_profile`)
    """

    target_phase: str
    phase_labels: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    frozen_cell_phases: tuple[str, ...] = ()
    background_coeffs: int = 6
    uiso_groups: tuple[tuple[str, ...], ...] = ()
    calibrated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "target_phase": self.target_phase,
            "phase_labels": {k: list(v) for k, v in self.phase_labels.items()},
            "frozen_cell_phases": list(self.frozen_cell_phases),
            "background_coeffs": self.background_coeffs,
            "uiso_groups": [list(g) for g in self.uiso_groups],
            "calibrated": self.calibrated,
        }


@dataclass(frozen=True)
class CompiledTemplate:
    """コンパイル結果。``run_auto_rietveld(histograms, phases, recipe=stages)`` で再生できる。"""

    stages: tuple[RefinementStage, ...]
    phases: tuple[PhaseSpec, ...]
    histograms: tuple[HistogramSpec, ...]
    background_coeffs: int
    template_version: str
    derivation: Mapping[str, object]


def _target_has_occupancy(spec: PhaseSpec) -> bool:
    return bool(
        spec.mixed_occupancy_groups or spec.free_occupancy_labels
        or spec.occupancy_equiv_groups or spec.occupancy_sum_groups
    )


def _head_stages(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    background_coeffs: int,
    calibrated: bool,
    cell_phases: "Sequence[str] | None",
) -> list[RefinementStage]:
    """段 0–4 (pass 1 と pass 2 で共通)。"""
    geometry = histograms[0].geometry
    stage0: dict[str, object] = {"scale": True, "background": {"coeffs": background_coeffs}}
    if len(phases) > 1:
        stage0["phase_fraction_sum"] = True
    # cell_phases が空 = 全相の格子を凍結した (pass 1 の帰属でどの 1 相を外しても段 1 が通らなかった)。
    #   段 1 はオフセットだけを解放し、格子は段 R に任せる。
    stage1: dict[str, object] = {}
    if cell_phases is None:
        stage1["cell"] = True
    elif cell_phases:
        stage1["cell"] = True
        stage1["cell_phases"] = list(cell_phases)
    if geometry is Geometry.BRAGG_BRENTANO:
        stage1["displacement"] = {0: ["Shift"]}
        offset_note = "Shift (Zero は装置値)"
    else:
        stage1["zero_offset"] = True
        offset_note = "Zero (偏心は解放しない)"
    out = [
        RefinementStage("T0 scale+background", stage0, f"背景 {background_coeffs} 項"),
        RefinementStage(
            "T1 lattice+offset", stage1,
            (f"格子 + {offset_note}" if "cell" in stage1 else f"{offset_note} (格子は段 R)"),
        ),
    ]
    if calibrated:
        out.append(
            RefinementStage(
                "T2 width-1", {"size_strain": "isotropic"},
                "較正済みの装置関数 → 幅は試料広がり (Size/Mustrain)",
            )
        )
    else:
        out.append(RefinementStage("T2 width-1", {"profile": ["U", "V", "W"]}, "U,V,W"))
        out.append(
            RefinementStage("T3 width-2", {"profile_lorentzian": ["X", "Y"]}, "X,Y (Zero を束ねない)")
        )
        out.append(RefinementStage("T4 asym", {"profile_asymmetry": True}, "SH/L"))
    return out


def pass1_stages(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    background_coeffs: int,
    calibrated: bool,
    cell_phases: "Sequence[str] | None" = None,
    extra: Sequence[RefinementStage] = (),
) -> tuple[RefinementStage, ...]:
    """pass 1 の段列 (段 0–4 + 検定のための追加段 ``extra``)。"""
    stages = tuple(
        _head_stages(
            histograms, phases, background_coeffs=background_coeffs,
            calibrated=calibrated, cell_phases=cell_phases,
        )
    ) + tuple(extra)
    validate_correlation_groups(stages, histograms=histograms)
    check_phase_scoped_flags(stages, phases)
    return stages


def compile_template(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    decisions: TemplateDecisions,
    *,
    evidence: "Mapping[str, object] | None" = None,
) -> CompiledTemplate:
    """判断を静的な段列と `PhaseSpec` にコンパイルする (純関数。呼び手の `PhaseSpec` は変えない)。

    :param evidence: pass 1 の根拠 (`derivation` にそのまま載せる)
    :raises ValueError: 対象相・凍結相が相に無い、非対象相のラベルが分からない
    """
    names = [p.phase_name for p in phases]
    if decisions.target_phase not in names:
        raise ValueError(f"対象相 {decisions.target_phase!r} が相の一覧にありません: {names}")
    unknown = sorted(set(decisions.frozen_cell_phases) - set(names))
    if unknown:
        raise ValueError(f"格子を凍結する相 {unknown} が相の一覧にありません: {names}")
    geometry = histograms[0].geometry

    new_phases: list[PhaseSpec] = []
    for p in phases:
        if p.phase_name == decisions.target_phase:
            groups = p.uiso_equiv_groups or decisions.uiso_groups
            new_phases.append(replace(p, uiso_equiv_groups=tuple(groups), fix_polar_origin=True))
            continue
        labels = decisions.phase_labels.get(p.phase_name)
        if not labels:
            raise ValueError(
                f"非対象相 {p.phase_name!r} の原子ラベルが分からないので構造を凍結できません"
            )
        new_phases.append(
            replace(
                p,
                frozen_coord_labels=tuple(dict.fromkeys((*p.frozen_coord_labels, *labels))),
                frozen_uiso_labels=tuple(dict.fromkeys((*p.frozen_uiso_labels, *labels))),
            )
        )

    frozen = [n for n in names if n in set(decisions.frozen_cell_phases)]
    released = [n for n in names if n not in set(frozen)]
    stages = _head_stages(
        histograms, new_phases, background_coeffs=decisions.background_coeffs,
        calibrated=decisions.calibrated, cell_phases=released if frozen else None,
    )
    # 【段 R は常に置く (セルフレビュー H2)】: pass 1 で凍結した相の格子をもう一度試すだけでなく、pass 2 の
    #   段 1 が (開始点・収束判定の都合で) 棄却されたときの再試行にもなる。置かないと、段 1 が棄却された
    #   fit は格子を一度も精密化しないまま完走し、それは `reverted` 1 つにしか現れない。段 1 が受理済みなら
    #   同じ解放の回し直し (新しい自由度 0)。
    stages.append(
        RefinementStage(
            "TR lattice-retry", {"cell": True},
            (f"pass 1 で凍結した相 {frozen} の格子をもう一度 (他の相は {NO_NEW_DOF})" if frozen
             else f"段 1 が棄却されたときの格子の再試行 (受理済みなら {NO_NEW_DOF})"),
        )
    )
    target = decisions.target_phase
    stages.append(RefinementStage("T5 coords", {"coords": True}, f"対象相 {target} の自由座標"))
    stages.append(RefinementStage("T6 B", {"uiso": True}, f"対象相 {target} の Uiso"))
    target_spec = next(p for p in new_phases if p.phase_name == target)
    if _target_has_occupancy(target_spec):
        stages.append(
            RefinementStage(
                "T7 occupancy", {"occupancy": True, "occupancy_phases": [target]},
                "混合占有 (和=1 + Uiso 等価)・部分占有",
            )
        )
    if geometry is Geometry.BRAGG_BRENTANO:
        stages.append(
            RefinementStage(
                "T8 pref",
                {"preferred_orientation": 1, "preferred_orientation_phases": [target]},
                "選択配向 (March–Dollase)",
            )
        )
    stages.append(
        RefinementStage("T8R struct-retry", {"coords": True, "uiso": True}, NO_NEW_DOF)
    )
    stages.append(RefinementStage("T9 final", {}, NO_NEW_DOF))
    out = tuple(stages)
    validate_correlation_groups(out, histograms=histograms)
    check_phase_scoped_flags(out, new_phases)
    derivation: dict[str, object] = {
        "template_version": TEMPLATE_VERSION,
        "decisions": decisions.to_dict(),
        "offset": "shift" if geometry is Geometry.BRAGG_BRENTANO else "zero",
        "stages": [s.label for s in out],
    }
    if evidence:
        derivation["evidence"] = dict(evidence)
    return CompiledTemplate(
        stages=out, phases=tuple(new_phases), histograms=tuple(histograms),
        background_coeffs=decisions.background_coeffs, template_version=TEMPLATE_VERSION,
        derivation=derivation,
    )
