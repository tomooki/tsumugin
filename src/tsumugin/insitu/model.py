"""M9 高温 in situ 逐次 Rietveld の入出力データモデル (frozen dataclass, numpy-only)。

温度/時間系列の各フレームの精密化結果 (`FrameRietveldResult`)、系列全体の結果
(`SequentialRietveldResult`)、系列途中で自動同定・追加された相の記録 (`PhaseAppearance`)、
逐次エンジンの設定 (`SequentialConfig` / `PhaseIdConfig`) を提供する。GSAS-II / MP に非依存の
純データ層 (engine が GSAS を遅延 import で駆動し、この層を組み立てる)。

信頼性: 🔵 architecture.md §2–3。M7 `autorietveld.model` の系列版。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

# 相ごとの格子: (a, b, c, α, β, γ)
Cell = tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class FrameSpec:
    """系列 1 フレームの入力仕様 (観測データ 1 本 + 軸値)。

    :param data_path: 観測データファイル (.xrdml/.fxye/.xye/.gsa 等)
    :param axis_value: フレーム軸値 (温度 K または時間)。None なら index 軸
    :param data_format: GSAS-II importer 種別 ("XRDML"/"FXYE"/"GSAS"/"XYE")
    :param two_theta_limits: このフレームの精密化レンジ (None なら系列既定/全域)
    :param label: 人間可読ラベル (既定はファイル名)
    """

    data_path: str
    axis_value: float | None = None
    data_format: str = "XRDML"
    two_theta_limits: tuple[float, float] | None = None
    label: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "data_path": self.data_path,
            "axis_value": self.axis_value,
            "data_format": self.data_format,
            "two_theta_limits": list(self.two_theta_limits)
            if self.two_theta_limits is not None
            else None,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "FrameSpec":
        limits = d.get("two_theta_limits")
        return cls(
            data_path=str(d["data_path"]),
            axis_value=d.get("axis_value"),  # type: ignore[arg-type]
            data_format=str(d.get("data_format", "XRDML")),
            two_theta_limits=(float(limits[0]), float(limits[1])) if limits is not None else None,
            label=str(d.get("label", "")),
        )


@dataclass(frozen=True)
class PhaseIdConfig:
    """系列途中の新相自動同定の設定。

    :param elements: 相同定に許す元素系 (既知相の元素 + 想定元素)。空なら同定を行わない
    :param frac_min: 新相の採用に要する最小相分率 (受理基準①)
    :param rwp_eps: 新相採用に要する最小 Rwp 改善 (受理基準②, %ポイント)
    :param top_k: 各変化点で試す候補相の数 (Dara ランキング上位)
    :param hull_cutoff_ev: MP 安定性フィルタ (energy above hull, eV/atom)
    :param subtract_bg: 残差ピーク抽出前に背景減算 (SNIP) するか
    :param trigger_rwp_ratio: 相同定を試みる Rwp 相対ジャンプ閾値。現フレーム Rwp が
        (系列内最小 Rwp × 本比) を超えたら (変化点発火に加えて) 新相探索を試みる。短系列で変化点窓の
        warm-up 前でも新相出現を捉えるための頑健トリガ (採否は受理基準が担保)。
    :param refine_new_phase_cell: 新相の**異方的**格子を Pawley プリアラインで補正するか (Issue #20)。
        MP(DFT)構造は格子が軸別にずれ (CaTeO3 delta で c +3.4%)、等方 strain では吸収できず Rietveld
        収束半径外で追えない。True で物質化 CIF を観測へ整合させた異方セルに置換してから精密化に渡す。
    :param wavelength: プリアラインの線源波長 (Å)。既定 Cu Kα1。放射光/中性子系列では実波長を指定。
    :param rerank_top_k: >0 で相同定の上位 K 候補を異方格子整合で再スコアする (Issue #20 hybrid)。
        等方整合が DFT の軸別誤差で正解相を top_k から落とすのを防ぐ。既定 5 (0 で無効)。
    """

    elements: tuple[str, ...] = ()
    frac_min: float = 0.02
    rwp_eps: float = 1e-6
    top_k: int = 1
    hull_cutoff_ev: float | None = 0.1
    subtract_bg: bool = True
    trigger_rwp_ratio: float = 1.25
    refine_new_phase_cell: bool = True
    wavelength: float = 1.5406
    rerank_top_k: int = 5

    @property
    def enabled(self) -> bool:
        return bool(self.elements)


@dataclass(frozen=True)
class SequentialConfig:
    """逐次精密化エンジンの設定。

    :param warm_start: 直前フレームの精密化格子を次フレームの初期格子に引き継ぐか
    :param two_theta_limits: 全フレーム共通の精密化レンジ (フレーム個別指定が優先)
    :param max_frames: 先頭から解析するフレーム上限 (None なら全部, デバッグ/検証短縮用)
    :param changepoint_window: 変化点検出のローリング窓 (sequential.changepoint と整合)
    :param phase_id: 新相自動同定設定 (None/無効なら相追加しない)
    """

    warm_start: bool = True
    two_theta_limits: tuple[float, float] | None = None
    max_frames: int | None = None
    changepoint_window: int = 5
    phase_id: PhaseIdConfig | None = None


@dataclass(frozen=True)
class FrameRietveldResult:
    """系列 1 フレームの精密化結果。

    :param frame_index: 0 始まりのフレーム番号
    :param axis_value: フレーム軸値 (温度/時間, None 可)
    :param data_path: 観測データファイル
    :param rwp: 最終 Rwp (%)。失敗フレームは inf
    :param gof: 最終 GOF。失敗フレームは inf
    :param refined_cells: 相名→精密化格子 (a,b,c,α,β,γ)
    :param phase_fractions: 相名→相分率 (単相は {name: 1.0})
    :param phase_names: このフレームで有効な相名 (安定順)
    :param changepoint: 変化点として発火したフレームか
    :param changepoint_reasons: 発火した指標名 (rwp_jump/lattice_jump/new_peaks)
    :param validity_passed: 物理妥当性ゲート合格か
    :param refine_failed: 精密化が失敗 (inf 変換) したフレームか
    """

    frame_index: int
    axis_value: float | None
    data_path: str
    rwp: float
    gof: float
    refined_cells: Mapping[str, Cell]
    phase_fractions: Mapping[str, float]
    phase_names: tuple[str, ...]
    changepoint: bool = False
    changepoint_reasons: tuple[str, ...] = ()
    validity_passed: bool = True
    refine_failed: bool = False


@dataclass(frozen=True)
class PhaseAppearance:
    """系列途中で自動同定・採用された新相の記録。

    :param phase_name: 相名
    :param frame_index: 初めて採用されたフレーム
    :param axis_value: そのフレームの軸値
    :param structure_path: 物質化した構造ファイル (CIF) パス
    :param source: 供給元 ("materials_project"/"user_cif"/...)
    :param rwp_before: 相追加前の Rwp
    :param rwp_after: 相追加後の Rwp
    :param evidence: 同定根拠 (dara_score・未指数説明数など)
    """

    phase_name: str
    frame_index: int
    axis_value: float | None
    structure_path: str
    source: str
    rwp_before: float
    rwp_after: float
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SequentialRietveldResult:
    """温度/時間系列の逐次自動 Rietveld の総合結果。

    :param frames: フレーム別結果 (フレーム順)
    :param appearances: 自動同定で採用された新相の記録 (採用順)
    :param phase_names: 系列で観測された全相名の和 (安定順)
    :param warnings: 非致命の警告
    :param ledger: 追記された台帳 (None なら未使用)
    """

    frames: tuple[FrameRietveldResult, ...]
    appearances: tuple[PhaseAppearance, ...] = ()
    phase_names: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    ledger: object | None = None

    def axis_values(self) -> tuple[float | None, ...]:
        """全フレームの軸値。"""
        return tuple(f.axis_value for f in self.frames)

    def cell_series(self, phase: str, component: str = "a") -> tuple[tuple[float, ...], tuple[float, ...]]:
        """相 phase の格子成分 (a/b/c/alpha/beta/gamma) の (軸値, 値) 系列を返す。

        当該相が存在し軸値が数値のフレームのみ (欠測フレームは除外)。decreasing でも順序保持。
        """
        idx = {"a": 0, "b": 1, "c": 2, "alpha": 3, "beta": 4, "gamma": 5}[component]
        axes: list[float] = []
        vals: list[float] = []
        for f in self.frames:
            cell = f.refined_cells.get(phase)
            if cell is None or f.axis_value is None or f.refine_failed:
                continue
            axes.append(float(f.axis_value))
            vals.append(float(cell[idx]))
        return tuple(axes), tuple(vals)

    def fraction_series(self, phase: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """相 phase の相分率の (軸値, 分率) 系列を返す (存在しないフレームは 0.0)。"""
        axes: list[float] = []
        vals: list[float] = []
        for f in self.frames:
            if f.axis_value is None or f.refine_failed:
                continue
            axes.append(float(f.axis_value))
            vals.append(float(f.phase_fractions.get(phase, 0.0)))
        return tuple(axes), tuple(vals)
