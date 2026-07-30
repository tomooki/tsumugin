"""10 案 → 5 案の選定 — **書き下した基準を関数にする** (判断で選ばない)。

`bench_recipes.py --out` が書いた per-(データ, 候補) の JSON を読み、適格性 → データ毎の順位 →
優先順位付き基準で部分集合を全列挙して 5 案を決める。

**なぜ全列挙か**: 達成条件 (P1) は「5 案の**中に**経路の違う一致対があること」= 部分集合内の
**対**の性質であり、候補ごとのスコアに分解できない。したがって貪欲な「上位 5 案」は誤りである。
C(9,5) = 126 は自明に列挙でき、完全に決定論になる。

**順位付けは `search.rank_outcomes` をそのまま使う** — 独自の比較器を作らない (収束優先の層 →
観測集合 → Rwp → 列挙順、という既存の全順序をここで再発明すると 2 つの規律ができる)。
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "tools"))

from bench_specs import (  # noqa: E402 — sys.path 調整後
    CAMPAIGN_DATASETS,
    ELIGIBLE_RECIPES,
    RECIPE_REGISTRY,
    RECIPES,
)


@dataclass(frozen=True)
class Cell:
    """1 (データ, 候補) の計測結果 (JSON からの読み出し)。"""

    dataset: str
    recipe: str
    payload: dict

    @property
    def rwp(self) -> float:
        v = self.payload.get("rwp")
        return float(v) if v is not None else float("inf")

    @property
    def valid(self) -> bool:
        return self.payload.get("validity") == "pass"

    @property
    def n_obs(self) -> int:
        return int(self.payload.get("n_obs", 0))

    @property
    def stages(self) -> list[dict]:
        return list(self.payload.get("stages", ()))

    @property
    def accepted_stages(self) -> list[dict]:
        """revert も no-op もされなかった段 (= 実効軌跡)。"""
        return [
            s for s in self.stages
            if not s.get("reverted") and "noop" not in str(s.get("note", ""))
        ]

    @property
    def trajectory(self) -> tuple[tuple[str, int], ...]:
        return tuple((str(s["label"]), int(s["n_params"])) for s in self.accepted_stages)

    @property
    def converged(self) -> "bool | None":
        acc = self.accepted_stages
        return None if not acc else acc[-1].get("converged")

    @property
    def n_params(self) -> int:
        acc = self.accepted_stages
        return int(acc[-1]["n_params"]) if acc else 0


@dataclass
class Admissibility:
    """Step 0 の適格性。**落ちた候補も表には残す** (何を試したかは結果の一部)。"""

    recipe: str
    ok: bool
    reasons: list[str] = field(default_factory=list)


def load_cells(out_dir: Path) -> dict[tuple[str, str], Cell]:
    cells: dict[tuple[str, str], Cell] = {}
    for path in sorted(out_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        d, r = payload.get("dataset"), payload.get("recipe")
        if d and r:
            cells[(str(d), str(r))] = Cell(str(d), str(r), payload)
    return cells


def check_admissibility(
    cells: dict[tuple[str, str], Cell], datasets: "list[str] | None" = None
) -> dict[str, Admissibility]:
    """Step 0: 適格性ゲート。

    - 0a 全データで結果を出す
    - 0b 選定対象である (負の対照は宣言により除外)
    - 0d **A0 と 1 データ以上で違う** — 退化した候補は名前を変えた重複で傍証を偽装する
    - 0e S0 より後に受理段が 1 つ以上 (全 revert だと収束判定が fail-open して tier 0 になる)
    """
    ds = datasets or list(CAMPAIGN_DATASETS)
    out: dict[str, Admissibility] = {}
    for recipe in RECIPES:
        adm = Admissibility(recipe=recipe, ok=True)
        build = RECIPE_REGISTRY[recipe]
        if not build.eligible:
            adm.ok = False
            adm.reasons.append("0b: 負の対照 (宣言により選定対象外)")
        missing = [d for d in ds if (d, recipe) not in cells]
        if missing:
            adm.ok = False
            adm.reasons.append(f"0a: 結果が無いデータ {missing}")
        else:
            failed = [d for d in ds if not cells[(d, recipe)].stages]
            if failed:
                adm.ok = False
                adm.reasons.append(f"0a: 段が 1 つも無い {failed}")
            thin = [d for d in ds if len(cells[(d, recipe)].accepted_stages) < 2]
            if thin:
                adm.ok = False
                adm.reasons.append(f"0e: S0 の後に受理段が無い {thin} (収束判定が fail-open する)")
            if recipe != "A0-default":
                same = [
                    d for d in ds
                    if cells[(d, recipe)].rwp == cells[(d, "A0-default")].rwp
                    and cells[(d, recipe)].trajectory == cells[(d, "A0-default")].trajectory
                ]
                if len(same) == len(ds):
                    adm.ok = False
                    adm.reasons.append(
                        "0d: 全データで A0 とビット同一かつ同一軌跡 = 名前を変えた重複"
                    )
        out[recipe] = adm
    return out


def rank_per_dataset(
    cells: dict[tuple[str, str], Cell], dataset: str, recipes: "list[str] | None" = None
) -> list[str]:
    """`search.rank_outcomes` を**そのまま**使ってデータ毎の順位を出す (独自比較器を作らない)。"""
    from tsumugin.autorietveld.model import (
        AutoRietveldResult,
        Geometry,
        HistogramSpec,
        Radiation,
        RefinementStage,
        StageResult,
        ValidityReport,
    )
    from tsumugin.autorietveld.search import (
        CandidateOutcome,
        RecipeCandidate,
        SearchConfig,
        rank_outcomes,
    )

    names = [r for r in (recipes or list(RECIPES)) if (dataset, r) in cells]
    outcomes = []
    for i, name in enumerate(names):
        c = cells[(dataset, name)]
        stages = tuple(
            StageResult(
                label=str(s["label"]),
                rwp=float(s["rwp"]) if s.get("rwp") is not None else float("inf"),
                gof=float(s["gof"]) if s.get("gof") is not None else float("inf"),
                n_params=int(s["n_params"]),
                converged=bool(s.get("converged")),
                reverted=bool(s.get("reverted")),
                note=str(s.get("note", "")),
            )
            for s in c.stages
        )
        result = AutoRietveldResult(
            stage_results=stages,
            final_rwp=c.rwp,
            final_gof=float(c.payload.get("gof") or float("inf")),
            refined_cells={
                k: tuple(v) for k, v in (c.payload.get("refined_cells") or {}).items()
            },
            validity=ValidityReport(passed=c.valid),
            n_obs=c.n_obs,
        )
        outcomes.append(
            CandidateOutcome(
                index=i,
                candidate=RecipeCandidate(
                    name=name,
                    stages=(RefinementStage(label="s", flags={}),),
                    origin="fixed",
                    histograms=(
                        HistogramSpec(
                            data_path="d", instrument_path="i",
                            radiation=Radiation.XRAY_LAB,
                            geometry=Geometry.BRAGG_BRENTANO,
                        ),
                    ),
                ),
                result=result,
            )
        )
    ranking = rank_outcomes(outcomes, SearchConfig())[0]
    return [names[i] for i in ranking]


def agreement_for(
    cells: dict[tuple[str, str], Cell], dataset: str, subset: "list[str]"
):
    """部分集合のその データ での一致判定 (`autorietveld.agreement`)。"""
    from tsumugin.autorietveld.agreement import (
        ProcedureProvenance,
        cluster_agreement_basins,
    )
    from tsumugin.autorietveld.model import AutoRietveldResult, ValidityReport

    results, provs = [], []
    for name in subset:
        c = cells.get((dataset, name))
        if c is None:
            results.append(None)
            provs.append(ProcedureProvenance(label=name))
            continue
        results.append(
            AutoRietveldResult(
                stage_results=(),
                final_rwp=c.rwp,
                final_gof=float(c.payload.get("gof") or float("inf")),
                refined_cells={
                    k: tuple(v) for k, v in (c.payload.get("refined_cells") or {}).items()
                },
                validity=ValidityReport(passed=c.valid),
                cell_esd={
                    k: tuple(v) for k, v in (c.payload.get("cell_esd") or {}).items()
                },
                atom_coords={
                    p: {lab: tuple(xyz) for lab, xyz in atoms.items()}
                    for p, atoms in (c.payload.get("atom_coords") or {}).items()
                },
                atom_coord_esd={
                    p: {lab: tuple(esd) for lab, esd in atoms.items()}
                    for p, atoms in (c.payload.get("atom_coord_esd") or {}).items()
                },
                atom_occupancy=c.payload.get("atom_occupancy") or {},
                atom_occupancy_esd=c.payload.get("atom_occupancy_esd") or {},
                atom_uiso=c.payload.get("atom_uiso") or {},
                atom_uiso_esd=c.payload.get("atom_uiso_esd") or {},
                n_obs=c.n_obs,
            )
        )
        provs.append(
            ProcedureProvenance(
                label=name,
                trajectory=c.trajectory,
                stage_metrics=tuple(
                    (float(s.get("rwp") or 0.0), float(s.get("gof") or 0.0),
                     int(s["n_params"]))
                    for s in c.stages
                ),
                n_obs=c.n_obs,
                frozen_parameters=tuple(c.payload.get("frozen_parameters") or ()),
            )
        )
    return cluster_agreement_basins(results, provs)


def select(
    cells: dict[tuple[str, str], Cell],
    *,
    datasets: "list[str] | None" = None,
    acceptance: "tuple[str, ...]" = ("T1", "T3"),
    size: int = 5,
) -> dict:
    """Step 0-2 を通して 5 案を決める (完全決定論)。"""
    ds = datasets or list(CAMPAIGN_DATASETS)
    adm = check_admissibility(cells, ds)
    pool = [r for r in ELIGIBLE_RECIPES if adm[r].ok]
    rankings = {d: rank_per_dataset(cells, d) for d in ds}
    best_tier_holder = {d: rankings[d][0] for d in ds if rankings[d]}

    scored = []
    for subset in itertools.combinations(pool, size):
        sub = list(subset)
        # P1: 達成条件 — T1 と T3 で**独立に**経路の違う一致対があること
        p1_detail = {}
        p1 = True
        for d in acceptance:
            rep = agreement_for(cells, d, sub)
            p1_detail[d] = rep
            if rep.n_independent_agreeing_pairs < 1 or rep.largest_basin_size < 2:
                p1 = False
        # P2: 各データで 10 案中の最良 tier を持つ候補を含む
        p2 = all(best_tier_holder.get(d) in sub for d in ds)
        # P3: 経路多様性 — 軸が 3 つ以上異なる & 累積と順次凍結の両方を含む
        axes = {RECIPE_REGISTRY[r].axis for r in sub}
        builders = {RECIPE_REGISTRY[r].builder for r in sub}
        p3 = len(axes) >= 3 and {"default", "serious"} <= builders
        # P4: 同一観測群内での順位和
        p4 = 0
        for d in ds:
            order = rankings[d]
            for r in sub:
                p4 += order.index(r) if r in order else len(order)
        # P5: コスト (段数の総和で代用 — 実測秒はハーネス表に出る)
        p5 = sum(
            len(cells[(d, r)].stages) for d in ds for r in sub if (d, r) in cells
        )
        scored.append(
            {
                "subset": sub,
                "p1": p1, "p2": p2, "p3": p3, "p4": p4, "p5": p5,
                "key": (not p1, not p2, not p3, p4, p5, [ELIGIBLE_RECIPES.index(r) for r in sub]),
                "agreement": {d: p1_detail[d] for d in acceptance},
            }
        )
    scored.sort(key=lambda s: s["key"])
    return {
        "admissibility": adm,
        "pool": pool,
        "rankings": rankings,
        "best": scored[0] if scored else None,
        "n_subsets": len(scored),
    }


def main(argv: "list[str] | None" = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results_dir", type=Path, help="bench_recipes --out が書いたディレクトリ")
    ap.add_argument("--size", type=int, default=5)
    args = ap.parse_args(argv)

    cells = load_cells(args.results_dir)
    if not cells:
        print(f"結果 JSON が見つかりません: {args.results_dir}")
        return 1
    got = select(cells, size=args.size)

    print("## Step 0 適格性\n")
    print("| 候補 | 適格 | 理由 |")
    print("|---|---|---|")
    for r in RECIPES:
        a = got["admissibility"][r]
        print(f"| {r} | {'○' if a.ok else '×'} | {'; '.join(a.reasons) or '—'} |")

    print("\n## Step 1 データ毎の順位 (`search.rank_outcomes`)\n")
    for d, order in got["rankings"].items():
        print(f"- **{d}**: {' > '.join(order)}")

    best = got["best"]
    print(f"\n## Step 2 選定 ({got['n_subsets']} 部分集合を全列挙)\n")
    if best is None:
        print("選定できる部分集合がありません")
        return 1
    print(f"**選定 5 案**: {', '.join(best['subset'])}\n")
    print(f"- P1 達成条件 (T1/T3 で独立な一致対): {'満たす' if best['p1'] else '**満たさない**'}")
    print(f"- P2 tier カバレッジ: {'満たす' if best['p2'] else '満たさない'}")
    print(f"- P3 経路多様性: {'満たす' if best['p3'] else '満たさない'}")
    print(f"- P4 順位和: {best['p4']} / P5 段数計: {best['p5']}")
    for d, rep in best["agreement"].items():
        print(
            f"\n### {d} の一致\n\n"
            f"- 傍証: {rep.is_corroborated} ({rep.corroboration_reason})\n"
            f"- 実効経路 {rep.n_distinct_trajectories} / 比較可能 {rep.n_comparable}\n"
            f"- 独立な一致対 {rep.n_independent_agreeing_pairs} / 最大ベイスン {rep.largest_basin_size}"
        )
        for b in rep.basins:
            members = [best["subset"][i] for i in b.member_indices]
            print(f"  - ベイスン {members} rwp={b.rwp:.4f} clique={b.is_clique}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
