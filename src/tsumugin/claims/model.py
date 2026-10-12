"""`Claim` — 値 1 つの出版状態を軸ごとの直積で持つ型 (fit-then-judge 決定 1A)。

設計: ``docs/design/fit-then-judge/proposal.md`` §3.1 と ``p1-1a-architecture.md``。
principles §3 の ``Claim = (value, evidence, scope, refuter)`` を 1 種類だけ使い、出版状態は
`determinacy`・`provenance`・`correlations`・`scope`・`checks`・`gate`・`witnesses` の軸に分けて持つ。

**`publishable` は保存せず導出する** — 保存すると、軸を更新したときに古い判定が残る。
導出規則: 止め (`gate`) が空 ∧ 決定性が `esd_only` 以上 ∧ 値がある ∧ 出自が「精密化した/対称性で
決まる/原点固定」のいずれかを含む ∧ **型が決める必須検査**がすべて `pass`。走らせていない必須検査は
`unevaluated` と同じに扱う (黙って pass にしない)。

stdlib のみの leaf モジュール (どこからでも import できる)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

__all__ = [
    "DETERMINACY_ORDER",
    "PARAM_CLASSES",
    "Check",
    "Claim",
    "Determinacy",
    "Scope",
    "Witness",
    "compose",
    "required_checks_for",
    "weaker_determinacy",
    "worse_check",
]


class Determinacy(str, Enum):
    """値がどれだけ決まっているか。`DETERMINACY_ORDER` の左ほど強い。"""

    #: 対称性で厳密に決まる (例: 特殊位置の座標、立方晶の α)
    EXACT = "exact"
    #: 証人がある (1A では収束確認の全開始点が kσ 以内で一致)
    DETERMINED = "determined"
    #: 初期値プローブ (±δ) で戻った (1B)
    LOCALLY_STABLE = "locally_stable"
    #: esd>0 だけ — 証人の無い基底状態
    ESD_ONLY = "esd_only"
    #: esd ≥ |値| (決まらなかった) / 剪定で凍結した
    UNDETERMINED_ESD = "undetermined_esd"
    #: 開始点間で kσ を超えて割れた
    INITIAL_VALUE_DEPENDENT = "initial_value_dependent"
    #: 最終段が収束していない
    UNCONVERGED = "unconverged"
    #: 縮退方向の証人付きで決定不能 (principles §3.1)
    UNDETERMINABLE = "undeterminable"


#: 強い順。合成は**弱い方** (この並びで右の方) をとる。
DETERMINACY_ORDER: tuple[Determinacy, ...] = tuple(Determinacy)
_RANK = {d: i for i, d in enumerate(DETERMINACY_ORDER)}

#: 証人が無ければ付けてはならないラベル (REQ-FTJ-1A-105)。
_WITNESS_REQUIRED = frozenset({Determinacy.DETERMINED, Determinacy.UNDETERMINABLE})


def weaker_determinacy(a: Determinacy, b: Determinacy) -> Determinacy:
    """2 つの決定性の弱い方。"""
    return a if _RANK[a] >= _RANK[b] else b


class Check(str, Enum):
    """検査 1 つの結果。悪い順に `fail` > `unevaluated` > `pass`。"""

    PASS = "pass"
    UNEVALUATED = "unevaluated"
    FAIL = "fail"


_CHECK_SEVERITY = {Check.PASS: 0, Check.UNEVALUATED: 1, Check.FAIL: 2}


def worse_check(a: Check, b: Check) -> Check:
    """2 つの検査結果の悪い方。"""
    return a if _CHECK_SEVERITY[a] >= _CHECK_SEVERITY[b] else b


class Scope(str, Enum):
    """値が有効な範囲。"""

    ABSOLUTE = "absolute"
    #: 同一試料・同一測定内の比・差にだけ有効 (例: 内部標準なしの格子)
    RELATIVE_WITHIN_SAMPLE = "relative_within_sample"


def _weaker_scope(a: Scope, b: Scope) -> Scope:
    return Scope.RELATIVE_WITHIN_SAMPLE if Scope.RELATIVE_WITHIN_SAMPLE in (a, b) else a


#: 値の種類 (`autorietveld.agreement` の比較クラスと同じ語彙)。
PARAM_CLASSES: tuple[str, ...] = (
    "cell", "coord", "uiso", "occupancy", "weight_fraction", "microstructure", "profile",
)

#: どの値にも必須の検査。
_COMMON_REQUIRED = frozenset({"phase_set_completeness", "provenance_known"})
#: 構造の値に足す必須検査 (その相の結晶化学)。
_STRUCTURE_REQUIRED = frozenset({"crystal_chemistry"})
_REQUIRED: Mapping[str, frozenset[str]] = MappingProxyType({
    "cell": _COMMON_REQUIRED,
    "coord": _COMMON_REQUIRED | _STRUCTURE_REQUIRED,
    "uiso": _COMMON_REQUIRED | _STRUCTURE_REQUIRED,
    "occupancy": _COMMON_REQUIRED | _STRUCTURE_REQUIRED,
    "weight_fraction": _COMMON_REQUIRED,
    "microstructure": _COMMON_REQUIRED,
    "profile": _COMMON_REQUIRED,
})


def required_checks_for(param_class: str) -> frozenset[str]:
    """値の種類ごとの必須検査。**型が決める** — 呼び手に渡させると、検査を減らして出版できてしまう。"""
    try:
        return _REQUIRED[param_class]
    except KeyError:
        raise ValueError(f"未知の値の種類です: {param_class!r} (既知: {PARAM_CLASSES})") from None


#: 出自の語彙。`declared:<id>` と `policy_default:<版>` は id/版付きでのみ許す。
_PROVENANCE_ATOMS = frozenset({"refined", "input", "symmetry", "origin_fix", "pruned"})
_PROVENANCE_PREFIXES = ("declared:", "policy_default:")
#: これらのどれかを含まない値は出版しない (入力値・出自不明)。
_PUBLISHABLE_ORIGINS = frozenset({"refined", "symmetry", "origin_fix"})


def _check_provenance(atoms: frozenset[str]) -> None:
    for atom in atoms:
        ok = atom in _PROVENANCE_ATOMS or any(
            atom.startswith(p) and len(atom) > len(p) for p in _PROVENANCE_PREFIXES
        )
        if not ok:
            raise ValueError(
                f"未知の provenance です: {atom!r} (既知: {sorted(_PROVENANCE_ATOMS)} と "
                f"{list(_PROVENANCE_PREFIXES)} + id)"
            )


def _json_value(value: Any) -> Any:
    """証人の中身を JSON 安全な形にそろえる (タプル → リスト、非有限 → None)。"""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


@dataclass(frozen=True)
class Witness:
    """強いラベル・閉じた判断要求の根拠。`kind` は証人の種類、`detail` は JSON 安全な中身。"""

    kind: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("witness の kind が空です")
        object.__setattr__(self, "detail", MappingProxyType(_json_value(dict(self.detail))))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Witness)
            and self.kind == other.kind
            and dict(self.detail) == dict(other.detail)
        )

    def __hash__(self) -> int:
        return hash((self.kind, repr(sorted(self.detail.items()))))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": dict(self.detail)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Witness":
        return cls(kind=str(d["kind"]), detail=dict(d.get("detail") or {}))


def _finite_or_none(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} は有限値か None にしてください (受け取った値: {value!r})")
    return v


@dataclass(frozen=True)
class Claim:
    """値 1 つとその出版状態。

    :param key: ``"<class>:<比較キー>"`` (例 ``"cell:PbSO4.a"``)。比較キーは
        `autorietveld.agreement` が開始点の比較に使う文字列と同じ
    :param checks: 検査名 → 結果。必須検査 (`required_checks_for`) が欠けていれば出版しない
    :param gate: 出版を止めている判断要求の id の集合
    :param witnesses: `determined`/`undeterminable` と閉じた判断要求の根拠
    """

    key: str
    param_class: str
    value: float | None
    esd: float | None
    unit: str
    phase: str | None = None
    label: str | None = None
    axis: str | None = None
    determinacy: Determinacy = Determinacy.ESD_ONLY
    provenance: frozenset[str] = frozenset()
    correlations: frozenset[str] = frozenset()
    scope: Scope = Scope.ABSOLUTE
    checks: Mapping[str, Check] = field(default_factory=dict)
    gate: frozenset[str] = frozenset()
    witnesses: tuple[Witness, ...] = ()

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("Claim の key が空です")
        required_checks_for(self.param_class)  # 未知の種類を拒否
        object.__setattr__(self, "value", _finite_or_none("value", self.value))
        object.__setattr__(self, "esd", _finite_or_none("esd", self.esd))
        object.__setattr__(self, "determinacy", Determinacy(self.determinacy))
        object.__setattr__(self, "scope", Scope(self.scope))
        object.__setattr__(self, "provenance", frozenset(self.provenance))
        object.__setattr__(self, "correlations", frozenset(self.correlations))
        object.__setattr__(self, "gate", frozenset(self.gate))
        object.__setattr__(self, "witnesses", tuple(self.witnesses))
        object.__setattr__(
            self, "checks",
            MappingProxyType({str(k): Check(v) for k, v in dict(self.checks).items()}),
        )
        _check_provenance(self.provenance)
        if self.determinacy in _WITNESS_REQUIRED and not self.witnesses:
            raise ValueError(
                f"{self.key}: `{self.determinacy.value}` は証人 (witness) があるときだけ付けられます"
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Claim):
            return NotImplemented
        return all(
            (dict(getattr(self, f.name)) == dict(getattr(other, f.name)))
            if f.name == "checks" else getattr(self, f.name) == getattr(other, f.name)
            for f in fields(self)
        )

    __hash__ = None  # type: ignore[assignment]  — checks が Mapping なのでハッシュしない

    # -- 導出 ---------------------------------------------------------------

    @property
    def required_checks(self) -> frozenset[str]:
        return required_checks_for(self.param_class)

    @property
    def publishable(self) -> bool:
        """出版してよいか (保存しない — 毎回軸から導く)。"""
        return (
            not self.gate
            and self.value is not None
            and _RANK[self.determinacy] <= _RANK[Determinacy.ESD_ONLY]
            and bool(self.provenance & _PUBLISHABLE_ORIGINS)
            and all(
                self.checks.get(name, Check.UNEVALUATED) is Check.PASS
                for name in self.required_checks
            )
        )

    # -- 非破壊更新 ---------------------------------------------------------

    def with_check(self, name: str, outcome: Check) -> "Claim":
        """検査を 1 つ記録する (既にあれば悪い方を残す)。"""
        prev = self.checks.get(name)
        merged = Check(outcome) if prev is None else worse_check(prev, Check(outcome))
        return replace(self, checks={**self.checks, name: merged})

    def with_gate(self, *request_ids: str) -> "Claim":
        return replace(self, gate=self.gate | frozenset(request_ids))

    def weakened_to(self, determinacy: Determinacy, *witnesses: Witness) -> "Claim":
        """決定性を弱い方へだけ動かす (強くするのは `strengthened_to`)。"""
        return replace(
            self,
            determinacy=weaker_determinacy(self.determinacy, determinacy),
            witnesses=self.witnesses + tuple(witnesses),
        )

    def strengthened_to(self, determinacy: Determinacy, witness: Witness) -> "Claim":
        """証人付きで決定性を上げる。証人無しでは上げられない (`__post_init__` が拒否する)。"""
        return replace(self, determinacy=determinacy, witnesses=self.witnesses + (witness,))

    # -- 直列化 -------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """全軸 + 導出した `publishable` を JSON 安全な dict にする (集合はソート済みリスト)。"""
        return {
            "key": self.key,
            "param_class": self.param_class,
            "value": self.value,
            "esd": self.esd,
            "unit": self.unit,
            "phase": self.phase,
            "label": self.label,
            "axis": self.axis,
            "determinacy": self.determinacy.value,
            "provenance": sorted(self.provenance),
            "correlations": sorted(self.correlations),
            "scope": self.scope.value,
            "checks": {k: v.value for k, v in sorted(self.checks.items())},
            "gate": sorted(self.gate),
            "witnesses": [w.to_dict() for w in self.witnesses],
            "publishable": self.publishable,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Claim":
        """`to_dict` の逆。``publishable`` は読まない (導出し直す)。素の数値は受け付けない。"""
        if not isinstance(d, Mapping):
            raise TypeError(f"Claim は dict から読みます (受け取った型: {type(d).__name__})")
        return cls(
            key=str(d["key"]),
            param_class=str(d["param_class"]),
            value=d["value"],
            esd=d["esd"],
            unit=str(d["unit"]),
            phase=d.get("phase"),
            label=d.get("label"),
            axis=d.get("axis"),
            determinacy=Determinacy(d["determinacy"]),
            provenance=frozenset(d["provenance"]),
            correlations=frozenset(d.get("correlations", ())),
            scope=Scope(d["scope"]),
            checks={str(k): Check(v) for k, v in dict(d["checks"]).items()},
            gate=frozenset(d.get("gate", ())),
            witnesses=tuple(Witness.from_dict(w) for w in d.get("witnesses", ())),
        )


def compose(a: Claim, b: Claim) -> Claim:
    """同じ値の 2 つの主張 (開始点違い・依存の伝播) を合成する (proposal §3.1 の合成規則)。

    値と esd は ``a`` のもの (呼び手が採用した方) を残す。出自が違えば初期値に依存している。
    """
    if a.key != b.key:
        raise ValueError(f"違う値の主張は合成できません (key: {a.key!r} と {b.key!r})")
    determinacy = weaker_determinacy(a.determinacy, b.determinacy)
    if a.provenance != b.provenance:
        determinacy = weaker_determinacy(determinacy, Determinacy.INITIAL_VALUE_DEPENDENT)
    checks = dict(a.checks)
    for name, outcome in b.checks.items():
        checks[name] = worse_check(checks[name], outcome) if name in checks else outcome
    return replace(
        a,
        determinacy=determinacy,
        provenance=a.provenance | b.provenance,
        correlations=a.correlations | b.correlations,
        scope=_weaker_scope(a.scope, b.scope),
        checks=checks,
        gate=a.gate | b.gate,
        witnesses=a.witnesses + tuple(w for w in b.witnesses if w not in a.witnesses),
    )
