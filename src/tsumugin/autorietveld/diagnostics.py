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
    "data_term_rwp",
    "diagnostics_from_cov_data",
    "read_diagnostics",
    "read_variable_values",
    "split_weak_variables",
    "values_from_cov_data",
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
    :param restraint_sum: 拘束の χ² 寄与 (``Rvals['RestraintSum']`` = ``pSum``)。
        ⚠ **報告は GSAS のゲート外なので、これが非ゼロでも拘束が効いている証明にはならない**
        (`GSASIIstrMath.errRefine:5203` の `dlg` ゲート, requirements.md F5)
    :param rwp: ``Rvals['Rwp']`` — **拘束が χ² に入っているときは penalty 込みの値**。
        「データへの合わなさ」として読んではならない (`data_rwp` を使う)
    :param chisq: ``Rvals['chisq']`` = ``Σ fvec²``。拘束が χ² に入っていれば penalty を含む。
        `data_rwp` の分離に使う唯一の追加情報
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
    # 【末尾追加】: 既存の位置引数構築を壊さないため必ず末尾に置く (既定 None = 情報なし)。
    rwp: "float | None" = None
    chisq: "float | None" = None

    @property
    def data_rwp(self) -> "float | None":
        """**データ項のみの Rwp** — 段の受理/revert 判定に使う唯一の適合指標。

        penalty が χ² に入っていない (拘束無効・拘束なし) 場合は ``rwp`` を**そのまま**返すので、
        既定経路ではビット同一である (`data_term_rwp` の縮退条件を参照)。
        """
        return data_term_rwp(self.rwp, self.chisq, self.restraint_sum)

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
            "rwp": finite_or_none(self.rwp),
            "chisq": finite_or_none(self.chisq),
            # 【分離値を必ず載せる】: ③ が「penalty 込みの Rwp」を適合値として読むのを防ぐ。
            "data_rwp": finite_or_none(self.data_rwp),
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


def split_weak_variables(
    weak_vars: Sequence[WeakVariable], exempt_tokens: Sequence[str]
) -> "tuple[tuple[WeakVariable, ...], tuple[WeakVariable, ...]]":
    """弱い変数を「``esd/|値|`` が意味を持つもの」と「持たないもの」に分ける (純関数)。

    **なぜ捨てずに分けるか**: 除外する変数を黙って落とすと、「決まらなかったパラメータ」の
    報告 (REQ-SAR-103) が**何を見なかったか**を隠してしまう。除外は「判定できない」であって
    「決まっている」ではないので、第 2 の列として返し呼び出し側が両方報告できるようにする。

    **既定の除外トークン ``dAx/dAy/dAz`` の根拠** (GSAS-II ソース実測):
    座標は ``x`` そのものではなく **``dAx`` = その精密化での x からのシフト**として精密化され、
    ``GSASIIstrIO.py:1732`` が精密化のたびに ``dAx/dAy/dAz`` を **0 に初期化**し、
    ``GSASIIstrMath.ApplyXYZshifts:2940`` が終了時にシフトを座標へ足し込む。したがって
    ``|dAx|`` は「そのサイクルで動いた量」であり、**収束するほど 0 に近づく**。分母が 0 へ
    向かうので ``esd/|dAx|`` は**座標が well-determined であるほど大きくなる** —
    比の向きが逆である。段の途中か最終かに依らない**パラメータ化由来の構造的偽陽性**なので、
    最終判定だけにしても除外は外せない (むしろ収束点で最も強く出る)。

    :param exempt_tokens: 変数名の**部分一致**トークン (空列なら除外なし)
    :returns: ``(判定対象, 判定対象外)`` — どちらも入力の順序 (比の悪い順) を保つ
    """
    if not exempt_tokens:
        return tuple(weak_vars), ()
    judged: list[WeakVariable] = []
    exempt: list[WeakVariable] = []
    for w in weak_vars:
        (exempt if any(tok in w.name for tok in exempt_tokens) else judged).append(w)
    return tuple(judged), tuple(exempt)


