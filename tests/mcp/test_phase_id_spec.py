"""② の設定 spec パーサ (`mcp._config_spec` 共有パーサ) の契約テスト (Issue #97 カバレッジ規則)。

**この defect の型**: ① 実装済 + テスト green ≠ ③ が到達できる。`PhaseIdConfig` は 19 フィールドを
持つのに、② `sequential_rietveld` は 7 キーの明示ホワイトリストで組み立てていたため、残り 12 は
**③ にとって存在しなかった** — 引数の出所 (規則①〜③) の問題ではなく、**呼び出せる面が無い**問題である。

とりわけ致命的だったのが 2 つ:

- ``wavelength`` (既定 **Cu Kα1 1.5406 Å**): 異方セルプリアラインと候補再スコアの線源波長。
  ③ から届かないため、**放射光 (λ≈0.8 Å) / 中性子系列は黙って Cu の波長で prealign・rerank して
  いた**。d↔2θ 変換が丸ごと狂うので、prealign が返すセルも候補順位も系統的に誤る (しかも
  例外は出ず Rwp が下がらないだけなので、③ は「この系では新相同定が効かない」と誤学習する)。
- ``refine_new_phase_cell``: 異方セルプリアラインの唯一の escape hatch。少数相フレームでは
  prealign が支配相のピークにロックして誤セルを返す (memory: prealign FoM minority bias) ため、
  切りたい場面が実在するのに切れなかった。

本テストは (a) 全フィールドが ② を往復すること、(b) タイポが黙って無視されないこと、
(c) 型の取り違えが黙って別の意味にならないこと を固定する。

**変異実証 (このファイルのガードが落ちることを実測済)**: 以下の 10 変異を実装へ当てて、
対応するテストが**実際に fail する**ことを確認した (無害な変異を当てた対照は pass する
= 常に落ちる網ではない)。

===================================================== =========================
変異                                                   落ちるテスト
===================================================== =========================
② を旧 7 キーのホワイトリストへ戻す                    forwards_every_phase_id_field
``wavelength`` だけを落とす (放射光の実害そのもの)     synchrotron_wavelength_reaches_the_prealign
bool ガード撤去 (``"false"`` → True の反転が復活)      rejects_non_bool_for_bool_field / anchor_config 側
int 整数性ガード撤去 (``int(3.9)==3`` の切り捨て)      rejects_non_integral_float_for_int_field
タプル裸文字列ガード撤去 (``"CaTeO"`` の分解)          rejects_bare_string_for_element_list
タプル要素型ガード撤去 (``[19,25,26]`` → ``("19",…)``) rejects_non_string_elements
null ガード撤去 (非 Optional が既定へ黙って戻る)       rejects_null_for_non_optional_field
未知キーガード撤去 (typo を黙って無視)                 rejects_unknown_keys / unknown_key_degrades_to_error_dict
``PhaseIdConfig`` の組み立てを try の外へ戻す          bad_phase_id_degrades_to_error_dict
③ 手順書から Cu 既定の警告を削る                       test_m9_plugin::..._wavelength_defaults_to_cu
① に新フィールドを足す                                 covers_every_phase_id_config_field /
                                                       test_layer_coverage::..._declares_its_fraction_basis
===================================================== =========================
"""

from __future__ import annotations

import dataclasses

import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.model import FrameSpec, PhaseIdConfig, SequentialRietveldResult
from tsumugin.mcp.insitu_tools import sequential_rietveld

#: 全フィールドを**既定と異なる**値で埋めた JSON spec。既定と同じ値だと「配線が無くても通る」
#: トートロジーになるため、1 つ残らず既定からずらす (下の網羅アサーションが取りこぼしを防ぐ)。
_ALL_FIELDS_SPEC: dict[str, object] = {
    "elements": ["K", "Mn", "Fe", "C", "N"],
    "frac_min": 0.05,
    "rwp_eps": 0.5,
    "top_k": 3,
    "hull_cutoff_ev": 0.05,
    "subtract_bg": False,
    "trigger_rwp_ratio": 1.5,
    "refine_new_phase_cell": False,
    "wavelength": 0.800113,  # 実測 K₂Mn[Fe(CN)₆] の放射光波長 (Cu Kα1 1.5406 ではない)
    "rerank_top_k": 8,
    "min_rwp_gain": 0.03,
    "require_validity": True,
    "require_full_element_system": False,
    "snr_trigger": 30.0,
    "max_new_phases": 2,
    "bic_acceptance": True,
    "bic_base_params": 40,
    "bic_per_phase_params": 15,
    "warm_start_known_phases": False,
    # 既定 0.0 (正スコアを要求) と**違う値**を置く — 転送されていなければ既定に戻り fail する。
    # `float | None` なので `null` も通る (ゲート無効) が、ここは転送の検証なので float を使う。
    "min_identify_score": 0.05,
}

