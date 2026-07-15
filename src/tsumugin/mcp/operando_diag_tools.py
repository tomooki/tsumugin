"""薄い MCP 4 ツール (operando 診断 ②) — ① 決定論アドバイザの計器 (Issue architecture §2)。

閉ループ丸ごとは出さない。③ (`skills/operando-diagnose`) が以下を反復駆動して系列結果を疑う
(architecture.md §0/§2, 二重反転回避): **判断しない・返すだけ**。

- ``assess_data_quality``: 観測ファイル (+esd) → 背景減算検出 + 2θ 上限提案 (計器)。
- ``residual_report``: (x, yobs, ycalc[, weight]) → baseline/peak 分解 + 上位未説明特徴 (計器)。
- ``check_phase_set``: 系列結果 (JSON) → 相集合完全性 + 相ごとの非単調性フラグ (計器)。
- ``repair_frames``: 系列結果 + frames + phases → 不連続検出 + 近傍 warm-start 修復 (Rwp 改善時のみ
  採用の自己検証可能な規則なので①/②に置ける安全部分集合)。改善しなかったものは
  ``needs_model_revision`` として③へ上げる。

**SDK 非依存**: 素の型 dict のみを返す (json.dumps allow_nan=False 安全, 浮動小数は
``finite_or_none``)。GSAS は ``repair_frames`` の既定 runner でのみ遅延 import。runner は注入可能
(テストは決定論スタブ)。エラーは既存ツール群 (``mem_tools``/``tools.identify_phases``) と同型の
``{"error", "error_type"}`` (or ``{"error": ...}``) dict へ縮退し、例外を送出しない。

信頼性: 🔵 docs/design/operando-diagnosis/architecture.md §2 の ② 4 ツール表と 1:1。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Mapping, Sequence

import numpy as np

from .._json import finite_or_none
from ..autorietveld import PhaseSpec
from ..insitu.model import FrameSpec
from .insitu_tools import _result_from_dict

if TYPE_CHECKING:
    from ..autorietveld.residual_report import ResidualReport

__all__ = [
    "OPERANDO_DIAG_TOOLS",
    "assess_data_quality",
    "check_phase_set",
    "repair_frames",
    "residual_report",
    "residual_report_to_dict",
]


def residual_report_to_dict(rep: "ResidualReport") -> dict[str, object]:
    """``ResidualReport`` を素の型 dict へ (json.dumps allow_nan=False 安全)。

    **単一情報源**: 本ツールの ``residual_report`` と ``rietveld_tools._result_to_dict``
    (``auto_rietveld`` の出力に同梱する経路) の双方がこれを使い、③ から見た残差レポートの
    形が経路によらず一致することを保証する。
    """
    return {
        "rwp": finite_or_none(rep.rwp),
        "peak_only_rwp": finite_or_none(rep.peak_only_rwp),
        "baseline_numerator_fraction": finite_or_none(rep.baseline_numerator_fraction),
        "peak_numerator_fraction": finite_or_none(rep.peak_numerator_fraction),
        "angular_rwp": [
            [finite_or_none(lo), finite_or_none(hi), finite_or_none(v)]
            for lo, hi, v in rep.angular_rwp
        ],
        "top_features": [
            {
                "two_theta": finite_or_none(f.two_theta),
                "residual": finite_or_none(f.residual),
                "obs": finite_or_none(f.obs),
            }
            for f in rep.top_features
        ],
    }


def _load_pattern_with_esd(
    path: str, data_format: str | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """観測ファイルを (two_theta, intensity, esd|None) へ読む。

    ``reference.io`` の各ローダーは esd (3 列目) を破棄するため、既定の ``XY`` (2〜3 列 ascii)
    は numpy で直接読み esd を保持する。他形式 (XRDML/FXYE/GSAS 等) は ``reference.io.load_pattern``
    に委譲し esd は None (未対応形式では esd を判別的に使わない; ``detect_background_subtracted``
    も esd を補助情報としてのみ使う設計と整合)。
    """
    fmt = (data_format or "XY").upper()
    if fmt == "XY":
        arr = np.loadtxt(path, comments="#")
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        if arr.shape[1] < 2:
            raise ValueError(f"XY データは2列以上必要です: {path!r} (実際 {arr.shape[1]} 列)")
        x = arr[:, 0].astype(float)
        y = arr[:, 1].astype(float)
        esd = arr[:, 2].astype(float) if arr.shape[1] >= 3 else None
        return x, y, esd

    from ..reference.io import load_pattern

    x, y = load_pattern(path, fmt)
    return x, y, None


def assess_data_quality(
    path: str,
    *,
    data_format: str | None = None,
    excluded_regions: Sequence[Sequence[float]] | None = None,
    reason: str = "",
) -> dict:
    """観測ファイルの背景減算検出 + 2θ 上限提案を返す (計器・① ``dataquality`` へ委譲)。

    J1 (データ品質を精密化前に問う) の入力。``is_subtracted=True`` は「生データがあれば使うべき」
    という助言のみで、ここでは何も変更しない (提案≠適用)。

    :param path: 観測データファイルパス
    :param data_format: ``FrameSpec.data_format`` と同語彙 ("XY"/"XRDML"/"FXYE"/"GSAS"/"XYE"、
        既定 None は "XY" 扱い)。"XY" のみ esd (3 列目) を保持する
    :param excluded_regions: 寄生ピーク等を 2θ 上限提案から除外する区間 ``[lo, hi]`` の列
        (渡さないと寄生ピークまで信号終端として拾われる, architecture.md §3 手順1 の注意)
    :returns: ``is_subtracted``/``confidence``/``reasons``/``recommendation``/``baseline_level``/
        ``peak_max``/``suggested_two_theta_limit``。読み込み失敗は ``{"error", "error_type"}``
    """
    from ..autorietveld.dataquality import detect_background_subtracted, suggest_two_theta_limit

    try:
        x, y, esd = _load_pattern_with_esd(path, data_format)
    except (OSError, ValueError, IndexError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    report = detect_background_subtracted(x, y, esd)
    regions = (
        tuple((float(lo), float(hi)) for lo, hi in excluded_regions)
        if excluded_regions
        else None
    )
    limit = suggest_two_theta_limit(x, y, excluded_regions=regions)

    return {
        "is_subtracted": bool(report.is_subtracted),
        "confidence": finite_or_none(report.confidence),
        "reasons": list(report.reasons),
        "recommendation": report.recommendation,
        "baseline_level": finite_or_none(report.baseline_level),
        "peak_max": finite_or_none(report.peak_max),
        "suggested_two_theta_limit": finite_or_none(limit),
        "reason": reason,
    }


def residual_report(
    x: Sequence[float],
    yobs: Sequence[float],
    ycalc: Sequence[float],
    weight: Sequence[float] | None = None,
    *,
    baseline_cut: float | None = None,
    baseline_k: float = 3.0,
    n_bins: int = 5,
    n_features: int = 6,
    feature_min_separation: float = 0.15,
    reason: str = "",
) -> dict:
    """残差 (obs-calc) を baseline/peak 寄与・角度ビン・上位特徴に分解する (計器・① へ委譲)。

    **本ツールは ③ の主経路ではない**。実データの残差配列は 2392 点 × 3 本 ≈ 150KB あり、
    **配列を MCP 境界に跨がせてはならない**。レポート自体は小さい (数個の float + ~6 特徴) ため、
    サーバ側で算出して返すのが正しい: ``auto_rietveld`` の出力に ``residual_report`` キーとして
    同梱してある (``rietveld_tools._result_to_dict`` → ``residual_report_from_result``)。
    ③ (MCP しか触れない skill) は通常そちらを読む。

    本ツールは**既に配列を手元に持つ呼び出し側**のための明示入力経路として残す (算出元を問わない)。

    :param x: 2θ (または TOF) 配列
    :param yobs: 観測強度
    :param ycalc: 計算強度
    :param weight: Rwp の重み。None なら計数統計慣習 ``w=1/max(yobs,1)`` を自動導出
    :returns: ``rwp``/``peak_only_rwp``/``baseline_numerator_fraction``/``peak_numerator_fraction``/
        ``angular_rwp``/``top_features``。失敗 (長さ不一致等) は ``{"error", "error_type"}``
    """
    from ..autorietveld.residual_report import residual_report as _residual_report

    try:
        rep = _residual_report(
            x,
            yobs,
            ycalc,
            weight,
            baseline_cut=baseline_cut,
            baseline_k=baseline_k,
            n_bins=n_bins,
            n_features=n_features,
            feature_min_separation=feature_min_separation,
        )
    except ValueError as exc:
        return {"error": str(exc), "error_type": "ValueError"}

    out = residual_report_to_dict(rep)
    out["reason"] = reason
    return out


def check_phase_set(
    result: Mapping[str, object],
    *,
    min_amplitude: float = 0.1,
    max_turning_points: int = 2,
    reason: str = "",
) -> dict:
    """相集合の完全性 + 相ごとの分率非単調性を返す (計器・① ``insitu.phaseset`` へ委譲)。

    J5/J7 (計量の近い相が互いの強度を肩代わりし、Rwp が良好なまま非物理な描像を生む) の検出器。
    ``sequential_rietveld``/``repair_frames`` が返す系列結果 dict をそのまま渡せる
    (``insitu_tools._result_from_dict`` と往復可能)。

    :param result: ``sequential_rietveld`` 等が返す系列結果 (JSON dict)
    :param min_amplitude: ``flag_nonmonotonic_fraction`` の振幅フィルタ (既定 0.1)
    :param max_turning_points: 同上の turning point 上限 (既定 2; 単一ドームまでは正常)
    :returns: ``is_complete``/``union``/``frames_with_missing``/``recommendation``/``phases``
        (和集合の全相について ``{phase, turning_points, flagged, reason}``)
    """
    from ..insitu.phaseset import flag_nonmonotonic_fraction, suggest_phase_set_completion

    seq = _result_from_dict(result)
    completion = suggest_phase_set_completion(seq)

    phases = []
    for phase_name in completion.union:
        rep = flag_nonmonotonic_fraction(
            seq, phase_name, min_amplitude=min_amplitude, max_turning_points=max_turning_points
        )
        phases.append(
            {
                "phase": rep.phase_name,
                "turning_points": rep.turning_points,
                "flagged": bool(rep.flagged),
                "reason": rep.reason,
            }
        )

    return {
        "is_complete": bool(completion.is_complete),
        "union": list(completion.union),
        "frames_with_missing": [
            [frame_index, list(missing)] for frame_index, missing in completion.frames_with_missing
        ],
        "recommendation": completion.recommendation,
        "phases": phases,
        "reason": reason,
    }


def repair_frames(
    result: Mapping[str, object],
    frames: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    *,
    rwp_abs: float | None = None,
    rwp_delta: float = 1.8,
    frac_delta: float = 0.15,
    rwp_tol: float = 0.1,
    min_block: int = 2,
    runner: Callable | None = None,
    reason: str = "",
) -> dict:
    """不連続フレームを検出し近傍 warm-start で修復する (① ``insitu.repair`` へ委譲)。

    ``repairs`` は Rwp が ``rwp_tol`` 超改善した場合のみ採用 (自己検証可能な規則なので①/②に
    置ける安全部分集合)。改善しなかった/試せなかったフレームは ``needs_model_revision`` として
    ③ (モデル改訂の判断) へ上げる。

    :param result: ``sequential_rietveld`` 等が返す系列結果 (JSON dict)
    :param frames: ``result["frames"]`` と同順・同数の ``FrameSpec.to_dict()`` 列
    :param phases: 系列で使われている全相の ``PhaseSpec.to_dict()`` 列 (相名で引く辞書のソース)
    :param runner: ``(frame, phases, initial_cells) -> AutoRietveldResult``。None なら
        GSAS 駆動の既定 runner (``insitu.engine`` と同じ既定, ``sequential_rietveld`` に倣う)
    :returns: ``repairs``/``needs_model_revision``/``systematic_hint``/``discontinuities``。
        失敗 (frames と result のフレーム数不一致等) は ``{"error", "error_type"}``
    """
    from ..insitu.engine import _default_gsas_runner
    from ..insitu.model import SequentialConfig
    from ..insitu.repair import detect_discontinuities, repair_isolated

    try:
        seq = _result_from_dict(result)
        frame_specs = [FrameSpec.from_dict(f) for f in frames]
        phase_specs = [PhaseSpec.from_dict(p) for p in phases]
    except (KeyError, ValueError, TypeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    discontinuities = detect_discontinuities(
        seq, rwp_abs=rwp_abs, rwp_delta=rwp_delta, frac_delta=frac_delta
    )
    run = runner or _default_gsas_runner(SequentialConfig())

    report = repair_isolated(
        frame_specs,
        seq,
        phase_specs,
        run,
        discontinuities,
        rwp_tol=rwp_tol,
        min_block=min_block,
    )

    return {
        "repairs": [
            {
                "frame": r.frame_index,
                "rwp_before": finite_or_none(r.rwp_before),
                "rwp_after": finite_or_none(r.rwp_after),
                "source": r.source,
                "phase_fractions": {k: finite_or_none(v) for k, v in r.phase_fractions.items()},
            }
            for r in report.repairs
        ],
        "needs_model_revision": list(report.needs_model_revision),
        "systematic_hint": [list(block) for block in report.systematic_hint],
        "discontinuities": [
            {
                "frame": d.frame_index,
                "rwp": finite_or_none(d.rwp),
                "reasons": list(d.reasons),
            }
            for d in discontinuities
        ],
        "reason": reason,
    }


# 【M-later ツールレジストリ】: MCP_TOOLS へマージする 4 ツール (architecture.md §2)。
OPERANDO_DIAG_TOOLS: Mapping[str, object] = {
    "assess_data_quality": assess_data_quality,
    "residual_report": residual_report,
    "check_phase_set": check_phase_set,
    "repair_frames": repair_frames,
}
