"""M12 T4: 装置パラメータ + 観測データの TOPAS 向け変換 (純関数)。

GSAS の ``.instprm`` (新形式 ``Key:value``) と ``.PRM`` (旧形式 固定桁) を読み分け、
観測データは `reference.io.load_pattern` 経由で ``.xye`` へ落として入力形式差を TOPAS へ
持ち込まない。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation
from tsumugin.topas.instrument import (
    histogram_to_topas,
    read_instrument,
    tchz_line,
    write_xye,
)

_INSTPRM_XRAY = (
    "#GSAS-II instrument parameter file\n"
    "Type:PXC\nBank:1.0\nLam1:1.540500\nLam2:1.544300\nI(L2)/I(L1):0.5\n"
    "Zero:0.0125\nU:2.0\nV:-2.0\nW:5.0\nX:0.0\nY:0.5\n"
)
_INSTPRM_TOF = (
    "#GSAS-II instrument parameter file\n"
    "Type:PNT\ndifC:22600.25\ndifA:-1.5\nZero:-8.5\nsig-1:-167.4\n"
)
_PRM_XRAY = (
    "            123456789012345678901234567890\n"
    "INS   BANK      1\n"
    "INS   HTYPE   PXCR\n"
    "INS  1 ICONS  1.540500  1.544300       0.0         0       0.7    0       0.5\n"
)
_PRM_NEUTRON = (
    "INS   BANK      1\n"
    "INS   HTYPE   PNCR\n"
    "INS  1 ICONS  1.909000  0.000000       0.0         0       0.0    0       0.0\n"
)


# ---------------- .instprm ----------------


def test_instprm_xray_wavelengths_and_zero(tmp_path):
    path = tmp_path / "x.instprm"
    path.write_text(_INSTPRM_XRAY, encoding="utf-8")
    spec = read_instrument(path)
    assert spec.lam1 == pytest.approx(1.5405)
    assert spec.lam2 == pytest.approx(1.5443)
    assert spec.zero == pytest.approx(0.0125)
    assert not spec.is_tof and not spec.is_neutron


def test_instprm_keeps_the_gsas_profile_in_gsas_units(tmp_path):
    """読み取り段階では**GSAS の単位系のまま**保持する (換算は別関数の責務)。"""
    path = tmp_path / "x.instprm"
    path.write_text(_INSTPRM_XRAY, encoding="utf-8")
    assert read_instrument(path).profile == {"U": 2.0, "V": -2.0, "W": 5.0, "X": 0.0, "Y": 0.5}


def test_instprm_tof_maps_difc_difa_zero(tmp_path):
    """TOF は GSAS の difC/difA/Zero と TOPAS の TOF_x_axis_calibration が直写像。"""
    path = tmp_path / "t.instprm"
    path.write_text(_INSTPRM_TOF, encoding="utf-8")
    spec = read_instrument(path)
    assert spec.is_tof and spec.is_neutron
    assert (spec.difc, spec.difa, spec.tof_zero) == (
        pytest.approx(22600.25), pytest.approx(-1.5), pytest.approx(-8.5)
    )
    assert spec.zero == 0.0  # TOF では 2θ ゼロ点ではない


# ---------------- 旧 .PRM ----------------


def test_prm_reads_icons_wavelengths(tmp_path):
    path = tmp_path / "i.PRM"
    path.write_text(_PRM_XRAY, encoding="utf-8")
    spec = read_instrument(path)
    assert spec.lam1 == pytest.approx(1.5405)
    assert spec.lam2 == pytest.approx(1.5443)
    assert not spec.is_neutron


def test_prm_zero_second_wavelength_means_monochromatic(tmp_path):
    """λ2 = 0 は「Kα2 なし」であって「波長 0」ではない。"""
    path = tmp_path / "n.PRM"
    path.write_text(_PRM_NEUTRON, encoding="utf-8")
    spec = read_instrument(path)
    assert spec.lam1 == pytest.approx(1.909)
    assert spec.lam2 is None
    assert spec.is_neutron


# ---------------- .xye 書き出し ----------------


def test_write_xye_is_three_columns_with_counting_sigma(tmp_path):
    out = write_xye(tmp_path / "d.xye", np.array([10.0, 10.02]), np.array([100.0, 0.0]))
    rows = [line.split() for line in out.read_text().splitlines()]
    assert [len(r) for r in rows] == [3, 3]
    assert float(rows[0][2]) == pytest.approx(10.0)  # √100
    assert float(rows[1][2]) == pytest.approx(1.0)  # √max(y,1) — 0 計数で σ=0 にしない


def test_write_xye_is_deterministic(tmp_path):
    x, y = np.array([10.0, 20.0]), np.array([5.0, 7.0])
    a = write_xye(tmp_path / "a.xye", x, y).read_text()
    b = write_xye(tmp_path / "b.xye", x, y).read_text()
    assert a == b


# ---------------- HistogramSpec → TopasHistogram ----------------


def _xye_source(tmp_path):
    src = tmp_path / "src.xye"
    src.write_text("\n".join(f"{10 + 0.02 * i:.4f} {100 + i} 1.0" for i in range(50)), "utf-8")
    return src


def test_histogram_conversion_writes_data_and_builds_emission(tmp_path):
    prm = tmp_path / "i.instprm"
    prm.write_text(_INSTPRM_XRAY, encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    hist = histogram_to_topas(spec, workdir=tmp_path, index=0)
    assert hist.data_path == "hist0.xye"
    assert (tmp_path / "hist0.xye").is_file()
    joined = "\n".join(hist.preamble)
    assert "lam" in joined and "1.5405" in joined
    assert "1.5443" in joined  # Kα2 も出す
    assert "LP_Factor" in joined


def test_missing_wavelength_raises_rather_than_defaulting_to_cu(tmp_path):
    """**Cu Kα で埋めない** — 誤った波長はピーク位置をずらし格子がそれを吸収する。"""
    prm = tmp_path / "bad.instprm"
    prm.write_text("Type:PXC\nBank:1.0\n", encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    with pytest.raises(ValueError, match="波長"):
        histogram_to_topas(spec, workdir=tmp_path)


def test_neutron_omits_the_xray_polarisation_factor(tmp_path):
    prm = tmp_path / "n.PRM"
    prm.write_text(_PRM_NEUTRON, encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )
    hist = histogram_to_topas(spec, workdir=tmp_path)
    # 偏光項 (LP_Factor) は入れないが、Lorentz 因子は入れる (下の専用テスト)。
    assert not any("LP_Factor" in line for line in hist.preamble)
    assert hist.is_neutron


def test_range_and_exclusions_are_carried_through(tmp_path):
    prm = tmp_path / "i.instprm"
    prm.write_text(_INSTPRM_XRAY, encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
        two_theta_limits=(10.2, 10.8), excluded_regions=((10.4, 10.5),), weight=2.0,
    )
    hist = histogram_to_topas(spec, workdir=tmp_path)
    assert hist.two_theta_limits == (10.2, 10.8)
    assert hist.excluded_regions == ((10.4, 10.5),)
    assert hist.weight == 2.0


# ---------------- TCHZ 行 ----------------


def test_tchz_defaults_are_frozen():
    """解放は段階フラグの責務。初期状態では全部 `!` 付き。"""
    line = tchz_line(0)
    assert line.startswith("TCHZ_Peak_Type(")
    assert line.count("!pk") == 6


def test_tchz_names_include_the_phase_so_they_do_not_collide():
    """**TOPAS のパラメータ名は大域** — 多相で同名を複数の str に宣言すると衝突する。"""
    a = tchz_line(0, phase_key="alpha")
    b = tchz_line(0, phase_key="beta")
    assert "pku0_alpha" in a and "pku0_beta" in b
    assert a != b


def test_tchz_without_phase_key_keeps_the_plain_name():
    assert "!pku0," in tchz_line(0)


def test_tchz_seed_is_in_topas_space_not_gsas_space():
    """**種は TOPAS の単位系で渡す** — GSAS 値をそのまま入れる口は塞ぐ。

    GSAS の U,V,W はガウス**分散**をセンチ度²で表す係数、TOPAS の u,v,w はガウス
    **FWHM²** を度² で表す係数。素通しすると幅が 4 桁ずれたまま「収束」する。
    換算は `gsas_cw_profile_to_tchz` の責務 (下)。
    """
    line = tchz_line(0, {"w": 0.3613, "y": 0.06})
    assert "0.3613" in line and "0.06" in line


# ---------------- GSAS の CW プロファイル → TCHZ ----------------


def test_gaussian_coefficients_convert_variance_centidegrees_to_fwhm_degrees():
    """``σ²[cdeg²] → FWHM²[deg²]`` は ``× 8ln2/10⁴``。

    GSAS-II ``getCWsig``: ``σ² = U tan²θ + V tanθ + W`` (センチ度²)。
    TOPAS ``TCHZ_Peak_Type``: ``FWHM_G² = u tan²θ + v tanθ + w + z/cos²θ`` (度²)。
    ``FWHM = √(8ln2)·σ`` かつ センチ度 → 度 が ``/100`` なので係数は ``8ln2/10⁴``。
    """
    from tsumugin.topas.instrument import GSAS_SIGMA_TO_TCHZ, gsas_cw_profile_to_tchz

    assert GSAS_SIGMA_TO_TCHZ == pytest.approx(8.0 * math.log(2.0) / 1.0e4)
    # 実 D1A (ILL 中性子): GU/GV/GW = 354.031 / -760.404 / 651.592
    seed = gsas_cw_profile_to_tchz({"U": 354.031, "V": -760.404, "W": 651.592})
    assert seed["w"] == pytest.approx(0.361319, abs=1e-6)
    # 2θ=90° での FWHM が D1A の実分解能 (~0.37°) になること。
    fwhm = math.sqrt(seed["u"] + seed["v"] + seed["w"])
    assert 0.30 < fwhm < 0.45


def test_lorentzian_coefficients_swap_names_between_the_two_engines():
    """**X と Y は入れ替わる**。GSAS は ``X/cosθ + Y·tanθ``、TOPAS は ``x·tanθ + y/cosθ``。

    名前が同じで意味が違うので、素直に写すと size 由来と歪み由来が入れ替わったまま
    「収束」する。単位はどちらも FWHM なのでセンチ度→度の ``/100`` だけ。
    """
    from tsumugin.topas.instrument import gsas_cw_profile_to_tchz

    seed = gsas_cw_profile_to_tchz({"X": 1.5, "Y": 2.5})
    assert seed["y"] == pytest.approx(0.015)  # GSAS X (1/cosθ 項) → TOPAS y
    assert seed["x"] == pytest.approx(0.025)  # GSAS Y (tanθ 項)   → TOPAS x


def test_gsas_z_is_not_mapped_to_the_topas_z():
    """**同名だが別物**: GSAS の Z はローレンツ幅の定数項、TOPAS の z はガウスの 1/cos²θ 項。"""
    from tsumugin.topas.instrument import gsas_cw_profile_to_tchz

    assert gsas_cw_profile_to_tchz({"Z": 5.0}).get("z", 0.0) == 0.0


def test_missing_coefficients_are_simply_absent():
    """装置ファイルに無い係数は種にしない (0 を積極的に置かない)。"""
    from tsumugin.topas.instrument import gsas_cw_profile_to_tchz

    assert set(gsas_cw_profile_to_tchz({"W": 651.592})) == {"w"}


def test_tof_profile_is_not_seeded_through_the_cw_route():
    """TOF は Caglioti でない — CW 用の換算を当てない。"""
    from tsumugin.topas.instrument import gsas_cw_profile_to_tchz

    assert gsas_cw_profile_to_tchz({"sig-1": -167.4, "difC": 22600.0}) == {}


# ---------------- 旧 .PRM のプロファイル係数 ----------------

_PRM_NEUTRON_PRCF = _PRM_NEUTRON + (
    "INS  1PRCF1     1    6      0.01\n"
    "INS  1PRCF11   0.354031E+03  -0.760404E+03   0.651592E+03   0.000000E+00\n"
    "INS  1PRCF12   0.000000E+00   0.000000E+00   0.000000E+00   0.000000E+00\n"
)
_PRM_XRAY_PRCF3 = _PRM_XRAY + (
    "INS  1PRCF1     3    8      0.01\n"
    "INS  1PRCF11   2.000000E+00  -2.000000E+00   5.000000E+00   0.100000E+00\n"
    "INS  1PRCF12   0.000000E+00   0.000000E+00   0.150000E-01   0.150000E-01\n"
)


def test_prm_reads_gaussian_coefficients_from_prcf11(tmp_path):
    """``INS  1PRCF11`` の先頭 3 つが GU/GV/GW (GSAS-II ``GSASIIfiles`` 準拠)。"""
    path = tmp_path / "n.PRM"
    path.write_text(_PRM_NEUTRON_PRCF, encoding="utf-8")
    profile = read_instrument(path).profile or {}
    assert profile["U"] == pytest.approx(354.031)
    assert profile["V"] == pytest.approx(-760.404)
    assert profile["W"] == pytest.approx(651.592)


def test_prm_lorentzian_coefficients_only_count_for_profile_type_3(tmp_path):
    """**``PRCF12`` を LX/LY と読んでよいのは型 3 のときだけ** (GSAS-II と同じ規律)。

    型 1 の ``PRCF12`` は別物 (D1A のファイルは 0 だが、0 でない装置で取り違えると
    ローレンツ幅を捏造することになる)。
    """
    neutron = tmp_path / "n.PRM"
    neutron.write_text(_PRM_NEUTRON_PRCF, encoding="utf-8")
    assert "X" not in (read_instrument(neutron).profile or {})

    xray = tmp_path / "x.PRM"
    xray.write_text(_PRM_XRAY_PRCF3, encoding="utf-8")
    profile = read_instrument(xray).profile or {}
    assert profile["X"] == pytest.approx(0.0)
    assert profile["Y"] == pytest.approx(0.0)
    assert profile["SH/L"] == pytest.approx(0.03)  # S + H


def test_prm_without_prcf_has_no_profile(tmp_path):
    path = tmp_path / "bare.PRM"
    path.write_text(_PRM_XRAY, encoding="utf-8")
    assert read_instrument(path).profile is None


# ---------------- 種付けの既定 ----------------


def _neutron_spec(tmp_path):
    prm = tmp_path / "n.PRM"
    prm.write_text(_PRM_NEUTRON_PRCF, encoding="utf-8")
    return HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )


def test_seeding_is_opt_in(tmp_path):
    """**既定では種付けしない**。

    TCHZ マクロの箱は ``Val`` を毎回評価する**移動する**箱なので、汎用初期値からでも
    十分遠くまで歩ける (実 garnet で w 0.003 → 0.143)。一方 GSAS 同梱の装置ファイルは
    "DUMMY" と自称する公称値のことがあり、実 D1A では較正値 w=0.361 が実データの好む
    0.143 の 2.5 倍だった。そこから始めると移動箱が届かず**種付けの方が悪くなる**
    (garnet 12.3% → 14.9%)。較正済みの実装置ファイルを持つ側が明示的に有効化する。
    """
    assert histogram_to_topas(_neutron_spec(tmp_path), workdir=tmp_path).profile_seed is None


def test_seeding_when_asked_carries_the_converted_values(tmp_path):
    hist = histogram_to_topas(_neutron_spec(tmp_path), workdir=tmp_path, seed_profile=True)
    assert hist.profile_seed is not None
    assert hist.profile_seed["w"] == pytest.approx(0.361319, abs=1e-6)


# ---------------- ゼロ点の箱 (#172 garnet) ----------------


def test_zero_point_is_written_with_an_explicit_box(tmp_path):
    """**ゼロ点は明示的に束縛する** — TOPAS 内蔵の箱 (±100 ステップ) は緩すぎる。

    実 garnet (CW 中性子, ステップ 0.05° → 内蔵の箱は ±5°) では格子解放段でゼロ点が
    **+1.16° まで暴走**し Rwp 18.5 → 51.3。1° を超える 2θ ゼロ点は「ゼロ点」ではなく
    波長か指数付けの誤りであって**数値的事故であり情報ではない** (GSAS 経路の
    `bounds.displacement_box_bounds` と同じ論法)。

    実測: 箱 ±0.1/±0.2/±0.5 はいずれも同じ解 (ze=−0.0406°, Rwp 19.384) に収束し、
    ±1.0 だけが暴走側の谷 (0.994 で上限に張り付き Rwp 51.3) に落ちる。
    """
    from tsumugin.topas.instrument import ZERO_POINT_LIMIT_DEG

    prm = tmp_path / "i.instprm"
    prm.write_text(_INSTPRM_XRAY, encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    joined = "\n".join(histogram_to_topas(spec, workdir=tmp_path).preamble)
    assert "th2_offset = ze0;" in joined
    assert f"min {0.0125 - ZERO_POINT_LIMIT_DEG!r}" in joined  # 装置の宣言値が箱の中心
    assert f"max {0.0125 + ZERO_POINT_LIMIT_DEG!r}" in joined
    assert "prm !ze0" in joined  # 解放は段階フラグの責務


def test_zero_lorentzian_coefficients_are_not_seeded(tmp_path):
    """``LX = LY = 0`` は「測って 0 だった」ではなく**情報が無い**。

    GSAS が配る DUMMY 装置ファイルはローレンツ項を 0 で埋めている。これを種にすると
    ピークが純ガウスの初期形になり、既定値 (y=0.03) から始めるより悪くなる
    (実 fluoroapatite で初期段 45.4 → 54.2)。
    """
    from tsumugin.topas.instrument import gsas_cw_profile_to_tchz

    seed = gsas_cw_profile_to_tchz({"U": 2.0, "V": -2.0, "W": 5.0, "X": 0.0, "Y": 0.0})
    assert set(seed) == {"u", "v", "w"}
    # 非ゼロなら種にする。
    assert "y" in gsas_cw_profile_to_tchz({"X": 1.5})


# ---------------- Lorentz 因子 (#174) ----------------


def test_cw_neutron_gets_the_lorentz_factor(tmp_path):
    """**CW 中性子にも Lorentz 因子が要る** — 偏光因子が無いだけで L は X 線と同じ。

    ``1/(sin²θ·cosθ)`` は 2θ=24° と 158° で 2 桁変わる。落とすと**ピーク位置は合うのに
    強度の 2θ 依存が系統的にずれ**、Rwp が 3 倍近く悪いところで頭打ちになる
    (実 garnet 12.3% 対 GSAS 4.33%、実 PbSO4 joint の中性子側 14.4%)。
    TOPAS の Tutorial (Magnetic Refinement/lamno3.inp) は ``LP_Factor(90)`` = 偏光項が
    消える角度、で同じ式を作っている。
    """
    hist = histogram_to_topas(_neutron_spec(tmp_path), workdir=tmp_path)
    joined = "\n".join(hist.preamble)
    assert "Lorentz_Factor" in joined
    assert "LP_Factor(" not in joined  # X 線の偏光項は入れない


def test_xray_keeps_the_polarised_lp_factor(tmp_path):
    prm = tmp_path / "i.instprm"
    prm.write_text(_INSTPRM_XRAY, encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    joined = "\n".join(histogram_to_topas(spec, workdir=tmp_path).preamble)
    assert "LP_Factor(26.4)" in joined and "Lorentz_Factor" not in joined


# ---------------- TOF (#174) ----------------


def _tof_spec(tmp_path):
    prm = tmp_path / "t.instprm"
    prm.write_text(_INSTPRM_TOF, encoding="utf-8")
    src = tmp_path / "t.xye"
    src.write_text("\n".join(f"{20000 + 10 * i}.0 {100 + i} 1.0" for i in range(50)), "utf-8")
    return HistogramSpec(
        data_path=str(src), instrument_path=str(prm),
        radiation=Radiation.NEUTRON_TOF, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )


def test_tof_gets_the_d_fourth_lorentz_factor(tmp_path):
    """**TOF の Lorentz 因子は ``d⁴``**。CW の 1/(sin²θcosθ) とは別式。

    固定検出器角なので sinθ は定数に吸収され、残るのが ``D_spacing^4``。落とすと長 d 側の
    強度が系統的に足りなくなる (CW 中性子で Lorentz を落としていたのと同じ病理)。
    TOPAS Tutorial (Tof Neutron Data/ZrW2O8.inp) が同じ式を書いている。
    """
    hist = histogram_to_topas(_tof_spec(tmp_path), workdir=tmp_path)
    joined = "\n".join(hist.preamble)
    assert "scale_pks = D_spacing^4;" in joined
    assert "Lorentz_Factor" not in joined and "LP_Factor" not in joined


def test_tof_declares_a_flat_emission_profile(tmp_path):
    """白色ビームなので単色の ``lam`` ではなく ``TOF_LAM``。"""
    assert any("TOF_LAM" in x for x in histogram_to_topas(_tof_spec(tmp_path), workdir=tmp_path).preamble)


def test_tof_peak_width_is_seeded_from_a_relative_resolution(tmp_path):
    """初期ピーク幅は **Δd/d × difC** で置く。

    GSAS の sig-1/sig-2 は**分散**の d² / d⁴ 係数、TOPAS は **FWHM** の d / d² 係数で
    関数形が違う (√の中の和 対 和) 上、実 POWGEN の sig-1 は**負**なので平方根が取れない。
    素直な写像が存在しないので、物理的に意味のある量 (相対分解能) から置き直す。
    """
    from tsumugin.topas.instrument import TOF_RELATIVE_RESOLUTION, tof_peak_type

    text = tof_peak_type(0, difc=22600.25, phase_key="NAC")
    assert "peak_type pv" in text and "D_spacing^2" in text
    assert f"{22600.25 * TOF_RELATIVE_RESOLUTION!r}" in text
    assert "!tofw10_NAC" in text and "!tofw20_NAC" in text  # 既定は凍結


def test_tof_peak_width_names_are_unique_per_phase(tmp_path):
    from tsumugin.topas.instrument import tof_peak_type

    assert tof_peak_type(0, difc=1.0, phase_key="a") != tof_peak_type(0, difc=1.0, phase_key="b")


def test_tof_calculation_step_is_the_minimum_bin_width(tmp_path):
    """**TOF の計算格子は定数**でなければならない。

    ``x_calculation_step = Yobs_dx_at(Xo);`` のような適応式は、計算ピークがデータ範囲の外へ
    出た瞬間に ``x_calculation_step too small or not defined`` で異常終了する (実測: 実
    POWGEN の 3 本目)。SLOG ビンは幅が t に比例するので、**最小**幅を採る — 中央値だと
    FWHM あたり 1 点しか置けず形状が粗くなる。
    """
    prm = tmp_path / "t.instprm"
    prm.write_text(_INSTPRM_TOF, encoding="utf-8")
    src = tmp_path / "t.xye"
    # 3, 5, 9 µs と広がるビン (SLOG を模す)。
    src.write_text("20000.0 1 1\n20003.0 1 1\n20008.0 1 1\n20017.0 1 1\n", "utf-8")
    spec = HistogramSpec(
        data_path=str(src), instrument_path=str(prm),
        radiation=Radiation.NEUTRON_TOF, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )
    assert histogram_to_topas(spec, workdir=tmp_path).calculation_step == pytest.approx(3.0)


def test_synchrotron_uses_the_lorentz_factor_only(tmp_path):
    """**放射光に管球用の偏光項を当てない**。

    散乱面内でほぼ完全偏光しているので偏光因子は ~1。topas.inc の
    ``LP_Factor_Synchrotron_Simple`` は実体が ``Lorentz_Factor`` だけである。
    ``LP_Factor(26.4)`` (グラファイトモノクロメータ) を当てると強度の 2θ 依存が系統的に狂う。
    """
    prm = tmp_path / "i.instprm"
    prm.write_text(_INSTPRM_XRAY, encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.XRAY_SYNCHROTRON, geometry=Geometry.DEBYE_SCHERRER,
        data_format="XYE",
    )
    joined = "\n".join(histogram_to_topas(spec, workdir=tmp_path).preamble)
    assert "Lorentz_Factor" in joined and "LP_Factor(" not in joined


def test_zero_point_derivative_step_matches_the_ze_macro(tmp_path):
    """``del`` は ``ZE`` マクロの中身をそのまま写す — **``X1`` であって ``Xo`` ではない**。

    topas.inc の ZE は ``del = .01 Yobs_dx_at(X1);`` (データ範囲の左端での刻み)。TOF の
    ``x_calculation_step`` で使う ``Yobs_dx_at(Xo)`` とは**別物**なので、字面が揃わないのは
    意図的である。既定に任せると数値微分が変わって収束先がわずかにずれる。
    """
    prm = tmp_path / "i.instprm"
    prm.write_text(_INSTPRM_XRAY, encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    joined = "\n".join(histogram_to_topas(spec, workdir=tmp_path).preamble)
    assert "del = .01 Yobs_dx_at(X1);" in joined
    assert "Yobs_dx_at(Xo)" not in joined
