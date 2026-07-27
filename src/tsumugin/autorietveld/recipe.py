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
    mixed_occ = any(
        p.mixed_occupancy_groups or p.free_occupancy_labels
        or p.occupancy_equiv_groups or p.occupancy_sum_groups
        for p in phases
    )
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

    # 【規定 (2026-07-27): 格子は単独 → 試料変位は後段】
    #   格子と試料変位はどちらも 2θ を動かすため強く相関する (Bragg-Brentano の Shift は
    #   ``pos -= const·4·Shift·cosθ`` で、格子定数の変化とほぼ同じ形のピークシフトを作る)。
    #   同じ段で自由にすると片方が他方を吸収し、**物理的に誤った格子で自己整合な解**へ落ちる —
    #   実測 (Kα1 単色 CaTeO3): Shift −274 µm 相当 (2θ −0.15°) を格子が肩代わりしていた。
    #   相関するパラメータを段で分ける、という段階解放の規律そのもの。
    #   Zero (`profile_lorentzian` 段) も 2θ オフセットなので、変位段はその**前**に置く。
    #   【交互精密化 cell → shift → cell】: 段のフラグは**累積 (enable のみ)** なので、変位段を
    #   分けただけでは格子は解放されたままで相関は切れない。変位段では格子を**明示的に凍結**し
    #   (``{"cell": False}``)、直後に格子を再解放する。これで「格子 → 変位 → 格子」の交互
    #   精密化になり、どちらか一方が他方を吸収したまま固まるのを防ぐ。
    displacement_stages = (
        RefinementStage(
            label="displacement",
            flags={"cell": False, "displacement": disp},
            note="ジオメトリ別 試料変位 (格子は凍結 — 2θ シフトが格子と相関するため)",
        ),
        RefinementStage(
            label="cell (repolish)",
            flags={"cell": True},
            note="変位を入れた上で格子を再解放 (交互精密化の戻り)",
        ),
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
        cell_flags: dict[str, object] = {"cell": True, "profile": ["U", "V", "W"]}
        cell_note = "格子 + プロファイル(CW)"
        if temp_diff:
            cell_flags["hydrostatic_strain"] = True
            cell_note += " + 温度差 Dij"
        stages.append(RefinementStage(label="cell+profile", flags=cell_flags, note=cell_note))
        stages.extend(displacement_stages)
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
        # 単相 (T1/T2/T3): 格子 (温度差なら Dij も; どちらも格子側パラメータ) を単独で先に張る
        s1_flags: dict[str, object] = {"cell": True}
        note_bits = ["格子 (試料変位とは別段)"]
        if temp_diff:
            s1_flags["hydrostatic_strain"] = True
            note_bits.append("温度差の静水圧歪み Dij")
        stages.append(RefinementStage(label="cell", flags=s1_flags, note="; ".join(note_bits)))
        stages.extend(displacement_stages)
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


# ---------------------------------------------------------------------------
# "本気フィット" (超丁寧) レシピ — 順次解放/凍結を 2 周してから全開放
# ---------------------------------------------------------------------------
#: 座標/占有率を「重原子から順に」解放するときに用意する元素ランク数の上限。
#: 実際の元素数を超えたランクの段は対象原子ゼロ = no-op (Rwp 不変で無害) になる。
_MAX_ELEMENT_RANKS = 6


def build_serious_recipe(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    background_coeffs: int = 6,
    rounds: int = 2,
) -> tuple[RefinementStage, ...]:
    """超丁寧な段階解放 (人手の「本気フィット」手順を機械化したもの)。

    手順 (ユーザー規定):
      1. 背景 + スケール (以降**常時解放**)
      2-12 を **順次解放 → 凍結** で ``rounds`` 周 (既定 2 周):
         2. 格子 / 3. 試料変位 / 4. プロファイル W→U→V (各単独) /
         5. 格子+変位 (収束確認。**以降 格子は常時解放**) / 6. サイズ・微小歪み /
         7. 座標 (重原子から順) / 8. 占有率 (重原子から順) / 9. Lorentzian /
         10. 非対称 / 11. 異方性歪み / 12. Uiso
      13. 全開放 (収束すれば完了)
      14. 2-12 を**累積**解放
      15. 全開放

    ``freeze_others`` は段の適用前に既存の解放を落とす (engine `_freeze_all`)。値に名前の列を
    与えるとそれらは凍結しない — 手順 5 以降は ``["cell"]`` を渡して格子を常時解放にする。
    座標/占有率の ``element_rank`` は「重い方から n 番目の元素だけ」を意味する。
    """
    if not histograms:
        raise ValueError("histograms が空です")
    if not phases:
        raise ValueError("phases が空です")
    disp = _displacement_map(histograms)
    has_xray = any(not h.radiation.is_neutron for h in histograms)
    multiphase = len(phases) > 1
    stages: list[RefinementStage] = [
        RefinementStage(
            label="bkg+scale",
            flags={"scale": True, "background": {"coeffs": background_coeffs}},
            note="背景 + スケール (以降 常時解放)",
        )
    ]
    if multiphase:
        stages.append(
            RefinementStage(
                label="phase_fractions",
                flags={"phase_fraction_sum": True},
                note="相分率 (和=1)。多相のみ",
            )
        )

    def sequential(keep: "list[str]") -> "list[RefinementStage]":
        """2-12 を 1 周ぶん (順次解放 → 凍結)。``keep`` は凍結しない名前。"""
        k = list(keep)
        out = [
            RefinementStage(label="cell", flags={"freeze_others": k or True, "cell": True},
                            note="格子のみ"),
            RefinementStage(label="displacement",
                            flags={"freeze_others": k or True, "displacement": disp},
                            note="試料変位のみ"),
        ]
        # 【W → U → V は "累積"】: Caglioti の U,V,W は独立の knob ではなく **1 つの物理量**
        #   (FWHM² = U·tan²θ + V·tanθ + W) の係数なので、1 つずつ「解放 → 凍結」すると
        #   意味を成さず後続が効かない。実測 (CaTeO3): W 単独のあと U 単独/V 単独は**両方 revert**
        #   し、以降 Lorentzian も効かず 18% で頭打ち (標準レシピの 12.4% に対し大幅悪化)。
        #   W から順に**足していく** (W → W,U → W,U,V) のが 古典的 な手順であり実測でも合う。
        for coeffs in (["W"], ["W", "U"], ["W", "U", "V"]):
            out.append(
                RefinementStage(label="profile_" + "".join(coeffs),
                                flags={"freeze_others": k or True, "profile": list(coeffs)},
                                note="プロファイル " + ",".join(coeffs) + " (累積)")
            )
        out.append(
            RefinementStage(label="cell+displacement",
                            flags={"freeze_others": k or True, "cell": True, "displacement": disp},
                            note="格子 + 変位 (収束確認。以降 格子は常時解放)")
        )
        # ここから格子は凍結しない
        k2 = sorted(set(k) | {"cell"})
        out.append(
            RefinementStage(label="size_strain",
                            flags={"freeze_others": k2, "size_strain": True},
                            note="サイズ / 微小歪み")
        )
        for rank in range(_MAX_ELEMENT_RANKS):
            out.append(
                RefinementStage(label=f"coords_z{rank}",
                                flags={"freeze_others": k2, "coords": rank},
                                note=f"座標 (重い方から {rank + 1} 番目の元素)")
            )
        for rank in range(_MAX_ELEMENT_RANKS):
            out.append(
                RefinementStage(label=f"occupancy_z{rank}",
                                flags={"freeze_others": k2, "occupancy": rank},
                                note=f"占有率 (重い方から {rank + 1} 番目の元素)")
            )
        if has_xray:
            out.append(
                RefinementStage(label="profile_lorentzian",
                                flags={"freeze_others": sorted(set(k2) | {"profile"}),
                                       "profile": ["U", "V", "W"], "profile_lorentzian": True},
                                note="Lorentzian X,Y + Zero (U,V,W は保持 — 同じ FWHM の別成分)")
            )
            out.append(
                RefinementStage(label="profile_asymmetry",
                                flags={"freeze_others": k2, "profile_asymmetry": True},
                                note="軸発散非対称 SH/L")
            )
        out.append(
            RefinementStage(label="aniso_strain",
                            flags={"freeze_others": k2, "size_strain": "generalized"},
                            note="異方性 微小歪み")
        )
        out.append(
            RefinementStage(label="uiso", flags={"freeze_others": k2, "uiso": True},
                            note="Uiso")
        )
        return out

    all_open: dict[str, object] = {
        "cell": True, "displacement": disp, "profile": ["U", "V", "W"],
        "size_strain": True, "coords": True, "uiso": True, "occupancy": True,
    }
    if multiphase:
        all_open["phase_fraction_sum"] = True
    if has_xray:
        all_open["profile_lorentzian"] = True
        all_open["profile_asymmetry"] = True

    keep: list[str] = []
    for _ in range(max(1, rounds)):
        stages.extend(sequential(keep))
        keep = ["cell"]  # 2 周目以降は格子を常時解放のまま入る
    # 13: 全開放
    stages.append(RefinementStage(label="all_open", flags=dict(all_open), note="全開放 (収束確認)"))
    # 14: 2-12 を累積解放 (freeze_others なし = 従来の累積セマンティクス)
    cumulative: list[tuple[str, dict[str, object]]] = [
        ("cell", {"cell": True}),
        ("displacement", {"displacement": disp}),
        ("profile", {"profile": ["W", "U", "V"]}),
        ("size_strain", {"size_strain": True}),
        ("coords", {"coords": True}),
        ("occupancy", {"occupancy": True}),
    ]
    if has_xray:
        cumulative.append(("profile_lorentzian", {"profile_lorentzian": True}))
        cumulative.append(("profile_asymmetry", {"profile_asymmetry": True}))
    cumulative.append(("aniso_strain", {"size_strain": "generalized"}))
    cumulative.append(("uiso", {"uiso": True}))
    for label, fl in cumulative:
        stages.append(RefinementStage(label=f"cum_{label}", flags=fl, note="累積解放"))
    # 15: 全開放
    stages.append(RefinementStage(label="all_open_final", flags=dict(all_open), note="全開放"))
    return tuple(
        RefinementStage(label=f"S{i} {s.label}", flags=s.flags, note=s.note)
        for i, s in enumerate(stages)
    )
