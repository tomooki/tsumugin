"""M6 相同定 公開面 e2e (トップレベル __all__ への昇順追記 + 実体同一 + 解決性)。

`test_m5_e2e.py` の手本に倣い、M6 (reference コア + mp 境界) のトップレベル公開が
昇順維持・後方互換・実体同一・コア numpy-only を満たすことを検証する。
"""

from __future__ import annotations

import importlib.util

import tsumugin
from tsumugin import (
    CODProvider,
    CachedReferenceProvider,
    DaraScore,
    ICSDProvider,
    MPEntry,
    MPReferenceProvider,
    MPRestClient,
    MPUnavailableError,
    PhaseIdentification,
    PhaseMatch,
    PhaseMatchGroup,
    ReferencePhase,
    ReferenceProvider,
    KAlpha2,
    LatticeAlignment,
    UserCIFProvider,
    add_kalpha2_satellites,
    align_peaks,
    dara_peak_score,
    estimate_snip_background,
    group_by_composition,
    identify_phase_mixtures,
    identify_phases,
    load_gsas_powder,
    load_xy,
    subtract_background,
)

_M6_PROMOTED_SYMBOLS = frozenset(
    {
        "CODProvider",
        "CachedReferenceProvider",
        "DaraScore",
        "ICSDProvider",
        "MPEntry",
        "MPReferenceProvider",
        "MPRestClient",
        "MPUnavailableError",
        "PhaseIdentification",
        "PhaseMatch",
        "PhaseMatchGroup",
        "ReferencePhase",
        "ReferenceProvider",
        "UserCIFProvider",
        "KAlpha2",
        "LatticeAlignment",
        "add_kalpha2_satellites",
        "align_peaks",
        "dara_peak_score",
        "estimate_snip_background",
        "group_by_composition",
        "identify_phase_mixtures",
        "identify_phases",
        "inflection_threshold",
        "load_gsas_powder",
        "load_xy",
        "subtract_background",
    }
)


def test_m6_symbols_in_dunder_all_and_sorted():
    exported = set(tsumugin.__all__)
    assert _M6_PROMOTED_SYMBOLS <= exported  # M6 シンボルが __all__ に包含
    assert list(tsumugin.__all__) == sorted(tsumugin.__all__)  # 完全昇順維持
    # M5/M4 の代表シンボルが 1 つも削除されていない (後方互換)。
    for prior in ("arbitrate", "propose_measurements", "AnalysisSession", "verify_survivors"):
        assert prior in exported
    # mp 側の実処理関数はトップレベル __all__ に載せない (mcp の 8 ツールと同じ方針)。
    for pkg_only in ("simulate_reference_peaks", "group_equivalent"):
        assert pkg_only not in exported


def test_m6_reexports_are_same_object():
    import tsumugin.mp
    import tsumugin.reference

    assert identify_phases is tsumugin.reference.identify_phases
    assert ReferencePhase is tsumugin.reference.ReferencePhase
    assert PhaseMatch is tsumugin.reference.PhaseMatch
    assert PhaseIdentification is tsumugin.reference.PhaseIdentification
    assert ReferenceProvider is tsumugin.reference.ReferenceProvider
    assert MPReferenceProvider is tsumugin.mp.MPReferenceProvider
    assert MPRestClient is tsumugin.mp.MPRestClient
    assert MPEntry is tsumugin.mp.MPEntry
    assert MPUnavailableError is tsumugin.errors.MPUnavailableError
    assert identify_phase_mixtures is tsumugin.reference.identify_phase_mixtures
    assert UserCIFProvider is tsumugin.reference.UserCIFProvider
    assert CODProvider is tsumugin.reference.CODProvider
    assert ICSDProvider is tsumugin.reference.ICSDProvider
    assert CachedReferenceProvider is tsumugin.reference.CachedReferenceProvider
    assert DaraScore is tsumugin.reference.DaraScore
    assert dara_peak_score is tsumugin.reference.dara_peak_score
    assert align_peaks is tsumugin.reference.align_peaks
    assert LatticeAlignment is tsumugin.reference.LatticeAlignment
    assert group_by_composition is tsumugin.reference.group_by_composition
    assert PhaseMatchGroup is tsumugin.reference.PhaseMatchGroup
    assert load_xy is tsumugin.reference.load_xy
    assert load_gsas_powder is tsumugin.reference.load_gsas_powder
    assert subtract_background is tsumugin.reference.subtract_background
    assert estimate_snip_background is tsumugin.reference.estimate_snip_background
    assert KAlpha2 is tsumugin.reference.KAlpha2
    assert add_kalpha2_satellites is tsumugin.reference.add_kalpha2_satellites


def test_m6_dunder_all_names_all_resolvable():
    for name in tsumugin.__all__:
        assert hasattr(tsumugin, name)


def test_m6_core_imports_numpy_only():
    import sys

    # pymatgen / mp_api が未導入なら、コア import で sys.modules に載らないこと。
    for optional in ("pymatgen", "mp_api"):
        if importlib.util.find_spec(optional) is None:
            assert optional not in sys.modules
    assert callable(identify_phases)
