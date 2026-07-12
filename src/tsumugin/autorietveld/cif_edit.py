"""原子レベルの CIF 編集 (autorietveld.cif_edit) — M8-③ MEM model-fix Phase A。

MEM 密度の解釈 (③) から得た**具体的な構造編集** (欠損原子の追加・座標移動・占有率是正・原子除去)
を CIF に適用し、新しい CIF を書き出す決定論ヘルパ。``ReviseStructure`` ModelAction が
「③ が編集した CIF の ``structure_path`` を差し替える」際の、その CIF を機械的に生成する部分を担う。
③ の手編集を不要にし、編集を単体テスト可能にする。

【設計】``cif_normalize`` の ``Structure``/``Atom``/``read_structure_cif``/``write_gsas_cif`` を再利用し、
  原子列 (``Structure.atoms``) への純変換として編集を表現する。特殊位置・対称操作には踏み込まない
  (与えられた分率座標をそのまま書く; 対称展開は GSAS が行う)。

【非破壊 (P2)】入力 CIF は読むだけで改変しない。編集結果は ``out_path`` へ新規に書く。
【決定論】編集を順に適用し、``write_gsas_cif`` の固定書式で出力するためビット同一。
【純 text (REQ-403)】``import tsumugin.autorietveld.cif_edit`` は numpy すら不要 (stdlib のみ)。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Literal, Sequence

from .cif_normalize import Atom, Structure, read_structure_cif, write_gsas_cif

__all__ = ["AtomEdit", "apply_atom_edits", "apply_edits_to_structure"]

# add 時の既定値 (占有率 1.0・Uiso 0.025 Å²)。
_DEFAULT_OCC = 1.0
_DEFAULT_UISO = 0.025

_OPS = ("add", "move", "set_occupancy", "set_uiso", "remove")


@dataclass(frozen=True)
class AtomEdit:
    """1 個の原子編集 (MEM 解釈由来の具体編集)。🔵 M8-③

    :param op: ``add`` | ``move`` | ``set_occupancy`` | ``set_uiso`` | ``remove``
    :param label: 対象/新規原子ラベル
    :param element: 元素記号 (``add`` で必須; type_symbol)
    :param frac: 分率座標 (x,y,z) (``add``/``move`` で必須)
    :param occ: 占有率 (``add``/``set_occupancy`` で使用; add 既定 1.0)
    :param uiso: 等方変位 Uiso (``add``/``set_uiso`` で使用; add 既定 0.025)
    """

    op: Literal["add", "move", "set_occupancy", "set_uiso", "remove"]
    label: str
    element: str | None = None
    frac: tuple[float, float, float] | None = None
    occ: float | None = None
    uiso: float | None = None


def _labels(structure: Structure) -> dict[str, int]:
    """ラベル→原子索引の辞書 (存在判定用)。"""
    return {a.label: i for i, a in enumerate(structure.atoms)}


def _apply_one(structure: Structure, edit: AtomEdit) -> Structure:
    """1 編集を Structure へ純適用する (fail-loud)。🔵"""
    atoms = list(structure.atoms)
    idx = _labels(structure)

    if edit.op == "add":
        if edit.label in idx:
            raise ValueError(f"add: ラベル {edit.label!r} は既に存在します (重複追加不可)。")
        if edit.element is None or edit.frac is None:
            raise ValueError(f"add: {edit.label!r} は element と frac が必須です。")
        atoms.append(
            Atom(
                label=edit.label, type_symbol=edit.element,
                x=float(edit.frac[0]), y=float(edit.frac[1]), z=float(edit.frac[2]),
                occ=_DEFAULT_OCC if edit.occ is None else float(edit.occ),
                uiso=_DEFAULT_UISO if edit.uiso is None else float(edit.uiso),
            )
        )
        return dataclasses.replace(structure, atoms=tuple(atoms))

    if edit.op not in _OPS:
        raise ValueError(f"未知の編集 op: {edit.op!r} (対応: {_OPS})")

    # move/set_*/remove は既存ラベル必須。
    if edit.label not in idx:
        raise KeyError(f"{edit.op}: ラベル {edit.label!r} が CIF に存在しません。")
    i = idx[edit.label]

    if edit.op == "remove":
        del atoms[i]
        return dataclasses.replace(structure, atoms=tuple(atoms))

    if edit.op == "move":
        if edit.frac is None:
            raise ValueError(f"move: {edit.label!r} は frac が必須です。")
        atoms[i] = dataclasses.replace(
            atoms[i], x=float(edit.frac[0]), y=float(edit.frac[1]), z=float(edit.frac[2])
        )
    elif edit.op == "set_occupancy":
        if edit.occ is None:
            raise ValueError(f"set_occupancy: {edit.label!r} は occ が必須です。")
        atoms[i] = dataclasses.replace(atoms[i], occ=float(edit.occ))
    elif edit.op == "set_uiso":
        if edit.uiso is None:
            raise ValueError(f"set_uiso: {edit.label!r} は uiso が必須です。")
        atoms[i] = dataclasses.replace(atoms[i], uiso=float(edit.uiso))
    return dataclasses.replace(structure, atoms=tuple(atoms))


def apply_edits_to_structure(
    structure: Structure, edits: Sequence[AtomEdit]
) -> Structure:
    """編集列を順に Structure へ適用した新 Structure を返す (純関数・元不変)。🔵 M8-③

    編集は与えられた順に適用する (add してから同じ原子を move する等が可能)。各編集は fail-loud。
    """
    result = structure
    for edit in edits:
        result = _apply_one(result, edit)
    return result


def apply_atom_edits(
    cif_path: str,
    edits: Sequence[AtomEdit],
    out_path: str,
    *,
    phase_name: str = "phase",
) -> str:
    """CIF を読み、原子編集を適用し、新 CIF を ``out_path`` へ書いてパスを返す。🔵 M8-③

    【非破壊 (P2)】入力 ``cif_path`` は改変しない。結果は新規ファイル。
    【決定論】``write_gsas_cif`` の固定書式で出力しビット同一。
    """
    structure = read_structure_cif(cif_path)
    edited = apply_edits_to_structure(structure, edits)
    write_gsas_cif(edited, out_path, phase_name=phase_name)
    return str(out_path)
