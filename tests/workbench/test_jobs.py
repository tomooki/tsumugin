"""``tsumugin.workbench.jobs`` の TDD テスト。

``RefinementJobManager`` 単体 (fake runner: 即時成功/例外/遅延, 二重起動 False, monotonic 注入で
決定論) と、``WorkbenchSession`` の on_success/on_failure コールバック (metrics/history/validity/
plot/phases が契約形へ更新されること・失敗時 ledger + status=failed で例外が貫通しないこと) を
検証する。
"""

from __future__ import annotations

import dataclasses
import threading

import pytest

import tsumugin.workbench.session as workbench_session_module
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.workbench import atoms, curves
from tsumugin.workbench.jobs import RefinementJobManager, build_default_runner
from tsumugin.workbench.project import WorkbenchProject
from tsumugin.workbench.session import WorkbenchSession


def _fake_project(tmp_path) -> WorkbenchProject:
    hist = HistogramSpec(
        data_path=str(tmp_path / "hist.xy"),
        instrument_path=str(tmp_path / "hist.instprm"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XY",
        two_theta_limits=(10.0, 20.0),
    )
    phase = PhaseSpec(structure_path=str(tmp_path / "phase.cif"), phase_name="phaseA")
    return WorkbenchProject(
        name="fake project",
        histograms=(hist,),
        phases=(phase,),
        background_coeffs=8,
        max_cyc=5,
        gpx_path=str(tmp_path / "workbench_out" / "refined.gpx"),
    )


def _fake_result(*, gpx_path: str = "") -> AutoRietveldResult:
    stages = (
        StageResult(label="background", rwp=20.0, gof=2.0, n_params=6, converged=True),
        StageResult(label="cell", rwp=10.0, gof=1.5, n_params=9, converged=True),
    )
    validity = ValidityReport(
        passed=True,
        checks=(("occupancy bounds", True, "0<=occ<=1"),),
        warnings=("low counts",),
    )
    return AutoRietveldResult(
        stage_results=stages,
        final_rwp=10.0,
        final_gof=1.5,
        refined_cells={"phaseA": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=validity,
        gpx_path=gpx_path,
        n_obs=1000,
        phase_weight_fractions={"phaseA": 1.0},
        phase_weight_fraction_esd={"phaseA": 0.0},
        hist_profile=({"U": -1.5, "V": -0.4},),
        atom_occupancy={"phaseA": {"O1": 1.0}},
    )


# ---------------------------------------------------------------------------
# RefinementJobManager 単体
# ---------------------------------------------------------------------------


def test_idle_status_before_start():
    job = RefinementJobManager()
    assert job.status() == {
        "status": "idle", "elapsed_s": None, "last_event": None, "error": None, "kind": None,
    }


def test_status_reports_kind_while_running_and_after_done():
    # 【セルフレビュー指摘 #1】: 共有ジョブ枠は refine/phaseid/multistart で使い回すため、
    #   status() の "kind" が起動時に渡した種別を反映し、完了後も直近の種別を保持すること。
    job = RefinementJobManager()
    started_evt = threading.Event()
    release_evt = threading.Event()

    def runner() -> str:
        started_evt.set()
        release_evt.wait(timeout=5)
        return "ok"

    job.start(runner, on_success=lambda r: None, on_failure=lambda e: None, kind="phaseid")
    assert started_evt.wait(timeout=5)
    assert job.status()["kind"] == "phaseid"

    release_evt.set()
    job.join(timeout=5)
    assert job.status()["status"] == "done"
    assert job.status()["kind"] == "phaseid"


def test_start_defaults_kind_to_refine_for_backward_compatible_callers():
    job = RefinementJobManager()
    job.start(lambda: "ok", on_success=lambda r: None, on_failure=lambda e: None)
    job.join(timeout=5)
    assert job.status()["kind"] == "refine"


def test_start_success_transitions_to_done_and_calls_on_success():
    job = RefinementJobManager()
    calls: list[str] = []

    started = job.start(lambda: "result", on_success=calls.append, on_failure=lambda e: None)
    job.join(timeout=5)

    assert started is True
    assert calls == ["result"]
    assert job.status()["status"] == "done"
    assert job.status()["error"] is None


def test_start_returns_false_while_running_double_start_guard():
    # 【二重起動ガード】: 実行中の 2 回目 start は False (POST /api/refine の 409 に対応)。
    job = RefinementJobManager()
    started_evt = threading.Event()
    release_evt = threading.Event()

    def runner() -> str:
        started_evt.set()
        release_evt.wait(timeout=5)
        return "ok"

    ok1 = job.start(runner, on_success=lambda r: None, on_failure=lambda e: None)
    assert ok1 is True
    assert started_evt.wait(timeout=5)

    ok2 = job.start(lambda: "second", on_success=lambda r: None, on_failure=lambda e: None)
    assert ok2 is False
    assert job.status()["status"] == "running"

    release_evt.set()
    job.join(timeout=5)
    assert job.status()["status"] == "done"


def test_runner_exception_marks_failed_and_calls_on_failure():
    job = RefinementJobManager()
    errors: list[BaseException] = []

    def bad_runner():
        raise RuntimeError("boom")

    job.start(bad_runner, on_success=lambda r: None, on_failure=errors.append)
    job.join(timeout=5)

    status = job.status()
    assert status["status"] == "failed"
    assert status["error"] == "boom"
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)


def test_on_success_exception_also_marks_failed_exception_does_not_propagate():
    # 【例外貫通禁止】: on_success (session 更新) 内の例外も job manager が捕捉して failed へ縮退する。
    job = RefinementJobManager()
    errors: list[BaseException] = []

    def on_success(result: object) -> None:
        raise ValueError("post-processing failed")

    job.start(lambda: "ok", on_success=on_success, on_failure=errors.append)
    job.join(timeout=5)  # 例外が join まで貫通しないこと自体がガード

    assert job.status()["status"] == "failed"
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)


