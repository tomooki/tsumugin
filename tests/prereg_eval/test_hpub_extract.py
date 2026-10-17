"""P0 §3.2.1-3/4: 凍結後の H-pub 抽出スクリプトの手続き (drand round の求め方・置換の順)。合成の ID だけ。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "docs" / "benchmark" / "fit-then-judge-hpub" / "extract.py"


def _mod():
    spec = importlib.util.spec_from_file_location("_hpub_extract", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_first_round_at_or_after_a_time():
    m = _mod()
    assert m.first_round_at_or_after(1000, genesis=1000, period=30) == 1
    assert m.first_round_at_or_after(1001, genesis=1000, period=30) == 2
    assert m.first_round_at_or_after(1030, genesis=1000, period=30) == 2
    assert m.first_round_at_or_after(1031, genesis=1000, period=30) == 3
    assert m.first_round_at_or_after(10, genesis=1000, period=30) == 1


def test_select_takes_k_in_order_and_records_replacements():
    m = _mod()
    reasons = {"b": "unreadable", "d": "development compound"}
    adopted, replaced = m.select(["a", "b", "c", "d", "e"], 3, reasons.get)
    assert adopted == ["a", "c", "e"] and replaced == [("b", "unreadable"), ("d", "development compound")]


def test_select_reports_shortfall_without_inventing_cases():
    m = _mod()
    adopted, replaced = m.select(["a", "b"], 3, lambda i: "unreadable" if i == "b" else None)
    assert adopted == ["a"] and replaced == [("b", "unreadable")]


def test_the_extraction_script_is_not_a_frozen_component():
    """抽出は凍結の後の作業 — スクリプトを凍結の部品に入れると、抽出の手直しが凍結を壊す (逆に部品を変えずに済むように外に置く)。"""
    from tsumugin.prereg_eval.freeze import FROZEN_COMPONENTS

    patterns = [g for globs in FROZEN_COMPONENTS.values() for g in globs]
    assert not any("extract.py" in g or g.endswith("fit-then-judge-hpub/*.py") for g in patterns)


def test_select_stops_at_k_even_when_more_candidates_remain():
    m = _mod()
    adopted, replaced = m.select(["a", "b", "c", "d"], 2, lambda i: None)
    assert adopted == ["a", "b"] and replaced == []
