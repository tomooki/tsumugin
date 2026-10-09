"""fit-then-judge P1a: GSAS 経路にしか無い `PhaseSpec` の機能を TOPAS に黙って渡さない。

`uiso_equiv_groups` (Uiso の等値の組) と `fix_polar_origin` (極性方向の原点固定) は GSAS-II
経路だけが実装している。TOPAS バックエンドに渡すと何もせずに完走する (= 指定したつもりの
拘束が無い精密化になる) ので、`resolve_backend("topas")` の入口で拒否する。
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
def test_topas_refuses_gsas_only_phase_features(spec, stub_topas):
    engine = resolve_backend("topas")
    with pytest.raises(InvalidPhaseSpecError, match="TOPAS"):
        engine([], [spec], recipe=())
    assert stub_topas == [], "拒否したのにエンジンが呼ばれた"


def test_topas_passes_ordinary_phases_through(stub_topas):
    engine = resolve_backend("topas")
    assert engine([], [PhaseSpec("x.cif", "x")], recipe=()) == "ran"
    assert len(stub_topas) == 1


def test_gsas_backend_is_not_wrapped():
    from tsumugin import autorietveld

    assert resolve_backend("gsasii") is autorietveld.run_auto_rietveld
