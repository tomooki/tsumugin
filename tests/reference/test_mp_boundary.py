"""M6 TASK-0102/0103 Materials Project 境界の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/mp/`` (未実装)。
extra ``mp`` (pymatgen/mp-api) 非導入でも走る契約テスト:
- ``import tsumugin.mp`` はコア (numpy) のみで成功する。
- pymatgen/mp_api を要求する呼び出しは ``MPUnavailableError`` へ縮退する。
- ``MPReferenceProvider`` は DI フェイク (client + simulate) で相同定コアと結線できる。

``@pytest.mark.mp`` を付けたテストは extra 導入環境でのみ実 XRD 生成の決定論を検証する。
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence

import pytest

from tsumugin.errors import MPUnavailableError
from tsumugin.reference.model import ReferencePhase
from tsumugin.reference.provider import ReferenceProvider
from tsumugin.search.peaks import Peak

_HAS_PYMATGEN = importlib.util.find_spec("pymatgen") is not None
_HAS_MP_API = importlib.util.find_spec("mp_api") is not None


# --- import 契約 (extra 非依存) --------------------------------------------


def test_import_mp_package_core_only():
    import tsumugin.mp as mp  # noqa: F401  コア import は pymatgen/mp_api を引き込まない

    assert hasattr(mp, "MPEntry")
    assert hasattr(mp, "MPReferenceProvider")


def test_mp_entry_is_core_value_object():
    from tsumugin.mp import MPEntry

    entry = MPEntry(
        material_id="mp-19017",
        formula="LiFePO4",
        element_system=("Fe", "Li", "O", "P"),
        structure=object(),
        energy_above_hull=0.0,
        spacegroup="Pnma",
    )
    assert entry.material_id == "mp-19017"
    assert entry.energy_above_hull == 0.0


# --- 遅延 import 縮退 (extra 非導入時のみ意味を持つ) ------------------------


@pytest.mark.skipif(_HAS_PYMATGEN, reason="pymatgen 導入済みでは縮退経路に入らない")
def test_simulate_reference_peaks_raises_without_pymatgen():
    from tsumugin.mp.xrd import simulate_reference_peaks

    with pytest.raises(MPUnavailableError):
        simulate_reference_peaks(object())


@pytest.mark.skipif(_HAS_MP_API, reason="mp_api 導入済みでは縮退経路に入らない")
def test_mp_rest_client_search_raises_without_mp_api():
    from tsumugin.mp.client import MPRestClient

    client = MPRestClient(api_key="dummy")
    with pytest.raises(MPUnavailableError):
        client.search(["Fe", "O"])


def test_mp_rest_client_requires_api_key():
    from tsumugin.mp.client import MPRestClient

    # 明示キーも環境変数も無ければ構築時に分かりやすく失敗する (mp_api を import せずに)
    with pytest.raises(ValueError):
        MPRestClient(api_key=None, _env={})


def test_mp_rest_client_reads_env_key():
    from tsumugin.mp.client import MPRestClient

    client = MPRestClient(api_key=None, _env={"MATERIALS_PROJECT_API": "secret"})
    assert client.api_key == "secret"


def test_mp_rest_client_strips_env_key_whitespace():
    # .env は "MATERIALS_PROJECT_API = key" 形式で前後空白が入り得る
    from tsumugin.mp.client import MPRestClient

    client = MPRestClient(api_key=None, _env={"MATERIALS_PROJECT_API": "  secret  "})
    assert client.api_key == "secret"


def test_chemsys_query_includes_all_subsystems():
    # 相同定では単体相・下位系も候補になり得るため全部分系をクエリする (FR-100 網羅性)
    from tsumugin.mp.client import MPRestClient

    client = MPRestClient(api_key="dummy", include_subsystems=True)
    systems = client._chemsys_query(["O", "Ti"])
    assert set(systems) == {"O", "Ti", "O-Ti"}  # 昇順・全非空部分集合


def test_chemsys_query_full_system_only_when_disabled():
    from tsumugin.mp.client import MPRestClient

    client = MPRestClient(api_key="dummy", include_subsystems=False)
    assert client._chemsys_query(["Ti", "O", "Fe"]) == "Fe-O-Ti"  # 完全系 1 本 (昇順)


def test_chemsys_query_dedups_and_sorts_elements():
    from tsumugin.mp.client import MPRestClient

    client = MPRestClient(api_key="dummy", include_subsystems=True)
    systems = client._chemsys_query(["Fe", "Fe", "O"])
    assert set(systems) == {"Fe", "O", "Fe-O"}


def test_mp_rest_client_rejects_whitespace_only_key():
    from tsumugin.mp.client import MPRestClient

    with pytest.raises(ValueError):
        MPRestClient(api_key=None, _env={"MATERIALS_PROJECT_API": "   "})


def test_doc_to_entry_normalizes_mp_api_doc():
    # mp_api summary doc の形状 (属性アクセス) を MPEntry へ正規化する (ネットワーク不要)
    import types

    from tsumugin.mp.client import MPEntry, _doc_to_entry

    doc = types.SimpleNamespace(
        material_id="mp-19017",
        formula_pretty="LiFePO4",
        elements=["Li", "Fe", "P", "O"],
        structure="STRUCT",
        energy_above_hull=0.0,
        symmetry=types.SimpleNamespace(symbol="Pnma"),
    )
    entry = _doc_to_entry(doc)
    assert isinstance(entry, MPEntry)
    assert entry.material_id == "mp-19017"
    assert entry.formula == "LiFePO4"
    assert entry.element_system == ("Fe", "Li", "O", "P")  # 昇順に正規化
    assert entry.structure == "STRUCT"
    assert entry.energy_above_hull == 0.0
    assert entry.spacegroup == "Pnma"


def test_doc_to_entry_handles_missing_fields():
    import types

    from tsumugin.mp.client import _doc_to_entry

    doc = types.SimpleNamespace()  # 全フィールド欠落
    entry = _doc_to_entry(doc)
    assert entry.material_id == ""
    assert entry.element_system == ()
    assert entry.energy_above_hull is None
    assert entry.spacegroup is None
    assert entry.structure is None


# --- MPReferenceProvider (DI フェイクでコア結線を検証) ---------------------


class _FakeClient:
    """``MPClient`` を満たす in-memory テストダブル。"""

    def __init__(self, entries) -> None:
        self._entries = tuple(entries)
        self.calls: list[tuple[str, ...]] = []

    def search(self, elements: Sequence[str]):
        self.calls.append(tuple(elements))
        return self._entries


def _entry(mid: str, *, elements, ehull=0.0, struct_tag: str = "s"):
    from tsumugin.mp import MPEntry

    return MPEntry(
        material_id=mid,
        formula="X",
        element_system=tuple(sorted(elements)),
        structure=struct_tag,  # 不透明ハンドル。フェイク simulate がタグで peaks を決める
        energy_above_hull=ehull,
        spacegroup="P1",
    )


def _fake_simulate_factory():
    def _sim(structure, **kwargs):
        # struct_tag ごとに決定論的な peaks を返す
        table = {
            "a": (Peak(20.0, 100.0), Peak(30.0, 50.0)),
            "b": (Peak(25.0, 100.0),),
        }
        return table.get(structure, (Peak(20.0, 100.0),))
    return _sim


def test_provider_satisfies_reference_provider_protocol():
    from tsumugin.mp import MPReferenceProvider

    prov = MPReferenceProvider(_FakeClient([]), simulate=_fake_simulate_factory())
    assert isinstance(prov, ReferenceProvider)


def test_provider_fetch_builds_reference_phases():
    from tsumugin.mp import MPReferenceProvider

    client = _FakeClient([
        _entry("mp-1", elements=["Fe", "O"], struct_tag="a"),
        _entry("mp-2", elements=["Fe", "O"], struct_tag="b"),
    ])
    # dedup は pymatgen StructureMatcher を要するため、build ロジック単体検証では無効化する。
    prov = MPReferenceProvider(client, simulate=_fake_simulate_factory(), deduplicate=False)
    refs = prov.fetch(["Fe", "O"])

    assert all(isinstance(r, ReferencePhase) for r in refs)
    by_id = {r.phase_id: r for r in refs}
    assert by_id["mp-1"].peaks == (Peak(20.0, 100.0), Peak(30.0, 50.0))
    assert by_id["mp-1"].formula == "X"
    assert by_id["mp-1"].energy_above_hull == 0.0
    assert client.calls == [("Fe", "O")]


def test_provider_populates_cell_and_crystal_system_via_injected_meta():
    """Issue #20 hybrid: structure_meta を注入すると cell/crystal_system が ReferencePhase に載る。"""
    from tsumugin.mp import MPReferenceProvider

    client = _FakeClient([_entry("mp-1", elements=["Fe", "O"], struct_tag="a")])

    def fake_meta(structure):
        return (5.0, 6.0, 7.0, 90.0, 90.0, 90.0), "orthorhombic"

    prov = MPReferenceProvider(
        client, simulate=_fake_simulate_factory(), deduplicate=False, structure_meta=fake_meta
    )
    ref = prov.fetch(["Fe", "O"])[0]
    assert ref.cell == (5.0, 6.0, 7.0, 90.0, 90.0, 90.0)
    assert ref.crystal_system == "orthorhombic"


