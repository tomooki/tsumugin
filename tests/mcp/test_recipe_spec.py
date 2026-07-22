"""`mcp._recipe_spec`: JSON 段階解放レシピ spec ↔ RefinementStage 変換の共有ヘルパ (Issue #101/#114)。

rietveld_tools (auto_rietveld/refine_with_revisions の ``stages``) と insitu_tools
(instrument spec の ``recipe``) が共有する唯一の変換実装であることを、構造的な検証と往復性で固定する。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld import RefinementStage
from tsumugin.mcp._recipe_spec import stage_from_dict, stage_to_dict, stages_from_dicts


def test_stage_from_dict_minimal():
    stage = stage_from_dict({"label": "S9 absorption"})
    assert stage == RefinementStage(label="S9 absorption", flags={}, note="")


def test_stage_from_dict_full():
    stage = stage_from_dict(
        {"label": "S9 abs", "flags": {"absorption": True}, "note": "opt-in absorption"}
    )
    assert stage.label == "S9 abs"
    assert stage.flags == {"absorption": True}
    assert stage.note == "opt-in absorption"


def test_stages_from_dicts_preserves_order():
    stages = stages_from_dicts(
        [{"label": "S9", "flags": {"absorption": True}}, {"label": "S10", "flags": {"tof_profile": True}}]
    )
    assert [s.label for s in stages] == ["S9", "S10"]
    assert stages[1].flags == {"tof_profile": True}


def test_stages_from_dicts_none_and_empty_are_empty_tuple():
    assert stages_from_dicts(None) == ()
    assert stages_from_dicts([]) == ()


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("not-a-dict", id="非 dict"),
        pytest.param({"flags": {}}, id="label 欠落"),
        pytest.param({"label": ""}, id="label 空文字"),
        pytest.param({"label": 5}, id="label が非文字列"),
        pytest.param({"label": "S9", "flags": "not-a-dict"}, id="flags が非 dict"),
        pytest.param({"label": "S9", "note": 5}, id="note が非 str"),
        pytest.param({"label": "S9", "unknown_key": 1}, id="不明なキー"),
    ],
)
def test_stage_from_dict_rejects_malformed_input(bad):
    """不正なキー/型は黙って無視せず ValueError にする (「呼べるが黙って間違う」の再導入防止)。"""
    with pytest.raises(ValueError):
        stage_from_dict(bad)


def test_stages_from_dicts_propagates_first_error():
    with pytest.raises(ValueError):
        stages_from_dicts([{"label": "ok"}, {"label": ""}])


def test_stage_to_dict_roundtrip():
    stage = RefinementStage(label="S9 abs", flags={"absorption": True}, note="n")
    d = stage_to_dict(stage)
    assert d == {"label": "S9 abs", "flags": {"absorption": True}, "note": "n"}
    assert stage_from_dict(d) == stage


def test_stage_to_dict_then_from_dict_is_identity_for_defaults():
    stage = RefinementStage(label="S0")
    assert stage_from_dict(stage_to_dict(stage)) == stage


def test_unknown_flag_name_is_rejected_with_allowed_list():
    """★未知フラグ名を拒否すること (「呼べるが黙って間違う」の予防)。

    engine は `if "cell" in flags` の明示的メンバシップで消費するため、未知名は**黙って
    無視される**。`profile_lorentzain` (1 文字タイポ) を通すと段階は走るのに何も解放されず、
    ③ は「この knob は効かない」と誤学習する。許容一覧付きで失敗させ自力修正を可能にする。
    """
    with pytest.raises(ValueError) as ei:
        stage_from_dict({"label": "typo", "flags": {"profile_lorentzain": True}})
    msg = str(ei.value)
    assert "profile_lorentzain" in msg, "どのフラグが不正か示していない"
    assert "profile_lorentzian" in msg, "許容一覧が無く ③ が自力で直せない"


def test_known_flags_covers_engine_vocabulary():
    """★`KNOWN_STAGE_FLAGS` が engine/recipe の実語彙を網羅すること (drift 検出)。

    非トートロジー: 表を読まず `autorietveld/engine.py` と `recipe.py` の**実ソース**から
    フラグ名リテラルを抽出して突き合わせる。engine に新フラグを足して本表を更新し忘れると、
    ③ がその新機能を指定した瞬間に「未知フラグ」で弾かれる (= 露出したのに使えない) ため、
    ここで強制的に気づかせる。
    """
    import re
    from pathlib import Path

    from tsumugin.mcp._recipe_spec import KNOWN_STAGE_FLAGS

    src_dir = Path(__file__).resolve().parents[2] / "src" / "tsumugin" / "autorietveld"
    vocab: set[str] = set()
    engine_src = (src_dir / "engine.py").read_text(encoding="utf-8")
    # `"name" in flags` / `"name" not in flags` / `flags.get("name")` (stage_flags 版も含む)
    for pat in (
        r'"([a-z_0-9]+)" (?:not )?in (?:stage_)?flags',
        r'(?:stage_)?flags\.get\("([a-z_0-9]+)"',
    ):
        vocab |= set(re.findall(pat, engine_src))
    recipe_src = (src_dir / "recipe.py").read_text(encoding="utf-8")
    vocab |= set(re.findall(r'"([a-z_0-9]+)": *(?:True|False)', recipe_src))

    assert vocab, "語彙抽出が 0 件 — 抽出パターンが実装とずれている (検査が空回りしている)"
    missing = vocab - KNOWN_STAGE_FLAGS
    assert not missing, (
        f"engine/recipe が解釈するフラグ {sorted(missing)} が KNOWN_STAGE_FLAGS に無い。"
        "② がこれを弾くため ③ から新機能が使えない — _recipe_spec.py の表を更新すること"
    )
