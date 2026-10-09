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
    "background_values_from_out",
    "limit_hits_from_out",
    "named_refined_values_from_out",
    "parse_out_metrics",
    "parse_records",
    "refined_values_from_out",
    "spherical_harmonics_blocks_from_out",
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


#: ``.out`` の精密化値: ``name 8.47`_0.0001`` / マクロ引数の ``name,-0.0019`_0.0025`` /
#: ``do_errors`` が無いときの ``name 8.47``` (esd 無しでもバッククォートは付く, 実測)。
#: **バッククォートが「精密化された値」の印** — 固定値 (``!name 0.0``) とキーワード
#: (``lo 1.5405``) には付かないので、名前の取り違えで値を持ち越すことがない。
#: 名前と値は同じ行にある (行を跨いで組にしない)。
_NAMED_REFINED = re.compile(rf"(?<![\w!@.])([A-Za-z_]\w*)[ \t]*,?[ \t]*({_NUM})`")

#: 値がパラメータではなく**報告値**のマクロ。``MVW(m, v, name w)`` の ``w`` は TOPAS が
#: 計算して書き戻す重量分率で、入力値は使われない。持ち越し対象から外す。
_REPORTED_MACRO = re.compile(r"\bMVW\s*\([^)]*\)")

_BKG_LINE = re.compile(r"(?m)^[ \t]*bkg\b(.*)$")
_ESD_SUFFIX = re.compile(r"`\S*")
_PO_BLOCK = re.compile(
    r"PO_Spherical_Harmonics\(\s*(\w+)\s*,\s*(\d+)\s+load\s+sh_Cij_prm\s*\{(.*?)\}\s*\)",
    re.DOTALL,
)


def _parameter_text(out_text: str) -> str:
    """``.out`` のうちパラメータが書かれた部分 (末尾の相関行列 ``C_matrix_normalized`` を除く)。"""
    head, _, _ = out_text.partition("C_matrix_normalized")
    return head


def named_refined_values_from_out(out_text: str) -> dict[str, float]:
    """名前付きパラメータの精密化値 (名前 → 値) を返す (#218: 次段への持ち越し用)。

    **精密化されたもの (値にバッククォートが付くもの) だけ**を拾う。固定値は INP に書いた
    値のままなので持ち越す必要が無い。報告値 (``MVW``) は除く。有限でない値は拾わない
    (発散した値を次段の出発点にしない)。
    """
    text = _REPORTED_MACRO.sub("", _parameter_text(out_text))
    values: dict[str, float] = {}
    for name, token in _NAMED_REFINED.findall(text):
        value = _to_float(token)
        if value is not None:
            values[name] = value
    return values


def background_values_from_out(out_text: str) -> "list[tuple[float, ...] | None]":
    """``bkg`` 行ごとの係数を**出現順**に返す (#218)。

    ``bkg`` の係数は名前を付けられない (実測: ``bkg b0 0 …`` は異常終了) ので、
    名前でなく行と位置で持ち越す。数値以外の字句を含む行は位置の対応が取れないので
    ``None`` を返す (取り違えて別の係数へ入れるより、持ち越さない方が安全)。
    """
    rows: "list[tuple[float, ...] | None]" = []
    for match in _BKG_LINE.finditer(_parameter_text(out_text)):
        tokens = _ESD_SUFFIX.sub("", match.group(1)).replace("@", " ").split()
        values = [_to_float(token) for token in tokens]
        if not values or any(value is None for value in values):
            rows.append(None)
            continue
        rows.append(tuple(value for value in values if value is not None))
    return rows


def spherical_harmonics_blocks_from_out(out_text: str) -> dict[str, str]:
    """球面調和の選択配向を**係数を展開した 1 行**で返す (名前 → INP 行, #218)。

    INP の ``PO_Spherical_Harmonics(name, 4)`` は精密化後
    ``PO_Spherical_Harmonics(name, 4 load sh_Cij_prm { y00 !name_c00 1 y20 name_c20 -0.066`_0.005 … } )``
    へ書き戻される (係数は TOPAS が空間群から決める)。短い形のまま次段に描くと係数が 0 から
    解き直しになるので、この形を次段の行にする。esd は落とし空白を詰める (1 行の形は
    実 tc.exe が受理することを確認済み)。
    """
    blocks: dict[str, str] = {}
    for name, order, body in _PO_BLOCK.findall(_parameter_text(out_text)):
        coefficients = " ".join(_ESD_SUFFIX.sub("", body).split())
        blocks[name] = (
            f"PO_Spherical_Harmonics({name}, {order} load sh_Cij_prm {{ {coefficients} }} )"
        )
    return blocks


def limit_hits_from_out(out_text: str) -> tuple[str, ...]:
    """境界に張り付いたパラメータの ``LIMIT_MIN_…``/``LIMIT_MAX_…`` を返す。

    GSAS 経路の ``detect_bound_hits`` と同じ役割: 境界張り付きは「収束した」ように見えて
    実際には拘束が効いているだけなので、診断として上げる。
    """
    return tuple(_LIMIT.findall(out_text))
