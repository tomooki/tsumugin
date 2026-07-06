"""M6 TASK-0108 パターンキャッシュ永続化 (FR-105) の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/reference/serialization.py`` + ``src/tsumugin/reference/cache.py`` (未実装)。
- ReferencePhase の JSON ラウンドトリップ。
- CachedReferenceProvider: 供給元の fetch 結果をディスクへ永続化し再取得時は再計算/再取得しない。
コアは numpy 非依存。決定論的なキーで X線/中性子 (namespace) を分離する。
"""

from __future__ import annotations

from collections.abc import Sequence

from tsumugin.reference.model import ReferencePhase
from tsumugin.reference.provider import ReferenceProvider
from tsumugin.search.peaks import Peak


def _ref(phase_id="mp-1"):
    return ReferencePhase(
        phase_id=phase_id,
        formula="LiFePO4",
        element_system=("Fe", "Li", "O", "P"),
        peaks=(Peak(20.0, 100.0), Peak(30.5, 55.2)),
        spacegroup="Pnma",
        energy_above_hull=0.012,
    )


class CountingProvider:
    """fetch 呼び出し回数を数える ``ReferenceProvider`` テストダブル。"""

    def __init__(self, phases: Sequence[ReferencePhase]) -> None:
        self._phases = tuple(phases)
        self.calls = 0

    def fetch(self, elements: Sequence[str]) -> Sequence[ReferencePhase]:
        self.calls += 1
        return self._phases


# --- シリアライズ ラウンドトリップ -----------------------------------------


def test_reference_phase_roundtrip():
    from tsumugin.reference.serialization import (
        reference_phase_from_dict,
        reference_phase_to_dict,
    )

    ref = _ref()
    restored = reference_phase_from_dict(reference_phase_to_dict(ref))
    assert restored == ref


def test_reference_phase_roundtrip_none_energy_and_spacegroup():
    from tsumugin.reference.serialization import (
        reference_phase_from_dict,
        reference_phase_to_dict,
    )

    ref = ReferencePhase(
        phase_id="user-cif",
        formula="Fe2O3",
        element_system=("Fe", "O"),
        peaks=(),
        spacegroup=None,
        energy_above_hull=None,
    )
    assert reference_phase_from_dict(reference_phase_to_dict(ref)) == ref


def test_reference_phase_roundtrip_with_hkl_and_cell():
    """Issue #20 hybrid: Peak.hkl + ReferencePhase.cell/crystal_system がラウンドトリップする。"""
    import json

    from tsumugin.reference.serialization import (
        reference_phase_from_dict,
        reference_phase_to_dict,
    )

    ref = ReferencePhase(
        phase_id="mp-delta",
        formula="CaTeO3",
        element_system=("Ca", "O", "Te"),
        peaks=(Peak(20.0, 100.0, hkl=(1, 0, 1)), Peak(30.5, 55.2, hkl=(0, 2, 0))),
        spacegroup="Pca2_1",
        energy_above_hull=0.0,
        cell=(8.17, 6.53, 13.32, 90.0, 90.0, 90.0),
        crystal_system="orthorhombic",
    )
    d = reference_phase_to_dict(ref)
    json.dumps(d, allow_nan=False)  # json 安全
    restored = reference_phase_from_dict(d)
    assert restored == ref
    assert restored.peaks[0].hkl == (1, 0, 1)
    assert restored.cell == (8.17, 6.53, 13.32, 90.0, 90.0, 90.0)
    assert restored.crystal_system == "orthorhombic"


def test_reference_phase_roundtrip_mixed_hkl_presence():
    """一部ピークだけ hkl を持つ (観測混在) 場合も欠落を保持してラウンドトリップ。"""
    from tsumugin.reference.serialization import (
        reference_phase_from_dict,
        reference_phase_to_dict,
    )

    ref = ReferencePhase(
        phase_id="x", formula="X", element_system=("X",),
        peaks=(Peak(10.0, 5.0, hkl=(1, 0, 0)), Peak(20.0, 3.0, hkl=None)),
    )
    restored = reference_phase_from_dict(reference_phase_to_dict(ref))
    assert restored == ref
    assert restored.peaks[1].hkl is None


def test_to_dict_is_json_serializable():
    import json

    from tsumugin.reference.serialization import reference_phase_to_dict

    text = json.dumps(reference_phase_to_dict(_ref()), allow_nan=False)
    assert "mp-1" in text


# --- CachedReferenceProvider -----------------------------------------------


def test_cached_provider_conforms_to_protocol(tmp_path):
    from tsumugin.reference.cache import CachedReferenceProvider

    prov = CachedReferenceProvider(CountingProvider([_ref()]), tmp_path)
    assert isinstance(prov, ReferenceProvider)


def test_cache_miss_then_hit_avoids_second_fetch(tmp_path):
    from tsumugin.reference.cache import CachedReferenceProvider

    inner = CountingProvider([_ref()])
    prov = CachedReferenceProvider(inner, tmp_path)
    r1 = prov.fetch(["Li", "Fe", "P", "O"])
    r2 = prov.fetch(["Li", "Fe", "P", "O"])
    assert inner.calls == 1  # 2 回目はキャッシュ
    assert r1 == r2


def test_cache_persists_across_instances(tmp_path):
    from tsumugin.reference.cache import CachedReferenceProvider

    inner1 = CountingProvider([_ref()])
    CachedReferenceProvider(inner1, tmp_path).fetch(["Fe", "O"])
    assert inner1.calls == 1
    # 別インスタンス (プロセス再起動相当) がディスクキャッシュを読む
    inner2 = CountingProvider([_ref("mp-should-not-appear")])
    refs = CachedReferenceProvider(inner2, tmp_path).fetch(["Fe", "O"])
    assert inner2.calls == 0  # ディスクヒットで inner を呼ばない
    assert refs[0].phase_id == "mp-1"  # 最初にキャッシュした内容


def test_cache_key_separates_elements(tmp_path):
    from tsumugin.reference.cache import CachedReferenceProvider

    inner = CountingProvider([_ref()])
    prov = CachedReferenceProvider(inner, tmp_path)
    prov.fetch(["Fe", "O"])
    prov.fetch(["Ti", "O"])  # 別元素系 → 別キャッシュ → inner 再取得
    assert inner.calls == 2


def test_cache_key_normalizes_element_order(tmp_path):
    from tsumugin.reference.cache import CachedReferenceProvider

    inner = CountingProvider([_ref()])
    prov = CachedReferenceProvider(inner, tmp_path)
    prov.fetch(["Fe", "O"])
    prov.fetch(["O", "Fe"])  # 順序違いは同一キー → キャッシュヒット
    assert inner.calls == 1


def test_namespace_separates_radiation(tmp_path):
    # FR-105: X線/中性子は散乱長が違うため namespace で別キャッシュにする
    from tsumugin.reference.cache import CachedReferenceProvider

    inner_xray = CountingProvider([_ref("xray-phase")])
    inner_neutron = CountingProvider([_ref("neutron-phase")])
    CachedReferenceProvider(inner_xray, tmp_path, namespace="xray").fetch(["Fe", "O"])
    refs = CachedReferenceProvider(inner_neutron, tmp_path, namespace="neutron").fetch(["Fe", "O"])
    assert inner_neutron.calls == 1  # namespace 違いはヒットしない
    assert refs[0].phase_id == "neutron-phase"


def test_cache_writes_file(tmp_path):
    from tsumugin.reference.cache import CachedReferenceProvider

    prov = CachedReferenceProvider(CountingProvider([_ref()]), tmp_path)
    prov.fetch(["Fe", "O"])
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
