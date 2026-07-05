"""M9 insitu.phaseid の純テスト (stub provider + stub materializer, MP/pymatgen 非依存)。

相同定→PhaseSpec 物質化ブリッジの論理 (同定・既知相除外・物質化・PhaseSpec 生成・失敗飛ばし)
を GSAS/MP なしで検証する。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from tsumugin.insitu.phaseid import IdentifiedPhase, identify_new_phases
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

    def materialize(self, phase_id: str, elements: Sequence[str], out_path: str) -> str:
        self.calls.append(phase_id)
        if phase_id in self.fail_ids:
            raise ValueError(f"no structure for {phase_id}")
        Path(out_path).write_text(f"# dummy CIF for {phase_id}\n", encoding="utf-8")
        return out_path


def _ref(phase_id, formula, peaks, elements, ehull=0.0):
    return ReferencePhase(
        phase_id=phase_id, formula=formula,
        element_system=tuple(sorted(elements)),
        peaks=tuple(Peak(position=p, height=h) for p, h in peaks),
        energy_above_hull=ehull,
    )


def _pattern(centers, heights=None, fwhm=0.2):
    tt = np.arange(15.0, 60.0, 0.02)
    inten = np.zeros_like(tt)
    hs = heights or [1.0] * len(centers)
    sigma = fwhm / 2.3548
    for c, h in zip(centers, hs):
        inten += h * np.exp(-0.5 * ((tt - c) / sigma) ** 2)
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
    )
    ids = [p.phase_id for p in out]
    assert "mp-alpha" not in ids
    assert "mp-delta" in ids


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
    # mp-a (最良) は物質化失敗 → mp-b を採る
    tt, inten = _pattern([20.0, 30.0, 40.0])
    prov = FakeProvider([
        _ref("mp-a", "AAA", [(20.0, 1.0), (30.0, 1.0), (40.0, 1.0)], ["Ca", "Te", "O"]),
        _ref("mp-b", "BBB", [(20.0, 1.0), (30.0, 1.0)], ["Ca", "Te", "O"]),
    ])
    mat = FakeMaterializer(fail_ids=["mp-a"])
    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path / "n.cif"), subtract_bg=False, refine_lattice=False, top_k=1,
    )
    assert len(out) == 1
    assert out[0].phase_id == "mp-b"
    assert mat.calls == ["mp-a", "mp-b"]  # a を試し失敗、b で成功


def test_empty_when_no_candidates(tmp_path):
    tt, inten = _pattern([20.0])
    prov = FakeProvider([])
    mat = FakeMaterializer()
    out = identify_new_phases(
        tt, inten, elements=["Ca", "Te", "O"], provider=prov, materializer=mat,
        workdir=str(tmp_path / "n.cif"), subtract_bg=False, refine_lattice=False,
    )
    assert out == ()
