"""JSON spec dict → frozen dataclass 設定 の**共有パーサ** (Issue #97 カバレッジ規則④)。

`PhaseIdConfig` (② `sequential_rietveld` の ``phase_id``) と `AnchorConfig`
(② `anchored_sequential` の ``anchor_config``) は、どちらも「③ (JSON しか送れない LLM) が
policy 定数を設定する frozen dataclass」である。本モジュールはその変換の**唯一の実装**とし、
両者が共有する (`_recipe_spec` と同じ規律 — 二重実装を作らない)。

**なぜ明示ホワイトリストをやめたか** (本モジュールを作った直接の理由):
② `sequential_rietveld` は ``PhaseIdConfig`` を

    PhaseIdConfig(elements=..., frac_min=..., rwp_eps=..., top_k=...,
                  hull_cutoff_ev=..., subtract_bg=..., trigger_rwp_ratio=...)

という 7 キーの手書きホワイトリストで組んでいた。① には 19 フィールドあるので、残り 12 は
**③ にとって存在しなかった** (①実装済 + テスト green ≠ ③ が到達できる = Issue #97 の型)。
とりわけ ``wavelength`` は既定が **Cu Kα1 1.5406 Å** なので、放射光/中性子系列は黙って
誤った波長で異方セルプリアラインと候補再スコアを行っていた (例外は出ず「新相同定が効かない」
としか見えない)。**フィールド駆動にすれば、① に足したフィールドは自動的に ② から届く。**

変換規則 (③ の typo と型取り違えを**黙って別の意味にしない**):

- **未知キーは ValueError** (許容一覧つき)。黙って無視すると「設定したのに効かない」= ③ が
  「この knob は効かない」と誤学習する (`_recipe_spec` が潰したのと同型の事故)。
- **bool フィールドは真の bool のみ**。``bool("false") is True`` なので、JSON 文字列
  ``"false"`` を通すと**③ の意図と逆**になる (旧 `AnchorConfig.from_dict` の ``bool(value)``
  が持っていた縮退)。
- **int フィールドは整数のみ** (``40.0`` は許すが ``3.9`` は拒否)。``int(3.9) == 3`` の
  黙った切り捨てを防ぐ。JSON クライアントが int/float を区別しない事情は ``40.0`` 許容で吸収する。
- **非 Optional フィールドの ``null`` は ValueError**。既定へ黙って戻すと「null で無効化した
  つもり」が既定値で動く = 別の解析になる。``float | None`` のフィールドだけ ``null`` を通す。
- **タプル (元素列) は裸の文字列も非文字列要素も ValueError**。``"CaTeO"`` を許すと
  ``("C","a","T","e","O")`` になり、原子番号 ``[19, 25, 26]`` を ``str()`` で通すと
  ``("19","25","26")`` になる — どちらも元素系が丸ごと別物になり、**例外を出さないまま**
  候補が全滅する (③ は「MP に候補が無い」と誤診する)。

呼び出し側 (②) はこの ValueError を ``{"error", "error_type"}`` dict へ縮退させる契約
(CLAUDE.md ② 不変条件: ③ は LLM なので例外は回復不能なハード失敗になる)。

**型の規則 (``check_*``) は往復 spec と共有する。null の扱いだけが違う**:
`PhaseSpec`/`HistogramSpec` (と同じ ② 入力面の `stability`/`search_config`) の ``from_dict`` は
`spec_value`/`spec_required` を通し、**キー欠落と null を既定値 (= 未指定)** として読む。
``to_dict`` 自身が Optional フィールドを null で出し (`free_uiso_labels` の None = 未指定, #189)、
② はそれを ``specs`` として ③ へ返すので、③ が学ぶ null の意味は「未指定」である。旧実装は
``bool(d.get("refine_cell", True))`` で null を ``bool(None) == False`` = **格子凍結**に読み替えて
いた (例外も警告も出ず、格子が初期値のまま出版される)。本モジュールの ``config_from_dict`` が
null を拒むのは、policy 定数で「null で無効化したつもり」を既定値で走らせないための選択である。
"""

from __future__ import annotations

