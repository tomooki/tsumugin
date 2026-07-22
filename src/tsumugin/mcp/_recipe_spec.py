"""JSON 段階解放レシピ spec ↔ `RefinementStage` 変換の共有ヘルパ (Issue #101/#114)。

`AnalysisInput.extra_stages` (`refine_loop/action.py`) と `make_gsas_runner(recipe=...)`
(`insitu/engine.py`) は ① に存在するのに、② (`rietveld_tools.auto_rietveld`/
`refine_with_revisions` と `insitu_tools.sequential_rietveld` の instrument spec) から JSON で
届かなかった (③ は callable を送れないため; CLAUDE.md §4.5 到達可能性)。

本モジュールは "stages" JSON (``[{"label": str, "flags": {...}, "note": str}, ...]``) を
`RefinementStage` タプルへ変換する**唯一の実装**とし、`rietveld_tools`/`insitu_tools` が共有する
(二重実装を作らない)。

**不正なキー/型は無視せず `ValueError` に正規化する** — 呼び出し側が ``{"error","error_type"}``
dict へ縮退する契約 (CLAUDE.md ② 不変条件)。黙って無視すると「呼べるが黙って間違う」
(指定した段階が静かに効かない) を再導入するため、構造的な誤りは大声で失敗させる。

``flags`` の**名前**も検証する。`engine._apply_stage` は ``if "cell" in flags`` の明示的
メンバシップ検査で消費するため、**未知のフラグ名は黙って無視される** (GSAS へ届かない)。
つまり ``"profile_lorentzain"`` のような 1 文字のタイポは、段階は走るのに何も解放されず
Rwp も動かない — ③ はこれを「この knob は効かない」と誤って学習する。これは
`repair_frames` の ``two_theta_limits`` 欠落と同じ「**呼べるが黙って間違う**」型の事故なので、
語彙を閉じた集合として持ち、未知名は許容一覧付きで大声で失敗させる (③ が自力で直せる)。
語彙が engine/recipe 側に足されたのに本表が古いままになる drift は
`tests/mcp/test_recipe_spec.py::test_known_flags_covers_engine_vocabulary` が検出する。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from ..autorietveld import RefinementStage

__all__ = ["stage_from_dict", "stage_to_dict", "stages_from_dicts"]

#: RefinementStage の JSON 表現が許す最上位キー。それ以外はタイポ/誤用として拒否する。
_ALLOWED_STAGE_KEYS = frozenset({"label", "flags", "note"})

#: `engine._apply_stage` / `recipe.build_recipe` が実際に解釈するフラグ名の閉じた語彙。
#: **ここに無い名前は engine が黙って無視する**ため、② の入口で拒否する (上の docstring 参照)。
#: 新しいフラグを engine/recipe に足したらここにも足すこと (drift はテストが検出)。
KNOWN_STAGE_FLAGS = frozenset(
    {
        "absorption",
        "background",
        "cell",
        "coords",
        "displacement",
        "hydrostatic_strain",
        "occupancy",
        "phase_fraction_sum",
        "preferred_orientation",
        "profile",
        "profile_asymmetry",
        "profile_lorentzian",
        "scale",
        "size_strain",
        "tof_profile",
        "uiso",
    }
)


def stage_from_dict(d: Mapping[str, object]) -> RefinementStage:
    """段階 1 つの JSON dict を `RefinementStage` へ変換する (③ からの spec 入力用)。

    :param d: ``{"label": str, "flags": dict (省略可, 既定 {}), "note": str (省略可, 既定 "")}``
    :raises ValueError: dict でない・不明なキーを含む・``label`` が非空文字列でない・
        ``flags``/``note`` の型が不正
    """
    if not isinstance(d, Mapping):
        raise ValueError(f"stage は dict である必要があります: {type(d).__name__}")
    unknown = set(d) - _ALLOWED_STAGE_KEYS
    if unknown:
        raise ValueError(
            f"stage に不明なキー {sorted(unknown)} があります "
            f"(許容キー: {sorted(_ALLOWED_STAGE_KEYS)})"
        )
    if "label" not in d:
        raise ValueError("stage は 'label' (str) が必須です")
    label = d["label"]
    if not isinstance(label, str) or not label:
        raise ValueError(f"stage.label は非空文字列である必要があります: {label!r}")
    flags = d.get("flags", {})
    if not isinstance(flags, Mapping):
        raise ValueError(
            f"stage.flags は dict である必要があります ({label!r}): {type(flags).__name__}"
        )
    # 【タイポ検出】: 未知フラグ名は engine が黙って無視する = 段階が静かに効かない。許容一覧を
    #   添えて拒否し、③ が自力で修正できるようにする ("呼べるが黙って間違う" の予防)。
    unknown_flags = set(flags) - KNOWN_STAGE_FLAGS
    if unknown_flags:
        raise ValueError(
            f"stage.flags に未知のフラグ {sorted(unknown_flags)} があります ({label!r})。"
            f"engine は未知フラグを黙って無視するため、この段階は何も解放しません "
            f"(許容フラグ: {sorted(KNOWN_STAGE_FLAGS)})"
        )
    note = d.get("note", "")
    if not isinstance(note, str):
        raise ValueError(f"stage.note は str である必要があります ({label!r}): {type(note).__name__}")
    return RefinementStage(label=label, flags=dict(flags), note=note)


def stages_from_dicts(
    stages: Sequence[Mapping[str, object]] | None,
) -> tuple[RefinementStage, ...]:
    """段階 spec の列を `RefinementStage` タプルへ変換する (None/空は空タプル)。

    :raises ValueError: いずれかの要素が ``stage_from_dict`` の検証に落ちるとき
    """
    if not stages:
        return ()
    return tuple(stage_from_dict(s) for s in stages)


def stage_to_dict(stage: RefinementStage) -> dict[str, object]:
    """`RefinementStage` を JSON dict へ写す (``stage_from_dict`` の逆写像, spec ハンドルの往復用)。"""
    return {"label": stage.label, "flags": dict(stage.flags), "note": stage.note}
