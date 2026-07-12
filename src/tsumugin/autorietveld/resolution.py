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
from typing import Mapping

from .model import (
    CalibrationResult,
    Geometry,
    HistogramSpec,
    InstrumentProfile,
    PhaseSpec,
    Radiation,
    RefinementStage,
)
from .recipe import _GEOMETRY_DISPLACEMENT

# 立方標準の認証格子定数 a [Å] (a=b=c, 90°)。波長較正で格子を固定する基準。
STANDARD_CELL_A: dict[str, float] = {
    "CeO2": 5.41165,   # NIST SRM 674b
    "Si": 5.43119,     # NIST SRM 640
}

# 抽出・固定で扱う CW 装置プロファイルキー。
INSTRUMENT_PROFILE_KEYS = ("U", "V", "W", "X", "Y", "SH/L", "Zero")

# 転写可能な分解能のための非負拘束 (U,W,X,Y≥0)。V は Caglioti 交差項で負が正常・SH/L は非対称なので拘束外。
# 無拘束抽出は CeO2 の超シャープピークで相関非物理解 (Y<0・2θ>32° で FWHM 負) に落ち転写不能なため。
NONNEG_PROFILE_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "U": (0.0, None), "W": (0.0, None), "X": (0.0, None), "Y": (0.0, None),
}

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
    constrain_nonneg: bool = True,
    search: str | None = None,
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
    cif_text = standard_reference_cif(standard)  # 未登録は早期に KeyError (ファイル書出前)
    auto_tmp = work_dir is None
    wd = Path(tempfile.mkdtemp(prefix="reso_")) if auto_tmp else Path(work_dir)
    try:
        wd.mkdir(parents=True, exist_ok=True)
        xye_path = wd / "standard.xye"
        cif_path = wd / f"{standard}.cif"
        prm_path = wd / "standard.instprm"
        xye_path.write_text(to_xye_text(two_theta, intensity), encoding="utf-8")
        cif_path.write_text(cif_text, encoding="utf-8")
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
        if search == "grid":
            # 物理拘束解をアンカーに候補探索し境界クランプを避けて最良物理解を選ぶ (Issue #38 拡張)。
            ip = search_instrument_profile(
                hist, phase, runner=runner, refine_sh_l=refine_sh_l,
            )
        else:
            ip = extract_instrument_profile(
                hist, phase, runner=runner,
                background_coeffs=background_coeffs, refine_sh_l=refine_sh_l,
                constrain_nonneg=constrain_nonneg,
            )
        return replace(ip, wavelength=wavelength)
    finally:
        # 自動生成した一時ディレクトリのみ後片付け (work_dir 指定時は保持)。
        if auto_tmp:
            import shutil

            shutil.rmtree(wd, ignore_errors=True)


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
    constrain_nonneg: bool = True,
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
    :param constrain_nonneg: U,W,X,Y を非負拘束するか (既定 True; 転写可能な分解能を得るため)。
        呼出側が standard.profile_bounds を明示指定していればそれを優先し非負拘束を上書きしない
    :returns: InstrumentProfile (values / source_rwp)
    """
    if constrain_nonneg:
        # 非負拘束をベースに、呼出側の明示 bounds を優先して上書き (EDGE-002)。
        merged = dict(NONNEG_PROFILE_BOUNDS)
        if standard.profile_bounds:
            merged.update(standard.profile_bounds)
        standard = replace(standard, profile_bounds=merged)
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


def build_calibration_recipe(
    *,
    geometry: Geometry = Geometry.DEBYE_SCHERRER,
    background_coeffs: int = 12,
    refine_wavelength: bool = False,
) -> tuple[RefinementStage, ...]:
    """標準試料較正用レシピ (格子固定・ゼロ点/変位/プロファイル解放, Issue #61)。

    格子は認証値に固定 (呼出側が `PhaseSpec.refine_cell=False` + `initial_cells` で設定) し、
    背景 → Zero+試料変位 → W → U,V,W,X,Y+Zero の順で位置とプロファイルを解放する。

    ⚠ **波長 (Lam) は既定で解放しない**。標準の強反射が低角に偏るデータでは、波長 (∝tanθ)・
    ゼロ点 (定数)・試料変位 (∝cosθ/sinθ) の角度依存が低角でほぼ縮退し、波長が試料変位と分離できない
    (CeO2 実測: 変位固定で +67 ppm・変位解放で +1172 ppm と大きく振れ同 Rwp)。波長はモノクロメータの
    エネルギー較正で与える公称値を**信頼して固定**し、標準ではゼロ点・変位・プロファイルを較正する。
    小さいゼロ点/変位で良好 Rwp なら公称波長と認証格子が整合している傍証となる。
    高角に強反射がある高分解能データで敢えて波長を交差確認したい場合のみ `refine_wavelength=True`
    (縮退に留意し変位と同時解放しない: Lam+Zero を W より前に単独段で解放)。

    **SH/L は解放しない**: 装置の非対称ラインシェイプと相関して位置を発散させる (Rwp 12→26% 悪化)。

    :param geometry: 回折計ジオメトリ (試料変位パラメータの選択に用いる)
    :param background_coeffs: 背景 (Chebyshev) 係数数
    :param refine_wavelength: 波長 Lam も解放するか (既定 False; 縮退のため非推奨・交差確認用)
    :returns: RefinementStage のタプル (calibrate_instrument_from_standard が用いる)
    """
    disp_keys = _GEOMETRY_DISPLACEMENT[geometry]
    disp = {0: list(disp_keys)}
    stages = [
        RefinementStage(
            label="cal scale+bkg",
            flags={"scale": True, "background": {"coeffs": int(background_coeffs)}},
            note="相分率スケール + 背景 (標準較正)",
        ),
        RefinementStage(
            label="cal zero+disp",
            flags={"displacement": disp, "profile": ["Zero"]},
            note="ゼロ点 + 試料変位 (位置合わせ)",
        ),
    ]
    if refine_wavelength:
        stages.append(
            RefinementStage(
                label="cal lam+zero",
                flags={"profile": ["Lam", "Zero"]},
                note="波長 Lam + ゼロ点 (縮退に留意; 変位・プロファイルと同時解放しない)",
            )
        )
    stages += [
        RefinementStage(
            label="cal W",
            flags={"profile": ["W"]},
            note="ガウス W 定数 (位置確定後にプロファイル)",
        ),
        RefinementStage(
            label="cal UVWXY+Zero",
            flags={"profile": ["U", "V", "W", "X", "Y", "Zero"]},
            note="U,V,W + Lorentzian X,Y + Zero (装置プロファイル)",
        ),
    ]
    return tuple(stages)


def calibrate_instrument_from_standard(
    data_path: str,
    *,
    wavelength_init: float,
    standard: str = "CeO2",
    cell_a: float | None = None,
    work_dir: str | None = None,
    two_theta_limits: tuple[float, float] | None = None,
    radiation: Radiation = Radiation.XRAY_SYNCHROTRON,
    geometry: Geometry = Geometry.DEBYE_SCHERRER,
    polarization: float = 0.95,
    background_coeffs: int = 12,
    constrain_nonneg: bool = True,
    refine_wavelength: bool = False,
    runner=None,
) -> CalibrationResult:
    """立方標準試料 (CeO2/Si 等) で**ゼロ点・試料変位・装置プロファイル**を較正する (格子固定, Issue #61)。

    `extract_instrument_profile*` が格子を解放して分解能を抽出するのと対照的に、本関数は格子を
    **認証値に固定** (`PhaseSpec.refine_cell=False` + `initial_cells`) し、公称波長も固定した上で、
    ゼロ点・試料変位・装置プロファイルを標準に合わせる。小さいゼロ点/変位で良好 Rwp なら、公称波長と
    認証格子の整合の傍証となる。

    ⚠ **波長は既定で解放しない** (`refine_wavelength=False`)。強反射が低角に偏ると波長は試料変位と
    縮退して分離できず (CeO2 実測: 変位固定 +67 ppm・変位解放 +1172 ppm・同 Rwp)、標準からの波長較正は
    信頼できない。波長はモノクロメータのエネルギー較正で与える公称値を採る。→ `CalibrationResult.wavelength`
    は既定で入力値と同一 (`ppm_shift=0`)。

    手順: 2 列読込 → Poisson esd 付き xye → 標準参照 CIF → PXC instprm → `build_calibration_recipe`
    (格子固定) を `run_auto_rietveld` へ。結果 `hist_profile[0]` から Zero/プロファイル (+任意で Lam) を拾う。
    転写に用いるのは Zero と装置プロファイル (V,X 等)。**試料変位は試料固有 (毛細管位置) なので転写せず**、
    試料側で別途精密化する。

    ⚠ **立方標準専用** (a=b=c, 90°)。非立方標準は未対応。SH/L は解放しない (位置を発散させる)。

    :param data_path: 生の 2 列 (2θ, 強度) データ (.dat/.xy)。3 列目 esd があれば無視し Poisson を用いる
    :param wavelength_init: 公称波長 [Å] (モノクロメータ較正値)。既定では固定して用いる
    :param standard: 標準試料名 (STANDARD_CELL_A/STANDARD_REFERENCE_CIF に登録: "CeO2"/"Si")
    :param cell_a: 認証格子 a [Å] (None なら STANDARD_CELL_A[standard])。ロット/温度で微調整する場合に指定
    :param two_theta_limits: 精密化レンジ (直接ビーム/低角ノイズ除外に推奨)
    :param constrain_nonneg: U,W,X,Y を非負拘束するか (既定 True; 転写可能な物理プロファイルを得る)
    :param refine_wavelength: 波長 Lam も解放するか (既定 False; 縮退のため非推奨・交差確認用)
    :param runner: 精密化関数 (既定 run_auto_rietveld; テストは stub 注入)
    :returns: CalibrationResult (wavelength/zero/profile/reference_cell/source_rwp)
    """
    from ..reference.io import load_xy  # 遅延 (numpy コア境界)

    two_theta, intensity = load_xy(data_path)
    cif_text = standard_reference_cif(standard)  # 未登録は早期 KeyError (大小文字非依存)
    if cell_a is not None:
        a: float | None = float(cell_a)
    else:
        # STANDARD_CELL_A も standard_reference_cif と同じく大小文字非依存で引く (整合)。
        cell_key = {k.lower(): k for k in STANDARD_CELL_A}.get(standard.lower())
        a = STANDARD_CELL_A[cell_key] if cell_key is not None else None
    if a is None:
        raise KeyError(
            f"標準 {standard!r} の認証格子が未登録です。cell_a を明示指定してください "
            f"(登録済: {', '.join(STANDARD_CELL_A)})"
        )
    ref_cell = (a, a, a, 90.0, 90.0, 90.0)

    auto_tmp = work_dir is None
    wd = Path(tempfile.mkdtemp(prefix="calib_")) if auto_tmp else Path(work_dir)
    try:
        wd.mkdir(parents=True, exist_ok=True)
        xye_path = wd / "standard.xye"
        cif_path = wd / f"{standard}.cif"
        prm_path = wd / "standard.instprm"
        xye_path.write_text(to_xye_text(two_theta, intensity), encoding="utf-8")
        cif_path.write_text(cif_text, encoding="utf-8")
        prm_path.write_text(
            pxc_instprm_text(wavelength_init, polarization=polarization), encoding="utf-8"
        )

        bounds = dict(NONNEG_PROFILE_BOUNDS) if constrain_nonneg else None
        hist = HistogramSpec(
            data_path=str(xye_path),
            instrument_path=str(prm_path),
            radiation=radiation,
            geometry=geometry,
            data_format="XYE",
            two_theta_limits=two_theta_limits,
            profile_bounds=bounds,
        )
        # 格子を認証値に固定 (refine_cell=False) し、initial_cells で認証セルを設定する。
        phase = PhaseSpec(
            structure_path=str(cif_path), phase_name=standard, format_hint="CIF",
            refine_cell=False,
        )
        run = runner
        if run is None:
            from .engine import run_auto_rietveld  # 遅延 import (GSAS 隔離)

            run = run_auto_rietveld
        recipe = build_calibration_recipe(
            geometry=geometry, background_coeffs=background_coeffs,
            refine_wavelength=refine_wavelength,
        )
        result = run(
            [hist], [phase], recipe=recipe, initial_cells={standard: ref_cell}
        )
        prof = result.hist_profile[0] if result.hist_profile else {}
        # 波長は既定で固定 → 入力値を採る。refine_wavelength=True のときのみ精密化値 (縮退注意)。
        lam = float(prof.get("Lam", wavelength_init)) if refine_wavelength else float(wavelength_init)
        zero = float(prof.get("Zero", 0.0))
        profile = {k: float(prof[k]) for k in ("U", "V", "W", "X", "Y", "SH/L") if k in prof}
        return CalibrationResult(
            wavelength=lam,
            wavelength_init=float(wavelength_init),
            zero=zero,
            profile=profile,
            reference_cell=ref_cell,
            source_rwp=result.final_rwp,
        )
    finally:
        if auto_tmp:
            import shutil

            shutil.rmtree(wd, ignore_errors=True)


# =====================================================================
# 物理候補探索 (境界クランプ回避; grid/Bayesian で最良物理解を選ぶ)
# =====================================================================

# FWHM 評価で tanθ/1/cosθ が発散する 2θ 端を避けるクランプ (度)。
_FWHM_TT_MIN = 0.5
_FWHM_TT_MAX = 179.0


def profile_total_fwhm(values: Mapping[str, float], two_theta):
    """GSAS getFWHM (CW) 準拠の総 pseudo-Voigt FWHM [deg] を 2θ 配列で返す。

    sig=sqrt(max(0.001, U·tan²θ+V·tanθ+W)) (GSAS はガウス分散を 0.001 でクランプ)、gam=X/cosθ+Y·tanθ、
    総 FWHM = getgamFW(2.35482·sig, gam)/100 (Thompson-Cox-Hastings 多項式)。poly≤0 (発散) は NaN。
    物理性の判定 (全域 FWHM>0=転写可能) に用いる純関数 (numpy)。
    """
    import numpy as np

    u, v, w, x, y = (float(values.get(k, 0.0)) for k in ("U", "V", "W", "X", "Y"))
    tt = np.clip(np.asarray(two_theta, dtype=float), _FWHM_TT_MIN, _FWHM_TT_MAX)
    th = np.radians(tt / 2.0)
    t, c = np.tan(th), np.cos(th)
    sig = np.sqrt(np.maximum(0.001, u * t * t + v * t + w))
    g = x / c + y * t
    a = 2.35482 * sig
    poly = (a**5 + 2.69269 * a**4 * g + 2.42843 * a**3 * g**2
            + 4.47163 * a**2 * g**3 + 0.07842 * a * g**4 + g**5)
    # poly≤0 (発散) は NaN。log は正値のみで評価する (非正の log 警告を避ける)。
    safe = np.where(poly > 0.0, poly, 1.0)
    return np.where(poly > 0.0, np.exp(np.log(safe) / 5.0) / 100.0, np.nan)


def profile_fwhm_min(
    values: Mapping[str, float], lo_deg: float = 5.0, hi_deg: float = 120.0, n: int = 64
) -> float:
    """総 FWHM のレンジ区間最小 [deg]。全域で有限かつ >0 なら転写可能。NaN があれば -inf (非物理)。"""
    import numpy as np

    fw = profile_total_fwhm(values, np.linspace(lo_deg, hi_deg, n))
    if np.any(np.isnan(fw)):
        return float("-inf")
    return float(np.min(fw))


def candidate_profiles(
    anchor: Mapping[str, float],
    *,
    x_factors=(0.6, 0.8, 1.0, 1.2, 1.4),
    w_factors=(0.7, 1.0, 1.3),
    y_offsets=(0.0,),
) -> list[dict[str, float]]:
    """アンカー周辺の候補プロファイル群を生成する (grid, numpy 不要)。

    X (Lorentzian 主成分) と W (Gaussian) を係数で、Y をオフセットで摂動。U,V,SH/L,Zero はアンカー据置。
    係数の直積順で決定論的。
    """
    base = dict(anchor)
    ax, aw, ay = (float(base.get(k, 0.0)) for k in ("X", "W", "Y"))
    out: list[dict[str, float]] = []
    for xf in x_factors:
        for wf in w_factors:
            for yo in y_offsets:
                cand = dict(base)
                cand["X"] = ax * xf
                cand["W"] = aw * wf
                cand["Y"] = ay + yo
                out.append(cand)
    return out


def search_instrument_profile(
    standard: HistogramSpec,
    structure: PhaseSpec,
    *,
    anchor: InstrumentProfile | None = None,
    candidates=None,
    fwhm_range: tuple[float, float] = (5.0, 120.0),
    refine_sh_l: bool = False,
    optimizer=None,
    runner=None,
) -> InstrumentProfile:
    """物理候補を探索し最良フィットの装置分解能を返す (境界クランプ回避, Issue #38 拡張)。

    自由精密化は初期値に依らず非物理解へ落ちる (大域アトラクタ) ため、素朴な初期値探索でなく
    **物理候補を固定評価**する。手順:
    (1) anchor 未指定 → `extract_instrument_profile(constrain_nonneg=True)` で物理アンカー。
    (2) candidates 未指定 → `candidate_profiles` (または注入 optimizer) でアンカー周辺候補。
    (3) 各候補: `profile_fwhm_min>0` の物理候補のみ、instrument_profile 固定 + recipe=[bg,cell] で評価→Rwp。
    (4) 物理候補のうち Rwp 最小を返す。1 つも無ければ anchor (安全網)。

    :param optimizer: 候補提案器 `anchor_values -> Sequence[Mapping]` (既定 grid)
    :param runner: 精密化関数 (既定 run_auto_rietveld; テストは stub 注入)
    """
    run = runner
    if run is None:
        from .engine import run_auto_rietveld  # 遅延 import (GSAS 隔離)

        run = run_auto_rietveld
    if anchor is None:
        anchor = extract_instrument_profile(
            standard, structure, runner=runner, refine_sh_l=refine_sh_l, constrain_nonneg=True
        )
    if not anchor.values:
        return anchor  # EDGE-002
    if candidates is None:
        candidates = (
            optimizer(dict(anchor.values)) if optimizer is not None
            else candidate_profiles(anchor.values)
        )

    lo, hi = fwhm_range
    # 固定した装置プロファイルの当てはまりを公平に測るため、試料広がり (size/mustrain) を解放する。
    # これが無いと固定プロファイル単独では観測幅 (装置⊗試料) に届かず Rwp が過大になる (CeO2 で 38% vs 9%)。
    eval_recipe = [
        RefinementStage("bg", flags={"background": {"coeffs": 12}}),
        RefinementStage("cell", flags={"cell": True}),
        RefinementStage("size", flags={"size_strain": True}),
    ]
    best: dict[str, float] | None = None
    best_rwp = float("inf")
    for cand in candidates:
        if profile_fwhm_min(cand, lo, hi) <= 0.0:
            continue  # 非物理 (総 FWHM 負) は除外 (REQ-102)
        hist = replace(standard, instrument_profile=InstrumentProfile(values=dict(cand)))
        try:
            res = run([hist], [structure], recipe=eval_recipe)
        except Exception:  # noqa: BLE001 — 評価失敗候補は除外し継続 (EDGE-001)
            continue
        rwp = res.final_rwp
        if math.isfinite(rwp) and rwp < best_rwp:
            best_rwp, best = rwp, dict(cand)
    if best is None:
        return anchor  # 物理候補なし → アンカー (REQ-103)
    return InstrumentProfile(values=best, source_rwp=best_rwp, wavelength=anchor.wavelength)
