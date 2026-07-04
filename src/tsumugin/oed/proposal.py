"""測定フィードバック提案 (OED v1) — 僅差競合の判別測定提案 (M5 / REQ-035/037/038/304/EDGE-010)。

D9。木探索/裁定で残った **僅差競合** (close_competitor) を判別するための追加測定を、情報利得順に
提案する **非破壊** レイヤ。仮説を accepted/rejected 化せず、データも改変しない。ledger 非 None の
ときのみ ``oed_proposal`` を追記記録する (提案のみ・P2/NFR-101)。

【v1 簡易近似 (REQ-304)】: PyBOED (``pyboed``) 獲得関数を用いた高度な情報利得評価は
  ``oed/pyboed.py`` の遅延 import 境界 (``acquire``) に隔離し、本モジュールの提案生成は外部依存
  なし・乱数不使用で決定論的に動作する (僅差競合数・evidence 差から利得スカラを導出する / REQ-105)。

【決定論 (REQ-402/NFR-102)】: 対象仮説 ID は昇順。提案は (利得降順, kind 昇順) の安定順で固定する。
  同一入力からの 2 回生成でビット同一。

本モジュールはコア (numpy 不要・標準ライブラリのみ) で import でき、``import tsumugin`` に
pyboed/dynesty を持ち込まない (REQ-403)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

from .._json import finite_or_none
from ..evidence.ranking import RankedHypothesis
from ..store.ledger import Ledger

__all__ = [
    "MeasurementKind",
    "OEDProposal",
    "propose_measurements",
    "proposals_to_json",
]

# 【提案測定種別 (REQ-035)】: 判別に効きうる 4 種の追加測定。🔵
MeasurementKind = Literal[
    "high_statistics_remeasure",  # 高統計再測定 🔵
    "additional_temperature_point",  # 追加温度点 🔵
    "neutron_for_joint",  # joint 用中性子測定 🔵
    "composition_analysis",  # 組成分析 🔵
]


@dataclass(frozen=True)
class OEDProposal:
    """僅差競合を判別する 1 測定提案 (情報利得付き)。🔵 REQ-035/304

    【情報利得順 (REQ-035)】: ``propose_measurements`` が ``estimated_information_gain`` 降順で並べる。
    【決定論 (REQ-038/402)】: ``target_hypothesis_ids`` は昇順で保持する。
    """

    kind: MeasurementKind  # 【提案測定種別】 🔵 REQ-035
    target_hypothesis_ids: tuple[str, ...]  # 【判別対象の僅差競合仮説群 (昇順)】 🔵 REQ-038/402
    rationale: str  # 【なぜこの測定が判別に効くか (ledger 記録用)】 🔵 REQ-035
    estimated_information_gain: float  # 【推定情報利得スカラ (v1 簡易近似)】 🔵 REQ-304
    parameters: Mapping[str, object] = field(default_factory=dict)  # 【提案パラメータ (温度点 等)】 🟡


# 【測定種別ごとの基準情報利得 (v1 簡易近似)】: 判別への寄与を種別で重み付けした決定論係数。
#   高統計再測定 > 中性子 joint > 組成分析 > 追加温度点 の順に基準利得を割り当てる (経験則)。
#   実際の利得は僅差競合数・evidence 差でスケールする (乱数不使用)。🔵 REQ-304
_KIND_BASE_GAIN: dict[MeasurementKind, float] = {
    "high_statistics_remeasure": 1.0,
    "neutron_for_joint": 0.9,
    "composition_analysis": 0.7,
    "additional_temperature_point": 0.5,
}

# 【提案 rationale テンプレート (ledger 記録用・日本語)】: 種別ごとの判別根拠。🔵 REQ-035
_KIND_RATIONALE: dict[MeasurementKind, str] = {
    "high_statistics_remeasure": (
        "僅差競合の evidence 差が小さいため、高統計再測定で S/N を上げ判別力を高める。"
    ),
    "neutron_for_joint": (
        "X 線のみでは判別困難な散乱コントラストを、中性子測定を加えた joint で分離する。"
    ),
    "composition_analysis": (
        "組成分析で相の化学量論を独立に拘束し、候補仮説を判別する。"
    ),
    "additional_temperature_point": (
        "追加温度点で相安定領域/転移挙動の差を捉え、候補仮説を判別する。"
    ),
}


def propose_measurements(
    ranked: Sequence[RankedHypothesis],
    *,
    close_threshold: float = 10.0,
    ledger: Ledger | None = None,
) -> tuple[OEDProposal, ...]:
    """僅差競合時の判別測定提案を情報利得順に生成する (非破壊・提案のみ)。🔵 REQ-035/037/038/EDGE-010

    【発動条件 (REQ-038/EDGE-010)】: rank の ``close_competitor`` (ΔBIC/ΔlogZ < close_threshold) が
      2 件以上存在するときのみ提案する (単独では判別対象が無い)。僅差競合が無ければ空 tuple を返す
      (状態変更なし, EDGE-010)。
    【提案 (REQ-035)】: 高統計再測定 / 追加温度点 / joint 用中性子測定 / 組成分析を情報利得順に並べる。
    【非破壊 (REQ-037)】: 仮説の accepted/rejected 化・データ改変を一切伴わない。ledger 非 None の
      ときのみ ``ledger.append("oed_proposal", {...})`` で追記記録する (P2/NFR-101)。
    【決定論 (REQ-402)】: 対象仮説 ID 昇順・提案は (利得降順, kind 昇順) の安定順で固定する (NFR-102)。

    Args:
        ranked: 一次 rank / 裁定後の RankedHypothesis 群 (close_competitor フラグ済み)。
        close_threshold: 僅差競合の判定閾値 (rank と共有・情報利得スケールに用いる)。
        ledger: 非 None のとき提案を追記記録する (追記のみ・削除しない)。

    Returns:
        (利得降順, kind 昇順) に並べた OEDProposal の tuple。僅差競合が無ければ空 tuple。
    """
    # 【僅差競合抽出 (REQ-038)】: close_competitor=True の仮説 ID を昇順で固定する 🔵
    close_ids = tuple(
        sorted(r.hypothesis.id for r in ranked if r.close_competitor)
    )
    # 【EDGE-010】: 判別対象 (競合) が 2 件未満なら提案しない (空 tuple・状態変更なし) 🔵
    if len(close_ids) < 2:
        return ()

    # 【evidence 差スケール (v1 簡易近似 / REQ-304)】: 僅差競合群の evidence 幅を close_threshold で
    #   正規化した「近さ」で利得をスケールする。差が小さい (= より僅差) ほど判別価値が高い。乱数不使用 🔵
    close_values = sorted(
        r.evidence.value for r in ranked if r.close_competitor
    )
    spread = close_values[-1] - close_values[0]
    # closeness ∈ (0, 1]: spread=0 (完全同点) で 1.0、spread→close_threshold で下限へ漸近する 🔵
    denom = close_threshold if close_threshold > 0.0 else 1.0
    closeness = 1.0 / (1.0 + spread / denom)
    # 競合数が多いほど 1 測定の判別寄与を薄めない範囲でわずかに底上げする (決定論係数) 🔵
    n_factor = float(len(close_ids))

    proposals: list[OEDProposal] = []
    for kind, base_gain in _KIND_BASE_GAIN.items():
        gain = base_gain * closeness * n_factor
        proposals.append(
            OEDProposal(
                kind=kind,
                target_hypothesis_ids=close_ids,
                rationale=_KIND_RATIONALE[kind],
                estimated_information_gain=gain,
            )
        )

    # 【決定論的並べ替え (REQ-402)】: (利得降順, kind 昇順) の安定順で固定する 🔵
    proposals.sort(key=lambda p: (-p.estimated_information_gain, p.kind))
    ordered = tuple(proposals)

    # 【追記記録のみ (REQ-037/P2)】: ledger 非 None のとき提案を記録する (削除/上書きしない) 🔵
    if ledger is not None:
        ledger.append(
            "oed_proposal",
            {
                "target_hypothesis_ids": list(close_ids),
                "n_proposals": len(ordered),
                "close_threshold": close_threshold,
                "proposals": proposals_to_json(ordered),
            },
        )

    return ordered


def proposals_to_json(proposals: Sequence[OEDProposal]) -> list[dict]:
    """OEDProposal 群を JSON ネイティブ list[dict] へ (情報利得順・決定論)。🔵 REQ-035/402

    非有限な情報利得は ``finite_or_none`` で純化し ``json.dumps(allow_nan=False)`` を安全にする。
    入力順 (propose_measurements の利得降順) をそのまま保つ。
    """
    return [
        {
            "kind": p.kind,
            "target_hypothesis_ids": list(p.target_hypothesis_ids),
            "rationale": p.rationale,
            # 【純化 (EDGE)】: 非有限利得を None 化し allow_nan=False を安全に通す 🔵
            "estimated_information_gain": finite_or_none(p.estimated_information_gain),
            "parameters": dict(p.parameters),
        }
        for p in proposals
    ]
