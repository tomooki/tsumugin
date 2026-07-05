"""M6 TASK-0106/0107 CIF 供給元の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/reference/cif.py`` + ``src/tsumugin/reference/providers.py`` (未実装)。
- UserCIFProvider: ユーザー提供 CIF → ReferencePhase (完全実装, parse を DI してテスト)。
- CODProvider / ICSDProvider: ネットワーク取得は導線 (downloader シーム) のみ確保。
- cif_to_reference_phases: pymatgen CifParser 実処理は ``@pytest.mark.mp`` で検証。
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

# --- テスト用フェイク parse -------------------------------------------------

_NACL_CIF = """data_NaCl
_cell_length_a 5.64
_cell_length_b 5.64
_cell_length_c 5.64
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'F m -3 m'
_symmetry_Int_Tables_number 225
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Na Na 0.0 0.0 0.0
Cl Cl 0.5 0.5 0.5
"""


def _fake_parse(cif: str, *, source_id: str | None = None, **kwargs) -> tuple[ReferencePhase, ...]:
    """CIF テキストの内容に依らず決定論的な 1 相を返すフェイク (pymatgen 非依存)。"""
    return (
        ReferencePhase(
            phase_id=source_id or "cif-0",
            formula="NaCl",
            element_system=("Cl", "Na"),
            peaks=(Peak(27.3, 100.0), Peak(31.7, 55.0)),
            spacegroup="Fm-3m",
            energy_above_hull=None,
        ),
    )


# --- UserCIFProvider (完全実装) --------------------------------------------


def test_user_cif_provider_conforms_to_protocol():
    from tsumugin.reference.providers import UserCIFProvider

    prov = UserCIFProvider([_NACL_CIF], parse=_fake_parse)
    assert isinstance(prov, ReferenceProvider)


def test_user_cif_provider_fetch_parses_sources():
    from tsumugin.reference.providers import UserCIFProvider

    prov = UserCIFProvider([_NACL_CIF], parse=_fake_parse)
    refs = prov.fetch(["Na", "Cl"])
    assert len(refs) == 1
    assert refs[0].formula == "NaCl"
    assert refs[0].energy_above_hull is None  # ユーザー CIF は未登録 → hull で保持


def test_user_cif_provider_multiple_sources():
    from tsumugin.reference.providers import UserCIFProvider

    counter = {"n": 0}

    def _parse(cif, *, source_id=None, **kw):
        counter["n"] += 1
        return (ReferencePhase(phase_id=f"s{counter['n']}", formula="X",
                               element_system=("Fe",), peaks=(Peak(20.0, 1.0),)),)

    prov = UserCIFProvider([_NACL_CIF, _NACL_CIF], parse=_parse)
    refs = prov.fetch(["Fe"])
    assert len(refs) == 2


def test_user_cif_provider_caches_parse():
    from tsumugin.reference.providers import UserCIFProvider

    calls = {"n": 0}

    def _parse(cif, *, source_id=None, **kw):
        calls["n"] += 1
        return _fake_parse(cif, source_id=source_id)

    prov = UserCIFProvider([_NACL_CIF], parse=_parse)
    prov.fetch(["Na", "Cl"])
    prov.fetch(["Na", "Cl"])
    assert calls["n"] == 1  # 2 回目はキャッシュを返し再パースしない


def test_user_cif_provider_from_files(tmp_path):
    from tsumugin.reference.providers import UserCIFProvider

    path = tmp_path / "nacl.cif"
    path.write_text(_NACL_CIF, encoding="utf-8")
    prov = UserCIFProvider.from_files([path], parse=_fake_parse)
    refs = prov.fetch(["Na", "Cl"])
    assert len(refs) == 1


# --- CODProvider / ICSDProvider (導線のみ) ---------------------------------


def test_cod_provider_conforms_to_protocol():
    from tsumugin.reference.providers import CODProvider

    assert isinstance(CODProvider(), ReferenceProvider)


def test_cod_provider_without_downloader_raises_not_implemented():
    from tsumugin.reference.providers import CODProvider

    prov = CODProvider()  # ネットワーク取得は未配線 (導線のみ)
    with pytest.raises(NotImplementedError):
        prov.fetch(["Fe", "O"])


def test_cod_provider_with_injected_downloader_works():
    # 導線 = downloader シーム。注入すれば共有 CIF パースで ReferencePhase を返す
    from tsumugin.reference.providers import CODProvider

    def _downloader(elements: Sequence[str]) -> Sequence[str]:
        return [_NACL_CIF]

    prov = CODProvider(downloader=_downloader, parse=_fake_parse)
    refs = prov.fetch(["Na", "Cl"])
    assert len(refs) == 1
    assert refs[0].formula == "NaCl"


def test_icsd_provider_conforms_and_requires_wiring():
    from tsumugin.reference.providers import ICSDProvider

    prov = ICSDProvider()
    assert isinstance(prov, ReferenceProvider)
    with pytest.raises(NotImplementedError):
        prov.fetch(["Fe", "O"])


def test_icsd_provider_with_injected_downloader_works():
    from tsumugin.reference.providers import ICSDProvider

    prov = ICSDProvider(downloader=lambda els: [_NACL_CIF], parse=_fake_parse)
    refs = prov.fetch(["Na", "Cl"])
    assert len(refs) == 1


# --- cif_to_reference_phases 縮退 (pymatgen 非導入時) -----------------------


@pytest.mark.skipif(_HAS_PYMATGEN, reason="pymatgen 導入済みでは縮退経路に入らない")
def test_cif_to_reference_phases_raises_without_pymatgen():
    from tsumugin.reference.cif import cif_to_reference_phases

    with pytest.raises(MPUnavailableError):
        cif_to_reference_phases(_NACL_CIF)


# --- cif_to_reference_phases 実処理 (pymatgen 導入環境のみ) -----------------


@pytest.mark.mp
def test_cif_to_reference_phases_parses_nacl():
    from tsumugin.reference.cif import cif_to_reference_phases

    refs = cif_to_reference_phases(_NACL_CIF, source_id="nacl", two_theta_range=(20.0, 80.0))
    assert len(refs) == 1
    ref = refs[0]
    assert isinstance(ref, ReferencePhase)
    assert set(ref.element_system) == {"Na", "Cl"}
    assert ref.energy_above_hull is None  # ユーザー CIF は未登録
    assert len(ref.peaks) > 0
    # NaCl (111) 反射 2θ ≈ 27.3° (Cu Kα)
    assert any(26.0 < p.position < 29.0 for p in ref.peaks)


@pytest.mark.mp
def test_user_cif_provider_end_to_end_identify():
    import numpy as np

    from tsumugin.reference import identify_phases
    from tsumugin.reference.providers import UserCIFProvider

    prov = UserCIFProvider([_NACL_CIF])  # 実 pymatgen パース
    refs = prov.fetch(["Na", "Cl"])
    peaks = refs[0].peaks
    two_theta = np.arange(20.0, 80.0, 0.02)
    sigma = 0.15 / 2.3548
    inten = np.zeros_like(two_theta)
    for p in peaks:
        inten += p.height * np.exp(-0.5 * ((two_theta - p.position) / sigma) ** 2)
    result = identify_phases(two_theta, inten, prov, elements=["Na", "Cl"])
    assert result.matches[0].reference.formula in ("NaCl", "ClNa")
