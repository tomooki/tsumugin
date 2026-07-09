"""標準試料からの CW 装置分解能関数の抽出 (Issue #38)。

NIST SRM 674b CeO2 等の標準試料を専用レシピで精密化し、装置プロファイル U,V,W,X,Y,SH/L を
`InstrumentProfile` として得る。得た分解能は `HistogramSpec.instrument_profile` に渡して試料精密化で
固定する (装置由来と試料由来の広がりの相関分離; PR #37 で判明した非物理値問題への対処)。

**確立した抽出レシピ (CeO2 実測)**: 背景 → cell → U,V,W → Lorentzian(X,Y,Zero) → (任意)SH/L。
**size/mustrain は解放しない** — 標準は試料広がりが無く、size/mustrain を解放すると U,V,W と競合して
負の局所解 (Rwp 20%) に落ちる。この順で Rwp 9.6% 到達を確認 (シャープ放射光ピークは Lorentzian 支配)。

numpy コア (レシピ合成・キー抽出)。GSAS は `run_auto_rietveld` 経由で遅延 import。
"""

from __future__ import annotations

from .model import HistogramSpec, InstrumentProfile, PhaseSpec, RefinementStage

# 抽出・固定で扱う CW 装置プロファイルキー。
INSTRUMENT_PROFILE_KEYS = ("U", "V", "W", "X", "Y", "SH/L", "Zero")


def build_resolution_recipe(
    *, background_coeffs: int = 12, refine_sh_l: bool = True
) -> tuple[RefinementStage, ...]:
    """標準試料の分解能抽出用レシピ (既存ステージフラグの合成)。

    背景+スケール → cell → profile(U,V,W) → profile_lorentzian(X,Y,Zero) → (任意)profile_asymmetry(SH/L)。
    **size/mustrain を含めない** (標準は試料広がりが無く、解放すると U,V,W と競合し負局所解に落ちる)。

    :param background_coeffs: 背景項数 (シャープピークの標準は多めが安定, 既定 12)
    :param refine_sh_l: 軸発散非対称 SH/L を最終段で解放するか (既定 True)
    :returns: RefinementStage のタプル (run_auto_rietveld の recipe 引数に渡す)
    """
    # 段階的解放が重要 (CeO2 実測): W→U,V,W→+X,Y の順で解放しないと、U,V,W を初手から同時解放すると
    # 悪い basin (Rwp~32%) に落ちる。かつ X,Y は U,V,W と**同一 "profile" フラグのキー列で同時解放**する
    # (別段階だと GSAS が Instrument Parameters を置換し U,V,W を凍結して相関局所解 ~20% を脱出できない)。
    stages = [
        RefinementStage(
            label="res scale+bkg",
            flags={"background": {"coeffs": int(background_coeffs)}},
            note="相分率スケール + 背景 (分解能抽出)",
        ),
        RefinementStage(label="res cell", flags={"cell": True}, note="格子定数"),
        RefinementStage(
            label="res W",
            flags={"profile": ["W"]},
            note="ガウス W 定数のみ先行 (初手全解放の悪 basin 回避)",
        ),
        RefinementStage(
            label="res UVW+Zero",
            flags={"profile": ["U", "V", "W", "Zero"]},
            note="ガウス Caglioti U,V,W + Zero",
        ),
        RefinementStage(
            label="res UVWXY",
            flags={"profile": ["U", "V", "W", "X", "Y", "Zero"]},
            note="U,V,W + Lorentzian X,Y + Zero を同時解放 (相関局所解を脱出; シャープ放射光は L 支配)",
        ),
    ]
    if refine_sh_l:
        stages.append(
            RefinementStage(
                label="res +SH/L",
                flags={"profile": ["U", "V", "W", "X", "Y", "Zero", "SH/L"]},
                note="軸発散非対称 SH/L も同時解放",
            )
        )
    return tuple(stages)


def extract_instrument_profile(
    standard: HistogramSpec,
    structure: PhaseSpec,
    *,
    runner=None,
    background_coeffs: int = 12,
    refine_sh_l: bool = True,
) -> InstrumentProfile:
    """標準試料を精密化し CW 装置分解能 (U,V,W,X,Y,SH/L,Zero) を抽出する。

    `build_resolution_recipe` を `run_auto_rietveld` (既定) または注入 runner に渡し、結果の
    `hist_profile[0]` から `INSTRUMENT_PROFILE_KEYS` を拾って `InstrumentProfile` を返す。
    runner 注入で決定論テスト可能 (GSAS 非依存)。実 CeO2 抽出は `@pytest.mark.gsas`。

    :param standard: 標準試料の観測仕様 (CeO2 等)
    :param structure: 標準の構造 (CeO2 CIF 等)
    :param runner: 精密化関数 (既定 run_auto_rietveld; テストは stub 注入)
    :param background_coeffs: 抽出レシピの背景項数
    :param refine_sh_l: SH/L 解放の有無
    :returns: InstrumentProfile (values / source_rwp)
    """
    run = runner
    if run is None:
        from .engine import run_auto_rietveld  # 遅延 import (GSAS 隔離)

        run = run_auto_rietveld
    recipe = build_resolution_recipe(
        background_coeffs=background_coeffs, refine_sh_l=refine_sh_l
    )
    result = run([standard], [structure], recipe=recipe)
    prof = result.hist_profile[0] if result.hist_profile else {}
    values = {k: float(prof[k]) for k in INSTRUMENT_PROFILE_KEYS if k in prof}
    return InstrumentProfile(values=values, source_rwp=result.final_rwp)