def test_elapsed_s_uses_injected_monotonic_clock_deterministically():
    clock = {"t": 0.0}
    job = RefinementJobManager(now=lambda: clock["t"])
    release_evt = threading.Event()

    def runner() -> str:
        release_evt.wait(timeout=5)
        return "ok"

    job.start(runner, on_success=lambda r: None, on_failure=lambda e: None)
    clock["t"] = 5.0
    assert job.status()["elapsed_s"] == 5.0
    assert job.status()["status"] == "running"

    clock["t"] = 9.0
    release_evt.set()
    job.join(timeout=5)

    status = job.status()
    assert status["status"] == "done"
    assert status["elapsed_s"] == 9.0  # start=0.0, end=9.0 (共に fake_now 注入値)


def test_last_event_callable_reflected_in_status():
    events = ["stage 01 rwp=20.0"]
    job = RefinementJobManager(last_event=lambda: events[-1])

    assert job.status()["last_event"] == "stage 01 rwp=20.0"
    events.append("stage 02 rwp=10.0")
    assert job.status()["last_event"] == "stage 02 rwp=10.0"


# ---------------------------------------------------------------------------
# build_default_runner (project → run_auto_rietveld 配線)
# ---------------------------------------------------------------------------


def test_build_default_runner_wires_project_settings(tmp_path, monkeypatch):
    project = _fake_project(tmp_path)
    captured: dict[str, object] = {}

    def fake_build_recipe(histograms, phases, *, background_coeffs):
        captured["background_coeffs"] = background_coeffs
        return ("STAGE",)

    def fake_run_auto_rietveld(
        histograms, phases, *, recipe, ledger, max_cyc, keep_gpx, initial_occupancies=None
    ):
        captured["recipe"] = recipe
        captured["max_cyc"] = max_cyc
        captured["keep_gpx"] = keep_gpx
        captured["ledger"] = ledger
        captured["initial_occupancies"] = initial_occupancies
        return "RESULT"

    import tsumugin.autorietveld.engine as engine_mod
    import tsumugin.autorietveld.recipe as recipe_mod

    monkeypatch.setattr(recipe_mod, "build_recipe", fake_build_recipe)
    monkeypatch.setattr(engine_mod, "run_auto_rietveld", fake_run_auto_rietveld)

    sentinel_ledger = object()
    runner = build_default_runner(project, ledger=sentinel_ledger)
    out = runner()

    assert out == "RESULT"
    assert captured["background_coeffs"] == project.background_coeffs
    assert captured["max_cyc"] == project.max_cyc
    assert captured["keep_gpx"] == project.gpx_path
    assert captured["ledger"] is sentinel_ledger
    assert captured["recipe"] == ("STAGE",)
    assert captured["initial_occupancies"] is None


def test_build_default_runner_filters_recipe_by_stages_on(tmp_path, monkeypatch):
    # 【A1】: stages_on で False にした段は build_recipe が返す段列から実際に除かれる。
    project = _fake_project(tmp_path)
    captured: dict[str, object] = {}

    def fake_build_recipe(histograms, phases, *, background_coeffs):
        return ("S1", "S2", "S3")

    def fake_run_auto_rietveld(
        histograms, phases, *, recipe, ledger, max_cyc, keep_gpx, initial_occupancies=None
    ):
        captured["recipe"] = recipe
        return "RESULT"

    import tsumugin.autorietveld.engine as engine_mod
    import tsumugin.autorietveld.recipe as recipe_mod

    monkeypatch.setattr(recipe_mod, "build_recipe", fake_build_recipe)
    monkeypatch.setattr(engine_mod, "run_auto_rietveld", fake_run_auto_rietveld)

    runner = build_default_runner(project, stages_on={"02": False})
    out = runner()

    assert out == "RESULT"
    assert captured["recipe"] == ("S1", "S3")