def data_term_rwp(
    rwp: Any, chisq: Any, restraint_sum: Any
) -> "float | None":
    """penalty 込みの Rwp から**データ項だけの Rwp** を復元する (GSAS 非依存の純関数)。

    **なぜ必要か**: `restraint_dlg.RefineProgressStub` を渡して restraint を有効にすると、
    `GSASIIstrMath.errRefine`:5210 が残差ベクトル ``M`` へ penalty ``√pWt·pVals`` を**連結**する。
    その ``M`` がそのまま `Rvals['Rwp']` の分子になるため、**Rwp が「データへの合わなさ」を
    表さなくなる**。段の受理/revert は Rwp の比較なので、この値で判定すると
    「拘束が引いた分」を「適合の悪化」と読み違えて全段を revert する (実測: bond weight 1e5 で
    Rwp 3558)。拘束は**引く力**であって適合の悪化ではないので、判定はデータ項で行う。

    **復元の根拠** (GSAS-II ソース実測):

    * `GSASIIstrMath.errRefine`:5199-5213 — ``pSum = Σ pWt·pVals²``、``dlg`` があるときだけ
      ``M = concat(M, √pWt·pVals)``。``Histograms['RestraintSum'] = pSum`` は**ゲートの外**。
    * `GSASIIstrMain`:359 — ``Rvals['chisq'] = Σ fvec²`` (= 連結後の ``M`` の二乗和)。
    * `GSASIIstrMain`:364/368 — ``Rvals['RestraintSum'] = pSum`` /
      ``Rvals['Rwp'] = 100·√(chisq / sumwYo)``。
    * `GSASIIstrMath`:5003-5004/5183 — ``sumwYo`` は**観測強度だけ**から積む (拘束と無関係)。

    分母 ``sumwYo`` が共通なので、それを知らなくても比だけで割れる::

        chisq_data = chisq − RestraintSum
        Rwp_data   = 100·√(chisq_data / sumwYo) = Rwp · √(1 − RestraintSum / chisq)

    **縮退 (元の ``rwp`` をそのまま返す) 条件**:

    * ``restraint_sum`` が 0 以下/非有限 — penalty が無い。既定経路 (拘束無効) はここに落ち、
      **ビット同一**の値が返る (非回帰契約)。
    * ``rwp``/``chisq`` が非有限、``chisq <= 0`` — 情報が無い。
    * ``restraint_sum >= chisq`` — **penalty が chisq に入っていない**証拠。GSAS は
      ``RestraintSum`` をゲートの外で報告するので、``dlg`` を渡していない精密化でも非ゼロの
      値が載る (実測 4.66e9 に対し chisq は Rwp 40% 相当)。ここで引き算すると負の chisq を
      作るため、**引かない**。「情報が無いことを正常と答えない」規律で、推測で補正しない。

    :returns: データ項のみの Rwp。``rwp`` が数値として読めないときのみ ``None``
    """
    base = _as_float(rwp)
    if base is None:
        return None
    penalty = _as_float(restraint_sum)
    total = _as_float(chisq)
    if penalty is None or penalty <= 0.0:
        return base
    if total is None or total <= 0.0 or penalty >= total:
        return base
    return base * math.sqrt(1.0 - penalty / total)


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
        rwp=_as_float(rvals.get("Rwp")),
        chisq=_as_float(rvals.get("chisq")),
        message=str(rvals.get("msg") or ""),
        weak_vars=weak_variables(names, values, sig),
        correlated_pairs=(
            correlated_pairs(names, cov, sig, corr_threshold) if cov is not None else ()
        ),
    )


def values_from_cov_data(cov_data: Mapping[str, Any]) -> dict[str, float]:
    """``covData`` から「変数名 → 精密化値」を取り出す (GSAS 非依存の純写像)。

    ここに置く理由 (D1): 箱拘束の**境界到達がどちら側か** (REQ-SAR-202) を決めるのに変数値が
    要るが、共分散を読む場所を増やすと drift する。読み出しは本モジュールに閉じる。

    値は `GSASIIstrMain.dropOOBvars` が境界へ丸める**前**のもの (covData は丸めの前に組まれる)
    なので、箱の外側にある = どちら側に出たかを一意に決められる。
    長さ不一致・非有限は落とす (fail open — 診断が精密化本体を落とさない)。
    """
    names = _as_sequence(cov_data.get("varyList"))
    values = _as_sequence(cov_data.get("variables"))
    if len(names) != len(values):
        return {}
    out: dict[str, float] = {}
    for name, raw in zip(names, values):
        v = _as_float(raw)
        if v is not None:
            out[str(name)] = v
    return out


def read_variable_values(gpx) -> dict[str, float]:
    """精密化済み ``G2Project`` から「変数名 → 精密化値」を読む (**GSAS 依存はここだけ**)。"""
    try:
        cov_data = gpx.data["Covariance"]["data"]
    except (KeyError, TypeError, AttributeError):
        return {}
    if not isinstance(cov_data, Mapping):
        return {}
    return values_from_cov_data(cov_data)


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
