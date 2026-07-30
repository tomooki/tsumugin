"""TOPAS 出力のパース (M12 T5) — 純関数。

一次のパース対象は ``out "results.txt"`` + ``Out(...)`` が吐く**タブ区切りレコード**である。
T0 実測で、これが最も決定論的な出力経路であることを確認した (書式をこちらで指定できるため)。
``.out`` は「精密化後の INP そのもの」なので INP 構文のパースが要り脆いが、1 行目の指標
(``r_p/r_wp/r_exp/gof``) と ``value`_esd`` 記法の回収には使える。

レコード書式 (INP 側で生成する形):

- スカラー: ``r_wp<TAB>12.297``
- 1 段キー: ``wt_frac<TAB>PbSO4<TAB>94.96<TAB>0.08`` (値, esd)
- 2 段キー: ``cell<TAB>PbSO4<TAB>a<TAB>8.4799<TAB>0.000098`` → ``keyed["cell"]["PbSO4/a"]``
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

__all__ = [
    "TopasRecords",
    "limit_hits_from_out",
    "parse_out_metrics",
    "parse_records",
    "refined_values_from_out",
]

_METRIC_KEYS = ("r_p", "r_wp", "r_exp", "gof", "r_wp_dash", "r_exp_dash")

# TOPAS の精密化後表記: ``8.479896`_0.000098`` / ``8.37e-06`_5.2e-07`` /
# ``443.12`_540.51_LIMIT_MIN_0.3``。esd の後ろに _LIMIT_… が続くことがある。
_NUM = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
_REFINED = re.compile(rf"({_NUM})`_({_NUM})")
_LIMIT = re.compile(r"_(LIMIT_(?:MIN|MAX)_[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")


def _to_float(token: str) -> "float | None":
    """有限の float だけを返す。**NaN/inf は None** — 発散を「値がある」と誤読しない。"""
    try:
        value = float(token)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


@dataclass(frozen=True)
class TopasRecords:
    """``results.txt`` のパース結果。"""

    scalars: dict[str, float] = field(default_factory=dict)
    keyed: dict[str, dict[str, "tuple[float, float | None]"]] = field(default_factory=dict)


def parse_records(text: str) -> TopasRecords:
    """タブ区切りレコードを構造化する。**壊れた行は黙って飛ばす**。

    部分的な出力でも段の受理/revert 判定はできるので、1 行の破損で全体を落とさない。
    (ただし「値が無い」ことは呼び出し側が検出できる — 欠けたキーは dict に現れない。)
    """
    scalars: dict[str, float] = {}
    keyed: dict[str, dict[str, "tuple[float, float | None]"]] = {}
    for raw in text.splitlines():
        parts = [p for p in raw.strip().split("\t") if p != ""]
        if len(parts) < 2:
            continue
        name, rest = parts[0], parts[1:]
        if len(rest) == 1:
            value = _to_float(rest[0])
            if value is not None:
                scalars[name] = value
            continue
        # 末尾の数値列を (値, esd) とみなし、その手前をキーとする。
        numeric_tail: list[float] = []
        while rest and (parsed := _to_float(rest[-1])) is not None:
            numeric_tail.insert(0, parsed)
            rest = rest[:-1]
        if not rest or not numeric_tail:
            continue
        key = "/".join(rest)
        esd = numeric_tail[1] if len(numeric_tail) > 1 else None
        keyed.setdefault(name, {})[key] = (numeric_tail[0], esd)
    return TopasRecords(scalars=scalars, keyed=keyed)


def parse_out_metrics(out_text: str) -> dict[str, float]:
    """``.out`` の先頭に書き戻される指標 (``r_p/r_wp/r_exp/gof`` …) を拾う。

    **総合指標についてはこちらが一次**である。``results.txt`` の ``Out(Get(r_wp))`` は
    それが書かれた ``xdd`` ブロックの値でしかなく、``out "file"`` は先頭 xdd にしか置けない
    ため (append 無しだと後続が先行レコードを消す)、joint では**第 1 ヒストグラムの値を総合値と
    名乗る**ことになる (実 PbSO4 joint で 8.635 対 10.772)。単一ヒストグラムでは両者が一致する。

    ``.out`` は「精密化後の INP そのもの」なので INP 構文のパースが要り脆い — だから
    **拾うのは先頭数行の指標だけ**に留め、パラメータ値は ``results.txt`` の書式指定済み
    レコードから採る (`parse_records`)。優先順位の実装は `engine._metrics`。
    """
    metrics: dict[str, float] = {}
    head = "\n".join(out_text.splitlines()[:5])
    for key in _METRIC_KEYS:
        match = re.search(rf"(?:^|\s){re.escape(key)}\s+({_NUM})", head)
        if match:
            value = _to_float(match.group(1))
            if value is not None:
                metrics[key] = value
    return metrics


def refined_values_from_out(out_text: str) -> "list[tuple[float, float]]":
    """``value`_esd`` 記法の (値, esd) を出現順に返す。

    精密化されなかった値は本記法を持たないため拾わない (= 解放したものだけが並ぶ)。
    """
    return [
        (float(value), float(esd))
        for value, esd in _REFINED.findall(out_text)
        if math.isfinite(float(value)) and math.isfinite(float(esd))
    ]


def limit_hits_from_out(out_text: str) -> tuple[str, ...]:
    """境界に張り付いたパラメータの ``LIMIT_MIN_…``/``LIMIT_MAX_…`` を返す。

    GSAS 経路の ``detect_bound_hits`` と同じ役割: 境界張り付きは「収束した」ように見えて
    実際には拘束が効いているだけなので、診断として上げる。
    """
    return tuple(_LIMIT.findall(out_text))
