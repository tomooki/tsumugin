"""② `propose_data_preprocessing` — ① `autorietveld.autorange` の露出 (REQ-SAR-401/402/403)。

★不変条件 (CLAUDE.md): **実装は必ず ② と ③ に露出させる — 実行者から見えない実装は「無い」と
同じ**。`autorange` は 760 行実装され `-m "not gsas"` で green だったが、③ から名指しで呼ぶ
JSON 経路が無く、`propose_excluded_regions` に至っては src 配下の呼び出し元がゼロだった
(M10 anchor の再演)。本テストは以下を固定する:

1. **JSON だけで届く** (パス文字列と素の型のみ。配列を境界に跨がせない)
2. **返り値が `auto_rietveld` の入力へそのまま貼れる** (到達可能性の「出口」側)
3. **除外領域は提案に留まる** (P-SAR-3。ツール自身が自分の提案を適用しない)
4. **例外を送出せず error dict へ縮退する** (③ は LLM なので例外は回復不能)

GSAS-II には依存しない (`-m "not gsas"` で回る)。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.mcp.rietveld_tools import propose_data_preprocessing
from tsumugin.mcp.tools import MCP_TOOLS


# --- 合成パターン (test_autorange と同じ病理: 低角の裾 + 高角のノイズ支配域) ----------


def _gauss(x: np.ndarray, center: float, height: float, fwhm: float) -> np.ndarray:
    sigma = fwhm / 2.354820045
    return height * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def _t4_like(seed: int = 3) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = np.linspace(3.0, 80.0, 7701)
    clean = 20.0 + 4000.0 * np.exp(-(x - 3.0) / 0.7)
    for center, height in [
        (12.0, 900.0), (17.0, 600.0), (21.0, 1200.0),
        (26.0, 400.0), (31.0, 700.0), (40.0, 250.0),
    ]:
        clean = clean + _gauss(x, center, height, 0.12)
    return x, rng.poisson(clean).astype(float)


def _spike_pattern(seed: int = 7) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """試料ピーク群 + **鋭い孤立**スパイク 1 本 (除外候補として挙がるべき信号)。"""
    rng = np.random.default_rng(seed)
    x = np.linspace(10.0, 70.0, 6001)
    sample = [15.0, 17.5, 20.0, 22.5, 25.0, 27.5, 30.0, 32.5, 35.0]
    clean = np.full_like(x, 40.0)
    for center in sample:
        clean = clean + _gauss(x, center, 900.0, 0.30)
    clean = clean + _gauss(x, 55.0, 1500.0, 0.04)  # 検出器スパイク (鋭い + 孤立)
    return x, rng.poisson(clean).astype(float), sample


def _write_xy(tmp_path, x: np.ndarray, y: np.ndarray, name: str = "p.xy") -> str:
    path = tmp_path / name
    np.savetxt(path, np.column_stack([x, y]))
    return str(path)


# ===========================================================================
# ② 到達可能性: JSON だけで届き、出力が入力へ貼れる
# ===========================================================================


def test_tool_is_registered_in_the_mcp_registry():
    assert MCP_TOOLS["propose_data_preprocessing"] is propose_data_preprocessing


def test_range_and_background_are_returned_in_a_form_that_pastes_into_auto_rietveld(tmp_path):
    # 【到達可能性の出口】: 返り値が `HistogramSpec.two_theta_limits` /
    #   `auto_rietveld(background_coeffs=)` にそのまま入ること。値を作り直させない。
    x, y = _t4_like()
    out = propose_data_preprocessing(_write_xy(tmp_path, x, y))

    limits = out["two_theta_range"]["two_theta_limits"]
    spec = HistogramSpec(
        data_path="d.xy",
        instrument_path="i.prm",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        two_theta_limits=(limits[0], limits[1]),
    )
    assert spec.to_dict()["two_theta_limits"] == limits
    # T4 の病理 (低角の裾 + 高角のノイズ支配域) が両側とも切られていること
    assert limits[0] > x[0] and limits[1] < x[-1]

    terms = out["background_terms"]["recommended"]
    assert isinstance(terms, int) and terms >= 1
    assert terms in out["background_terms"]["candidates"]


def test_output_is_json_safe_and_carries_no_arrays(tmp_path):
    # 【配列を跨がせない】: 実データは数千点。境界に載せてよいのはスカラと少数の候補だけ。
    x, y, _ = _spike_pattern()
    out = propose_data_preprocessing(_write_xy(tmp_path, x, y))

    json.dumps(out, allow_nan=False)  # 非有限は None 化されていること
    assert len(out["excluded_region_candidates"]["candidates"]) <= 10


def test_esd_column_switches_the_noise_model_to_counting_statistics(tmp_path):
    # 【契約差】: `assess_data_quality` (esd 非対応) との違いはここ。3 列 XYE は esd を活かす。
    x, y = _t4_like()
    path = tmp_path / "p.xye"
    np.savetxt(path, np.column_stack([x, y, np.sqrt(np.maximum(y, 1.0))]))

    out = propose_data_preprocessing(str(path), data_format="XYE")

    assert out["two_theta_range"]["noise_model"] == "esd"
    assert propose_data_preprocessing(_write_xy(tmp_path, x, y))[
        "two_theta_range"
    ]["noise_model"] == "mad"


# ===========================================================================
# P-SAR-3: 除外領域は**提案のみ**
# ===========================================================================


def test_excluded_regions_are_proposed_never_applied(tmp_path):
    # 【目的】: 除外は解析の解釈を変える操作 (未知相のピークを消せば相同定を殺す)。
    #   ツールは候補と注意書きだけを返し、**自分の提案を自分のレンジ判定へ流し込まない**。
    x, y, sample = _spike_pattern()
    path = _write_xy(tmp_path, x, y)

    out = propose_data_preprocessing(path, explained_two_theta=sample)
    excl = out["excluded_region_candidates"]

    assert excl["requires_human_approval"] is True
    centers = [c["center"] for c in excl["candidates"]]
    assert any(abs(c - 55.0) < 0.5 for c in centers), f"鋭い孤立スパイクが挙がらない: {centers}"

    # **提案を自己適用していない**: 候補と同じ区間を承認済みとして渡すと上限が変わる。
    #   自己適用していれば渡す前後で同じ答えになるはずである。
    approved = [[c["lower"], c["upper"]] for c in excl["candidates"]]
    after = propose_data_preprocessing(path, explained_two_theta=sample,
                                       excluded_regions=approved)
    assert after["two_theta_range"]["upper"] < out["two_theta_range"]["upper"], (
        "承認済み除外を渡しても上限が変わらない = 提案を内部で自己適用している疑い"
    )


def test_note_warns_when_the_explained_positions_are_missing(tmp_path):
    # 【情報が無いことを正常と答えない】: 反射位置が無ければ「説明できない」判定は成立しない。
    x, y, _ = _spike_pattern()
    out = propose_data_preprocessing(_write_xy(tmp_path, x, y))

    assert out["explained_source"] == "none"
    assert "explained_two_theta" in out["excluded_region_candidates"]["note"]


def test_unknown_wavelength_stops_position_generation_instead_of_guessing(tmp_path):
    # 【波長を知らないなら波長に依存する計算をしない】: λ=0.7996 の放射光を Cu Kα1 として
    #   扱うと 2θ が数度ずれ「説明済み」判定が丸ごと誤る。推測より「未確認」を返す。
    x, y, _ = _spike_pattern()
    out = propose_data_preprocessing(
        _write_xy(tmp_path, x, y),
        phases=[PhaseSpec(structure_path="a.cif", phase_name="ph").to_dict()],
        wavelength=None,
    )

    assert out["explained_source"] == "wavelength_unknown"


def test_unreadable_phase_cif_degrades_to_unavailable_not_to_a_false_clean_verdict(tmp_path):
    # 【偽の正常応答の禁止】: CIF を読めなかったことを「説明済みの相は無い」と答えない。
    x, y, _ = _spike_pattern()
    out = propose_data_preprocessing(
        _write_xy(tmp_path, x, y),
        phases=[PhaseSpec(structure_path=str(tmp_path / "nope.cif"),
                          phase_name="ph").to_dict()],
    )

    assert out["explained_source"] == "unavailable"
    assert "explained_two_theta" in out["excluded_region_candidates"]["note"]


# ===========================================================================
# ② の縮退契約: 例外を送出しない
# ===========================================================================


def test_missing_file_degrades_to_an_error_dict(tmp_path):
    out = propose_data_preprocessing(str(tmp_path / "missing.xy"))

    assert out["error_type"] in {"FileNotFoundError", "OSError"}
    assert "two_theta_range" not in out


def test_malformed_excluded_regions_degrade_to_an_error_dict(tmp_path):
    x, y = _t4_like()
    out = propose_data_preprocessing(_write_xy(tmp_path, x, y),
                                     excluded_regions=[[10.0, 20.0, 30.0]])

    assert out["error_type"] == "ValueError"


def test_malformed_phase_spec_degrades_to_an_error_dict(tmp_path):
    x, y = _t4_like()
    out = propose_data_preprocessing(_write_xy(tmp_path, x, y), phases=[{"phase_name": "ph"}])

    assert out["error_type"] == "ValueError"


def test_empty_pattern_is_not_answered_as_nothing_to_trim(tmp_path):
    # 【最悪の失敗形の禁止】: 空を「切り詰め不要」と答えると ③ は疑うのをやめる。
    path = tmp_path / "empty.xy"
    path.write_text("", encoding="utf-8")

    out = propose_data_preprocessing(str(path))

    assert "error" in out
    assert "two_theta_range" not in out


def test_repeated_calls_are_bit_identical(tmp_path):
    # 【NFR-102】: 決定論 (乱数なし)。
    x, y, sample = _spike_pattern()
    path = _write_xy(tmp_path, x, y)

    a = propose_data_preprocessing(path, explained_two_theta=sample)
    b = propose_data_preprocessing(path, explained_two_theta=sample)

    assert a == b


@pytest.mark.parametrize("key", ["two_theta_range", "background_terms",
                                 "excluded_region_candidates"])
def test_all_three_requirements_are_reachable_from_one_call(key, tmp_path):
    # 【REQ-SAR-401/402/403】: 3 要件すべてが 1 呼び出しで ③ に届くこと。
    x, y = _t4_like()
    out = propose_data_preprocessing(_write_xy(tmp_path, x, y))

    assert key in out


def test_empty_explained_list_is_normalized_to_unsupplied(tmp_path):
    # 【情報が無いことを正常と答えない】: 空列は「未説明を確認した」ではない。
    #   `propose_excluded_regions` は None と () を区別し、() では note の警告を落とすので、
    #   ここで正規化しないと ③ が「確認済み」と誤読する。
    x, y, _ = _spike_pattern()
    out = propose_data_preprocessing(_write_xy(tmp_path, x, y), explained_two_theta=[])

    assert out["explained_source"] == "none"
    assert "explained_two_theta" in out["excluded_region_candidates"]["note"]