#: 期待される PhaseIdConfig (spec と 1:1。`elements` だけ tuple 化される)。
_EXPECTED = PhaseIdConfig(
    **{**_ALL_FIELDS_SPEC, "elements": ("K", "Mn", "Fe", "C", "N")}  # type: ignore[arg-type]
)


def test_the_spec_fixture_covers_every_phase_id_config_field():
    """★上の spec が `PhaseIdConfig` の**全**フィールドを埋めていること (テスト自身の陳腐化防止)。

    非トートロジー: `dataclasses.fields` で実フィールドを列挙する。① にフィールドを足したら
    本テストが fail し、「② から到達可能にするか / なぜしないか」を一度考えさせる
    (`tests/test_layer_coverage.py` の SPEC_INPUT_BASIS 網と同じ規律の、値レベル版)。
    """
    actual = {f.name for f in dataclasses.fields(PhaseIdConfig)}
    assert set(_ALL_FIELDS_SPEC) == actual, (
        f"spec fixture と PhaseIdConfig が食い違う。"
        f"未網羅 (② から届くか確かめること): {sorted(actual - set(_ALL_FIELDS_SPEC))} / "
        f"実在しない (削除/改名?): {sorted(set(_ALL_FIELDS_SPEC) - actual)}"
    )
    # 既定と同じ値が混じっていると「配線が無くても通る」ので、ずれていることを確かめる
    defaults = PhaseIdConfig()
    same = [
        name
        for name in _ALL_FIELDS_SPEC
        if getattr(_EXPECTED, name) == getattr(defaults, name)
    ]
    assert not same, f"既定と同じ値を使っているフィールド (配線が無くても通る): {same}"


# ---------------------------------------------------------------------------
# ① 共有パーサ単体
# ---------------------------------------------------------------------------


def test_phase_id_config_from_dict_round_trips_every_field():
    """★JSON spec の全 19 フィールドが `PhaseIdConfig` へ往復すること。

    **旧実装はここで落ちた**: 7 キー (elements/frac_min/rwp_eps/top_k/hull_cutoff_ev/
    subtract_bg/trigger_rwp_ratio) のホワイトリストだったため、残り 12 は既定のまま黙って捨てられた。
    """
    assert PhaseIdConfig.from_dict(_ALL_FIELDS_SPEC) == _EXPECTED


def test_phase_id_config_from_dict_empty_is_all_defaults():
    assert PhaseIdConfig.from_dict({}) == PhaseIdConfig()


def test_phase_id_config_from_dict_rejects_unknown_keys():
    """タイポは黙って無視せず ValueError (許容キー一覧つき)。

    黙って無視すると ③ は「設定したのに効かない」= `_recipe_spec` が潰した「呼べるが黙って
    間違う」型の事故を再導入する。③ は ② の error dict で自力修正できる。
    """
    with pytest.raises(ValueError, match="wavelenght"):
        PhaseIdConfig.from_dict({"wavelenght": 0.8})  # 実際に起きやすい綴り誤り


def test_phase_id_config_from_dict_allows_null_for_optional_field():
    """`hull_cutoff_ev` は `float | None` なので null (= MP 安定性フィルタ無効) を通すこと。"""
    assert PhaseIdConfig.from_dict({"hull_cutoff_ev": None}).hull_cutoff_ev is None


def test_phase_id_config_from_dict_rejects_null_for_non_optional_field():
    """★非 Optional フィールドの null は ValueError (既定へ黙って戻さない)。

    黙って既定へ戻すと「null を送って無効化したつもり」が既定値で動く = 別の解析になる。
    """
    with pytest.raises(ValueError, match="wavelength"):
        PhaseIdConfig.from_dict({"wavelength": None})


def test_phase_id_config_from_dict_rejects_non_bool_for_bool_field():
    """★bool フィールドに非 bool を渡したら ValueError。

    **これが「黙って逆の意味になる」の典型**: JSON の文字列 ``"false"`` は Python の
    ``bool("false") is True`` である。旧 `AnchorConfig.from_dict` / ② の
    ``bool(phase_id.get("subtract_bg", True))`` はどちらもこの縮退を持っていた —
    ③ が「背景減算を切る」つもりで送った ``"false"`` が**入れたまま**になる。
    """
    with pytest.raises(ValueError, match="subtract_bg"):
        PhaseIdConfig.from_dict({"subtract_bg": "false"})


