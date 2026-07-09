"""生の標準試料データからの装置分解能抽出パイプライン (再現可能な別関数) のテスト。

純ヘルパ (xye 変換・instprm 生成・標準 CIF) + runner 注入のパイプラインを GSAS 非依存で検証。
実 CeO2 抽出は test_resolution_gsas.py (gated)。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    StageResult,
    ValidityReport,
)
from tsumugin.autorietveld.resolution import (
    STANDARD_REFERENCE_CIF,
    extract_instrument_profile_from_standard,
    pxc_instprm_text,
    standard_reference_cif,
    to_xye_text,
)


# --- to_xye_text (2列→ esd 付き xye, Poisson) ---

def test_to_xye_text_poisson_esd():
    txt = to_xye_text(np.array([10.0, 20.0]), np.array([100.0, 0.0]))
    lines = txt.strip().splitlines()
    assert lines[0].split() == ["10.000000", "100.000000", "10.000000"]  # esd=sqrt(100)=10
    # I=0 は esd 下限 1.0 (0 除算/ゼロ重み回避)
    assert lines[1].split()[2] == "1.000000"


def test_to_xye_text_row_count():
    txt = to_xye_text(np.arange(5.0), np.ones(5) * 4.0)
    assert len(txt.strip().splitlines()) == 5


# --- pxc_instprm_text ---

def test_pxc_instprm_contains_keys():
    txt = pxc_instprm_text(0.79958, zero=0.0059, polarization=0.95)
    assert "Type:PXC" in txt
    assert "Lam:0.799580" in txt
    assert "Polariz.:0.9500" in txt
    for k in ("U:", "V:", "W:", "X:", "Y:", "SH/L:", "Zero:"):
        assert k in txt


# --- standard_reference_cif ---

def test_standard_cif_ceo2():
    cif = standard_reference_cif("CeO2")
    assert "Ce" in cif and "O" in cif
    assert "_cell_length_a" in cif


def test_standard_cif_case_insensitive_and_registry():
    assert standard_reference_cif("ceo2") == STANDARD_REFERENCE_CIF["CeO2"]
    assert "Si" in STANDARD_REFERENCE_CIF


def test_standard_cif_unknown_raises():
    try:
        standard_reference_cif("Unobtainium")
        assert False, "未知標準は例外"
    except (KeyError, ValueError):
        pass


# --- extract_instrument_profile_from_standard (runner 注入・ファイル準備) ---

def _result(profile, rwp):
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=rwp, gof=1.0, n_params=8, converged=True),),
        final_rwp=rwp, final_gof=1.0, refined_cells={"CeO2": (5.41,) * 3 + (90.0,) * 3},
        validity=ValidityReport(passed=True), hist_profile=(profile,),
    )


def test_pipeline_prepares_files_and_extracts(tmp_path):
    # 生の2列 .dat を用意
    dat = tmp_path / "std.dat"
    dat.write_text("\n".join(f"{10+0.01*i:.3f} {100+i}" for i in range(50)) + "\n")
    captured = {}

    def stub(hists, phases, *, recipe=None, **kw):
        h = hists[0]
        captured["data_path"] = h.data_path
        captured["instr_path"] = h.instrument_path
        captured["phase"] = phases[0].phase_name
        captured["limits"] = h.two_theta_limits
        return _result({"U": 3.7, "V": -0.7, "W": 1.3, "X": 0.43, "Y": -5.3}, 8.9)

    ip = extract_instrument_profile_from_standard(
        str(dat), wavelength=0.79958, standard="CeO2", work_dir=str(tmp_path),
        two_theta_limits=(8.0, 82.0), runner=stub, refine_sh_l=False,
    )
    # 抽出結果 + 波長記録
    assert ip.values["U"] == 3.7
    assert ip.source_rwp == 8.9
    assert ip.wavelength == 0.79958
    # 準備ファイルが work_dir に生成され runner に渡っている
    assert Path(captured["data_path"]).exists() and captured["data_path"].endswith(".xye")
    assert Path(captured["instr_path"]).exists()
    assert captured["phase"] == "CeO2"
    assert captured["limits"] == (8.0, 82.0)
    # 生成 xye は3列 (esd 付き)
    first = Path(captured["data_path"]).read_text().strip().splitlines()[0].split()
    assert len(first) == 3


def test_pipeline_deterministic(tmp_path):
    dat = tmp_path / "std.dat"
    dat.write_text("\n".join(f"{10+0.01*i:.3f} {100+i}" for i in range(20)) + "\n")

    def stub(hists, phases, *, recipe=None, **kw):
        return _result({"W": 1.3}, 9.0)

    a = extract_instrument_profile_from_standard(str(dat), wavelength=0.8, work_dir=str(tmp_path / "a"), runner=stub)
    b = extract_instrument_profile_from_standard(str(dat), wavelength=0.8, work_dir=str(tmp_path / "b"), runner=stub)
    assert dict(a.values) == dict(b.values) and a.wavelength == b.wavelength
