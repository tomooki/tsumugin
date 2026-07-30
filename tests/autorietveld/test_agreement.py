"""`autorietveld.agreement` — 2 手順が同じ解に収束したかの判定 (GSAS 非依存)。

ここで固定するのは **esd の 3 状態を混同しないこと**と、**判らないものを一致と答えないこと**。
どちらも壊れても Rwp には現れないので、テストが唯一の検出手段になる。
"""

from __future__ import annotations

import json
import math

import pytest

from tsumugin.autorietveld.agreement import (
    AGREE,
    AGREE_BY_FLOOR,
    AGREE_ONE_SIDED_ESD,
    CELL,
    COORD,
    DIFFERENT,
    DISAGREE,
    DUPLICATE,
    INCOMPARABLE,
    SAME_ON_SHARED_SUBSET,
    SAME_SOLUTION,
    UNDETERMINED,
    AgreementTolerances,
    ProcedureProvenance,
    cluster_agreement_basins,
    compare_results,
    effective_trajectory,
    is_agreement,
)
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    StageResult,
    ValidityReport,
)

_CUBIC = (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)


def _result(
    *,
    cell=_CUBIC,
    cell_esd=(0.001,) * 3 + (0.0,) * 3,
    coords=None,
    coord_esd=None,
    rwp=9.8,
    stages=(("S0", 3, False), ("S1", 7, False)),
    occ=None,
    occ_esd=None,
) -> AutoRietveldResult:
    coords = coords if coords is not None else {"O1": (0.25, 0.5, 0.125)}
    coord_esd = coord_esd if coord_esd is not None else {"O1": (0.001, 0.001, 0.001)}
    return AutoRietveldResult(
        stage_results=tuple(
            StageResult(label=lab, rwp=rwp, gof=1.0, n_params=n, converged=True, reverted=rev)
            for lab, n, rev in stages
        ),
        final_rwp=rwp,
        final_gof=1.0,
        refined_cells={"p": cell},
        validity=ValidityReport(passed=True),
        cell_esd={"p": cell_esd},
        atom_coords={"p": coords},
        atom_coord_esd={"p": coord_esd},
        atom_occupancy={"p": occ} if occ else {},
        atom_occupancy_esd={"p": occ_esd} if occ_esd else {},
    )


def _prov(label: str, result: AutoRietveldResult, *, n_obs: int = 5752) -> ProcedureProvenance:
    return ProcedureProvenance(
        label=label,
        structure_paths={"p": "p.cif"},
        trajectory=effective_trajectory(result),
        stage_metrics=tuple((s.rwp, s.gof, s.n_params) for s in result.stage_results),
        n_obs=n_obs,
    )


def _cmp(a, b, *, tol=None, label_a="A", label_b="B", n_obs_b=5752):
    return compare_results(
        a, b, _prov(label_a, a), _prov(label_b, b, n_obs=n_obs_b), tolerances=tol
    )


# ---------------------------------------------------------------------------
# ★ 中核: 判らないものを一致と答えない
# ---------------------------------------------------------------------------


def test_undetermined_esd_pair_is_not_reported_as_agreement():
    """★esd が両方無く差が床を超えるなら **UNDETERMINED** — 一致でも不一致でもない。

    非トートロジー: これを AGREE へ倒すのが最悪の嘘 (`check_phase_set` が garbage から
    `is_complete=True` を返すのと同型)。DISAGREE へ倒すのも嘘で、「決まっていない」と
    「違う」は別の陳述である。
    """
    a = _result(cell=(5.0,) * 3 + (90.0,) * 3, cell_esd=(None,) * 6)
    b = _result(cell=(5.2,) * 3 + (90.0,) * 3, cell_esd=(None,) * 6)

    pair = _cmp(a, b)
    cell = next(c for c in pair.classes if c.param_class == CELL)

    assert cell.verdict == UNDETERMINED
    assert cell.n_undetermined > 0
    assert pair.verdict == UNDETERMINED, "対の判定も一致にしてはならない"
    assert not is_agreement(UNDETERMINED)