import dataclasses
import numbers
from typing import Callable, Mapping, Sequence, TypeVar

__all__ = [
    "check_bool",
    "check_float",
    "check_int",
    "check_str",
    "check_str_tuple",
    "config_from_dict",
    "spec_required",
    "spec_value",
]

T = TypeVar("T")
D = TypeVar("D")


def _annotation(field: "dataclasses.Field") -> str:
    """フィールドの型注釈を素の文字列に正規化する。

    ``from __future__ import annotations`` によりモジュール内の注釈は文字列化されるが、
    ``x: "float | None"`` のように**元から引用符付き**で書かれた注釈は引用符ごと残る
    (実際に ① で使われている書き方なので、剥がさないと Optional 判定が外れる)。
    """
    return str(field.type).strip().strip("\"'")


def _is_optional(field: "dataclasses.Field") -> bool:
    """``| None`` / ``Optional[...]`` を許す注釈か (``null`` を通してよいフィールドか)。"""
    ann = _annotation(field)
    return "None" in ann or "Optional" in ann


def check_bool(name: str, value: object) -> bool:
    """真の bool のみ。0/1 も拒む (JSON の真偽値は数値と別物)。"""
    if not isinstance(value, bool):
        raise ValueError(
            f"{name} は真偽値 (true/false) である必要があります: {value!r} "
            f"({type(value).__name__})。文字列 \"false\" は Python では真になるため、"
            "黙って逆の意味になるのを防いでいます"
        )
    return value


def check_int(name: str, value: object) -> int:
    """整数のみ (``40.0`` は許すが ``3.9`` は拒否 — ``int(3.9) == 3`` の黙った切り捨てを防ぐ)。"""
    # bool は int のサブクラスなので**先に**弾く (True が 1 になる)。
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(
            f"{name} は整数である必要があります: {value!r} ({type(value).__name__})"
        )
    if not isinstance(value, numbers.Integral) and not float(value).is_integer():
        raise ValueError(
            f"{name} は整数である必要があります: {value!r} "
            "(切り捨てると黙って別の値になるため拒否します)"
        )
    return int(value)


def check_float(name: str, value: object) -> float:
    """数値のみ。bool は拒む (``float(True) == 1.0`` で「1」を黙って作らない)。"""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(
            f"{name} は数値である必要があります: {value!r} ({type(value).__name__})"
        )
    return float(value)


def check_str(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"{name} は文字列である必要があります: {value!r} ({type(value).__name__})"
        )
    return value


