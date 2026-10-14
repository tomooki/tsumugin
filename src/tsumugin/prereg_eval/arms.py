"""P0 §1.1 のアームを 1 事例について回す (GSAS は遅延 import)。

| アーム | 中身 |
|---|---|
| ``B-single`` | `build_recipe` の既定レシピで `run_auto_rietveld` 単発 |
| ``B-AB`` | `optimize_then_confirm` (Phase A = `DEFAULT_CANDIDATES` / Phase B = 開始点 5・格子 ±0.7%・座標 0.05 Å) |
| ``T-single`` | テンプレート (pass 1 → コンパイル → pass 2) の単発 (`run_recipe_search(names=("template",))`) |
| ``T-AB`` | `optimize_then_confirm(candidates=("template",))` (Phase B は B-AB と同じ設定) |
| ``T-single/bkg`` / ``T-AB/bkg`` | 上の 2 つで、背景項数だけを比較相手が採用した値に置き換えたもの (同じなら元のアームを使い回す) |
| ``X-transplant`` | 現行の段順 (`build_recipe`) に、テンプレートのモデル化の選択 (相の指定 = Uiso の組・副相の構造凍結・原点固定と、背景項数) を移植 |
| ``T-perm:<id>`` | テンプレートの段順を置換したもの (`PERMUTATIONS`)。置換に要る段が無い事例では回さない (None) |

各アームは精密化の実体 (結果・使った入力・Phase B の結果) を `ArmRun` に写す。評価の指標は `adapter` / `case` が計算する。
**事後の収束検査** (§1.2) は全アームの最終 gpx に同じ ``posthoc`` を掛ける (閾値は P1.5 で凍結 — ここでは値を記録するだけ)。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

__all__ = [
    "PERMUTATIONS",
    "ArmRun",
    "Runners",
    "permute_stages",
    "run_arms",
    "stage_background",
    "with_background",
]


@dataclass(frozen=True)
class ArmRun:
    arm: str
    result: Any | None
    error: str = ""
    histograms: tuple = ()
    phases: tuple = ()
    multistart: Any | None = None
    derivation: Mapping[str, Any] | None = None
    background_coeffs: int | None = None
    stage_labels: tuple[str, ...] = ()
    posthoc_shift_esd: float | None = None
    same_as: str = ""


# --- 段列の操作 ------------------------------------------------------------------------------


def stage_background(stages: Sequence[Any]) -> int | None:
    """段列が使う背景項数 (最初に背景を解放する段の値)。無ければ None。"""
    for st in stages:
        bg = dict(getattr(st, "flags", {}) or {}).get("background")
        if isinstance(bg, Mapping) and "coeffs" in bg:
            return int(bg["coeffs"])
    return None


def with_background(stages: Sequence[Any], coeffs: int) -> tuple[Any, ...]:
    """背景項数だけを ``coeffs`` に置き換えた段列 (ほかの段フラグは変えない)。"""
    out = []
    for st in stages:
        flags = dict(getattr(st, "flags", {}) or {})
        bg = flags.get("background")
        if isinstance(bg, Mapping) and "coeffs" in bg:
            flags["background"] = {**dict(bg), "coeffs": int(coeffs)}
            st = replace(st, flags=flags)
        out.append(st)
    return tuple(out)


def _prefix(stage: Any) -> str:
    return str(getattr(stage, "label", "")).split(" ", 1)[0]


def _index(stages: Sequence[Any], prefix: str) -> int | None:
    hits = [i for i, st in enumerate(stages) if _prefix(st) == prefix]
    return hits[0] if len(hits) == 1 else None


def _swap(a: str, b: str) -> Callable[[Sequence[Any]], tuple | None]:
    def f(stages: Sequence[Any]) -> tuple | None:
        i, j = _index(stages, a), _index(stages, b)
        if i is None or j is None:
            return None
        out = list(stages)
        out[i], out[j] = out[j], out[i]
        return tuple(out)

    return f


def _move_before(moved: str, anchor: str) -> Callable[[Sequence[Any]], tuple | None]:
    def f(stages: Sequence[Any]) -> tuple | None:
        i, j = _index(stages, moved), _index(stages, anchor)
        if i is None or j is None or i < j:
            return None  # 既に前にある (置換にならない) なら回さない
        out = list(stages)
        st = out.pop(i)
        out.insert(j, st)
        return tuple(out)

    return f


#: P0 §7.1 R1-3 の置換アーム (少なくとも 4 つ — review-response 1 巡目 §2 で順序が問題になった組)。P1.5 で凍結する一覧
PERMUTATIONS: dict[str, Callable[[Sequence[Any]], tuple | None]] = {
    "swap_T1_T2": _swap("T1", "T2"),  # 格子と幅
    "swap_T5_T6": _swap("T5", "T6"),  # 座標と B
    "T8_before_T5": _move_before("T8", "T5"),  # 選択配向を構造より前
    "T7_before_T6": _move_before("T7", "T6"),  # 占有率を B より前
}


def permute_stages(stages: Sequence[Any], perm_id: str) -> tuple | None:
    """置換 ``perm_id`` を当てた段列。置換に要る段が無ければ None (その事例では回さない)。"""
    return PERMUTATIONS[perm_id](stages)


# --- 実行 ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Runners:
    """精密化の実体 (既定は GSAS を回す本物。テストでは差し替える)。"""

    single: Callable[..., Any] | None = None  # run_auto_rietveld(h, p, recipe=, stability=, blas_threads=)
    template_search: Callable[..., Any] | None = None  # run_recipe_search(h, p, names=("template",), template_declarations=)
    confirm: Callable[..., Any] | None = None  # optimize_then_confirm(h, p, candidates=, template_declarations=, n_starts=...)
    multistart: Callable[..., Any] | None = None  # run_multistart_rietveld(h, p, config=, coord_jitter_ang=, seed=, recipe=...)
    recipe: Callable[..., Any] | None = None  # build_recipe(h, p, background_coeffs=)
    posthoc: Callable[[str], float | None] | None = None  # posthoc_shift_esd(gpx_path)


def _defaults(r: Runners) -> Runners:
    from ..autorietveld.confirm import optimize_then_confirm
    from ..autorietveld.engine import posthoc_shift_esd, run_auto_rietveld
    from ..autorietveld.multistart import run_multistart_rietveld
    from ..autorietveld.recipe import build_recipe
    from ..autorietveld.search import run_recipe_search

    return Runners(
        single=r.single or run_auto_rietveld,
        template_search=r.template_search or run_recipe_search,
        confirm=r.confirm or optimize_then_confirm,
        multistart=r.multistart or run_multistart_rietveld,
        recipe=r.recipe or build_recipe,
        posthoc=r.posthoc or (lambda path: posthoc_shift_esd(path, cycles=1)),
    )


@dataclass(frozen=True)
class _AB:
    n_starts: int = 5
    lattice_frac: float = 0.007
    coord_jitter_ang: float = 0.05
    seed: int = 0
    extra: Mapping[str, Any] = field(default_factory=dict)


def _guard(arm: str, fn: Callable[[], ArmRun]) -> ArmRun:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — アームの失敗は評価の入力 (失敗した側の負け — §1.2)
        return ArmRun(arm=arm, result=None, error=f"{type(exc).__name__}: {exc}"[:500])


def _with_posthoc(run: ArmRun, posthoc: Callable[[str], float | None]) -> ArmRun:
    path = str(getattr(run.result, "gpx_path", "") or "")
    if run.result is None or not path:
        return run
    try:
        return replace(run, posthoc_shift_esd=posthoc(path))
    except Exception as exc:  # noqa: BLE001 — 事後検査が回らない = 未収束扱い (呼び手が失敗に畳む)
        return replace(run, error=f"posthoc: {type(exc).__name__}: {exc}"[:500])


def run_arms(
    histograms: Sequence[Any],
    phases: Sequence[Any],
    declarations: Any,
    *,
    permutations: Sequence[str] = tuple(PERMUTATIONS),
    n_starts: int = 5,
    lattice_frac: float = 0.007,
    coord_jitter_ang: float = 0.05,
    seed: int = 0,
    runners: Runners = Runners(),
    run_kwargs: Mapping[str, Any] | None = None,
) -> dict[str, ArmRun | None]:
    """1 事例の全アーム。回さないアーム (置換に要る段が無い) は None。"""
    from ..multistart.perturb import MultistartConfig, PerturbationSpec
    from ..autorietveld.search import _TEMPLATE_STABILITY

    r = _defaults(runners)
    kw = dict(run_kwargs or {})
    hists, phs = tuple(histograms), tuple(phases)
    out: dict[str, ArmRun | None] = {}

    # B-single — 既定レシピを明示的に組んで渡す (背景項数を知るため。中身は recipe=None と同じ)
    def b_single() -> ArmRun:
        recipe = tuple(r.recipe(list(hists), list(phs)))
        res = r.single(list(hists), list(phs), recipe=recipe, **kw)
        return ArmRun("B-single", res, histograms=hists, phases=phs, background_coeffs=stage_background(recipe),
                      stage_labels=tuple(s.label for s in recipe))

    out["B-single"] = _guard("B-single", b_single)

    ab = dict(n_starts=n_starts, lattice_frac=lattice_frac, coord_jitter_ang=coord_jitter_ang, jitter_seed=seed)

    def from_report(arm: str, report: Any) -> ArmRun:
        cand = report.search.selected.candidate if report.search and report.search.selected else None
        return ArmRun(
            arm, report.best,
            error="" if report.best is not None else "; ".join(report.warnings)[:500] or "no result",
            histograms=tuple(cand.histograms) if cand else hists,
            phases=tuple(cand.phases) if cand and cand.phases is not None else phs,
            multistart=report.multistart, derivation=getattr(cand, "derivation", None),
            background_coeffs=stage_background(cand.stages) if cand else None,
            stage_labels=tuple(s.label for s in cand.stages) if cand else (),
        )

    out["B-AB"] = _guard("B-AB", lambda: from_report("B-AB", r.confirm(list(hists), list(phs), **ab, **kw)))

    # T-single — テンプレートの候補 (コンパイル済みの段列と相の指定) もここで得る
    holder: dict[str, Any] = {}

    def t_single() -> ArmRun:
        search = r.template_search(list(hists), list(phs), names=("template",), template_declarations=declarations, **kw)
        sel = search.selected
        if sel is None or sel.result is None:
            raise RuntimeError("template candidate was not built or failed: " + "; ".join(search.warnings)[:300])
        holder["cand"] = sel.candidate
        c = sel.candidate
        return ArmRun("T-single", sel.result, histograms=tuple(c.histograms), phases=tuple(c.phases or phs),
                      derivation=c.derivation, background_coeffs=stage_background(c.stages),
                      stage_labels=tuple(s.label for s in c.stages))

    out["T-single"] = _guard("T-single", t_single)
    out["T-AB"] = _guard(
        "T-AB",
        lambda: from_report("T-AB", r.confirm(list(hists), list(phs), candidates=("template",),
                                              template_declarations=declarations, **ab, **kw)),
    )

    cand = holder.get("cand")

    def run_template_stages(arm: str, stages: tuple) -> ArmRun:
        res = r.single(list(cand.histograms), list(cand.phases or phs), recipe=stages,
                       stability=_TEMPLATE_STABILITY, blas_threads=1, **kw)
        return ArmRun(arm, res, histograms=tuple(cand.histograms), phases=tuple(cand.phases or phs),
                      derivation=cand.derivation, background_coeffs=stage_background(stages),
                      stage_labels=tuple(s.label for s in stages))

    # T-*/bkg — 比較相手の背景項数に置き換える
    def bkg_arm(arm: str, base: str, comparator: str, multistart: bool) -> ArmRun | None:
        comp, own = out.get(comparator), out.get(base)
        if cand is None or comp is None or comp.background_coeffs is None or own is None:
            return ArmRun(arm, None, error=f"{base} or {comparator} has no background count")
        if comp.background_coeffs == own.background_coeffs:
            return replace(own, arm=arm, same_as=base)
        stages = with_background(cand.stages, comp.background_coeffs)
        if not multistart:
            return run_template_stages(arm, stages)
        ms = r.multistart(
            list(cand.histograms), list(cand.phases or phs),
            config=MultistartConfig(n_starts=n_starts, spec=PerturbationSpec(lattice_frac=lattice_frac)),
            coord_jitter_ang=coord_jitter_ang, seed=seed, recipe=stages,
            stability=_TEMPLATE_STABILITY, blas_threads=1, **kw,
        )
        return ArmRun(arm, ms.best, error="" if ms.best is not None else "multistart had no best result",
                      histograms=tuple(cand.histograms), phases=tuple(cand.phases or phs), multistart=ms,
                      derivation=cand.derivation, background_coeffs=comp.background_coeffs,
                      stage_labels=tuple(s.label for s in stages))

    out["T-single/bkg"] = _guard("T-single/bkg", lambda: bkg_arm("T-single/bkg", "T-single", "B-single", False))
    out["T-AB/bkg"] = _guard("T-AB/bkg", lambda: bkg_arm("T-AB/bkg", "T-AB", "B-AB", True))

    # X-transplant — 現行の段順にテンプレートのモデル化の選択を移植
    def transplant() -> ArmRun:
        if cand is None:
            raise RuntimeError("template candidate unavailable")
        tphases = list(cand.phases or phs)
        recipe = tuple(r.recipe(list(cand.histograms), tphases, background_coeffs=int(cand.background_coeffs)))
        res = r.single(list(cand.histograms), tphases, recipe=recipe, **kw)
        return ArmRun("X-transplant", res, histograms=tuple(cand.histograms), phases=tuple(tphases),
                      background_coeffs=stage_background(recipe), stage_labels=tuple(s.label for s in recipe))

    out["X-transplant"] = _guard("X-transplant", transplant)

    for pid in permutations:
        arm = f"T-perm:{pid}"
        if cand is None:
            out[arm] = ArmRun(arm, None, error="template candidate unavailable")
            continue
        stages = permute_stages(cand.stages, pid)
        out[arm] = None if stages is None else _guard(arm, lambda s=stages, a=arm: run_template_stages(a, s))

    done: dict[str, ArmRun | None] = {
        k: (None if v is None or v.same_as else _with_posthoc(v, r.posthoc)) for k, v in out.items()
    }
    for k, v in out.items():
        if v is not None and v.same_as:
            base = done.get(v.same_as)
            # 同じ fit なので事後検査の値も同じもの (二度回さない)
            done[k] = replace(base, arm=k, same_as=v.same_as) if base is not None else v
    return done