def test_provider_degrades_when_structure_meta_fails():
    """フェイク構造/pymatgen 無しで structure_meta が例外を投げても cell/crystal_system=None で継続。"""
    from tsumugin.mp import MPReferenceProvider

    client = _FakeClient([_entry("mp-1", elements=["Fe", "O"], struct_tag="a")])

    def boom(structure):
        raise ValueError("not a pymatgen structure")

    prov = MPReferenceProvider(
        client, simulate=_fake_simulate_factory(), deduplicate=False, structure_meta=boom
    )
    ref = prov.fetch(["Fe", "O"])[0]
    assert ref.cell is None
    assert ref.crystal_system is None
    # ピーク等の他フィールドは通常通り
    assert ref.peaks == (Peak(20.0, 100.0), Peak(30.0, 50.0))


def test_provider_default_meta_degrades_on_fake_structure():
    """既定 structure_meta (pymatgen) はフェイク文字列構造では失敗し None に縮退する (回帰なし)。"""
    from tsumugin.mp import MPReferenceProvider

    client = _FakeClient([_entry("mp-1", elements=["Fe", "O"], struct_tag="a")])
    prov = MPReferenceProvider(client, simulate=_fake_simulate_factory(), deduplicate=False)
    ref = prov.fetch(["Fe", "O"])[0]
    assert ref.cell is None and ref.crystal_system is None


