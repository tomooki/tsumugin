"""テンプレートの入力宣言と範囲 (proposal §4.1・§3.5・§2, REQ-FTJ-1B-201〜203)。

宣言は fit の設定を変えるが、**検出器を黙らせず、判断要求も閉じない** (principles §1.4)。宣言に依存した値は
``provenance`` に ``declared(<キー>)`` を持つ。② は LLM と人を区別できないので、宣言は
``actor = caller_unverified`` として ledger に記録する。

宣言しないことは「宣言なし」で、各項目の既定は proposal §4.1 の表 (例: 内部標準が無ければ格子は
``relative_within_sample``)。外部背景・偏光・参照構造の温度の宣言は受け口を作らない — 作って何もしないと
「宣言したのに効かない」になる (設計 §9)。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Mapping, Sequence

from .._config_spec import check_bool, check_str, spec_value
from ..errors import TsumuginError

__all__ = [
    "TEMPLATE_SCOPE",
    "TemplateDeclarations",
    "TemplateScopeError",
    "check_template_scope",
    "record_declarations",
]

#: 第 1 期の範囲 (proposal §2)。③ への説明と error dict の文言に使う。
TEMPLATE_SCOPE = "CW X 線 (実験室・放射光)・ヒストグラム 1 本・GSAS-II"


class TemplateScopeError(TsumuginError, ValueError):
    """テンプレートを範囲外の入力に要求された (② は呼び出し全体を error dict にする)。"""


@dataclass(frozen=True)
class TemplateDeclarations:
    """呼び手の宣言 (すべて None = 宣言なし)。

    :param instrument_calibrated: 装置関数 (U,V,W,X,Y・非対称) が標準試料由来か。真なら幅は試料広がり
        (Size/Mustrain) として読み、装置の幅は解放しない
    :param internal_standard: 同一試料内の内部標準の相名。あれば格子は ``scope = absolute``
    :param target_phase: 対象相の宣言。宣言しても積分強度の比較は回り、僅差なら判断要求が出る
    :param zero_calibrated: 装置ファイルの Zero が較正値か (Bragg-Brentano で Zero を装置値に固定する根拠)
    """

    instrument_calibrated: "bool | None" = None
    internal_standard: "str | None" = None
    target_phase: "str | None" = None
    zero_calibrated: "bool | None" = None

    @classmethod
    def from_dict(cls, data: "Mapping[str, object] | None") -> "TemplateDeclarations":
        """JSON の宣言から作る (未知キー・型違いは ValueError — 綴り違いの宣言を黙って捨てない)。"""
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ValueError(f"template は dict である必要があります: {type(data).__name__}")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"template に未知のキーがあります: {unknown} (既知: {sorted(known)})")
        s = "template"
        return cls(
            instrument_calibrated=spec_value(data, "instrument_calibrated", s, None, check_bool),
            internal_standard=spec_value(data, "internal_standard", s, None, check_str),
            target_phase=spec_value(data, "target_phase", s, None, check_str),
            zero_calibrated=spec_value(data, "zero_calibrated", s, None, check_bool),
        )

    def to_dict(self) -> dict[str, object]:
        """宣言したキーだけ (None は宣言なしなので載せない)。"""
        return {k: v for k, v in asdict(self).items() if v is not None}

    def declared_ids(self) -> tuple[str, ...]:
        """宣言の id (= キー)。``provenance`` の ``declared(<id>)`` に使う。"""
        return tuple(f.name for f in fields(self) if getattr(self, f.name) is not None)

    def check_phases(self, phases: Sequence[object]) -> None:
        """相名を名指す宣言が相に実在するか (:raises ValueError:)。"""
        known = {getattr(p, "phase_name", None) for p in phases}
        for key in ("target_phase", "internal_standard"):
            name = getattr(self, key)
            if name is not None and name not in known:
                raise ValueError(
                    f"template.{key} の相 {name!r} が相の一覧にありません: {sorted(map(str, known))}"
                )


def check_template_scope(
    histograms: Sequence[object], phases: Sequence[object], *, backend: str = "gsasii"
) -> None:
    """第 1 期の範囲かを**精密化の前に**確かめる (:raises TemplateScopeError:)。

    範囲外のデータで黙って回すと、手順が想定していない幅・オフセットの扱いで「テンプレートの結果」が出る。
    """
    reasons: list[str] = []
    if backend != "gsasii":
        reasons.append(f"バックエンドが {backend!r} (GSAS-II のみ)")
    if len(histograms) != 1:
        reasons.append(f"ヒストグラムが {len(histograms)} 本 (1 本のみ — joint は範囲外)")
    for h in histograms:
        rad = getattr(h, "radiation", None)
        if rad is None or not getattr(rad, "is_xray", False):
            reasons.append(f"放射源が {getattr(rad, 'value', rad)!r} (CW X 線のみ)")
    if not phases:
        reasons.append("相がありません")
    if reasons:
        raise TemplateScopeError(
            "テンプレートの範囲外です: " + " / ".join(reasons) + f"。範囲: {TEMPLATE_SCOPE}"
        )


def record_declarations(ledger: object, declarations: TemplateDeclarations) -> None:
    """宣言を ledger に記録する (② は呼び手を検証できない = ``caller_unverified``)。"""
    ledger.append(  # type: ignore[attr-defined]
        "template_declaration",
        {"actor": "caller_unverified", "declarations": declarations.to_dict()},
    )
