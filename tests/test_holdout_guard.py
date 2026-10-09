"""fit-then-judge の (準) hold-out を、新しい部品のテストが参照しないことの恒久ガード。

`docs/design/fit-then-judge/proposal.md` §6: 凍結前の段階 (P1/P1.5) でテンプレートの部品を
(準) hold-out に対して実行すると、評価が in-sample に戻る。テンプレートの部品 (P1a で足した
`PhaseSpec` のフィールド・段フラグ・観測) を使う**関数**が、hold-out のデータを参照していない
ことをソースで検査する。既存経路の非回帰 (ゴールデン) は部品を使わないので網に掛からない。

粒度は関数単位 (ファイル単位だと、同じファイルの無関係なテストの文字列を誤検出する)。関数が
名前で参照するモジュール定数 (例 ``_DATA = Path(".../m7/labdata")``) の値も、その関数の字面として
数える — 定数経由の参照を見逃さないため。
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
)

#: (準) hold-out の参照 (データディレクトリと代表ファイル名)。
HOLDOUT_TOKENS = (
    "m7/labdata",  # T1 fluoroapatite
    "FAP.XRA",
    "m9/cateo3",  # CaTeO3
    "NB-LM01MO",
    "PBSO4.XRA",  # T3 の X 線ヒストグラム
    "m7/cwcombined",
    "11BM",  # T4 の 11-BM ヒストグラム
    "m7/tofcw",
)

_TESTS = Path(__file__).resolve().parent
#: 本ガード自身 (トークンの一覧を字面に持つ)。
_SELF = Path(__file__).resolve()


def _function_texts(path: Path) -> list[tuple[str, str]]:
    """(関数名, 関数の字面 + 参照するモジュール定数の字面) の列。"""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            text = ast.get_source_segment(source, node) or ""
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = text
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            text = ast.get_source_segment(source, node) or ""
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            text += "\n".join(constants[n] for n in names if n in constants)
            out.append((node.name, text))
    return out


def _offenders(root: Path) -> list[tuple[str, str, list[str]]]:
    out = []
    for path in sorted(root.rglob("test_*.py")):
        if path.resolve() == _SELF:
            continue
        for name, text in _function_texts(path):
            if not any(tok in text for tok in FEATURE_TOKENS):
                continue
            hits = [tok for tok in HOLDOUT_TOKENS if tok in text]
            if hits:
                out.append((path.relative_to(root).as_posix(), name, hits))
    return out


def test_feature_tests_do_not_touch_the_holdout():
    offenders = _offenders(_TESTS)
    assert not offenders, (
        "テンプレートの部品を使うテストが (準) hold-out を参照しています: "
        f"{offenders}。合成データか hold-out 外の公開データ (T2 garnet 等) を使ってください"
    )


def test_the_guard_flags_a_direct_and_an_indirect_reference(tmp_path):
    """空振りしないこと: 直接の字面と、モジュール定数経由の参照の両方を拾う。"""
    (tmp_path / "test_bad.py").write_text(
        "from pathlib import Path\n"
        "_DATA = Path('docs/benchmark/testdata/m7/labdata')\n"
        "def test_direct():\n"
        "    spec = dict(uiso_equiv_groups=[], data='FAP.XRA')\n"
        "def test_indirect():\n"
        "    return _DATA, 'fix_polar_origin'\n"
        "def test_unrelated():\n"
        "    return 'FAP.XRA'\n",
        encoding="utf-8",
    )
    found = {(name, tuple(hits)) for _, name, hits in _offenders(tmp_path)}
    assert ("test_direct", ("FAP.XRA",)) in found
    assert ("test_indirect", ("m7/labdata",)) in found
    assert not any(name == "test_unrelated" for name, _ in found)
