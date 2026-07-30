"""標準経路: **手順最適化 → 初期値摂動による収束確認** (Phase A → Phase B)。

2 段に分ける理由は交絡の排除である。手順どうしの一致を傍証にすると、一致しても
「同じ最小点」なのか「似た手順だから似た答え」なのかを切れない (実測: T3 の一致は rounds
だけが違う 2 案から来て、最良解は孤立した)。**手順を先に 1 つ決めてから初期値を振る**と、
観測されるベイスン構造は最適化問題そのものの性質になる。

    Phase A  `run_recipe_search`      → 収束した候補を採用 (一つでも収束すれば採用)
    Phase B  `run_multistart_rietveld` → その手順のまま初期値を振り、同じ解へ来るか

⚠ **Phase A が変えた入力ごと固定して Phase B へ渡す**。適応候補が勝った場合はレンジも背景項数も
変わっているので、元の入力で収束確認すると**別の土俵で確認したことになる**。

`run_auto_rietveld` は**単発プリミティブのまま変えない** — `insitu` が per-frame で呼ぶため
(REQ-SAR-502: operando は軽量な単一レシピを維持する)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .._json import finite_or_none
from ..multistart.perturb import MultistartConfig, PerturbationSpec
from ..store import Ledger
from .model import AutoRietveldResult, HistogramSpec, PhaseSpec
from .multistart import RietveldMultistartResult, run_multistart_rietveld
from .agreement import CELL, COORD, OCCUPANCY
from .search import DEFAULT_CANDIDATES, RecipeSearchResult, SearchConfig, run_recipe_search

#: 「解を採用してよいか」を決めるクラス。歪/プロファイルは縮退の影響を受けるため含めない —
#: 含めると縮退のあるデータでは**どの手順でも解が出せなくなる** (実測: T1 は歪が常に割れる)。
STRUCTURE_CLASSES = (CELL, COORD, OCCUPANCY)

__all__ = ["DEFAULT_COORD_JITTER_ANG", "ConvergenceReport", "optimize_then_confirm"]

#: 座標摂動の既定振幅 (Å) — **実測で決めた** (2026-07-30, T1/T3 掃引)。
#:
#: 判断材料は「構造ベイスンを実際に探れているか」と「大きすぎて壊れないか」の 2 つ。
#: 0.0 / 0.01 / 0.02 / 0.05 / 0.10 Å を T1 (`polish`, 5 開始点) と T3 (`sizestrain_last`,
#: 5 開始点) で掃引した結果:
#:
#: - **どの振幅でも座標クラスは AGREE**。0.10 Å 動かしても戻ってくる (T1 60 軸 / T3 55 軸)。
#: - **発散 0・validity fail の増加なし**。0.10 Å でも壊れない。
#: - 判定を分けているのは座標ではなく **T1 は歪・T3 は格子**であり、これらは摂動 0 でも割れる。
#:
#: つまり「壊れる上限」は 0.10 Å より上にあり、この 2 データでは 0.05 と 0.10 の情報量は
#: 変わらなかった。そこで**一致判定の床 (0.02 Å) の 2.5 倍**を採る — 「許容差より大きく
#: 動かして、許容差の内側へ戻ってきた」と言える最小の振幅であり、出発構造として物理的にも
#: 無理がない。上限側の余裕は残しておく (軽原子や短い結合を持つ構造では 0.10 Å が隣接サイトへ
#: 踏み込み得るため、2 データの無傷をもって安全とは言えない)。
DEFAULT_COORD_JITTER_ANG = 0.05


@dataclass(frozen=True)
class ConvergenceReport:
    """標準経路の結果 = 採用した手順 + その手順での収束確認。

    :param adopted_recipe: Phase A が採用した候補名 (全滅なら ``""``)
    :param search: Phase A の全候補表 (何を試したかは結果の一部)
    :param multistart: Phase B の開始点別結果とベイスン
    :param best: 最終的に採用する結果 = **収束確認で最良のフィット**。構造と歪が一致して
        いればプロファイル由来のばらつきは当てはめの良し悪しなので、最良を採ればよい
    """

    adopted_recipe: str
    search: "RecipeSearchResult | None"
    multistart: "RietveldMultistartResult | None"
    best: "AutoRietveldResult | None"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_corroborated(self) -> bool:
        """**全クラス**が収束したか (厳密な AND)。行動を決めるのは下の 2 つの方が有用。"""
        return bool(self.multistart is not None and self.multistart.is_global_corroborated)

    @property
    def structure_is_corroborated(self) -> bool:
        """**構造 (格子・座標・占有率) が収束したか** — 解を採用してよいかの判断。

        縮退 (サイズ/微小歪み ↔ Caglioti U/V/W) は手順では解消できないので、全クラスの
        収束を採用条件にすると**どのデータでも解を出せなくなる**。構造が収束していれば
        構造の答えは信頼でき、割れたクラスは「決まっていない」として報告すればよい。
        """
        ms = self.multistart
        if ms is None or not ms.class_convergence:
            return False
        return all(
            ms.class_convergence.get(c, "INCOMPARABLE") == "AGREE"
            for c in STRUCTURE_CLASSES
            if c in ms.class_convergence
        ) and any(c in ms.class_convergence for c in STRUCTURE_CLASSES)

    @property
    def undetermined_by_initial_values(self) -> tuple[str, ...]:
        """**初期値依存のため出版してはならない**パラメータ (esd を超えて開始点間で割れた)。

        縮退そのものは消せないが、影響を受けた値を「決まっている」として出すのは止められる。
        `AutoRietveldResult.undetermined_parameters` (単発の esd 判定) と同じ規律で、
        こちらは**複数開始点でしか見えない**種類の未決定を拾う。
        """
        return () if self.multistart is None else self.multistart.initial_value_dependent

    def to_dict(self) -> dict[str, Any]:
        return {
            "adopted_recipe": self.adopted_recipe,
            "is_corroborated": self.is_corroborated,
            # 【行動を決めるのはこの 2 つ】: 単一 bool は「何をすべきか」を語らない。
            "structure_is_corroborated": self.structure_is_corroborated,
            "undetermined_by_initial_values": list(self.undetermined_by_initial_values),
            "class_convergence": (
                {} if self.multistart is None else dict(self.multistart.class_convergence)
            ),
            "final_rwp": finite_or_none(self.best.final_rwp) if self.best else None,
            "search": None if self.search is None else self.search.to_dict(),
            "multistart": None if self.multistart is None else self.multistart.to_dict(),
            "warnings": list(self.warnings),
        }


def optimize_then_confirm(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    candidates: "Sequence[str] | None" = None,
    search_config: "SearchConfig | None" = None,
    n_starts: int = 5,
    lattice_frac: float = 0.007,
    coord_jitter_ang: float = DEFAULT_COORD_JITTER_ANG,
    jitter_seed: int = 0,
    jobs: "int | None" = None,
    ledger: "Ledger | None" = None,
    search_runner: "Any | None" = None,
    multistart_runner: "Any | None" = None,
    **run_kwargs: object,
) -> ConvergenceReport:
    """手順を最適化してから初期値を振って収束を確認する (標準経路)。

    :param candidates: Phase A の候補名 (None で `DEFAULT_CANDIDATES` = 実測で選んだ集合)
    :param n_starts: Phase B の開始点数。**奇数**にすると格子グリッドの中央が無摂動になり
        基準点が常に開始点集合へ入る
    :param coord_jitter_ang: 座標摂動の振幅 (Å, 既定 `DEFAULT_COORD_JITTER_ANG`)。
        0 にすると格子軸だけの試験になり、**構造の局所解を試験しない**
    :param jobs: Phase B の並列度 (None で開始点数)。開始点は独立なので**壁時計は最も遅い
        開始点 1 本分**になる (平均ではなく最悪であることに注意)
    :param search_runner: Phase A の候補実行 callable (**テスト注入専用のシーム**)。
        実運用経路は JSON spec であり ③ はここへ callable を送れない (CLAUDE.md §4.5)
    :param multistart_runner: Phase B の実行 callable (同上)
    """
    ledger = ledger if ledger is not None else Ledger()
    warnings: list[str] = []

    search = run_recipe_search(
        list(histograms), list(phases),
        names=tuple(candidates) if candidates is not None else DEFAULT_CANDIDATES,
        config=search_config, ledger=ledger, runner=search_runner, **run_kwargs,
    )
    selected = search.selected
    if selected is None or selected.result is None:
        warnings.append("全候補が失敗したため収束確認へ進めない (手順が 1 つも立たなかった)")
        return ConvergenceReport(
            adopted_recipe="", search=search, multistart=None, best=None,
            warnings=tuple(warnings),
        )

    # 【採用候補の入力ごと固定する】: 適応候補はレンジ/背景項数を変えているので、元の入力で
    #   Phase B を回すと**別の土俵で収束確認したことになる**。
    cand = selected.candidate
    confirm_kwargs = dict(run_kwargs)
    confirm_kwargs["recipe"] = cand.stages
    # 【`background_coeffs` は渡さない】: これは**レシピを組み立てる**引数であって
    #   `run_auto_rietveld` は受け取らない (渡すと全開始点が TypeError で落ちる)。採用候補の
    #   背景項数は `cand.stages` の `background: {"coeffs": N}` に既に焼き込まれているので、
    #   段列を運べば背景モデルも一緒に運ばれる。呼び出し側が渡してきた分もここで落とす。
    confirm_kwargs.pop("background_coeffs", None)
    if cand.stability is not None:
        confirm_kwargs["stability"] = cand.stability
    ledger.append(
        "convergence_phase_a",
        {
            "adopted": cand.name,
            "reason": search.selection_reason,
            "rwp": finite_or_none(selected.result.final_rwp),
            "n_candidates": len(search.outcomes),
        },
    )

    run_confirm = multistart_runner or run_multistart_rietveld
    multistart = run_confirm(
        list(cand.histograms), list(phases),
        config=MultistartConfig(
            n_starts=n_starts, spec=PerturbationSpec(lattice_frac=lattice_frac)
        ),
        ledger=ledger,
        coord_jitter_ang=coord_jitter_ang,
        seed=jitter_seed,
        jobs=jobs,
        **confirm_kwargs,
    )
    warnings.extend(f"収束確認: {w}" for w in multistart.warnings)
    diverged = [
        c for c, v in multistart.class_convergence.items() if v != "AGREE"
    ]
    if diverged:
        warnings.append(
            f"初期値依存のクラス: {sorted(diverged)} — **これらの値は「決まっている」として"
            "出版してはならない**。縮退 (サイズ/微小歪み ↔ Caglioti U/V/W) は手順では解消"
            "できないので、閾値を緩めて隠すのではなく未決定として報告する"
        )
    if diverged and not set(diverged) & set(STRUCTURE_CLASSES):
        warnings.append(
            "**構造 (格子・座標・占有率) は収束している** — 構造の答えは採用してよい。"
            f"割れているのは {sorted(diverged)} だけである"
        )
    # 最終値は収束確認の最良フィット (Phase A の単発結果ではない — 同じ手順で複数点走らせた
    # うちの最良の方が、常に同等以上である)。
    best = multistart.best if multistart.best is not None else selected.result
    return ConvergenceReport(
        adopted_recipe=cand.name, search=search, multistart=multistart,
        best=best, warnings=tuple(warnings),
    )
