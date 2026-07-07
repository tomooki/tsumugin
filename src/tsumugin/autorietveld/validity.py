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
    uiso_neg_tol: float = 1e-4,
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
    :param uiso_neg_tol: Uiso の許容下限 (負側)。0 近傍・数値ノイズの微小負を許容 (既定 1e-4)
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

    # --- Uiso ∈ [-uiso_neg_tol, uiso_max] ---
    # 未精密化で CIF 値 0 のまま/精密化の数値ノイズで僅かに負の Uiso は物理的に許容する (L9)。
    # 明確に負 (< -uiso_neg_tol, 過剰適合) や上限超過のみを非物理として弾く。
    for name, values in uiso.items():
        for i, u in enumerate(values):
            ok = (u >= -uiso_neg_tol) and (u <= uiso_max)
            checks.append(
                (f"uiso_{name}_{i}", ok, f"Uiso={u:.5f} (要 -{uiso_neg_tol}<=U<={uiso_max})")
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


def _element_radius(specie) -> float:
    """元素の代表半径 (Å)。共有結合半径→原子半径→既定 1.0 の順で取得 (pymatgen)。"""
    el = getattr(specie, "element", specie)
    for attr in ("atomic_radius_calculated", "atomic_radius"):
        r = getattr(el, attr, None)
        if r is not None:
            try:
                return float(r)
            except (TypeError, ValueError):
                pass
    return 1.0


def check_bond_validity(
    structure_path: str,
    refined_cell: Sequence[float] | None = None,
    *,
    bond_tol_lo: float = 0.7,
    bond_tol_hi: float = 1.3,
    expected_coordination: Mapping[str, tuple[int, int]] | None = None,
) -> ValidityReport:
    """精密化構造の**最近接結合距離**と (任意) **配位数**の物理妥当性を判定する (FR-335)。

    誤構造が偶然 Rwp に合う場合を、原子間距離・配位で棄却するための追加ゲート。最近接原子対の距離が
    元素半径和の `bond_tol_lo`〜`bond_tol_hi` 倍に収まるか (下限割れ=セル崩壊・上限超え=過膨張) を検査。
    `expected_coordination` 指定時は pymatgen `CrystalNN` で元素別配位数の範囲も検査する。

    pymatgen 不在・構造読込失敗は **passed=True + 警告** に縮退する (gate, クラッシュさせない; REQ-1013)。

    :param structure_path: 構造ファイル (CIF)
    :param refined_cell: 精密化格子 (a,b,c,α,β,γ)。指定時は構造の格子をこれに置換して検査
    :param bond_tol_lo: 最近接距離の許容下限倍率 (半径和に対する)
    :param bond_tol_hi: 最近接距離の許容上限倍率
    :param expected_coordination: 元素記号 → (配位数下限, 上限)。None なら配位数検査を省略
    """
    try:
        from pymatgen.core import Lattice, Structure
    except Exception:
        return ValidityReport(
            passed=True, checks=(),
            warnings=("pymatgen 不在: 結合距離/配位数チェックを skip",),
        )
    try:
        structure = Structure.from_file(structure_path)
    except Exception as exc:  # noqa: BLE001 — 読込失敗は非致命 skip
        return ValidityReport(
            passed=True, checks=(), warnings=(f"構造読込失敗 skip: {exc}",),
        )

    if refined_cell is not None and len(refined_cell) >= 6:
        lat = Lattice.from_parameters(*(float(x) for x in refined_cell[:6]))
        structure = Structure(lat, structure.species, structure.frac_coords)

    checks: list[tuple[str, bool, str]] = []
    warnings: list[str] = []

    # --- 最近接結合距離 (PBC 最小像; distance_matrix は周期境界を考慮) ---
    n = len(structure)
    if n >= 2:
        dm = structure.distance_matrix
        min_ratio = float("inf")
        worst = (0.0, 0.0)
        for i in range(n):
            ri = _element_radius(structure[i].specie)
            for j in range(i + 1, n):
                d = float(dm[i][j])
                expected = ri + _element_radius(structure[j].specie)
                if expected <= 0.0:
                    continue
                ratio = d / expected
                if ratio < min_ratio:
                    min_ratio = ratio
                    worst = (d, expected)
        if min_ratio < float("inf"):
            ok = bond_tol_lo <= min_ratio <= bond_tol_hi
            checks.append((
                "min_bond_distance", ok,
                f"最近接 {worst[0]:.3f}Å / 半径和 {worst[1]:.3f}Å = {min_ratio:.3f} "
                f"(要 {bond_tol_lo}<=r<={bond_tol_hi})",
            ))

    # --- 配位数 (任意, CrystalNN) ---
    if expected_coordination:
        try:
            from pymatgen.analysis.local_env import CrystalNN

            nn = CrystalNN()
            for i, site in enumerate(structure):
                sym = site.specie.symbol
                rng = expected_coordination.get(sym)
                if rng is None:
                    continue
                cn = nn.get_cn(structure, i)
                ok = rng[0] <= cn <= rng[1]
                checks.append((
                    f"coordination_{sym}_{i}", ok,
                    f"CN={cn} (要 {rng[0]}<=CN<={rng[1]})",
                ))
        except Exception as exc:  # noqa: BLE001 — CrystalNN 失敗は非致命 skip
            warnings.append(f"配位数解析 skip: {exc}")

    passed = all(ok for _, ok, _ in checks)
    return ValidityReport(passed=passed, checks=tuple(checks), warnings=tuple(warnings))