def test_build_default_runner_passes_initial_occupancies_through(tmp_path, monkeypatch):
    # 【A3】: initial_occupancies は run_auto_rietveld へそのまま透過する。
    project = _fake_project(tmp_path)
    captured: dict[str, object] = {}

    def fake_build_recipe(histograms, phases, *, background_coeffs):
        return ("STAGE",)

    def fake_run_auto_rietveld(
        histograms, phases, *, recipe, ledger, max_cyc, keep_gpx, initial_occupancies=None
    ):
        captured["initial_occupancies"] = initial_occupancies
        return "RESULT"

    import tsumugin.autorietveld.engine as engine_mod
    import tsumugin.autorietveld.recipe as recipe_mod

    monkeypatch.setattr(recipe_mod, "build_recipe", fake_build_recipe)
    monkeypatch.setattr(engine_mod, "run_auto_rietveld", fake_run_auto_rietveld)

    occ = {"phaseA": {"O1": 0.5}}
    runner = build_default_runner(project, initial_occupancies=occ)
    runner()

    assert captured["initial_occupancies"] == occ


# ---------------------------------------------------------------------------
# WorkbenchSession の on_success/on_failure コールバック (session 更新が契約形)
# ---------------------------------------------------------------------------


def test_on_refine_success_updates_session_in_contract_shape(tmp_path, monkeypatch):
    project = _fake_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    fake_plot = {
        "h0": {
            "x": [1.0], "yobs": [2.0], "ycalc": [2.1], "ybkg": [0.1], "residual": [-0.1],
            "ticks": {"phaseA": [1.0]},
        }
    }
    monkeypatch.setattr(curves, "extract_curves", lambda gpx, **kw: fake_plot)
    fake_sites = [
        {
            "id": "s1", "label": "O1", "el": "O", "x": "0.1000", "y": "0.2000", "z": "0.3000",
            "occ": "1.0000", "uiso": "0.0100", "note": "", "lock": {"x": False, "y": False, "z": False},
            "rel": {"x": False, "y": False, "z": False, "occ": False, "uiso": False},
            "phase": "phaseA",
        }
    ]
    monkeypatch.setattr(atoms, "extract_sites", lambda gpx, **kw: fake_sites)
    result = _fake_result(gpx_path=str(tmp_path / "refined.gpx"))

    before_snaps = len(session.snapshots.snapshots)
    before_ledger = len(session.ledger.entries)

    session._on_refine_success(result)

    vm = session.viewmodel()
    metrics = {m["key"]: m for m in vm["fit"]["metrics"]}
    assert metrics["rwp"]["value"] == "10.00%"
    assert metrics["gof"]["value"] == "1.50"
    assert metrics["n_params"]["value"] == "9"
    assert metrics["n_obs"]["value"] == "1000"

    history = vm["fit"]["history"]
    assert len(history) == 2
    assert history[0]["rwp"] == 20.0
    assert history[1]["rwp"] == 10.0
    assert history[1]["delta_rwp"] == pytest.approx(-10.0)
    assert all(row["reverted"] is False for row in history)

    validity = vm["fit"]["validity"]
    assert any(row["status"] == "pass" for row in validity)
    assert any(row["status"] == "warn" and row["detail"] == "low counts" for row in validity)

    assert vm["fit"]["plot"] == fake_plot

    phase_row = next(p for p in vm["phases"] if p["name"] == "phaseA")
    assert phase_row["wt_frac"] == "100.0 %"  # esd=0.0 (単相の自明値) は括弧を出さない

    # A2: 実サイトが反映され、内部専用の "phase" キーは viewmodel から取り除かれている
    site_row = next(s for s in vm["structure"]["sites"] if s["label"] == "O1")
    assert site_row["el"] == "O"
    assert "phase" not in site_row
    # セルフレビュー指摘 #3: _site_phase_map は label でなく site の一意 id をキーにする
    # (多相で label が衝突しうるため)。
    assert session._site_phase_map["s1"] == "phaseA"

    assert len(session.snapshots.snapshots) == before_snaps + 1
    # 副作用は SnapshotStore.save (snapshot_save) + 明示 "refine_finished" の 2 エントリ
    assert len(session.ledger.entries) == before_ledger + 2
    assert session.ledger.entries[-1].kind == "refine_finished"