def check_str_tuple(
    name: str, value: object, *, item: str = "文字列", why: str = ""
) -> tuple[str, ...]:
    """文字列の**リスト**のみ。裸の文字列も非文字列要素も拒む。

    ``"CaTeO"`` を許すと ``("C","a","T","e","O")`` に、``[19, 25]`` を ``str()`` で通すと
    ``("19","25")`` になる — どちらも指定したものと別の集合になり、例外を出さないまま
    下流が空振りする (元素系なら候補が全滅、原子ラベルなら何も凍結しない)。

    :param item: メッセージに出す要素の名前 (「元素記号」「原子ラベル」等)
    :param why: 要素型違反のメッセージ末尾に足す帰結の説明
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(
            f"{name} は{item}の**リスト**である必要があります: {value!r} "
            f"({type(value).__name__})。裸の文字列は 1 文字ずつに分解され、"
            "指定したものと別の集合になります"
        )
    bad = [v for v in value if not isinstance(v, str)]
    if bad:
        raise ValueError(
            f"{name} の要素は{item}の文字列である必要があります: {bad!r}。"
            "数値や入れ子を str() で黙って文字列化すると別の値になります" + why
        )
    return tuple(value)


def _coerce(name: str, value: object, default: object, field: "dataclasses.Field") -> object:
    """1 フィールド分の値を既定値の型へ強制する (規則はモジュール docstring 参照)。

    :raises ValueError: 型が合わず**黙って別の意味になる**入力のとき
    """
    if value is None:
        if _is_optional(field):
            return None
        raise ValueError(
            f"{name} に null は指定できません (このフィールドは null 非許容です)。"
            f"既定値 ({default!r}) を使うならキー自体を省略してください "
            "— null を既定へ黙って戻すと『無効化したつもり』が既定値で動きます"
        )

    # bool は int のサブクラスなので**先に**判定する (順序を入れ替えると True が 1 になる)。
    if isinstance(default, bool):
        return check_bool(name, value)
    if isinstance(default, int):
        return check_int(name, value)
    if isinstance(default, float):
        return check_float(name, value)
    if isinstance(default, str):
        return check_str(name, value)
    if isinstance(default, tuple):
        # 現状の対象設定 (PhaseIdConfig.elements) は **str タプルのみ**。別の要素型を ① に
        # 足したらここで大声で失敗する (黙って str 化して静かに壊さない)。
        if "str" not in _annotation(field):
            raise ValueError(
                f"{name}: str 以外の要素を持つタプル型 ({_annotation(field)}) は "
                "本パーサが未対応です (_config_spec に要素型の変換規則を足してください)"
            )
        return check_str_tuple(
            name, value, item="元素記号",
            why=" (例 19 → \"19\" は元素記号にならず、例外を出さないまま候補が全滅します)",
        )

    raise ValueError(  # pragma: no cover - 未対応の既定値型 (設定側の追加時に大声で気づく)
        f"{name}: 既定値の型 {type(default).__name__} は本パーサが未対応です"
    )


def spec_value(
    d: Mapping[str, object],
    key: str,
    spec: str,
    default: D,
    check: Callable[[str, object], T],
) -> "T | D":
    """往復 spec の 1 キーを読む: **欠落/null は ``default``**、値があれば ``check`` を通す。

    ``check`` は ``(表示名, 値) -> 値`` で型が合わなければ ValueError (``check_*`` 等)。
    ``[]``/``0``/``""`` は null と別物として ``check`` に渡る (#189: ``[]`` は「凍結」)。
    """
    value = d.get(key)
    if value is None:
        return default
    return check(f"{spec}.{key}", value)


def spec_required(
    d: Mapping[str, object], key: str, spec: str, check: Callable[[str, object], T]
) -> T:
    """既定の無いキー。欠落は KeyError のまま (呼び出し側が「必須キー」へ言い換える契約)、
    null は ValueError (``str(None) == "None"`` を名前やパスとして黙って使わない)。"""
    value = d[key]
    if value is None:
        raise ValueError(f"{spec}.{key} に null は指定できません (必須・既定値なし)")
    return check(f"{spec}.{key}", value)


def config_from_dict(cls: "type[T]", data: Mapping[str, object], *, spec_name: str) -> T:
    """JSON 由来 dict から frozen dataclass 設定 ``cls`` を構成する (② の JSON 経路の唯一の入口)。

    **フィールド駆動** (`dataclasses.fields`) なので、① に足したフィールドは追加の配線なしに
    ② から到達可能になる — 手書きホワイトリストが構造的に生む「①にあるのに③から呼べない」
    (Issue #97) を再発させないための設計である。

    :param cls: 全フィールドに既定値を持つ frozen dataclass (`PhaseIdConfig`/`AnchorConfig`)
    :param data: ③ から届いた JSON dict (空なら全既定)
    :param spec_name: エラーメッセージに出す spec 名 (``"phase_id"`` / ``"anchor_config"``)
    :raises ValueError: ``data`` が dict でない・未知キーを含む・値の型が不正なとき
    """
    if not isinstance(data, Mapping):
        raise ValueError(
            f"{spec_name} は dict である必要があります: {type(data).__name__}"
        )
    fields = {f.name: f for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    unknown = set(data) - set(fields)
    if unknown:
        raise ValueError(
            f"unknown {spec_name} keys: {sorted(unknown)} (known: {sorted(fields)})"
        )
    defaults = cls()  # type: ignore[call-arg]
    kwargs: dict[str, object] = {}
    for name, value in data.items():
        field = fields[name]
        kwargs[name] = _coerce(
            f"{spec_name}.{name}", value, getattr(defaults, name), field
        )
    return cls(**kwargs)  # type: ignore[arg-type]
