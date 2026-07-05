"""M6 TASK-0109 GSAS-II チュートリアル実測データでの相同定検証 (統合テスト)。

GSAS-II tutorial "Running a GSAS-II Refinement from the Command Line" の PbSO4 実測 CuKα
粉末パターン (``PBSO4.XRA``) + 構造 CIF (``PbSO4-Wyckoff.cif``) を用い、実データ (背景・ノイズ・
Kα2 を含む) 上で相同定パイプラインが機能することを検証する。

データは ``docs/benchmark/testdata/`` (gitignore 対象) に配置する。取得方法は
``docs/benchmark/README.md`` を参照。データ不在時 / pymatgen 未導入時は自動 skip する。
"""

from __future__ import annotations

import pathlib

import pytest

_DATA = pathlib.Path(__file__).resolve().parents[2] / "docs" / "benchmark" / "testdata"
_XRA = _DATA / "PBSO4.XRA"
_CIF = _DATA / "PbSO4-Wyckoff.cif"
_HAS_DATA = _XRA.exists() and _CIF.exists()

pytestmark = pytest.mark.skipif(
    not _HAS_DATA, reason="GSAS-II tutorial PbSO4 データ未配置 (docs/benchmark/README.md 参照)"
)

_CU_KA1 = 1.5405


def test_load_real_pbso4_pattern():
    from tsumugin.reference.io import load_gsas_powder

    two_theta, intensity = load_gsas_powder(_XRA)
    assert two_theta.size == 6001
    assert two_theta[0] == pytest.approx(10.0)
    assert two_theta[-1] == pytest.approx(160.0)
    assert intensity.max() > intensity.min() > 0  # 実測強度 (背景 + ピーク)


@pytest.mark.mp
def test_identify_pbso4_from_real_cuka_pattern():
    # 実測 CuKα パターン + PbSO4 CIF → 相同定が PbSO4 を最良マッチにする (実 pymatgen XRD)
    from tsumugin.reference import UserCIFProvider, identify_phases
    from tsumugin.reference.io import load_gsas_powder

    two_theta, intensity = load_gsas_powder(_XRA)
    cif = _CIF.read_text(encoding="utf-8")
    provider = UserCIFProvider(
        [cif], wavelength_angstrom=_CU_KA1, two_theta_range=(10.0, 160.0)
    )
    refs = provider.fetch(["Pb", "S", "O"])
    assert refs[0].formula == "PbSO4"
    assert refs[0].spacegroup == "Pnma"
    assert len(refs[0].peaks) > 50  # 実構造から多数の反射

    result = identify_phases(two_theta, intensity, provider, elements=["Pb", "S", "O"])
    assert result.matches[0].reference.formula == "PbSO4"
    # 実データ (背景・Kα2 未処理) でもピーク位置一致でスコアが立つ
    assert result.matches[0].score > 0.3
    assert len(result.observed_peaks) > 20


@pytest.mark.mp
def test_kalpha2_resolves_unknown_phase_flag_on_real_data():
    # Kα2 サテライトモデルが実測 PbSO4 の二重線を説明し、単相サンプルの未知相誤検出を解消する
    from tsumugin.reference import KAlpha2, UserCIFProvider, identify_phases
    from tsumugin.reference.io import load_gsas_powder

    two_theta, intensity = load_gsas_powder(_XRA)
    provider = UserCIFProvider(
        [_CIF.read_text(encoding="utf-8")],
        wavelength_angstrom=_CU_KA1,
        two_theta_range=(10.0, 160.0),
    )
    base = identify_phases(two_theta, intensity, provider, elements=["Pb", "S", "O"])
    with_ka2 = identify_phases(
        two_theta, intensity, provider, elements=["Pb", "S", "O"], kalpha2=KAlpha2()
    )
    # baseline は Kα2 二重線を説明できず未マッチ観測が残る
    assert len(base.unmatched.unmatched_observed) > 0
    assert base.unmatched.unknown_phase_flag is True
    # Kα2 モデルで未マッチが減り、単相サンプルの未知相フラグが解消する
    assert len(with_ka2.unmatched.unmatched_observed) < len(base.unmatched.unmatched_observed)
    assert with_ka2.unmatched.unknown_phase_flag is False


@pytest.mark.mp
def test_background_subtraction_reduces_spurious_peaks_on_real_data():
    from tsumugin.reference import UserCIFProvider, identify_phases
    from tsumugin.reference.io import load_gsas_powder

    two_theta, intensity = load_gsas_powder(_XRA)
    provider = UserCIFProvider(
        [_CIF.read_text(encoding="utf-8")],
        wavelength_angstrom=_CU_KA1,
        two_theta_range=(10.0, 160.0),
    )
    base = identify_phases(two_theta, intensity, provider, elements=["Pb", "S", "O"])
    with_bg = identify_phases(
        two_theta, intensity, provider, elements=["Pb", "S", "O"], subtract_bg=True
    )
    # 背景減算で背景に乗った弱い偽ピークが減り、最良マッチは PbSO4 のまま
    assert len(with_bg.observed_peaks) <= len(base.observed_peaks)
    assert with_bg.matches[0].reference.formula == "PbSO4"


@pytest.mark.mp
def test_identify_phase_mixtures_on_real_pattern_returns_result():
    from tsumugin.reference import UserCIFProvider, identify_phase_mixtures
    from tsumugin.reference.io import load_gsas_powder

    two_theta, intensity = load_gsas_powder(_XRA)
    cif = _CIF.read_text(encoding="utf-8")
    provider = UserCIFProvider(
        [cif], wavelength_angstrom=_CU_KA1, two_theta_range=(10.0, 160.0)
    )
    result = identify_phase_mixtures(two_theta, intensity, provider, elements=["Pb", "S", "O"])
    assert result.ranked  # 単相でも仮説が返る
    top_ids = [p.phase_ref for p in result.ranked[0].hypothesis.phases]
    assert len(top_ids) >= 1
