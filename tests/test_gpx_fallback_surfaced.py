"""★成果物の退避理由を**呼び出し側が捨てない** — `gpxstore` の解決関数の全呼び出しを見る静的ガード。

`gpxstore.group_context` / `series_context` / `resolve_run_dir` は ``(値, 退避理由)`` を返す。
理由が非空なのは、頼まれた根 (``gpx_dir`` / データ隣接) に run ディレクトリを作れず**一時領域へ
退避した**ときである (gpx-retention 設計 §5「temp へ退避し理由を ledger」)。理由は**解決した入口で
しか分からない** — エンジンは解決済みの文脈を受け取るだけで、しかもファンアウト経路 (探索 /
マルチスタート / 収束確認 / モデル比較 / 修復 / 系列 / M8 閉ループ) ではエンジンの台帳は呼び出し側が
見ない私有の台帳である。入口が理由を捨てると、成果物が %TEMP% に置かれたことは**どこにも残らない**。

実害: `group, _reason = group_context(...)` の形で捨てていた入口が複数あり (探索 / マルチスタート /
モデル比較 / 修復は個別に直した)、直した後にも `refine_loop.orchestrator` に 1 件残っていた。
入口ごとに直しても、**次の呼び出し側が同じ形で捨てるのを止めるものが無い**。

規則 (違反は ``<file>:<line>`` で報告する):

1. 呼び出しの戻り値は**その場で 2 つの名前に分解する** (``ctx, reason = group_context(...)``)。
   添字 (``[0]``) ・単一名への代入・式文として捨てる・他の式へ埋め込む、はどれも違反
2. 理由の名前は ``_`` で始めない (``_`` / ``_reason`` は「捨てた」の宣言である)
3. 理由は分解の**後で、上書きされる前に**読まれる。読みは同じ関数の中 (入れ子の関数も含むが、
   同じ名前を自分で束縛する入れ子の関数・内包表記の中は別の変数なので数えない)。代入しただけ /
   ``del`` しただけ / 分解より前にしか現れない / 読む前に上書き、はどれも違反
4. 理由を**呼び出し側へ転送するだけ**の形 (``return group_context(...)`` / ``return ctx, reason`` /
   ``return reason`` / ``yield ctx, reason`` / 条件式の枝に詰めた ``return``) は `gpxstore` 自身の
   解決関数の中だけ。外で許すと、その関数が新しい解決関数になり、その呼び出し側が網から外れる

解決関数は**どの module からの import でも名前で**追う (``from ..autorietveld.search import
group_context`` のような再輸出経由も。同名の別関数が src に無いことは別テストが固定する)。

**網の限界 (正直に言う)**: 「読んだ」は「ledger/警告に載せた」ではない — ``if reason: pass`` は
通る。網が止めるのは**うっかり捨てる形**であり、載せる先が正しいか (台帳の種別・② の
``warnings``) は入口ごとの振る舞いテスト
(`tests/autorietveld/test_gpx_fanout.py::test_fanout_entries_record_a_fallback_to_temp` ほか) が
見る。順序は行・列の位置で見るので、分岐 (片方の枝でだけ上書き) やループの 2 周目は区別しない。
解決関数を別名の変数へ代入して呼ぶ (``f = group_context; f(...)``) 形も追わない。
``ArtifactPlan.fallback_reason`` (エンジンが `plan_output` から受け取る側) は本網の対象外で、両エンジンの
``_save_*_artifact`` が読んでいることは各エンジンのテストが見る。

**なぜ型 (`GpxContext` に理由を載せる) にしなかったか**: 理由を文脈に載せてエンジンの
``_save_gpx_artifact`` に ``m7_gpx_fallback`` を書かせる案は、ファンアウト経路ではエンジンの台帳が
私有 (呼び出し側へ返らない) なので**誰も見ない台帳に書くだけ**になる — 「構造的に記録される」ように
見えて実際は黙って消える。さらに属性にすると「読み忘れ」が呼び出し側に**何の痕跡も残さない**
(``_reason`` すら書かれない) ので、捨てたことがかえって見えなくなる。詳細は設計 §5。

変異検査で実証済 (実ソースへの変異で `test_no_src_caller_discards_the_fallback_reason` が fail):
``refine_loop.orchestrator`` を修正前の ``group, _reason =`` に戻す / ``compare.py`` の警告行を
``warnings = ()`` に置き換える (理由が未使用) / ``search.py`` を ``group_context(...)[0]`` にする /
``gpxstore.series_context`` が理由の代わりに ``""`` を返す / ``insitu.engine._series_context`` で
分解直後に ``reason = ""`` と上書きする / ``insitu.repair._repair_group`` が台帳に書かず
``return group, gpx_fallback`` で転送する。
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

#: 走査対象。**テストファイルの位置から辿る** — editable install は main チェックアウトの src を
#: 指すので、`tsumugin.__file__` から辿ると worktree では別ツリーを検査してしまう。
_SRC = Path(__file__).resolve().parents[1] / "src" / "tsumugin"
_GPXSTORE = _SRC / "gpxstore.py"

#: ``(値, 退避理由)`` を返す解決関数。
_RESOLVERS = frozenset({"group_context", "series_context", "resolve_run_dir"})

#: 網が実際にこれらの呼び出しを見ていること (走査先を取り違えると 0 件で黙って緑になる)。
#: 呼び出しを移した/消したときは意識的にここを更新する。
_KNOWN_CALLERS = frozenset({
    "gpxstore.py",
    "autorietveld/search.py",
    "autorietveld/multistart.py",
    "autorietveld/confirm.py",
    "autorietveld/compare.py",
    "insitu/engine.py",
    "insitu/repair.py",
    "refine_loop/orchestrator.py",
})

_Scope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _resolver_names(tree: ast.AST, *, defines_resolvers: bool) -> dict[str, str]:
    """この module で解決関数を指すローカル名 → 解決関数名。

    ``as`` 別名・関数内 import・``import *`` も拾う (どれも名前呼び出しで網を抜けうる)。
    **どの module からの import でも名前で拾う** — 解決関数は gpxstore 以外の module にも
    import 済みの名前として居るので、IDE の自動 import が ``from ..autorietveld.search import
    group_context`` のような再輸出経由を選ぶことがある。src に同名の別関数は無い
    (`test_resolver_names_are_unique_in_src` が保証する) ので、名前で拾っても誤検出しない。
    """
    names = {r: r for r in _RESOLVERS} if defines_resolvers else {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    names.update({r: r for r in _RESOLVERS})
                elif alias.name in _RESOLVERS:
                    names[alias.asname or alias.name] = alias.name
    return names


def _called_resolver(call: ast.Call, names: dict[str, str]) -> str | None:
    """呼び出しが解決関数なら その名前 (``gpxstore.group_context(...)`` の属性呼び出しも)。"""
    func = call.func
    if isinstance(func, ast.Name):
        return names.get(func.id)
    if isinstance(func, ast.Attribute) and func.attr in _RESOLVERS:
        return func.attr
    return None


def _own_scope(fn: ast.AST) -> list[ast.AST]:
    """関数本体のうち**その関数自身のスコープ**に属するノード (入れ子の関数・クラス・内包表記の
    中へは降りない — そこでの代入はそれぞれの変数であって、この関数の束縛ではない)。"""
    out: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, *_COMPREHENSIONS)
        ):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


def _rebinds(node: ast.AST, name: str) -> bool:
    """入れ子の関数/内包表記が ``name`` を**自分の変数として**束縛するか (= 外の理由とは別物)。"""
    if isinstance(node, _COMPREHENSIONS):
        return any(
            isinstance(t, ast.Name) and t.id == name
            for gen in node.generators
            for t in ast.walk(gen.target)
        )
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return False
    a = node.args
    params = [*a.posonlyargs, *a.args, *a.kwonlyargs, *(p for p in (a.vararg, a.kwarg) if p)]
    if any(p.arg == name for p in params):
        return True
    if isinstance(node, ast.Lambda):
        return False
    own = _own_scope(node)
    if any(isinstance(n, (ast.Nonlocal, ast.Global)) and name in n.names for n in own):
        return False
    return any(
        isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Store) for n in own
    )


def _occurrences(scope: ast.AST, name: str) -> list[ast.Name]:
    """``scope`` の中の ``name`` の出現 (同名を自前で束縛する入れ子の中は除く)。"""
    out: list[ast.Name] = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if _rebinds(node, name):
            continue
        if isinstance(node, ast.Name) and node.id == name:
            out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def _pos(node: ast.AST) -> tuple[int, int]:
    return (node.lineno, node.col_offset)  # type: ignore[attr-defined]


def _scan(source: str, *, defines_resolvers: bool = False) -> tuple[list[int], list[str]]:
    """``(解決関数の呼び出し行, 違反)`` を返す。違反は ``"<line> <resolver>: <理由>"``。"""
    tree = ast.parse(source)
    names = _resolver_names(tree, defines_resolvers=defines_resolvers)
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def enclosing_scope(node: ast.AST) -> _Scope:
        cur = parent.get(node)
        while cur is not None and not isinstance(cur, _Scope):
            cur = parent.get(cur)
        return cur if cur is not None else tree  # type: ignore[return-value]

    def forwarded(load: ast.Name, scope: _Scope) -> bool:
        """``return reason`` / ``return ctx, reason`` / ``yield ctx, reason`` — 読まずに呼び出し側へ
        渡すだけの形。条件式の枝に詰めた形 (``return (ctx, reason) if … else …``) も同じ。

        **解決した関数自身の** ``return``/``yield`` だけを数える。入れ子の関数 (閉包) が理由を
        返すのはその関数を呼んだ側が読むという意味なので、転送ではなく読みである。条件式の
        **条件**に使うのも読みである (理由で分岐している)。
        """
        child: ast.AST = load
        up = parent.get(load)
        while isinstance(up, ast.Tuple) or (isinstance(up, ast.IfExp) and child is not up.test):
            child, up = up, parent.get(up)
        return isinstance(up, (ast.Return, ast.Yield, ast.YieldFrom)) and (
            enclosing_scope(up) is scope
        )

    sites: list[int] = []
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        resolver = _called_resolver(node, names)
        if resolver is None:
            continue
        sites.append(node.lineno)

        def bad(why: str, node: ast.Call = node, resolver: str = resolver) -> None:
            violations.append(f"{node.lineno} {resolver}: {why}")

        holder = parent.get(node)
        scope = enclosing_scope(node)
        # 【転送してよいのは gpxstore 自身の解決関数だけ】: 外で許すとその関数が新しい解決関数に
        #   なり、その呼び出し側が網から外れる。
        own_resolver = (
            defines_resolvers
            and isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
            and scope.name in _RESOLVERS
        )
        if isinstance(holder, ast.Return):
            if not own_resolver:
                bad("素通しで返している — 呼び出し側が網から外れる (分解して理由を扱うこと)")
            continue
        targets = holder.targets if isinstance(holder, ast.Assign) else []
        if not (
            len(targets) == 1
            and isinstance(targets[0], ast.Tuple)
            and len(targets[0].elts) == 2
            and all(isinstance(e, ast.Name) for e in targets[0].elts)
        ):
            bad("戻り値を (値, 理由) の 2 つの名前に分解していない — 理由が捨てられる")
            continue
        reason = targets[0].elts[1].id  # type: ignore[attr-defined]
        if reason.startswith("_"):
            bad(f"理由を {reason!r} で捨てている")
            continue
        # 【分解の後で、上書きされる前の読みだけを数える】: 同じ関数に同名の別の変数があると、
        #   位置を見ない網は「読んだ」と誤認する (理由を捨てても緑になる)。
        assert isinstance(holder, ast.Assign)
        start = (holder.end_lineno or holder.lineno, holder.end_col_offset or 0)
        seen = _occurrences(scope, reason)
        stop = min(
            (_pos(n) for n in seen if not isinstance(n.ctx, ast.Load) and _pos(n) > start),
            default=(10**9, 0),
        )
        reads = [n for n in seen if isinstance(n.ctx, ast.Load) and start < _pos(n) < stop]
        if not reads:
            bad(f"理由 {reason!r} を分解の後で (上書き前に) 一度も読んでいない")
        elif all(forwarded(n, scope) for n in reads) and not own_resolver:
            bad(f"理由 {reason!r} を返り値に詰めて転送するだけ — 呼び出し側が網から外れる")
    return sites, violations


@functools.cache
def _scan_src() -> tuple[dict[str, list[int]], tuple[str, ...]]:
    """src 全体を 1 度だけ走査する (2 つのテストが同じ結果を使う)。"""
    sites: dict[str, list[int]] = {}
    violations: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if not any(r in text for r in _RESOLVERS):
            continue  # 呼び出しにも import にも解決関数の名前が出ない module は見るまでもない
        rel = path.relative_to(_SRC).as_posix()
        found, bad = _scan(text, defines_resolvers=path == _GPXSTORE)
        if found:
            sites[rel] = found
        violations.extend(f"src/tsumugin/{rel}:{v}" for v in bad)
    return sites, tuple(violations)


def test_no_src_caller_discards_the_fallback_reason():
    """★src の全呼び出しが退避理由を (分解して) 読んでいること。"""
    _sites, violations = _scan_src()
    assert not violations, (
        "成果物の退避理由 (一時領域へ退避した理由) を捨てている呼び出しがあります。解決した入口で"
        "しか分からない情報なので、台帳 (m7/m9/m10_gpx_fallback) か結果の警告に載せてください "
        "(gpx-retention 設計 §5):\n" + "\n".join(violations)
    )


def test_resolver_names_are_unique_in_src():
    """解決関数の名前を持つ関数/代入は src で gpxstore だけにあること。

    網はどの module からの import でも**名前で**解決関数とみなす (再輸出経由の import を
    逃さないため)。同名の別関数ができるとそれが誤って網に掛かるので、その前提をここで固定する。
    """
    owners: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                named = [node.name]
            elif isinstance(node, ast.Assign):
                named = [t.id for t in node.targets if isinstance(t, ast.Name)]
            else:
                continue
            owners += [f"{rel}:{n}" for n in named if n in _RESOLVERS]
    assert sorted(owners) == sorted(f"gpxstore.py:{r}" for r in _RESOLVERS), owners


def test_the_net_sees_the_known_callers():
    """網が既知の呼び出し元を実際に見ていること (走査先の取り違えで 0 件 = 偽の緑を防ぐ)。"""
    sites, _violations = _scan_src()
    missing = _KNOWN_CALLERS - set(sites)
    assert not missing, (
        f"既知の呼び出し元が網に掛かっていない: {sorted(missing)} (見えているのは {sorted(sites)})。"
        "呼び出しを移した/消したなら _KNOWN_CALLERS を更新すること"
    )


_HEAD = "from tsumugin.gpxstore import group_context, series_context, resolve_run_dir\n"

_DISCARDS = {
    "underscore_name": _HEAD + "def f():\n    g, _reason = group_context('d')\n    return g\n",
    "bare_underscore": _HEAD + "def f():\n    g, _ = series_context('d')\n    return g\n",
    "resolve_underscore": _HEAD + "def f():\n    run_dir, _ = resolve_run_dir('d')\n    return run_dir\n",
    "subscript": _HEAD + "def f():\n    g = group_context('d')[0]\n    return g\n",
    "expression_statement": _HEAD + "def f():\n    group_context('d')\n",
    "single_name": _HEAD + "def f():\n    pair = group_context('d')\n    return pair\n",
    "never_read": _HEAD + "def f():\n    g, reason = group_context('d')\n    return g\n",
    "only_deleted": _HEAD + "def f():\n    g, reason = group_context('d')\n    del reason\n",
    "read_only_before_the_unpack": (
        _HEAD + "def f(log):\n    reason = 'other'\n    log(reason)\n"
        "    g, reason = group_context('d')\n    return g\n"
    ),
    "overwritten_before_read": (
        _HEAD + "def f(log):\n    g, reason = group_context('d')\n    reason = ''\n"
        "    log(reason)\n    return g\n"
    ),
    "shadowed_by_a_nested_parameter": (
        _HEAD + "def f():\n    g, reason = group_context('d')\n"
        "    def note(reason):\n        return reason\n    return g, note\n"
    ),
    "shadowed_by_a_nested_assignment": (
        _HEAD + "def f():\n    g, reason = group_context('d')\n"
        "    def note():\n        reason = 'x'\n        return reason\n    return g, note\n"
    ),
    "shadowed_by_a_comprehension": (
        _HEAD + "def f(xs):\n    g, reason = group_context('d')\n"
        "    return g, [reason for reason in xs]\n"
    ),
    "aliased_import": (
        "from ..gpxstore import series_context as sc\n"
        "def f():\n    c, _r = sc('d')\n    return c\n"
    ),
    "star_import": (
        "from tsumugin.gpxstore import *\n"
        "def f():\n    g, _ = group_context('d')\n    return g\n"
    ),
    "attribute_call": (
        "from tsumugin import gpxstore\n"
        "def f():\n    g, _r = gpxstore.group_context('d')\n    return g\n"
    ),
    "lazy_import": (
        "def f():\n    from ...gpxstore import group_context\n"
        "    g, _ = group_context('d')\n    return g\n"
    ),
    "forwarded_outside_gpxstore": _HEAD + "def make():\n    return group_context('d')\n",
    "repacked_into_a_return": (
        _HEAD + "def make():\n    g, reason = group_context('d')\n    return g, reason\n"
    ),
    "returned_alone": (
        _HEAD + "def make():\n    g, reason = group_context('d')\n    return reason\n"
    ),
    "yielded": (
        _HEAD + "def make():\n    g, reason = group_context('d')\n    yield g, reason\n"
    ),
    "conditionally_repacked": (
        _HEAD + "def make(x):\n    g, reason = group_context('d')\n"
        "    return (g, reason) if x else (g, '')\n"
    ),
    "reexported_import": (
        "from ..autorietveld.search import group_context\n"
        "def f():\n    g, _ = group_context('d')\n    return g\n"
    ),
}


@pytest.mark.parametrize("case", sorted(_DISCARDS))
def test_the_net_flags_a_discarded_reason(case):
    """網が各「捨て方」を実際に捕まえること (落ちない網は無いより悪い)。"""
    sites, violations = _scan(_DISCARDS[case])
    assert sites, f"{case}: 解決関数の呼び出し自体が見えていない"
    assert violations, f"{case}: 理由を捨てる形を見逃した"


_SURFACED = {
    "ledger_and_warning": (
        _HEAD + "def f(ledger):\n    g, reason = group_context('d')\n"
        "    if reason:\n        ledger.append('m7_gpx_fallback', {'reason': reason})\n    return g\n"
    ),
    "read_in_a_closure": (
        _HEAD + "def f():\n    g, reason = series_context('d')\n"
        "    def note():\n        return reason\n    return g, note\n"
    ),
    "resolve_run_dir_read": (
        _HEAD + "def f(log):\n    run_dir, reason = resolve_run_dir('d')\n"
        "    log(reason)\n    return run_dir\n"
    ),
    "read_then_overwritten": (
        _HEAD + "def f(log):\n    g, reason = group_context('d')\n    log(reason)\n"
        "    reason = ''\n    return g\n"
    ),
    "closure_with_a_grand_nested_rebinding": (
        _HEAD + "def f(log):\n    g, reason = group_context('d')\n"
        "    def note():\n        log(reason)\n"
        "        def inner():\n            reason = 'x'\n            return reason\n"
        "        return inner\n    return g, note\n"
    ),
    "branches_on_the_reason": (
        _HEAD + "def f():\n    g, reason = group_context('d')\n"
        "    return (g, 'redirected') if reason else (g, '')\n"
    ),
    "carried_into_a_constructor": (
        _HEAD + "def f(Plan):\n    run_dir, reason = resolve_run_dir('d')\n"
        "    return Plan(run_dir, fallback_reason=reason)\n"
    ),
}


@pytest.mark.parametrize("case", sorted(_SURFACED))
def test_the_net_accepts_a_surfaced_reason(case):
    """理由を読んでいる呼び出しは通す (何でも落とす網で上のテストを満たせないように)。"""
    sites, violations = _scan(_SURFACED[case])
    assert sites, f"{case}: 解決関数の呼び出し自体が見えていない"
    assert not violations, violations


def test_gpxstore_may_forward_between_its_own_resolvers():
    """`group_context` が `series_context` の (値, 理由) をそのまま返すのは転送であって破棄ではない。

    `series_context` が `resolve_run_dir` の理由を自分の戻り値に詰めるのも同じ。同じ形でも
    `gpxstore` の外 (= 解決関数でない関数) なら違反になることを対で確かめる。
    """
    src = (
        "def resolve_run_dir(d):\n    return d, ''\n"
        "def series_context(d):\n    run_dir, reason = resolve_run_dir(d)\n"
        "    return run_dir, reason\n"
        "def group_context(d):\n    return series_context(d)\n"
    )
    assert _scan(src, defines_resolvers=True) == ([4, 7], [])
    helper = src.replace("def series_context", "def helper").replace(
        "def group_context(d):\n    return series_context(d)\n", ""
    )
    assert _scan(helper, defines_resolvers=True)[1]
    assert _scan("def helper(d):\n    return series_context(d)\n", defines_resolvers=True)[1]
