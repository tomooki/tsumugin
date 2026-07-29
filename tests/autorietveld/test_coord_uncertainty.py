"""座標/Uiso/プロファイル esd の結果配線 (`_atom_result_maps` / `_profile_esd_map`) — GSAS 非依存。

2 つの精密化手順が**同じ解に収束したか**は Rwp では判定できない (T3 実測: Rwp 差 0.361 で
格子 0.161% 違い)。判定には座標と esd が要るが、座標は結果に一切載っていなかった。
ここで固定するのは**捏造しないこと**と**相を落とさないこと**。

実 GSAS 版は `test_coord_uncertainty_gsas.py`。
"""

from __future__ import annotations

import dataclasses

import pytest

from tsumugin.autorietveld.engine import AtomMaps, _atom_result_maps, _profile_esd_map
from tsumugin.autorietveld.model import AutoRietveldResult, ValidityReport, coerce_coord_esd

#: GSAS-II の実既定 `AtomPtrs` (`GSASIIobj.py:191`)。
_PTRS = (3, 1, 7, 9)

#: `GSASIIspc.CSxinel` の**実テーブル値** (`GSASIIspc.py:2528-2557`) を注入する。
#: ⚠ **実 `GetCSxinel` を使ってはならない** — この機械には GSAS が入っているので実関数が走り、
#: CI (GSAS 無し) では縮退経路が走る = 同じテストが環境で別の答えを出す (CI 導入時に 44 件が
#: 踏んだ穴と同型)。注入すればどちらの環境でも同一。
_CSXINEL = {
    "1": [[1, 2, 3], [1.0, 1.0, 1.0], [1, 2, 3]],        # #28 X Y Z (一般位置)
    "0 0 z": [[0, 0, 1], [0.0, 0.0, 1.0], [0, 0, 3]],    # #14 0 0 Z
    "x -x 0": [[1, 1, 0], [1.0, -1.0, 0.0], [1, 1, 0]],  # #7  X -X 0 (x,y 結束・z 固定)
}


def _getcsxinel(site_sym: str):
    return _CSXINEL[site_sym]


class _FakeProject:
    """``ph.proj["Covariance"]["data"]`` を提供する最小プロジェクト。"""

    def __init__(self, cov: dict | None):
        self._cov = cov if cov is not None else {}

    def __getitem__(self, key: str) -> dict:
        if key != "Covariance":
            raise KeyError(key)
        return {"data": self._cov}

    # `read_variable_esds` は gpx.data["Covariance"] を見るため data も生やす
    @property
    def data(self) -> dict:
        return {"Covariance": {"data": self._cov}}


class _FakePhase:
    def __init__(self, name: str, pid: int, atoms: list[list], cov: dict | None = None):
        self.name = name
        self.id = pid
        self.data = {"Atoms": atoms, "General": {"AtomPtrs": list(_PTRS)}}
        self.proj = _FakeProject(cov)


def _atom(label, xyz, sytsym="1", occ=1.0, mult=4.0, uiso=0.01, adp="I"):
    return [label, label[0], "", xyz[0], xyz[1], xyz[2], occ, sytsym, mult, adp, uiso]


# ---------------------------------------------------------------------------
# 戻り値の形 (位置タプルへ戻さない)
# ---------------------------------------------------------------------------


def test_atom_maps_is_a_dataclass_not_a_widening_tuple():
    """★戻り値は dataclass。位置タプルへ戻すと次の追加で静かに別の値を読む。

    非トートロジー: 元は 4 要素タプルで、事前警告の呼び出し側が ``_, uiso_init, _, _`` と
    位置で受けていた。8 要素に増えた今、9 要素目を足した人が位置をずらす事故が現実的。
    """
    maps = _atom_result_maps([], getcsxinel=_getcsxinel)
    assert dataclasses.is_dataclass(maps) and isinstance(maps, AtomMaps)
    with pytest.raises(TypeError):
        _a, _b, _c, _d = maps  # 位置アンパック不可 = 位置依存の呼び出し側を作らせない


def test_pre_refinement_call_site_still_sees_uiso():
    # engine の事前警告 (`check_initial_uiso`) が使う経路。名前アクセスで壊れないこと。
    ph = _FakePhase("p", 0, [_atom("O1", (0.1, 0.2, 0.3))])
    assert _atom_result_maps([ph], getcsxinel=_getcsxinel).uiso == {"p": {"O1": 0.01}}


