"""透過吸収補正 v1 のモデル層 (TASK-0026 / D8 / FR-317)。

【機能概要】: 平板透過配置の吸収因子 A(θ; μt) = exp(-μt / cosθ) を計算する純関数と、
              精密化に用いる吸収設定 ``AbsorptionConfig`` (frozen 値オブジェクト) を提供する。
【実装方針】: コア依存は numpy のみ (REQ-403)。組成→μt の算出 (xraylib) には実依存せず、
              ``from_cell_config`` は ``CellConfig.mu_t_calc`` を読むだけに留める。
【テスト対応】: tests/test_absorption.py の T-N01/N02/N05/N06/N07/E03/B01/B07 を通す。
🔵 信頼性レベル: 要件定義 2.3 / interfaces.py L97-114 / architecture.md D8 に依拠。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # 【型のみ参照】: 実行時は CellConfig を import せず結合を最小化する 🔵
    from ..model import CellConfig


def transmission_factor(two_theta_deg: np.ndarray, mu_t: float) -> np.ndarray:
    """平板透過の吸収因子 A(θ; μt) = exp(-μt / cosθ) を返す。

    【機能概要】: 各 2θ 点の透過吸収因子を計算する。θ = radians(2θ / 2) の半角変換を伴う。
    【実装方針】: numpy ベクトル演算による純関数。μt=0 なら exp(0)=1 で全域 1.0 (EDGE-006 境界)。
    【テスト対応】: T-N01 (理論式一致) / T-N02 (既知角) / T-B01 (μt=0→全域 1.0)。
    🔵 信頼性レベル: 要件定義 2.3 / interfaces.py L112-114 に依拠。

    :param two_theta_deg: 2θ (度) の配列
    :param mu_t: 実効 μt (吸収の厚み積、≥0 を想定)
    :returns: 各点の吸収因子 (入力と同一形状の np.ndarray)
    """
    # 【半角変換】: 回折角 2θ から Bragg 角 θ = 2θ/2 を得て radian 化する 🔵
    theta = np.radians(np.asarray(two_theta_deg, dtype=float) / 2.0)
    # 【吸収因子】: A = exp(-μt/cosθ)。μt=0 は exp(0)=1 で無補正境界に一致する 🔵
    return np.exp(-float(mu_t) / np.cos(theta))


@dataclass(frozen=True)
class AbsorptionConfig:
    """透過吸収補正 v1 の設定 (frozen 値オブジェクト)。

    【機能概要】: 実効 μt の初期値・restraint 中心・restraint 重み・経験推定モード・許容逸脱幅を保持する。
    【実装方針】: すべて既定値付きの frozen dataclass。ファクトリで CellConfig 由来 / 経験推定を切替える。
    【設計方針】: restraint 幅超過警告 (REQ-103 字義) の許容幅を ``restraint_width`` として明示保持し、
                  精密化後の |μt − μt_calc| がこれを超えたら相関疑い警告を出す判定に用いる。
    【テスト対応】: T-N05 (既定/明示) / T-N06 (from_cell_config) / T-N07 (empirical) / E03 (frozen) /
                  T-E06 (restraint_width 超過で字義どおりの逸脱警告)。
    🔵 信頼性レベル: interfaces.py L97-104 / 要件定義 2.3 に依拠 (w_r 既定値・restraint_width は 🟡 設計裁量)。
    """

    mu_t_initial: float = 0.0  # 【初期実効 μt】: フィット開始値。既定 0.0 (無補正相当) 🔵
    mu_t_calc: float | None = None  # 【restraint 中心】: CellConfig 由来。None=経験推定 🔵
    restraint_weight: float = 100.0  # 【w_r】: restraint ペナルティ重み。既定 100.0 (強) 🔵
    empirical_mode: bool = False  # 【経験推定モード】: CellConfig 未提供時 True (警告出力) 🔵
    # 【許容逸脱幅】: |μt − μt_calc| がこれを超えたら restraint 幅超過の相関疑い警告 (REQ-103 字義)。
    # 既定 0.3 は透過セルの実効 μt が概ね O(0.1〜2) の域で「明確に逸脱」とみなせる絶対幅 🟡 設計裁量。
    restraint_width: float = 0.3

    @staticmethod
    def from_cell_config(config: CellConfig) -> AbsorptionConfig:
        """CellConfig から吸収設定を構成する。

        【実装方針】: ``config.mu_t_calc`` が算出済み (非 None) なら、それを restraint 中心かつ
                      初期値に採り強 restraint (w_r=100.0) を構成する。未算出 (None) なら経験推定
                      へフォールバックする (REQ-018)。xraylib は呼ばず mu_t_calc を読むだけ (REQ-403)。
        【テスト対応】: T-N06 (mu_t_calc あり→強 restraint) / T-B07 (None→empirical フォールバック)。
        🔵 信頼性レベル: 要件定義 2.3 / REQ-017/018/019 に依拠。
        """
        if config.mu_t_calc is not None:
            # 【強 restraint 構成】: 算出済み μt を中心+初期値に採用し empirical_mode=False 🔵
            mu = float(config.mu_t_calc)
            return AbsorptionConfig(
                mu_t_initial=mu, mu_t_calc=mu, restraint_weight=100.0, empirical_mode=False
            )
        # 【フォールバック】: μt 未算出は経験推定へ (弱 restraint + 警告) 🟡
        return AbsorptionConfig.empirical()

    @staticmethod
    def empirical() -> AbsorptionConfig:
        """CellConfig 未提供時の経験推定構成 (弱 restraint + 経験モード) を返す。

        【実装方針】: restraint 中心なし (None)・弱 restraint (w_r=1.0)・empirical_mode=True。
                      精密化時に「経験推定モード」明示 + 逆算 μt 提示の警告を伴う (REQ-018)。
        【テスト対応】: T-N07 (弱 restraint + 経験モード)。
        🔵 信頼性レベル: interfaces.py L103/109 / REQ-018 に依拠 (w_r=1.0 は 🟡)。
        """
        return AbsorptionConfig(
            mu_t_initial=0.0, mu_t_calc=None, restraint_weight=1.0, empirical_mode=True
        )
