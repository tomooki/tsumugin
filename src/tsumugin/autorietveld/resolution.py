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

import math
import tempfile
from dataclasses import replace
from pathlib import Path

from .model import (
    Geometry,
    HistogramSpec,
    InstrumentProfile,
    PhaseSpec,
    Radiation,
    RefinementStage,
)

# 抽出・固定で扱う CW 装置プロファイルキー。
INSTRUMENT_PROFILE_KEYS = ("U", "V", "W", "X", "Y", "SH/L", "Zero")

# 分解能標準試料の参照構造 (最小 CIF)。line-profile 標準として一般的なもの。
STANDARD_REFERENCE_CIF: dict[str, str] = {
    # NIST SRM 674b CeO2 (蛍石型 Fm-3m, a≈5.4117 Å)。
    "CeO2": (
        "data_CeO2\n"
        "_cell_length_a 5.41165\n_cell_length_b 5.41165\n_cell_length_c 5.41165\n"
        "_cell_angle_alpha 90.0\n_cell_angle_beta 90.0\n_cell_angle_gamma 90.0\n"
        "_symmetry_space_group_name_H-M 'F m -3 m'\n_symmetry_Int_Tables_number 225\n"
        "loop_\n_atom_site_label\n_atom_site_type_symbol\n"
        "_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n"
        "_atom_site_occupancy\n_atom_site_U_iso_or_equiv\n"
        "Ce1 Ce 0.0 0.0 0.0 1.0 0.005\nO1 O 0.25 0.25 0.25 1.0 0.008\n"
    ),
    # NIST SRM 640 Si (ダイヤモンド型 Fd-3m, a≈5.4311 Å)。
    "Si": (
        "data_Si\n"
        "_cell_length_a 5.43119\n_cell_length_b 5.43119\n_cell_length_c 5.43119\n"
        "_cell_angle_alpha 90.0\n_cell_angle_beta 90.0\n_cell_angle_gamma 90.0\n"
        "_symmetry_space_group_name_H-M 'F d -3 m'\n_symmetry_Int_Tables_number 227\n"
        "loop_\n_atom_site_label\n_atom_site_type_symbol\n"
        "_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n"
        "_atom_site_occupancy\n_atom_site_U_iso_or_equiv\n"
        "Si1 Si 0.0 0.0 0.0 1.0 0.005\n"
    ),
}


def standard_reference_cif(name: str) -> str:
    """分解能標準の参照構造 CIF テキストを返す (大小文字非依存)。未登録は KeyError。"""
    key = {k.lower(): k for k in STANDARD_REFERENCE_CIF}.get(name.lower())
    if key is None:
        raise KeyError(
            f"未登録の標準試料: {name!r} (登録済: {', '.join(STANDARD_REFERENCE_CIF)})"
        )
    return STANDARD_REFERENCE_CIF[key]


def to_xye_text(two_theta, intensity) -> str:
    """(2θ, 強度) を GSAS 読込可能な xye テキスト (2θ 強度 esd) に変換する。

    esd は計数統計 (Poisson) の ``sqrt(I)``。I≤0 は esd 下限 1.0 (ゼロ重み/0 除算回避)。
    生の 2 列標準データ (.dat) を精密化可能にするための純変換 (numpy 配列 → テキスト)。
    """
    lines = []
    for tt, i in zip(two_theta, intensity):
        iv = float(i)
        esd = math.sqrt(iv) if iv > 0.0 else 1.0
        lines.append(f"{float(tt):.6f} {iv:.6f} {max(esd, 1.0):.6f}")
    return "\n".join(lines) + "\n"


