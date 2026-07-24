"""相・格子データモデル (仕様 §4 PhaseInstance / LatticeParams)。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Literal, Mapping

# 【σ 由来の許容値】: "covariance" (共分散由来の真の esd) / "proxy" (簡易代理値, 将来用) /
#   "" (未提供, 既定)。joint/model.py の PerHistogramMetrics.sigma_source と同じ Literal 慣習。
#   NFR-107 (σ 由来明示) 🔵
SigmaSource = Literal["covariance", "proxy", ""]


@dataclass(frozen=True)
class LatticeParams:
    """格子定数 (±σ)。角はすべて度。

    ``sigma``/``sigma_source`` は「当該 refine() 呼び出しで推定した不確かさのみ」を表す
    (統一セマンティクス)。今回解放しなかった格子属性・相の σ は空 (持ち越しなし)。
    """

    a: float
    b: float
    c: float
    alpha: float = 90.0
    beta: float = 90.0
    gamma: float = 90.0
    sigma: Mapping[str, float] = field(default_factory=dict)
    # 【σ 由来明示】: SigmaSource 参照 (NFR-107) 🔵
    sigma_source: SigmaSource = ""

    def volume(self) -> float:
        """一般三斜格子の単位胞体積 (Å³)。"""
        ca = math.cos(math.radians(self.alpha))
        cb = math.cos(math.radians(self.beta))
        cg = math.cos(math.radians(self.gamma))
        factor = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
        # 数値誤差で僅かに負へ落ちる縮退ケースを 0 にクランプ
        factor = max(factor, 0.0)
        return self.a * self.b * self.c * math.sqrt(factor)


@dataclass(frozen=True)
class PhaseLifecycle:
    """相ライフサイクル値オブジェクト (REQ-004 / interfaces.py L31-37)。

    【機能概要】: 相がいつ出現(birth)/消滅(death)したかと存在確信度を保持する不変値オブジェクト。
    【実装方針】: 全フィールド既定値付きの frozen dataclass とし、器のみを提供 (算出は後続 LifecycleTracker スコープ)。
    【テスト対応】: N-01/N-02/E-01/B-01/B-05 を通す。
    🔵 信頼性レベル: 要件定義 2.1 / interfaces.py L31-37 に依拠。
    """

    birth_frame: int | None = None  # 【出現フレーム】: 相が現れた frame index。未確定/未追跡は None
    death_frame: int | None = None  # 【消滅フレーム】: 相が消えた frame index。未消滅/未追跡は None
    confidence: float = 1.0  # 【存在確信度】: [0,1]。本タスクは既定 1.0 保持のみ (範囲検証は非スコープ)


@dataclass(frozen=True)
class PhaseRef:
    """相 ID + 組成/元素系ヒント (ChemPlausibility.score の第 1 引数)。🟡 REQ-020

    【橋渡し】: 既存 ``PhaseInstance.phase_ref: str`` は不変とし、本型は疎結合の別値オブジェクト。
    PhaseInstance へのフィールド追加は行わない (D6)。``id`` を ``PhaseInstance.phase_ref`` と
    一致させることで id 整合する。
    """

    id: str  # 【相 ID】: PhaseInstance.phase_ref と一致させる 🔵
    formula: str | None = None  # 【組成式】: 例 "LiFePO4"。不明は None 🟡
    element_system: tuple[str, ...] = ()  # 【元素系ヒント】: 例 ("Li","Fe","P","O") 🟡

    @staticmethod
    def from_phase_ref(
        phase_ref: str, *, formula: str | None = None, element_system: tuple[str, ...] = ()
    ) -> "PhaseRef":
        """既存 str ``phase_ref`` から PhaseRef を生成する橋渡し。🟡 REQ-020"""
        return PhaseRef(id=phase_ref, formula=formula, element_system=element_system)


@dataclass(frozen=True)
class PhaseInstance:
    """1 つの相インスタンス。更新は with_updates による非破壊生成のみ (P2)。"""

    phase_ref: str
    lattice: LatticeParams
    scale: float = 1.0  # 相スケール因子
    wt_frac: float | None = None
    occupancies: Mapping[str, float] = field(default_factory=dict)
    # 【追加フィールド】: 相ライフサイクル。末尾・既定 None で後方互換を保証 (REQ-404 非破壊追加) 🔵
    lifecycle: PhaseLifecycle | None = None
    # 【追加フィールド (Issue #130)】: 実結晶構造 CIF へのパス。末尾・既定 None で非破壊追加。
    #   ``GSASIIBackend`` は structure_ref があれば実 CIF を add_phase し格子だけ上書きする
    #   (無ければ従来のプレースホルダ CIF)。``SimulatedBackend`` は本フィールドを無視する
    #   (hkl_table を phase_ref で引くため影響なし = 後方互換)。🔵
    structure_ref: str | None = None

    def with_updates(self, **changes) -> "PhaseInstance":
        """変更を適用した新インスタンスを返す。自身は不変。"""
        return replace(self, **changes)


def strip_lattice_sigma(phases: tuple[PhaseInstance, ...]) -> tuple[PhaseInstance, ...]:
    """格子 σ (``lattice.sigma``/``sigma_source``) が非空の相のみ {}/"" へ縮退した新タプルを返す。

    【共有ヘルパー (レビュー対応, Issue #66 ラウンド2)】: 「当該 refine() 呼び出しで推定した
    不確かさのみを σ として表す」統一セマンティクスを、精密化結果を素通りさせる 2 箇所で
    一貫させるための純関数。重複実装を避けるため model 層に 1 実装のみ置き、呼び出し側が
    import して使う:

    - ``backends.gsasii.GSASIIBackend.refine`` の GSAS 例外分岐: 最小二乗が失敗し
      入力 ``model.phases`` をそのまま返す際、入力に残る古い σ が chi2=inf の仮説に
      付いたまま見えてしまうのを防ぐ。
    - ``joint.engine._build_aggregate``: ブロック座標降下の各 ``backend.refine`` は
      「そのヒスト 1 本の統計」で共有格子の σ を都度上書きするため、最終 phases の σ は
      最後に処理したヒスト依存の局所量になる。joint としての結合 σ は現状算出していない
      (将来課題) ため、単一ヒスト σ を joint σ と誤表示しないよう最終集約時に剥離する。

    全相が既に sigma/sigma_source 空なら同一タプルをそのまま返す (無駄な複製回避)。

    :param phases: 対象の相集合 (精密化結果または途中経過)
    :returns: sigma/sigma_source を全相 {}/"" に揃えた新タプル (非破壊, P2)
    """
    if not any(p.lattice.sigma or p.lattice.sigma_source for p in phases):
        return phases
    return tuple(
        p.with_updates(lattice=replace(p.lattice, sigma={}, sigma_source=""))
        if (p.lattice.sigma or p.lattice.sigma_source)
        else p
        for p in phases
    )
