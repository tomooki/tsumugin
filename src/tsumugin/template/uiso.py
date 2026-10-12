"""Uiso のまとめ方の規則 (proposal §4.3): 同じ元素で同じ配位数の原子は 1 つの Uiso を共有する。

段階的に緩める検定は P2 で効果を測ってから (proposal §4.3)。ここでは規則だけを決める。配位数は
「最近接距離 × ``tolerance`` 以内の隣接原子の数」(有効配位数の素朴な定義。原子半径の表を使わない —
経験的な原子半径の和は陽イオン同士まで数えてしまう: 岩塩の Na で 18)。

混合占有・部分占有の原子 (順序だっていないサイト) はまとめない — 同じ位置の原子の Uiso 等価は engine が
混合占有の組として張る。pymatgen が無い・構造を読めないときは ``unevaluated`` を返し、まとめない
(= 原子ごと)。**「規則を適用した結果まとめる組が無かった」と「規則を適用できなかった」を区別する**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

__all__ = ["UisoGrouping", "uiso_groups_from_cif"]


@dataclass(frozen=True)
class UisoGrouping:
    """規則の結果。``groups`` は 2 原子以上の組だけ (ラベルは入力順)。"""

    groups: tuple[tuple[str, ...], ...]
    status: str  # "pass" | "unevaluated"
    coordination: Mapping[str, int] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "groups": [list(g) for g in self.groups],
            "status": self.status,
            "coordination": dict(self.coordination),
            "reason": self.reason,
        }


def uiso_groups_from_cif(
    cif_path: str,
    *,
    labels: "Sequence[str] | None" = None,
    tolerance: float = 1.2,
    search_radius: float = 4.0,
) -> UisoGrouping:
    """CIF から (元素, 配位数) で Uiso の組を作る。

    :param labels: この原子だけを対象にする (例: 精密化する原子。None なら全原子)
    """
    try:
        from pymatgen.io.cif import CifParser
    except ImportError as exc:  # pragma: no cover — 環境依存
        return UisoGrouping((), "unevaluated", reason=f"pymatgen を読み込めない: {exc}")
    try:
        structure = CifParser(cif_path).parse_structures(primitive=False)[0]
    except Exception as exc:  # noqa: BLE001 — 読めない構造は unevaluated
        return UisoGrouping((), "unevaluated", reason=f"構造を読めない: {exc!r}"[:300])

    wanted = set(labels) if labels is not None else None
    first_site: dict[str, int] = {}
    for i, site in enumerate(structure):
        label = getattr(site, "label", None) or ""
        if label and label not in first_site:
            first_site[label] = i
    if not first_site:
        return UisoGrouping((), "unevaluated", reason="ラベル付きのサイトが無い")

    coordination: dict[str, int] = {}
    keys: dict[str, tuple[str, int]] = {}
    for label, i in first_site.items():
        if wanted is not None and label not in wanted:
            continue
        site = structure[i]
        if not site.is_ordered:
            continue  # 混合占有のサイト — engine が組として扱う
        neighbors = structure.get_neighbors(site, search_radius)
        if not neighbors:
            continue
        d_min = min(nb.nn_distance for nb in neighbors)
        cn = sum(1 for nb in neighbors if nb.nn_distance <= d_min * tolerance)
        coordination[label] = cn
        keys[label] = (site.specie.symbol, cn)

    by_key: dict[tuple[str, int], list[str]] = {}
    for label in first_site:
        if label in keys:
            by_key.setdefault(keys[label], []).append(label)
    groups = tuple(tuple(v) for v in by_key.values() if len(v) >= 2)
    return UisoGrouping(groups, "pass", coordination=coordination)
