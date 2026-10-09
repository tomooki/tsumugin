"""等値拘束の組の合併と検査 — 純関数・GSAS 非依存 (fit-then-judge P1a)。

GSAS-II の等値拘束 (`add_EquivConstr`) は、同じ変数を 2 つの組に入れると一般拘束へ変換し直す
(GSASIImapvars)。混合占有の Uiso 等価 (`PhaseSpec.mixed_occupancy_groups`) と
`PhaseSpec.uiso_equiv_groups` が同じ原子を含むと二重に張ることになるので、**推移的に合併して
1 回だけ張る**。

等値の組は**全員が解放されているか、全員が凍結されているか**のどちらかでなければならない。
一部だけにフラグが立つと、等値拘束が「動く変数」と「動かない変数」を結ぶことになり、GSAS が
どちらに寄せるかは拘束の書き方に依存する (呼べるが黙って別の手順に化ける)。
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence

__all__ = ["merge_equiv_groups", "partially_released_groups", "unknown_labels"]

Group = tuple[str, ...]


def merge_equiv_groups(*group_lists: Iterable[Sequence[str]]) -> tuple[Group, ...]:
    """組の列を**推移的に合併**し、2 原子以上の組だけを返す。

    順序は決定論 (NFR-102): 組は「最初に現れたラベル」の出現順、組内のラベルも出現順。

    :param group_lists: 合併する組の列 (例: 混合占有の組, Uiso の等値の組)。
    """
    order: dict[str, int] = {}
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        # 代表は出現の早い方 (合併の順序を出現順に固定する)
        if order[rb] < order[ra]:
            ra, rb = rb, ra
        parent[rb] = ra

    for groups in group_lists:
        for group in groups:
            labels = [str(lab) for lab in group]
            for lab in labels:
                if lab not in order:
                    order[lab] = len(order)
                    parent[lab] = lab
            for a, b in zip(labels, labels[1:]):
                union(a, b)

    members: dict[str, list[str]] = {}
    for lab in sorted(order, key=order.__getitem__):
        members.setdefault(find(lab), []).append(lab)
    merged = [tuple(labs) for labs in members.values() if len(labs) >= 2]
    return tuple(sorted(merged, key=lambda g: order[g[0]]))


def unknown_labels(groups: Iterable[Sequence[str]], labels: Collection[str]) -> list[str]:
    """組に現れるが ``labels`` (相の原子ラベル) に無いものを出現順に返す (重複なし)。"""
    known = set(labels)
    out: list[str] = []
    for group in groups:
        for lab in group:
            if lab not in known and lab not in out:
                out.append(lab)
    return out


def partially_released_groups(
    groups: Iterable[Sequence[str]], released: Collection[str]
) -> list[Group]:
    """一部の原子だけが ``released`` に入っている組を返す (全員/誰も、なら問題なし)。"""
    rel = set(released)
    out: list[Group] = []
    for group in groups:
        flags = {lab in rel for lab in group}
        if len(flags) > 1:
            out.append(tuple(group))
    return out