def test_phase_id_config_from_dict_rejects_non_integral_float_for_int_field():
    """★int フィールドへの非整数 float は ValueError (`int(3.9) == 3` の黙った切り捨てを防ぐ)。

    ``40.0`` のような整数値 float は許す (JSON は int/float を区別しないクライアントがある)。
    """
    assert PhaseIdConfig.from_dict({"top_k": 3.0}).top_k == 3
    with pytest.raises(ValueError, match="top_k"):
        PhaseIdConfig.from_dict({"top_k": 3.9})


def test_phase_id_config_from_dict_rejects_bare_string_for_element_list():
    """★`elements` に裸の文字列を渡したら ValueError (1 文字ずつに分解する黙った誤り)。

    ``"CaTeO"`` を許すと ``("C","a","T","e","O")`` = 元素系が丸ごと別物になり、同定候補が
    全滅する (例外は出ないので ③ は「MP に候補が無い」と誤診する)。
    """
    with pytest.raises(ValueError, match="elements"):
        PhaseIdConfig.from_dict({"elements": "CaTeO"})


@pytest.mark.parametrize(
    "elements",
    [
        pytest.param([19, 25, 26], id="atomic_numbers"),
        pytest.param(["K", 25], id="mixed"),
        pytest.param([["K"], "Mn"], id="nested_list"),
        pytest.param([True], id="bool"),
    ],
)
def test_phase_id_config_from_dict_rejects_non_string_elements(elements):
    """★`elements` の**要素**が文字列でなければ ValueError (``str()`` の黙った文字列化を防ぐ)。

    裸文字列ガード (上のテスト) だけでは足りない: リストの**中身**が元素記号でないとき、
    ``tuple(str(v) for v in value)`` は同じ事故を静かに起こす — 原子番号 ``[19, 25, 26]`` は
    ``("19","25","26")``、入れ子 ``[["K"], "Mn"]`` は ``("['K']","Mn")`` になり、**例外を
    出さないまま候補が全滅する** (③ は「MP に候補が無い」と誤診し、元素系ではなく
    Materials Project 側を疑い始める)。

    他の型 (bool/int/float/str) は全て不一致で ValueError にしているので、タプルの要素だけ
    黙って読み替える非対称を残さない。
    """
    with pytest.raises(ValueError, match="elements"):
        PhaseIdConfig.from_dict({"elements": elements})


def test_phase_id_config_from_dict_keeps_valid_element_lists():
    """正しい元素記号のリストは通り、tuple[str, ...] になること (ガードが過剰でないこと)。"""
    cfg = PhaseIdConfig.from_dict({"elements": ["Ca", "Te", "O"]})
    assert cfg.elements == ("Ca", "Te", "O")
    assert all(isinstance(e, str) for e in cfg.elements)


