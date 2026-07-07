"""M11 identify_pattern の実データ検証 (T7)。

fast tier (ピーク空間) の到達スコープを固定する:
- CandAt (実測 calcite+aragonite, オフライン MP 169候補キャッシュ, cell なし): **calcite(R-3c) +
  aragonite(Pnma) を両回復し graphite(C) を棄却**する。減算前の候補格子整合 (E1) が無いと aragonite
  単独しか取れない (DFT 格子ズレの残差汚染)。※ Ca 金属等の元素部分集合偽陽性は fast tier では棄却
  できず、深段 refiner / 層3 化学ガードの担当 (設計) — 本テストは「正解相の回復 + graphite 棄却」を検証。
- PbSO4 (実測 CuKα, 単相): k=1 で自然停止 (偽 2 相目なし)。

CandAt キャッシュ経路は numpy のみ (pymatgen 不要)。PbSO4 は CIF パースに pymatgen を要する。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from tsumugin.reference import IdentifyConfig, identify_pattern, reference_phase_from_dict
from tsumugin.reference.io import load_xy

_DATA = pathlib.Path(__file__).resolve().parents[2] / "docs" / "benchmark" / "testdata"
_JANA = _DATA / "jana"
_CANDAT = _JANA / "CandAt.xy"
_MP_CACHE = _JANA / "mpcache" / "CuKa1_CandAt__C-Ca-O.json"
_XRA = _DATA / "PBSO4.XRA"
_PBSO4_CIF = _DATA / "PbSO4-Wyckoff.cif"

_HAS_CANDAT = _CANDAT.exists() and _MP_CACHE.exists()
_HAS_PBSO4 = _XRA.exists() and _PBSO4_CIF.exists()


class _CachedProvider:
    def __init__(self, refs):
        self._refs = tuple(refs)

    def fetch(self, elements):
        return self._refs


@pytest.mark.skipif(not _HAS_CANDAT, reason="CandAt / MP キャッシュ未配置 (docs/benchmark)")
def test_candat_recovers_calcite_and_aragonite_and_rejects_graphite():
    """CandAt × MP 169候補 (キャッシュ) で calcite(R-3c)+aragonite(Pnma) 両回復・graphite 棄却。"""
    tt, inten = load_xy(str(_CANDAT))
    refs = tuple(reference_phase_from_dict(d)
                 for d in json.loads(_MP_CACHE.read_text(encoding="utf-8"))["phases"])
    lut = {r.phase_id: r for r in refs}
    res = identify_pattern(tt, inten, _CachedProvider(refs), elements=["Ca", "C", "O"],
                           cfg=IdentifyConfig(max_phases=4, try_k=5))
    accepted = [lut[a.phase_id] for a in res.accepted if a.phase_id in lut]
    spacegroups = {r.spacegroup for r in accepted}
    formulas = {r.formula for r in accepted}
    # 正解の 2 多形を両方回復
    assert "R-3c" in spacegroups, f"calcite (R-3c) 未回復: {spacegroups}"
    assert "Pnma" in spacegroups, f"aragonite (Pnma) 未回復: {spacegroups}"
    assert sum(1 for r in accepted if r.formula == "CaCO3") >= 2
    # graphite (単体 C) は棄却
    assert "C" not in formulas, f"graphite 混入: {formulas}"
    # 決定論
    res2 = identify_pattern(tt, inten, _CachedProvider(refs), elements=["Ca", "C", "O"],
                            cfg=IdentifyConfig(max_phases=4, try_k=5))
    assert res.phase_ids == res2.phase_ids


@pytest.mark.mp
@pytest.mark.skipif(not _HAS_PBSO4, reason="PbSO4 実測データ未配置 (docs/benchmark)")
def test_pbso4_single_phase_stops_at_k1():
    """PbSO4 単相 (実測 CuKα) は k=1 で自然停止 (偽 2 相目を出さない)。"""
    pytest.importorskip("pymatgen")
    from tsumugin.reference import UserCIFProvider
    from tsumugin.reference.io import load_gsas_powder

    tt, inten = load_gsas_powder(_XRA)
    provider = UserCIFProvider([_PBSO4_CIF.read_text(encoding="utf-8")],
                               wavelength_angstrom=1.5405, two_theta_range=(10.0, 120.0))
    res = identify_pattern(tt, inten, provider, elements=["Pb", "S", "O"],
                           cfg=IdentifyConfig(max_phases=3))
    assert len(res.accepted) == 1, f"単相のはずが {res.phase_ids}"
    assert len(res.iterations) == 1