# ---------------------------------------------------------------------------
# 座標と esd
# ---------------------------------------------------------------------------


def test_coords_come_from_the_atom_row():
    ph = _FakePhase("p", 0, [_atom("O1", (0.25, 0.5, 0.125))])
    got = _atom_result_maps([ph], getcsxinel=_getcsxinel).coords
    assert got == {"p": {"O1": (0.25, 0.5, 0.125)}}


def test_coord_esd_uses_dax_sig_and_keeps_three_states():
    """★一般位置は dAx の sig、対称固定軸は 0.0、決まっていない軸は None。"""
    atoms = [_atom("O1", (0.25, 0.5, 0.125)), _atom("Ca1", (0.0, 0.0, 0.3), sytsym="0 0 z")]
    cov = {"varyList": ["0::dAx:0", "0::dAy:0", "0::dAz:0"], "sig": [0.001, 0.002, 0.003]}
    ph = _FakePhase("p", 0, atoms, cov)

    got = _atom_result_maps([ph], getcsxinel=_getcsxinel).coord_esd["p"]
    assert got["O1"] == (0.001, 0.002, 0.003)
    # Ca1 は "0 0 z": x,y は対称固定 (0.0 = 真の陳述)、z は解放していない (None)
    assert got["Ca1"] == (0.0, 0.0, None)


def test_uiso_esd_is_two_state_and_absent_for_anisotropic_atoms():
    atoms = [_atom("O1", (0.1, 0.2, 0.3)), _atom("Fe1", (0.0, 0.0, 0.0), adp="A")]
    cov = {"varyList": ["0::AUiso:0"], "sig": [0.0009]}
    maps = _atom_result_maps([_FakePhase("p", 0, atoms, cov)], getcsxinel=_getcsxinel)
    assert maps.uiso_esd["p"] == {"O1": 0.0009}, "異方性原子はキーごと欠落 (0.0 を捏造しない)"
    assert "Fe1" not in maps.uiso


def test_no_covariance_yields_none_esds_never_zero():
    """★共分散が無い (未精密化/失敗) 場合、esd は None。**0.0 にしない**。"""
    ph = _FakePhase("p", 0, [_atom("O1", (0.1, 0.2, 0.3))], cov=None)
    maps = _atom_result_maps([ph], getcsxinel=_getcsxinel)
    assert maps.coord_esd["p"]["O1"] == (None, None, None)
    assert maps.uiso_esd["p"]["O1"] is None
    assert maps.occupancy_esd["p"]["O1"] is None
    # 値そのものは読めている (esd が無いだけで相を落とさない)
    assert maps.coords["p"]["O1"] == (0.1, 0.2, 0.3)


def test_free_index_is_recorded_per_axis():
    atoms = [_atom("O1", (0.1, 0.2, 0.3)), _atom("Ca1", (0.0, 0.0, 0.3), sytsym="0 0 z")]
    got = _atom_result_maps(
        [_FakePhase("p", 0, atoms)], getcsxinel=_getcsxinel
    ).coord_free_index["p"]
    assert got["O1"] == (1, 2, 3)
    assert got["Ca1"] == (0, 0, 1)


def test_a_broken_phase_is_skipped_without_losing_the_others():
    good = _FakePhase("good", 0, [_atom("O1", (0.1, 0.2, 0.3))])
    broken = _FakePhase("broken", 1, [_atom("X", (0, 0, 0))])
    broken.data = {"Atoms": "not-a-list-of-rows", "General": {}}
    maps = _atom_result_maps([good, broken], getcsxinel=_getcsxinel)
    assert set(maps.coords) == {"good"}


def test_phase_id_prefix_is_used_so_other_phases_esds_are_not_borrowed():
    """★別相の dAx を自相のものと取り違えないこと (pId プレフィクスで識別)。

    非トートロジー: 多相では主相だけ座標を解放するのが普通なので、プレフィクスを見ない
    実装は**凍結した副相にも esd を配る** (`_cell_was_refined` が塞いだのと同型の事故)。
    """
    cov = {"varyList": ["0::dAx:0"], "sig": [0.001]}
    minor = _FakePhase("minor", 2, [_atom("O1", (0.1, 0.2, 0.3))], cov)
    got = _atom_result_maps([minor], getcsxinel=_getcsxinel).coord_esd["minor"]
    assert got["O1"] == (None, None, None)


