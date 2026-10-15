"""★backend の警告を**呼び出し側が捨てない** — ``.refine`` の全呼び出しを見る静的ガード + 集め口。

``RefinementResult.warnings`` は GSAS の structure_ref 経路の特殊位置吸着の記録 (とりわけ「多重度を
保証できず吸着しなかった」skipped) の**唯一の置き場**である (backend に ledger が無い)。消費側が
``result.warnings`` を読まずに捨てると、その経路では記録が無言で消える。

実害: PR #254 で段階精密化・pipeline・木探索・マルチスタート・逐次を直した後にも、joint 検証・
MEM-Rietveld 反復・区間自動分割・nested 物理尤度の 4 箇所が捨てていた (PR #255)。消費側ごとに
直しても、**次の消費側が同じ形で捨てるのを止めるものが無い**。

規則 (違反は ``<file>:<line>`` で報告する。対象は ``src/tsumugin`` の backend 実装 ``backends/`` 以外):

1. ``<…>.refine(...)`` の呼び出しは**受け手の名前を問わず**、その場で ``collect(...)`` の唯一の引数
   として渡す (``collector.collect(backend.refine(m))``)。代入してから後で読む・ヘルパから
   ``return`` して呼び出し側で読む、はどれも違反 — 読み忘れが痕跡を残さないため、集めることを
   呼び出しの形そのものにする。backend 以外の ``refine`` を足すときは ``_NOT_A_BACKEND`` に理由付きで
2. ``collect`` の受け手は**名前**で、同じ関数か外側の関数で ``WarningCollector`` と束縛されている
   (``= WarningCollector()`` / 型注釈 ``WarningCollector`` の引数・変数)。``gc.collect`` や別の集計器の
   ``collect`` では通らない
3. ``name = WarningCollector()`` で作った集め口は、``collect`` の受け手以外で**読まれる**
   (``.merged()`` / 他の関数へ渡す / 反復 / ``return``)。集めただけで結果に載せない形を止める

**網の限界 (正直に言う)**: 規則 3 は「読んだ」までで「結果の ``backend_warnings`` や ② の
``warnings`` へ載せた」までは見ない — それは振る舞いテスト
(`tests/test_backend_warnings_propagation.py`) が見る。``getattr(backend, "refine")`` 経由の呼び出し・
別の関数へ渡された集め口がその先で読まれるかは追わない。
"""

from __future__ import annotations

import ast
from pathlib import Path

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

#: ``RefinementBackend`` ではない ``.refine`` の呼び出し (``"<file>:<受け手>"`` → 理由)。今は無い。
_NOT_A_BACKEND: dict[str, str] = {}

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _is_refine(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "refine"
    )


def _is_collect_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "collect"
        and len(node.args) == 1
        and not node.keywords
    )


def _is_collector_ctor(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "WarningCollector"
    )


def _is_collector_annotation(node: ast.AST | None) -> bool:
    return node is not None and "WarningCollector" in ast.unparse(node)


def _bindings(func: ast.AST, name: str) -> list[bool] | None:
    """``func`` 自身が ``name`` を束縛する箇所ごとに「集め口として束縛したか」。束縛しなければ None。

    入れ子の関数の中の束縛は数えない (それは別の変数)。
    """
    found: list[bool] = []
    args = getattr(func, "args", None)
    if args is not None:
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
            if arg is not None and arg.arg == name:
                found.append(_is_collector_annotation(arg.annotation))
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, _FUNCS):
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    found.append(_is_collector_ctor(node.value))
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                found.append(_is_collector_annotation(node.annotation))
        elif isinstance(node, (ast.AugAssign, ast.NamedExpr, ast.For, ast.With)):
            targets = ast.walk(getattr(node, "target", None) or node)
            if any(isinstance(t, ast.Name) and t.id == name and isinstance(t.ctx, ast.Store)
                   for t in targets):
                found.append(False)
        stack.extend(ast.iter_child_nodes(node))
    return found or None


