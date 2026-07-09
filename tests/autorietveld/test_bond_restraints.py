"""_apply_bond_restraints (GSAS-II Bond restraint 登録) のテスト。

GSAS 非依存モック (addDistRestraint / setDistRestraintWeight 記録) で、拘束ツリー初期化・
相名フィルタ・引数写像・weight 設定・ラベル不一致スキップを検証する。O–H/D 結合長ソフト拘束で
無秩序水の軽原子座標の漂流を防ぐ機能 (run_auto_rietveld の bond_restraints)。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _apply_bond_restraints


class _MockPhase:
    def __init__(self, name):
        self.name = name
        self.dist_calls = []
        self.weight = None

    def addDistRestraint(self, origin, target, bond, factor=1.1, ESD=0.01):
        self.dist_calls.append((list(origin), list(target), bond, factor, ESD))
        return len(target)

    def setDistRestraintWeight(self, factor=1):
        self.weight = factor


class _MockGpx:
    def __init__(self):
        self.data = {}


def _spec(origin, target, distance, **kw):
    return {"origin": origin, "target": target, "distance": distance, **kw}


def test_registers_restraint_and_weight():
    g = _MockGpx()
    ph = _MockPhase("Wat")
    specs = [_spec(("O1",), ("D1", "H1"), 0.96, esd=0.03, factor=1.4, weight=200.0)]
    _apply_bond_restraints(g, [ph], {"Wat": specs})
    assert ph.dist_calls == [(["O1"], ["D1", "H1"], 0.96, 1.4, 0.03)]
    assert ph.weight == 200.0
    # 拘束ツリーが初期化される (addDistRestraint が参照する既定構造)。
    assert g.data["Restraints"]["data"]["Wat"]["Bond"]["Use"] is True


def test_phase_name_filter():
    g = _MockGpx()
    a, b = _MockPhase("A"), _MockPhase("B")
    _apply_bond_restraints(g, [a, b], {"A": [_spec(("O",), ("D",), 0.96)]})
    assert len(a.dist_calls) == 1
    assert b.dist_calls == []  # B は指定なし → 未登録


def test_defaults_applied():
    g = _MockGpx()
    ph = _MockPhase("P")
    _apply_bond_restraints(g, [ph], {"P": [_spec(("O",), ("D",), 0.96)]})
    _, _, bond, factor, esd = ph.dist_calls[0]
    assert (bond, factor, esd) == (0.96, 1.5, 0.02)  # 既定 factor/esd


def test_none_is_noop():
    g = _MockGpx()
    ph = _MockPhase("P")
    _apply_bond_restraints(g, [ph], None)
    assert ph.dist_calls == [] and "Restraints" not in g.data


def test_addrestraint_failure_skipped():
    class _Boom(_MockPhase):
        def addDistRestraint(self, *a, **k):
            raise RuntimeError("label mismatch")

    g = _MockGpx()
    ph = _Boom("P")
    # 例外は握って継続 (weight 設定まで到達)。
    _apply_bond_restraints(g, [ph], {"P": [_spec(("O",), ("D",), 0.96, weight=50.0)]})
    assert ph.weight == 50.0
