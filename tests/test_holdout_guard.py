"""fit-then-judge の (準) hold-out を、新しい部品のテストが参照しないことの恒久ガード。

`docs/design/fit-then-judge/proposal.md` §6: 凍結前の段階 (P1/P1.5) でテンプレートの部品を
(準) hold-out に対して実行すると、評価が in-sample に戻る。テンプレートの部品 (P1a で足した
`PhaseSpec` のフィールド・段フラグ・観測・関数) を使う**テスト**が、hold-out のデータを参照して
いないことをソースで検査する。既存経路の非回帰 (ゴールデン) は部品を使わないので網に掛からない。

検査の単位はテスト関数 (クラスのメソッドを含む)。その字面に、テストが辿り得る定義を**推移的に**
連結してから照合する (どれも「部品のテストが hold-out を読む」抜け道になり得る。セルフレビュー
2・3 巡目で指摘された):

- 名前・属性で参照するモジュールの定数 (``Assign``/``AnnAssign``) と関数・メソッド
- 引数名で受ける fixture (同じモジュールと、テストファイルから上位の ``conftest.py``)
- import した名前 (関数の中の import を含む。相対・``tests.`` の絶対・``from . import test_x`` の
  モジュール属性)
- デコレータ (``parametrize`` に直接書いたパス)

照合は**コードの字面**で行う: docstring とコメントは除く (動機として「CaTeO3 で…」と書いただけで
当たらないように)。hold-out の定義 (proposal §6 のデータ区分) に合わせ、T3/T4 はヒストグラムの
ファイル名で照合し (中性子単独・TOF は hold-out ではない)、T1 と CaTeO3 はディレクトリ全体が
hold-out なのでディレクトリ名単体で照合する (分割して組んだパスも拾う)。
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path

#: テンプレートの部品を使っている印。部品のモジュール名と P1a で足した名前。
FEATURE_TOKENS = (
    "constraint_groups",
    "uiso_equiv_groups",
    "fix_polar_origin",
    "zero_offset",
    "export_cif_dir",
    "phase_integrated_intensity",
    "coordinate_freedom_mismatches",
    "_apply_polar_origin",
    "_integrated_intensity",
    "_checked_uiso_groups",
    "_export_refined_cifs",
    "_refuse_polar_origin_with_ranked_coords",
    "_refuse_polar_origin_with_coord_jitter",
)

#: (準) hold-out の参照。大文字小文字を区別しない。
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


def _code(node: ast.AST) -> str:
    return ast.unparse(_strip_docstrings(node))


class _Module:
    """1 モジュールの定義 (定数・関数/メソッド・import) — 全階層を走査する。"""

    def __init__(self, path: Path, root: Path):
        self.path = path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        self.constants: dict[str, str] = {}
        self.functions: dict[str, list[ast.AST]] = {}
        self.imports: dict[str, tuple[Path, str | None]] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.constants[target.id] = _code(node)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self.constants[node.target.id] = _code(node)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(node.name, []).append(node)
            elif isinstance(node, ast.ImportFrom):
                self._register_import(node, root)

    def _register_import(self, node: ast.ImportFrom, root: Path) -> None:
        if node.level >= 1:
            base = self.path.parent
            for _ in range(node.level - 1):
                base = base.parent
            parts = node.module.split(".") if node.module else []
        elif node.module and node.module.split(".")[0] == root.name:
            base = root.parent
            parts = node.module.split(".")
        else:
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


def _module(path: Path, root: Path) -> _Module:
    path = path.resolve()
    if path not in _CACHE:
        _CACHE[path] = _Module(path, root)
    return _CACHE[path]


def _conftests(path: Path, root: Path) -> list[_Module]:
    """テストファイルから root までの各階層の conftest.py (fixture の供給元)。"""
    out = []
    d = path.parent
    while True:
        c = d / "conftest.py"
        if c.exists():
            out.append(_module(c, root))
        if d == root or d.parent == d:
            break
        d = d.parent
    return out


def _closure_text(mod: _Module, node: ast.AST, root: Path) -> str:
    """テストの字面に、辿り得る定義を推移的に連結する (docstring/コメントを除く)。"""
    seen: set[tuple[Path, str]] = set()
    parts: list[str] = []
    stack: list[tuple[_Module, ast.AST]] = [(mod, node)]
    while stack:
        m, n = stack.pop()
        parts.append(_code(n))
        providers = [m, *_conftests(m.path, root)]
        refs: list[tuple[str | None, str]] = []  # (モジュール別名 or None, 名前)
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
                    parts.append(other.constants.get(name, ""))
                    stack.extend((other, f) for f in other.functions.get(name, []))
                continue
            for provider in providers:
                key = (provider.path, name)
                if key in seen:
                    continue
                seen.add(key)
                if name in provider.constants:
                    parts.append(provider.constants[name])
                stack.extend((provider, f) for f in provider.functions.get(name, []) if f is not n)
            if name in m.imports:
                target_path, original = m.imports[name]
                if original is None:
                    continue
                other = _module(target_path, root)
                key = (other.path, original)
                if key not in seen:
                    seen.add(key)
                    parts.append(other.constants.get(original, ""))
                    stack.extend((other, f) for f in other.functions.get(original, []))
    return "\n".join(parts)


def _offenders(root: Path) -> list[tuple[str, str, list[str]]]:
    out = []
    for path in sorted(root.rglob("test_*.py")):
        if path.resolve() == _SELF:
            continue
        mod = _module(path, root)
        for name, nodes in mod.functions.items():
            if not name.startswith("test"):
                continue
            for node in nodes:
                text = _closure_text(mod, node, root)
                if not any(tok in text for tok in FEATURE_TOKENS):
                    continue
                lowered = text.lower()
                hits = [tok for tok in HOLDOUT_TOKENS if tok in lowered]
                if hits:
                    out.append((path.relative_to(root).as_posix(), name, hits))
    return out


def test_feature_tests_do_not_touch_the_holdout():
    offenders = _offenders(_TESTS)
    assert not offenders, (
        "テンプレートの部品を使うテストが (準) hold-out を参照しています: "
        f"{offenders}。合成データか hold-out 外の公開データ (T2 garnet 等) を使ってください"
    )


def test_the_guard_sees_through_every_known_loophole(tmp_path):
    """空振りしないこと: セルフレビュー 2・3 巡目が挙げた抜け道をすべて拾い、誤検出しない。"""
    _CACHE.clear()
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
        "from .test_shared import _SHARED\n"
        "from . import test_shared\n"
        "_DATA = Path('docs/benchmark/testdata/m7/labdata')\n"
        "_ANN: Path = Path('docs') / 'benchmark' / 'testdata' / 'm7' / 'labdata'\n"
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
        "    return 'zero_offset'\n",
        encoding="utf-8",
    )
    found = {name for _, name, _ in _offenders(root)}
    _CACHE.clear()
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
        "test_decorator",
        "test_method",
    }, found
