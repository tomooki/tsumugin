"""プロジェクトライフサイクル (create/open/save/recent) — V2a P1/P2
(`docs/design/gui-workbench/api-contract.md` §プロジェクトライフサイクル)。

プロジェクト = ディレクトリ + ``project.json`` (spec スキーマは ② ``auto_rietveld`` と同一・
`project.WorkbenchProject`/``load_project_spec`` を再利用) + ``data/`` (取り込みファイル) +
``ledger.jsonl``/``snapshots.jsonl`` (永続 ledger/snapshot, `store.persistent`) + ``workbench_out/``。

本モジュールはファイルシステム操作 (ディレクトリ作成・spec 書き戻し・recent 一覧の永続化) のみを
担う。永続 ledger/snapshot の実体配線は `session.WorkbenchSession.open_persistent` の責務。
"""

from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from typing import Any

from .project import WorkbenchProject, load_project_spec

__all__ = [
    "PROJECT_JSON_NAME",
    "create_project",
    "open_project",
    "save_project_spec",
    "sanitize_filename",
    "load_recent",
    "add_recent",
]

#: プロジェクトディレクトリ直下の spec ファイル名 (`api-contract.md` §プロジェクトライフサイクル)。
PROJECT_JSON_NAME = "project.json"

#: recent 一覧の保持上限 (api-contract.md GET /api/project/recent)。
_RECENT_MAX = 10


def _recent_path() -> Path:
    """``~/.tsumugin/workbench_recent.json`` (``Path.home()`` は呼び出し時に解決 — テストで monkeypatch 可)。"""
    return Path.home() / ".tsumugin" / "workbench_recent.json"


def create_project(name: str, directory: "str | Path") -> WorkbenchProject:
    """``<directory>/<name>/`` を新規作成し空 project.json + ``data/``/``workbench_out/`` を用意する。

    :raises ValueError: ``<directory>/<name>/`` が既に存在するとき (呼び出し側 [`app.py`] が
        409 へ縮退する, api-contract.md)。
    """
    base = Path(directory)
    target = base / name
    if target.exists():
        raise ValueError(f"ディレクトリが既に存在します: {target}")
    target.mkdir(parents=True)
    (target / "data").mkdir()
    (target / "workbench_out").mkdir()
    spec: dict[str, Any] = {
        "name": name,
        "histograms": [],
        "phases": [],
        "background_coeffs": 6,
        "max_cyc": 12,
    }
    (target / PROJECT_JSON_NAME).write_text(
        json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    project = load_project_spec(target / PROJECT_JSON_NAME, allow_empty=True)
    add_recent(project.name, str(target.resolve()))
    return project


def open_project(path: "str | Path") -> WorkbenchProject:
    """project.json (またはそのディレクトリ) を読み ``WorkbenchProject`` を返す。

    ``path`` がディレクトリなら ``<path>/project.json`` を補って読む。ヒストグラム/相 0 件の
    (作成直後・未設定の) プロジェクトも許容する (``allow_empty=True``)。

    型でエラー種別を区別する (呼び出し側 [`app.py`] のマッピング, セルフレビュー指摘 #3):

    :raises FileNotFoundError: ``path`` (または ``<path>/project.json``) 自体が存在しないとき
        (呼び出し側は 404 NotFoundError へ縮退する)。
    :raises ValueError: spec の内容が不正 (JSON 壊れ/必須キー欠落/不正 enum/参照データファイル欠落
        等) のとき (呼び出し側は 422 ValueError へ縮退する)。
    """
    p = Path(path)
    if p.is_dir():
        p = p / PROJECT_JSON_NAME
    if not p.exists():
        raise FileNotFoundError(f"プロジェクトが見つかりません: {p}")
    project = load_project_spec(p, allow_empty=True)
    add_recent(project.name, str(p.resolve().parent))
    return project


def save_project_spec(project: WorkbenchProject) -> None:
    """``project`` を ``<spec_dir>/project.json`` へ書き戻す (全ての spec 変更で自動保存)。

    パスは spec ディレクトリ配下にあれば相対化して書く (プロジェクトディレクトリごと移動しても
    壊れないよう自己完結性を保つ)。範囲外の絶対パスはそのまま書く。
    """
    spec_dir = Path(project.spec_dir).resolve()

    histograms: list[dict[str, Any]] = []
    for h in project.histograms:
        d = h.to_dict()
        d["data_path"] = _relpath(spec_dir, h.data_path)
        d["instrument_path"] = _relpath(spec_dir, h.instrument_path)
        histograms.append(d)

    phases: list[dict[str, Any]] = []
    for p in project.phases:
        d = p.to_dict()
        d["structure_path"] = _relpath(spec_dir, p.structure_path)
        display = project.phase_display.get(p.phase_name)
        if display:
            d["display"] = dict(display)
        phases.append(d)

    spec = {
        "name": project.name,
        "background_coeffs": project.background_coeffs,
        "max_cyc": project.max_cyc,
        "histograms": histograms,
        "phases": phases,
    }
    (spec_dir / PROJECT_JSON_NAME).write_text(
        json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _relpath(base: Path, raw: str) -> str:
    """``raw`` を ``base`` 基準の相対パスへ変換する (範囲外ならそのまま絶対パス)。"""
    p = Path(raw)
    try:
        return str(p.relative_to(base))
    except ValueError:
        return str(p)


def sanitize_filename(name: str) -> str:
    """アップロードファイル名からディレクトリ区切り・パストラバーサルを除去する (P2 upload)。

    ``os.path.basename`` でディレクトリ部を落とし、英数字・``.``・``-``・``_`` 以外を ``_`` に置換する。
    結果が空または ``.``/``..`` のみになる場合は ``"file"`` に丸める (親ディレクトリへの脱出を防ぐ)。
    """
    base = os.path.basename(str(name).replace("\\", "/"))
    base = re.sub(r"[^\w.\-]", "_", base)
    if not base or set(base) <= {"."}:
        base = "file"
    return base


def load_recent() -> list[dict[str, Any]]:
    """``~/.tsumugin/workbench_recent.json`` から recent 一覧を読む (無ければ空リスト)。"""
    path = _recent_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [dict(e) for e in data if isinstance(e, dict)]


def add_recent(name: str, path: str) -> None:
    """recent 一覧の先頭へ ``{name, path, last_opened}`` を積む (同一 path は移動・重複させない, 最大10件)。"""
    entries = [e for e in load_recent() if e.get("path") != path]
    entries.insert(0, {"name": name, "path": path, "last_opened": _now_iso()})
    entries = entries[:_RECENT_MAX]
    recent_path = _recent_path()
    recent_path.parent.mkdir(parents=True, exist_ok=True)
    recent_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
