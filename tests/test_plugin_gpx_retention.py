"""★③ の手順書が「成果物は全部保存される・どこを見る」を実際に言っていることの恒久ガード。

skill/PLAYBOOK は **③ (LLM) への実行可能な指示**であり、誤った/欠けた指示は実装バグと同等に
有害である (CLAUDE.md 不変条件)。① と ② を配線しても、手順書が

- 「保存される」と言わなければ ③ は保存を**頼まない**か、無いものとして進む
- ハンドル名 (`gpx_path` / `gpx_dir`) を書かなければ ③ は**探せない**
- ② に無い引数 (`keep_gpx` は ① 専用) を書けば ③ は**呼べない引数を呼ぶ**

ため、規定は成立しない。ここは「文書に書いてあること」を機械検査する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SKILLS = Path("plugins/tsumugin/skills")
_PLAYBOOKS = (
    Path("docs/tasks/m7-real-data-validation/AGENT_PLAYBOOK.md"),
    Path("docs/tasks/m9-insitu-sequential/AGENT_PLAYBOOK.md"),
    Path("docs/tasks/operando-diagnosis/AGENT_PLAYBOOK.md"),
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_analyze_skill_declares_that_artifacts_are_saved_by_default():
    """`analyze`: 既定で保存されること・ハンドルが `gpx_path` であることを言う。"""
    body = _text(_SKILLS / "analyze" / "SKILL.md")

    assert "既定で全部保存" in body, "「既定で保存される」と書かれていない (③ は頼まない)"
    assert "gpx_path" in body, "保存先を読むキー名が書かれていない (③ は探せない)"
    assert "gpx_dir" in body, "置き場所を指定する引数が書かれていない"
    assert "save_gpx" in body, "opt-out が書かれていない (容量問題で詰まったとき手が無い)"


def test_insitu_skill_declares_per_frame_artifacts():
    """`insitu`: フレーム別ハンドルと**棄却トライアルも残る**ことを言う。"""
    body = _text(_SKILLS / "insitu" / "SKILL.md")

    assert "frames[].gpx_path" in body, "フレーム別ハンドルが書かれていない"
    assert "gpx_dir" in body, "系列の run ディレクトリが書かれていない"
    assert "trial" in body and "棄却" in body, (
        "棄却されたトライアルも残ることが書かれていない — "
        "「なぜ棄却されたか」を追う唯一の一次資料である"
    )


def test_mem_skill_says_where_the_gpx_handle_comes_from():
    """`mem-model-fix`: 入力 `gpx_path` の**出所**を言う (§4.5 到達可能性)。

    MEM ツールの入力は「精密化済み gpx のパス」であり、それを産む ② ツールを名指ししないと
    ③ から見て呼び手が存在しない (dead on arrival)。
    """
    body = _text(_SKILLS / "mem-model-fix" / "SKILL.md")

    assert "auto_rietveld" in body
    assert "frames[].gpx_path" in body, (
        "系列フレームからも MEM を掛けられることが書かれていない "
        "(operando の任意フレームは sequential 系の出力からしか来ない)"
    )


def test_joint_skill_says_where_each_model_variant_fit_is():
    """`joint`: モデル比較の**各バリアント** (棄却モデルも) のハンドルと保存指定を言う。

    `compare_structure_models` の目的は「サイトは要るか」の判定であり、その根拠は棄却された
    モデルがどう壊れていたか (実測 NaCuHCF model5 は Na>1 / O<0 に発散) にある。ハンドル名を
    書かなければ ③ は ΔBIC だけを報告し、棄却側の fit を誰も開かない。
    """
    body = _text(_SKILLS / "joint" / "SKILL.md")

    assert "scores[].gpx_path" in body, "バリアント別ハンドルが書かれていない"
    assert "gpx_dir" in body and "save_gpx" in body, "モデル比較の保存指定が書かれていない"


_REPAIR_DOCS = (
    _SKILLS / "insitu" / "SKILL.md",
    _SKILLS / "operando-diagnose" / "SKILL.md",
    Path("docs/tasks/operando-diagnosis/AGENT_PLAYBOOK.md"),
)


@pytest.mark.parametrize("path", _REPAIR_DOCS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_repair_docs_say_where_rejected_repair_fits_are(path: Path):
    """修復を扱う手順書: **棄却された修復**の fit の在処 (台帳行) と修復の run ディレクトリを言う。

    棄却された修復 (`needs_model_revision`) は `repairs[]` に現れない。「warm-start でなぜ
    直らなかったか」を見るために保存しているのに、在処 (`insitu_repair_rejected` 行の
    `gpx_path`) を書かなければ ③ からは存在しないのと同じ。修復は系列とは別の呼び出しなので
    成果物も**別の run ディレクトリ**にある (系列の `gpx_dir` を探しても見つからない)。
    """
    body = _text(path)

    assert "insitu_repair_rejected" in body, f"{path}: 棄却された修復の fit の在処が書かれていない"
    assert "別の run ディレクトリ" in body, f"{path}: 修復試行が系列と別の run にあることが書かれていない"


#: 退避理由を返す ② ツール → それを ③ に説明する手順書。キーは「その手順書が名指しすべき返り値」。
_FALLBACK_DOCS = {
    _SKILLS / "analyze" / "SKILL.md": ("warnings", "search.warnings", "convergence.warnings"),
    _SKILLS / "insitu" / "SKILL.md": ("warnings", "m9_gpx_fallback"),
}


@pytest.mark.parametrize(
    "path", sorted(_FALLBACK_DOCS), ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_skills_say_where_the_fallback_reason_appears(path: Path):
    """成果物が一時領域へ退避したとき**どのキーに理由が出るか**を手順書が言う (設計 §5/§6)。

    ② が理由を返していても、手順書がキーを書かなければ ③ は ``gpx_path`` を「頼んだ場所」と
    読んだまま報告する (退避先は OS の掃除で消えうる)。行の形 (``成果物の保存先:``) も書く —
    `validity.warnings` 等と同じ ``warnings`` 名なので、形が無いと ③ は見分けられない。
    """
    body = _text(path)

    assert "成果物の保存先" in body, f"{path}: 退避理由の行の形が書かれていない"
    assert "一時領域" in body, f"{path}: 退避したら一時領域にあることが書かれていない"
    for key in _FALLBACK_DOCS[path]:
        assert f"`{key}`" in body, f"{path}: 退避理由が出るキー {key!r} が書かれていない"


@pytest.mark.parametrize("path", _PLAYBOOKS, ids=lambda p: p.parent.name)
def test_playbooks_mention_the_retention_rule(path: Path):
    """非 Claude 実行者向け PLAYBOOK にも規定が書かれていること (skill と同じ内容)。"""
    body = _text(path)
    assert "gpx" in body.lower()
    assert "gpx_path" in body or "gpx_dir" in body, f"{path}: ハンドル名が書かれていない"


def test_skills_do_not_advertise_the_layer1_only_argument():
    """③ の手順書に ``keep_gpx`` を書かない — **② から渡せない ① 専用引数**である。

    ② が受けるのは `gpx_dir` / `save_gpx`。手順書が `keep_gpx` を書くと、③ は JSON に
    その名前を載せて呼び、**黙って無視される**か error になる (「呼べるが間違う」の再導入)。
    """
    offenders = [
        p for p in _SKILLS.rglob("SKILL.md") if "keep_gpx" in _text(p)
    ]
    assert not offenders, (
        f"③ 手順書が ① 専用引数 keep_gpx を宣伝している: {[str(p) for p in offenders]}"
    )
