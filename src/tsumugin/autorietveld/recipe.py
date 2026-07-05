"""段階解放レシピ生成 (M7 自動 Rietveld アルゴリズム中核, 成果物1)。

GSAS-II チュートリアル T1–T4 の手順を一般化した普遍段階列に、ジオメトリ・温度差・多相・
混合占有のアダプタを適用して RefinementStage 列を生成する。純関数 (GSAS 非依存) のため
ユニットテスト可能で、engine 層がこの宣言的フラグを GSAS-II 呼び出しへ翻訳する。

**フラグ語彙 (engine が解釈する正準キー)**:
- ``background``: {"coeffs": N} — プロジェクト背景係数の解放
- ``scale``: True — 相分率スケールの解放
- ``cell``: True — 全相の単位胞
- ``displacement``: {hist_index: [GSAS Sample Parameters キー]} — ジオメトリ別試料変位
- ``profile``: ["U","V","W"] — プロファイル係数
- ``size_strain``: True — 結晶子サイズ + 微小歪み (HAP)
- ``coords``: True — 原子座標 X
- ``uiso``: True — 等方温度因子 U
- ``occupancy``: True — 混合占有サイトの占有率 (制約下)
- ``phase_fraction_sum``: True — 多相の相分率和=1 制約
- ``hydrostatic_strain``: True — ヒストグラム間温度差の静水圧歪み Dij

信頼性: 🔵 チュートリアル手順 (PLAN §4) + T1 プロトタイプ進行の一般化。
"""

from __future__ import annotations

from typing import Sequence

from .model import Geometry, HistogramSpec, PhaseSpec, RefinementStage

_GEOMETRY_DISPLACEMENT: dict[Geometry, list[str]] = {
    Geometry.BRAGG_BRENTANO: ["Shift"],
    Geometry.DEBYE_SCHERRER: ["DisplaceX", "DisplaceY"],
}


def _displacement_map(histograms: Sequence[HistogramSpec]) -> dict[int, list[str]]:
    """各ヒストグラムのジオメトリから試料変位パラメータ集合を決める (REQ-101)。"""
    return {
        i: list(_GEOMETRY_DISPLACEMENT[h.geometry])
        for i, h in enumerate(histograms)
    }


def _has_temperature_difference(histograms: Sequence[HistogramSpec]) -> bool:
    """測定温度が複数ヒストグラム間で異なるか (REQ-103)。"""
    temps = [h.temperature for h in histograms if h.temperature is not None]
    return len(temps) >= 2 and (max(temps) - min(temps) > 1e-9)


def build_recipe(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    background_coeffs: int = 3,
) -> tuple[RefinementStage, ...]:
    """普遍段階列 + アダプタから段階解放レシピを生成する。

    :param histograms: 観測ヒストグラム仕様 (1 本以上)
    :param phases: 相仕様 (1 つ以上)
    :param background_coeffs: 初期背景 (Chebyshev) 係数数
    :returns: RefinementStage の順序付きタプル
    """
    if not histograms:
        raise ValueError("histograms が空です")
    if not phases:
        raise ValueError("phases が空です")

    multiphase = len(phases) > 1
    mixed_occ = any(p.mixed_occupancy_sites for p in phases)
    temp_diff = _has_temperature_difference(histograms)
    disp = _displacement_map(histograms)

    stages: list[RefinementStage] = []

    # S0: 相分率スケール + 背景 (全チュートリアル共通の起点)
    stages.append(
        RefinementStage(
            label="S0 scale+background",
            flags={"scale": True, "background": {"coeffs": background_coeffs}},
            note="起点: スケールと背景のみ",
        )
    )

    # S1: 格子 + 試料変位 (+ 多相なら相分率和制約, 温度差なら静水圧歪み)
    s1_flags: dict[str, object] = {"cell": True, "displacement": disp}
    note_bits = ["格子 + ジオメトリ別試料変位"]
    if multiphase:
        s1_flags["phase_fraction_sum"] = True
        note_bits.append("相分率和=1 制約")
    if temp_diff:
        s1_flags["hydrostatic_strain"] = True
        note_bits.append("温度差の静水圧歪み Dij")
    stages.append(
        RefinementStage(label="S1 cell+displacement", flags=s1_flags, note="; ".join(note_bits))
    )

    # S2: プロファイル UVW + サイズ/微小歪み
    stages.append(
        RefinementStage(
            label="S2 profile+size_strain",
            flags={"profile": ["U", "V", "W"], "size_strain": True},
            note="プロファイル係数 + 結晶子サイズ/微小歪み",
        )
    )

    # S3: 原子座標
    stages.append(
        RefinementStage(label="S3 coords", flags={"coords": True}, note="原子座標 X")
    )

    # S4: 等方温度因子
    stages.append(
        RefinementStage(label="S4 uiso", flags={"uiso": True}, note="等方温度因子 Uiso")
    )

    # S5: 混合占有サイトの占有率 (制約下, 該当相があるときのみ)
    if mixed_occ:
        stages.append(
            RefinementStage(
                label="S5 occupancy",
                flags={"occupancy": True},
                note="混合占有サイトの占有率 (等価/和制約下)",
            )
        )

    return tuple(stages)
