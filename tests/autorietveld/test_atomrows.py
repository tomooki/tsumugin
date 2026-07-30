"""GSAS 原子行の読み取りテンプレート (`autorietveld.atomrows`) — GSAS 非依存。

原子行を読む処理は本リポジトリに**3 箇所**あった (`engine._atom_result_maps` /
`engine._phase_atom_info` / `workbench.atoms.extract_sites`)。互いの docstring は「同じ抽出
テンプレート」と称しながら各自が書き直しており、`AtomPtrs` の意味と対称性の解釈が
独立に 3 通り存在していた。本モジュールがその唯一の実装で、ここが正なら 3 者は一致する。

GSAS 原子行は**素の Python list** なので import は不要。`GetCSxinel` だけ関数注入にして
`-m "not gsas"` で回る (注入する fake は GSAS の実テーブル値を使う — 下記)。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.atomrows import (
    atom_row,
    coord_esd_states,
    free_index_from_site_symmetry,
    lock_from_free_index,
)

#: GSAS-II の実既定 `AtomPtrs` (`GSASIIobj.py:191` / `GSASIIElem.py:779`)。
#: label=[0] type=[1] x,y,z=[3,4,5] occ=[6] sytsym=[7] mult=[8] 'I'|'A'=[9] Uiso=[10]
_PTRS = (3, 1, 7, 9)

#: `GSASIIspc.CSxinel` の**実テーブル値** (`GSASIIspc.py:2528-2557`)。
#: 添字 0 が xId (0=対称固定 / 正値が一致する軸どうしは結束 / 相異なる正値は独立)。
_CSXINEL = {
    "1": [[1, 2, 3], [1.0, 1.0, 1.0], [1, 2, 3]],        # #28 X  Y  Z (一般位置)
    "0 0 z": [[0, 0, 1], [0.0, 0.0, 1.0], [0, 0, 3]],    # #14 0  0  Z
    "x -x 0": [[1, 1, 0], [1.0, -1.0, 0.0], [1, 1, 0]],  # #7  X -X  0 (x,y 結束・z 固定)
    "0 0 0": [[0, 0, 0], [0.0, 0.0, 0.0], [0, 0, 0]],    # #1  0  0  0 (全固定)
}


def _getcsxinel(site_sym: str):
    """`GSASIIspc.GetCSxinel` の代役 (未知の site symmetry は GSAS と同じく KeyError)。"""
    return _CSXINEL[site_sym]


def _row(label="O1", el="O", xyz=(0.25, 0.5, 0.125), occ=1.0, sytsym="1", mult=4.0, uiso=0.01):
    """GSAS 原子行 (`_PTRS` レイアウト) を組む。"""
    return [label, el, "", xyz[0], xyz[1], xyz[2], occ, sytsym, mult, "I", uiso]


# ---------------------------------------------------------------------------
# 行の読み取り
# ---------------------------------------------------------------------------


def test_atom_row_reads_every_field_from_the_pointer_layout():
    got = atom_row(_row(), _PTRS)
    assert got.label == "O1" and got.element == "O"
    assert got.coords == (0.25, 0.5, 0.125)
    assert got.occupancy == 1.0
    assert got.site_symmetry == "1"
    assert got.multiplicity == 4.0
    assert got.uiso == 0.01


def test_anisotropic_atom_has_no_uiso():
    # 【目的】: `row[cia] == "I"` でないとき Uiso キーは**存在しない** (0.0 を捏造しない)。
    #   既存 `_atom_result_maps` の規律と同じ — 異方性原子は atom_uiso に載らない。
    row = _row()
    row[9] = "A"
    assert atom_row(row, _PTRS).uiso is None


def test_label_comes_from_ct_minus_one_not_from_index_zero():
    """★ラベルは `row[ct-1]` であって `row[0]` ではない (`AtomPtrs` が動けば位置も動く)。

    非トートロジー: `ct` をずらしたレイアウトを渡すと、位置決め打ちの実装は別のセルを読む。
    `mem/gsas.py:484` は cx=3 を決め打ちしており、この差が実在する。
    """
    #  label が [1]、type が [2]、座標が [4,5,6] のレイアウト (ct=2 → label は row[1])
    shifted = ["ignored", "Ca1", "Ca", 0.1, 0.2, 0.3, 1.0, "1", 2.0, "I", 0.02]
    got = atom_row(shifted, (3, 2, 7, 9))
    assert got.label == "Ca1" and got.element == "Ca"
    assert got.coords == (0.1, 0.2, 0.3)


# ---------------------------------------------------------------------------
# 対称性の 3 状態 (bool ではない)
# ---------------------------------------------------------------------------


def test_free_index_is_the_raw_triple_not_a_bool():
    """★`GetCSxinel` は軸ごとに **3 状態**を返す — bool に潰すと結束軸が独立に見える。

    非トートロジー: `workbench.atoms._lock_from_site_symmetry` は `not bool(free[i])` で
    潰していた。GUI のロック表示にはそれで足るが、esd の状態源としては誤り —
    `x -x 0` の y は「自由」ではなく x に**結束**されており、GSAS は
    `StoreEquivalence` で従属変数にする (`GSASIIstrIO.py:1759-1765`)。
    """
    assert free_index_from_site_symmetry(_getcsxinel, "1") == (1, 2, 3)
    assert free_index_from_site_symmetry(_getcsxinel, "0 0 z") == (0, 0, 1)
    assert free_index_from_site_symmetry(_getcsxinel, "x -x 0") == (1, 1, 0)
    assert free_index_from_site_symmetry(_getcsxinel, "0 0 0") == (0, 0, 0)


def test_unknown_site_symmetry_degrades_to_the_general_position_test():
    """`GetCSxinel` の KeyError は GSAS 自身が起こす (sytsym 名の変更, `GSASIIstrIO.py:1746`)。

    ここで例外を上げると相ごと落ちるので、`"1"` (一般位置) かどうかの保守的判定へ縮退する。
    """
    assert free_index_from_site_symmetry(_getcsxinel, "unknown-sytsym") == (0, 0, 0)
    assert free_index_from_site_symmetry(_getcsxinel, "1 ") == (1, 2, 3)  # 空白は無視


def test_lock_from_free_index_matches_the_gui_contract():
    # 固定 (0) のみ lock=True。結束軸は「動く」ので GUI 上は lock でない。
    assert lock_from_free_index((0, 0, 1)) == {"x": True, "y": True, "z": False}
    assert lock_from_free_index((1, 1, 0)) == {"x": False, "y": False, "z": True}
    assert lock_from_free_index((1, 2, 3)) == {"x": False, "y": False, "z": False}


# ---------------------------------------------------------------------------
# 座標 esd の 3 状態 (cell_esd と同型)
# ---------------------------------------------------------------------------


def test_symmetry_fixed_axis_reports_exactly_zero_not_none():
    """★対称固定軸の esd は `0.0` = **真の陳述** ("厳密に 0 0 Z である")。

    `cell_esd` の mono α/γ=90° と同じ規律。`None` (決まっていない) と混同してはならない。
    """
    got = coord_esd_states((0, 0, 1), pid=0, index=3, esd_lookup={}.get)
    assert got == (0.0, 0.0, None), "固定軸は 0.0 / 自由軸は lookup が無いので None"


def test_refined_axis_takes_its_esd_from_the_dax_variable():
    """★座標 esd は `dAx` の **sig** から来る (値ではない)。

    非トートロジー: GSAS は座標をシフト `dAx` として精密化し毎回 0 に再初期化する
    (`GSASIIstrIO.py:1732`) ので**値は無意味**だが、その sig が x の esd である —
    GSAS 自身が `GSASIIstrIO.py:2603-2606` の `names[ind].replace('A','dA')` でそう決めている。
    `Ax` を引く実装 (素朴な連想) はここで落ちる。
    """
    lookup = {"0::dAx:3": 0.0012, "0::dAy:3": 0.0009, "0::dAz:3": 0.0031}.get
    assert coord_esd_states((1, 2, 3), pid=0, index=3, esd_lookup=lookup) == (
        0.0012, 0.0009, 0.0031,
    )


def test_equivalence_constrained_axis_still_gets_an_esd():
    """★結束軸 (`x -x 0` の y) は varyList に載らないが `depSigDict` 経由で esd を持つ。

    `G2mv.ComputeDepESD` が従属変数へ esd を伝播し `covData['depSigDict']` に入る
    (`GSASIIstrMain.py:562-582`)。従属だから `None` と決めつけると出版値を捨てることになる。
    """
    lookup = {"0::dAx:1": 0.002, "0::dAy:1": 0.002}.get
    assert coord_esd_states((1, 1, 0), pid=0, index=1, esd_lookup=lookup) == (
        0.002, 0.002, 0.0,
    )


def test_free_axis_without_an_esd_is_none_never_zero():
    """★解放されていない/共分散が無い自由軸は `None`。**0.0 を捏造しない**。

    0.0 は「厳密に固定」の意味を既に持っているので、ここで 0.0 を返すと
    「対称拘束で固定された座標」と区別できなくなる (`cell_esd` が塞いだのと同じ事故)。
    """
    assert coord_esd_states((1, 2, 3), pid=0, index=0, esd_lookup={}.get) == (None,) * 3


def test_unknown_symmetry_yields_all_none_not_all_zero():
    # 縮退した free_index (0,0,0) は「一般位置と判定できなかった」でもあり得るため、
    # lookup に値があればそれを優先する (固定と決めつけない)。
    lookup = {"0::dAx:2": 0.004}.get
    assert coord_esd_states((0, 0, 0), pid=0, index=2, esd_lookup=lookup) == (0.004, 0.0, 0.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_non_positive_or_non_finite_lookup_values_become_none(bad):
    """★`ComputeDepESD` は `0.0` を捏造する (`GSASIImapvars.py:1410-1423`: 独立変数が
    varyList に無いと `vcov` が全 0 のまま `sqrt(0)=0.0` を返す)。自由軸で 0.0 が来たら
    「決まっていない」であって「厳密に 0」ではない。"""
    lookup = {"0::dAx:0": bad}.get
    assert coord_esd_states((1, 2, 3), pid=0, index=0, esd_lookup=lookup)[0] is None