def _scan(path: Path) -> tuple[list[int], list[int]]:
    """(.refine の行, 規則 1-3 の違反行)。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing(node: ast.AST) -> list[ast.AST]:
        chain = []
        while node in parents:
            node = parents[node]
            if isinstance(node, _FUNCS):
                chain.append(node)
        return chain

    def is_collector_name(node: ast.AST) -> bool:
        if not isinstance(node, ast.Name):
            return False
        for func in enclosing(node):
            found = _bindings(func, node.id)
            if found is not None:
                return all(found)
        return False

    calls, bad = [], set()
    for node in ast.walk(tree):
        # 規則 1 + 2
        if _is_refine(node):
            calls.append(node.lineno)
            receiver = ast.unparse(node.func.value)
            if f"{path.name}:{receiver}" in _NOT_A_BACKEND:
                continue
            parent = parents.get(node)
            if not (
                _is_collect_call(parent)
                and parent.args[0] is node
                and is_collector_name(parent.func.value)
            ):
                bad.add(node.lineno)
        # 規則 3
        if isinstance(node, ast.Assign) and _is_collector_ctor(node.value):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            scope = (enclosing(node) or [tree])[0]
            for name in names:
                read = False
                for use in ast.walk(scope):
                    if not (isinstance(use, ast.Name) and use.id == name
                            and isinstance(use.ctx, ast.Load)):
                        continue
                    owner = parents.get(use)
                    is_collect_receiver = (
                        isinstance(owner, ast.Attribute) and owner.attr == "collect"
                    )
                    if not is_collect_receiver:
                        read = True
                        break
                if not read:
                    bad.add(node.lineno)
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
        ".refine(...) は WarningCollector の collect(...) に直接渡し、集め口は読むこと: "
        + ", ".join(violations)
    )


def _scan_text(tmp_path, text: str) -> tuple[list[int], list[int]]:
    src = tmp_path / "m.py"
    src.write_text(text, encoding="utf-8")
    return _scan(src)


def test_guard_rule1_refine_must_go_straight_into_collect(tmp_path):
    calls, bad = _scan_text(
        tmp_path,
        "def ok(backend, m, c: WarningCollector):\n"                  # 1
        "    return c.collect(backend.refine(m))\n"                     # 2
        "def assigned(backend, m, c: WarningCollector):\n"            # 3
        "    r = backend.refine(m)\n"                                   # 4
        "    return c.collect(r)\n"                                     # 5
        "def returned(self, m):\n"                                      # 6
        "    return self.backend.refine(m)\n"                           # 7
        "def wrapped_twice(backend, m, c: WarningCollector):\n"       # 8
        "    return c.collect(f(backend.refine(m)))\n"                  # 9
        "def other_name(engine, m):\n"                                  # 10
        "    return engine.refine(m)\n",                                # 11
    )
    assert calls == [2, 4, 7, 9, 11]
    assert bad == [4, 7, 9, 11]  # 受け手の名前が backend でなくても見る (11)


def test_guard_rule2_receiver_must_be_a_collector(tmp_path):
    calls, bad = _scan_text(
        tmp_path,
        "import gc\n"                                                   # 1
        "def local(backend, m):\n"                                      # 2
        "    c = WarningCollector()\n"                                  # 3
        "    r = c.collect(backend.refine(m))\n"                        # 4
        "    return r, c.merged()\n"                                    # 5
        "def closure(backend, m):\n"                                    # 6
        "    c = WarningCollector()\n"                                  # 7
        "    def inner():\n"                                            # 8
        "        return c.collect(backend.refine(m))\n"                 # 9
        "    inner()\n"                                                 # 10
        "    return c.merged()\n"                                       # 11
        "def annotated(backend, m, sink=None):\n"                       # 12
        "    s: WarningCollector = sink if sink else WarningCollector()\n"  # 13
        "    return s.collect(backend.refine(m))\n"                     # 14
        "def garbage(backend, m):\n"                                    # 15
        "    return gc.collect(backend.refine(m))\n"                    # 16
        "def untyped_param(backend, m, stats):\n"                       # 17
        "    return stats.collect(backend.refine(m))\n"                 # 18
        "def attribute(self, m):\n"                                     # 19
        "    return self.c.collect(self.backend.refine(m))\n"           # 20
        "def rebound(backend, m):\n"                                    # 21
        "    c = WarningCollector()\n"                                  # 22
        "    c = Other()\n"                                             # 23
        "    return c.collect(backend.refine(m)), list(c)\n",           # 24
    )
    assert bad == [16, 18, 20, 24]


def test_guard_rule3_collector_must_be_read(tmp_path):
    _calls, bad = _scan_text(
        tmp_path,
        "def merged(backend, m):\n"                                     # 1
        "    c = WarningCollector()\n"                                  # 2
        "    c.collect(backend.refine(m))\n"                            # 3
        "    return c.merged()\n"                                       # 4
        "def passed_on(backend, m):\n"                                  # 5
        "    c = WarningCollector()\n"                                  # 6
        "    c.collect(backend.refine(m))\n"                            # 7
        "    return finish(c)\n"                                        # 8
        "def only_collected(backend, m):\n"                             # 9
        "    c = WarningCollector()\n"                                  # 10
        "    return c.collect(backend.refine(m))\n"                     # 11
        "def inline(backend, m):\n"                                     # 12
        "    return WarningCollector().collect(backend.refine(m))\n",   # 13
    )
    assert bad == [10, 13]  # 13 は受け手が名前でない (規則 2) — 作って捨てる形


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
    assert list(WarningCollector()) == []
