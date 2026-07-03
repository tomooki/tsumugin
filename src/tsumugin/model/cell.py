"""operando セル構成のデータモデル (仕様 §4 / REQ-016 CellConfig / REQ-019 MuCalculator)。

【機能概要】: セル層構成・ビーム条件・セル形状を表現する frozen 値オブジェクト群と、
              組成→μt 計算の交換境界 (Protocol) と未実装スタブを提供する。
【実装方針】: M0〜M2 の「不変値オブジェクト + Protocol 境界」パターンに準拠。numpy 等に依存しない純データ層。
【テスト対応】: tests/test_model_m3.py の N-01〜N-06/N-09/E-01〜E-04/B-01〜B-03/B-06 を通す。
🔵 信頼性レベル: 要件定義 2.1〜2.3/2.6 / interfaces.py L40-80 に依拠。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class CellLayer:
    """セル構成 1 層を表す不変値オブジェクト。

    【機能概要】: 層の役割・物質・層厚・密度を保持する frozen dataclass。
    【実装方針】: 必須 3 フィールド + 任意 density (既定 None) の器のみ。バリデーションは非スコープ。
    【テスト対応】: N-01/N-02/E-01/B-03 を通す。
    🔵 信頼性レベル: 要件定義 2.1 / interfaces.py L40-48 に依拠。
    """

    role: Literal["window", "electrode", "electrolyte", "separator", "collector"]  # 【層の役割】: 位置必須 🔵
    material: str  # 【物質名】: 位置必須。組成式 or 物質名 🔵
    thickness_mm: float  # 【層厚】: 位置必須。単位 mm 🔵
    density: float | None = None  # 【密度】: 任意 (g/cm3)。既定 None (計算しない/未知) 🟡


@dataclass(frozen=True)
class BeamConfig:
    """ビーム条件を表す不変値オブジェクト。

    【機能概要】: 波長/エネルギー/ビームサイズを保持する frozen dataclass。全フィールド既定値付き。
    【実装方針】: energy か wavelength の一方必須制約は本タスク非スコープ (器のみ)。
    【テスト対応】: N-03/E-02/B-01 を通す。
    🔵 信頼性レベル: 要件定義 2.2 / interfaces.py L50-57 に依拠。
    """

    wavelength: float | None = None  # 【波長】: 単位 Å。既定 None 🔵
    energy_kev: float | None = None  # 【エネルギー】: 単位 keV。既定 None 🔵
    size_mm: tuple[float, float] | None = None  # 【ビームサイズ】: 単位 mm。既定 None 🔵


@dataclass(frozen=True)
class CellConfig:
    """セル構成 (形状・層構成・ビーム・計算済み μt) を表す不変値オブジェクト。

    【機能概要】: 吸収補正 v1 (TASK-0026) の入力となるセル構成を保持する frozen dataclass。
    【実装方針】: 位置必須 geometry + 既定値付き 3 フィールド。素の tuple/None のみで構成し、
                  ``dataclasses.asdict`` でネスト dataclass→dict / tuple→tuple の JSON 互換型へ再帰展開する。
    【シリアライズ契約】: ``dataclasses.asdict`` は Python 仕様上 tuple 型を保持する (list へは変換しない)。
                  layers は tuple のまま展開されるため、tuple/list を同一視する equality ハックは設けない
                  (== の対称性を壊さない)。永続化統合で list 化が要るなら呼び出し側で明示変換する。
    【テスト対応】: N-04/N-05/N-06/E-03/E-04/B-02/B-06 を通す。
    🔵 信頼性レベル: 要件定義 2.3 / interfaces.py L59-67 に依拠。
    """

    geometry: Literal["transmission", "capillary"]  # 【セル形状】: 位置必須。層状セルは透過法のみ 🔵
    layers: tuple[CellLayer, ...] = ()  # 【層構成】: 既定は空 tuple。asdict でも tuple のまま保持 🔵
    beam: BeamConfig | None = None  # 【ビーム条件】: 既定 None 🔵
    mu_t_calc: float | None = None  # 【計算済み μt】: MuCalculator or 手入力。既定 None 🟡


class MuCalculator(Protocol):
    """組成→μt のエネルギー依存計算 (xraylib 等) の構造的型境界。

    【機能概要】: CellConfig から μt を算出する交換境界 (Protocol)。M3 は境界のみ提供。
    【実装方針】: 構造的部分型 (duck typing) の境界。実装は差し替え可能。
    【テスト対応】: N-09 (XraylibMuCalculator が本 Protocol を満たす) を通す。
    🔵 信頼性レベル: 要件定義 2.6 / REQ-019 / interfaces.py L69-73 に依拠。
    """

    def mu_t(self, config: CellConfig) -> float:
        """セル構成 config から μt を算出する。"""
        ...


class XraylibMuCalculator:
    """xraylib 連携の実装予定スタブ (M3 では未実装)。

    【機能概要】: MuCalculator を満たす実装予定スタブ。mu_t 呼出で NotImplementedError を送出する。
    【実装方針】: M3 では Protocol のみ確立し xraylib への実依存を持たない (REQ-403)。fail-loud で沈黙した誤値を返さない。
    【テスト対応】: N-09 (Protocol 適合) / E-04 (mu_t → NotImplementedError) を通す。
    🔵 信頼性レベル: 要件定義 2.6/4.4 / REQ-019 / TC-207-07 / interfaces.py L75-76 に依拠。
    """

    def mu_t(self, config: CellConfig) -> float:
        """μt 算出は M3 未実装。呼び出すと NotImplementedError を送出する。

        【実装方針】: xraylib 連携が未実装のため明示エラーで拒否 (沈黙した誤値を返さない)。
        🔵 信頼性レベル: 要件定義 4.4 / TC-207-07 に依拠。
        """
        # 【未実装拒否】: M3 では算出ロジックを持たないため fail-loud で NotImplementedError を送出 🔵
        raise NotImplementedError("xraylib による μt 計算は M3 では未実装です (REQ-019)")
