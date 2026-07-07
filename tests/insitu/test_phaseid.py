"""M9 insitu.phaseid の純テスト (stub provider + stub materializer, MP/pymatgen 非依存)。

相同定→PhaseSpec 物質化ブリッジの論理 (同定・既知相除外・物質化・PhaseSpec 生成・失敗飛ばし)
を GSAS/MP なしで検証する。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from tsumugin.insitu.phaseid import IdentifiedPhase, identify_new_phases, structure_to_cif
from tsumugin.reference.model import ReferencePhase
from tsumugin.search.peaks import Peak


class FakeProvider:
    def __init__(self, phases: Sequence[ReferencePhase]) -> None:
        self._phases = tuple(phases)

    def fetch(self, elements: Sequence[str]) -> Sequence[ReferencePhase]:
        return self._phases


class FakeMaterializer:
    """phase_id ごとにダミー CIF テキストを書き出すスタブ。呼び出しを記録。"""

    def __init__(self, *, fail_ids: Sequence[str] = ()) -> None:
        self.fail_ids = set(fail_ids)
        self.calls: list[str] = []
        self.strains: list[float] = []
        self.cells: list[object] = []  # materialize に渡った cell (None or 6-tuple)

    def materialize(
        self, phase_id: str, elements: Sequence[str], out_path: str,
        strain: float = 0.0, cell=None,
    ) -> str:
        self.calls.append(phase_id)
        self.strains.append(strain)
        self.cells.append(cell)
        if phase_id in self.fail_ids:
            raise ValueError(f"no structure for {phase_id}")
        Path(out_path).write_text(
            f"# dummy CIF for {phase_id} strain={strain} cell={cell}\n", encoding="utf-8"
        )
        return out_path


def _ref(phase_id, formula, peaks, elements, ehull=0.0):
    return ReferencePhase(
        phase_id=phase_id, formula=formula,
        element_system=tuple(sorted(elements)),
        peaks=tuple(Peak(position=p, height=h) for p, h in peaks),
        energy_above_hull=ehull,
    )


def _pattern(centers, heights=None, fwhm=0.2, counts=1500.0):
    """合成パターン。M11 委譲後の identify_pattern は計数統計 σ に対する残差 S/N で停止するため、
    現実的なカウント数 (`counts`) にスケールして相ピークが S/N 閾値を超えるようにする。"""
    tt = np.arange(15.0, 60.0, 0.02)
    inten = np.zeros_like(tt)
    hs = heights or [1.0] * len(centers)
    sigma = fwhm / 2.3548
    for c, h in zip(centers, hs):
        inten += counts * h * np.exp(-0.5 * ((tt - c) / sigma) ** 2)
    return tt, inten


def test_materializes_top_phase(tmp_path):
    tt, inten = _pattern([20.0, 30.0])
    prov = FakeProvider([_ref("mp-delta", "CaTeO3", [(20.0, 1.0), (30.0, 0.8)], ["Ca", "Te", "O"])])
    mat = FakeMaterializer()
    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path / "delta.cif"), subtract_bg=False, refine_lattice=False,
    )
    assert len(out) == 1
    assert isinstance(out[0], IdentifiedPhase)
    assert out[0].phase_id == "mp-delta"
    assert out[0].formula == "CaTeO3"
    assert out[0].phase_spec.format_hint == "CIF"
    assert out[0].phase_spec.structure_path.endswith(".cif")
    assert Path(out[0].phase_spec.structure_path).exists()
    assert mat.calls == ["mp-delta"]
    # refine_lattice=False なら歪みは 0 で materialize に渡る (strain 伝播経路の下限固定)。
    assert mat.strains == [0.0]


def test_nonzero_strain_propagates_to_materialize(tmp_path):
    """refine_lattice=True で候補ピークが観測から系統的にずれると refine_lattice が非零歪みを求め、
    それが materialize(strain=) へ伝播する (DFT 格子ズレ補正の経路)。

    M11 委譲後の減算整合は多ピーク (_MIN_ALIGN_MATCHES=8) で活性化するため、観測を真位置、候補相を
    一律 +1% 高角シフト (等方格子ズレ相当) にした 9 ピーク相で検証する。
    """
    true_pos = [18.0, 21.0, 24.0, 28.0, 32.0, 36.0, 41.0, 46.0, 52.0]
    heights = [1.0, 0.9, 0.8, 1.0, 0.7, 0.9, 0.6, 0.8, 0.7]
    tt, inten = _pattern(true_pos, heights=heights)  # 観測は真位置
    shifted = [(p * 1.010, h) for p, h in zip(true_pos, heights)]  # 候補は一律 +1% 高角
    prov = FakeProvider([_ref("mp-x", "CaTeO3", shifted, ["Ca", "Te", "O"])])
    mat = FakeMaterializer()
    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path / "x.cif"), subtract_bg=False, refine_lattice=True, max_strain=0.05,
    )
    assert len(out) == 1
    assert len(mat.strains) == 1
    # 非零の歪みが求まり materialize に渡ったこと (符号は align 次第、絶対値 > 0)。
    assert abs(mat.strains[0]) > 1e-4
    # IdentifiedPhase.strain と materialize に渡した値が一致すること。
    assert out[0].strain == mat.strains[0]


def test_cell_refiner_rematerializes_with_anisotropic_cell(tmp_path):
    """cell_refiner が異方セルを返すと、そのセルで CIF を再物質化し refined_cell に記録する。"""
    tt, inten = _pattern([20.0, 30.0])
    prov = FakeProvider([_ref("mp-delta", "CaTeO3", [(20.0, 1.0), (30.0, 0.8)], ["Ca", "Te", "O"])])
    mat = FakeMaterializer()
    aniso = (6.53, 8.17, 13.32, 90.0, 90.0, 90.0)

    def refiner(cif_path: str):
        assert Path(cif_path).exists()  # 等方版が先に書き出されている
        return aniso

    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path), subtract_bg=False, refine_lattice=False, cell_refiner=refiner,
    )
    assert len(out) == 1
    assert out[0].refined_cell == aniso
    # materialize が 2 回 (等方 strain → 異方 cell) 呼ばれ、2 回目に cell が渡る。
    assert mat.calls == ["mp-delta", "mp-delta"]
    assert mat.cells[0] is None
    assert mat.cells[1] == aniso


def test_cell_refiner_none_keeps_isotropic(tmp_path):
    """cell_refiner が None を返すと再物質化せず等方版を維持する (refined_cell=None)。"""
    tt, inten = _pattern([20.0, 30.0])
    prov = FakeProvider([_ref("mp-delta", "CaTeO3", [(20.0, 1.0), (30.0, 0.8)], ["Ca", "Te", "O"])])
    mat = FakeMaterializer()
    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path), subtract_bg=False, refine_lattice=False,
        cell_refiner=lambda _p: None,
    )
    assert out[0].refined_cell is None
    assert mat.calls == ["mp-delta"]  # 再物質化なし


def test_cell_refiner_exception_is_safe(tmp_path):
    """cell_refiner が例外を投げても等方版で継続する (提案≠適用の安全側)。"""
    tt, inten = _pattern([20.0, 30.0])
    prov = FakeProvider([_ref("mp-delta", "CaTeO3", [(20.0, 1.0), (30.0, 0.8)], ["Ca", "Te", "O"])])
    mat = FakeMaterializer()

    def boom(_p: str):
        raise RuntimeError("cell refine failed")

    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path), subtract_bg=False, refine_lattice=False, cell_refiner=boom,
    )
    assert len(out) == 1
    assert out[0].refined_cell is None
    assert mat.calls == ["mp-delta"]


def test_excludes_known_phase_by_formula(tmp_path):
    # alpha (既知) と delta (新相) が両方候補にある。alpha を除外して delta を選ぶ。
    tt, inten = _pattern([20.0, 30.0, 25.0])
    prov = FakeProvider([
        _ref("mp-alpha", "CaH2O4Te", [(20.0, 1.0), (30.0, 0.9)], ["Ca", "H", "Te", "O"]),
        _ref("mp-delta", "CaTeO3", [(20.0, 1.0), (25.0, 0.8)], ["Ca", "Te", "O"]),
    ])
    mat = FakeMaterializer()
    out = identify_new_phases(
        tt, inten, elements=["Ca", "H", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path / "new.cif"), exclude_formulas=["CaH2O4Te"],
        subtract_bg=False, refine_lattice=False, top_k=2,
        require_full_element_system=False,  # 本テストは formula 除外の検証 (化学ガードは別テスト)
    )
    ids = [p.phase_id for p in out]
    assert "mp-alpha" not in ids
    assert "mp-delta" in ids


def test_chemistry_guard_excludes_element_subset_phases(tmp_path):
    """③ 化学ガード: require_full_element_system=True は全元素系を含まない部分集合相を除外する。

    観測に元素 Ca (単純相) が偶然マッチしても、Ca-Te-O 全系を持つ CaTeO3 のみ残す (junk 除去)。
    """
    tt, inten = _pattern([20.0, 30.0, 25.0])
    prov = FakeProvider([
        _ref("mp-ca", "Ca", [(20.0, 1.0)], ["Ca"]),            # 元素 Ca (部分集合 junk)
        _ref("mp-o2", "O2", [(30.0, 1.0)], ["O"]),             # O2 (部分集合 junk)
        _ref("mp-delta", "CaTeO3", [(20.0, 1.0), (25.0, 0.8), (30.0, 0.6)], ["Ca", "Te", "O"]),
    ])
    mat = FakeMaterializer()
    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path), subtract_bg=False, refine_lattice=False, top_k=5,
        require_full_element_system=True,
    )
    ids = [p.phase_id for p in out]
    assert ids == ["mp-delta"]  # junk (Ca, O2) は化学ガードで除外、delta のみ


def test_chemistry_guard_off_keeps_subsets(tmp_path):
    """require_full_element_system=False なら従来通り部分集合相も候補に残る (後方互換)。"""
    tt, inten = _pattern([20.0, 30.0])
    prov = FakeProvider([_ref("mp-ca", "Ca", [(20.0, 1.0), (30.0, 0.9)], ["Ca"])])
    mat = FakeMaterializer()
    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path), subtract_bg=False, refine_lattice=False,
        require_full_element_system=False,
    )
    assert [p.phase_id for p in out] == ["mp-ca"]  # ガード off で Ca が残る


def test_excludes_by_phase_id(tmp_path):
    tt, inten = _pattern([20.0, 30.0])
    prov = FakeProvider([_ref("mp-alpha", "CaH2O4Te", [(20.0, 1.0), (30.0, 0.9)], ["Ca", "H", "Te", "O"])])
    mat = FakeMaterializer()
    out = identify_new_phases(
        tt, inten, elements=["Ca", "H", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path / "n.cif"), exclude_phase_ids=["mp-alpha"],
        subtract_bg=False, refine_lattice=False,
    )
    assert out == ()  # 唯一の候補を除外 → 空


def test_skips_materialization_failure_takes_next(tmp_path):
    # mp-a (最強・先に受理) は物質化失敗 → 次の受理相 mp-b を採る。
    # M11 委譲後は残差支持で受理された相のみが物質化対象なので、両相が実際にパターンに存在する必要が
    # ある (旧: 素の identify_phases ランキング上位から順に。新: 受理集合から順に)。mp-a/mp-b は
    # 別ピーク群を持つ独立の相として両方存在させる。
    tt, inten = _pattern(
        [20.0, 30.0, 40.0, 25.0, 35.0, 45.0], heights=[1.0, 1.0, 1.0, 0.7, 0.7, 0.7]
    )
    prov = FakeProvider([
        _ref("mp-a", "AAA", [(20.0, 1.0), (30.0, 1.0), (40.0, 1.0)], ["Ca", "Te", "O"]),
        _ref("mp-b", "BBB", [(25.0, 1.0), (35.0, 1.0), (45.0, 1.0)], ["Ca", "Te", "O"]),
    ])
    mat = FakeMaterializer(fail_ids=["mp-a"])
    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path / "n.cif"), subtract_bg=False, refine_lattice=False, top_k=1,
    )
    assert len(out) == 1
    assert out[0].phase_id == "mp-b"
    assert mat.calls == ["mp-a", "mp-b"]  # a を試し失敗、b で成功


def test_known_phases_warmstart_materializes_only_new(tmp_path):
    """known_phases=[alpha] 起点なら alpha を先に減算し、新相 delta のみ物質化する (operando 一本化)。

    alpha は受理集合には残るが known_phases なので物質化から除外され、delta だけが CIF 化される。
    """
    # alpha (既知, 3 強ピーク) + delta (新相, 別ピーク群) が混在するフレーム。
    tt, inten = _pattern(
        [18.0, 28.0, 38.0, 23.0, 33.0, 43.0], heights=[1.0, 1.0, 1.0, 0.8, 0.8, 0.8]
    )
    alpha = _ref("mp-alpha", "CaH2O4Te", [(18.0, 1.0), (28.0, 1.0), (38.0, 1.0)],
                 ["Ca", "H", "Te", "O"])
    delta = _ref("mp-delta", "CaTeO3", [(23.0, 1.0), (33.0, 1.0), (43.0, 1.0)], ["Ca", "Te", "O"])
    prov = FakeProvider([alpha, delta])
    mat = FakeMaterializer()
    out = identify_new_phases(
        tt, inten, elements=["Ca", "H", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path), subtract_bg=False, refine_lattice=False, top_k=5,
        require_full_element_system=False, known_phases=[alpha],
    )
    ids = [p.phase_id for p in out]
    assert ids == ["mp-delta"]  # alpha は known_phases として物質化除外、delta のみ新相
    assert mat.calls == ["mp-delta"]  # 既知 alpha は再物質化されない


def test_empty_when_no_candidates(tmp_path):
    tt, inten = _pattern([20.0])
    prov = FakeProvider([])
    mat = FakeMaterializer()
    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path / "n.cif"), subtract_bg=False, refine_lattice=False,
    )
    assert out == ()


@pytest.mark.mp
def test_structure_to_cif_cell_override_replaces_lattice(tmp_path):
    """structure_to_cif(cell=) は格子を絶対値に置換し (分率座標保持)、strain より優先する。"""
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter  # noqa: F401 (import 経路の健全性)

    orig = Structure(
        Lattice.from_parameters(5.0, 6.0, 7.0, 90.0, 90.0, 90.0),
        ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    target = (6.53, 8.17, 13.32, 90.0, 90.0, 90.0)
    out = structure_to_cif(orig, str(tmp_path / "c.cif"), strain=0.02, cell=target)
    written = Structure.from_file(out)
    lat = written.lattice
    assert abs(lat.a - 6.53) < 1e-3 and abs(lat.b - 8.17) < 1e-3 and abs(lat.c - 13.32) < 1e-3
    # 分率座標は保持 (Cl は 0.5,0.5,0.5 のまま)
    assert np.allclose(sorted(written.frac_coords[:, 0]), [0.0, 0.5], atol=1e-6)
    # 元構造は不変
    assert abs(orig.lattice.a - 5.0) < 1e-9
