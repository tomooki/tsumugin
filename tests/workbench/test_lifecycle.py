"""``tsumugin.workbench.lifecycle`` の TDD テスト (create/open/save/recent/永続 ledger 継続)。

対象: `lifecycle.create_project`/`open_project`/`save_project_spec`/`sanitize_filename`/
`load_recent`/`add_recent` と、`WorkbenchSession.open_persistent`/`create_empty` の round trip。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tsumugin.errors import LedgerIntegrityError
from tsumugin.workbench import lifecycle
from tsumugin.workbench.project import WorkbenchProject
from tsumugin.workbench.session import WorkbenchSession


@pytest.fixture(autouse=True)
def _fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """recent 一覧の保存先 (``~/.tsumugin/...``) をテスト用ホームへ隔離する。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


def test_create_project_builds_directory_structure(tmp_path: Path):
    project = lifecycle.create_project("myproj", str(tmp_path))

    target = tmp_path / "myproj"
    assert target.is_dir()
    assert (target / "data").is_dir()
    assert (target / "workbench_out").is_dir()
    assert (target / "project.json").exists()

    assert isinstance(project, WorkbenchProject)
    assert project.name == "myproj"
    assert project.histograms == ()
    assert project.phases == ()
    assert project.background_coeffs == 6
    assert project.max_cyc == 12
    assert Path(project.spec_dir) == target.resolve()


def test_create_project_existing_directory_raises_value_error(tmp_path: Path):
    (tmp_path / "myproj").mkdir()

    with pytest.raises(ValueError):
        lifecycle.create_project("myproj", str(tmp_path))


def test_create_project_registers_recent(tmp_path: Path):
    project = lifecycle.create_project("myproj", str(tmp_path))

    recent = lifecycle.load_recent()
    assert len(recent) == 1
    assert recent[0]["name"] == "myproj"
    assert Path(recent[0]["path"]) == Path(project.spec_dir)
    assert "last_opened" in recent[0]


# ---------------------------------------------------------------------------
# open_project
# ---------------------------------------------------------------------------


def test_open_project_from_directory_and_from_file(tmp_path: Path):
    created = lifecycle.create_project("myproj", str(tmp_path))

    from_dir = lifecycle.open_project(created.spec_dir)
    from_file = lifecycle.open_project(str(Path(created.spec_dir) / "project.json"))

    assert from_dir.name == "myproj"
    assert from_file.name == "myproj"


def test_open_project_missing_raises_value_error(tmp_path: Path):
    with pytest.raises(ValueError):
        lifecycle.open_project(tmp_path / "does-not-exist")


def test_open_project_reads_added_histograms_and_phases(tmp_path: Path):
    created = lifecycle.create_project("myproj", str(tmp_path))
    spec_path = Path(created.spec_dir) / "project.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["histograms"].append(
        {
            "data_path": "data/hist.xy",
            "instrument_path": "data/hist.instprm",
            "radiation": "xray_lab",
            "geometry": "bragg_brentano",
            "data_format": "XY",
        }
    )
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    reopened = lifecycle.open_project(created.spec_dir)

    assert len(reopened.histograms) == 1
    assert reopened.histograms[0].data_format == "XY"


# ---------------------------------------------------------------------------
# save_project_spec (round trip + 相対パス化)
# ---------------------------------------------------------------------------


def test_save_project_spec_roundtrip_relativizes_paths_under_spec_dir(tmp_path: Path):
    import dataclasses

    from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation

    project = lifecycle.create_project("myproj", str(tmp_path))
    spec_dir = Path(project.spec_dir)
    (spec_dir / "data" / "hist.xy").parent.mkdir(parents=True, exist_ok=True)
    hist = HistogramSpec(
        data_path=str(spec_dir / "data" / "hist.xy"),
        instrument_path=str(spec_dir / "data" / "hist.instprm"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XY",
    )
    phase = PhaseSpec(structure_path=str(spec_dir / "data" / "phase.cif"), phase_name="phaseA")
    updated = dataclasses.replace(project, histograms=(hist,), phases=(phase,))

    lifecycle.save_project_spec(updated)

    raw = json.loads((spec_dir / "project.json").read_text(encoding="utf-8"))
    assert raw["histograms"][0]["data_path"] == "data\\hist.xy" or raw["histograms"][0][
        "data_path"
    ].replace("\\", "/") == "data/hist.xy"

    reopened = lifecycle.open_project(spec_dir)
    assert Path(reopened.histograms[0].data_path) == (spec_dir / "data" / "hist.xy").resolve()
    assert Path(reopened.phases[0].structure_path) == (spec_dir / "data" / "phase.cif").resolve()


def test_save_project_spec_preserves_phase_display(tmp_path: Path):
    import dataclasses

    from tsumugin.autorietveld.model import PhaseSpec

    project = lifecycle.create_project("myproj", str(tmp_path))
    phase = PhaseSpec(structure_path="phase.cif", phase_name="phaseA")
    updated = dataclasses.replace(
        project, phases=(phase,), phase_display={"phaseA": {"space_group": "P1"}}
    )

    lifecycle.save_project_spec(updated)
    reopened = lifecycle.open_project(project.spec_dir)

    assert reopened.phase_display["phaseA"]["space_group"] == "P1"


# ---------------------------------------------------------------------------
# sanitize_filename (P2 upload)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("hist.xy", "hist.xy"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\evil.dll", "evil.dll"),
        ("..", "file"),
        ("", "file"),
        ("a b*c?d.xy", "a_b_c_d.xy"),
    ],
)
def test_sanitize_filename(raw: str, expected: str):
    assert lifecycle.sanitize_filename(raw) == expected


