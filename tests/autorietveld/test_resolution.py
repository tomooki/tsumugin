"""build_resolution_recipe + extract_instrument_profile (TASK-0002) の決定論テスト。

抽出は runner 注入で GSAS 非依存。実 CeO2 抽出は test_resolution_gsas.py (gated)。
"""

from __future__ import annotations

from dataclasses import replace as dataclasses_replace

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.autorietveld.resolution import (
    NONNEG_PROFILE_BOUNDS,
    build_resolution_recipe,
    extract_instrument_profile,
)


def _standard():
    return HistogramSpec("ceo2.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")


def _structure():
    return PhaseSpec("ceo2.cif", "CeO2", format_hint="CIF")


# --- build_resolution_recipe ---

def test_recipe_stage_flags_and_order():
    r = build_resolution_recipe()
    flags = [dict(s.flags) for s in r]
    # 背景 → cell → W → U,V,W,Zero → U,V,W,X,Y,Zero 同時 → +SH/L (段階的解放)
    assert "background" in flags[0]
    assert flags[1] == {"cell": True}
    assert flags[2] == {"profile": ["W"]}
    assert flags[3] == {"profile": ["U", "V", "W", "Zero"]}
    assert flags[4] == {"profile": ["U", "V", "W", "X", "Y", "Zero"]}
    assert flags[5] == {"profile": ["U", "V", "W", "X", "Y", "Zero", "SH/L"]}
    assert len(r) == 6


def test_recipe_no_size_strain_anywhere():
    # 標準は試料広がりが無い → size/mustrain を解放しない (負局所解回避)
    for s in build_resolution_recipe():
        assert "size_strain" not in s.flags


def test_recipe_releases_uvw_and_xy_together():
    # 相関局所解の脱出には U,V,W と X,Y の同時解放が必要 (別段階だと GSAS が U,V,W 凍結)
    r = build_resolution_recipe(refine_sh_l=False)
    last = list(r[-1].flags["profile"])
    assert {"U", "V", "W", "X", "Y"}.issubset(set(last))


def test_recipe_without_sh_l():
    r = build_resolution_recipe(refine_sh_l=False)
    assert len(r) == 5
    assert all("SH/L" not in s.flags.get("profile", []) for s in r)


def test_recipe_background_coeffs_passthrough():
    r = build_resolution_recipe(background_coeffs=20)
    assert r[0].flags["background"]["coeffs"] == 20


# --- extract_instrument_profile (stub runner) ---

def _result(profile, rwp):
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=rwp, gof=1.0, n_params=8, converged=True),),
        final_rwp=rwp, final_gof=1.0, refined_cells={"CeO2": (5.41,) * 3 + (90.0,) * 3},
        validity=ValidityReport(passed=True), hist_profile=(profile,),
    )


def test_extract_returns_instrument_profile():
    captured = {}

    def stub(hists, phases, *, recipe=None, **kw):
        captured["recipe"] = recipe
        captured["n_hists"] = len(hists)
        return _result({"U": 2.7, "V": -0.2, "W": 1.2, "X": 0.4, "Y": -5.2, "SH/L": 0.002,
                        "Zero": 0.001, "Polariz.": 0.95}, 9.5)

    ip = extract_instrument_profile(_standard(), _structure(), runner=stub)
    # INSTRUMENT_PROFILE_KEYS のみ拾う (Polariz. は除外)
    assert set(ip.values) == {"U", "V", "W", "X", "Y", "SH/L", "Zero"}
    assert ip.values["U"] == 2.7
    assert ip.source_rwp == 9.5
    # レシピが渡され単一ヒストグラム
    assert captured["recipe"] is not None and captured["n_hists"] == 1


def test_extract_excludes_missing_keys():
    def stub(hists, phases, *, recipe=None, **kw):
        return _result({"W": 1.2, "X": 0.4}, 10.0)  # 一部キーのみ

    ip = extract_instrument_profile(_standard(), _structure(), runner=stub)
    assert set(ip.values) == {"W", "X"}


def test_extract_empty_hist_profile():
    def stub(hists, phases, *, recipe=None, **kw):
        return _result({}, 12.0)  # EDGE-002

    ip = extract_instrument_profile(_standard(), _structure(), runner=stub)
    assert ip.values == {}
    assert ip.source_rwp == 12.0


def test_extract_deterministic():
    def stub(hists, phases, *, recipe=None, **kw):
        return _result({"U": 1.0, "W": 2.0}, 9.9)

    a = extract_instrument_profile(_standard(), _structure(), runner=stub)
    b = extract_instrument_profile(_standard(), _structure(), runner=stub)
    assert dict(a.values) == dict(b.values) and a.source_rwp == b.source_rwp


# --- constrain_nonneg (TASK-0003) ---

def test_constrain_nonneg_default_applies_bounds():
    captured = {}

    def stub(hists, phases, *, recipe=None, **kw):
        captured["bounds"] = hists[0].profile_bounds
        return _result({"U": 0.0, "W": 1.0, "X": 0.4, "Y": 0.0}, 9.06)

    extract_instrument_profile(_standard(), _structure(), runner=stub)  # 既定 True
    assert captured["bounds"] == NONNEG_PROFILE_BOUNDS
    assert set(NONNEG_PROFILE_BOUNDS) == {"U", "W", "X", "Y"}
    assert all(lo == 0.0 and hi is None for lo, hi in NONNEG_PROFILE_BOUNDS.values())


def test_constrain_nonneg_false_no_bounds():
    captured = {}

    def stub(hists, phases, *, recipe=None, **kw):
        captured["bounds"] = hists[0].profile_bounds
        return _result({"U": -8.0}, 8.88)

    extract_instrument_profile(_standard(), _structure(), runner=stub, constrain_nonneg=False)
    assert captured["bounds"] is None


def test_constrain_nonneg_preserves_caller_bounds():
    # 呼出側の明示 bounds を優先 (Y に上限を課したい等, EDGE-002)
    std = _standard()
    std = dataclasses_replace(std, profile_bounds={"Y": (0.0, 3.0)})
    captured = {}

    def stub(hists, phases, *, recipe=None, **kw):
        captured["bounds"] = hists[0].profile_bounds
        return _result({"W": 1.0}, 9.0)

    extract_instrument_profile(std, _structure(), runner=stub)
    assert captured["bounds"]["Y"] == (0.0, 3.0)   # 呼出側優先
    assert captured["bounds"]["X"] == (0.0, None)   # 非負はマージ
