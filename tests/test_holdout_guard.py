"""fit-then-judge の (準) hold-out を、新しい部品のテストが参照しないことの恒久ガード。

`docs/design/fit-then-judge/proposal.md` §6: 凍結前の段階 (P1/P1.5) でテンプレートの部品を
(準) hold-out に対して実行すると、評価が in-sample に戻る。テンプレートの部品 (P1a で足した
`PhaseSpec` のフィールド・段フラグ・観測・関数) を使う**関数**が、hold-out のデータを参照して
いないことをソースで検査する。既存経路の非回帰 (ゴールデン) は部品を使わないので網に掛からない。

**粒度は関数単位**だが、関数の字面には次も連結する (どれも「部品のテストが hold-out を読む」の
抜け道になるため。2 巡目のセルフレビューで指摘された):

- 名前で参照するモジュール直下の定数 (``Assign`` と型注釈付きの ``AnnAssign``)
- 名前で参照する同じモジュールの補助関数・fixture (引数名で受ける fixture を含む)、**推移的に**
- 同じテストパッケージの別モジュールから import した名前 (その定義を同様に辿る)
- デコレータ (``parametrize`` に直接書いたパス)

hold-out の定義 (proposal §6 のデータ区分) に合わせ、T3/T4 は**ヒストグラムのファイル名**で照合する
(T3 の CW 中性子単独・T4 の TOF は hold-out ではないので、ディレクトリ名では照合しない)。T1 と
CaTeO3 はディレクトリ全体が hold-out なので、分割して組んだパス (``Path(...)/"labdata"``) も拾える
よう**ディレクトリ名単体**で照合する。
"""

from __future__ import annotations

import ast
from pathlib import Path

#: テンプレートの部品を使っている印 (P1a で足した名前)。
FEATURE_TOKENS = (
    "uiso_equiv_groups",
    "fix_polar_origin",
    "zero_offset",
    "export_cif_dir",
    "phase_integrated_intensity",
    "coordinate_freedom_mismatches",
    "_apply_polar_origin",
    "polar_origin_constraints",
    "_integrated_intensity",
    "merge_equiv_groups",
    "_checked_uiso_groups",
    "_export_refined_cifs",
    "_refuse_polar_origin_with_ranked_coords",
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


class _Module:
    """1 テストモジュールの定義 (定数・関数) と、別モジュールから import した名前。"""

    def __init__(self, path: Path):
        self.path = path
        self.source = path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.constants: dict[str, str] = {}
        self.functions: dict[str, ast.AST] = {}
        self.imports: dict[str, tuple[Path, str]] = {}
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                text = ast.get_source_segment(self.source, node) or ""
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.constants[target.id] = text
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self.constants[node.target.id] = ast.get_source_segment(self.source, node) or ""
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
            elif isinstance(node, ast.ImportFrom) and node.level >= 1 and node.module:
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                target = base.joinpath(*node.module.split(".")).with_suffix(".py")
                if target.exists():
                    for alias in node.names:
                        self.imports[alias.asname or alias.name] = (target, alias.name)

    def node_text(self, node: ast.AST) -> str:
        text = ast.get_source_segment(self.source, node) or ""
        for deco in getattr(node, "decorator_list", []):
            text += "\n" + (ast.get_source_segment(self.source, deco) or "")
        return text


_CACHE: dict[Path, _Module] = {}


def _module(path: Path) -> _Module:
    path = path.resolve()
    if path not in _CACHE:
        _CACHE[path] = _Module(path)
    return _CACHE[path]


def _referenced_names(node: ast.AST) -> set[str]:
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    names |= {a.arg for a in ast.walk(node) if isinstance(a, ast.arg)}  # fixture は引数名で受ける
    return names


def _closure_text(mod: _Module, node: ast.AST) -> str:
    """関数の字面に、参照する定数・関数・fixture・import 先を推移的に連結する。"""
    seen: set[tuple[Path, str]] = set()
    parts: list[str] = []
    stack: list[tuple[_Module, ast.AST]] = [(mod, node)]
    while stack:
        m, n = stack.pop()
        parts.append(m.node_text(n))
        for name in _referenced_names(n):
            key = (m.path, name)
            if key in seen:
                continue
            seen.add(key)
            if name in m.constants:
                parts.append(m.constants[name])
            if name in m.functions and m.functions[name] is not n:
                stack.append((m, m.functions[name]))
            if name in m.imports:
                target, original = m.imports[name]
                other = _module(target)
                if original in other.constants:
                    parts.append(other.constants[original])
                if original in other.functions:
                    stack.append((other, other.functions[original]))
    return "\n".join(parts)


def _offenders(root: Path) -> list[tuple[str, str, list[str]]]:
    out = []
    for path in sorted(root.rglob("test_*.py")):
        if path.resolve() == _SELF:
            continue
        mod = _module(path)
        for name, node in mod.functions.items():
            if not name.startswith("test"):
                continue
            text = _closure_text(mod, node)
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
    """空振りしないこと: 2 巡目のセルフレビューが挙げた抜け道をすべて拾う。"""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "test_shared.py").write_text(
        "from pathlib import Path\n_SHARED = Path('docs/benchmark/testdata/m9/cateo3')\n",
        encoding="utf-8",
    )
    (pkg / "test_bad.py").write_text(
        "import pytest\n"
        "from pathlib import Path\n"
        "from .test_shared import _SHARED\n"
        "_DATA = Path('docs/benchmark/testdata/m7/labdata')\n"
        "_ANN: Path = Path('docs') / 'benchmark' / 'testdata' / 'm7' / 'labdata'\n"
        "def _run_t1():\n"
        "    return _DATA\n"
        "@pytest.fixture\n"
        "def t1_data():\n"
        "    return 'FAP.XRA'\n"
        "def test_direct():\n"
        "    spec = dict(uiso_equiv_groups=[], data='FAP.XRA')\n"
        "def test_constant():\n"
        "    return _DATA, 'fix_polar_origin'\n"
        "def test_annotated_split_path():\n"
        "    return _ANN, 'zero_offset'\n"
        "def test_helper():\n"
        "    r = _run_t1()\n"
        "    return r.phase_integrated_intensity\n"
        "def test_fixture(t1_data):\n"
        "    return t1_data, 'export_cif_dir'\n"
        "def test_imported():\n"
        "    return _SHARED, 'coordinate_freedom_mismatches'\n"
        "@pytest.mark.parametrize('p', ['NB-LM01MO_030.XRDML'])\n"
        "def test_decorator(p):\n"
        "    return p, 'merge_equiv_groups'\n"
        "def test_unrelated():\n"
        "    return 'FAP.XRA'\n"
        "def test_neutron_only_t3_is_allowed():\n"
        "    return 'docs/benchmark/testdata/m7/cwcombined/PBSO4.CWN', 'zero_offset'\n",
        encoding="utf-8",
    )
    found = {name for _, name, _ in _offenders(tmp_path)}
    assert found == {
        "test_direct",
        "test_constant",
        "test_annotated_split_path",
        "test_helper",
        "test_fixture",
        "test_imported",
        "test_decorator",
    }, found
