"""fit-then-judge P1c タスク 2: ③ の手順書が MEM の `input_publication` の読み方を書いているかのガード。"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SKILL = (_ROOT / "plugins/tsumugin/skills/mem-model-fix/SKILL.md").read_text(encoding="utf-8")
_PLAYBOOK = (_ROOT / "docs/tasks/m7-real-data-validation/AGENT_PLAYBOOK.md").read_text(
    encoding="utf-8"
)


def _section(text: str, prefix: str) -> str:
    start = text.index(prefix)
    nxt = text.find("\n## ", start + 1)
    return text[start: nxt if nxt != -1 else len(text)]


_SEC = _section(_SKILL, "## 入力の出版状態を読む")


def test_the_documented_keys_exist_in_the_layer_two_output():
    """手順書が読めと言うキー・値が ② の出力に実在する。"""
    import inspect

    from tsumugin.claims.publication import input_publication
    from tsumugin.mcp import mem_tools

    unknown = input_publication("")
    for key in ("state", "structure_held", "blocking_requests"):
        assert f"`{key}" in _SEC and key in unknown, key
    assert '`state: "unknown"`' in _SEC and unknown["state"] == "unknown"
    assert '`state: "known"`' in _SEC
    for tool in ("mem_density", "mem_rietveld_iterate"):
        assert f"`{tool}`" in _SEC
        assert '"input_publication"' in inspect.getsource(getattr(mem_tools, tool))
    assert '`publication_state: "unknown"`' in _SEC
    assert '"publication_state": "unknown"' in inspect.getsource(mem_tools.mem_rietveld_iterate)


def test_the_rule_not_to_publish_density_conclusions_is_stated():
    assert "出版値として報告しない" in _SEC
    assert "`publishable_values`" in _SEC


def test_the_playbook_carries_the_same_rule():
    assert "`input_publication`" in _PLAYBOOK and "出版値として報告しない" in _PLAYBOOK