# ---------------------------------------------------------------------------
# プロファイル esd
# ---------------------------------------------------------------------------


class _FakeHist:
    def __init__(self, hid: int, inst: dict, cov: dict | None = None):
        self.id = hid
        self.data = {"Instrument Parameters": [inst]}
        self.proj = _FakeProject(cov)


def test_profile_esd_uses_the_histogram_id_not_the_enumeration_index():
    """★装置変数名は ``:{hist.id}:{key}`` — 列挙索引ではない。

    非トートロジー: 単一プロジェクトでは両者が一致するので既存の `_apply_profile_bounds`
    (enumerate 索引) は実害を出していない。id が索引とずれる構成でだけ差が出る。
    """
    inst = {"U": [1.0, 2.0, True], "V": [0.0, -1.0, True]}
    cov = {"varyList": [":3:U", ":0:U"], "sig": [0.5, 9.9]}
    got = _profile_esd_map([_FakeHist(3, inst, cov)])
    assert got[0]["U"] == 0.5, "hist.id=3 の esd を引くこと (索引 0 の 9.9 ではない)"
    assert got[0]["V"] is None


def test_profile_esd_degrades_to_empty_when_instrument_params_are_missing():
    h = _FakeHist(0, {})
    h.data = {}
    assert _profile_esd_map([h]) == ({},)


# ---------------------------------------------------------------------------
# 後方互換 / 型
# ---------------------------------------------------------------------------


def test_new_fields_default_to_empty_for_back_compat():
    r = AutoRietveldResult(
        stage_results=(),
        final_rwp=1.0,
        final_gof=1.0,
        refined_cells={},
        validity=ValidityReport(passed=True),
    )
    assert r.atom_coords == {} and r.atom_coord_esd == {}
    assert r.atom_coord_free_index == {} and r.atom_uiso_esd == {}
    assert r.hist_profile_refined == () and r.hist_profile_esd == ()


def test_coerce_coord_esd_keeps_none_and_zero_distinct():
    """★``coerce_coord_esd`` が存在する理由: `float(None)` を避けるために 0.0 へ丸めさせない。"""
    assert coerce_coord_esd([0.001, None, 0.0]) == (0.001, None, 0.0)
    assert coerce_coord_esd([float("nan"), 1.0, None]) == (None, 1.0, None)
    with pytest.raises(ValueError):
        coerce_coord_esd([0.1, 0.2])


def test_a_failing_getcsxinel_does_not_drop_the_phase():
    """★`GetCSxinel` の失敗で**相ごと落としてはならない**。

    非トートロジー: GSAS 自身が sytsym 名の変更で KeyError を出し、その場でパッチしている
    (`GSASIIstrIO.py:1746-1749`)。それが相ごとの ``except`` に届くと ``uiso`` まで落ち、
    `check_initial_uiso` の事前警告が**黙って**弱まる (Uiso 発散が検出されなくなる)。
    振る舞いで固定するので、防御が engine 側か `atomrows` 側かに依らず有効。
    """

    def _always_raises(_sym):
        raise KeyError("sytsym name changed")

    atoms = [
        _atom("O1", (0.1, 0.2, 0.3)),                          # 一般位置 (sytsym "1")
        _atom("Ca1", (0.0, 0.0, 0.3), sytsym="0 0 z"),         # 特殊位置
    ]
    maps = _atom_result_maps([_FakePhase("p", 0, atoms)], getcsxinel=_always_raises)

    assert maps.uiso == {"p": {"O1": 0.01, "Ca1": 0.01}}, "自由度判定の失敗で uiso を失わない"
    assert maps.coords["p"]["O1"] == (0.1, 0.2, 0.3)
    # 判定不能時の縮退は sytsym 文字列だけを見る保守的判定 (`atomrows` の契約):
    #   "1" は一般位置とみなし全独立、それ以外は全固定扱い。
    assert maps.coord_free_index["p"]["O1"] == (1, 2, 3)
    assert maps.coord_free_index["p"]["Ca1"] == (0, 0, 0)