def test_phase_id_config_from_dict_rejects_non_mapping():
    with pytest.raises(ValueError, match="dict"):
        PhaseIdConfig.from_dict(["elements", "Ca"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ② `sequential_rietveld` — ③ から実際に届くか (境界を跨いだ観測)
# ---------------------------------------------------------------------------


def _capture_config(monkeypatch) -> dict:
    """`run_sequential_rietveld` を捕捉スタブへ差し替え、渡された SequentialConfig を捕まえる。

    非トートロジー: ② のソースを grep せず、**②→① の境界を実際に越えた設定オブジェクト**を見る。
    """
    captured: dict[str, object] = {}

    def fake_run(frames, phases, *, config=None, runner=None, phase_finder=None, workdir=None):
        captured["config"] = config
        return SequentialRietveldResult(frames=(), phase_names=())

    monkeypatch.setattr("tsumugin.insitu.engine.run_sequential_rietveld", fake_run)
    return captured


_FRAMES = [FrameSpec("f0.xye", data_format="XYE", axis_value=0.0).to_dict()]
_PHASES = [PhaseSpec("alpha.cif", "alpha").to_dict()]


def _stub_runner(frame, phases, initial_cells):
    return AutoRietveldResult(
        stage_results=(), final_rwp=9.0, final_gof=1.0, refined_cells={},
        validity=ValidityReport(passed=True), phase_fractions={},
    )


def test_sequential_rietveld_forwards_every_phase_id_field(monkeypatch):
    """★★③ が送った `phase_id` の**全フィールド**が ① の `PhaseIdConfig` に届くこと。

    **旧実装はここで落ちた** (Issue #97 型のカバレッジ欠陥): ② が 7 キーだけを読んでいたため、
    ``wavelength``/``refine_new_phase_cell``/``min_rwp_gain``/``require_validity``/
    ``require_full_element_system``/``snr_trigger``/``max_new_phases``/``bic_*``/
    ``rerank_top_k``/``warm_start_known_phases`` は ③ にとって存在しなかった。
    """
    captured = _capture_config(monkeypatch)

    sequential_rietveld(
        _FRAMES, _PHASES, phase_id=_ALL_FIELDS_SPEC, runner=_stub_runner
    )

    assert captured["config"].phase_id == _EXPECTED  # type: ignore[union-attr]


def test_sequential_rietveld_synchrotron_wavelength_reaches_the_prealign(monkeypatch):
    """★放射光波長が prealign/rerank に届くこと (既定 Cu Kα1 のまま黙って走らせない)。

    ``wavelength`` は `insitu.engine._prealigned_spec` → `prealign_cell_from_structure` と
    `identify_new_phases(rerank_wavelength=)` の両方に渡る。λ を間違えると d↔2θ が丸ごとずれ、
    プリアライン後のセルも候補順位も系統的に誤る (例外なし = 気づけない)。
    """
    captured = _capture_config(monkeypatch)

    sequential_rietveld(
        _FRAMES, _PHASES,
        phase_id={"elements": ["K", "Mn", "Fe", "C", "N"], "wavelength": 0.800113},
        runner=_stub_runner,
    )

    pid = captured["config"].phase_id  # type: ignore[union-attr]
    assert pid.wavelength == pytest.approx(0.800113)
    assert pid.wavelength != PhaseIdConfig().wavelength, "既定 (Cu Kα1) のまま届いている"


def test_sequential_rietveld_bad_phase_id_degrades_to_error_dict():
    """★不正な `phase_id` は例外を貫かせず ``{"error", "error_type"}`` へ縮退すること。

    **旧実装はここでも落ちた**: `PhaseIdConfig(...)` の組み立てが try ブロックの**外**にあり、
    ``float("x")`` の ValueError が ② 境界を貫通していた (② は例外を送出しない契約 —
    ③ は LLM なので例外は回復不能なハード失敗になる)。
    """
    out = sequential_rietveld(_FRAMES, _PHASES, phase_id={"frac_min": "x"}, runner=_stub_runner)
    assert out["error_type"] == "ValueError"
    assert "frac_min" in out["error"]


def test_sequential_rietveld_unknown_phase_id_key_degrades_to_error_dict():
    """タイポは error dict で ③ に返す (黙って無視 = 効かないツマミ を作らない)。"""
    out = sequential_rietveld(
        _FRAMES, _PHASES, phase_id={"refine_new_phase_cells": False}, runner=_stub_runner
    )
    assert out["error_type"] == "ValueError"
    assert "refine_new_phase_cells" in out["error"]


# ---------------------------------------------------------------------------
# ② `anchored_sequential` — 同じ共有パーサを通ること
# ---------------------------------------------------------------------------


def test_anchor_config_shares_the_parser_and_rejects_string_false():
    """★`anchored_sequential` の `anchor_config` も同じ共有パーサを通ること。

    `AnchorConfig` は元から全フィールド網羅 (whitelist ではない) だったので**切り詰めの穴は
    無かった**が、``bool(value)`` の縮退は同型で持っていた: ``"false"`` → True。
    ③ が「結合ゲートを切る」つもりで送った文字列が**入れたまま**になる。共有パーサで両方塞ぐ。
    """
    from tsumugin.insitu.anchor.model import AnchorConfig

    with pytest.raises(ValueError, match="require_bond_validity"):
        AnchorConfig.from_dict({"require_bond_validity": "false"})


def test_anchored_sequential_string_false_degrades_to_error_dict():
    """② 境界でも例外でなく error dict になること (縮退契約は共有パーサ導入後も不変)。"""
    from tsumugin.mcp.anchor_tools import anchored_sequential

    out = anchored_sequential(
        _FRAMES, _PHASES,
        anchor_config={"require_bond_validity": "false"},
        runner=_stub_runner,
    )
    assert out["error_type"] == "ValueError"
    assert "require_bond_validity" in out["error"]
