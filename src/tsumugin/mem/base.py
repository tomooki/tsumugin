"""MEM ソルバの交換可能境界と結果型 (M5 / REQ-018/027〜031 / FR-602 / P7)。

``RefinementBackend`` / ``EvidenceBackend`` / ``ChemPlausibility`` と同型の Protocol 境界
(``MEMBackend``) と、MEM 実行結果を表す frozen dataclass 群 (``MEMDensityMap`` /
``DensityCrossSection`` / ``BondPathDensity`` / ``MEMResult``) を提供する。

【非破壊 (P2)】: 実密度グリッドはファイル (path) に保持し、メモリには要約統計のみ持つ。
  MEMResult は密度を path 参照し親仮説/joint 結果を書き換えない。適用ガード警告は
  ``warnings`` に積むが仮説除外はしない (Dara 教訓, REQ-031)。

``MEMBackend.run`` の引数型 ``MEMInput`` は TASK-0054 で定義予定のため、文字列前方参照
(``"MEMInput"``) で受ける (``from __future__ import annotations`` により注釈は遅延評価され、
本モジュールは MEMInput を import しない)。実処理は TASK-0055 の ``DysnomiaBackend``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class MEMDensityMap:
    """MEM 密度マップ (VESTA 互換 .grd 等) への参照 + メタ。🔵 REQ-027

    実密度グリッドはファイル (``path``) に保持し、メモリには要約統計 (min/max) のみ持つ
    (重データを引き回さない・非破壊)。
    """

    path: str  # 【密度マップファイルパス (.grd 等)】 🔵 REQ-027
    density_kind: Literal["electron", "nuclear"]  # 【電子密度 / 核密度】 🔵 REQ-022
    grid_shape: tuple[int, int, int]  # 【グリッド次元 (nx, ny, nz)】 🔵
    min_density: float  # 【最小密度値】 🔵
    max_density: float  # 【最大密度値】 🔵


@dataclass(frozen=True)
class DensityCrossSection:
    """指定サイト/結合経路に沿った 1D/2D 断面。🔵 REQ-028"""

    label: str  # 【断面識別 (サイト対 / 経路名)】 🔵
    dimension: Literal[1, 2]  # 【1D / 2D】 🔵
    coordinates: np.ndarray  # 【断面座標 (経路長 or 面グリッド)】 🔵
    values: np.ndarray  # 【断面上の密度値】 🔵


@dataclass(frozen=True)
class BondPathDensity:
    """ボンド経路の最小密度 (伝導パス評価)。🔵 REQ-029

    Na/K 伝導パス可視化を想定し、経路上の最小密度を伝導ボトルネックとして抽出する。
    """

    start_site: str  # 【始点サイト】 🔵
    end_site: str  # 【終点サイト】 🔵
    min_density: float  # 【経路上の最小密度 (ボトルネック)】 🔵 REQ-029
    path_length: float  # 【経路長】 🔵


@dataclass(frozen=True)
class MEMResult:
    """MEM 実行結果 (密度マップ・断面・ボンド経路最小密度・警告)。🔵 REQ-018/027〜031

    【非破壊 (P2)】: 密度は ``density_map.path`` で参照し親仮説/joint 結果を書き換えない。
    【Dara 教訓 (REQ-031)】: 適用ガード警告は ``warnings`` に積むが仮説除外はしない
      (excluded/rejected 等のフィールドを一切持たない)。
    """

    density_map: MEMDensityMap  # 【密度マップ (.grd 参照 + 統計)】 🔵 REQ-027
    cross_sections: tuple[DensityCrossSection, ...] = ()  # 【1D/2D 断面】 🔵 REQ-028
    bond_paths: tuple[BondPathDensity, ...] = ()  # 【ボンド経路最小密度】 🔵 REQ-029
    r_factor: float | None = None  # 【MEM フィット R (収束判定用)】 🔵 REQ-026
    converged: bool = True  # 【MEM ソルバ収束】 🔵
    warnings: tuple[str, ...] = ()  # 【適用ガード等の信頼性警告 (除外はしない)】 🔵 REQ-030/031


@runtime_checkable
class MEMBackend(Protocol):
    """MEM ソルバの交換可能境界。🔵 REQ-018/FR-602

    ``RefinementBackend`` / ``EvidenceBackend`` / ``ChemPlausibility`` と同型の Protocol。
    v1 実装は ``DysnomiaBackend`` (外部バイナリラッパ, TASK-0055)。将来の内製/他ソルバも
    本 IF で交換可能。
    """

    name: str

    def run(self, mem_input: "MEMInput") -> MEMResult:  # noqa: F821 - 前方参照 (TASK-0054)
        """MEM 入力から密度マップ等を計算する。🔵 REQ-018/020

        未導入バックエンド (外部ソルバ未検出) は ``MEMUnavailableError`` (M4 定義済) を送出する
        契約とする。実処理は TASK-0055 の ``DysnomiaBackend``。``mem_input`` の型 ``MEMInput`` は
        TASK-0054 で定義予定のため文字列前方参照で受ける。
        """
        ...