def test_zero_esd_is_not_conflated_with_missing_esd():
    """★``0.0`` (対称拘束で厳密固定) と ``None`` (決まっていない) は別物。

    非トートロジー: `esd or None` / `esd or 0.0` と書くと両者が潰れる。0.0 は真の陳述
    (「厳密に 90°」) なので、片方が固定・他方が可変なら**対称性の仮定が違う**のであって
    「一致した」でも「違う」でもない。
    """
    a = _result(cell_esd=(0.001, 0.001, 0.001, 0.0, 0.0, 0.0))
    b = _result(cell_esd=(0.001, 0.001, 0.001, None, None, None))

    pair = _cmp(a, b)
    cell = next(c for c in pair.classes if c.param_class == CELL)
    incomparable = [
        it for it in [cell.worst] if it is not None and it.verdict == INCOMPARABLE
    ]
    assert incomparable or cell.n_incomparable > 0, "0.0 と None を同一視している"


def test_two_symmetry_fixed_zero_esds_do_not_divide_by_zero():
    """★双方 ``0.0`` で ``√(σa²+σb²)`` を素直に書くと 0 割りになる。

    非トートロジー: 立方晶の α,β,γ は必ずこの状態になるので、**日常的に踏む**経路である。
    """
    a = _result(cell_esd=(0.001, 0.001, 0.001, 0.0, 0.0, 0.0))
    b = _result(cell_esd=(0.001, 0.001, 0.001, 0.0, 0.0, 0.0))
    pair = _cmp(a, b)  # 例外を出さないこと自体が主張
    cell = next(c for c in pair.classes if c.param_class == CELL)
    assert cell.verdict == AGREE
    for it in [cell.worst]:
        assert it is None or it.z is None or math.isfinite(it.z)


def test_one_sided_esd_is_stricter_not_looser():
    """★片側 esd は欠落 σ を 0 と仮定する = 二側検定より**厳しい**。

    非トートロジー: σ を推定して埋めると一致を安売りする。0 と仮定すれば安全方向にしか
    動かないので、経験的な仮定を置かずに済む。
    """
    tol = AgreementTolerances(k_esd=3.0, cell_rel_floor=0.0)
    # Δ=0.002, σa=0.001 → 片側 z=2.0 (通る)。二側なら σ=√2·0.001 で z=1.41 とさらに緩い。
    a = _result(cell=(5.000,) * 3 + (90.0,) * 3, cell_esd=(0.001,) * 3 + (0.0,) * 3)
    b = _result(cell=(5.002,) * 3 + (90.0,) * 3, cell_esd=(None,) * 3 + (0.0,) * 3)
    pair = _cmp(a, b, tol=tol)
    cell = next(c for c in pair.classes if c.param_class == CELL)
    assert cell.verdict == AGREE
    assert cell.worst is None or cell.worst.verdict in (
        AGREE, AGREE_ONE_SIDED_ESD, AGREE_BY_FLOOR
    )

    # Δ=0.010 なら片側 z=10 で落ちる (二側より厳しいことの対照)。
    c = _result(cell=(5.010,) * 3 + (90.0,) * 3, cell_esd=(None,) * 3 + (0.0,) * 3)
    assert next(
        cl for cl in _cmp(a, c, tol=tol).classes if cl.param_class == CELL
    ).verdict == DISAGREE


# ---------------------------------------------------------------------------
# ★ 座標: 床は比ではなく距離 / 周期ラップ
# ---------------------------------------------------------------------------


def test_coordinate_floor_is_a_distance_not_a_ratio():
    """★``x=0.0012`` vs ``0.0031`` は相対差 158% だが変位 0.002 Å = 同じ原子。

    非トートロジー: 相対床にすると原点近傍の座標がことごとく「不一致」になる。
    座標の一致は化学的な距離で判断するしかない。
    """
    tol = AgreementTolerances(coord_dist_floor_ang=0.02)
    a = _result(coords={"O1": (0.0012, 0.5, 0.5)}, coord_esd={"O1": (None, None, None)})
    b = _result(coords={"O1": (0.0031, 0.5, 0.5)}, coord_esd={"O1": (None, None, None)})
    coord = next(c for c in _cmp(a, b, tol=tol).classes if c.param_class == COORD)
    assert coord.verdict == AGREE, "0.0095 Å の変位を不一致にしてはならない"


