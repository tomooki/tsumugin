"""``tsumugin.workbench.seed`` の決定論シードデータテスト。

seed 関数群は numpy にも fastapi にも依存しない純関数であることを確認しつつ、
api-contract.md の形状 (キー集合・JSON serializable・非有限値なし) を検証する。
"""

from __future__ import annotations

import json

from tsumugin.workbench import seed


def test_seed_functions_are_deterministic():
    # 【目的】: 同一呼び出しは常に同じ値を返す (NFR-102 決定論)
    assert seed.seed_fit() == seed.seed_fit()
    assert seed.seed_hypotheses_rows() == seed.seed_hypotheses_rows()
    assert seed.seed_structure_sites() == seed.seed_structure_sites()


def test_seed_fit_has_six_metric_cards_and_finite_values():
    fit = seed.seed_fit()
    assert len(fit["metrics"]) == 6
    text = json.dumps(fit, allow_nan=False)
    assert text
    assert fit["two_theta"] == {"min": 4.0, "max": 38.0}


def test_seed_parameters_covers_all_three_histograms():
    params = seed.seed_parameters()
    assert set(params) == {"sxrd", "nd1", "nd2"}
    for hist in params.values():
        assert "released_count" in hist
        assert isinstance(hist["released_count"], int)
        assert len(hist["cards"]) >= 3
        for card in hist["cards"]:
            assert {"id", "title", "rows"} <= set(card)


def test_seed_hypotheses_rows_ids_match_search_result():
    rows = seed.seed_hypotheses_rows()
    result = seed.build_seed_search_result()
    row_ids = {r["id"] for r in rows}
    assert row_ids == set(result.hypotheses)
    assert row_ids == {"H-014", "H-011", "H-009"}


def test_build_seed_search_result_ranked_matches_rows():
    result = seed.build_seed_search_result()
    rows = {r["id"]: r for r in seed.seed_hypotheses_rows()}
    for ranked in result.ranked:
        row = rows[ranked.hypothesis.id]
        assert ranked.hypothesis.metrics.rwp == row["rwp"]
        assert ranked.hypothesis.metrics.evidence["bic"] == row["bic"]


def test_seed_review_items_has_four_entries_matching_handoff():
    items = seed.seed_review_items()
    assert len(items) == 4
    titles = [item["title"] for item in items]
    assert titles == [
        "close competitor", "unindexed peaks", "guard fired 3×",
        "coulometric feasibility infeasible",
    ]
    refs = [item["ref"] for item in items]
    assert refs == ["ΔlogZ 1.2", "2θ 12.42, 17.88", "3 consecutive", "fr092"]


def test_seed_structure_sites_k1_matches_api_contract_example():
    sites = seed.seed_structure_sites()
    k1 = next(s for s in sites if s["label"] == "K1")
    assert k1["el"] == "K"
    assert k1["x"] == "0.2500"
    assert k1["occ"] == "0.71"
    assert k1["lock"] == {"x": True, "y": True, "z": True}
    assert k1["rel"]["occ"] is True
    assert k1["rel"]["x"] is False


def test_seed_structure_base_phase_occupancies_match_sites():
    phase = seed.seed_structure_base_phase()
    sites = seed.seed_structure_sites()
    for site in sites:
        assert phase.occupancies[site["label"]] == float(site["occ"])


def test_seed_transcript_has_all_message_kinds():
    transcript = seed.seed_transcript()
    kinds = {m["kind"] for m in transcript}
    assert kinds == {"user", "agent", "tool", "judgement", "approval", "escalation"}
    approval = next(m for m in transcript if m["kind"] == "approval")
    assert approval["action_id"] == "a1"
    assert approval["state"] == "pending"


def test_seed_stages_has_eight_rows_with_gate_mapping():
    stages = seed.seed_stages()
    assert len(stages) == 8
    gates = {s["nn"]: s["gate"] for s in stages}
    assert gates["01"] == "bkg"
    assert gates["02"] is None  # ungated (scale + cell)
    assert gates["03"] is None  # ungated (zero)
    assert gates["06"] == "sample"
    assert gates["07"] == "occ"
    assert gates["08"] == "micro"


def test_seed_phase_id_completeness_is_incomplete():
    phase_id = seed.seed_phase_id()
    assert phase_id["completeness"]["is_complete"] is False
    assert len(phase_id["unexplained"]) == 2


def test_all_seed_top_level_functions_json_serializable_without_nan():
    payload = {
        "project": seed.seed_project(),
        "status": seed.seed_status(),
        "agent": seed.seed_agent_status(),
        "datasets": seed.seed_datasets(),
        "phases": seed.seed_phases(),
        "channels": seed.seed_channels(),
        "snapshots": seed.seed_snapshots(),
        "fit": seed.seed_fit(),
        "parameters": seed.seed_parameters(),
        "hypotheses_rows": seed.seed_hypotheses_rows(),
        "hypotheses_diff": seed.seed_hypotheses_diff(),
        "hypotheses_evidence": seed.seed_hypotheses_evidence(),
        "phase_id": seed.seed_phase_id(),
        "sequence": seed.seed_sequence(),
        "structure_sites": seed.seed_structure_sites(),
        "structure_constraints": seed.seed_structure_constraints(),
        "mem_peaks": seed.seed_mem_peaks(),
        "stages": seed.seed_stages(),
        "review_items": seed.seed_review_items(),
        "transcript": seed.seed_transcript(),
    }
    text = json.dumps(payload, allow_nan=False)
    assert text
