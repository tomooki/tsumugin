"""frozen_coord_labels (座標凍結: coords 段の解放対象から除外) のテスト。

PhaseSpec の round-trip と _phase_atom_info の coord_atoms 除外を GSAS 非依存モックで検証する。
無秩序水の D/H を剛体的に理想幾何へ固定 (orientation 評価) する用途。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import PhaseSpec


def test_roundtrip_frozen_labels():
    spec = PhaseSpec("s.cif", "P", frozen_coord_labels=("D1", "H1"))
    assert PhaseSpec.from_dict(spec.to_dict()).frozen_coord_labels == ("D1", "H1")


def test_default_empty():
    assert PhaseSpec("s.cif", "P").frozen_coord_labels == ()


class _MockG2spcModule:
    """GetCSxinel が常に自由座標ありを返すスタブ (import 差し替え用)。"""

    @staticmethod
    def GetCSxinel(_sym):
        return [(1, 1, 1)]


class _MockPhase:
    """_phase_atom_info が触る最小構造 (Atoms / General AtomPtrs)。"""

    def __init__(self, labels):
        # 行: [x,y,z,frac,..., label(ct-1), ..., sym(cs)] 相当。簡易に label と sym だけ用意。
        cx, ct, cs, cia = 3, 8, 4, 12
        self._ptrs = (cx, ct, cs, cia)
        atoms = []
        for lab in labels:
            row = [0.0] * 20
            row[ct - 1] = lab
            row[cs] = "1"  # 一般位置
            atoms.append(row)
        self.data = {"Atoms": atoms, "General": {"AtomPtrs": [cx, ct, cs, cia]}}


def _info(labels, frozen, monkeypatch):
    """`_phase_atom_info` を偽の ``GSASII`` パッケージで駆動する (実 GSAS-II 不要)。

    `_phase_atom_info` は関数内で ``from GSASII import GSASIIspc`` する。旧実装は
    ``monkeypatch.setattr("GSASII.GSASIIspc", ...)`` で属性だけ差し替えていたが、**文字列
    ターゲットの setattr は親モジュール ``GSASII`` を実 import する**ため GSAS-II 不在環境では
    ``ModuleNotFoundError`` になった (``raising=False`` は属性不在を許すだけで import 失敗は
    救わない)。本ファイルの docstring は「GSAS 非依存モックで検証する」と宣言しているのに、
    実際は GSAS-II が入った機械でしか動いていなかった — 開発機には常に入っているので
    **ローカルでは不可視**で、CI (GSAS-II 不在) で初めて露見した (2026-07-28)。

    ``sys.modules`` に偽パッケージを差し込めば ``from GSASII import GSASIIspc`` は実物を
    探さずこれを解決する (monkeypatch.setitem なので実 GSASII があっても後で復元される)。
    """
    import sys
    import types

    import tsumugin.autorietveld.engine as eng

    fake_pkg = types.ModuleType("GSASII")
    fake_pkg.GSASIIspc = _MockG2spcModule  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "GSASII", fake_pkg)
    monkeypatch.setitem(sys.modules, "GSASII.GSASIIspc", _MockG2spcModule)  # type: ignore[arg-type]
    spec = PhaseSpec("s.cif", "P", frozen_coord_labels=tuple(frozen))
    return eng._phase_atom_info(_MockPhase(labels), spec)


def test_frozen_excluded_from_coord_atoms(monkeypatch):
    info = _info(["Fe", "O1", "D1", "H1"], ["D1", "H1"], monkeypatch)
    assert "Fe" in info["coord_atoms"] and "O1" in info["coord_atoms"]
    assert "D1" not in info["coord_atoms"] and "H1" not in info["coord_atoms"]


def test_no_frozen_keeps_all(monkeypatch):
    info = _info(["Fe", "O1", "D1"], [], monkeypatch)
    assert set(info["coord_atoms"]) == {"Fe", "O1", "D1"}
