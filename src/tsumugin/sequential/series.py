"""シーケンシャル入力の値オブジェクト (仕様 §4 sequence_axis / interfaces.py L62-73)。

時系列 (時間/温度軸) の粉末回折フレーム列を保持する不変値オブジェクト ``FrameSeries`` を提供する。
全フレーム共通の 2θ グリッドとフレーム×測定点の強度行列を持ち、``__post_init__`` で形状不一致を
明示エラー (``ValueError``) にする (縮退 None ではなく器の契約違反として弾く)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from tsumugin.model import ExternalChannel

# 【軸種別】: フレーム軸の意味づけ。空 axis_values は index 軸を表す 🔵 interfaces.py L69
AxisKind = Literal["time", "temperature", "index", "custom"]


@dataclass(frozen=True)
class FrameSeries:
    """時系列フレーム列を保持する不変値オブジェクト。

    【機能概要】: 全フレーム共通の 2θ グリッドと (n_frames, n_points) の強度行列を保持し、
      フレーム軸メタデータ (axis_values / axis_kind) と外部チャネル (channels) を紐付ける。
    【実装方針】: interfaces.py L62-73 の frozen dataclass 契約に一致させ、__post_init__ で
      構造的な形状不一致のみを明示エラーにする (統計縮退とは区別し器の契約違反として弾く)。
    【テスト対応】: TC-S-N01〜N03 / TC-S-E01〜E03 / TC-S-B01〜B03 を通す。
    🔵 信頼性レベル: interfaces.py L62-73 / REQ-006 / 完了条件① に依拠。
    """

    two_theta: np.ndarray  # 【共通グリッド】: 全フレーム共通の 2θ 軸 (n_points,) 🔵
    intensities: np.ndarray  # 【強度行列】: (n_frames, n_points) のフレーム×測定点 🟡
    axis_values: tuple[float, ...] = ()  # 【軸値】: フレーム軸値。空なら index 軸 🔵
    axis_kind: AxisKind = "index"  # 【軸種別】: 既定 index 🔵
    channels: tuple[ExternalChannel, ...] = ()  # 【外部チャネル】: 温度等 (TASK-0011) 🔵 REQ-006

    def __post_init__(self) -> None:
        """形状整合を検証し不一致を明示エラーにする (縮退値ではなく契約違反)。

        【実装方針】: 完了条件① の 2 条件 (列数一致 / 軸値長一致) を厳密不一致 (!=) で判定。
          空 axis_values は index 軸を意味するため長さ検証を免除する (interfaces.py L69)。
        【テスト対応】: TC-S-E01 (列数不一致) / TC-S-E02 (軸値長不一致) を明示エラーにする。
        🟡 信頼性レベル: 完了条件① に依拠。エラー型 ValueError は backends/base.py:61 の入力検証慣習に準拠。
        """
        # 【次元検証】: intensities は必ず 2D (単一フレームでも (1, n_points))。1D 誤入力を弾く 🟡
        if self.intensities.ndim != 2:
            raise ValueError(
                f"intensities must be 2D (n_frames, n_points); got ndim={self.intensities.ndim}"
            )
        # 【列数検証】: 強度行列の測定点数が共通グリッド長と一致すること (別グリッド混在を弾く) 🟡
        n_points = self.intensities.shape[1]
        if n_points != len(self.two_theta):
            raise ValueError(
                "intensities column count must match two_theta length: "
                f"{n_points} != {len(self.two_theta)}"
            )
        # 【軸値長検証】: 非空 axis_values はフレーム数と一致すること。空は index 軸で免除 🔵
        if self.axis_values and len(self.axis_values) != self.intensities.shape[0]:
            raise ValueError(
                "axis_values length must match n_frames: "
                f"{len(self.axis_values)} != {self.intensities.shape[0]}"
            )

    @property
    def n_frames(self) -> int:
        """フレーム数を返す (強度行列の行数由来)。

        【実装方針】: axis_values 長ではなく intensities.shape[0] を採り、空軸値でも正しく算出。
        🔵 信頼性レベル: interfaces.py L72-73 (n_frames = intensities.shape[0]) に依拠。
        """
        # 【行数由来】: 軸値の有無に依存せず強度行列の行数をフレーム数とする 🔵
        return int(self.intensities.shape[0])
