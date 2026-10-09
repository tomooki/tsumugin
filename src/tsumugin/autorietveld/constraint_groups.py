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

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..errors import InvalidPhaseSpecError

__all__ = [
    "AtomSite",
    "OriginConstraint",
    "merge_equiv_groups",
    "partially_released_groups",
    "polar_origin_constraints",
    "refuse_polar_origin_with_coord_jitter",
    "refuse_polar_origin_with_ranked_coords",
    "unknown_labels",
]

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


# ---------------------------------------------------------------------------
# 極性方向の原点固定 (fit-then-judge P1a タスク 3)
# ---------------------------------------------------------------------------

_AXES = ("x", "y", "z")

#: GSAS-II `GSASIIspc.SGpolar` の値域 → 原点が決まらない並進方向の列。
_POLAR_DIRECTIONS: dict[str, tuple[tuple[float, float, float], ...]] = {
    "": (),
    "x": ((1.0, 0.0, 0.0),),
    "y": ((0.0, 1.0, 0.0),),
    "z": ((0.0, 0.0, 1.0),),
    "x y": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "x z": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "y z": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "xyz": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "111": ((1.0, 1.0, 1.0),),
}


@dataclass(frozen=True)
class AtomSite:
    """原点固定の判断に要る原子 1 つ分の情報。

    :param label: 原子ラベル。
    :param z: 散乱能の代理 (X 線では原子番号)。最も散乱の強い原子で固定する。
    :param xid: 各軸の独立変数の番号 (GSAS `GetCSxinel` の第 1 要素。0 = 対称性で固定、
        同じ番号 = 結合した座標)。
    :param xcoef: 各軸の係数 (`GetCSxinel` の第 2 要素)。
    :param refined: 座標を精密化する原子か (凍結した原子は原点を既に決めている)。
    """

    label: str
    z: float
    xid: tuple[int, int, int]
    xcoef: tuple[float, float, float]
    refined: bool


#: 原点固定 1 本 = (原子ラベル, ((独立変数の軸名, 係数), ...))。Σ 係数·dA軸 = 0 を意味し、
#: 項が 1 つなら単なる hold。軸名は GSAS の独立変数 (結合した座標の最初の軸) の名前。
OriginConstraint = tuple[str, tuple[tuple[str, float], ...]]


def _translation_terms(
    site: AtomSite, direction: tuple[float, float, float]
) -> tuple[tuple[str, float], ...]:
    """方向 ``direction`` への並進を、原子の独立変数の一次結合として返す (係数 0 の項は除く)。

    座標 a は ``xcoef[a]·p[xid[a]]`` と書けるので、位置の方向成分 Σ_a d[a]·座標_a を一定に保つ
    拘束は、独立変数 k について係数 Σ_{a: xid[a]=k} d[a]·xcoef[a] の一次式になる。
    """
    coef: dict[int, float] = {}
    first_axis: dict[int, str] = {}
    for a, axis in enumerate(_AXES):
        k = site.xid[a]
        if k == 0:
            continue
        first_axis.setdefault(k, axis)
        coef[k] = coef.get(k, 0.0) + direction[a] * site.xcoef[a]
    return tuple(
        (first_axis[k], c) for k, c in sorted(coef.items()) if abs(c) > 1e-12
    )