def test_coordinate_wrap_is_handled():
    """★0.999 と 0.001 は**同じサイト** (周期境界を跨いだだけ)。"""
    tol = AgreementTolerances(coord_dist_floor_ang=0.02)
    a = _result(coords={"O1": (0.999, 0.5, 0.5)}, coord_esd={"O1": (None, None, None)})
    b = _result(coords={"O1": (0.001, 0.5, 0.5)}, coord_esd={"O1": (None, None, None)})
    coord = next(c for c in _cmp(a, b, tol=tol).classes if c.param_class == COORD)
    assert coord.verdict == AGREE


def test_a_genuinely_displaced_atom_still_disagrees():
    """【対照】床が「何でも一致」へ縮退していないこと。0.1 分率 ≈ 0.5 Å は別物。"""
    tol = AgreementTolerances(coord_dist_floor_ang=0.02)
    a = _result(coords={"O1": (0.25, 0.5, 0.5)}, coord_esd={"O1": (0.0005,) * 3})
    b = _result(coords={"O1": (0.35, 0.5, 0.5)}, coord_esd={"O1": (0.0005,) * 3})
    coord = next(c for c in _cmp(a, b, tol=tol).classes if c.param_class == COORD)
    assert coord.verdict == DISAGREE
    assert coord.worst is not None and coord.worst.key.endswith(".x")


# ---------------------------------------------------------------------------
# ★ 独立性
# ---------------------------------------------------------------------------


def test_bit_identical_results_do_not_corroborate():
    """★ビット同一の 2 手順が一致しても情報量ゼロ (同じ精密化が 2 度走っただけ)。"""
    a, b = _result(), _result()
    pair = _cmp(a, b)
    assert pair.verdict == SAME_SOLUTION
    assert pair.independence.verdict == DUPLICATE
    assert pair.independence.identical_values is True


def test_effective_trajectory_ignores_reverted_and_noop_stages():
    """★「revert される段だけが違う 2 案」は実効的に同じ道を歩いている。

    非トートロジー: 宣言 (レシピ) を比べると別物に見える。観測 (revert フラグ) で比べて
    初めて重複が判る — これが「5 案回したが実質 3 経路」を検出する仕組み。
    """
    a = _result(stages=(("S0", 3, False), ("S1", 7, False)))
    b = _result(stages=(("S0", 3, False), ("Sx extra", 7, True), ("S1", 7, False)))
    assert effective_trajectory(a) == effective_trajectory(b)
    assert _cmp(a, b).independence.verdict == DUPLICATE


def test_differing_observation_sets_raise_independence():
    """★観測集合が違うのは独立性を**上げる** (別レンジで同じ構造に至る方が強い証拠)。"""
    a, b = _result(), _result(rwp=9.82)
    b = _result(rwp=9.82, stages=(("S0", 3, False), ("S1 trimmed", 7, False)))
    pair = _cmp(a, b, n_obs_b=5535)
    assert pair.independence.same_observation_set is False
    assert pair.independence.verdict != DUPLICATE


# ---------------------------------------------------------------------------
# ★ 傍証のガード
# ---------------------------------------------------------------------------


def _bundle(n: int, **kw):
    results = [_result(**kw) for _ in range(n)]
    provs = [_prov(f"c{i}", r) for i, r in enumerate(results)]
    return results, provs


def test_a_single_result_is_never_corroborated():
    """★1 手順は必ず 1 クラスタなので、``n_basins == 1`` は空虚に成立する。"""
    results, provs = _bundle(1)
    rep = cluster_agreement_basins(results, provs)
    assert rep.is_corroborated is False
    assert rep.corroboration_reason == "insufficient_procedures"


