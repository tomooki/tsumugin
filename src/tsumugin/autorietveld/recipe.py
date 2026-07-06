"""段階解放レシピ生成 (M7 自動 Rietveld アルゴリズム中核, 成果物1)。

GSAS-II チュートリアル T1–T4 の手順を一般化した普遍段階列に、ジオメトリ・温度差・多相・
混合占有のアダプタを適用して RefinementStage 列を生成する。純関数 (GSAS 非依存) のため
ユニットテスト可能で、engine 層がこの宣言的フラグを GSAS-II 呼び出しへ翻訳する。

**フラグ語彙 (engine が解釈する正準キー)**:
- ``background``: {"coeffs": N} — プロジェクト背景係数の解放
- ``scale``: True — 相分率スケールの解放
- ``cell``: True — 全相の単位胞
- ``displacement``: {hist_index: [GSAS Sample Parameters キー]} — ジオメトリ別試料変位
- ``profile``: ["U","V","W"] — Gaussian プロファイル係数
- ``profile_lorentzian``: True — X 線 Lorentzian X,Y + Zero の追加解放 (別段階, revert ガード)
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
    background_coeffs: int = 6,
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
    mixed_occ = any(p.mixed_occupancy_groups for p in phases)
    temp_diff = _has_temperature_difference(histograms)
    has_xray = any(not h.radiation.is_neutron for h in histograms)
    disp = _displacement_map(histograms)

    profile_stage = RefinementStage(
        label="profile+size_strain",
        flags={"profile": ["U", "V", "W"], "size_strain": True},
        note="プロファイル係数 + 結晶子サイズ/微小歪み",
    )
    # X 線は Lorentzian (X,Y) + Zero を別段階で追加解放する (実験室/放射光は Lorentzian 支配的;
    # U,V,W のみでは実測ピーク形状に合わず高止まり — CaTeO3 実測 43%→13%)。悪化時は本段階ごと
    # revert され U,V,W は保持 (T3/T4 非回帰)。中性子/TOF は engine 側でスキップ。
    lorentzian_stage = RefinementStage(
        label="profile_lorentzian",
        flags={"profile_lorentzian": True},
        note="X 線 Lorentzian X,Y + Zero (別段階, revert ガード)",
    )
    # 軸発散非対称 SH/L (分割擬フォークト相当の経験的ピーク形状)。X,Y,Zero とは別段階にし常に
    # 改善する訳ではないため悪化時は本段のみ revert (CaTeO3 frame0 で X,Y,Zero と同段だと 13.4→16.3 に劣化)。
    asymmetry_stage = RefinementStage(
        label="profile_asymmetry",
        flags={"profile_asymmetry": True},
        note="X 線 軸発散非対称 SH/L (別段階, revert ガード)",
    )
    coords_stage = RefinementStage(
        label="coords", flags={"coords": True}, note="一般位置の原子座標 X"
    )
    uiso_stage = RefinementStage(
        label="uiso", flags={"uiso": True}, note="等方温度因子 Uiso (混合占有は等価制約下)"
    )

    stages: list[RefinementStage] = []

    # S0: 相分率スケール + 背景 (全チュートリアル共通の起点)
    stages.append(
        RefinementStage(
            label="scale+background",
            flags={"scale": True, "background": {"coeffs": background_coeffs}},
            note="起点: スケールと背景のみ",
        )
    )

    if multiphase and not mixed_occ:
        # 多相 (T4 型: 放射光+TOF 二相) の順序 (実測で確立):
        # 相分率(和=1)を単独で先に → 格子+変位+プロファイル(+温度差 Dij) → 座標 → Uiso →
        # size/微小歪みを最後に。相分率を格子と同時に解放すると噛まず、size/歪みを座標より
        # 先に解放すると座標段階が悪化して revert するため、この順序が有効。
        stages.append(
            RefinementStage(
                label="phase_fractions",
                flags={"phase_fraction_sum": True},
                note="相分率 (各ヒストグラム和=1 制約)",
            )
        )
        cell_flags: dict[str, object] = {
            "cell": True,
            "displacement": disp,
            "profile": ["U", "V", "W"],
        }
        cell_note = "格子 + 試料変位 + プロファイル(CW)"
        if temp_diff:
            cell_flags["hydrostatic_strain"] = True
            cell_note += " + 温度差 Dij"
        stages.append(
            RefinementStage(label="cell+displacement+profile", flags=cell_flags, note=cell_note)
        )
        stages.append(coords_stage)
        stages.append(uiso_stage)
        stages.append(
            RefinementStage(
                label="size_strain",
                flags={"size_strain": True},
                note="結晶子サイズ/微小歪み (最後に解放)",
            )
        )
    else:
        # 単相 (T1/T2/T3): 格子+変位 (温度差なら Dij) を先に張る
        s1_flags: dict[str, object] = {"cell": True, "displacement": disp}
        note_bits = ["格子 + ジオメトリ別試料変位"]
        if temp_diff:
            s1_flags["hydrostatic_strain"] = True
            note_bits.append("温度差の静水圧歪み Dij")
        stages.append(
            RefinementStage(label="cell+displacement", flags=s1_flags, note="; ".join(note_bits))
        )
        # 混合占有の有無で解放順序を切り替える:
        # - 混合占有あり (中性子 garnet 型): 占有率 → Uiso(等価) → プロファイル → 一般位置座標。
        # - 混合占有なし (ラボ X 線 fluoroapatite 型): プロファイル → 座標 → Uiso。
        if mixed_occ:
            stages.append(
                RefinementStage(
                    label="occupancy",
                    flags={"occupancy": True},
                    note="混合占有サイトの占有率 (和=1 制約下)",
                )
            )
            stages.append(uiso_stage)
            stages.append(profile_stage)
            stages.append(coords_stage)
        else:
            stages.append(profile_stage)
            stages.append(coords_stage)
            stages.append(uiso_stage)

    # X 線は Lorentzian (X,Y) + Zero → 非対称 (SH/L) を最終段で追加解放 (各 revert ガード;
    # 中性子/TOF のみなら不要)
    if has_xray:
        stages.append(lorentzian_stage)
        stages.append(asymmetry_stage)

    # ラベルに S番号 を前置
    return tuple(
        RefinementStage(label=f"S{i} {s.label}", flags=s.flags, note=s.note)
        for i, s in enumerate(stages)
    )
