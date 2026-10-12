"""fit-then-judge P1a: GSAS 経路にしか無い `PhaseSpec` の機能を TOPAS に黙って渡さない。

`uiso_equiv_groups` (Uiso の等値の組) と `fix_polar_origin` (極性方向の原点固定) は GSAS-II
経路だけが実装している。TOPAS バックエンドに渡すと何もせずに完走する (= 指定したつもりの
拘束が無い精密化になる) ので、TOPAS エンジンが構造を読む前に拒否する
(`topas.structure.PHASE_SPEC_FIELDS` の ``refused``)。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.backends import resolve_backend
from tsumugin.autorietveld.model import PhaseSpec
from tsumugin.errors import InvalidPhaseSpecError


@pytest.fixture
def stub_topas(monkeypatch):
    calls = []

    def fake(histograms, phases, **kwargs):
        calls.append((histograms, phases, kwargs))
        return "ran"

    monkeypatch.setattr("tsumugin.topas.engine.run_topas_rietveld", fake)
    return calls


@pytest.mark.parametrize(
    "spec",
    [
        PhaseSpec("x.cif", "x", uiso_equiv_groups=(("O1", "O2"),)),
        PhaseSpec("x.cif", "x", fix_polar_origin=True),
    ],
)
def test_topas_refuses_gsas_only_phase_features(spec):
    """TOPAS の相の指定の分類表 (`PHASE_SPEC_FIELDS`) で ``refused`` にしてあり、TOPAS エンジンが
    構造を読む前に呼ぶ `check_phase_spec_supported` が拒否する (#229 の仕組みに載せた)。"""
    from tsumugin.topas.structure import PHASE_SPEC_FIELDS, check_phase_spec_supported

    assert PHASE_SPEC_FIELDS["uiso_equiv_groups"][0] == "refused"
    assert PHASE_SPEC_FIELDS["fix_polar_origin"][0] == "refused"
    with pytest.raises(InvalidPhaseSpecError, match="TOPAS"):
        check_phase_spec_supported(spec)


def test_topas_passes_ordinary_phases_through(stub_topas):
    engine = resolve_backend("topas")
    assert engine([], [PhaseSpec("x.cif", "x")], recipe=()) == "ran"
    assert len(stub_topas) == 1


def test_gsas_backend_is_not_wrapped():
    from tsumugin import autorietveld

    assert resolve_backend("gsasii") is autorietveld.run_auto_rietveld


def test_topas_refuses_lorentzian_key_lists(stub_topas):
    """TOPAS は profile_lorentzian の値の真偽で x,y を解放するだけ — ["Zero"] でも幅が動く (M3)。"""
    from tsumugin.autorietveld.model import RefinementStage
    from tsumugin.topas.flags import UnsupportedStageFlagError

    engine = resolve_backend("topas")
    stage = RefinementStage("l", {"profile_lorentzian": ["Zero"]})
    with pytest.raises(UnsupportedStageFlagError, match="キー列"):
        engine([], [PhaseSpec("x.cif", "x")], recipe=(stage,))
    assert stub_topas == []
    # 真偽値は従来どおり通す
    ok = RefinementStage("l", {"profile_lorentzian": True})
    assert engine([], [PhaseSpec("x.cif", "x")], recipe=(ok,)) == "ran"