def test_on_refine_success_and_apply_structure_route_colliding_labels_by_id(tmp_path, monkeypatch):
    """セルフレビュー指摘 #3 (end-to-end): 2 相が同じ label ("O1") を持つ raw_sites を
    `atoms.extract_sites` から注入し、`_on_refine_success` が構築する `_site_phase_map` が
    site の一意 id をキーにすること、その後の `apply_structure` の occ 編集が id 経由で
    正しい相の `_pending_occupancies` へ配信されることを検証する (label キーだと衝突した
    片方の相の revision が消える回帰の恒久ガード)。
    """
    project = _fake_project(tmp_path)
    project = dataclasses.replace(
        project,
        phases=project.phases + (PhaseSpec(structure_path=str(tmp_path / "phaseB.cif"), phase_name="phaseB"),),
    )
    session = WorkbenchSession.from_project(project)
    monkeypatch.setattr(curves, "extract_curves", lambda gpx, **kw: {})
    fake_sites = [
        {
            "id": "s1", "label": "O1", "el": "O", "x": "0.1000", "y": "0.2000", "z": "0.3000",
            "occ": "1.0000", "uiso": "0.0100", "note": "", "lock": {"x": False, "y": False, "z": False},
            "rel": {"x": False, "y": False, "z": False, "occ": False, "uiso": False},
            "phase": "phaseA",
        },
        {
            "id": "s7", "label": "O1", "el": "O", "x": "0.5000", "y": "0.5000", "z": "0.5000",
            "occ": "1.0000", "uiso": "0.0100", "note": "", "lock": {"x": False, "y": False, "z": False},
            "rel": {"x": False, "y": False, "z": False, "occ": False, "uiso": False},
            "phase": "phaseB",
        },
    ]
    monkeypatch.setattr(atoms, "extract_sites", lambda gpx, **kw: fake_sites)
    result = _fake_result(gpx_path=str(tmp_path / "refined.gpx"))

    session._on_refine_success(result)

    assert session._site_phase_map == {"s1": "phaseA", "s7": "phaseB"}

    apply_result = session.apply_structure(
        [
            {"id": "s1", "label": "O1", "occ": "0.40"},
            {"id": "s7", "label": "O1", "occ": "0.80"},
        ]
    )

    assert "error" not in apply_result
    assert session._pending_occupancies == {
        "phaseA": {"O1": 0.40},
        "phaseB": {"O1": 0.80},
    }


def test_on_refine_success_updates_profile_card_from_hist_profile(tmp_path):
    project = _fake_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    result = _fake_result(gpx_path="")  # gpx_path 空 → plot 抽出はスキップされる (GSAS 不要)

    session._on_refine_success(result)

    vm = session.viewmodel()
    profile_card = next(c for c in vm["parameters"]["h0"]["cards"] if c["id"] == "profile")
    fields = {row["field"]: row["value"] for row in profile_card["rows"]}
    assert fields["U"] == "-1.5"
    assert fields["V"] == "-0.4"
    assert all(row["released"] for row in profile_card["rows"])


def test_on_refine_failure_appends_ledger_and_no_snapshot_no_exception(tmp_path):
    project = _fake_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    before_snaps = len(session.snapshots.snapshots)
    before_ledger = len(session.ledger.entries)

    session._on_refine_failure(RuntimeError("boom"))  # 例外を送出しないこと自体がテスト対象

    assert len(session.snapshots.snapshots) == before_snaps
    assert len(session.ledger.entries) == before_ledger + 1
    assert session.ledger.entries[-1].kind == "refine_failed"
    assert "boom" in session.ledger.entries[-1].payload["error"]


def test_request_refine_conflict_when_already_running(tmp_path, monkeypatch):
    # 【二重起動 409 の end-to-end】: session.request_refine 経由でも RefinementJobManager の
    #   二重起動ガードが効くことを確認する (fake runner 注入は §4.5 に従いテスト専用)。
    project = _fake_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    started_evt = threading.Event()
    release_evt = threading.Event()

    def fake_runner() -> AutoRietveldResult:
        started_evt.set()
        release_evt.wait(timeout=5)
        return _fake_result()

    monkeypatch.setattr(
        workbench_session_module, "build_default_runner",
        lambda project, ledger=None, stages_on=None, initial_occupancies=None: fake_runner,
    )

    result1 = session.request_refine()
    assert result1 == {"status": "started"}
    assert started_evt.wait(timeout=5)
    assert session.refine_status()["status"] == "running"

    result2 = session.request_refine()
    assert result2["error_type"] == "ConflictError"
    assert "error" in result2

    release_evt.set()
    session._job.join(timeout=5)
    assert session.refine_status()["status"] == "done"