def test_all_duplicate_trajectories_are_not_corroboration():
    """★同じ実効軌跡の 3 手順が一致しても「3 通り試した」ことにならない。"""
    results, provs = _bundle(3)
    rep = cluster_agreement_basins(results, provs)
    assert rep.n_distinct_trajectories == 1
    assert rep.is_corroborated is False
    assert rep.corroboration_reason == "all_trajectories_duplicate"
    assert any("実効経路" in w for w in rep.warnings), "黙って落とさず理由を述べること"


def test_diverged_results_are_excluded_and_warned():
    results = [_result(), _result(rwp=float("inf")), None]
    provs = [_prov("a", results[0]), _prov("b", results[1]), _prov("c", results[0])]
    rep = cluster_agreement_basins(results, provs)
    assert rep.n_diverged == 2 and rep.n_comparable == 1
    assert any("発散" in w for w in rep.warnings)


def test_independent_agreeing_pair_corroborates():
    """【対照】条件が「常に False」へ縮退していないこと。"""
    r0 = _result(stages=(("S0", 3, False), ("S1", 7, False)))
    r1 = _result(stages=(("S0", 3, False), ("P_W", 5, False), ("P_WUV", 7, False)))
    r2 = _result(cell=(5.4,) * 3 + (90.0,) * 3, stages=(("Z", 9, False),))
    results = [r0, r1, r2]
    provs = [_prov("A0", r0), _prov("A1", r1), _prov("N0", r2)]

    rep = cluster_agreement_basins(results, provs)

    assert rep.n_distinct_trajectories == 3
    assert rep.corroboration_reason == "corroborated"
    assert rep.is_corroborated is True
    assert rep.largest_basin_size == 2, "r0/r1 が同じベイスン・r2 は別"


def test_basins_are_order_independent():
    """★推移的でない「同一」を貪欲に畳むと**列挙順でベイスン数が変わる**。

    非トートロジー: a≈b, b≈c, a≉c の鎖を作り、順列を変えても分割が同じであることを見る。
    貪欲な「先頭一致」(`multistart.cluster_rietveld_basins`) はここで落ちる。
    """
    import itertools

    tol = AgreementTolerances(k_esd=3.0, cell_rel_floor=0.0, coord_dist_floor_ang=0.02)
    # 格子を 0.006 刻みで並べる (σ=0.001 なので隣は z=4.2… 実際は下で床調整)
    cells = [(5.000,) * 3 + (90.0,) * 3, (5.004,) * 3 + (90.0,) * 3, (5.008,) * 3 + (90.0,) * 3]
    base = [_result(cell=c, cell_esd=(0.001,) * 3 + (0.0,) * 3) for c in cells]

    partitions = set()
    for order in itertools.permutations(range(3)):
        results = [base[i] for i in order]
        provs = [_prov(f"c{i}", results[k]) for k, i in enumerate(order)]
        rep = cluster_agreement_basins(results, provs, tolerances=tol)
        # 元の index へ写し戻してから正規化する
        mapped = frozenset(
            frozenset(order[m] for m in b.member_indices) for b in rep.basins
        )
        partitions.add(mapped)
    assert len(partitions) == 1, f"列挙順で分割が変わった: {partitions}"


def test_chain_basin_is_not_reported_as_a_clique():
    """★推移閉包で 1 ベイスンになった「鎖」は clique より弱い証拠なのでそう言う。"""
    tol = AgreementTolerances(k_esd=3.0, cell_rel_floor=0.0, coord_dist_floor_ang=0.02)
    cells = [(5.000,) * 3 + (90.0,) * 3, (5.004,) * 3 + (90.0,) * 3, (5.008,) * 3 + (90.0,) * 3]
    results = [_result(cell=c, cell_esd=(0.001,) * 3 + (0.0,) * 3) for c in cells]
    provs = [
        _prov("a", results[0]),
        ProcedureProvenance(label="b", structure_paths={"p": "p.cif"},
                            trajectory=(("B", 5),), n_obs=5752),
        ProcedureProvenance(label="c", structure_paths={"p": "p.cif"},
                            trajectory=(("C", 6),), n_obs=5752),
    ]
    rep = cluster_agreement_basins(results, provs, tolerances=tol)
    big = max(rep.basins, key=lambda b: len(b.member_indices))
    if len(big.member_indices) == 3:
        assert big.is_clique is False, "鎖を clique と報告してはならない"


