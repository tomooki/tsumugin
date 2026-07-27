"""``tsumugin.workbench.fsbrowse`` のテスト (アプリ内ファイル選択ウィンドウ用 fs 列挙 API)。

契約: `docs/design/gui-workbench/api-contract.md` §ファイル選択 (Welcome のファイル選択ウィンドウ)。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tsumugin.workbench import fsbrowse


# ---------------------------------------------------------------------------
# list_roots
# ---------------------------------------------------------------------------


def test_list_roots_includes_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    roots = fsbrowse.list_roots()

    assert {"path": str(fake_home), "label": "Home"} in roots


def test_list_roots_windows_includes_existing_drive_letters_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(fsbrowse.os, "name", "nt")

    def _fake_exists(path: str) -> bool:
        return path == "C:\\"

    monkeypatch.setattr(fsbrowse.os.path, "exists", _fake_exists)

    roots = fsbrowse.list_roots()

    drive_paths = [r["path"] for r in roots if r["path"] != str(fake_home)]
    assert drive_paths == ["C:\\"]


def test_list_roots_posix_includes_slash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(fsbrowse.os, "name", "posix")

    roots = fsbrowse.list_roots()

    assert {"path": "/", "label": "/"} in roots


# ---------------------------------------------------------------------------
# list_dir: フィルタ・並び順・is_project
# ---------------------------------------------------------------------------


@pytest.fixture()
def populated_dir(tmp_path: Path) -> Path:
    """dir/dir_with_project/.json/.txt/.cif の混在ディレクトリを用意する。"""
    root = tmp_path / "root"
    root.mkdir()
    (root / "zeta_dir").mkdir()
    (root / "alpha_dir").mkdir()
    project_dir = root / "beta_project"
    project_dir.mkdir()
    (project_dir / "project.json").write_text("{}", encoding="utf-8")
    (root / "config.json").write_text("{}", encoding="utf-8")
    (root / "notes.txt").write_text("not json", encoding="utf-8")
    (root / "structure.cif").write_text("data_x", encoding="utf-8")
    return root


def test_list_dir_filters_to_dirs_and_json_only(populated_dir: Path):
    result = fsbrowse.list_dir(str(populated_dir))
    names = {e["name"] for e in result["entries"]}
    assert names == {"zeta_dir", "alpha_dir", "beta_project", "config.json"}
    assert "notes.txt" not in names
    assert "structure.cif" not in names


def test_list_dir_sorts_directories_first_then_name_ascending(populated_dir: Path):
    result = fsbrowse.list_dir(str(populated_dir))
    names = [e["name"] for e in result["entries"]]
    assert names == ["alpha_dir", "beta_project", "zeta_dir", "config.json"]


def test_list_dir_marks_is_project_for_directory_with_project_json(populated_dir: Path):
    result = fsbrowse.list_dir(str(populated_dir))
    by_name = {e["name"]: e for e in result["entries"]}
    assert by_name["beta_project"]["is_project"] is True
    assert by_name["alpha_dir"]["is_project"] is False
    assert by_name["zeta_dir"]["is_project"] is False


def test_list_dir_json_file_entry_is_project_always_false(populated_dir: Path):
    result = fsbrowse.list_dir(str(populated_dir))
    by_name = {e["name"]: e for e in result["entries"]}
    assert by_name["config.json"]["is_dir"] is False
    assert by_name["config.json"]["is_project"] is False


def test_list_dir_entry_shape(populated_dir: Path):
    result = fsbrowse.list_dir(str(populated_dir))
    for entry in result["entries"]:
        assert set(entry.keys()) == {"name", "path", "is_dir", "is_project"}


def test_list_dir_hidden_json_file_is_not_excluded(tmp_path: Path):
    """隠しファイル (先頭 '.') は除外しない方針 — .tsumugin 等をユーザが選べるようにする。"""
    root = tmp_path / "root"
    root.mkdir()
    (root / ".hidden.json").write_text("{}", encoding="utf-8")

    result = fsbrowse.list_dir(str(root))

    names = {e["name"] for e in result["entries"]}
    assert ".hidden.json" in names


# ---------------------------------------------------------------------------
# list_dir: path / parent
# ---------------------------------------------------------------------------


def test_list_dir_returns_absolute_path_and_parent(tmp_path: Path):
    child = tmp_path / "child"
    child.mkdir()
    result = fsbrowse.list_dir(str(child))
    assert result["path"] == str(child.resolve())
    assert result["parent"] == str(child.resolve().parent)


def test_list_dir_at_filesystem_root_has_no_parent(monkeypatch: pytest.MonkeyPatch):
    if os.name == "nt":
        root_str = os.environ.get("SystemDrive", "C:") + "\\"
    else:
        root_str = "/"
    result = fsbrowse.list_dir(root_str)
    assert result["parent"] is None


# ---------------------------------------------------------------------------
# list_dir: エラー種別
# ---------------------------------------------------------------------------


def test_list_dir_missing_path_raises_file_not_found(tmp_path: Path):
    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        fsbrowse.list_dir(str(missing))


def test_list_dir_file_path_raises_not_a_directory(tmp_path: Path):
    file_path = tmp_path / "a_file.json"
    file_path.write_text("{}", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        fsbrowse.list_dir(str(file_path))


def test_list_dir_permission_error_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "root"
    root.mkdir()

    def _raise_permission_error(self):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "iterdir", _raise_permission_error)

    with pytest.raises(PermissionError):
        fsbrowse.list_dir(str(root))


def test_list_dir_skips_unreadable_entry_without_failing_whole_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """列挙できない (is_dir が失敗する) entry が 1 つあっても全体を落とさない。"""
    root = tmp_path / "root"
    root.mkdir()
    (root / "good_dir").mkdir()
    (root / "bad.json").write_text("{}", encoding="utf-8")

    real_is_dir = Path.is_dir

    def _flaky_is_dir(self: Path) -> bool:
        if self.name == "bad.json":
            raise OSError("simulated stat failure")
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", _flaky_is_dir)

    result = fsbrowse.list_dir(str(root))

    names = {e["name"] for e in result["entries"]}
    assert names == {"good_dir"}


def test_list_dir_project_dir_check_does_not_raise_on_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """is_project 判定中の権限エラーは個別に false へ倒す (呼び出し全体は失敗しない)。"""
    root = tmp_path / "root"
    root.mkdir()
    (root / "sub_dir").mkdir()

    def _raise_permission_error(self: Path) -> bool:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "is_file", _raise_permission_error)

    result = fsbrowse.list_dir(str(root))

    by_name = {e["name"]: e for e in result["entries"]}
    assert by_name["sub_dir"]["is_project"] is False


# ---------------------------------------------------------------------------
# 変異実証: .json 以外のファイルが漏れないフィルタ
# ---------------------------------------------------------------------------


def test_mutation_proof_non_json_filter_would_leak_without_suffix_check(populated_dir: Path):
    """``child.suffix == ".json"`` チェックを外すと non-json ファイルが混入することを実証する
    (ガードが機能していることの変異実証 — 落ちないガードは無いより悪い, CLAUDE.md)。
    """
    root = populated_dir

    def _list_dir_without_json_filter(path: str) -> dict:
        target = Path(path).resolve()
        entries = []
        for child in target.iterdir():
            if child.is_dir():
                entries.append({"name": child.name, "is_dir": True})
            else:
                # 【意図的に壊した版】: suffix チェックを外し全ファイルを通す
                entries.append({"name": child.name, "is_dir": False})
        return {"entries": entries}

    mutated = _list_dir_without_json_filter(str(root))
    mutated_names = {e["name"] for e in mutated["entries"]}
    assert "notes.txt" in mutated_names  # 変異版は漏れる

    real = fsbrowse.list_dir(str(root))
    real_names = {e["name"] for e in real["entries"]}
    assert "notes.txt" not in real_names  # 実装は漏れない
