"""M8-③: MEM 密度 → 構造改訂提案 (ReviseStructure) の橋渡し (Phase B)。

実 Dysnomia MEM (``tsumugin.mem.gsas.run_dysnomia_mem``) が返す ``MEMDensityResult`` の
**未モデル密度ピーク** (最近接原子から離れた密度) を、``ReviseStructure`` ModelAction の
``ActionProposal`` へ変換する。「どこに原子を足す/占有を是正するか」の空間的手がかりを
③ (Claude/人間) の結晶学判断へ渡す。

【提案のみ (§1 Dara 教訓)】採否と元素/占有の確定は ③。本モジュールは候補と**具体 evidence**
  (ピーク分率座標・大きさ・最近接原子・probe・編集テンプレ) を出すだけで、構造は編集しない。
  規則ポリシー (①) はこれらを実行しない (すべて ``safe=False`` = ModelAction)。

【密度の読み (evidence に反映)】
  - 正の未モデル密度 (原子から ``unmodeled_distance`` 以上) → **欠損原子候補** (add)。
  - 負の核密度 (原子近傍) → **水素 (b<0) or 占有率過大** の是正候補 (nuclear のみ; 電子密度の
    負ピークは重原子近傍の series-termination なので候補にしない)。

【決定論】優先度 (|magnitude|) 降順 → frac 昇順で安定ソートし ``max_proposals`` で打ち切る。
【GSAS 非依存】``MEMDensityResult`` は純データ。本モジュールは numpy すら不要 (stdlib)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .action import ReviseStructure
from .diagnostics import ActionProposal

if TYPE_CHECKING:  # 型注釈のみ (実行時 import 不要・循環回避)
    from ..mem.gsas import MEMDensityResult


def _element_note(density_kind: str, magnitude: float) -> str:
    """probe と密度符号から元素判定の指針を返す (元素は確定しない・③ の判断材料)。"""
    if density_kind == "electron":
        return "電子密度: 大きさは電子数 (Z) に比例。③ が Z で元素を判定。"
    if magnitude < 0:
        return "核密度が負: 水素 (b=-3.74 fm) の徴候。"
    return "核密度: 大きさは散乱長 b に比例。③ が b で元素を判定。"


def propose_structure_revisions_from_mem(
    mem: "MEMDensityResult",
    *,
    phase: str,
    unmodeled_distance: float = 0.8,
    negative_tol: float = 1e-6,
    max_proposals: int = 8,
) -> tuple[ActionProposal, ...]:
    """MEM 未モデル密度ピークから ReviseStructure 候補を決定論的に提案する。🔵 M8-③ Phase B

    :param mem: 実 MEM 結果 (``mem.gsas.run_dysnomia_mem`` 由来)
    :param phase: 対象相名
    :param unmodeled_distance: 「未モデル」とみなす最近接原子距離 (Å) 下限
    :param negative_tol: 負ピークとみなす下限 (|mag|)
    :param max_proposals: 返す提案の上限
    :returns: ``ActionProposal[]`` (すべて ``safe=False`` = ModelAction・提案のみ)
    """
    proposals: list[ActionProposal] = []
    kind = mem.density_kind

    for pk in mem.peaks:
        if pk.magnitude > 0 and pk.distance >= unmodeled_distance:
            # 正の未モデル密度 → 欠損原子候補 (add)。
            proposals.append(
                ActionProposal(
                    action=ReviseStructure(phase, {}),  # 具体編集は evidence.suggested_edit に
                    rationale=(
                        f"MEM 未モデル正密度 {pk.magnitude:+.2f} @ frac="
                        f"{tuple(round(x, 3) for x in pk.frac)} "
                        f"(最近接 {pk.nearest_atom} d={pk.distance:.2f}Å) → 欠損原子候補。"
                        f" {_element_note(kind, pk.magnitude)}"
                    ),
                    priority=abs(float(pk.magnitude)),
                    evidence={
                        "signal": "mem_unmodeled_positive",
                        "frac": pk.frac,
                        "magnitude": float(pk.magnitude),
                        "distance": float(pk.distance),
                        "nearest_atom": pk.nearest_atom,
                        "density_kind": kind,
                        "element_note": _element_note(kind, pk.magnitude),
                        "suggested_op": "add",
                        "suggested_edit": {
                            "op": "add", "element": None, "frac": pk.frac,
                            "occ": None, "uiso": None,
                        },
                    },
                    safe=False,
                )
            )
        elif (
            kind == "nuclear"
            and pk.magnitude < -abs(negative_tol)
            and pk.distance < unmodeled_distance
        ):
            # 負の核密度が原子近傍 → 水素 (b<0) or 占有率過大の是正候補。
            proposals.append(
                ActionProposal(
                    action=ReviseStructure(phase, {}),
                    rationale=(
                        f"MEM 負核密度 {pk.magnitude:+.2f} @ 最近接 {pk.nearest_atom} "
                        f"d={pk.distance:.2f}Å → 水素 (b<0) の未モデル or {pk.nearest_atom} "
                        f"占有率過大の是正候補。"
                    ),
                    priority=abs(float(pk.magnitude)),
                    evidence={
                        "signal": "mem_negative_nuclear",
                        "frac": pk.frac,
                        "magnitude": float(pk.magnitude),
                        "distance": float(pk.distance),
                        "nearest_atom": pk.nearest_atom,
                        "density_kind": kind,
                        "suggested_op": "add_H_or_reduce_occupancy",
                    },
                    safe=False,
                )
            )

    # 決定論・安定順: |magnitude| 降順 → frac 昇順。
    proposals.sort(key=lambda pr: (-pr.priority, tuple(pr.evidence["frac"])))
    return tuple(proposals[:max_proposals])