# ---------------------------------------------------------------------------
# 比較不能 / 出自
# ---------------------------------------------------------------------------


def test_different_structure_paths_are_incomparable_not_agreement():
    """★入力構造が違えば*モデル*の比較であって収束の比較ではない。近似せず拒否する。"""
    a, b = _result(), _result()
    pa = ProcedureProvenance(label="A", structure_paths={"p": "alpha.cif"})
    pb = ProcedureProvenance(label="B", structure_paths={"p": "delta.cif"})
    pair = compare_results(a, b, pa, pb)
    assert pair.verdict == INCOMPARABLE
    assert any("compare_structure_models" in w for w in pair.warnings)


def test_phase_set_mismatch_is_warned_and_only_shared_phases_compared():
    a = _result()
    b = _result()
    b = AutoRietveldResult(
        stage_results=b.stage_results, final_rwp=b.final_rwp, final_gof=b.final_gof,
        refined_cells={"p": _CUBIC, "extra": _CUBIC}, validity=b.validity,
        cell_esd=b.cell_esd, atom_coords=b.atom_coords, atom_coord_esd=b.atom_coord_esd,
    )
    pair = _cmp(a, b)
    assert any("相集合が違う" in w for w in pair.warnings)


def test_asymmetric_profile_release_downgrades_to_shared_subset():
    """★片方だけが解放した項は「凍結していた」であって「決まらなかった」ではない。"""
    a = _result()
    b = _result()
    a = AutoRietveldResult(
        **{**a.__dict__, "hist_profile": ({"U": 1.0},),
           "hist_profile_refined": ({"U": True},), "hist_profile_esd": ({"U": 0.01},)}
    )
    b = AutoRietveldResult(
        **{**b.__dict__, "hist_profile": ({"U": 5.0},),
           "hist_profile_refined": ({"U": False},), "hist_profile_esd": ({"U": None},)}
    )
    pair = _cmp(a, b)
    profile = next(c for c in pair.classes if c.param_class == "profile")
    assert profile.n_asymmetric == 1
    assert pair.verdict in (SAME_ON_SHARED_SUBSET, SAME_SOLUTION)


# ---------------------------------------------------------------------------
# 決定論 / JSON
# ---------------------------------------------------------------------------


def test_report_is_bit_identical_across_repeats():
    results, provs = _bundle(3)
    first = cluster_agreement_basins(results, provs).to_dict()
    for _ in range(3):
        assert cluster_agreement_basins(results, provs).to_dict() == first


def test_report_dict_is_json_safe():
    results, provs = _bundle(2)
    payload = cluster_agreement_basins(results, provs).to_dict()
    json.dumps(payload, allow_nan=False)  # 非有限が漏れたらここで落ちる


