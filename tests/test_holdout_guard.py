"""fit-then-judge の (準) hold-out を、新しい部品のテストが参照しないことの恒久ガード。

`docs/design/fit-then-judge/proposal.md` §6: 凍結前の段階 (P1/P1.5) でテンプレートの部品を
(準) hold-out に対して実行すると、評価が in-sample に戻る。テンプレートの部品 (P1a で足した
`PhaseSpec` のフィールド・段フラグ・観測・関数) を使う**テスト**が、hold-out のデータを参照して
いないことをソースで検査する。既存経路の非回帰 (ゴールデン) は部品を使わないので網に掛からない。

検査の単位はテスト関数 (クラスのメソッドを含む)。テストが辿り得る定義を**推移的に**集めてから
照合する (どれも「部品のテストが hold-out を読む」抜け道になり得る。セルフレビュー 2–4 巡目):

- 名前・属性で参照するモジュールの定数 (``Assign``/``AnnAssign``) と関数・メソッド
- 引数名で受ける fixture (同じモジュールと、テストファイルから上位の ``conftest.py``)
- import した名前 (関数の中の import を含む。相対・``tests.`` の絶対・``from . import test_x`` の
  モジュール属性)。tests の**外**から import した名前は、import 元のモジュール名を字面に足す
  (``from tsumugin.autorietveld.constraint_groups import f as g`` でも部品と判定できる)
- デコレータ (``parametrize`` に直接書いたパス)

照合は 2 つに分ける:

- **部品の判定**は、docstring とコメントを除いたコードの字面に部品の名前があるか
- **hold-out の判定**は、**パスらしい文字列**だけで行う (区切り文字か拡張子を含む文字列・``/`` で
  連結された文字列)。説明文 (docstring・定数の理由文) に「CaTeO3 で…」と書いただけで当たらない

hold-out の定義 (proposal §6 のデータ区分) に合わせ、T3/T4 はヒストグラムのファイル名で照合し
(中性子単独・TOF は hold-out ではない)、T1 と CaTeO3 はディレクトリ全体が hold-out なので
ディレクトリ名単体で照合する。
"""

from __future__ import annotations

import ast
import copy
import re
from pathlib import Path

#: テンプレートの部品を使っている印 — 部品の名前と、部品のモジュール (import 元で照合)。
FEATURE_TOKENS = (
    "autorietveld.constraint_groups",
    "uiso_equiv_groups",
    "fix_polar_origin",
    "zero_offset",
    "export_cif_dir",
    "phase_integrated_intensity",
    "coordinate_freedom_mismatches",
    "merge_equiv_groups",
    "partially_released_groups",
    "polar_origin_constraints",
    "refuse_polar_origin_with_ranked_coords",
    "refuse_polar_origin_with_coord_jitter",
    "_apply_polar_origin",
    "_integrated_intensity",
    "_checked_uiso_groups",
    "_export_refined_cifs",
)

#: (準) hold-out の参照 (パスらしい文字列の中で照合する)。大文字小文字を区別しない。
HOLDOUT_TOKENS = (
    "labdata",  # T1 fluoroapatite (ディレクトリ全体)
    "fap.xra",
    "cateo3",  # CaTeO3 (ディレクトリ全体)
    "nb-lm01mo",
    "pbso4.xra",  # T3 の X 線ヒストグラム (中性子単独は hold-out ではない)
    "inst_xry",
    "11bm",  # T4 の 11-BM ヒストグラム (TOF は hold-out ではない)
)

_TESTS = Path(__file__).resolve().parent
_SELF = Path(__file__).resolve()
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{2,6}$")


