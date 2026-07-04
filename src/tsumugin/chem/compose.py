"""複数の化学的妥当性スコアの合成 (M4 / REQ-018 / EDGE-007)。

``combine_plausibility``: 複数モジュールの ``PlausibilityResult`` を重み付き幾何平均で合成する。
score=0 のモジュールがあれば合成 0 へ伝播 (降格伝播・除外しない)。空入力は score=1.0 (素通し)。
source は寄与 module id を昇順連結し決定論を担保する (REQ-402)。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .base import PlausibilityResult


def combine_plausibility(
    results: Sequence[PlausibilityResult], *, weights: Mapping[str, float] | None = None
) -> PlausibilityResult:
    """複数モジュールのスコアを重み付き幾何平均で合成する。🔵 REQ-018/EDGE-007

    【合成】: s = Π s_i^(w_i / Σw) (既定は等重み)。score=0 のモジュールがあれば合成 0 へ伝播し
      降格が伝播する (除外はしない, EDGE-007)。source は寄与 module id を昇順連結 (REQ-402)。
    【空入力】: results 空なら score=1.0 (降格なし) を返す (REQ-105 の素通し前提)。
    """
    # 【空入力】: 素通し (降格なし)。REQ-105 🔵
    if not results:
        return PlausibilityResult(score=1.0, rationale="評価モジュールなし (素通し)", source="")

    # 【決定論】: 寄与 module id 昇順で評価順序を固定する (REQ-402) 🔵
    ordered = sorted(results, key=lambda r: r.source)

    # 【重み解決】: 未指定 module は等重み (1.0)。Σw で正規化する。🔵
    resolved_weights = [
        (weights.get(r.source, 1.0) if weights is not None else 1.0) for r in ordered
    ]
    weight_sum = sum(resolved_weights)

    # 【幾何平均】: s = Π s_i^(w_i/Σw)。score=0 は 0^(正の指数)=0 で自然に 0 伝播 (EDGE-007) 🔵
    #   weight_sum<=0 の縮退時は等重み幾何平均へフォールバックし ZeroDivision を避ける。
    if weight_sum <= 0.0:
        exponents = [1.0 / len(ordered) for _ in ordered]
    else:
        exponents = [w / weight_sum for w in resolved_weights]

    combined_score = 1.0
    for r, exponent in zip(ordered, exponents):
        # score が厳密に 0 なら合成も 0 (降格伝播)。負値混入は 0 にクランプして安全化。
        base = max(r.score, 0.0)
        if base == 0.0:
            combined_score = 0.0
            break
        combined_score *= base ** exponent

    # 【source/rationale】: 昇順 module id を決定論連結する (REQ-402) 🔵
    sources = [r.source for r in ordered]
    combined_source = "+".join(sources)
    combined_rationale = "; ".join(f"{r.source}={r.score:.3g}" for r in ordered)

    return PlausibilityResult(
        score=combined_score, rationale=combined_rationale, source=combined_source
    )