def test_provider_deduplicates_via_injected_group():
    # FR-102: 等価構造グループの代表 (最小 index) のみ残す。fake group で pymatgen 非依存に検証。
    from tsumugin.mp import MPReferenceProvider

    client = _FakeClient([
        _entry("mp-1", elements=["Fe", "O"], struct_tag="a"),
        _entry("mp-2", elements=["Fe", "O"], struct_tag="a"),  # mp-1 と等価
        _entry("mp-3", elements=["Fe", "O"], struct_tag="b"),
    ])
    # index 0,1 が等価グループ、2 は単独
    fake_group = lambda structs: [(0, 1), (2,)]  # noqa: E731
    prov = MPReferenceProvider(
        client, simulate=_fake_simulate_factory(), deduplicate=True, group=fake_group
    )
    refs = prov.fetch(["Fe", "O"])
    ids = sorted(r.phase_id for r in refs)
    assert ids == ["mp-1", "mp-3"]  # mp-2 は代表でないため除外


def test_provider_skips_entries_without_structure():
    from tsumugin.mp import MPEntry, MPReferenceProvider

    entry = MPEntry(
        material_id="mp-nostruct",
        formula="X",
        element_system=("Fe", "O"),
        structure=None,
        energy_above_hull=0.0,
    )
    prov = MPReferenceProvider(_FakeClient([entry]), simulate=_fake_simulate_factory())
    refs = prov.fetch(["Fe", "O"])
    assert refs == ()


