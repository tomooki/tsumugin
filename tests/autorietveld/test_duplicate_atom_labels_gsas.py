"""重複した原子ラベルの拒否 — **実 GSAS-II** で (@pytest.mark.gsas, PbSO4 実データ)。

速いティア (`test_duplicate_atom_labels.py`) は偽の GSAS で配線を測る。ここでは:

- GSAS の CIF インポータが重複ラベルを実際に別原子として読み、``set_refinements`` が
  **先頭の原子にしかフラグを付けない**こと (= 拒否する理由そのもの。GSAS-II の更新でこれが
  変わったら落ちるカナリア — そのときは拒否を添字の引き当てへ緩めてよいかを再検討する)
- engine が精密化の前に止めること、② が JSON 引数だけで error dict を返すこと
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.errors import DuplicateAtomLabelError

_DATA = Path("docs/benchmark/testdata")

pytestmark = [
    pytest.mark.gsas,
    pytest.mark.skipif(
        not ((_DATA / "PBSO4.XRA").exists() and (_DATA / "PbSO4-Wyckoff.cif").exists()),
        reason="PbSO4 データ未取得",
    ),
]


def _duplicated_cif(tmp_path: Path) -> Path:
    """PbSO4 の O2 (別サイト) を ``O1`` に改名した CIF。構造は原本と同一。"""
    src = (_DATA / "PbSO4-Wyckoff.cif").read_text()
    target = "\nO2     O    0.18100"
    assert src.count(target) == 1, "原本 CIF の書式が変わった (改名が空振りする)"
    path = tmp_path / "PbSO4-dupO1.cif"
    path.write_text(src.replace(target, "\nO1     O    0.18100"))
    return path


def _hist() -> HistogramSpec:
    return HistogramSpec(
        data_path=str(_DATA / "PBSO4.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )


def test_canary_gsas_flags_only_the_first_atom_sharing_a_label(tmp_path):
    """★拒否の理由: GSAS は重複ラベルを 2 原子として読むが、``{"O1": "XU"}`` は先頭にしか
    付かない (2 番目 = 元の O2 サイトは空のまま)。"""
    from GSASII import GSASIIscriptable as G2sc

    gpx = G2sc.G2Project(newgpx=str(tmp_path / "canary.gpx"))
    ph = gpx.add_phase(str(_duplicated_cif(tmp_path)), phasename="dup")
    ct = ph.data["General"]["AtomPtrs"][1]
    labels = [row[ct - 1] for row in ph.data["Atoms"]]
    assert labels == ["Pb", "S", "O1", "O1", "O3"], "GSAS が重複ラベルを別原子として読まない"
    ph.set_refinements({"Atoms": {"O1": "XU"}})
    flags = [row[ct + 1] for row in ph.data["Atoms"]]
    assert flags[2] == "XU"
    assert flags[3] == "", (
        "GSAS が 2 番目の O1 にもフラグを付けた — 先頭一致の挙動が変わった。重複ラベルの拒否"
        "(engine._refuse_duplicate_atom_labels) を緩めてよいか再検討する"
    )


def test_real_gsas_refuses_a_repeated_label_before_refinement(tmp_path):
    """以前は既定レシピが完走し (validity 合格・Rwp 11.0191 vs 正しいラベル 11.0181)、
    2 番目の O1 は座標・Uiso が CIF の出発値のまま、報告の ``atom_uiso["O1"]`` は 0.01 だった。"""
    phase = PhaseSpec(structure_path=str(_duplicated_cif(tmp_path)), phase_name="PbSO4")
    with pytest.raises(DuplicateAtomLabelError) as excinfo:
        run_auto_rietveld([_hist()], [phase], save_gpx=False)
    message = str(excinfo.value)
    assert "'PbSO4'" in message
    assert "{'O1': [3, 4]}" in message, message


def test_layer_two_degrades_the_refusal_on_the_default_backend(tmp_path):
    """③ が実際に通る経路 (**JSON 引数だけ**・既定バックエンド) で error dict になる。"""
    from tsumugin.mcp import rietveld_tools

    hist = _hist().to_dict()
    phase = PhaseSpec(
        structure_path=str(_duplicated_cif(tmp_path)), phase_name="PbSO4"
    ).to_dict()
    out = rietveld_tools.auto_rietveld([hist], [phase], save_gpx=False)
    assert out.get("error_type") == "DuplicateAtomLabelError", out
    assert "O1" in out["error"]
