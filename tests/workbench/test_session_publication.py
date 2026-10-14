"""fit-then-judge P1c タスク 3: ワークベンチの精密化が出版状態を作り、viewmodel に出す。"""

from __future__ import annotations

import json

from tsumugin.autorietveld.claim_variables import PhaseVariables, claim_variable_names
from tsumugin.autorietveld.diagnostics import CovarianceRecord
from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.workbench import lifecycle
from tsumugin.workbench.session import WorkbenchSession


def _result(gpx_path: str = "") -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("s", 8.1, 1.3, 17, True),), final_rwp=8.1, final_gof=1.3,
        refined_cells={"P": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True), gpx_path=gpx_path, n_obs=3300,
        cell_esd={"P": (0.001, 0.001, 0.001, 0.0, 0.0, 0.0)},
        atom_coords={"P": {"O1": (0.25, 0.1, 0.3)}},
        atom_coord_esd={"P": {"O1": (0.001, 0.002, None)}},
        atom_coord_free_index={"P": {"O1": (1, 2, 3)}},
        final_covariance=CovarianceRecord(
            vary_list=("0::A0", "0::dAx:0"), dependent=(), correlations=(),
        ),
        claim_variables=claim_variable_names([PhaseVariables(name="P", pid=0, labels=("O1",))], []),
    )


def _session(tmp_path) -> WorkbenchSession:
    return WorkbenchSession.from_project(lifecycle.create_project("proj", str(tmp_path)))


def test_no_publication_before_a_refinement(tmp_path):
    assert "publication" not in _session(tmp_path).viewmodel()


def test_the_demo_never_shows_a_publication_state():
    assert "publication" not in WorkbenchSession(mode="manual").viewmodel()


def test_a_refinement_produces_the_publication_state(tmp_path):
    session = _session(tmp_path)
    session._on_refine_success(_result())
    pub = session.viewmodel()["publication"]
    json.dumps(pub, allow_nan=False)
    assert pub["claims_version"] and pub["policy"] and pub["error"] is None
    assert pub["n_values"] == len(pub["rows"]) > 0
    row = next(r for r in pub["rows"] if r["key"] == "cell:P.a")
    assert row["value"] == 5.0 and row["publishable"] is False  # 相集合・結晶化学が未検査
    assert row["scope"] == "relative_within_sample" and row["determinacy"] == "esd_only"
    assert row["gate"]  # 止めている判断要求
    req = next(r for r in pub["judgment_requests"] if r["kind"] == "phase_set_completeness")
    assert req["blocking"] and req["default_answer"] == "hold" and req["n_blocked"] > 0
    assert "hold" in req["candidates"]


def test_the_assessment_is_recorded_in_the_ledger_and_the_sidecar(tmp_path, monkeypatch):
    # 曲線とサイトの抽出は実 gpx を要する — ここでは出版状態だけを見る
    monkeypatch.setattr("tsumugin.workbench.curves.extract_curves", lambda *a, **k: {})
    monkeypatch.setattr("tsumugin.workbench.atoms.extract_sites", lambda *a, **k: [])
    gpx = tmp_path / "refined.gpx"
    gpx.write_bytes(b"gpx")
    session = _session(tmp_path)
    session._on_refine_success(_result(str(gpx)))
    entry = [e for e in session.ledger.entries if e.kind == "publication_assessed"][-1].payload
    assert entry["n_values"] > 0 and entry["n_blocking"] >= 1
    assert entry["sidecar"].endswith("refined.claims.json")
    assert session.viewmodel()["publication"]["sidecar"] == entry["sidecar"]
    text = [e for e in session.ledger_view()["entries"] if "publication" in e["text"]][-1]
    assert text["actor"] == "GUARD"


def test_a_failure_to_assess_is_shown_not_hidden(tmp_path, monkeypatch):
    import tsumugin.claims.requests as requests

    def boom(*a, **k):
        raise RuntimeError("assess failed")

    monkeypatch.setattr(requests, "assess", boom)
    session = _session(tmp_path)
    session._on_refine_success(_result())
    pub = session.viewmodel()["publication"]
    assert pub["error"] and pub["rows"] == [] and pub["n_publishable"] == 0


def test_the_viewmodel_does_not_hand_out_the_internal_state(tmp_path):
    session = _session(tmp_path)
    session._on_refine_success(_result())
    session.viewmodel()["publication"]["rows"].clear()
    assert session.viewmodel()["publication"]["rows"]


def test_a_broken_view_does_not_fail_a_successful_refinement(tmp_path, monkeypatch):
    """表示の組み立て自体が落ちても、成功した精密化は「成功」のまま (エラーは表示に出す)。"""
    import tsumugin.workbench.session as session_module

    def boom(*a, **k):
        raise KeyError("rows")

    monkeypatch.setattr(session_module, "_build_publication_view", boom)
    session = _session(tmp_path)
    session._on_refine_success(_result())
    pub = session.viewmodel()["publication"]
    assert "KeyError" in pub["error"] and pub["rows"] == [] and pub["n_values"] == 0
    assert any(e.kind == "publication_assessed" for e in session.ledger.entries)


def test_changing_the_project_inputs_drops_the_old_publication(tmp_path):
    session = _session(tmp_path)
    session._on_refine_success(_result())
    session._refresh_project_views()
    assert "publication" not in session.viewmodel()


def test_the_contract_vocabulary_matches_the_claim_types():
    """契約の語彙 (api-contract.md §語彙) が `Claim` の型と一致する — 片方だけ増やさない。"""
    import re
    from pathlib import Path

    from tsumugin.claims.model import Determinacy, Scope

    doc = (Path(__file__).resolve().parents[2] / "docs/design/gui-workbench/api-contract.md").read_text(
        encoding="utf-8"
    )

    def vocab(field: str) -> set[str]:
        row = next(line for line in doc.splitlines() if line.startswith(f"| `{field}` |"))
        return set(re.findall(r"`([a-z_]+)`", row.split("|", 2)[2]))

    assert vocab("publication.rows[].determinacy") == {d.value for d in Determinacy}
    assert vocab("publication.rows[].scope") == {s.value for s in Scope}
