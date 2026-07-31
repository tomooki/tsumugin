"""ベンチマーク成果物の由来宣言ガード (公開リポジトリの安全弁)。

**なぜ要るか** (実際に起きた事故): v0.1 公開時、未公開実験データ (NaCuHCF·nD₂O) の精密化結果
— Rwp・占有率と esd — が `docs/benchmark/joint/results/` と `docs/benchmark/README.md` の
両方に載ったまま public になった。`.gitignore` は `results/*.gpx` と**拡張子スコープ**だった
ため、同じ精密化から出る csv/log が網から漏れていた。生データ (.gpx) は一度も追跡されて
いなかったので「守れている」ように見えていたのが厄介なところである。

「気をつける」では再発する。**由来を宣言させ、宣言と追跡状態の食い違いを機械検査する** —
①②③ の露出で採っているのと同じ型 (黙ってやらせず、宣言させる)。

本ガードが答える問いは 1 つ: **公開リポジトリに追跡されている各ファイルは、公開してよいと
誰かが明示的に判断したものか**。判断していない (宣言が無い) ものは落とす。
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

_BENCHMARK = Path("docs/benchmark")
_MANIFEST = _BENCHMARK / "provenance.toml"

#: 追跡を許す由来。`private` は**測定値を追跡できない** (例外は個別宣言が要る)。
_PUBLISHABLE = frozenset({"public", "synthetic"})
_ALL_PROVENANCE = _PUBLISHABLE | {"private"}


def _tracked_under(path: Path) -> "list[str]":
    """``path`` 配下で git が追跡しているファイル (リポジトリ相対 POSIX パス)。

    **git に聞く**のが要点 — ディスクを walk すると gitignore 済みの成果物まで拾ってしまい、
    「公開されているか」という問いに答えられない。
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", path.as_posix()],
        capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert _MANIFEST.is_file(), f"{_MANIFEST} が無い"
    return tomllib.loads(_MANIFEST.read_text(encoding="utf-8"))["entries"]


def _top_level_entries() -> "set[str]":
    """追跡ファイルを持つ `docs/benchmark/` 直下のエントリ名。"""
    names: set[str] = set()
    for tracked in _tracked_under(_BENCHMARK):
        rest = Path(tracked).relative_to(_BENCHMARK).parts
        if rest and rest[0] != _MANIFEST.name:
            names.add(rest[0])
    return names


def test_every_tracked_entry_declares_its_provenance(manifest: dict):
    """**宣言の無い追跡エントリを作らせない**。

    新しいベンチを足して結果を commit した瞬間にここが落ちる。「公開してよいか」を
    その場で考えさせるのが目的で、考えた結果 public なら 1 行足すだけで通る。
    """
    undeclared = sorted(_top_level_entries() - set(manifest))
    assert not undeclared, (
        f"由来が宣言されていないベンチ成果物がある: {undeclared}。"
        f"{_MANIFEST} に provenance を追加すること (public/synthetic/private)"
    )


def test_declarations_are_not_stale(manifest: dict):
    """**消えたエントリの宣言を残さない** (宣言が現実と乖離すると読む人を誤らせる)。"""
    orphaned = sorted(set(manifest) - _top_level_entries())
    assert not orphaned, (
        f"追跡ファイルが無いのに宣言だけ残っている: {orphaned}。{_MANIFEST} から消すこと"
    )


@pytest.mark.parametrize("field", ["provenance"])
def test_required_fields_are_present(manifest: dict, field: str):
    missing = sorted(name for name, entry in manifest.items() if field not in entry)
    assert not missing, f"{field} が無いエントリ: {missing}"


def test_provenance_values_are_from_the_closed_vocabulary(manifest: dict):
    """語彙を閉じる — 綴り違い (`Public`/`opensource` 等) が黙って通ると宣言が意味を失う。"""
    bad = {n: e["provenance"] for n, e in manifest.items()
           if e["provenance"] not in _ALL_PROVENANCE}
    assert not bad, f"未知の provenance: {bad} (許容: {sorted(_ALL_PROVENANCE)})"


def test_public_entries_state_their_source(manifest: dict):
    """`public` は**出典を書かせる**。「公開データです」だけでは後から検算できない。"""
    missing = sorted(
        name for name, entry in manifest.items()
        if entry["provenance"] == "public" and not entry.get("source", "").strip()
    )
    assert not missing, f"public なのに source が無い: {missing}"


def test_private_entries_track_nothing_beyond_declared_exceptions(manifest: dict):
    """**これが本体**: 未公開データのエントリで、宣言していないファイルが追跡されていないこと。

    今回の事故 (`joint/results/` の 4 ファイル) はまさにこれで落ちる。例外は
    `tracked_exceptions` に 1 件ずつ挙げさせる — 再生成スクリプトのように測定値を含まない
    ものだけを、意識的に通す。
    """
    for name, entry in manifest.items():
        if entry["provenance"] != "private":
            continue
        allowed = set(entry.get("tracked_exceptions", []))
        root = _BENCHMARK / name
        actual = {
            Path(p).relative_to(root).as_posix() for p in _tracked_under(root)
        }
        leaked = sorted(actual - allowed)
        assert not leaked, (
            f"未公開データ '{name}' の未宣言ファイルが追跡されている: {leaked}。"
            f"測定値なら追跡から外し、そうでなければ tracked_exceptions に理由付きで足すこと"
        )


def test_declared_exceptions_actually_exist(manifest: dict):
    """例外宣言が現実と合っていること (消えたファイルの例外が残ると網が緩む)。"""
    for name, entry in manifest.items():
        root = _BENCHMARK / name
        actual = {Path(p).relative_to(root).as_posix() for p in _tracked_under(root)}
        ghosts = sorted(set(entry.get("tracked_exceptions", [])) - actual)
        assert not ghosts, f"'{name}' の tracked_exceptions に実在しないファイル: {ghosts}"


def test_results_directories_are_ignored_by_default():
    """**測定結果の出力先は既定で ignore** — 拡張子スコープでは漏れる (今回の直接原因)。

    `.gitignore` が `results/*.gpx` のように拡張子で切っていると、同じ精密化から出る
    csv/log が網の外になる。ディレクトリごと落とし、公開したいものだけ `git add -f` で
    上げる (既定を安全側に倒す)。
    """
    ignored = Path(".gitignore").read_text(encoding="utf-8")
    assert "docs/benchmark/joint/results/" in ignored
    assert "docs/benchmark/joint/results/*." not in ignored, (
        "拡張子スコープの ignore は同じ出力ディレクトリの別形式を取りこぼす"
    )
