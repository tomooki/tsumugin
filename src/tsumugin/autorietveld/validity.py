"""物理的妥当性ゲート (M7 達成目標判定)。

自動 Rietveld の精密化結果が物理的に妥当か (格子定数の妥当範囲・Uiso 正値かつ上限内・
占有率 ∈[0,1]・相分率和=1 制約・収束) を判定する。純関数 (GSAS 非依存) のため
ユニットテスト可能。engine は GSAS-II から抽出した値を渡す。

信頼性: 🔵 設計 architecture.md §2.3 / M7 達成目標 (格子・Uiso・占有率・制約充足)。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .model import ValidityReport

# 格子パラメータのラベル (a,b,c は長さ, α,β,γ は角度)
_CELL_LABELS = ("a", "b", "c", "alpha", "beta", "gamma")


def check_validity(
    *,
    refined_cells: Mapping[str, Sequence[float]],
    reference_cells: Mapping[str, Sequence[float]],
    uiso: Mapping[str, Sequence[float]],
    occupancies: Mapping[str, Sequence[float]],
    phase_fractions: Sequence[float] | None = None,
    converged: bool = True,
    lattice_tol_pct: float = 0.5,
    uiso_max: float = 0.1,
    constraint_tol: float = 2e-2,
) -> ValidityReport:
    """精密化結果の物理的妥当性を判定する。

    :param refined_cells: 相名 → 精密化後の格子 (a,b,c,α,β,γ)
    :param reference_cells: 相名 → 参照格子 (CIF 初期値/文献)
    :param uiso: 相名 → Uiso 値の列
    :param occupancies: 相名 → 占有率の列
    :param phase_fractions: 相分率の列 (多相のとき和=1 を検査。None なら検査省略)
    :param converged: 精密化が収束したか
    :param lattice_tol_pct: 格子定数の許容ずれ (%)
    :param uiso_max: Uiso の物理的上限 (Å²)
    :param constraint_tol: 制約 (相分率和) の許容誤差
    :returns: ValidityReport (passed / 項目別チェック / 警告)
    """
    checks: list[tuple[str, bool, str]] = []
    warnings: list[str] = []

    # --- 格子定数の妥当範囲 ---
    for name, cell in refined_cells.items():
        ref = reference_cells.get(name)
        if ref is None:
            warnings.append(f"{name}: 参照格子なし (格子妥当性を検査せず)")
            continue
        for label, val, refval in zip(_CELL_LABELS, cell, ref):
            if refval == 0:
                continue
            dev_pct = abs(val - refval) / abs(refval) * 100.0
            ok = dev_pct <= lattice_tol_pct
            checks.append(
                (
                    f"lattice_{name}_{label}",
                    ok,
                    f"{val:.5f} vs ref {refval:.5f} ({dev_pct:.3f}% dev, tol {lattice_tol_pct}%)",
                )
            )

    # --- Uiso ∈ (0, uiso_max] ---
    for name, values in uiso.items():
        for i, u in enumerate(values):
            ok = (u > 0.0) and (u <= uiso_max)
            checks.append(
                (f"uiso_{name}_{i}", ok, f"Uiso={u:.5f} (要 0<U<={uiso_max})")
            )

    # --- 占有率 ∈ [0, 1] ---
    for name, values in occupancies.items():
        for i, occ in enumerate(values):
            ok = 0.0 <= occ <= 1.0 + 1e-9
            checks.append(
                (f"occupancy_{name}_{i}", ok, f"frac={occ:.4f} (要 0<=f<=1)")
            )

    # --- 相分率和=1 制約 ---
    if phase_fractions is not None and len(phase_fractions) > 1:
        total = float(sum(phase_fractions))
        ok = abs(total - 1.0) <= constraint_tol
        checks.append(
            ("phase_fraction_sum", ok, f"Σfrac={total:.4f} (要 |Σ-1|<={constraint_tol})")
        )

    # --- 収束 (非致命: 警告扱い) ---
    if not converged:
        warnings.append("精密化が収束していません (converged=False)")

    passed = all(ok for _, ok, _ in checks)
    return ValidityReport(passed=passed, checks=tuple(checks), warnings=tuple(warnings))
