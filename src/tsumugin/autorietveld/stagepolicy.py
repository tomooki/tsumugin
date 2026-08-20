"""段の受理/revert/no-op 判定 (M12 T7 / Issue #175) — 純関数・エンジン非依存。

`run_auto_rietveld` (GSAS-II) と `run_topas_rietveld` (TOPAS) は**同じ方針**で段を受け取る:

1. バックエンドの失敗は例外でなく ``rwp=inf`` に変換され、ここで revert に落ちる (不変条件)。
2. 悪化した段は revert して**その段なしで続行**する (REQ-105 / FR-202)。
3. 何も動かなかった段 (指標がビット同一・母数も増えない) は **revert せず検出だけ**する
   (REQ-SAR-102)。「改善しなかった」と「無言で失敗した」を Rwp からは区別できないため、
   区別できる事実として残す。

**方針だけをここに置く**: スナップショット復元 (`.gpx` コピー / 文書の巻き戻し)・
ledger のキー・救済凍結といった**engine 固有の作用**は各 engine に残す。実測で積み上げた
振舞い (無言失敗検出・試料ジオメトリ整合・格子崩壊ガード) には触らない。

**なぜ共有するか**: 判定が別実装だと、片方で学んだ検出がもう片方に効かない。実害として、
no-op 検出は GSAS 側にしか無く、TOPAS の T4 では S3 phase_fractions / S5 occupancy が
「rwp・n_params ともビット同一で ``reverted`` も立たない」まま完走していた (2026-08-19 実測)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["StageDecision", "StageMetrics", "decide_stage"]

#: 悪化とみなす閾値 (数値ノイズで段を捨てないための余裕)。両エンジンの実測既定。
DEFAULT_WORSEN_EPS = 1e-6


@dataclass(frozen=True)
class StageMetrics:
    """段 1 つ分の指標。

    :param rwp: **データ項のみの Rwp** (拘束 penalty を含まない)。受理/revert の判定は
        必ずこちらで行う — penalty は「引く力」であって適合の悪化ではない。
    :param gof: goodness of fit。
    :param n_params: 精密化した変数の数 (母数)。
    """

    rwp: float
    gof: float
    n_params: int


@dataclass(frozen=True)
class StageDecision:
    """段をどう扱うかの判断 (**作用は持たない**)。

    :param reverted: 直前の受理状態へ戻すべきか。
    :param is_noop: 受理はするが「何も動いていない」段か (検出のみ・revert しない)。
    :param reason: revert の理由 (``""`` = 受理 / ``"unconverged"`` / ``"non_finite"`` /
        ``"worse"``)。**なぜ戻したか**を ledger に残せるようにする。
    """

    reverted: bool
    is_noop: bool
    reason: str


def decide_stage(
    previous: StageMetrics,
    trial: StageMetrics,
    *,
    worsen_eps: float = DEFAULT_WORSEN_EPS,
    unconverged: bool = False,
    detect_noop: bool = True,
) -> StageDecision:
    """段の試行結果を受理するか戻すかを決める。

    :param previous: 直前の**受理済み**状態の指標 (初段は ``rwp=inf``)。
    :param trial: この段を適用して精密化した結果の指標。
    :param worsen_eps: これを超える悪化を revert とみなす。
    :param unconverged: 収束判定に失敗した段か (GSAS の WS-1 ゲート)。Rwp が下がっていても
        受理しない — 収束していない値は「良くなった」証拠にならない。
    :param detect_noop: no-op 検出を行うか (GSAS 側は ``StabilityOptions.detect_noop_stages``
        で opt-in)。
    """
    if unconverged:
        return StageDecision(reverted=True, is_noop=False, reason="unconverged")
    if not math.isfinite(trial.rwp):
        return StageDecision(reverted=True, is_noop=False, reason="non_finite")
    if trial.rwp > previous.rwp + worsen_eps:
        return StageDecision(reverted=True, is_noop=False, reason="worse")
    return StageDecision(
        reverted=False, is_noop=_is_noop(previous, trial, detect_noop), reason=""
    )


def _is_noop(previous: StageMetrics, trial: StageMetrics, detect: bool) -> bool:
    """その段が「何もしていない」か (REQ-SAR-102)。

    条件は **``n_params`` が増えず、rwp と gof が直前段とビット同一**であること。GSAS-II の
    無言失敗 (`engine._capture_refine_status`)、実元素数を超えた固定ランクの段 (T1 実測)、
    プロファイル段が全ヒストグラムで除外される多相 TOF (T4 実測) がこのクラスに落ちる。

    非有限は判定しない — ``inf == inf`` を「ビット同一」と読むと初段の失敗を全部 no-op と
    誤報する (revert 経路が既に扱う別クラスの失敗である)。
    """
    if not detect:
        return False
    if not (math.isfinite(trial.rwp) and math.isfinite(previous.rwp)):
        return False
    return (
        trial.n_params <= previous.n_params
        and trial.rwp == previous.rwp
        and trial.gof == previous.gof
    )
