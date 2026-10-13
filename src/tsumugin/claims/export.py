"""出版状態の列を持つ CSV (fit-then-judge P1-1A, REQ-FTJ-1A-503)。

**状態を落とす変換の禁止** (principles §4.4): 型は最終出力まで届いて初めて機能する。CSV で素の float に
潰れたら、表という一番使われる場所でだけ保証が消える。そこで:

- 全行が状態の列 (``publishable``・``determinacy``・``provenance``・``scope``・``checks``・``gate``) を持つ
- 出版不可の行も**消さずに書く** (消すと「その値は無かった」と読まれる) — 状態の列で示す
- 入力は `Claim` の dict (② の ``claims`` そのもの) で、`Claim.from_dict` を通す (素の数値は拒否)
- 既存ファイルは上書きしない (``x`` モード)
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping

from .model import Claim

__all__ = ["CSV_COLUMNS", "write_claims_csv"]

CSV_COLUMNS: tuple[str, ...] = (
    "key", "param_class", "phase", "label", "axis", "value", "esd", "unit",
    "publishable", "determinacy", "provenance", "scope", "checks", "gate",
)


def _cell(value: Any) -> str:
    return "" if value is None else repr(value) if isinstance(value, float) else str(value)


def _text(value: str) -> str:
    """表計算ソフトが数式と読む先頭 (``= + - @`` とタブ・CR) を無害化する (CSV injection 対策)。

    相名・原子ラベルは CIF や ③ の spec から来るので、数式として実行させない。数値の列には使わない。
    """
    if value and value[0] in "=+-@\t\r":
        return "'" + value
    return value


def write_claims_csv(claims: Mapping[str, Mapping[str, Any] | Claim], path: str | Path) -> Path:
    """`Claim` (または `Claim.to_dict()` の dict) の表を CSV に書く。書いたパスを返す。

    :raises FileExistsError: 既にファイルがある (上書きしない)
    :raises TypeError/ValueError/KeyError: 状態を持たない値が混じっている
    """
    rows = []
    for key in sorted(claims):
        raw = claims[key]
        claim = raw if isinstance(raw, Claim) else Claim.from_dict(raw)
        rows.append({
            "key": _text(claim.key),
            "param_class": claim.param_class,
            "phase": _text(_cell(claim.phase)),
            "label": _text(_cell(claim.label)),
            "axis": _cell(claim.axis),
            "value": _cell(claim.value),
            "esd": _cell(claim.esd),
            "unit": claim.unit,
            "publishable": "true" if claim.publishable else "false",
            "determinacy": claim.determinacy.value,
            "provenance": ";".join(sorted(claim.provenance)),
            "scope": claim.scope.value,
            "checks": ";".join(f"{k}={v.value}" for k, v in sorted(claim.checks.items())),
            "gate": ";".join(sorted(claim.gate)),
        })
    out = Path(path)
    with out.open("x", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return out