def pxc_instprm_text(
    wavelength: float,
    *,
    zero: float = 0.0,
    polarization: float = 0.95,
    u: float = 2.0,
    v: float = -2.0,
    w: float = 5.0,
    sh_l: float = 0.002,
) -> str:
    """X 線 (PXC) の GSAS ``.instprm`` テキストを生成する (分解能抽出の初期値)。

    U,V,W,X,Y は抽出精密化で解放するため初期値でよい。放射光は偏光を高めに採る (既定 0.95)。
    """
    return "\n".join(
        [
            "#GSAS-II instrument parameter file; created by tsumugin.autorietveld.resolution",
            "Type:PXC",
            "Bank:1.0",
            f"Lam:{wavelength:.6f}",
            f"Zero:{zero:.6f}",
            f"Polariz.:{polarization:.4f}",
            "Azimuth:0.0",
            f"U:{u}",
            f"V:{v}",
            f"W:{w}",
            "X:0.0",
            "Y:0.0",
            "Z:0.0",
            f"SH/L:{sh_l}",
        ]
    ) + "\n"


def extract_instrument_profile_from_standard(
    data_path: str,
    *,
    wavelength: float,
    standard: str = "CeO2",
    work_dir: str | None = None,
    two_theta_limits: tuple[float, float] | None = None,
    radiation: Radiation = Radiation.XRAY_SYNCHROTRON,
    geometry: Geometry = Geometry.DEBYE_SCHERRER,
    zero: float = 0.0,
    polarization: float = 0.95,
    background_coeffs: int = 12,
    refine_sh_l: bool = False,
    runner=None,
) -> InstrumentProfile:
    """**生の 2 列標準試料データ**から装置分解能 (U,V,W,X,Y,SH/L,Zero) を一括抽出する再現関数。

    scratchpad の手作業 (2 列→xye 変換・CeO2 CIF 手書き・instprm 用意) を関数化し、生データ 1 ファイルから
    決定論的に `InstrumentProfile` を再現する。手順: 2 列読込 (`reference.io.load_xy`) → Poisson esd 付き
    xye 書出 → 標準参照 CIF (`standard`) 書出 → PXC instprm 生成 → `extract_instrument_profile`。

    :param data_path: 生の 2 列 (2θ, 強度) データ (.dat/.xy)。3 列目 esd があれば無視して Poisson を用いる
    :param wavelength: X 線波長 [Å] (必須; 較正ファイルと別なら実効値を指定)
    :param standard: 標準試料名 (STANDARD_REFERENCE_CIF に登録: "CeO2"/"Si")
    :param work_dir: 中間ファイル (xye/cif/instprm) の出力先。None なら一時ディレクトリ
    :param two_theta_limits: 精密化レンジ (直接ビーム/低角ノイズ除外に推奨)
    :param zero/polarization: instprm のゼロ点・偏光係数
    :param background_coeffs/refine_sh_l: 抽出レシピ設定 (build_resolution_recipe へ)
    :param runner: 精密化関数 (既定 run_auto_rietveld; テストは stub 注入)
    :returns: InstrumentProfile (values/source_rwp/wavelength)
    """
    from ..reference.io import load_xy  # 遅延 (numpy コア境界)

    two_theta, intensity = load_xy(data_path)
    wd = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="reso_"))
    wd.mkdir(parents=True, exist_ok=True)
    xye_path = wd / "standard.xye"
    cif_path = wd / f"{standard}.cif"
    prm_path = wd / "standard.instprm"
    xye_path.write_text(to_xye_text(two_theta, intensity), encoding="utf-8")
    cif_path.write_text(standard_reference_cif(standard), encoding="utf-8")
    prm_path.write_text(
        pxc_instprm_text(wavelength, zero=zero, polarization=polarization), encoding="utf-8"
    )

    hist = HistogramSpec(
        data_path=str(xye_path),
        instrument_path=str(prm_path),
        radiation=radiation,
        geometry=geometry,
        data_format="XYE",
        two_theta_limits=two_theta_limits,
    )
    phase = PhaseSpec(structure_path=str(cif_path), phase_name=standard, format_hint="CIF")
    ip = extract_instrument_profile(
        hist, phase, runner=runner,
        background_coeffs=background_coeffs, refine_sh_l=refine_sh_l,
    )
    return replace(ip, wavelength=wavelength)


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
