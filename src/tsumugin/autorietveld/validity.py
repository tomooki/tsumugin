"""物理的妥当性ゲート (M7 達成目標判定)。

自動 Rietveld の精密化結果が物理的に妥当か (格子定数の妥当範囲・Uiso 正値かつ上限内・
占有率 ∈[0,1]・相分率和=1 制約・収束) を判定する。純関数 (GSAS 非依存) のため
ユニットテスト可能。engine は GSAS-II から抽出した値を渡す。

信頼性: 🔵 設計 architecture.md §2.3 / M7 達成目標 (格子・Uiso・占有率・制約充足)。
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from .model import Radiation, ValidityReport

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


# =====================================================================
# プロファイル物理性ガード (revert 用 hard + 警告用 soft)。numpy 不要 (stdlib math)。
# =====================================================================

# 幅二乗が発散する 2θ 端 (tanθ→∞) を避けるためのクランプ範囲 (度)。
_TT_MIN = 0.01
_TT_MAX = 179.0


def _gauss_min_over_range(u: float, v: float, w: float, lo_deg: float, hi_deg: float) -> float:
    """CW ガウス幅二乗 H_G² = U·tan²θ + V·tanθ + W の測定 2θ レンジ区間最小 (端点 + 頂点)。

    引数は 2θ (度)。θ = 2θ/2。2次関数 (tanθ の) なので端点と、レンジ内にある頂点 tanθ*=-V/2U の
    3 点で厳密に区間最小が求まる (U=0 の線形退化は頂点を省く)。
    """
    lo = max(_TT_MIN, min(lo_deg, hi_deg))
    hi = min(_TT_MAX, max(lo_deg, hi_deg))
    t_lo = math.tan(math.radians(lo / 2.0))
    t_hi = math.tan(math.radians(hi / 2.0))

    def h(t: float) -> float:
        return u * t * t + v * t + w

    cands = [h(t_lo), h(t_hi)]
    if u != 0.0:
        t_star = -v / (2.0 * u)
        if min(t_lo, t_hi) <= t_star <= max(t_lo, t_hi):
            cands.append(h(t_star))
    return min(cands)


def _tof_sigma_min_over_range(
    s0: float, s1: float, s2: float, d_lo: float, d_hi: float
) -> float:
    """TOF ガウス分散 σ² = sig0 + sig1·d² + sig2·d⁴ の d レンジ区間最小 (x=d² の 2 次式)。

    x=d² と置くと σ² = s0 + s1·x + s2·x² の 2 次式。端点 x=d_lo²,d_hi² と、レンジ内頂点
    x*=-s1/2s2 で区間最小を求める (s2=0 の線形退化は頂点を省く)。
    """
    x_lo = min(d_lo, d_hi) ** 2
    x_hi = max(d_lo, d_hi) ** 2

    def s(x: float) -> float:
        return s0 + s1 * x + s2 * x * x

    cands = [s(x_lo), s(x_hi)]
    if s2 != 0.0:
        x_star = -s1 / (2.0 * s2)
        if x_lo <= x_star <= x_hi:
            cands.append(s(x_star))
    return min(cands)


def _check_cw_profile(
    i: int,
    prof: Mapping[str, tuple[float, bool]],
    rng: tuple[float, float] | None,
    checks: list[tuple[str, bool, str]],
    warnings: list[str],
    sign_tol: float,
    shl_soft_max: float,
    width_floor: float,
) -> None:
    """CW (X線/CW中性子) プロファイルの soft 判定 (警告のみ・revert しない)。

    **設計注記 (GSAS-II getFWHM 準拠)**: GSAS は CW ガウス分散を ``sqrt(max(0.001, U·tan²θ+V·tanθ+W))``
    と**下駄履き (0.001 でクランプ)** して計算するため、U,V,W が負で H_G² がレンジ内で負に振れても
    非物理ではない (実 T1 fluoroapatite の良好フィットは U=-1.96 等に収束する)。ローレンツ (X,Y) の
    負値も反射位置以外では総 FWHM に影響せず GSAS が許容する。よって CW 係数の符号は revert 基準に
    ならず、情報提供の警告に留める。真の発散 (値が NaN/inf) は呼出側で全放射源共通の hard 判定を行う。
    """
    # --- ガウス幅 (情報): レンジ内区間最小が負なら警告 (GSAS はクランプするので revert しない) ---
    if all(k in prof for k in ("U", "V", "W")) and rng is not None:
        u, v, w = prof["U"][0], prof["V"][0], prof["W"][0]
        mn = _gauss_min_over_range(u, v, w, rng[0], rng[1])
        if mn <= width_floor:
            warnings.append(
                f"hist{i} H_G²_min={mn:.4g}<=0 (GSAS はガウス分散を 0.001 でクランプ・非 revert) [参考]"
            )
    # --- ローレンツ X,Y (情報): 負値を警告 ---
    for key in ("X", "Y"):
        if key in prof and prof[key][0] < -sign_tol:
            warnings.append(f"hist{i} {key}={prof[key][0]:.4g} 負 (総 FWHM は反射位置依存・非 revert) [参考]")
    # --- 非対称 SH/L (情報): 負値・soft 上限超を警告 ---
    if "SH/L" in prof:
        val = prof["SH/L"][0]
        if val < -sign_tol:
            warnings.append(f"hist{i} SH/L={val:.4g} 負 [参考]")
        elif val > shl_soft_max:
            warnings.append(f"hist{i} SH/L={val:.4g} > soft上限 {shl_soft_max} [要注意]")


def _check_tof_profile(
    i: int,
    prof: Mapping[str, tuple[float, bool]],
    rng: tuple[float, float] | None,
    checks: list[tuple[str, bool, str]],
    warnings: list[str],
    sign_tol: float,
) -> None:
    """TOF プロファイルの hard 判定 (真の発散のみ)。解放済 (refined=True) パラメータのみ hard。

    **設計注記 (GSAS-II getFWHM 準拠)**: TOF ガウス分散は ``sqrt(σ²)`` を**クランプせず**計算するため
    (`sigTOF`), σ²<0 は NaN を生む真の非物理。立上り alpha・減衰 beta-0 は式中 ``alp/d``,``bet0+…`` から
    ``1/α``,``1/β`` で発散するため strict > 0 が必須。beta-1 は d 依存の補正係数で単独符号制約を課さない。
    """
    # --- ガウス分散 σ²≥0 (sig-0/1/2, 解放済のみ hard; GSAS は sqrt をクランプしない) ---
    sig_keys = ("sig-0", "sig-1", "sig-2")
    if any(prof.get(k, (0.0, False))[1] for k in sig_keys) and rng is not None:
        s0 = prof.get("sig-0", (0.0, False))[0]
        s1 = prof.get("sig-1", (0.0, False))[0]
        s2 = prof.get("sig-2", (0.0, False))[0]
        mn = _tof_sigma_min_over_range(s0, s1, s2, rng[0], rng[1])
        checks.append(
            (f"tof_sigma_hist{i}", mn >= -sign_tol, f"σ²_min={mn:.4g} (要 >=-{sign_tol})")
        )

    # --- 立上り/減衰 strict-pos (alpha, beta-0; 解放済のみ hard) ---
    for key in ("alpha", "beta-0"):
        if key in prof:
            val, ref = prof[key]
            if ref:
                checks.append((f"tof_{key}_hist{i}", val > 0.0, f"{key}={val:.4g} (要 >0)"))
            elif val <= 0.0:
                warnings.append(f"hist{i} {key}={val:.4g} <=0 だが未解放 [参考]")


def check_profile_physicality(
    *,
    profiles: Sequence[Mapping[str, tuple[float, bool]]],
    radiations: Sequence[Radiation],
    ranges: Sequence[tuple[float, float] | None],
    sign_tol: float = 1e-3,
    shl_soft_max: float = 0.1,
    width_floor: float = 0.0,
) -> ValidityReport:
    """精密化後プロファイルの物理的妥当性を判定する (revert 用 hard + 警告用 soft)。

    材料非依存の物理法則のみで判定する。**hard (passed=False = revert) は真の発散のみ**に限定する
    (GSAS-II getFWHM の実挙動に整合):

    - **全放射源共通 hard**: 解放済パラメータの値が NaN/inf (発散)。
    - **TOF hard**: ガウス分散 σ²=sig0+sig1·d²+sig2·d⁴ のレンジ区間最小 < -sign_tol (GSAS は sqrt(σ²) を
      クランプしないため NaN 化); alpha, beta-0 ≤ 0 (1/α,1/β 発散)。解放済のときのみ hard。
    - **CW soft (warnings のみ)**: U,V,W の H_G² 負値 (GSAS が 0.001 にクランプするため非 revert)・X,Y 負値
      (総 FWHM は反射位置依存)・SH/L 負値/soft 上限超。良好フィットでも U<0,Y<0 に収束しうるため revert
      基準にしない (実 T1/T3/T4 非回帰の要)。

    hard は当該パラメータ群に解放済 (refined=True) が 1 つ以上あるときのみ (未解放の初期 instprm 由来で
    誤 revert しない, REQ-102)。抽出不能 (空 dict)・レンジ None は当該判定を skip する (EDGE-001/003)。

    :param profiles: 各 hist の {key: (value, refined)}
    :param radiations: 各 hist の放射源 (profiles と同順)
    :param ranges: 各 hist の評価レンジ (CW=2θ°, TOF=d)。None はレンジ依存判定を skip
    :param sign_tol: 符号/非負判定の負側許容 (数値ノイズ用)
    :param shl_soft_max: SH/L の soft 上限 (超過は警告のみ・revert しない)
    :param width_floor: ガウス幅二乗の警告下限 (既定 0.0)
    :returns: ValidityReport (passed=全 hard 通過 / checks / warnings)
    """
    checks: list[tuple[str, bool, str]] = []
    warnings: list[str] = []

    for i, (prof, rad, rng) in enumerate(zip(profiles, radiations, ranges)):
        if not prof:
            warnings.append(f"hist{i}: プロファイル抽出不能につき物理性判定を skip")
            continue
        # 全放射源共通: 解放済パラメータの NaN/inf は真の発散 → hard。
        for key, (val, ref) in prof.items():
            if ref and not math.isfinite(val):
                checks.append((f"nonfinite_{key}_hist{i}", False, f"{key}={val} 非有限値 [発散]"))
        if getattr(rad, "is_tof", False):
            _check_tof_profile(i, prof, rng, checks, warnings, sign_tol)
        else:
            _check_cw_profile(i, prof, rng, checks, warnings, sign_tol, shl_soft_max, width_floor)

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


def check_initial_uiso(
    atom_uiso: Mapping[str, Mapping[str, float]],
    *,
    uiso_min: float = 1e-3,
    uiso_max: float = 0.05,
) -> tuple[str, ...]:
    """初期 Uiso の妥当帯検査 (FR-318 / REQ-318-005) — **精密化前**に警告を返す。🔵

    電気化学制約解析では占有率-Uiso 縮退を避けるため Uiso を固定する。固定値が非物理
    (小さすぎ/大きすぎ) だと占有率へ系統誤差が転嫁されるため、精密化を始める前に警告する
    (abort はしない — 判断は第3層)。

    :param atom_uiso: 相名→原子ラベル→初期 Uiso [Å²] (ラベルキー)
    :param uiso_min: 下限 (既定 1e-3 Å²; 室温の熱振動下限の目安)
    :param uiso_max: 上限 (既定 0.05 Å²; 可動イオンはより大きい値が物理的なこともある —
        その場合は上限を緩めて呼ぶ)
    :returns: 警告文の列 (空 = 全原子妥当)
    """
    warnings: list[str] = []
    for phase, atoms in atom_uiso.items():
        for label, u in atoms.items():
            if not math.isfinite(u) or u < uiso_min or u > uiso_max:
                warnings.append(
                    f"初期 Uiso が妥当帯 [{uiso_min}, {uiso_max}] Å² を外れています: "
                    f"{phase}/{label} = {u} — 固定値のまま占有率を導出すると系統誤差が"
                    "組成へ転嫁されます。値を確認するか妥当帯を明示的に緩めてください。"
                )
    return tuple(warnings)


def warn_occupancy_uiso_coupling(recipe: Sequence[object]) -> tuple[str, ...]:
    """占有率と Uiso の同時精密化を検出して警告する (FR-318 / REQ-318-005)。🔵

    X 線では占有率と Uiso が強く縮退する (NaCuHCF 実測: X 線単独の占有率解放段は revert)。
    組成を占有率から導出する解析でこの両方を解放すると、導出組成が Uiso と交換可能になり
    信頼できない。レシピ (`RefinementStage` 列) に両方の段があれば警告を返す。
    """
    has_occ = any("occupancy" in getattr(st, "flags", {}) for st in recipe)
    has_uiso = any("uiso" in getattr(st, "flags", {}) for st in recipe)
    if has_occ and has_uiso:
        return (
            "レシピに占有率 (occupancy) 段と Uiso (uiso) 段が両方あります — 両者は縮退する"
            "ため、占有率から組成を導出する場合 Uiso は固定してください (REQ-318-005)。",
        )
    return ()