def _strip_docstrings(node: ast.AST) -> ast.AST:
    """docstring を除いた写しを返す (``ast.unparse`` はコメントを落とすので、両方が消える)。"""
    node = copy.deepcopy(node)
    for n in ast.walk(node):
        body = getattr(n, "body", None)
        if (
            isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            n.body = body[1:] or [ast.Pass()]
    return node


_CODE_MEMO: dict[int, str] = {}
_PATHS_MEMO: dict[int, list[str]] = {}


def _code(node: ast.AST) -> str:
    key = id(node)
    if key not in _CODE_MEMO:
        _CODE_MEMO[key] = ast.unparse(_strip_docstrings(node))
    return _CODE_MEMO[key]


def _path_strings(node: ast.AST) -> list[str]:
    """パスらしい文字列: 区切り文字か拡張子を含む文字列、``/`` 演算で連結される文字列。"""
    key = id(node)
    if key in _PATHS_MEMO:
        return _PATHS_MEMO[key]
    stripped = _strip_docstrings(node)
    joined: set[int] = set()
    for n in ast.walk(stripped):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            for side in (n.left, n.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    joined.add(id(side))
    out = [
        n.value
        for n in ast.walk(stripped)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and (
            id(n) in joined
            or "/" in n.value
            or "\\" in n.value
            or _EXTENSION.search(n.value.strip())
        )
    ]
    _PATHS_MEMO[key] = out
    return out


class _Module:
    """1 モジュールの定義 (定数・関数/メソッド・import) — 全階層を走査する。"""

    def __init__(self, path: Path, root: Path):
        self.path = path
        self.raw = path.read_text(encoding="utf-8")
        tree = ast.parse(self.raw)
        self.constants: dict[str, ast.AST] = {}
        self.functions: dict[str, list[ast.AST]] = {}
        self.imports: dict[str, tuple[Path, str | None]] = {}
        #: tests の外から import した名前 → import 元 (``tsumugin.x.y`` / ``tsumugin.x.y.f``)
        self.external: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.constants[target.id] = node
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self.constants[node.target.id] = node
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(node.name, []).append(node)
            elif isinstance(node, ast.ImportFrom):
                self._register_from(node, root)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.external[alias.asname or alias.name.split(".")[0]] = alias.name

    def _register_from(self, node: ast.ImportFrom, root: Path) -> None:
        if node.level >= 1:
            base = self.path.parent
            for _ in range(node.level - 1):
                base = base.parent
            parts = node.module.split(".") if node.module else []
        elif node.module and node.module.split(".")[0] == root.name:
            base = root.parent
            parts = node.module.split(".")
        else:
            for alias in node.names:
                self.external[alias.asname or alias.name] = f"{node.module}.{alias.name}"
            return
        target = base.joinpath(*parts)
        for alias in node.names:
            bound = alias.asname or alias.name
            as_module = target / f"{alias.name}.py"
            if as_module.exists():  # from . import test_x → モジュール
                self.imports[bound] = (as_module, None)
            elif target.with_suffix(".py").exists():
                self.imports[bound] = (target.with_suffix(".py"), alias.name)


_CACHE: dict[Path, _Module] = {}
_CONFTEST_CACHE: dict[Path, list[_Module]] = {}


def _module(path: Path, root: Path) -> _Module:
    path = path.resolve()
    if path not in _CACHE:
        _CACHE[path] = _Module(path, root)
    return _CACHE[path]


def _conftests(path: Path, root: Path) -> list[_Module]:
    """テストファイルから root までの各階層の conftest.py (fixture の供給元)。"""
    key = path.parent.resolve()
    if key in _CONFTEST_CACHE:
        return _CONFTEST_CACHE[key]
    out = []
    d = path.parent
    while True:
        c = d / "conftest.py"
        if c.exists():
            out.append(_module(c, root))
        if d == root or d.parent == d:
            break
        d = d.parent
    _CONFTEST_CACHE[key] = out
    return out


def _closure(mod: _Module, node: ast.AST, root: Path) -> tuple[str, list[str]]:
    """(部品判定用のコードの字面, hold-out 判定用のパスらしい文字列) を推移的に集める。"""
    seen: set[tuple[Path, str]] = set()
    code: list[str] = []
    paths: list[str] = []
    stack: list[tuple[_Module, ast.AST]] = [(mod, node)]

    def take(n: ast.AST) -> None:
        code.append(_code(n))
        paths.extend(_path_strings(n))

    while stack:
        m, n = stack.pop()
        take(n)
        providers = [m, *_conftests(m.path, root)]
        refs: list[tuple[str | None, str]] = []
        for sub in ast.walk(n):
            if isinstance(sub, ast.Name):
                refs.append((None, sub.id))
            elif isinstance(sub, ast.arg):
                refs.append((None, sub.arg))  # fixture は引数名で受ける
            elif isinstance(sub, ast.Attribute):
                refs.append((None, sub.attr))  # self._helper 等
                if isinstance(sub.value, ast.Name):
                    refs.append((sub.value.id, sub.attr))  # test_x._run 等
        for alias, name in refs:
            if alias is not None:
                target = m.imports.get(alias)
                if not target or target[1] is not None:
                    continue
                other = _module(target[0], root)
                key = (other.path, name)
                if key not in seen:
                    seen.add(key)
                    if name in other.constants:
                        take(other.constants[name])
                    stack.extend((other, f) for f in other.functions.get(name, []))
                continue
            if name in m.external:
                code.append(m.external[name])  # import 元のモジュール名で部品を判定する
            for provider in providers:
                key = (provider.path, name)
                if key in seen:
                    continue
                seen.add(key)
                if name in provider.constants:
                    take(provider.constants[name])
                stack.extend((provider, f) for f in provider.functions.get(name, []) if f is not n)
            if name in m.imports:
                target_path, original = m.imports[name]
                if original is None:
                    continue
                other = _module(target_path, root)
                key = (other.path, original)
                if key not in seen:
                    seen.add(key)
                    if original in other.constants:
                        take(other.constants[original])
                    stack.extend((other, f) for f in other.functions.get(original, []))
    return "\n".join(code), paths


def _could_reach_a_feature(mod: _Module, root: Path) -> bool:
    """このファイルのテストが部品に届き得るか (届き得なければ閉包を作らずに飛ばす — 速度のため)。

    部品の名前は、テストの字面か、辿り得るファイル (conftest・import した tests のモジュール) の
    どこかに字面として現れるはず。どこにも無ければ、そのファイルのテストは部品のテストではない。
    """
    seen: set[Path] = set()
    stack = [mod]
    while stack:
        m = stack.pop()
        if m.path in seen:
            continue
        seen.add(m.path)
        if any(tok in m.raw for tok in FEATURE_TOKENS):
            return True
        stack.extend(_conftests(m.path, root))
        stack.extend(_module(p, root) for p, _ in m.imports.values())
    return False


def _offenders(root: Path) -> list[tuple[str, str, list[str]]]:
    out = []
    for path in sorted(root.rglob("test_*.py")):
        if path.resolve() == _SELF:
            continue
        mod = _module(path, root)
        if not _could_reach_a_feature(mod, root):
            continue
        for name, nodes in mod.functions.items():
            if not name.startswith("test"):
                continue
            for node in nodes:
                code, paths = _closure(mod, node, root)
                if not any(tok in code for tok in FEATURE_TOKENS):
                    continue
                lowered = "\n".join(paths).lower()
                hits = [tok for tok in HOLDOUT_TOKENS if tok in lowered]
                if hits:
                    out.append((path.relative_to(root).as_posix(), name, hits))
    return out


def _reset_caches() -> None:
    _CACHE.clear()
    _CONFTEST_CACHE.clear()
    _CODE_MEMO.clear()
    _PATHS_MEMO.clear()


def test_feature_tests_do_not_touch_the_holdout():
    offenders = _offenders(_TESTS)
    assert not offenders, (
        "テンプレートの部品を使うテストが (準) hold-out を参照しています: "
        f"{offenders}。合成データか hold-out 外の公開データ (T2 garnet 等) を使ってください"
    )


def test_the_guard_sees_through_every_known_loophole(tmp_path):
    """空振りしないこと: セルフレビュー 2–4 巡目が挙げた抜け道をすべて拾い、誤検出しない。"""
    _reset_caches()
    root = tmp_path / "tests"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (root / "conftest.py").write_text(
        "import pytest\n@pytest.fixture\ndef t1_data():\n    return 'FAP.XRA'\n", encoding="utf-8"
    )
    (pkg / "test_shared.py").write_text(
        "from pathlib import Path\n"
        "_SHARED = Path('docs/benchmark/testdata/m9/cateo3')\n"
        "def _run_t1():\n"
        "    return 'docs/benchmark/testdata/m7/labdata/FAP.XRA'\n",
        encoding="utf-8",
    )
    (pkg / "test_bad.py").write_text(
        "import pytest\n"
        "from pathlib import Path\n"
        "import tsumugin.autorietveld.constraint_groups as cg\n"
        "from tsumugin.autorietveld.constraint_groups import polar_origin_constraints as poc\n"
        "from .test_shared import _SHARED\n"
        "from . import test_shared\n"
        "_DATA = Path('docs/benchmark/testdata/m7/labdata')\n"
        "_ANN: Path = Path('docs') / 'benchmark' / 'testdata' / 'm7' / 'labdata'\n"
        "_REASON = '観測の整合 (実測 CaTeO3 の labdata 比較で見つかった)'\n"
        "def _run_local():\n"
        "    return _DATA\n"
        "@pytest.fixture\n"
        "def local_data():\n"
        "    return 'FAP.XRA'\n"
        "def test_direct():\n"
        "    spec = dict(uiso_equiv_groups=[], data='FAP.XRA')\n"
        "def test_constant():\n"
        "    return _DATA, 'fix_polar_origin'\n"
        "def test_annotated_split_path():\n"
        "    return _ANN, 'zero_offset'\n"
        "def test_helper():\n"
        "    r = _run_local()\n"
        "    return r.phase_integrated_intensity\n"
        "def test_local_fixture(local_data):\n"
        "    return local_data, 'export_cif_dir'\n"
        "def test_conftest_fixture(t1_data):\n"
        "    return t1_data, 'export_cif_dir'\n"
        "def test_imported():\n"
        "    return _SHARED, 'coordinate_freedom_mismatches'\n"
        "def test_inner_import():\n"
        "    from .test_shared import _run_t1\n"
        "    return _run_t1(), 'fix_polar_origin'\n"
        "def test_module_attribute():\n"
        "    return test_shared._run_t1(), 'zero_offset'\n"
        "def test_absolute_import():\n"
        "    from tests.pkg.test_shared import _SHARED as s\n"
        "    return s, 'zero_offset'\n"
        "def test_external_renamed_import():\n"
        "    return poc('z', 'docs/benchmark/testdata/m7/labdata')\n"
        "def test_external_module_alias():\n"
        "    return cg.merge_equiv_groups, 'FAP.XRA'\n"
        "@pytest.mark.parametrize('p', ['NB-LM01MO_030.XRDML'])\n"
        "def test_decorator(p):\n"
        "    return p, 'fix_polar_origin'\n"
        "class TestInClass:\n"
        "    def _helper(self):\n"
        "        return 'FAP.XRA'\n"
        "    def test_method(self):\n"
        "        return self._helper(), 'zero_offset'\n"
        "def test_unrelated():\n"
        "    return 'FAP.XRA'\n"
        "def test_neutron_only_t3_is_allowed():\n"
        "    return 'docs/benchmark/testdata/m7/cwcombined/PBSO4.CWN', 'zero_offset'\n"
        "def test_docstring_mention_is_not_a_reference():\n"
        "    '''CaTeO3 の実測で見つかった病理 (動機の記述)。'''\n"
        "    # labdata の T1 でも同じ\n"
        "    return 'zero_offset'\n"
        "def test_reason_text_is_not_a_reference():\n"
        "    return _REASON, 'zero_offset'\n"
        "def test_phase_spec_constraint_groups_are_carried_through():\n"
        "    return 'FAP.XRA'  # 名前に constraint_groups を含むだけの無関係なテスト\n",
        encoding="utf-8",
    )
    found = {name for _, name, _ in _offenders(root)}
    _reset_caches()
    assert found == {
        "test_direct",
        "test_constant",
        "test_annotated_split_path",
        "test_helper",
        "test_local_fixture",
        "test_conftest_fixture",
        "test_imported",
        "test_inner_import",
        "test_module_attribute",
        "test_absolute_import",
        "test_external_renamed_import",
        "test_external_module_alias",
        "test_decorator",
        "test_method",
    }, found
