"""★backend の警告を**呼び出し側が捨てない** — ``backend.refine`` の全呼び出しを見る静的ガード + 集め口。

``RefinementResult.warnings`` は GSAS の structure_ref 経路の特殊位置吸着の記録 (とりわけ「多重度を
保証できず吸着しなかった」skipped) の**唯一の置き場**である (backend に ledger が無い)。消費側が
``result.warnings`` を読まずに捨てると、その経路では記録が無言で消える。

実害: PR #254 で段階精密化・pipeline・木探索・マルチスタート・逐次を直した後にも、joint 検証・
MEM-Rietveld 反復・区間自動分割・nested 物理尤度の 4 箇所が捨てていた (PR #255)。消費側ごとに
直しても、**次の消費側が同じ形で捨てるのを止めるものが無い**。

規則 (違反は ``<file>:<line>`` で報告する): ``src/tsumugin`` (backend 実装 ``backends/`` を除く) の
``<…>backend.refine(...)`` / ``<…>_backend.refine(...)`` の呼び出しは、**その場で**
``WarningCollector.collect(...)`` の唯一の引数として渡す (``collector.collect(backend.refine(m))``)。
代入してから後で読む・ヘルパから ``return`` して呼び出し側で読む、はどれも違反 — 読み忘れが痕跡を
残さないため、集めることを呼び出しの形そのものにする。

**網の限界 (正直に言う)**: 受け手の名前が ``backend`` / ``_backend`` で終わる呼び出しだけを見る
(別名の変数に代入した backend・``getattr`` 経由は追わない)。集めた警告を結果の ``backend_warnings``
や ② の ``warnings`` へ**載せたか**は見ない — それは振る舞いテスト
(`tests/test_backend_warnings_propagation.py`) が見る。
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

from tsumugin.backends.base import RefinementResult, WarningCollector, merge_warnings

#: 走査対象。**テストファイルの位置から辿る** — editable install は main チェックアウトの src を
#: 指すので、`tsumugin.__file__` から辿ると worktree では別ツリーを検査してしまう。
_SRC = Path(__file__).resolve().parents[1] / "src" / "tsumugin"

#: 網が実際にこれらの呼び出しを見ていること (走査先を取り違えると 0 件で黙って緑になる)。
#: 呼び出しを移した/消したときは意識的にここを更新する。
_KNOWN_CALLERS = frozenset({
    "joint/engine.py",
    "mem/iterate.py",
    "multistart/engine.py",
    "nested/physical.py",
    "operando/discrimination.py",
    "operando/segmentation.py",
    "refinement/staged.py",
    "search/tree.py",
    "sequential/engine.py",
})


def _is_backend_refine(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr != "refine":
        return False
    receiver = node.func.value
    name = receiver.attr if isinstance(receiver, ast.Attribute) else getattr(receiver, "id", "")
    return name.endswith("backend")


def _is_collect_of(parent: ast.AST, child: ast.AST) -> bool:
    return (
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Attribute)
        and parent.func.attr == "collect"
        and len(parent.args) == 1
        and parent.args[0] is child
        and not parent.keywords
    )


def _scan(path: Path) -> tuple[list[int], list[int]]:
    """(backend.refine の行, そのうち collect に直接渡していない行)。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    calls, bad = [], []
    for node in ast.walk(tree):
        if _is_backend_refine(node):
            calls.append(node.lineno)
            if not _is_collect_of(parents.get(node), node):
                bad.append(node.lineno)
    return sorted(calls), sorted(bad)


def test_no_src_caller_drops_backend_warnings():
    callers: set[str] = set()
    violations: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        if rel.startswith("backends/"):
            continue
        calls, bad = _scan(path)
        if calls:
            callers.add(rel)
        violations.extend(f"{rel}:{line}" for line in bad)

    assert callers == _KNOWN_CALLERS
    assert violations == [], (
        "backend.refine(...) は WarningCollector.collect(...) に直接渡すこと: " + ", ".join(violations)
    )


def test_guard_flags_the_forms_that_drop_warnings(tmp_path):
    # 網そのものの検査 — 捨てる形を違反に、集める形を合格にする
    src = tmp_path / "m.py"
    src.write_text(
        "def ok(c, backend, m):\n"
        "    return c.collect(backend.refine(m))\n"
        "def ok_attr(self, m):\n"
        "    r = self.warnings.collect(self._backend.refine(m, max_cycles=5))\n"
        "def assigned(backend, m):\n"
        "    r = backend.refine(m)\n"
        "    return r\n"
        "def returned(self, m):\n"
        "    return self.backend.refine(m)\n"
        "def wrapped_twice(c, backend, m):\n"
        "    return c.collect(f(backend.refine(m)))\n"
        "def not_a_backend(engine, m):\n"
        "    return engine.refine(m)\n",
        encoding="utf-8",
    )
    calls, bad = _scan(src)
    assert calls == [2, 4, 6, 9, 11]
    assert bad == [6, 9, 11]


def _result(*warnings: str) -> RefinementResult:
    return RefinementResult(
        phases=(), chi2=1.0, rwp=1.0, n_obs=1, n_params=0, converged=True, n_cycles=1,
        free_params=frozenset(), warnings=warnings,
    )


def test_collect_returns_the_result_unchanged():
    result = _result("a")
    assert WarningCollector().collect(result) is result


def test_merged_equals_merge_warnings_of_every_raw_warning():
    # 精密化ごとの文を全部並べて merge_warnings した結果と同じ (同じ文は数えない・同種は畳む)
    raw = [("note A", "s=0.1"), ("note A", "s=0.2"), ("s=0.1", "note B"), ("s=0.3",)]
    collector = WarningCollector()
    for group in raw:
        collector.collect(_result(*group))

    assert collector.merged() == merge_warnings(*raw)
    assert collector.merged() == ("note A", "s=0.1 [同種の文 ほか 2 件]", "note B")


def test_raw_warnings_are_stored_once():
    # sampler が何千回も呼ぶ経路 — 同じ文で列を伸ばさない
    collector = WarningCollector()
    for _ in range(1000):
        collector.collect(_result("note A", "note B"))
    assert list(collector) == ["note A", "note B"]


def test_extend_merged_keeps_folded_counts():
    # 子の結果 (畳み済み) は数え直すので重複除去しない — 2 フレームの同じ畳み済み文は件数が足される
    child = merge_warnings(["rwp=1.5%", "rwp=2.5%"])
    collector = WarningCollector()
    collector.extend_merged(child)
    collector.extend_merged(child)
    collector.collect(_result("rwp=3.5%"))

    assert collector.merged() == merge_warnings(child, child, ["rwp=3.5%"])
    assert collector.merged() == ("rwp=1.5% [同種の文 ほか 3 件]",)


def test_iteration_feeds_merge_warnings_in_order():
    collector = WarningCollector()
    collector.collect(_result("b"))
    collector.extend_merged(("a",))
    assert merge_warnings(["z"], collector) == ("z", "b", "a")


def test_empty_collector_merges_to_nothing():
    assert WarningCollector().merged() == ()
    assert np.asarray(list(WarningCollector())).size == 0
