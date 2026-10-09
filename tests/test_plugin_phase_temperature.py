"""★③ の手順書が「測定温度はヒストグラムに入れる」と言い、相の `temperature` を効く設定として指示しない恒久ガード。

`PhaseSpec.temperature` は**どの精密化エンジンも読まないメタデータ**である (docstring と
`test_recipe.py` / `topas/test_recipe.py` の `test_phase_temperature_is_not_read_*` が実証)。
ヒストグラム間の温度差の段 (静水圧歪み Dij) は `HistogramSpec.temperature` だけで決まる。

③ (LLM) は `auto_rietveld` の `specs` ハンドルで各相に `"temperature": null` を見るので、手順書が
温度の置き場所を言わなければ相の側を埋めて「温度差を入れたつもり」になる — 段は張られず、
エラーも出ない (呼べるが黙って効かない)。ここは「文書に書いてあること」を機械検査する。

①②③ を横断する 1 つの契約なので、skill ごとの契約テストに割らず検出器をここに 1 つ置く
(`test_plugin_gpx_retention.py` と同じ形)。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tsumugin.mcp.tools import MCP_TOOLS

# cwd に依らず repo を指す (相対パスだと別の cwd で走査対象が空になり、ガードが黙って通る)
_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN = _ROOT / "plugins" / "tsumugin"
_DOCS = (
    *sorted(_PLUGIN.rglob("*.md")),
    *sorted((_ROOT / "docs" / "tasks").glob("*/AGENT_PLAYBOOK.md")),
)

#: 相の temperature への言及 (`phases[].temperature` / `PhaseSpec.temperature` / 相の `temperature`)。
_PHASE_TEMPERATURE = re.compile(
    r"phases\[[^\]]*\]\.temperature|PhaseSpec\.temperature|相の\s*`?temperature\b"
)
#: 言及に必須の否定。「読まない」単独だと「GSAS は読まないが TOPAS では効く」も通るので、
#: エンジン全体について言っていることを要求する。
_NO_ENGINE_READS = re.compile(r"(?:どの|どちらの)(?:精密化)?(?:エンジン|バックエンド)も読まない")
#: JSON の相オブジェクト (`phase_name`/`structure_path` を持つ入れ子なしの `{...}`) と、
#: その中で temperature に値を入れているもの (`null` は相の既定の往復なので許す)。
#: ⚠ 空白は先読みの**中**に置く — `:\s*(?!null)` だと `\s*` が後退して `: null` も一致する。
_PHASE_OBJECT = re.compile(r"\{[^{}]*\"(?:phase_name|structure_path)\"[^{}]*\}")
_SETS_TEMPERATURE = re.compile(r"\"temperature\"\s*:(?!\s*null\b)")


def _offending(name: str, text: str) -> list[str]:
    """相の temperature を効く設定として読める箇所 (文の言及・JSON の相の例)。"""
    bad = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _PHASE_TEMPERATURE.search(line) and not _NO_ENGINE_READS.search(line)
    ]
    bad += [
        f"{name}: JSON の相の例に temperature: {m.group(0)}"
        for m in _PHASE_OBJECT.finditer(text)
        if _SETS_TEMPERATURE.search(m.group(0))
    ]
    return bad


def test_the_guard_catches_an_instruction_to_set_a_phase_temperature():
    """検出器の自己検査: 相に温度を入れさせる記述は拾い、効かないと併記した記述は通す。"""
    assert _offending("x", "温度差があれば `phases[].temperature` に入れる")
    assert _offending("x", "PhaseSpec.temperature を測定温度にする")
    assert _offending("x", "相の `temperature` を 10 K にする")
    assert _offending("x", "GSAS は読まないが TOPAS では相の `temperature` が効く")
    assert _offending("x", '{"structure_path": "a.cif", "phase_name": "A", "temperature": 10}')
    assert _offending("x", '{"phase_name": "A",\n "temperature": 295.0}')
    assert not _offending("x", "相の `temperature` はどのエンジンも読まない")
    assert not _offending("x", "相の `temperature` は**どちらのエンジンも読まない**。")
    assert not _offending("x", "各 `histograms[].temperature` に入れる")
    assert not _offending("x", '{"phase_name": "A", "temperature": null}')
    assert not _offending("x", '{"data_path": "x.xye", "temperature": 295.0}')  # ヒストグラム


def test_the_scan_covers_the_skills_and_playbooks():
    """走査対象が空・欠けだとガードが黙って通る (落ちないガードは無いより悪い)。"""
    names = {p.relative_to(_ROOT).as_posix() for p in _DOCS}
    assert "plugins/tsumugin/skills/analyze/SKILL.md" in names
    assert "plugins/tsumugin/skills/joint/SKILL.md" in names
    assert "docs/tasks/m7-real-data-validation/AGENT_PLAYBOOK.md" in names


@pytest.mark.parametrize("path", _DOCS, ids=lambda p: p.relative_to(_ROOT).as_posix())
def test_documents_never_present_a_phase_temperature_as_effective(path: Path):
    """skill/コマンド/PLAYBOOK が相の temperature に触れるなら、どのエンジンも読まないと同じ行で言う。"""
    bad = _offending(path.relative_to(_ROOT).as_posix(), path.read_text(encoding="utf-8"))
    assert not bad, "相の temperature を効く設定として読める指示がある:\n" + "\n".join(bad)


def test_mcp_tool_docstrings_never_present_a_phase_temperature_as_effective():
    """② のツール docstring も同じ規則 (③ が読む説明の一次情報)。"""
    bad: list[str] = []
    for name, fn in MCP_TOOLS.items():
        bad += _offending(f"MCP_TOOLS[{name!r}]", getattr(fn, "__doc__", None) or "")
    assert not bad, "相の temperature を効く設定として読める docstring がある:\n" + "\n".join(bad)


@pytest.mark.parametrize("skill", ["analyze", "joint"])
def test_spec_building_skills_say_where_the_measurement_temperature_goes(skill: str):
    """`HistogramSpec`/`PhaseSpec` を組ませる skill は、温度の置き場所と相の側が効かないことを言う。

    `analyze` (手順 1 の入力組み立て) と `joint` (温度の違うヒストグラムを束ねる典型 —
    M7 T3 は X 線 295 K / 中性子 10 K) が対象。置き場所だけでなく「相の側は読まれない」まで
    書かないと、`specs` ハンドルで相の `"temperature": null` を見た ③ はそこを埋める。
    """
    body = (_PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "histograms[].temperature" in body, f"{skill}: 測定温度の置き場所を言っていない"
    assert _PHASE_TEMPERATURE.search(body), f"{skill}: 相の temperature が効かないことを言っていない"
