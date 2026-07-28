"""精密化の自己診断 — 収束・悪条件・弱い変数・強相関を 1 箇所で読む (REQ-SAR-105)。

**なぜ 1 モジュールに集約するか**: 収束判定 (REQ-SAR-101)・esd プルーニング (REQ-SAR-103)・
高相関検出 (REQ-SAR-104) は**どれも同じ情報源** (`gpx.data["Covariance"]["data"]`) を要する。
3 箇所で別々に掘ると GSAS の内部構造への依存が散らばり、片方だけ古くなる (drift)。

**返す型は素の Python スカラ**にして GSAS のデータ構造を外へ漏らさない。`to_dict()` は
そのまま JSON 化でき (非有限は None)、② MCP 境界へ載せられる。

GSAS 依存は `read_diagnostics(gpx)` の 1 関数のみ。それ以外は numpy だけで動く純関数なので
GSAS 無しでテストできる (`tests/autorietveld/test_diagnostics.py`)。

信頼性: 🔵 `GSASIIstrMain.py:565` の covData スキーマ + `:356-365` の Rvals キー実測。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from .._json import finite_or_none

__all__ = [
    "CorrelatedPair",
    "RefinementDiagnostics",
    "WeakVariable",
    "correlated_pairs",
    "diagnostics_from_cov_data",
    "read_diagnostics",
    "weak_variables",
]


@dataclass(frozen=True)
class WeakVariable:
    """esd が値以上に大きい変数 = 「決まらなかった」変数 (凍結候補, REQ-SAR-103)。

    :param ratio: ``esd / |値|``。値 0 のときは ``inf`` (esd がある限り無意味なので weak)
    """

    name: str
    value: float
    esd: float
    ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": finite_or_none(self.value),
            "esd": finite_or_none(self.esd),
            "ratio": finite_or_none(self.ratio),
        }


@dataclass(frozen=True)
class CorrelatedPair:
    """強く相関した 2 変数 (同時解放を避ける対象, REQ-SAR-104)。"""

    a: str
    b: str
    r: float

    def to_dict(self) -> dict[str, Any]:
        return {"a": self.a, "b": self.b, "r": finite_or_none(self.r)}


@dataclass(frozen=True)
class RefinementDiagnostics:
    """1 回の精密化の自己診断。

    :param converged: GSAS 自身の収束フラグ (``Rvals['converged']``)。None = 情報なし
    :param max_shift_esd: 最終サイクルの ``max |shift| / esd`` (``Rvals['Max shft/sig']``)。
        **1 を大きく超えていれば収束していない** — 実測ログには 258.8 を出しながら
        「改善した」として段が通過する例がある
    :param svd_singularities: ``Rvals['SVD0']``。>0 は特異な変数があった = 悪条件の直接証拠
    :param restraint_sum: 拘束の χ² 寄与 (``Rvals['RestraintSum']``)。
        ⚠ **報告は GSAS のゲート外なので、これが非ゼロでも拘束が効いている証明にはならない**
        (`GSASIIstrMath.errRefine:5203` の `dlg` ゲート, requirements.md F5)
    """

    converged: "bool | None" = None
    max_shift_esd: "float | None" = None
    svd_singularities: int = 0
    delta_chi2: "float | None" = None
    n_obs: int = 0
    n_vars: int = 0
    restraint_sum: float = 0.0
    message: str = ""
    weak_vars: tuple[WeakVariable, ...] = ()
    correlated_pairs: tuple[CorrelatedPair, ...] = ()

    def is_converged(self, *, max_shift_esd: float = 1.0) -> "bool | None":
        """収束したか — **GSAS のフラグと shift/esd の両方**を要求する (REQ-SAR-101)。

        どちらの情報も無ければ ``None`` (「収束した」とは答えない — 情報が無いことを
        正常と答えない ② 不変条件と同じ規律)。
        """
        if self.converged is None and self.max_shift_esd is None:
            return None
        if self.converged is False:
            return False
        if self.max_shift_esd is not None and self.max_shift_esd > max_shift_esd:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "converged": self.converged,
            "max_shift_esd": finite_or_none(self.max_shift_esd),
            "svd_singularities": self.svd_singularities,
            "delta_chi2": finite_or_none(self.delta_chi2),
            "n_obs": self.n_obs,
            "n_vars": self.n_vars,
            "restraint_sum": finite_or_none(self.restraint_sum),
            "message": self.message,
            "weak_vars": [w.to_dict() for w in self.weak_vars],
            "correlated_pairs": [p.to_dict() for p in self.correlated_pairs],
        }


def _as_float(value: Any) -> "float | None":
    """非有限・非数値は None (finite_or_none 規約)。"""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _as_sequence(value: Any) -> list[Any]:
    """``None`` を空列に落として list 化する。

    **`value or []` と書いてはいけない**: GSAS の covData は ``variables``/``sig`` を
    **numpy 配列**で持つため、``or`` が配列の真偽値評価を起こし
    ``ValueError: The truth value of an array with more than one element is ambiguous``
    で診断が丸ごと落ちる (実測 T1: 段が全部 chi2=inf → revert された)。
    診断は精密化本体を落としてはならないので、真偽値判定を経由しない形にする。
    """
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:  # 反復不能な値 (スカラ等) は情報なし扱い
        return []


def weak_variables(
    names: Sequence[str], values: Sequence[Any], sig: Sequence[Any]
) -> tuple[WeakVariable, ...]:
    """``esd >= |値|`` の変数を悪い順に返す (REQ-SAR-103)。

    esd が取れない (None/NaN) 変数は**拾わない** — 「決まらなかった」証拠ではなく単に共分散が
    無いだけであり、拾うと esd を持たない精密化で全変数を凍結してしまう。

    長さ不一致は空タプルへ縮退する (診断が例外で精密化を落とさない, fail open)。
    """
    if not (len(names) == len(values) == len(sig)):
        return ()
    out: list[WeakVariable] = []
    for name, raw_value, raw_esd in zip(names, values, sig):
        esd = _as_float(raw_esd)
        value = _as_float(raw_value)
        if esd is None or value is None or esd <= 0.0:
            continue
        ratio = math.inf if value == 0.0 else esd / abs(value)
        if ratio >= 1.0:
            out.append(WeakVariable(name=str(name), value=value, esd=esd, ratio=ratio))
    out.sort(key=lambda w: w.ratio, reverse=True)
    return tuple(out)


def correlated_pairs(
    names: Sequence[str],
    cov_matrix: Any,
    sig: Sequence[Any],
    threshold: float = 0.9,
) -> tuple[CorrelatedPair, ...]:
    """``|r| >= threshold`` の変数ペアを相関の強い順に返す (REQ-SAR-104)。

    ``r_ij = cov_ij / (sig_i · sig_j)``。esd が 0/非有限のペアは飛ばす (0 除算を作らない)。
    形の合わない入力は空タプルへ縮退する (fail open)。
    """
    try:
        cov = np.asarray(cov_matrix, dtype=float)
    except (TypeError, ValueError):
        return ()
    n = len(names)
    if n == 0 or cov.ndim != 2 or cov.shape != (n, n) or len(sig) != n:
        return ()
    esd = np.array([_as_float(s) if _as_float(s) is not None else 0.0 for s in sig], dtype=float)
    out: list[CorrelatedPair] = []
    for i in range(n):
        for j in range(i + 1, n):
            denom = esd[i] * esd[j]
            if denom <= 0.0 or not math.isfinite(denom):
                continue
            r = float(cov[i, j]) / denom
            if math.isfinite(r) and abs(r) >= threshold:
                out.append(CorrelatedPair(a=str(names[i]), b=str(names[j]), r=r))
    out.sort(key=lambda p: abs(p.r), reverse=True)
    return tuple(out)


def diagnostics_from_cov_data(
    cov_data: Mapping[str, Any], *, corr_threshold: float = 0.9
) -> RefinementDiagnostics:
    """GSAS の ``covData`` dict から診断を組み立てる (GSAS 非依存の純写像)。

    空/欠損でも**診断自体は返す** — 呼び出し側に「共分散があるか」の分岐を書かせないため。
    """
    raw_rvals = cov_data.get("Rvals")
    rvals: Mapping[str, Any] = raw_rvals if isinstance(raw_rvals, Mapping) else {}
    names = _as_sequence(cov_data.get("varyList"))
    values = _as_sequence(cov_data.get("variables"))
    sig = _as_sequence(cov_data.get("sig"))
    cov = cov_data.get("covMatrix")

    converged = rvals.get("converged")
    try:
        svd = int(rvals.get("SVD0", 0) or 0)
    except (TypeError, ValueError):
        svd = 0
    try:
        n_obs = int(rvals.get("Nobs", 0) or 0)
    except (TypeError, ValueError):
        n_obs = 0
    try:
        n_vars = int(rvals.get("Nvars", len(names)) or len(names))
    except (TypeError, ValueError):
        n_vars = len(names)

    return RefinementDiagnostics(
        converged=bool(converged) if isinstance(converged, (bool, np.bool_)) else None,
        max_shift_esd=_as_float(rvals.get("Max shft/sig")),
        svd_singularities=svd,
        delta_chi2=_as_float(rvals.get("DelChi2")),
        n_obs=n_obs,
        n_vars=n_vars,
        restraint_sum=_as_float(rvals.get("RestraintSum")) or 0.0,
        message=str(rvals.get("msg") or ""),
        weak_vars=weak_variables(names, values, sig),
        correlated_pairs=(
            correlated_pairs(names, cov, sig, corr_threshold) if cov is not None else ()
        ),
    )


def read_diagnostics(gpx, *, corr_threshold: float = 0.9) -> RefinementDiagnostics:
    """精密化済み ``G2Project`` から診断を読む (**GSAS 依存はここだけ**)。

    共分散が無い (未精密化 / 失敗) 場合も空の診断を返す。
    """
    try:
        cov_data = gpx.data["Covariance"]["data"]
    except (KeyError, TypeError, AttributeError):
        return RefinementDiagnostics()
    if not isinstance(cov_data, Mapping):
        return RefinementDiagnostics()
    return diagnostics_from_cov_data(cov_data, corr_threshold=corr_threshold)
