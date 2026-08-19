"""TOPAS 向けの段階解放レシピ (M12) — 純関数。

`autorietveld.recipe.build_recipe` は **GSAS-II 向けに調整された順序**である。GSAS は装置
パラメータファイル (``.prm``/``.instprm``) から**較正済みの Caglioti U,V,W** を読み込んで
そこから始めるため、ピーク幅が最初から概ね合っており、格子や構造を先に解放しても収束する。

TOPAS はそうではない。TOPAS の ``TCHZ_Peak_Type`` は装置ファイルを参照せず**汎用の初期値**
から始まるので、ピーク幅が実測と大きく食い違ったまま格子を解放すると、格子がピーク幅の
不一致を吸収しようとして**悪化する**。実測 (garnet CW 中性子): 既定順では S1 cell が
42.7 → 50.7 と悪化して revert され、最終 23.6% で頭打ちになる。プロファイルを先に解放すると
同じデータで 12% 台まで落ちる。

したがって TOPAS の既定順序は **背景/スケール → プロファイル → 格子 → 構造** とする。
これはバックエンドの出自の違いに由来する**実質的な差**であり、レシピを共有できない箇所である
(共有できる中立層は `RefinementStage` の語彙そのものであって、順序ではない)。
"""

from __future__ import annotations

from typing import Sequence

from ..autorietveld.model import HistogramSpec, PhaseSpec, RefinementStage

# 【GSAS 側の判定をそのまま使う】: 「温度差があるか」は**バックエンドに依らない入力の性質**で、
#   ここで別実装を持つと 2 つの経路が別々の条件で段を出すようになる。翻訳が違うのは段の**中身**。
from ..autorietveld.recipe import has_temperature_difference

__all__ = ["build_topas_recipe"]


def build_topas_recipe(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    background_coeffs: int = 6,
) -> tuple[RefinementStage, ...]:
    """TOPAS 向けの適応段階解放レシピを組む。

    :param histograms: 観測ヒストグラム仕様 (放射源で分岐する)
    :param phases: 相仕様 (多相なら相分率段を挟む)
    """
    multiphase = len(phases) > 1
    any_xray = any(h.radiation.is_xray for h in histograms)
    all_tof = bool(histograms) and all(h.radiation.is_tof for h in histograms)

    stages: list[RefinementStage] = [
        RefinementStage(
            label="S0 scale+background",
            flags={"background": {"coeffs": background_coeffs}, "scale": True},
            note="まずスケールと背景だけを合わせる",
        )
    ]

    if not all_tof:
        # 【TOPAS では最優先】: 汎用初期値のピーク幅を実測へ寄せてから格子を触る。
        #   TOF は装置由来のプロファイルが較正済みなので解放しない (GSAS 経路 T4 の教訓と同じ)。
        stages.append(
            RefinementStage(
                label="S1 profile",
                flags={"profile": True},
                note="TOPAS は装置ファイルの U,V,W を読まないため先にピーク幅を合わせる",
            )
        )

    stages.append(
        RefinementStage(
            label="S2 cell+displacement",
            flags={"cell": True, "displacement": {i: ["Shift"] for i in range(len(histograms))}},
            note="ピーク位置 (格子 + ゼロ点)",
        )
    )

    if len(histograms) > 1 and has_temperature_difference(histograms):
        # 【温度差】: 構造としての格子は 1 つだが、実効セルはヒストグラムごとに違う
        #   (M7 T3 は X 線 295 K / 中性子 10 K)。共有セルを 1 本で妥協させると**両方が
        #   同じくらい悪くなる**ので、格子を合わせた直後に per-xdd のずれを許す。
        #   単一ヒストグラムでは格子と縮退するので出さない (`apply_stage` が落とす段)。
        stages.append(
            RefinementStage(
                label="S2b hydrostatic_strain",
                flags={"hydrostatic_strain": True},
                note="ヒストグラム間の温度差を per-xdd の実効セルで吸収する",
            )
        )

    if multiphase:
        # 多相は相分率を構造より先に分離する (M7 T4 の教訓)。
        stages.append(
            RefinementStage(
                label="S3 phase_fractions",
                flags={"scale": True, "phase_fraction_sum": True},
                note="相分率を構造より先に分離する",
            )
        )

    stages.append(
        RefinementStage(label="S4 coords", flags={"coords": True}, note="原子座標 (自由軸のみ)")
    )
    stages.append(
        RefinementStage(
            label="S5 occupancy",
            flags={"occupancy": True},
            note="占有率 (中性子は Uiso より先 — 散乱長コントラストが効く)",
        )
    )
    stages.append(RefinementStage(label="S6 uiso", flags={"uiso": True}, note="等方性 ADP"))

    if any_xray and not all_tof:
        stages.append(
            RefinementStage(
                label="S7 profile_lorentzian",
                flags={"profile_lorentzian": True},
                note="X 線の Lorentzian 成分",
            )
        )
    if not all_tof:
        stages.append(
            RefinementStage(
                label="S8 profile_asymmetry",
                flags={"profile_asymmetry": True},
                note="低角の軸発散非対称",
            )
        )

    stages.append(
        RefinementStage(
            label="S9 size_strain",
            flags={"size_strain": True},
            note="微細構造は最後 (プロファイルと強く縮退するため)",
        )
    )
    return tuple(stages)
