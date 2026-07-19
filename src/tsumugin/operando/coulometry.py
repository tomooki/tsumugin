"""クーロメトリー→可動アルカリ量の物理コア (FR-318 / REQ-318-001〜004, 007, 008)。🔵

充放電の実測積算電気量 Q(t) [mAh] を式単位あたり反応電子数 n_e(t) に変換し、
各回折フレームの総アルカリ量目標 x_total(t) = x₀ − sign·n_e(t) を作る。numpy-only・決定論。

設計 (docs/design/charge-constrained-rietveld/architecture.md):

- **実測 Q(t) を使う** (`EchemCurve.charge_mah` / `FramePoint.charge_mah`)。CC 線形性を
  仮定しないので CV 保持・rest を正しく扱う (`operando.echem` の ``capacity_to_x`` 線形換算は
  CC 専用の旧経路)。
- **複数元素サイト** (REQ-318-008): Na/K ハイブリッド系では電子数 = 総アルカリ挿入量しか
  拘束できないため、:class:`MobileSiteSpec` はサイト毎に複数元素の占有率を合算する。
- **★ FW 除算** (REQ-318-007): XRD 由来総量のモル平均換算は重量分率を**式量 FWᵢ で割る**。
  セル質量 Zᵢ·FWᵢ で割ると Z を二重計上する (最頻出バグとしてテストでピン留め)。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np

from ..interop.biologic import FramePoint

__all__ = [
    "F_MAH_PER_MOL",
    "AlkaliBudget",
    "FrameTarget",
    "MobileSiteSpec",
    "alkali_targets",
    "content_from_occupancies",
    "coulometric_fractions",
    "electron_count",
    "feasibility",
    "occupancies_for_content",
    "x_xrd_from_weight_fractions",
]

F_MAH_PER_MOL: float = 96485.33212 / 3.6
"""ファラデー定数 [mAh/mol] (= 96485.33212 C/mol ÷ 3.6 C/mAh ≈ 26801.48)。"""

_X0_SOURCES = ("given", "first_frame", "anchor")


def electron_count(
    charge_mah: "float | np.ndarray",
    active_mass_mg: float,
    formula_weight: float,
    *,
    z: int = 1,
) -> "float | np.ndarray":
    """積算電気量 [mAh] → 式単位あたり反応電子数 n_e (REQ-318-001)。🔵

    n_e = (Q / m) × M / F / z。Q はスカラでも ndarray でも良い (形状保存)。

    :param charge_mah: 実測積算電気量 [mAh] (充電で増・放電で減)
    :param active_mass_mg: 活物質質量 [mg]
    :param formula_weight: 活物質の式量 M [g/mol]
    :param z: イオン価数 (アルカリ金属は 1)
    """
    if active_mass_mg <= 0:
        raise ValueError(f"active_mass_mg は正であること: {active_mass_mg}")
    if formula_weight <= 0:
        raise ValueError(f"formula_weight は正であること: {formula_weight}")
    if z <= 0:
        raise ValueError(f"z は正の整数であること: {z}")
    mass_g = active_mass_mg / 1000.0
    scale = formula_weight / (mass_g * F_MAH_PER_MOL * z)
    if isinstance(charge_mah, np.ndarray):
        return charge_mah * scale
    return float(charge_mah) * scale


@dataclass(frozen=True)
class FrameTarget:
    """1 フレームの総アルカリ量目標。🔵

    :param frame_index: 回折フレーム番号 (入力順を保つ)
    :param x_total: 式単位あたり総アルカリ量目標。**None = 目標なし** (echem 範囲外 —
        範囲外の外挿値で拘束することを構造的に禁止する; REQ-318-003)
    :param n_e: 式単位あたり反応電子数 (x_total が None なら None)
    :param state: ``"rest"`` / ``"charge"`` / ``"discharge"`` / ``"unknown"``
    :param in_span: echem 曲線の時間範囲内か
    """

    frame_index: int
    x_total: float | None
    n_e: float | None
    state: str
    in_span: bool


@dataclass(frozen=True)
class AlkaliBudget:
    """フレーム列全体のアルカリ量収支 (x₀ の来歴と sign 検証警告を含む)。🔵

    :param targets: フレーム毎の目標 (入力順)
    :param x0: 基準組成 (charge_mah = 0 の時点の式単位あたりアルカリ量)
    :param x0_source: x₀ の由来 — ``given`` (ユーザー指定) / ``first_frame`` (先頭フレームで
        精密化) / ``anchor`` (アンカー精密化値で校正済み)。REQ-318-002/006
    :param sign: +1 = 充電 (Q 増) でアルカリ減 (正極規約) / −1 = 逆 (負極規約)
    :param warnings: 非既定 sign の明示確認等 (REQ-318-003)。⚠ 電極取り違えの**検出**は
        原理的に不可能 (state が積算電荷由来のため) — `_sign_consistency_warnings` 参照
    """

    targets: tuple[FrameTarget, ...]
    x0: float
    x0_source: str
    sign: int
    warnings: tuple[str, ...]


def alkali_targets(
    frame_points: Iterable[FramePoint],
    *,
    x0: float,
    active_mass_mg: float,
    formula_weight: float,
    z: int = 1,
    sign: int = 1,
    x0_source: str = "given",
) -> AlkaliBudget:
    """フレーム列の総アルカリ量目標 x_total(t) = x₀ − sign·n_e(t) を作る (REQ-318-003)。🔵

    - ``in_span=False`` または ``charge_mah=None`` のフレームには目標を作らない (捏造禁止)。
    - ``state=rest`` は Q 一定なので目標は有効。
    - **sign の検証限界** (レビューで確定): ``state`` は積算電荷 ΔQ の符号から導かれるため、
      「x の増減 vs state」の照合は**同語反復**であり電極の取り違えを原理的に検出できない
      (Q と独立な電極化学の知識が要る)。よって本関数は取り違え検出を**主張しない** —
      非既定の ``sign=-1`` (負極規約: 充電で挿入) が指定されたときに**明示確認の警告**を
      積むのみとする (既定 +1 = 正極規約: 充電でアルカリ減)。
    """
    if sign not in (1, -1):
        raise ValueError(f"sign は +1 か -1 であること: {sign}")
    if x0_source not in _X0_SOURCES:
        raise ValueError(f"x0_source は {_X0_SOURCES} のいずれか: {x0_source!r}")
    # 物理パラメータは in-span フレームの有無に依らず**無条件に**検証する (レビュー LOW:
    # 全フレーム範囲外だと electron_count が一度も呼ばれず、ゴミ質量でも「正常」を返していた)。
    electron_count(0.0, active_mass_mg, formula_weight, z=z)

    targets: list[FrameTarget] = []
    for pt in frame_points:
        if not pt.in_span or pt.charge_mah is None:
            targets.append(
                FrameTarget(
                    frame_index=pt.frame_index, x_total=None, n_e=None,
                    state=pt.state, in_span=pt.in_span,
                )
            )
            continue
        n_e = float(
            electron_count(pt.charge_mah, active_mass_mg, formula_weight, z=z)
        )
        targets.append(
            FrameTarget(
                frame_index=pt.frame_index, x_total=x0 - sign * n_e, n_e=n_e,
                state=pt.state, in_span=pt.in_span,
            )
        )

    warnings = _sign_consistency_warnings(targets, sign)
    return AlkaliBudget(
        targets=tuple(targets), x0=float(x0), x0_source=x0_source, sign=sign,
        warnings=warnings,
    )


def _sign_consistency_warnings(targets: list[FrameTarget], sign: int) -> tuple[str, ...]:
    """非既定 sign (=-1, 負極規約) の明示確認警告。🔵

    **旧実装は同語反復だった** (レビュー MEDIUM で確定): ``state`` は積算電荷 ΔQ の符号から
    導かれる (`interop.biologic._sample_states`) ため、「充電区間で x が増えるか」の検査は
    構造的に「sign == -1 か」と等価であり、**電極の取り違え (sign=+1 のまま負極を解析) は
    原理的に検出できない** (Q と独立な情報が要る)。検出できない検証を「配線ミス検出」と
    主張するのは「呼べるが黙って間違う」の亜種なので、主張を能力に合わせる:
    sign=-1 が指定されたときのみ「負極規約を選択した」ことの明示確認を促す。
    """
    if sign == -1 and any(t.x_total is not None for t in targets):
        return (
            "sign=-1 (負極規約: 充電でアルカリ挿入) が指定されています。回折側電極が"
            "負極の場合のみ正しい規約です — 正極 (充電で脱離) なら既定の sign=+1 を"
            "使ってください。⚠ この選択の正誤はデータからは検証できません "
            "(state は積算電荷由来のため電極の役割と独立な照合が不可能)。",
        )
    return ()


@dataclass(frozen=True)
class MobileSiteSpec:
    """1 相の可動イオンサイト仕様 (複数元素合算対応; REQ-318-008)。🔵

    Na/K ハイブリッド系では同一サイトを Na と K が分け合う。クーロメトリーは合算量しか
    拘束できないため、``site_labels`` に両方の原子ラベルを列挙し合算して x とする。

    :param phase_name: 相名
    :param site_labels: 可動イオン原子ラベル列 (例 ``("Na1", "K1")``)
    :param multiplicities: 各ラベルのサイト多重度 (同順・同長)
    """

    phase_name: str
    site_labels: tuple[str, ...]
    multiplicities: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.site_labels) != len(self.multiplicities):
            raise ValueError(
                f"site_labels ({len(self.site_labels)}) と multiplicities "
                f"({len(self.multiplicities)}) の長さが一致しません"
            )
        if not self.site_labels:
            raise ValueError("site_labels が空です")

    def to_dict(self) -> dict[str, object]:
        """JSON 直列化 (② MCP 境界用)。"""
        return {
            "phase_name": self.phase_name,
            "site_labels": list(self.site_labels),
            "multiplicities": list(self.multiplicities),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "MobileSiteSpec":
        return cls(
            phase_name=str(d["phase_name"]),
            site_labels=tuple(str(x) for x in d["site_labels"]),  # type: ignore[union-attr]
            multiplicities=tuple(float(x) for x in d["multiplicities"]),  # type: ignore[union-attr]
        )


def content_from_occupancies(
    occupancies: Mapping[str, float],
    spec: MobileSiteSpec,
    *,
    z_formula: float,
) -> float:
    """占有率 → 式単位あたり可動イオン量 x = Σ occ·mult / Z。🔵"""
    if z_formula <= 0:
        raise ValueError(f"z_formula は正であること: {z_formula}")
    missing = [lb for lb in spec.site_labels if lb not in occupancies]
    if missing:
        raise ValueError(f"占有率が与えられていないラベル: {missing}")
    total = sum(
        float(occupancies[lb]) * m for lb, m in zip(spec.site_labels, spec.multiplicities)
    )
    return total / float(z_formula)


def occupancies_for_content(
    x_target: float,
    spec: MobileSiteSpec,
    *,
    z_formula: float,
    base_occupancies: Mapping[str, float],
) -> dict[str, float]:
    """目標 x を満たす占有率へ**等比配分** (逆写像)。🔵

    既存占有比 (Na:K 等) を保存して全体をスケールする。既存が全ゼロなら均等配分。
    結果の占有率が 1 を超える配分は物理的に不可能なので ValueError。
    """
    x_base = content_from_occupancies(base_occupancies, spec, z_formula=z_formula)
    if x_base > 0:
        ratio = x_target / x_base
        out = {lb: float(base_occupancies[lb]) * ratio for lb in spec.site_labels}
    else:
        mult_sum = sum(spec.multiplicities)
        out = {lb: x_target * z_formula / mult_sum for lb in spec.site_labels}
    over = {lb: v for lb, v in out.items() if v > 1.0 + 1e-9}
    if over:
        raise ValueError(
            f"目標 x={x_target} は占有率 1 超を要求します (物理的に不可能): {over}"
        )
    # 負も同様に物理的に不可能 (レビュー HIGH: x₀ 過小/不可逆容量で x_total<0 になる充電末は
    # **現実に起きる** — ここで raise すれば `_occupancy_targets` が捕捉して診断へ縮退し、
    # 系列 run が生の ValueError で死なない)。
    under = {lb: v for lb, v in out.items() if v < -1e-9}
    if under:
        raise ValueError(
            f"目標 x={x_target} は負の占有率を要求します (物理的に不可能 — x₀ の過小/"
            f"不可逆容量の疑い): {under}"
        )
    return out


def x_xrd_from_weight_fractions(
    weight_fractions: Mapping[str, float],
    formula_weights: Mapping[str, float],
    x_per_phase: Mapping[str, float],
    *,
    weight_esd: Mapping[str, float] | None = None,
    x_esd: Mapping[str, float] | None = None,
) -> tuple[float, float | None]:
    """重量分率 → XRD 由来のモル平均アルカリ量 x_XRD ± esd (REQ-318-007)。🔵

    φᵢᵐᵒˡ = (wᵢ/FWᵢ) / Σ(wⱼ/FWⱼ)、x_XRD = Σ φᵢᵐᵒˡ·xᵢ。

    **★ FW で割る (セル質量 Zᵢ·FWᵢ ではない)** — セル質量で割ると Z を二重計上する。
    式単位モル数 nᵢ ∝ wᵢ/FWᵢ が正しい (テスト ``test_asymmetric_fw_pins_the_divisor``)。

    esd (一次伝播): σ²(x) = Σ ((xₖ−x)/(FWₖ·S))²·σ²(wₖ) + Σ φₖ²·σ²(xₖ), S = Σ wⱼ/FWⱼ。
    esd 入力が両方 None なら **None を返す** (0.0 の無限精度捏造をしない — §4.5 規則⑤⑥)。
    """
    names = list(weight_fractions)
    if not names:
        raise ValueError("weight_fractions が空です")
    for nm in names:
        if nm not in formula_weights or nm not in x_per_phase:
            raise ValueError(f"formula_weights / x_per_phase に相 {nm!r} がありません")
        if formula_weights[nm] <= 0:
            raise ValueError(f"式量は正であること: {nm}={formula_weights[nm]}")

    s = sum(weight_fractions[nm] / formula_weights[nm] for nm in names)
    if s <= 0:
        raise ValueError("重量分率の総モル数が 0 以下です")
    phi = {nm: (weight_fractions[nm] / formula_weights[nm]) / s for nm in names}
    x = sum(phi[nm] * x_per_phase[nm] for nm in names)

    if weight_esd is None and x_esd is None:
        return float(x), None
    var = 0.0
    if weight_esd is not None:
        var += sum(
            ((x_per_phase[nm] - x) / (formula_weights[nm] * s)) ** 2
            * float(weight_esd.get(nm, 0.0)) ** 2
            for nm in names
        )
    if x_esd is not None:
        var += sum(phi[nm] ** 2 * float(x_esd.get(nm, 0.0)) ** 2 for nm in names)
    return float(x), math.sqrt(var)


def feasibility(
    x_total: float,
    x_per_phase: Mapping[str, float],
    *,
    tol: float = 1e-6,
    degenerate_tol: float = 1e-6,
) -> str:
    """総量拘束の実行可能性判定 (REQ-318-004)。🔵

    - ``"degenerate"``: xᵢ が相間で (許容差内で) 等しい (単相含む) — 拘束は分率和=1 と縮退
      するため情報を持たない → skip 対象。
    - ``"infeasible"``: x_total ∉ [min xᵢ − tol, max xᵢ + tol] — 非負の相分率では実現不能
      → 拘束せず縮退 + 警告 (= 多相域の不可逆容量検出器)。
    - ``"feasible"``: 上記以外。
    """
    values = list(x_per_phase.values())
    if not values:
        raise ValueError("x_per_phase が空です")
    lo, hi = min(values), max(values)
    if hi - lo < degenerate_tol:
        return "degenerate"
    if x_total < lo - tol or x_total > hi + tol:
        return "infeasible"
    return "feasible"


def coulometric_fractions(
    x_total: float,
    x_per_phase: Mapping[str, float],
    *,
    z_formula: Mapping[str, float],
) -> dict[str, float]:
    """2 相の総量拘束を厳密に解いた Scale 分率 (lock_fractions の解析解・検算オラクル)。🔵

    連立: Σ Scaleᵢ·Zᵢ·(xᵢ − x_total) = 0, Σ Scaleᵢ = 1。
    2 相では一意解。3 相以上は 1 DOF 残り一意でないため明示エラー (REQ-318-004 は
    2 相を主対象とし、3 相以上の lock は GSAS の最小二乗に委ねる)。
    """
    names = list(x_per_phase)
    if len(names) != 2:
        raise ValueError(f"解析解は 2 相のみ対応 (与えられた相数: {len(names)})")
    a, b = names
    xa, xb = x_per_phase[a], x_per_phase[b]
    za, zb = z_formula[a], z_formula[b]
    if feasibility(x_total, x_per_phase) == "infeasible":
        raise ValueError(
            f"x_total={x_total} は [min xᵢ, max xᵢ]=[{min(xa, xb)}, {max(xa, xb)}] の"
            "範囲外です (非負分率で実現不能 = 不可逆容量の疑い)"
        )
    denom = za * (xa - x_total) + zb * (x_total - xb)
    if abs(denom) < 1e-15:
        raise ValueError("拘束が縮退しています (xᵢ が等値)")
    sa = zb * (x_total - xb) / denom
    return {a: float(sa), b: float(1.0 - sa)}
