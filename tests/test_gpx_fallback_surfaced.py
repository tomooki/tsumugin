"""★成果物の退避理由を**呼び出し側が捨てない** — `gpxstore` の解決関数の全呼び出しを見る静的ガード。

`gpxstore.group_context` / `series_context` / `resolve_run_dir(report_fallback=True)` は
``(値, 退避理由)`` を返す。理由が非空なのは、頼まれた根 (``gpx_dir`` / データ隣接) に run
ディレクトリを作れず**一時領域へ退避した**ときである (gpx-retention 設計 §5「temp へ退避し理由を
ledger」)。理由は**解決した入口でしか分からない** — エンジンは解決済みの文脈を受け取るだけで、
しかもファンアウト経路 (探索 / マルチスタート / 収束確認 / モデル比較 / 修復 / 系列 / M8 閉ループ)
ではエンジンの台帳は呼び出し側が見ない私有の台帳である。入口が理由を捨てると、成果物が
%TEMP% に置かれたことは**どこにも残らない**。

実害: `group, _reason = group_context(...)` の形で捨てていた入口が複数あり (探索 / マルチスタート /
モデル比較 / 修復は個別に直した)、直した後にも `refine_loop.orchestrator` に 1 件残っていた。
入口ごとに直しても、**次の呼び出し側が同じ形で捨てるのを止めるものが無い**。

規則 (違反は ``<file>:<line>`` で報告する):

1. 呼び出しの戻り値は**その場で 2 つの名前に分解する** (``ctx, reason = group_context(...)``)。
   添字 (``[0]``) ・単一名への代入・式文として捨てる・他の式へ埋め込む、はどれも違反
2. 理由の名前は ``_`` で始めない (``_`` / ``_reason`` は「捨てた」の宣言である)
3. 理由の名前は同じ関数の中で**読まれる** (代入しただけ / ``del`` しただけは違反)
4. ``return group_context(...)`` のような**素通しの転送**は `gpxstore` 自身の解決関数の中だけ
   (外で許すと、その関数が新しい解決関数になり、その呼び出し側が網から外れる)
5. ``resolve_run_dir`` は ``report_fallback=True`` を明示する (既定では理由を捨てる API なので)

**網の限界 (正直に言う)**: 「読んだ」は「ledger/警告に載せた」ではない — ``if reason: pass`` は
通る。網が止めるのは**うっかり捨てる形** (``_reason`` / ``[0]`` / 未使用) であり、載せる先が正しいか
(台帳の種別・② の ``warnings``) は入口ごとの振る舞いテスト
(`tests/autorietveld/test_gpx_fanout.py::test_fanout_entries_record_a_fallback_to_temp` ほか) が
見る。また ``ArtifactPlan.fallback_reason`` (エンジンが `plan_output` から受け取る側) は本網の
対象外で、両エンジンの ``_save_*_artifact`` が読んでいることは各エンジンのテストが見る。

**なぜ型 (`GpxContext` に理由を載せる) にしなかったか**: 理由を文脈に載せてエンジンの
``_save_gpx_artifact`` に ``m7_gpx_fallback`` を書かせる案は、ファンアウト経路ではエンジンの台帳が
私有 (呼び出し側へ返らない) なので**誰も見ない台帳に書くだけ**になる — 「構造的に記録される」ように
見えて実際は黙って消える。さらに属性にすると「読み忘れ」が呼び出し側に**何の痕跡も残さない**
(``_reason`` すら書かれない) ので、捨てたことがかえって見えなくなる。詳細は設計 §5。

変異検査で実証済 (実ソースへの変異で `test_no_src_caller_discards_the_fallback_reason` が fail):
``refine_loop.orchestrator`` を修正前の ``group, _reason =`` に戻す / ``compare.py`` の警告行を
``warnings = ()`` に置き換える (理由が未使用) / ``search.py`` を ``group_context(...)[0]`` にする /
``gpxstore.series_context`` の ``report_fallback=True`` を外す。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: 走査対象。**テストファイルの位置から辿る** — editable install は main チェックアウトの src を
#: 指すので、`tsumugin.__file__` から辿ると worktree では別ツリーを検査してしまう。
_SRC = Path(__file__).resolve().parents[1] / "src" / "tsumugin"
_GPXSTORE = _SRC / "gpxstore.py"

#: ``(値, 退避理由)`` を返す解決関数。
_RESOLVERS = frozenset({"group_context", "series_context", "resolve_run_dir"})

#: 既定では理由を返さない (= 捨てる) 解決関数と、理由を返させるフラグ。
_OPT_IN_FLAG = {"resolve_run_dir": "report_fallback"}

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


def _resolver_names(tree: ast.AST, *, defines_resolvers: bool) -> dict[str, str]:
    """この module で解決関数を指すローカル名 → 解決関数名 (``as`` 別名・関数内 import も拾う)。"""
    names = {r: r for r in _RESOLVERS} if defines_resolvers else {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == "gpxstore":
            for alias in node.names:
                if alias.name in _RESOLVERS:
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


def _is_loaded(scope: ast.AST, name: str) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)
        for n in ast.walk(scope)
    )


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

        flag = _OPT_IN_FLAG.get(resolver)
        if flag is not None and not any(
            kw.arg == flag and isinstance(kw.value, ast.Constant) and kw.value.value is True
            for kw in node.keywords
        ):
            bad(f"{flag}=True が無い — 既定では退避理由を返さない (捨てる)")

        holder = parent.get(node)
        scope = enclosing_scope(node)
        if isinstance(holder, ast.Return):
            forwards_own = (
                defines_resolvers
                and isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
                and scope.name in _RESOLVERS
            )
            if not forwards_own:
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
        elif not _is_loaded(scope, reason):
            bad(f"理由 {reason!r} を一度も読んでいない")
    return sites, violations


def _scan_src() -> tuple[dict[str, list[int]], list[str]]:
    sites: dict[str, list[int]] = {}
    violations: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        found, bad = _scan(path.read_text(encoding="utf-8"), defines_resolvers=path == _GPXSTORE)
        if found:
            sites[rel] = found
        violations.extend(f"src/tsumugin/{rel}:{v}" for v in bad)
    return sites, violations


def test_no_src_caller_discards_the_fallback_reason():
    """★src の全呼び出しが退避理由を (分解して) 読んでいること。"""
    _sites, violations = _scan_src()
    assert not violations, (
        "成果物の退避理由 (一時領域へ退避した理由) を捨てている呼び出しがあります。解決した入口で"
        "しか分からない情報なので、台帳 (m7/m9/m10_gpx_fallback) か結果の警告に載せてください "
        "(gpx-retention 設計 §5):\n" + "\n".join(violations)
    )


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
    "subscript": _HEAD + "def f():\n    g = group_context('d')[0]\n    return g\n",
    "expression_statement": _HEAD + "def f():\n    group_context('d')\n",
    "single_name": _HEAD + "def f():\n    pair = group_context('d')\n    return pair\n",
    "never_read": _HEAD + "def f():\n    g, reason = group_context('d')\n    return g\n",
    "only_deleted": _HEAD + "def f():\n    g, reason = group_context('d')\n    del reason\n",
    "aliased_import": (
        "from ..gpxstore import series_context as sc\n"
        "def f():\n    c, _r = sc('d')\n    return c\n"
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
    "resolve_without_opt_in": (
        _HEAD + "def f():\n    run_dir, reason = resolve_run_dir('d')\n    return run_dir, reason\n"
    ),
    "resolve_with_opt_out": (
        _HEAD + "def f():\n"
        "    run_dir, reason = resolve_run_dir('d', report_fallback=False)\n"
        "    return run_dir, reason\n"
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
    "resolve_with_opt_in": (
        _HEAD + "def f():\n"
        "    run_dir, reason = resolve_run_dir('d', report_fallback=True)\n"
        "    return run_dir, reason\n"
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

    同じ形でも `gpxstore` の外 (= 解決関数でない関数) なら違反になることを対で確かめる。
    """
    src = (
        "def series_context(d):\n    return 1, ''\n"
        "def group_context(d):\n    return series_context(d)\n"
    )
    assert _scan(src, defines_resolvers=True) == ([4], [])
    assert _scan("def helper(d):\n    return series_context(d)\n", defines_resolvers=True)[1]
