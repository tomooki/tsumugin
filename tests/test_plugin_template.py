"""fit-then-judge P1-1B タスク 11: ③ の手順書のテンプレート・初期値プローブ節のガード (REQ-FTJ-1B-702)。

skill は「③ への実行可能な指示」なので、誤った指示は実装バグと同等に有害 (CLAUDE.md)。手順書に書いた
候補名・宣言のキー・出力キー・判断要求の種類・プローブのキーが ② と ① に実在すること、使えない範囲と
「閉じない」「再利用しない」が消えないことを固定する。
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SKILL = (_ROOT / "plugins/tsumugin/skills/analyze/SKILL.md").read_text(encoding="utf-8")
_PLAYBOOK = (_ROOT / "docs/tasks/m7-real-data-validation/AGENT_PLAYBOOK.md").read_text(
    encoding="utf-8"
)


def _section(text: str, heading_prefix: str) -> str:
    start = text.index(heading_prefix)
    nxt = text.find("\n## ", start + 1)
    return text[start: nxt if nxt != -1 else len(text)]


_TEMPLATE = _section(_SKILL, "## テンプレートを候補に加える")
_PROBE = _section(_SKILL, "## 初期値プローブ")


def test_the_candidate_name_exists_and_is_not_a_default():
    from tsumugin.autorietveld.search import CANDIDATE_NAMES, DEFAULT_CANDIDATES

    assert '"template"' in _TEMPLATE
    assert "template" in CANDIDATE_NAMES and "template" not in DEFAULT_CANDIDATES
    assert "既定の集合" in _TEMPLATE  # 既定に入っていないことを言う


def test_documented_declaration_keys_are_the_real_ones():
    from tsumugin.template.declarations import TemplateDeclarations

    rows = re.findall(r"^\| `([a-z_]+)` \|", _TEMPLATE, flags=re.M)
    real = {f.name for f in fields(TemplateDeclarations)}
    assert rows and set(rows) == real, (set(rows), real)


def test_the_scope_limits_and_the_error_type_are_stated():
    from tsumugin.template.declarations import TemplateScopeError

    assert f"`error_type: \"{TemplateScopeError.__name__}\"`" in _TEMPLATE
    for word in ("中性子", "joint", "topas", "operando"):
        assert word in _TEMPLATE, word


def test_documented_output_keys_exist_in_the_layer_two_output():
    """手順書が読めと言うキーが ② の出力に実在する (無いキーを読ませない)。"""
    import numpy as np

    from tsumugin.autorietveld.model import (
        AutoRietveldResult,
        PhaseSpec,
        StageResult,
        ValidityReport,
    )
    from tsumugin.mcp.rietveld_tools import auto_rietveld

    def res(stages, phases):
        out = tuple(StageResult(s.label, 9.0, 1.1, 5 + i, True) for i, s in enumerate(stages))
        out = out or (StageResult("S0", 9.0, 1.1, 5, True),)
        return AutoRietveldResult(
            stage_results=out, final_rwp=9.0, final_gof=1.1, refined_cells={},
            validity=ValidityReport(passed=True), n_obs=500,
            residual_intensity=tuple(np.random.default_rng(0).standard_normal(100)),
            residual_sigma=(1.0,) * 100,
            atom_uiso={p.phase_name: {"X1": 0.01} for p in phases},
            phase_integrated_intensity={p.phase_name: (1.0,) for p in phases},
        )

    phases = [{"structure_path": "a.cif", "phase_name": "A"}]
    out = auto_rietveld(
        [{"data_path": "d.xye", "instrument_path": "i.prm", "radiation": "xray_lab",
          "geometry": "bragg_brentano"}],
        phases, search=["template"], template={}, save_gpx=False, initial_value_probe={},
        search_runner=lambda c: res(c.stages, c.phases or [PhaseSpec("a.cif", "A")]),
        template_pass1_runner=lambda t, h, p, s: res(s, p),
    )
    assert "error" not in out, out
    for key in ("template_version", "template_derivation", "initial_value_probe"):
        assert f"`{key}`" in _SKILL, key
        assert key in out, key
    for key in ("cell", "target_phase", "background", "zero_offset", "uiso", "effective_dof"):
        assert f"`{key}`" in _TEMPLATE, key
        assert key in out["template_derivation"]["evidence"], key
    for key in ("complete", "rwp", "errors", "reason"):
        assert f"`{key}`" in _PROBE and key in out["initial_value_probe"], key


def test_documented_request_kinds_are_issued_by_the_code():
    import inspect

    from tsumugin.claims import requests

    src = inspect.getsource(requests.template_adjustments)
    for kind in ("target_phase_ambiguous", "zero_offset_significant"):
        assert f"`{kind}`" in _TEMPLATE and f'"{kind}"' in src, kind
    assert "閉じてはならない" in _TEMPLATE


def test_compiled_phases_must_not_be_fed_back():
    assert "`refine_with_revisions`" in _TEMPLATE and "渡せない" in _TEMPLATE
    assert "元の phases" in _TEMPLATE


def test_documented_probe_keys_are_the_real_ones():
    from tsumugin.autorietveld.probe import ProbeConfig

    keys = set(re.findall(r'"([a-z_]+)": [0-9.]+', _PROBE))
    assert keys and keys <= {f.name for f in fields(ProbeConfig)}, keys
    assert "`locally_stable`" in _PROBE and "`save_gpx: false`" in _PROBE


def test_the_playbook_carries_the_same_rules():
    for needle in ('"template"', "TemplateScopeError", "`template_derivation`",
                   "`target_phase_ambiguous`", "`refine_with_revisions` に渡せない",
                   "`initial_value_probe", "`locally_stable`"):
        assert needle in _PLAYBOOK, needle
