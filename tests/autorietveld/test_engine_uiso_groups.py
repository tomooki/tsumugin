"""fit-then-judge P1a タスク 2: `PhaseSpec.uiso_equiv_groups` の engine 配線。

- 決定論: 段の原子フラグ更新が「等値の組の一部だけに U を立てる」ことを例外で止めること。
  混合占有だけの既存経路 (``uiso_groups`` が空) は従来どおり止めないこと。
- gated (T2 garnet, CW 中性子 — fit-then-judge の hold-out 外): 混合占有の組と合併した 4 原子の
  Uiso が**ビット同一**に揃い、指定しなければ揃わないこと (陰性対照)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld.engine import _update_atom_flags


def _info(**over):
    info = {
        "labels": ["Y1", "Fe1", "Al1", "Al2", "Fe2", "O1"],
        "coord_atoms": ["O1"],
        "mixed": {"Fe1", "Al1", "Al2", "Fe2"},
        "free_occ": set(),
        "equiv_occ": set(),
        "uiso_labels": None,
        "frozen_uiso": set(),
        "element_of": {"Y1": "Y", "Fe1": "Fe", "Al1": "Al", "Al2": "Al", "Fe2": "Fe", "O1": "O"},
        "uiso_groups": (("Fe1", "Al1", "Al2", "Fe2"),),
    }
    info.update(over)
    return info


def test_full_release_of_a_group_is_allowed():
    flags: dict[str, str] = {}
    _update_atom_flags(flags, _info(), {"uiso": True})
    assert all("U" in flags[lab] for lab in ("Fe1", "Al1", "Al2", "Fe2"))


def test_partial_release_by_frozen_label_is_refused():
    with pytest.raises(ValueError, match="一部だけ"):
        _update_atom_flags({}, _info(frozen_uiso={"Al2"}), {"uiso": True})


def test_partial_release_by_element_rank_is_refused():
    # rank 1 = 最重元素 (Y) … Fe は rank 2。Fe だけ解放すると組 (Fe,Al) が割れる。
    with pytest.raises(ValueError, match="一部だけ"):
        _update_atom_flags({}, _info(), {"uiso": 2})


def test_existing_mixed_only_route_is_not_checked():
    """`uiso_equiv_groups` を使わない既存経路の挙動は変えない (検査しない)。"""
    flags: dict[str, str] = {}
    _update_atom_flags(flags, _info(uiso_groups=(), frozen_uiso={"Al2"}), {"uiso": True})
    assert "U" in flags["Fe1"] and "U" not in flags.get("Al2", "")


_T2 = Path("docs/benchmark/testdata/m7/cwneutron")


def _t2_present() -> bool:
    return all((_T2 / f).exists() for f in ("garnet.raw", "garnet_YFeAlO.cif", "inst_d1a.prm"))


def _run_t2(uiso_equiv_groups, tmp_path, monkeypatch):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path))
    hist = HistogramSpec(
        data_path=str(_T2 / "garnet.raw"),
        instrument_path=str(_T2 / "inst_d1a.prm"),
        radiation=Radiation.NEUTRON_CW,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="GSAS",
    )
    phase = PhaseSpec(
        structure_path=str(_T2 / "garnet_YFeAlO.cif"),
        phase_name="garnet",
        mixed_occupancy_groups=(("Fe1", "Al1"), ("Al2", "Fe2")),
        uiso_equiv_groups=uiso_equiv_groups,
    )
    return run_auto_rietveld([hist], [phase])


@pytest.mark.gsas
@pytest.mark.skipif(not _t2_present(), reason="M7 T2 データ未取得")
def test_merged_uiso_group_is_bit_identical_on_garnet(tmp_path, monkeypatch):
    result = _run_t2((("Fe1", "Al2"),), tmp_path / "with", monkeypatch)
    u = result.atom_uiso["garnet"]
    merged = [u["Fe1"], u["Al1"], u["Al2"], u["Fe2"]]
    assert len(set(merged)) == 1, f"合併した組の Uiso が揃っていない: {merged}"
    assert u["Y1"] != merged[0] and u["O1"] != merged[0], "組の外まで揃っている"
    # 等値の組を張っても段が失敗していないこと (例外は revert_reason=error になる)
    assert all(s.revert_reason != "error" for s in result.stage_results), [
        (s.label, s.revert_reason) for s in result.stage_results
    ]


@pytest.mark.gsas
@pytest.mark.skipif(not _t2_present(), reason="M7 T2 データ未取得")
def test_without_the_group_the_two_sites_differ_negative_control(tmp_path, monkeypatch):
    """陰性対照: 指定しなければ 16a と 24d の Uiso は揃わない (上のテストが空振りでない)。"""
    u = _run_t2((), tmp_path / "without", monkeypatch).atom_uiso["garnet"]
    assert u["Fe1"] != u["Al2"]
