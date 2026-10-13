"""判断要求・止める値・既定ポリシー D と、出版状態を決める入口 `assess` (fit-then-judge P1-1A)。

設計: ``docs/design/fit-then-judge/p1-1a-architecture.md`` §6 / proposal §3.2・§3.4。

`assess(result, phases, multistart)` は **写像 → 証人 → 結晶化学 → 判断要求 → D** を通し、値ごとの
`Claim` と判断要求を返す。出版状態を決める入口はこれ 1 つ (② はこれだけを呼ぶ)。

**判断要求は止める値を自分で持つ** (`blocks`)。blocking な要求の id は、止める値の `Claim.gate` に入る。
伝播は表で固定し、推移閉包はとらない (|ρ| の伝播は「初期値で割れた」値の**直接の**相手だけ):

| kind | 発行条件 | blocking | 止める値 |
|---|---|---|---|
| ``phase_set_completeness`` | 証人が fail/unevaluated | yes | 全値 |
| ``input_structure_provenance`` | 常に (1A に宣言の受け口が無い) | no | — |
| ``crystal_chemistry:<相>`` | その相の検査が fail/unevaluated | yes | その相の座標・Uiso・占有率 |
| ``validity:<検査名>`` | validity の検査が fail | yes | 違反した値とその相の全値 (相を引けなければ全値) |
| ``initial_value_dependence`` | 開始点間で割れた値がある | yes | 割れた値 + 直接 \\|ρ\\| の相手 |
| ``frozen_cell:<相>`` | 格子を凍結した相 | yes | その相の質量分率 |
| ``coordinate_freedom:<相>.<原子>`` | 座標の自由度の食い違い | yes | その原子の座標 |

**既定ポリシー D (`DEFAULT_POLICY`)** は全要求に ``hold`` を返す。**止めを外さない** — 止めが外れるのは
データの証人で要求がそもそも発行されないときだけ (人の回答で閉じる経路は決定 2)。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .build import CLAIMS_VERSION, base_claims, with_convergence, with_probe
from .chemistry import crystal_chemistry
from .model import Check, Claim, Determinacy, Scope, Witness, _json_value
from .witness import residual_window_witness

__all__ = [
    "DEFAULT_POLICY",
    "Assessment",
    "JudgmentRequest",
    "assess",
    "assess_claims",
]

#: 既定ポリシー D の版 (回答表を変えたら上げる)。
DEFAULT_POLICY = "D-1A/1"
_HOLD = MappingProxyType({"answer": "hold", "policy": DEFAULT_POLICY})
_STRUCTURE_CLASSES = frozenset({"coord", "uiso", "occupancy"})


@dataclass(frozen=True)
class JudgmentRequest:
    """決まらなかったこと・検査できなかったこと 1 件。

    :param blocks: 止める値のキー (blocking のときだけ `Claim.gate` に入る)
    :param candidates: 取りうる回答 (1A では D が ``hold`` を選ぶだけ)
    :param default: 既定ポリシー D の回答 (`_apply_default_policy` が埋める)
    """

    id: str
    kind: str
    blocking: bool
    blocks: frozenset[str]
    trigger: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    candidates: tuple[str, ...] = ("hold",)
    priority: float = 0.5
    default: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "blocking": self.blocking,
            "blocks": sorted(self.blocks),
            "trigger": self.trigger,
            "evidence": _json_value(dict(self.evidence)),
            "candidates": list(self.candidates),
            "priority": self.priority,
            "default": dict(self.default) if self.default is not None else None,
        }


@dataclass(frozen=True)
class Assessment:
    """値ごとの出版状態と判断要求。"""

    claims: Mapping[str, Claim]
    requests: tuple[JudgmentRequest, ...]
    version: str = CLAIMS_VERSION
    policy: str = DEFAULT_POLICY

    def publishable_values(self) -> dict[str, dict[str, Any]]:
        """出版してよい値だけ (``{キー: {value, esd, unit, scope, determinacy}}``)。

        ``scope`` を落とさない — 格子は 1A では常に ``relative_within_sample`` (内部標準の宣言が無い) で、
        値だけを渡すと ③ は絶対値として報告する (状態を落とす変換の禁止)。
        """
        return {
            key: {
                "value": c.value, "esd": c.esd, "unit": c.unit,
                "scope": c.scope.value, "determinacy": c.determinacy.value,
            }
            for key, c in sorted(self.claims.items()) if c.publishable
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims_version": self.version,
            "policy": self.policy,
            "claims": {key: c.to_dict() for key, c in sorted(self.claims.items())},
            "judgment_requests": [r.to_dict() for r in self.requests],
            "publishable_values": self.publishable_values(),
        }


# ---------------------------------------------------------------- 検査器 (テストで差し替える)


def _phase_set_witness(result: object) -> tuple[Check, Witness]:
    profiles = getattr(result, "hist_profile", ())
    if len(profiles) > 1:
        # 残差・反射位置は先頭ヒストグラムのものだけ — joint で他のヒストグラムにしか見えない相を
        #   見落とすので、第 1 期の範囲 (単一ヒストグラム) の外は検査しない
        return Check.UNEVALUATED, Witness(
            "residual_window_snr", {"reason": "multiple_histograms", "n_histograms": len(profiles)},
        )
    return residual_window_witness(
        getattr(result, "residual_two_theta", ()),
        getattr(result, "residual_intensity", ()),
        getattr(result, "residual_sigma", ()),
        getattr(result, "reflection_two_theta", None),
        profiles[0] if profiles else None,
    )


# ---------------------------------------------------------------- 判断要求の発行


def _keys(claims: Mapping[str, Claim], **match: object) -> frozenset[str]:
    return frozenset(
        key for key, c in claims.items()
        if all(getattr(c, attr) == want for attr, want in match.items())
    )


def _phase_of_check(name: str, phases: Iterable[str]) -> str | None:
    """validity の検査名 (``lattice_<相>_<軸>`` 等) から相を引く。相名の ``_`` に強いよう前方一致で。"""
    for prefix in ("lattice_", "uiso_", "occupancy_"):
        if name.startswith(prefix):
            rest = name[len(prefix):]
            for phase in sorted(phases, key=len, reverse=True):
                if rest.startswith(f"{phase}_"):
                    return phase
    return None


def _validity_requests(claims: Mapping[str, Claim], result: object) -> list[JudgmentRequest]:
    phases = set(getattr(result, "refined_cells", {}))
    out: list[JudgmentRequest] = []
    for name, ok, detail in getattr(getattr(result, "validity", None), "checks", ()):
        if ok:
            continue
        phase = _phase_of_check(name, phases)
        blocks = _keys(claims, phase=phase) if phase is not None else frozenset(claims)
        out.append(JudgmentRequest(
            id=f"validity:{name}", kind="validity", blocking=True, blocks=blocks,
            trigger=f"物理妥当性の検査 {name} が fail",
            evidence={"check": name, "detail": str(detail), "phase": phase},
            priority=0.9,
        ))
    return out


def _frozen_cell_phases(claims: Mapping[str, Claim], phases: Sequence[object] | None) -> set[str]:
    """格子を凍結した相。``refine_cell=False`` の指定に加え、**格子を 1 軸も精密化しなかった**相
    (自動凍結・格子段の revert) も拾う — 指定だけを見ると engine が凍結した相を見落とす。"""
    frozen = {getattr(p, "phase_name") for p in phases or () if not getattr(p, "refine_cell", True)}
    cells: dict[str, list[Claim]] = {}
    for c in claims.values():
        if c.param_class == "cell" and c.phase is not None:
            cells.setdefault(c.phase, []).append(c)
    for phase, cell in cells.items():
        if any(("input" in c.provenance or "pruned" in c.provenance) for c in cell) and not any(
            "refined" in c.provenance for c in cell
        ):
            frozen.add(phase)
    return frozen


def _unmapped_partners(split: set[str], result: object) -> set[str]:
    """割れた値の相関の相手のうち、値のキーに引けないもの。

    GSAS は拘束 (混合占有の和など) を varyList で ``::constrN`` に置き換えるので、その変数との相関は
    どの値の相手かを引けない (実 GSAS の garnet で確認)。拘束の従属側だけで動く値 (varyList に無く
    ``depSigDict`` にだけある) も相関を持てない。拘束の中身は**別の相**のこともある (スケール ↔ 他相の
    占有率) ので、呼び手はこれが空でなければ全値を止める (「相手が無い」ではなく「分からない」)。
    """
    cov = getattr(result, "final_covariance", None)
    variables: Mapping[str, tuple[str, ...]] = getattr(result, "claim_variables", None) or {}
    if cov is None:
        return set()
    mapped = {v for names in variables.values() for v in names}
    vary = set(cov.vary_list)
    dependent = set(cov.dependent)
    unmapped: set[str] = set()
    for key in split:
        names = set(variables.get(key, ()))
        if names and not names & vary and names & dependent:
            unmapped.add(f"<dependent:{key}>")
        for pair in cov.correlations:
            for mine, other in ((pair.a, pair.b), (pair.b, pair.a)):
                if mine in names and other not in mapped and other.startswith("::constr"):
                    unmapped.add(other)
    return unmapped


def _issue(
    claims: Mapping[str, Claim], result: object, phases: Sequence[object] | None,
    phase_set: tuple[Check, Witness], chemistry: Mapping[str, tuple[Check, Witness]],
) -> list[JudgmentRequest]:
    out: list[JudgmentRequest] = []
    outcome, witness = phase_set
    if outcome is not Check.PASS:
        out.append(JudgmentRequest(
            id="phase_set_completeness", kind="phase_set_completeness", blocking=True,
            blocks=frozenset(claims),
            trigger=f"相集合の完全性の証人が {outcome.value} (欠落相は全値を偏らせる)",
            evidence=witness.to_dict(), candidates=("hold", "add_phase", "remeasure"),
            priority=1.0,
        ))
    out.append(JudgmentRequest(
        id="input_structure_provenance", kind="input_structure_provenance", blocking=False,
        blocks=frozenset(),
        trigger="入力構造の出所は宣言でしか閉じない (データから証人は得られない)",
        evidence={"input_provenance": "undeclared"}, candidates=("hold", "declare"),
        priority=0.1,
    ))
    for phase in sorted({c.phase for c in claims.values() if c.phase is not None}):
        chem = next(iter(
            c.checks.get("crystal_chemistry") for c in claims.values()
            if c.phase == phase and c.param_class in _STRUCTURE_CLASSES
        ), None)
        if chem is not None and chem is not Check.PASS:
            out.append(JudgmentRequest(
                id=f"crystal_chemistry:{phase}", kind="crystal_chemistry", blocking=True,
                blocks=frozenset(
                    k for k, c in claims.items()
                    if c.phase == phase and c.param_class in _STRUCTURE_CLASSES
                ),
                trigger=f"相 {phase} の結晶化学検査が {chem.value}",
                # 検査ごとの結果と理由 (unevaluated なら何が組めなかったか) — ③ が報告に書ける形で
                evidence={"phase": phase, **(
                    chemistry[phase][1].to_dict() if phase in chemistry else {}
                )},
                candidates=("hold", "revise_structure"),
                priority=0.8,
            ))
    out.extend(_validity_requests(claims, result))
    split = {k for k, c in claims.items() if c.determinacy is Determinacy.INITIAL_VALUE_DEPENDENT}
    if split:
        partners = {p for k in split for p in claims[k].correlations if p in claims}
        unmapped = _unmapped_partners(split, result)
        if unmapped:
            partners |= set(claims)  # 相手が分からない — 拘束の中身は別の相のこともあるので全値
        out.append(JudgmentRequest(
            id="initial_value_dependence", kind="initial_value_dependence", blocking=True,
            blocks=frozenset(split | partners),
            trigger="開始点間で値が kσ を超えて割れた (+ 直接の |ρ| の相手)",
            evidence={"split": sorted(split), "partners": sorted(partners - split),
                      "unmapped_partners": sorted(unmapped)},
            candidates=("hold", "fix_parameter", "remeasure"), priority=0.9,
        ))
    for phase in sorted(_frozen_cell_phases(claims, phases)):
        out.append(JudgmentRequest(
            id=f"frozen_cell:{phase}", kind="frozen_cell", blocking=True,
            # 分率の和は 1 — 凍結した相の誤差は他相の分率にも同じだけ移るので全相の分率を止める。
            #   単相の分率 = 1 (exact) は定義で決まるので止めない
            blocks=frozenset(
                k for k in _keys(claims, param_class="weight_fraction")
                if "symmetry" not in claims[k].provenance
            ),
            trigger=f"相 {phase} の格子を凍結した (相分率は格子の誤差を吸収しうる)",
            evidence={"phase": phase}, candidates=("hold", "release_cell"), priority=0.6,
        ))
    for phase, rows in sorted((getattr(result, "coordinate_freedom_mismatches", None) or {}).items()):
        for label, row_sym, recomputed in rows:
            out.append(JudgmentRequest(
                id=f"coordinate_freedom:{phase}.{label}", kind="coordinate_freedom",
                blocking=True,
                blocks=_keys(claims, param_class="coord", phase=phase, label=label),
                trigger=f"{phase}.{label} の座標の自由度が site symmetry と食い違う",
                evidence={"row_site_symmetry": row_sym, "recomputed": recomputed},
                candidates=("hold", "revise_structure"), priority=0.7,
            ))
    return out


# ---------------------------------------------------------------- 入口


def template_adjustments(
    claims: Mapping[str, Claim], derivation: "Mapping[str, Any] | None"
) -> tuple[dict[str, Claim], list[JudgmentRequest]]:
    """テンプレートの判断 (`RecipeCandidate.derivation`) を出版状態に写す (fit-then-judge 1B)。

    - **内部標準を宣言した** (かつ Zero が有意でない): 格子は ``scope = absolute``、出自に
      ``declared:internal_standard`` (宣言でしか閉じない根拠なので、宣言に依存したことを残す)
    - **Zero が有意** (Bragg-Brentano で Shift だけでは足りない): 格子は ``relative_within_sample`` のまま
      Zero の値と相関に結び、非 blocking の判断要求 ``zero_offset_significant`` (pass 2 は Zero を装置値に
      固定している = D の既定)
    - **対象相が僅差・宣言と食い違う・計測できない**: blocking の ``target_phase_ambiguous`` で全相の構造値
      (座標・Uiso・占有率) を止める (構造を精密化した相の選択そのものが決まっていない)
    - 対象相を宣言したら対象相の構造値に、装置の較正を宣言したら微細構造の値に ``declared:<キー>``
    """
    out = dict(claims)
    requests: list[JudgmentRequest] = []
    if not derivation:
        return out, requests
    decl = dict(derivation.get("declarations") or {})
    evidence = dict(derivation.get("evidence") or {})
    decisions = dict(derivation.get("decisions") or {})
    zero_sig = derivation.get("zero_offset_significant")
    cells = [k for k, c in out.items() if c.param_class == "cell"]
    if decl.get("internal_standard") and zero_sig is not True:
        for k in cells:
            c = out[k]
            if "refined" in c.provenance:
                out[k] = replace(
                    c, scope=Scope.ABSOLUTE,
                    provenance=c.provenance | {"declared:internal_standard"},
                )
    if zero_sig is True:
        zero_keys = {k for k, c in out.items() if c.param_class == "profile" and c.axis == "Zero"}
        for k in cells:
            c = out[k]
            out[k] = replace(
                c, scope=Scope.RELATIVE_WITHIN_SAMPLE, correlations=c.correlations | zero_keys,
            )
        requests.append(JudgmentRequest(
            id="zero_offset_significant", kind="zero_offset_significant", blocking=False,
            blocks=frozenset(),
            trigger="pass 1 で Shift + Zero が Shift だけより有意に良い (Zero は装置値に固定した)",
            evidence={"zero_offset": evidence.get("zero_offset"), "correlated": ["Shift", "Zero"]},
            candidates=("hold", "release_zero", "calibrate_instrument"), priority=0.4,
        ))
    if derivation.get("target_phase_ambiguous"):
        requests.append(JudgmentRequest(
            id="target_phase_ambiguous", kind="target_phase_ambiguous", blocking=True,
            blocks=frozenset(k for k, c in out.items() if c.param_class in _STRUCTURE_CLASSES),
            trigger="対象相 (構造を精密化する相) が積分強度で決まらない・宣言と食い違う・計測できない",
            evidence={"target_phase": evidence.get("target_phase")},
            candidates=("hold", "declare_target_phase"), priority=0.85,
        ))
    target = decisions.get("target_phase")
    if decl.get("target_phase") and target:
        for k, c in list(out.items()):
            if c.phase == target and c.param_class in _STRUCTURE_CLASSES:
                out[k] = replace(c, provenance=c.provenance | {"declared:target_phase"})
    if decl.get("instrument_calibrated"):
        for k, c in list(out.items()):
            if c.param_class == "microstructure":
                out[k] = replace(c, provenance=c.provenance | {"declared:instrument_calibrated"})
    return out, requests


def assess_claims(
    claims: Mapping[str, Claim], result: object, phases: Sequence[object] | None,
    extra_requests: Sequence[JudgmentRequest] = (),
) -> Assessment:
    """写像済みの `Claim` に検査器・判断要求・D を掛ける (`assess` の後半)。

    :param extra_requests: 写像の外で発行した判断要求 (テンプレートの判断など)。同じく D の既定回答を
        受け、blocking なら止める
    """
    phase_set = _phase_set_witness(result)
    paths = {getattr(p, "phase_name"): getattr(p, "structure_path") for p in phases or ()}
    chem: dict[str, tuple[Check, Witness]] = {}
    for phase in {c.phase for c in claims.values() if c.phase is not None}:
        if phase in paths:
            chem[phase] = crystal_chemistry(phase, paths[phase], result)["crystal_chemistry"]
        else:
            chem[phase] = (Check.UNEVALUATED, Witness(
                "crystal_chemistry", {"reason": "structure_path_unknown"},
            ))

    checked: dict[str, Claim] = {}
    for key, c in claims.items():
        c = c.with_check("phase_set_completeness", phase_set[0])
        if c.param_class in _STRUCTURE_CLASSES and c.phase in chem:
            c = c.with_check("crystal_chemistry", chem[c.phase][0])
        checked[key] = c

    requests = [
        replace(r, default=_HOLD)
        for r in [*_issue(checked, result, phases, phase_set, chem), *extra_requests]
    ]
    gated = dict(checked)
    for r in requests:
        if r.blocking:
            for key in r.blocks:
                gated[key] = gated[key].with_gate(r.id)
    return Assessment(claims=gated, requests=tuple(requests))


def assess(
    result: object, phases: Sequence[object] | None = None, multistart: object | None = None,
    *,
    derivation: "Mapping[str, Any] | None" = None,
    probe: object | None = None,
) -> Assessment:
    """結果 (+ 相の指定・収束確認) から出版状態を決める (fit-then-judge の唯一の入口)。

    :param phases: `PhaseSpec` の列 (結晶化学検査の入力構造と、格子を凍結した相)。None なら
        結晶化学は ``unevaluated``
    :param multistart: `RietveldMultistartResult` (収束確認)。None なら `determined` は付かない
    :param derivation: テンプレートの判断 (1B)。None なら何もしない
    :param probe: 初期値プローブ (`autorietveld.probe.ProbeOutcome`, 1B)。None なら `locally_stable` は付かない
    """
    claims = with_probe(with_convergence(base_claims(result), multistart), result, probe)
    claims, extra = template_adjustments(claims, derivation)
    return assess_claims(claims, result, phases, extra)
