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

# Jana2020 Cookbook CandAt (Calcite + Aragonite 二相混合, 簡易シミュレーション X線)
_JANA = _DATA / "jana"
_CANDAT_XY = _JANA / "CandAt.xy"
_CALCITE_CIF = _JANA / "calcite.cif"
_ARAGONITE_CIF = _JANA / "aragonite_mp-4626.cif"
_HAS_JANA = _CANDAT_XY.exists() and _CALCITE_CIF.exists() and _ARAGONITE_CIF.exists()

# 全 MP Ca-C-O 候補 (169 相) を FR-105 キャッシュに保存したもの (element-only 同定の再現用)
_MP_CACHE = _JANA / "mpcache" / "CuKa1_CandAt__C-Ca-O.json"
_HAS_MP_CACHE = _CANDAT_XY.exists() and _MP_CACHE.exists()

pytestmark = pytest.mark.skipif(
    not _HAS_DATA, reason="GSAS-II tutorial PbSO4 データ未配置 (docs/benchmark/README.md 参照)"
)

_CU_KA1 = 1.5405
_JANA_WL = 1.54059


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


# ---------------------------------------------------------------------------
# Jana2020 Cookbook CandAt — Calcite + Aragonite 二相混合の多相同定
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_JANA, reason="Jana2020 CandAt データ未配置 (docs/benchmark/README.md 参照)")
def test_load_candat_xy():
    from tsumugin.reference.io import load_xy

    two_theta, intensity = load_xy(_CANDAT_XY)
    assert two_theta.size > 7000
    assert two_theta[0] == pytest.approx(10.005, abs=0.01)
    assert intensity.max() > intensity.min() > 0


@pytest.mark.mp
@pytest.mark.skipif(not _HAS_JANA, reason="Jana2020 CandAt データ未配置 (docs/benchmark/README.md 参照)")
def test_background_subtraction_cleans_simulated_noise():
    # CandAt 簡易シミュレーションは構造化ベースラインで偽ピークが多数 → 背景減算で激減する
    from tsumugin.reference import UserCIFProvider, identify_phases
    from tsumugin.reference.io import load_xy

    two_theta, intensity = load_xy(_CANDAT_XY)
    provider = UserCIFProvider(
        [_CALCITE_CIF.read_text(encoding="utf-8")],
        wavelength_angstrom=_JANA_WL,
        two_theta_range=(10.0, 120.0),
    )
    base = identify_phases(two_theta, intensity, provider, elements=["Ca", "C", "O"])
    with_bg = identify_phases(
        two_theta, intensity, provider, elements=["Ca", "C", "O"], subtract_bg=True
    )
    # 背景減算で観測ピークが大幅に減る (ノイズ由来の偽ピーク除去)
    assert len(with_bg.observed_peaks) < 0.5 * len(base.observed_peaks)


@pytest.mark.mp
@pytest.mark.skipif(not _HAS_JANA, reason="Jana2020 CandAt データ未配置 (docs/benchmark/README.md 参照)")
def test_identify_calcite_aragonite_mixture():
    # Calcite + Aragonite (CaCO3 の 2 多形) 混合を多相同定で検出する (背景減算必須)
    from tsumugin.reference import UserCIFProvider, identify_phase_mixtures
    from tsumugin.reference.io import load_xy
    from tsumugin.search.tree import SearchConfig

    two_theta, intensity = load_xy(_CANDAT_XY)
    provider = UserCIFProvider(
        [_CALCITE_CIF.read_text(encoding="utf-8"), _ARAGONITE_CIF.read_text(encoding="utf-8")],
        wavelength_angstrom=_JANA_WL,
        two_theta_range=(10.0, 120.0),
    )
    result = identify_phase_mixtures(
        two_theta,
        intensity,
        provider,
        elements=["Ca", "C", "O"],
        subtract_bg=True,
        config=SearchConfig(max_phases=2),
    )
    assert result.ranked
    best = result.ranked[0].hypothesis
    # 最良仮説は 2 相 (calcite + aragonite) を含み、単相より Rwp が良い
    assert len(best.phases) == 2
    refs_in_best = {p.phase_ref for p in best.phases}
    assert len(refs_in_best) == 2  # 2 つの異なる相 (2 多形)
    # 2 相仮説が単相仮説より良い (混合を正しく検出)
    single_hyps = [rk for rk in result.ranked if len(rk.hypothesis.phases) == 1]
    if single_hyps:
        assert best.metrics.rwp <= single_hyps[0].hypothesis.metrics.rwp


@pytest.mark.skipif(not _HAS_MP_CACHE, reason="MP Ca-C-O キャッシュ未配置 (docs/benchmark/README.md 参照)")
def test_element_only_multiphase_from_full_mp_candidates():
    # 本題: Ca,C,O の元素情報のみから、全 MP 候補 (169 相) を経て calcite+aragonite を同定する。
    # キャッシュ済み実データ利用でネットワーク/pymatgen 不要のオフライン再現テスト。
    import json

    from tsumugin.reference import identify_phase_mixtures, reference_phase_from_dict
    from tsumugin.reference.io import load_xy
    from tsumugin.search.tree import SearchConfig

    two_theta, intensity = load_xy(_CANDAT_XY)
    data = json.loads(_MP_CACHE.read_text(encoding="utf-8"))
    refs = tuple(reference_phase_from_dict(d) for d in data["phases"])
    assert len(refs) > 100  # 全 MP Ca-C-O 候補

    class _CachedProvider:
        def fetch(self, elements):
            return refs

    lookup = {r.phase_id: r for r in refs}
    result = identify_phase_mixtures(
        two_theta,
        intensity,
        _CachedProvider(),
        elements=["Ca", "C", "O"],
        hull_cutoff_ev=0.15,
        subtract_bg=True,       # 簡易シミュレーションの構造化背景を除去
        prefilter_top_k=8,      # Dara スコアで無関係相 (炭素等) を除外
        config=SearchConfig(max_phases=2),
    )
    assert result.ranked
    best = result.ranked[0].hypothesis
    # 最良仮説は 2 相で、両方 CaCO3 (calcite R-3c + aragonite Pnma)
    assert len(best.phases) == 2
    formulas = {lookup[p.phase_ref].formula for p in best.phases}
    spacegroups = {lookup[p.phase_ref].spacegroup for p in best.phases}
    assert formulas == {"CaCO3"}
    assert spacegroups == {"R-3c", "Pnma"}  # calcite + aragonite の 2 多形