def test_provider_end_to_end_with_identify():
    # MP 境界 → 相同定コアの結線: フェイク client + simulate で identify_phases が動く
    import numpy as np

    from tsumugin.mp import MPReferenceProvider
    from tsumugin.reference import identify_phases

    client = _FakeClient([_entry("mp-1", elements=["Fe", "O"], struct_tag="a")])
    prov = MPReferenceProvider(client, simulate=_fake_simulate_factory())

    two_theta = np.arange(15.0, 40.0, 0.02)
    sigma = 0.2 / 2.3548
    intensity = np.exp(-0.5 * ((two_theta - 20.0) / sigma) ** 2) + \
        0.5 * np.exp(-0.5 * ((two_theta - 30.0) / sigma) ** 2)
    result = identify_phases(two_theta, intensity, prov, elements=["Fe", "O"])
    assert result.matches[0].reference.phase_id == "mp-1"


# --- 実 pymatgen XRD (extra 導入環境のみ) ----------------------------------


@pytest.mark.mp
def test_simulate_reference_peaks_deterministic_nacl():
    from pymatgen.core import Lattice, Structure

    from tsumugin.mp.xrd import simulate_reference_peaks

    # 岩塩 NaCl (Fm-3m, a=5.64) の最小構造で XRD ピークを生成
    lattice = Lattice.cubic(5.64)
    structure = Structure(
        lattice,
        ["Na", "Cl"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )
    peaks_1 = simulate_reference_peaks(structure, two_theta_range=(20.0, 80.0))
    peaks_2 = simulate_reference_peaks(structure, two_theta_range=(20.0, 80.0))

    assert peaks_1 == peaks_2  # 決定論 (NFR-102)
    assert len(peaks_1) > 0
    assert all(isinstance(p, Peak) for p in peaks_1)
    # NaCl (111) 反射は 2θ ≈ 27.3° (Cu Kα) 付近
    assert any(26.0 < p.position < 29.0 for p in peaks_1)
    # Issue #20 hybrid: 各ピークに hkl が付く (異方整合の入力)
    assert all(p.hkl is not None and len(p.hkl) == 3 for p in peaks_1)


@pytest.mark.mp
def test_structure_cell_and_system_nacl():
    from pymatgen.core import Lattice, Structure

    from tsumugin.mp.xrd import structure_cell_and_system

    structure = Structure(Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    cell, system = structure_cell_and_system(structure)
    assert system == "cubic"
    assert abs(cell[0] - 5.64) < 1e-6 and abs(cell[3] - 90.0) < 1e-6


@pytest.mark.mp
def test_group_equivalent_dedups_identical_structures():
    from pymatgen.core import Lattice, Structure

    from tsumugin.mp.xrd import group_equivalent

    nacl_a = Structure(Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    nacl_b = Structure(Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    other = Structure(Lattice.cubic(4.0), ["Fe"], [[0, 0, 0]])

    groups = group_equivalent([nacl_a, nacl_b, other])
    # index 0,1 (等価 NaCl) が同一グループ、2 (Fe) は単独。代表 (最小 index) 昇順。
    assert (0, 1) in groups
    assert (2,) in groups
    assert len(groups) == 2


@pytest.mark.mp
def test_group_equivalent_empty_is_empty():
    from tsumugin.mp.xrd import group_equivalent

    assert group_equivalent([]) == ()
