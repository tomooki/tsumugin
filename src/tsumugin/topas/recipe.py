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
    :param phases: 相仕様 (占有率の宣言があれば占有率段を挟む)
    """
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

    # 【相分率の段は出さない】: GSAS 経路の「相分率を構造より先に分離する」(M7 T4 の教訓) は、
    #   TOPAS では **S0 で既に済んでいる** — 相ごとの ``scale`` が相分率そのもので、S0 が
    #   それを解放しているからである (和=1 の拘束も `MVW` の正規化があるので存在しない)。
    #   ここで ``{"scale": True, "phase_fraction_sum": True}`` の段を置くと、**何も変わらない
    #   段が「相分率を分離した」という顔で段列に残る** (実測 T4 で rwp・gof・n_params が
    #   ビット同一の no-op)。段列が嘘をつくくらいなら出さない。
    #
    # 【「分離を本当にやる」も測ったが効かなかった】: S0 を「背景のみ」→「+ 相分率」の 2 段に
    #   割って軌跡を変える案を T4 で実測したところ、**A 案と全段で一致した**
    #   (背景のみ 266.57 → 相分率を足して 27.4417 = 一括で合わせた S0 と同値。最終も
    #   19.2525 / 67.6165 で変わらず)。背景と相分率はこの系では**分けるほど縮退していない**。
    #   再発明を防ぐために負けた案として残す (`docs/benchmark/m12-topas/README.md`)。

    stages.append(
        RefinementStage(label="S4 coords", flags={"coords": True}, note="原子座標 (自由軸のみ)")
    )
    # 【占有率の段は宣言があるときだけ】: `apply_stage` は**宣言されたサイトだけ**解放する
    #   (全サイト一斉解放はスケール因子と縮退して占有率 1 超の非物理解へ行くため)。
    #   宣言が無ければ解放対象がゼロ = 構造的な no-op なので、段そのものを出さない。
    if any(p.free_occupancy_labels or p.mixed_occupancy_groups for p in phases):
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

    if any(h.radiation.is_tof for h in histograms):
        # 【TOF の幅も TOPAS では解放する】: GSAS 経路は「TOF 装置プロファイルは較正済みなので
        #   精密化しない」だったが、**TOPAS は装置ファイルの σ を読まない** — 幅の初期値は
        #   相対分解能から置いた粗い当て推量である (α/β は装置ファイルから写せるが、幅の
        #   sig-0/1/2 は関数形が違う)。出発点が違うので**同じ教訓が逆向きに効く**。
        #
        # 【効果は実測で確認済み】: T4 (決定論実行) で本段を外すと 19.25% → 22.45% に悪化し、
        #   内訳は TOF の 2 本が 29.0/44.6 → 47.0/46.7 と目に見えて崩れる。
        #
        # ⚠ **置き場所は結果に効かない**: X 線プロファイルの前に置いても後ろに置いても
        #   19.2525% でビット同一だった。当初「前 67.6% / 後 43.5%」という 24 ポイントの差を
        #   観測したが、それは **tc.exe のスレッド依存の非決定性**であって順序の効果ではなかった
        #   (`driver` が 1 スレッドに固定するようになった経緯を参照)。順序は**規約**として
        #   固定しているだけである。
        stages.append(
            RefinementStage(
                label="S7b tof_profile",
                flags={"tof_profile": True},
                note="TOF の d 依存幅 (TOPAS は装置ファイルの σ を読まないため)",
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

    # 【張れる先があるときだけ出す】: ``CS_L``/``Strain_L`` は波長と Bragg 角で書かれた
    #   **角度分散のモデル**で、TOF には対応物が無い (実 tc.exe は ``Negative FWHM`` で異常
    #   終了する)。TOF で同じ物理を担うのは上の ``tof_profile`` (幅の d/d² 項) である。
    #   条件を ``not all_tof`` でなく「非 TOF が 1 本でもある」にするのは、**ヒストグラムが
    #   空のとき** (`all_tof` は False) に「適用すると必ず `UnsupportedStageFlagError` で
    #   落ちる段」を出さないため。混在 joint では非 TOF にだけ張る (`flags.apply_stage`)。
    if any(not h.radiation.is_tof for h in histograms):
        any_tof = any(h.radiation.is_tof for h in histograms)
        stages.append(
            RefinementStage(
                label="S9 size_strain" + (" (非 TOF のみ)" if any_tof else ""),
                flags={"size_strain": True},
                note="微細構造は最後 (プロファイルと強く縮退するため)",
            )
        )
    return tuple(stages)