# ---------------------------------------------------------------------------
# recent (load/add: dedup + 最大 10 件)
# ---------------------------------------------------------------------------


def test_load_recent_returns_empty_list_when_missing():
    assert lifecycle.load_recent() == []


def test_add_recent_dedups_and_moves_to_front():
    lifecycle.add_recent("a", "/path/a")
    lifecycle.add_recent("b", "/path/b")
    lifecycle.add_recent("a", "/path/a")

    recent = lifecycle.load_recent()
    assert [e["path"] for e in recent] == ["/path/a", "/path/b"]


def test_add_recent_caps_at_ten_entries():
    for i in range(12):
        lifecycle.add_recent(f"p{i}", f"/path/{i}")

    recent = lifecycle.load_recent()
    assert len(recent) == 10
    # 最新 (直近追加) が先頭
    assert recent[0]["path"] == "/path/11"


# ---------------------------------------------------------------------------
# WorkbenchSession.open_persistent / create_empty (P1: 永続 ledger 継続 + Welcome)
# ---------------------------------------------------------------------------


def test_open_persistent_creates_ledger_and_snapshot_files(tmp_path: Path):
    project = lifecycle.create_project("myproj", str(tmp_path))
    session = WorkbenchSession.open_persistent(project)

    assert session.source == "project"
    session.ledger.append("project_edit", {"op": "noop"})
    session.snapshots.save((), label="empty")

    spec_dir = Path(project.spec_dir)
    assert (spec_dir / "ledger.jsonl").exists()
    assert (spec_dir / "snapshots.jsonl").exists()


def test_open_persistent_ledger_continues_across_reopen(tmp_path: Path):
    project = lifecycle.create_project("myproj", str(tmp_path))
    session1 = WorkbenchSession.open_persistent(project)
    session1.set_mode("auto")
    session1.set_mode("manual")
    count_after_first_open = len(session1.ledger.entries)
    assert count_after_first_open >= 2

    reopened_project = lifecycle.open_project(project.spec_dir)
    session2 = WorkbenchSession.open_persistent(reopened_project)

    assert len(session2.ledger.entries) == count_after_first_open
    assert session2.ledger.verify() is True

    session2.set_mode("auto")
    assert len(session2.ledger.entries) == count_after_first_open + 1
    assert session2.ledger.verify() is True


def test_open_persistent_corrupted_ledger_raises_ledger_integrity_error(tmp_path: Path):
    project = lifecycle.create_project("myproj", str(tmp_path))
    session1 = WorkbenchSession.open_persistent(project)
    session1.set_mode("auto")

    ledger_path = Path(project.spec_dir) / "ledger.jsonl"
    raw = ledger_path.read_text(encoding="utf-8")
    # 【1 文字改竄】: 末尾の hash 16 進文字を書き換え、再計算突合でチェーン破損が検出されることを
    #   確認する (P2 無修復)。UTF-8 として妥当な文字での置換に留める (生バイト XOR は不正 UTF-8 に
    #   なり得て別の例外 [UnicodeDecodeError] を誘発してしまうため避ける)。
    corrupted = raw[:-6] + ("0" if raw[-6] != "0" else "1") + raw[-5:]
    assert corrupted != raw
    ledger_path.write_text(corrupted, encoding="utf-8")

    reopened_project = lifecycle.open_project(project.spec_dir)
    with pytest.raises(LedgerIntegrityError):
        WorkbenchSession.open_persistent(reopened_project)


def test_create_empty_session_is_source_none_with_null_project_path():
    session = WorkbenchSession.create_empty()

    assert session.source == "none"
    state = session.state()
    assert state["source"] == "none"
    assert state["project_path"] is None
    assert state["project"]["name"] is None

    vm = session.viewmodel()
    assert vm["datasets"] == []
    assert vm["phases"] == []
    assert vm["stages"] == []
    assert vm["phase_id"]["candidates"] == []
    assert vm["sequence"]["charts"] == []


def test_from_project_sets_project_path_when_spec_dir_is_real(tmp_path: Path):
    project = lifecycle.create_project("myproj", str(tmp_path))
    session = WorkbenchSession.from_project(project)

    state = session.state()
    assert state["project_path"] == str(Path(project.spec_dir) / "project.json")
