"""fit-then-judge P1-1A タスク 10: ③ の手順書が出版状態から報告するよう縛るガード (REQ-FTJ-1A-504)。

skill は「③ への実行可能な指示」なので、誤った指示は実装バグと同等に有害 (CLAUDE.md)。手順書に書いた
キー・語彙・ツールが ② に実在することと、報告の仕方 (`publishable_values` から書く・平文フィールドから
拾わない・判断要求を閉じない) が消えないことを固定する。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from tsumugin.claims.model import Determinacy

_ROOT = Path(__file__).resolve().parents[1]
_SKILL = (_ROOT / "plugins/tsumugin/skills/analyze/SKILL.md").read_text(encoding="utf-8")
_PLAYBOOK = (_ROOT / "docs/tasks/m7-real-data-validation/AGENT_PLAYBOOK.md").read_text(
    encoding="utf-8"
)


def _section(text: str, heading_prefix: str) -> str:
    start = text.index(heading_prefix)
    nxt = text.find("\n## ", start + 1)
    return text[start: nxt if nxt != -1 else len(text)]


_CLAIMS_SECTION = _section(_SKILL, "## 出版状態")


def test_the_reporting_rule_is_stated():
    for needle in ("publishable_values", "judgment_requests", "claims", "export_claims_csv"):
        assert f"`{needle}" in _CLAIMS_SECTION, needle
    # 平文フィールドから拾わない (状態が落ちる)
    assert "平文" in _CLAIMS_SECTION and "`refined_cells`" in _CLAIMS_SECTION
    # 判断要求を ③ が閉じない (1A に回答経路は無い)
    assert "閉じてはならない" in _CLAIMS_SECTION
    # 格子は relative のまま出版される — scope を読めと言う (値だけ拾うと絶対値として報告される)
    assert "`relative_within_sample`" in _CLAIMS_SECTION and "`scope`" in _CLAIMS_SECTION


def test_the_final_report_step_points_at_publishable_values():
    step7 = _SKILL[_SKILL.index("\n7. "): _SKILL.index("## 権限境界")]
    assert "`publishable_values`" in step7 and "`judgment_requests`" in step7


def test_documented_output_keys_exist_in_the_layer_two_output():
    """手順書が名指すキーが ② の出力に実在すること (無いキーを読めという指示は害)。"""
    from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
    from tsumugin.mcp.rietveld_tools import auto_rietveld

    result = AutoRietveldResult(
        stage_results=(StageResult("S0", 9.5, 1.5, 3, True),), final_rwp=9.5, final_gof=1.5,
        refined_cells={"ph": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
    )
    out = auto_rietveld(
        [{"data_path": "d.xra", "instrument_path": "i.prm", "radiation": "xray_lab",
          "geometry": "bragg_brentano"}],
        [{"structure_path": "a.cif", "phase_name": "ph"}],
        runner=lambda inp: result,
    )
    for key in re.findall(r"^\| `([a-z_]+)` \|", _CLAIMS_SECTION, flags=re.M):
        assert key in out, f"手順書の表のキー {key!r} が ② の出力に無い"


def test_documented_state_vocabulary_exists_in_the_type():
    """手順書に書いた determinacy の語彙が型に実在すること (存在しない状態を探させない)。"""
    row = next(line for line in _CLAIMS_SECTION.splitlines() if "`determinacy` (" in line)
    listed = re.findall(r"`([a-z_]+)`", row.split("`determinacy` (", 1)[1].split(")", 1)[0])
    valid = {d.value for d in Determinacy}
    assert listed and set(listed) <= valid, set(listed) - valid


def test_the_csv_tool_is_called_with_its_real_parameters():
    from tsumugin.mcp.rietveld_tools import export_claims_csv

    params = list(inspect.signature(export_claims_csv).parameters)
    assert params == ["gpx_path", "path"]
    assert "`export_claims_csv(gpx_path, path)`" in _CLAIMS_SECTION


def test_the_playbook_carries_the_same_rule():
    assert "`publishable_values`" in _PLAYBOOK
    assert "`export_claims_csv(" in _PLAYBOOK
    assert "平文" in _PLAYBOOK