def test_module_does_not_import_gsas():
    import ast
    import pathlib

    src = pathlib.Path("src/tsumugin/autorietveld/agreement.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [getattr(node, "module", "") or ""] + [a.name for a in node.names]
            assert not any("GSAS" in n for n in names), names


@pytest.mark.parametrize("verdict", [AGREE, AGREE_BY_FLOOR, AGREE_ONE_SIDED_ESD])
def test_is_agreement_accepts_only_the_three_agree_verdicts(verdict):
    assert is_agreement(verdict) is True


@pytest.mark.parametrize("verdict", [DISAGREE, UNDETERMINED, INCOMPARABLE, DIFFERENT])
def test_is_agreement_rejects_everything_else(verdict):
    assert is_agreement(verdict) is False


# ---------------------------------------------------------------------------
# ★ 独立性の根拠 (basis) — マルチスタートでは判定が**逆を向く**
# ---------------------------------------------------------------------------


def _start_prov(label: str, result, start_key, *, n_obs: int = 5752) -> ProcedureProvenance:
    return ProcedureProvenance(
        label=label,
        structure_paths={"p": "p.cif"},
        trajectory=effective_trajectory(result),
        stage_metrics=tuple((s.rwp, s.gof, s.n_params) for s in result.stage_results),
        n_obs=n_obs,
        start_key=start_key,
    )


def test_start_basis_does_not_call_identical_trajectories_duplicate():
    """★マルチスタートでは軌跡が**構造的に同一**になる — DUPLICATE にしたら傍証は永久に出ない。

    非トートロジー: 全開始点が同じ手順を走るので段ラベルも母数も一致する。手順比較の規則を
    そのまま持ち込むと、正しく実装しても `n_independent_agreeing_pairs` が常に 0 になり、
    「収束確認が一度も成功しない」という壊れ方をする (しかも Rwp には現れない)。
    """
    a, b = _result(), _result(rwp=9.81)
    pa = _start_prov("s0", a, ("cell", 1.00))
    pb = _start_prov("s1", b, ("cell", 1.01))
    assert pa.trajectory == pb.trajectory, "前提: 同じ手順なので軌跡は同一"

    proc = compare_results(a, b, pa, pb, basis="procedure")
    start = compare_results(a, b, pa, pb, basis="start")

    assert proc.independence.verdict == DUPLICATE
    assert start.independence.verdict == "INDEPENDENT"


def test_start_basis_treats_bit_identical_results_as_the_strongest_evidence():
    """★別の初期値からビット同一の解へ来ることは**収束の最強の証拠**であって重複ではない。

    非トートロジー: 手順比較では同じ意味 (ビット同一) が「同じ精密化が 2 度走った」証拠に
    なるため DUPLICATE。同じ判定を持ち込むと最良の結果を捨てる。
    """
    a, b = _result(), _result()  # 完全に同じ解
    pa = _start_prov("s0", a, ("cell", 0.99))
    pb = _start_prov("s1", b, ("cell", 1.01))

    pair = compare_results(a, b, pa, pb, basis="start")

    assert pair.verdict == SAME_SOLUTION
    assert pair.independence.identical_values is True
    assert pair.independence.verdict == "INDEPENDENT"
    assert any("最強の証拠" in r for r in pair.independence.reasons)


def test_start_basis_still_rejects_the_same_starting_point_twice():
    """【対照】``start`` が「常に独立」へ縮退していないこと — 同じ初期値の 2 回は重複。"""
    a, b = _result(), _result()
    same = ("cell", 1.00)
    pair = compare_results(a, b, _start_prov("s0", a, same), _start_prov("s1", b, same),
                           basis="start")
    assert pair.independence.verdict == DUPLICATE


def test_start_basis_counts_distinct_starting_points_not_trajectories():
    """★「何本の別の実験を走らせたか」の数え方もモードで変わる。"""
    results = [_result(), _result(rwp=9.81), _result(rwp=9.82)]
    provs = [
        _start_prov("s0", results[0], ("cell", 0.99)),
        _start_prov("s1", results[1], ("cell", 1.00)),
        _start_prov("s2", results[2], ("cell", 1.01)),
    ]
    rep = cluster_agreement_basins(results, provs, basis="start")

    assert rep.n_distinct_trajectories == 3, "初期値が 3 通り (軌跡は 1 通りしかない)"
    assert rep.is_corroborated is True
    assert rep.corroboration_reason == "corroborated"

    # 同じ入力を procedure 基準で見ると、軌跡が 1 通りなので傍証にならない。
    proc = cluster_agreement_basins(results, provs, basis="procedure")
    assert proc.is_corroborated is False
    assert proc.corroboration_reason == "all_trajectories_duplicate"


def test_unknown_independence_basis_is_rejected():
    a, b = _result(), _result()
    with pytest.raises(ValueError, match="basis"):
        compare_results(a, b, _prov("A", a), _prov("B", b), basis="bogus")