def polar_origin_constraints(polax: str, sites: Sequence[AtomSite]) -> list[OriginConstraint]:
    """極性方向ごとに原点を固定する一次拘束を返す (要らなければ空)。

    方向ごとに: その方向へ動ける原子が**全員**精密化される場合だけ、最も散乱の強い原子
    (同値なら先頭) でその方向の座標の一次結合を 1 本固定する。1 原子でも凍結されていれば
    原点は既に決まっているので何もしない (足すと実在の自由度を消す)。

    :param polax: GSAS-II の ``SGData['SGPolax']`` (``''``/``'x'``/…/``'xyz'``/``'111'``)。
    :param sites: 相の原子。
    :raises ValueError: 未知の ``polax``、または複数の極性方向の固定が同じ独立変数に重なる
        (固定どうしが特異になる) とき。
    """
    key = polax.strip()
    if key not in _POLAR_DIRECTIONS:
        raise ValueError(f"未知の極性軸の値です: {polax!r} (許容: {sorted(_POLAR_DIRECTIONS)})")
    used: set[tuple[str, str]] = set()  # (原子, 独立変数の軸名) — 固定済み
    out: list[OriginConstraint] = []
    for direction in _POLAR_DIRECTIONS[key]:
        movable = [(s, _translation_terms(s, direction)) for s in sites]
        movable = [(s, terms) for s, terms in movable if terms]
        if not movable or any(not s.refined for s, _ in movable):
            continue
        candidates = [
            (s, terms) for s, terms in movable if not any((s.label, ax) in used for ax, _ in terms)
        ]
        if not candidates:
            raise ValueError(
                f"極性方向 {direction} の原点固定が、既に固定した独立変数と重なります "
                "(結合した座標しか持たない原子だけが動ける)"
            )
        # 最も散乱の強い原子。同値なら入力順で先頭 (決定論)。
        best_i = max(range(len(candidates)), key=lambda i: (candidates[i][0].z, -i))
        site, terms = candidates[best_i]
        used.update((site.label, ax) for ax, _ in terms)
        out.append((site.label, terms))
    return out


# ---------------------------------------------------------------------------
# 原点固定と組み合わせられない入力の検査 (GSAS 非依存の純粋な入力検査。engine と confirm が使う)
# ---------------------------------------------------------------------------


def refuse_polar_origin_with_ranked_coords(phases: Sequence, stages: Sequence) -> None:
    """`fix_polar_origin` と元素ランクの座標段 (`coords: <int>`) の組み合わせを拒否する (P1a)。

    原点固定は精密化の前に 1 回だけ張る静的な拘束で、「その方向へ動ける原子を**全員**精密化
    する」ときに要る。元素ランクの段では固定原子以外が凍結されて原点は既に決まっており、
    固定が実在の自由度を消す (その段が座標について no-op になり、重原子だけのレシピでは固定原子の
    座標が一度も精密化されない)。段ごとに拘束を入れ替える仕組みは P1-1B の範囲なので、
    それまでは組み合わせを大声で止める。

    :raises InvalidPhaseSpecError: 組み合わせたとき
    """
    if not any(getattr(p, "fix_polar_origin", False) for p in phases):
        return
    ranked = [
        st.label
        for st in stages
        if isinstance(st.flags.get("coords"), int) and not isinstance(st.flags.get("coords"), bool)
    ]
    if ranked:
        raise InvalidPhaseSpecError(
            f"fix_polar_origin は元素ランクで座標を一部だけ解放する段 {ranked} と組み合わせられません"
            " (その段では原点は既に決まっており、固定が実在の自由度を消す)。coords: true の段を"
            "使うか、fix_polar_origin を外してください"
        )


def refuse_polar_origin_with_coord_jitter(
    phases: Sequence, jitter: "Mapping[str, float | None] | None"
) -> None:
    """`fix_polar_origin` の相への座標の初期摂動 (マルチスタートの構造軸) を拒否する (P1a)。

    摂動 (engine `_apply_coord_jitter`) は原点固定 (engine `_apply_polar_origin`) より**先に**掛かるので、hold した
    原子の極性方向の座標は摂動された値のまま固定され、構造全体が極性方向へずれた解になる。開始点
    ごとに原点がずれるので、極性方向の座標が「初期値依存」と誤判定される (セルフレビュー 2 巡目)。
    hold した座標を摂動から外す/極性方向の並進を除いて比べる対応は設計 §4.5 で P1-1B に予定
    しているので、それまでは組み合わせを大声で止める。

    :raises InvalidPhaseSpecError: 原点固定の相に正の摂動幅が与えられたとき
    """
    if not jitter:
        return
    bad = [
        p.phase_name
        for p in phases
        if getattr(p, "fix_polar_origin", False) and float(jitter.get(p.phase_name) or 0.0) > 0.0
    ]
    if bad:
        raise InvalidPhaseSpecError(
            f"fix_polar_origin の相 {bad} には座標の初期摂動を掛けられません (摂動が原点固定より先に"
            "掛かり、構造全体が極性方向へずれた解になる)。マルチスタートでは原点固定を外すか、"
            "座標の摂動幅を 0 にしてください"
        )
