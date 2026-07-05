"""相同定結果の組成グルーピング (仕様 §5 / Dara フロー Phase E)。

同一組成 (reduced formula) の候補相は XRD では区別が難しい多形・固溶体であることが多い。
ランキング済みマッチを組成でまとめ、各グループの最良スコア相を代表として提示することで冗長性を
減らし、曖昧性 (同組成の複数構造候補) を人間に分かりやすく報告する (Dara の compositional grouping)。
numpy 非依存・決定論的な純関数。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .model import PhaseMatch

__all__ = ["PhaseMatchGroup", "group_by_composition"]


@dataclass(frozen=True)
class PhaseMatchGroup:
    """同一組成のマッチ群。🔵 Phase E"""

    formula: str  # グループの組成 (reduced formula) 🔵
    representative: PhaseMatch  # グループ内最良スコアのマッチ 🔵
    members: tuple[PhaseMatch, ...]  # 全メンバー (score 降順・同点 phase_id 昇順) 🔵


def group_by_composition(matches: Sequence[PhaseMatch]) -> tuple[PhaseMatchGroup, ...]:
    """マッチを組成でグルーピングし代表スコア降順で返す (Phase E)。🔵

    Args:
        matches: ランキング済み ``PhaseMatch`` 群 (``identify_phases`` の出力)。

    Returns:
        ``PhaseMatchGroup`` の並び (代表スコア降順・同点 formula 昇順)。空入力は空タプル。
    """
    by_formula: dict[str, list[PhaseMatch]] = {}
    for m in matches:
        by_formula.setdefault(m.reference.formula, []).append(m)

    groups: list[PhaseMatchGroup] = []
    for formula, members in by_formula.items():
        ordered = tuple(
            sorted(members, key=lambda m: (-m.score, m.reference.phase_id))
        )
        groups.append(
            PhaseMatchGroup(formula=formula, representative=ordered[0], members=ordered)
        )
    # 代表スコア降順・同点 formula 昇順で決定論的に整列 🔵
    groups.sort(key=lambda g: (-g.representative.score, g.formula))
    return tuple(groups)
