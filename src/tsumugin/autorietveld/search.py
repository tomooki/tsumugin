"""レシピ探索 — 「収束したものの中で最良」を**測って**選ぶ (REQ-SAR-500/501/502)。

## なぜ探索するのか (実測)

段の順序も解放手順も、**単一のレシピで全データを満たすことはできない**。試料変位段の配置
4 通り × 4 データではどの配置でも 1 つ以上が落ち、レシピ 3 本は 3 通りの勝ち方をした
(真の基準表 2026-07-29):

===========  ==========  ==========
データ       default     serious
===========  ==========  ==========
T1            **9.81**    10.45
T2             4.33        4.32
T3             6.66       **6.10**
CaTeO3        12.20       12.19
===========  ==========  ==========

順序を*当てる*のは不可能なので、**候補を独立に実行して測り、規則で選ぶ**
(`docs/design/stable-auto-rietveld/phase2-search.md` S1-S6)。

## 選択規則 (S1)

1. **収束**でふるいに掛ける (未収束は最良ではない)
2. **妥当性**で降格する (fail は**除外せず**所見付きで残す — Dara 教訓と同じ規律)
3. **観測集合 (レンジ) が違う候補**は Rwp/BIC では上に来られない
   (`observation_groups` — χ² は観測点数に比例するので**データを捨てた候補が必ず勝つ**)
4. 残りから **Rwp 最良**を採る
5. **同点近傍** (Rwp 差 < ``rwp_tie_eps``) は **BIC** で裁定する
   (候補間で母数が違うと Rwp 比較は不公平。式は `insitu.anchor.select.frame_bic` と同一)

### ⚠ 収束フィルタを素朴に適用すると全候補が落ちる (WS-1 実測)

T1 の「成功している」段でさえ shift/esd 基準では収束していない (max shft/sig = 86/116/47、
S1/S2 は GSAS 自身の ``converged`` も False)。**フィルタを字義どおり実装すると答えが
1 つも残らない**。

本実装は「フィルタ」を **tier (層) による順位付け + フォールバック**として実現する:

===== ====================== ==============================================
tier  条件                   意味
===== ====================== ==============================================
0     収束 ∧ 妥当            採用したい層
1     収束 ∧ 妥当性 fail     妥当性は**降格**なので収束層の中で下位
2     未収束 ∧ 妥当          収束層が空のときだけ到達する (フォールバック)
3     未収束 ∧ 妥当性 fail   同上
4     実行失敗 / Rwp 非有限  順位表には残すが決して選ばれない
===== ====================== ==============================================

**最良 tier の中だけで** Rwp/BIC 裁定を行う。収束候補が 1 つでもあれば tier 0/1 で決着する
ので、これは「未収束を落とすフィルタ」と厳密に同じ振る舞いになる。全候補が未収束のときだけ
tier 2/3 へ落ち、``convergence_fallback=True`` と**警告**を添えて最良を返す。

なぜ閾値を緩める案 (option 2) を採らなかったか: 判定に使える材料は GSAS 自身の
``Rvals['converged']`` であって我々の閾値ではない。加えて ``Max shft/sig`` は
``np.max(Lastshft/sig)`` で**絶対値ではなく**、強い負シフトは小さい値として通る (上流仕様,
WS-1 実測) — 片側にしか効かない量の閾値をこちらで動かしても「収束した」の意味は良くならない。
なぜ純粋なランキング第 2 キー (option 3) にしなかったか: それでは Rwp が僅かに良い未収束解が
収束解に勝ってしまい、S1 の設計意図 (**収束していない best を選ばない**) が消える。

## 何をしないか

- **ビームサーチはしない** (S4)。候補レシピの独立実行に留める — 実装の単純さと再現性を
  探索効率より優先する (時間は無視できるという前提)。
- **operando は探索しない** (S6, REQ-SAR-502)。フレーム数 × 候補数の積は現実的でない。
  `tsumugin.insitu` は本モジュールを import しない (`tests/autorietveld/test_search.py` の
  非回帰ガードが強制する)。
- 並列実行は**呼び出し側の責務**。選択は列挙順で解決するので、完走順が変わっても結果は
  ビット同一である (S5 / P-SAR-4)。

信頼性: 🔵 `docs/design/stable-auto-rietveld/phase2-search.md` の S1-S6 と 1:1。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable, Mapping, Sequence

from .._json import finite_or_none
from ..store import Ledger
from .model import (
    AutoRietveldResult,
    HistogramSpec,
    PhaseSpec,
    RefinementStage,
    StabilityOptions,
    StageResult,
)
from .agreement import (
    CorroborationReport,
    ProcedureProvenance,
    cluster_agreement_basins,
    effective_trajectory,
)
from .recipe import build_recipe, build_serious_recipe

__all__ = [
    "CANDIDATE_NAMES",
    "CandidateOutcome",
    "CandidateRunner",
    "RecipeCandidate",
    "RecipeSearchResult",
    "SearchConfig",
    "TIER_LABELS",
    "build_candidates",
    "DEFAULT_CANDIDATES",
    "candidate_bic",
    "convergence_verdict",
    "outcome_tier",
    "rank_outcomes",
    "run_recipe_search",
    "summarize_search",
]

#: 候補の**列挙順** (S5)。辞書順や集合順ではなく明示的なタプルにする — 実装都合で順序が
#: 変わると同点解決が揺れ、決定論 (P-SAR-4) が崩れる。実績のある固定層を先に置き、
#: 自動判定の適応層を後ろに置く (同点なら実績側が勝つ)。
CANDIDATE_NAMES: tuple[str, ...] = (
    "default",
    "sizestrain_last",
    "polish",
    "serious1",
    "serious",
    "adaptive",
)

#: ``search=true`` が実際に回す集合 = **実測で選んだ手順** (2026-07-30, 10 案 × 4 データ)。
#: データ毎の収束した勝者は T1/CaTeO3 = ``polish`` / T2 = ``serious1`` / T3 = ``sizestrain_last``
#: で、``default`` は基準 (列挙 index 0 が `observation_groups` の観測集合基準になる) として置く。
#: ``serious`` (2 周) は**測定で支配された**ため既定から外した — T3 では ``sizestrain_last``
#: (5.98) が、T2/CaTeO3 では ``serious1`` が同等以上で、かつ 2 周は 1 周の 1.4 倍の時間を要する。
#: 名前としては選べるまま残してある (``search: ["serious"]`` は従来どおり動く)。
#: ⚠ **順序を変えないこと** — `observation_groups` の基準と全ての同点解決を駆動する。
DEFAULT_CANDIDATES: tuple[str, ...] = (
    "default",
    "sizestrain_last",
    "polish",
    "serious1",
    "adaptive",
)

#: tier → 人間が読むラベル (② / ledger / 報告に出す)。
TIER_LABELS: tuple[str, ...] = (
    "収束∧妥当",
    "収束∧妥当性fail",
    "未収束∧妥当",
    "未収束∧妥当性fail",
    "実行失敗",
)

_TIER_CONVERGED_VALID = 0
_TIER_CONVERGED_INVALID = 1
_TIER_UNCONVERGED_VALID = 2
_TIER_UNCONVERGED_INVALID = 3
_TIER_FAILED = 4

#: 段の note に engine (診断ゲート REQ-SAR-101) が書く未収束マーカ。
_UNCONVERGED_NOTE = "unconverged"


# ===========================================================================
# 設定
# ===========================================================================


@dataclass(frozen=True)
class SearchConfig:
    """レシピ探索の判定閾値 (不変)。

    :param rwp_tie_eps: **同点近傍**とみなす Rwp 差 [ポイント]。この窓の中は BIC で裁定する
        (母数の違う候補を Rwp だけで比べない)。0 にすると BIC 裁定を実質無効化できる。
    :param disagreement_rwp_eps: 「Rwp はほぼ同じ」とみなす窓 [ポイント]。この窓の中で
        格子/相分率が有意に違えば**順序依存**として警告する (REQ-SAR-501)。
    :param cell_rel_tol: 格子が「有意に違う」相対差の閾値 (既定 1e-3 = 0.1%)。精密化された
        格子の esd は通常これより 1-2 桁小さいので、0.1% の食い違いは数値誤差では説明できない。
    :param fraction_abs_tol: 相分率が「有意に違う」絶対差の閾値 (既定 0.02)。
    :param require_convergence: 収束を tier の一次キーにするか。``False`` にすると妥当性だけで
        降格し、収束は報告のみになる (**既定 True** — 収束していない best を選ばないため)。
    """

    rwp_tie_eps: float = 0.1
    disagreement_rwp_eps: float = 0.5
    cell_rel_tol: float = 1.0e-3
    fraction_abs_tol: float = 0.02
    require_convergence: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "rwp_tie_eps": self.rwp_tie_eps,
            "disagreement_rwp_eps": self.disagreement_rwp_eps,
            "cell_rel_tol": self.cell_rel_tol,
            "fraction_abs_tol": self.fraction_abs_tol,
            "require_convergence": self.require_convergence,
        }

    @classmethod
    def from_dict(cls, d: "Mapping[str, object] | None") -> "SearchConfig":
        """JSON spec から組み立てる (② 到達可能性: ③ は JSON しか送れない)。

        **未知キーは ``ValueError``** — 黙って無視すると「閾値を変えたつもりが効いていない」
        という静かな失敗になる (② ツールが error dict へ縮退させる)。
        """
        if not d:
            return cls()
        known = {"rwp_tie_eps", "disagreement_rwp_eps", "cell_rel_tol",
                 "fraction_abs_tol", "require_convergence"}
        unknown = sorted(set(d) - known)
        if unknown:
            raise ValueError(
                f"search_config に未知のキーがあります: {unknown} (既知: {sorted(known)})"
            )
        return cls(
            rwp_tie_eps=float(d.get("rwp_tie_eps", 0.1)),  # type: ignore[arg-type]
            disagreement_rwp_eps=float(d.get("disagreement_rwp_eps", 0.5)),  # type: ignore[arg-type]
            cell_rel_tol=float(d.get("cell_rel_tol", 1.0e-3)),  # type: ignore[arg-type]
            fraction_abs_tol=float(d.get("fraction_abs_tol", 0.02)),  # type: ignore[arg-type]
            require_convergence=bool(d.get("require_convergence", True)),
        )


# ===========================================================================
# 候補と結果
# ===========================================================================


@dataclass(frozen=True)
class RecipeCandidate:
    """探索する候補 1 つ (レシピ + その候補が使う入力)。

    **ヒストグラムを候補が持つ**のは、適応層 (S2) がデータレンジを変えた変種を作るためである。
    レシピだけを差し替える設計にすると、レンジ/背景の自動判定を「別候補として保険付きで試す」
    ことができず、自動判定が外れたときの逃げ道が無くなる。

    :param name: 候補名 (`CANDIDATE_NAMES` のいずれか、または呼び出し側が組んだ任意名)
    :param stages: 段階解放レシピ (`run_auto_rietveld(recipe=...)` にそのまま渡す)
    :param origin: ``"fixed"`` (実績のある固定レシピ) / ``"adaptive"`` (自動判定由来)
    :param histograms: この候補が使うヒストグラム仕様 (適応層はレンジ調整済み)
    :param background_coeffs: この候補の背景項数 (レシピ生成に使った値。報告用)
    :param note: 何をした候補かの説明 (③ / 人間が読む)
    """

    name: str
    stages: tuple[RefinementStage, ...]
    origin: str
    histograms: tuple[HistogramSpec, ...]
    background_coeffs: int = 6
    note: str = ""
    # 【末尾追加・既定 None で後方互換】: 候補は**段列だけでは表せない** — 最終研磨のような
    #   「手順」は `StabilityOptions` 側にあるため、候補が自分の実行設定を持つ必要がある。
    #   None は「既定の実行設定 (= 呼び出し側の `run_kwargs` のまま)」を意味する。
    stability: "StabilityOptions | None" = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "origin": self.origin,
            "n_stages": len(self.stages),
            "background_coeffs": self.background_coeffs,
            "two_theta_limits": [
                list(h.two_theta_limits) if h.two_theta_limits is not None else None
                for h in self.histograms
            ],
            "note": self.note,
        }


@dataclass(frozen=True)
class CandidateOutcome:
    """候補 1 つの実行結果 (成功/失敗の両方を表す)。

    :param index: **列挙順の位置**。同点解決の最終キー (S5: 完走順に依存させない)
    :param candidate: 実行した候補
    :param result: 精密化結果 (実行失敗なら None)
    :param error: 実行失敗の理由 (成功なら空文字)
    """

    index: int
    candidate: RecipeCandidate
    result: "AutoRietveldResult | None" = None
    error: str = ""

    @property
    def rwp(self) -> float:
        """最終 Rwp (実行失敗/非有限は ``inf``)。順位付けの二次キー。"""
        if self.result is None or not math.isfinite(self.result.final_rwp):
            return math.inf
        return float(self.result.final_rwp)

    @property
    def valid(self) -> bool:
        return self.result is not None and bool(self.result.validity.passed)

    @property
    def bic(self) -> float:
        return math.inf if self.result is None else candidate_bic(self.result)

    def to_dict(self, *, require_convergence: bool = True) -> dict[str, object]:
        """素の型 dict へ (② / ledger / GUI)。

        :param require_convergence: **報告する tier を、実際に順位付けへ使った規則で計算する**
            ためのキー。``require_convergence`` は ② の ``search_config`` から設定できる公開ノブ
            であり、``rank_outcomes``/`summarize_search` は ``config.require_convergence`` で
            tier を計算する。ここで ``True`` を決め打ちすると、``false`` を渡した呼び手には
            **「報告された tier」と「選択に使われた tier」が食い違う**答えが返る
            (③ は「なぜその候補が勝ったか」を tier_label で読む)。呼び出し側は
            `RecipeSearchResult.to_dict` / `run_recipe_search` が config の値を渡す。
        """
        verdict, reason = (None, "実行失敗") if self.result is None else convergence_verdict(
            self.result
        )
        tier = outcome_tier(self, require_convergence=require_convergence)
        return {
            "index": self.index,
            "candidate": self.candidate.to_dict(),
            "rwp": finite_or_none(self.rwp),
            "gof": finite_or_none(self.result.final_gof) if self.result else None,
            "n_params": accepted_n_params(self.result) if self.result else None,
            # n_obs も出す: BIC を**この 1 エントリだけから**再導出できるようにするため
            # (GUI の LEDGER が `gof/n_params/n_obs` から同じ式で計算する。値を 2 系統持つと
            # 片方が古くなる)。
            "n_obs": int(self.result.n_obs) if self.result else None,
            "bic": finite_or_none(self.bic),
            "converged": verdict,
            "converged_reason": reason,
            "validity_passed": self.valid,
            "tier": tier,
            "tier_label": TIER_LABELS[tier],
            "error": self.error,
        }


@dataclass(frozen=True)
class RecipeSearchResult:
    """レシピ探索の結果 (全候補 + 選択 + 警告)。

    :param outcomes: **列挙順**の全候補結果 (落ちた候補も残す — 何を試したかは結果の一部)
    :param ranking: 順位順の `outcomes` index (先頭 = 採用)。全候補を含む全順序
    :param selected_index: 採用した候補の `outcomes` index。**全滅なら -1**
    :param convergence_fallback: 収束層が空で未収束層へ落ちたか (信頼度が低い印)
    :param order_dependent: 最良と次点が僅差なのに答えが割れたか (REQ-SAR-501)
    :param selection_reason: なぜその候補を採ったか — **次点と最初に食い違った順位キー**
        (``tier`` 収束/妥当性 / ``observation_set`` 観測集合が違い比較していない / ``rwp`` /
        ``bic`` 同点近傍の裁定 / ``only_candidate``)
    :param warnings: 人間/③ が読む警告
    :param config: 判定に使った閾値 (再現性のため結果に同梱する)
    :param agreement: **どの手順どうしが同じ解に収束したか** (`autorietveld.agreement`)。
        `order_dependent` とは別の問いに答える — あちらは「最良と次点が僅差なのに割れた」
        という*選択の信頼度*の旗 (上位 2 件のみ・相分率 Scale 基準)、こちらは全対の
        *収束の一致* (esd スケール・構造クラス) である。両者は冗長ではない
    """

    outcomes: tuple[CandidateOutcome, ...]
    ranking: tuple[int, ...]
    selected_index: int
    convergence_fallback: bool = False
    order_dependent: bool = False
    selection_reason: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
    config: SearchConfig = field(default_factory=SearchConfig)
    # 【末尾追加・既定 None で後方互換】: 傍証を計算しなかった (結果が 1 つ以下 / 呼び出し側が
    #   要求しなかった) 場合は None。**空の報告を捏造しない** — 「一致を調べていない」と
    #   「調べたが一致しなかった」は別の陳述である。
    agreement: "CorroborationReport | None" = None

    @property
    def selected(self) -> "CandidateOutcome | None":
        """採用した候補結果 (全滅なら None — **捏造した最良を返さない**)。"""
        if self.selected_index < 0:
            return None
        return self.outcomes[self.selected_index]

    @property
    def best(self) -> "AutoRietveldResult | None":
        """採用した候補の精密化結果 (全滅なら None)。"""
        sel = self.selected
        return None if sel is None else sel.result

    @property
    def ranked(self) -> tuple[CandidateOutcome, ...]:
        """順位順の候補結果。"""
        return tuple(self.outcomes[i] for i in self.ranking)

    def to_dict(self) -> dict[str, object]:
        """素の型 dict へ (② MCP 境界。非有限は None 化され ``allow_nan=False`` で安全)。"""
        return {
            # tier は**この結果を選んだ規則**で計算する (config を落として True 決め打ちにすると
            # 報告 tier と選択 tier が食い違う — `CandidateOutcome.to_dict` の docstring 参照)。
            "candidates": [
                o.to_dict(require_convergence=self.config.require_convergence)
                for o in self.outcomes
            ],
            "ranking": list(self.ranking),
            "selected_index": self.selected_index,
            "selected": None if self.selected is None else self.selected.candidate.name,
            "selection_reason": self.selection_reason,
            "convergence_fallback": self.convergence_fallback,
            "order_dependent": self.order_dependent,
            "warnings": list(self.warnings),
            "config": self.config.to_dict(),
            "agreement": None if self.agreement is None else self.agreement.to_dict(),
        }


#: 候補 1 つを実行する関数 (既定は GSAS 駆動 `run_auto_rietveld`)。
#: **注入は探索の並列化とテストのためのシーム** — ② からは JSON spec で到達する。
CandidateRunner = Callable[[RecipeCandidate], AutoRietveldResult]


# ===========================================================================
# 判定の素材 (純関数)
# ===========================================================================


def accepted_stage(result: "AutoRietveldResult | None") -> "StageResult | None":
    """**最後に受理された段** (revert されていない段) を返す。

    revert された段は gpx ごと巻き戻されているので、その段の未収束/母数は**最終状態の性質
    ではない**。最終 Rwp を作ったのは最後に受理された段である。1 段も受理されていない
    (全段 revert) 場合は None。
    """
    if result is None:
        return None
    for stage in reversed(result.stage_results):
        if not stage.reverted:
            return stage
    return None


def accepted_n_params(result: "AutoRietveldResult | None") -> int:
    """最終状態の母数 (最後に受理された段の ``n_params``)。受理段が無ければ 0。"""
    stage = accepted_stage(result)
    return 0 if stage is None else int(stage.n_params)


def convergence_verdict(result: "AutoRietveldResult | None") -> tuple["bool | None", str]:
    """候補が収束したか — ``True`` / ``False`` / ``None`` (判定材料なし) と理由を返す。

    情報源は 2 つで、**厳しい方を採る**:

    - engine が段の note に書く ``unconverged`` — `StabilityOptions.require_convergence` を
      有効にしたときだけ現れる、``Max shft/sig`` 由来の厳しい判定 (REQ-SAR-101)
    - `StageResult.converged` — GSAS 自身の ``Rvals['converged']``。診断ゲート未使用でも常に
      得られる。⚠ Rvals にキーが無いときは engine が ``True`` に縮退させる (fail open) ので、
      「情報が無い」と「収束した」をここで区別することはできない

    ``None`` を返すのは**受理された段が 1 つも無い**ときだけで、「収束した」とは答えない
    (情報が無いことを正常と答えない ② の規律と同じ)。呼び出し側 (`outcome_tier`) は
    ``None`` を fail open (収束側の層) で扱う — 判定材料が無いことを理由に候補を降格させると、
    診断ゲート無しの既定経路が丸ごと降格してしまうためである。
    """
    stage = accepted_stage(result)
    if stage is None:
        return None, "受理された段がありません (全段 revert)"
    if _UNCONVERGED_NOTE in stage.note:
        return False, f"{stage.label}: 診断ゲートが未収束と判定 (note={stage.note!r})"
    if not stage.converged:
        return False, f"{stage.label}: GSAS の converged=False"
    return True, f"{stage.label}: converged=True"


def candidate_bic(result: "AutoRietveldResult | None") -> float:
    """候補の BIC = ``χ² + n_params·ln(n_obs)``、``χ² = GOF²·(n_obs − n_params)``。

    **`insitu.anchor.select.frame_bic` と同一式**である。相数を Rwp で決めない規律
    (Rwp は母数を増やせば単調に減る) をレシピ選択にも適用するのが目的なので、式が場所ごとに
    違うと「BIC で裁定した」という主張の意味が変わってしまう。

    ``n_obs`` が未設定 (0) の結果では ``n_obs=1`` に縮退し penalty ≈ 0 になる — その場合の
    BIC 裁定は実質 χ² 比較になる (スタブ/旧構築への fail open)。
    """
    if result is None or not math.isfinite(result.final_gof):
        return math.inf
    if not math.isfinite(result.final_rwp):
        return math.inf
    n_obs = max(int(result.n_obs), 1)
    n_params = accepted_n_params(result)
    dof = max(n_obs - n_params, 1)
    chi2 = float(result.final_gof) ** 2 * dof
    return chi2 + n_params * math.log(n_obs)


def outcome_tier(outcome: CandidateOutcome, *, require_convergence: bool = True) -> int:
    """候補を層 (tier) へ振り分ける — モジュール docstring の表を実装したもの。

    収束が一次キー (**フィルタ**)、妥当性が二次キー (**降格**)。``require_convergence=False``
    なら収束は tier に効かせず報告のみにする。
    """
    if outcome.result is None or not math.isfinite(outcome.rwp):
        return _TIER_FAILED
    valid = outcome.valid
    if not require_convergence:
        return _TIER_CONVERGED_VALID if valid else _TIER_CONVERGED_INVALID
    verdict, _ = convergence_verdict(outcome.result)
    # None (判定材料なし) は fail open で収束側に置く — 診断ゲート無しの既定経路を
    # 「情報が無い」という理由だけで降格させないため。
    converged = verdict is not False
    if converged:
        return _TIER_CONVERGED_VALID if valid else _TIER_CONVERGED_INVALID
    return _TIER_UNCONVERGED_VALID if valid else _TIER_UNCONVERGED_INVALID


# ===========================================================================
# 順位付けと選択 (S1 / S5)
# ===========================================================================


def observation_groups(outcomes: Sequence[CandidateOutcome]) -> tuple[int, ...]:
    """候補を**観測集合**で 0 (基準と同一) / 1 (異なる) に分ける。

    ⚠ **これは実測で必要になった規則である** (T1 で発覚)。適応候補がレンジを 19.32–130° に
    切り詰めると観測点数が 5752 → 5535 に減り、``χ² = GOF²·(n_obs − n_params)`` は**点数に
    比例して小さくなる**ので BIC が 17875 → 16785 と下がる。つまり**データを捨てた候補が
    BIC で必ず勝つ**という構造的バイアスがある (実測: T1 で adaptive が既知最良の default に
    Rwp 差 0.019 で "勝った")。Rwp も同じ理由で観測集合を跨いでは比較できない
    (③ の受理基準にも「データリミット変更は Rwp 比較不能」と書いてある)。

    したがって**観測集合が違う候補は Rwp/BIC では上に来られない** ようにする。勝てるのは
    tier (収束・妥当性) だけである — これは適応レンジの本来の動機と正確に一致する:
    T4 の非収束はレンジ未設定が主因だったので、レンジを切った候補は「収束する」ことで
    勝つべきであって、「点数が減って χ² が小さい」ことで勝つべきではない。

    基準は**列挙順で最初に結果を返した候補** (= 固定層 ``default``) の観測点数。
    ``n_obs`` が 0 (未設定/スタブ) の候補は基準と同一扱い (fail open)。
    """
    ref: "int | None" = None
    for o in outcomes:
        if o.result is not None and int(o.result.n_obs) > 0:
            ref = int(o.result.n_obs)
            break
    if ref is None:
        return tuple(0 for _ in outcomes)
    groups: list[int] = []
    for o in outcomes:
        n = int(o.result.n_obs) if o.result is not None else 0
        groups.append(0 if n in (0, ref) else 1)
    return tuple(groups)


def rank_outcomes(
    outcomes: Sequence[CandidateOutcome], config: SearchConfig
) -> tuple[tuple[int, ...], bool]:
    """候補を順位付けし ``(ranking, convergence_fallback)`` を返す (決定論)。

    順位は ``(tier, 観測集合, rwp, 列挙順)`` の全順序。ただし**先頭 (= 採用) だけ**は
    最良 tier かつ**同じ観測集合**の中で「Rwp 最小から ``rwp_tie_eps`` 以内」の同点群を作り、
    その中で BIC 最小を採る (S1-4)。観測集合を分ける理由は `observation_groups` を参照。

    同点は最後に必ず**列挙順**で解決する — 並列実行の完走順や浮動小数の揺らぎで採用が
    変わらないため (S5 / P-SAR-4)。
    """
    if not outcomes:
        return (), False
    tiers = [outcome_tier(o, require_convergence=config.require_convergence) for o in outcomes]
    groups = observation_groups(outcomes)
    order = sorted(
        range(len(outcomes)),
        key=lambda i: (tiers[i], groups[i], outcomes[i].rwp, outcomes[i].index),
    )
    best_tier = tiers[order[0]]
    if best_tier >= _TIER_FAILED:
        # 全滅 — 順位表は残すが選択はしない (捏造した最良を返さない)。
        return tuple(order), False
    best_group = groups[order[0]]
    pool = [i for i in order if tiers[i] == best_tier and groups[i] == best_group]
    rwp_min = outcomes[pool[0]].rwp
    tie = [i for i in pool if outcomes[i].rwp <= rwp_min + config.rwp_tie_eps]
    winner = min(tie, key=lambda i: (outcomes[i].bic, outcomes[i].index))
    ranking = (winner, *[i for i in order if i != winner])
    fallback = best_tier in (_TIER_UNCONVERGED_VALID, _TIER_UNCONVERGED_INVALID)
    return ranking, fallback


def _cell_disagreements(
    a: AutoRietveldResult, b: AutoRietveldResult, rel_tol: float
) -> tuple[str, ...]:
    """2 結果の格子で相対差が ``rel_tol`` を超える (相, 軸) を列挙する。"""
    labels = ("a", "b", "c", "alpha", "beta", "gamma")
    out: list[str] = []
    for name, cell in sorted(a.refined_cells.items()):
        other = b.refined_cells.get(name)
        if other is None:
            continue
        for label, x, y in zip(labels, cell, other):
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            denom = max(abs(x), abs(y), 1e-12)
            if abs(x - y) / denom > rel_tol:
                out.append(f"{name}.{label} {x:.6g} vs {y:.6g}")
    return tuple(out)


def _fraction_disagreements(
    a: AutoRietveldResult, b: AutoRietveldResult, abs_tol: float
) -> tuple[str, ...]:
    """2 結果の相分率で絶対差が ``abs_tol`` を超える相を列挙する。"""
    out: list[str] = []
    for name in sorted(set(a.phase_fractions) & set(b.phase_fractions)):
        x, y = float(a.phase_fractions[name]), float(b.phase_fractions[name])
        if math.isfinite(x) and math.isfinite(y) and abs(x - y) > abs_tol:
            out.append(f"{name} {x:.3f} vs {y:.3f}")
    return tuple(out)


def summarize_search(
    outcomes: Sequence[CandidateOutcome], config: "SearchConfig | None" = None
) -> RecipeSearchResult:
    """候補結果から順位・選択・警告を組み立てる (純関数, GSAS 非依存)。

    警告は 5 種:

    - **実行失敗** — 何が落ちたかを黙らせない
    - **収束フォールバック** — 全候補が未収束だったので信頼度が低い
    - **妥当性 fail** — 採用した候補が物理妥当性ゲートを通っていない (降格しても残る所見)
    - **観測集合の相違** — 候補表の Rwp 列を素直に比べてはいけないという事実
    - **順序依存** (REQ-SAR-501) — 最良と次点が僅差なのに格子/相分率が有意に違う

    ⚠ 順序依存の判定は次点が**別の観測集合**でも行う。Rwp 差の比較自体は厳密には
    apples-to-apples でないが、「設定を変えたら格子が動いた」という事実は報告する側に倒す
    (黙る方が有害。判断材料は警告文に相/軸ごとの値として全部出す)。
    """
    config = config or SearchConfig()
    outcomes = tuple(outcomes)
    ranking, fallback = rank_outcomes(outcomes, config)
    warnings: list[str] = []

    for o in outcomes:
        if o.error:
            warnings.append(f"候補 {o.candidate.name!r} の実行が失敗しました: {o.error}")

    tiers = [outcome_tier(o, require_convergence=config.require_convergence) for o in outcomes]
    groups = observation_groups(outcomes)
    selected_index = -1
    reason = ""
    if ranking and tiers[ranking[0]] < _TIER_FAILED:
        selected_index = ranking[0]
    if selected_index < 0:
        warnings.append("採用できる候補がありません (全候補が実行失敗 / Rwp 非有限)")
        return RecipeSearchResult(
            outcomes=outcomes, ranking=ranking, selected_index=-1,
            convergence_fallback=fallback, warnings=tuple(warnings), config=config,
        )

    selected = outcomes[selected_index]
    runners_up = [i for i in ranking[1:] if outcomes[i].result is not None]
    if not runners_up:
        reason = "only_candidate"
    else:
        second_index = runners_up[0]
        second = outcomes[second_index]
        # 【なぜ勝ったかを言い切る】: 順位キーは (tier, 観測集合, rwp, bic) の階層なので、
        #   **次点と最初に食い違ったキー**がその候補が勝った理由である。「Rwp が良かった」と
        #   一括りにすると、③ は「収束で勝った」「観測集合が違うので比較していない」を
        #   Rwp の勝利と誤読する。
        if tiers[selected_index] != tiers[second_index]:
            reason = "tier"
        elif groups[selected_index] != groups[second_index]:
            reason = "observation_set"
        elif selected.rwp < second.rwp:
            reason = "rwp"
        else:
            reason = "bic"

    if fallback:
        warnings.append(
            "全候補が収束していないため収束フィルタを無効化しました "
            "(選ばれた解は信頼度が低い — 追加サイクル/レンジ/母数を疑うこと)"
        )
    if not selected.valid:
        warnings.append(
            f"採用候補 {selected.candidate.name!r} は物理妥当性ゲートに合格していません "
            "(降格したうえで最良だったため採用。所見として扱うこと)"
        )
    # 【観測集合が違う候補があることを隠さない】: 適応層 (S2) はデータレンジを変えうるので、
    #   その候補の Rwp/BIC は他候補と**同じ観測集合の上に無い**。順位付けでは別扱いにして
    #   いるが、候補表の Rwp 列を素直に比べられると誤読されるため事実を添える
    #   (③ の受理基準にも「データリミット変更は Rwp 比較不能」と書いてある)。
    off_group = [
        f"{outcomes[i].candidate.name!r}={int(outcomes[i].result.n_obs)}"  # type: ignore[union-attr]
        for i in range(len(outcomes))
        if groups[i] == 1 and outcomes[i].result is not None
    ]
    if off_group:
        n_sel = int(selected.result.n_obs)  # type: ignore[union-attr]
        warnings.append(
            f"観測点数が候補間で異なります (採用候補={n_sel} / {', '.join(off_group)})。"
            "Rwp/BIC は同じ観測集合の上でしか比較できないため、レンジを変えた候補は"
            "**収束・妥当性でしか上位に来られない**規則で順位付けしている "
            "(候補表の Rwp 列を素直に比べないこと)"
        )

    order_dependent = False
    if runners_up:
        second = outcomes[runners_up[0]]
        if abs(selected.rwp - second.rwp) < config.disagreement_rwp_eps:
            cells = _cell_disagreements(selected.result, second.result, config.cell_rel_tol)  # type: ignore[arg-type]
            fracs = _fraction_disagreements(
                selected.result, second.result, config.fraction_abs_tol  # type: ignore[arg-type]
            )
            if cells or fracs:
                order_dependent = True
                # **何が割れたか**を名前で言う。「答えが割れた」だけでは ③ は次に何を確かめれば
                # よいか決められない (格子なら段順序/変位、相分率なら初期分率と相集合を疑う)。
                parts: list[str] = []
                if cells:
                    parts.append("格子: " + ", ".join(cells[:3]))
                if fracs:
                    parts.append("相分率: " + ", ".join(fracs[:3]))
                warnings.append(
                    f"順序依存の疑い: {selected.candidate.name!r} と "
                    f"{second.candidate.name!r} は Rwp 差 "
                    f"{abs(selected.rwp - second.rwp):.3f} と僅差なのに答えが割れています "
                    f"[{'; '.join(parts)}]。この解は信頼度が低い — "
                    "追加測定か手動確認を検討すること"
                )

    # 【収束の一致 (傍証)】: 候補が 2 つ以上あるときだけ計算する — 1 つでは「クラスタが 1 つ」が
    #   空虚に成立するので、**報告そのものを作らない** (空の報告は「調べたが一致しなかった」と
    #   読めてしまい、「調べていない」との区別が消える)。
    agreement = None
    if sum(1 for o in outcomes if o.result is not None) >= 2:
        agreement = cluster_agreement_basins(
            [o.result for o in outcomes],
            [
                ProcedureProvenance(
                    label=o.candidate.name,
                    # 1 回の探索では**全候補が同じ相仕様を共有する** (候補が持つのは
                    # ヒストグラムと段列だけ) ため、構造パスの食い違いは構成上起き得ない。
                    # 空で渡すのが正しい — `getattr` で無い属性を探るのは死んだ反射になる。
                    # この検査が意味を持つのは run をまたいだ比較 (別 CIF どうし) のときで、
                    # そこでは呼び出し側が `compare_results` を直接使う。
                    structure_paths={},
                    trajectory=(
                        effective_trajectory(o.result) if o.result is not None else ()
                    ),
                    stage_metrics=(
                        tuple(
                            (st.rwp, st.gof, st.n_params) for st in o.result.stage_results
                        )
                        if o.result is not None
                        else ()
                    ),
                    n_obs=o.result.n_obs if o.result is not None else 0,
                    frozen_parameters=(
                        tuple(o.result.frozen_parameters) if o.result is not None else ()
                    ),
                )
                for o in outcomes
            ],
        )
        for w in agreement.warnings:
            warnings.append(f"一致判定: {w}")

    return RecipeSearchResult(
        outcomes=outcomes,
        ranking=ranking,
        selected_index=selected_index,
        convergence_fallback=fallback,
        order_dependent=order_dependent,
        selection_reason=reason,
        warnings=tuple(warnings),
        config=config,
        agreement=agreement,
    )



# ===========================================================================
# 候補生成 (S2: 固定 + 適応の 2 層)
# ===========================================================================


def _fixed_candidate(
    name: str,
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    background_coeffs: int,
) -> RecipeCandidate:
    hists = tuple(histograms)
    stability: "StabilityOptions | None" = None
    if name == "default":
        stages = build_recipe(hists, phases, background_coeffs=background_coeffs)
        note = "M7 既定レシピ (基準。T1 9.81 / T2 4.33 / T3 6.66 / CaTeO3 12.20)"
    elif name == "sizestrain_last":
        stages = build_recipe(
            hists, phases, background_coeffs=background_coeffs,
            size_strain_placement="last",
        )
        note = (
            "size/歪みを座標・Uiso の後段へ。**T3 で最良かつ収束** (5.98 — 本気フィットの "
            "6.10 より良い)。多相分岐が実測で採っている順序を単相へ適用したもの"
        )
    elif name == "polish":
        stages = build_recipe(hists, phases, background_coeffs=background_coeffs)
        stability = StabilityOptions(
            report_undetermined=True, polish_frozen_undetermined=True
        )
        note = (
            "既定 + 最終研磨 (決まらなかった変数を最後だけ凍結)。**T1 と CaTeO3 で最良** "
            "(T1 9.67)。研磨が効かないデータでは既定とビット同一になる"
        )
    elif name == "serious1":
        stages = build_serious_recipe(
            hists, phases, background_coeffs=background_coeffs, rounds=1
        )
        note = "本気フィット 1 周 (順次解放/凍結)。**T2 で最良** (4.32)。2 周版の約 0.7 倍の時間"
    else:
        stages = build_serious_recipe(hists, phases, background_coeffs=background_coeffs)
        note = "本気フィット 2 周。既定集合からは外れているが名前として選べる (後方互換)"
    return RecipeCandidate(
        name=name, stages=stages, origin="fixed", histograms=hists,
        background_coeffs=background_coeffs, note=note, stability=stability,
    )


def _adaptive_inputs(
    histograms: Sequence[HistogramSpec], background_coeffs: int
) -> "tuple[tuple[HistogramSpec, ...], int, tuple[str, ...]] | None":
    """観測パターンから **レンジ + 背景項数** を自動判定した入力を作る (WS-4 の適用)。

    判定できない (データが読めない/形式未対応) 場合は ``None`` を返し、**適応候補を立てない**。
    固定層が保険として残るので、適応層が使えないことは探索の失敗ではない (S2 の要点)。

    2 つの意図的な制限:

    - **TOF ヒストグラムはレンジ判定の対象外**。`autorange` は 2θ を前提にした低角
      (ビームストップ裾) / 高角 (ノイズ支配域) の判定であり、x が µs の TOF に当てると
      「低角の裾」の意味が変わる。誤ったレンジで自動候補を作るくらいなら作らない。
    - **`two_theta_limits` を明示指定したヒストグラムは上書きしない**。明示指定は人間の
      判断であり (T4 のレンジ制限は非収束の主因を潰した実測値)、自動判定で黙って
      置き換えるのは「提案≠適用」(P-SAR-3) に反する。
    """
    from ..reference.io import load_pattern
    from .autorange import suggest_background_terms, suggest_two_theta_range

    notes: list[str] = []
    out: list[HistogramSpec] = []
    bg = background_coeffs
    bg_decided = False
    for h in histograms:
        try:
            x, y = load_pattern(h.data_path, h.data_format)
        except (OSError, ValueError, KeyError):
            return None
        if x.size < 8:
            return None
        if not h.radiation.is_tof and not bg_decided:
            bg = int(suggest_background_terms(x, y).recommended)
            bg_decided = True
            if bg != background_coeffs:
                notes.append(f"背景 {background_coeffs}→{bg} 項")
        if h.radiation.is_tof or h.two_theta_limits is not None:
            out.append(h)
            continue
        rng = suggest_two_theta_range(x, y)
        limits = rng.as_limits()
        if limits[1] - limits[0] <= 0.0:
            out.append(h)
            continue
        if (
            abs(limits[0] - float(x.min())) > 1e-9
            or abs(limits[1] - float(x.max())) > 1e-9
        ):
            notes.append(f"レンジ {limits[0]:.2f}–{limits[1]:.2f}°")
            out.append(replace(h, two_theta_limits=limits))
        else:
            out.append(h)
    if not notes:
        return None  # 固定候補と同一 — 同じ計算を 2 度回さない
    return tuple(out), bg, tuple(notes)


def build_candidates(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    background_coeffs: int = 6,
    names: "Sequence[str] | None" = None,
) -> tuple[RecipeCandidate, ...]:
    """探索する候補列を**列挙順で**組み立てる (S2)。

    層は 2 つ:

    ===========  =====================================  ==============================
    層           内容                                    根拠
    ===========  =========================================  ==========================
    固定         ``default`` / ``sizestrain_last`` /         データ毎に別々に勝っている
                 ``polish`` / ``serious1`` (+ ``serious``)   (2026-07-30 実測)
    適応         ``adaptive`` (レンジ/背景の自動判定)         手動調整の穴を埋める
    ===========  =========================================  ==========================

    既定 (``names=None``) で回るのは `DEFAULT_CANDIDATES` であり `CANDIDATE_NAMES` 全部では
    ない — 後者は「選べる名前」の集合で、測定で支配された ``serious`` (2 周) も後方互換の
    ために残してある。

    **適応層を固定層と別候補にする**のが要点である。自動判定を既定へ埋め込むと、外したときの
    逃げ道が無い。別候補なら固定層が保険になる。

    :param names: 生成する候補名 (既定 `CANDIDATE_NAMES` 全部)。順序は `CANDIDATE_NAMES` に
        正規化される (呼び出し順で決定論が揺れないため)
    :raises ValueError: 未知の候補名 (綴り間違いを黙って無視すると「探索したつもり」で
        候補が 1 つしか回らない)
    """
    requested = tuple(names) if names is not None else DEFAULT_CANDIDATES
    unknown = [n for n in requested if n not in CANDIDATE_NAMES]
    if unknown:
        raise ValueError(
            f"未知の候補名です: {unknown} (既知: {list(CANDIDATE_NAMES)})"
        )
    wanted = [n for n in CANDIDATE_NAMES if n in set(requested)]
    out: list[RecipeCandidate] = []
    for name in wanted:
        if name != "adaptive":
            out.append(_fixed_candidate(name, histograms, phases, background_coeffs))
            continue
        adapted = _adaptive_inputs(histograms, background_coeffs)
        if adapted is None:
            continue  # 呼び出し側が warnings で「立たなかった」ことを報告する
        hists, bg, notes = adapted
        out.append(
            RecipeCandidate(
                name=name,
                stages=build_recipe(hists, phases, background_coeffs=bg),
                origin="adaptive",
                histograms=hists,
                background_coeffs=bg,
                note="自動判定: " + " / ".join(notes),
            )
        )
    return tuple(out)


# ===========================================================================
# 実行 (S4: 候補の独立実行のみ — ビームサーチはしない)
# ===========================================================================


def _default_candidate_runner(
    phases: Sequence[PhaseSpec], run_kwargs: Mapping[str, object]
) -> CandidateRunner:
    """候補 1 つを `run_auto_rietveld` で実行する既定 runner (GSAS 遅延 import)。

    ``run_auto_rietveld`` は**変更しない** — 探索は候補 1 つの実行にそれを使うだけである。
    """

    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        from .engine import run_auto_rietveld

        kwargs = dict(run_kwargs)
        if candidate.stability is not None:
            # 候補が自分の実行設定を持つときはそれを使う (呼び出し側指定より候補が優先 —
            # 候補の定義そのものだから)。持たない候補は run_kwargs のまま。
            kwargs["stability"] = candidate.stability
        return run_auto_rietveld(
            list(candidate.histograms),
            list(phases),
            recipe=candidate.stages,
            **kwargs,  # type: ignore[arg-type]
        )

    return runner


def run_recipe_search(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    candidates: "Sequence[RecipeCandidate] | None" = None,
    names: "Sequence[str] | None" = None,
    background_coeffs: int = 6,
    config: "SearchConfig | None" = None,
    runner: "CandidateRunner | None" = None,
    ledger: "Ledger | None" = None,
    **run_kwargs: object,
) -> RecipeSearchResult:
    """レシピ候補を独立に実行し、S1 の規則で最良を選ぶ (REQ-SAR-500)。

    :param histograms: 観測ヒストグラム仕様
    :param phases: 相仕様
    :param candidates: 候補を直接与える (None なら `build_candidates` が組む)
    :param names: `build_candidates` に渡す候補名 (``candidates`` 指定時は無視)
    :param background_coeffs: 固定層のレシピ生成に使う背景項数
    :param config: 判定閾値 (None で既定)
    :param runner: 候補 1 つの実行関数 (None なら GSAS 駆動)。**注入はテスト/並列化のシーム**
    :param ledger: 追記台帳 (None なら内部生成)。候補ごと + 選択を追記する
    :param run_kwargs: `run_auto_rietveld` へ透過する追加引数 (``max_cyc``/``stability`` 等)
    :returns: RecipeSearchResult

    候補の実行で例外が出ても**送出しない** — `CandidateOutcome.error` に落として順位表へ残す
    (「バックエンドの失敗は例外でなく結果に縮退させ、ガードレールに処理させる」不変条件)。
    """
    config = config or SearchConfig()
    ledger = ledger if ledger is not None else Ledger()
    requested = tuple(names) if names is not None else DEFAULT_CANDIDATES
    if candidates is None:
        cands = build_candidates(
            histograms, phases, background_coeffs=background_coeffs, names=requested
        )
    else:
        cands = tuple(candidates)
    run = runner or _default_candidate_runner(phases, run_kwargs)

    outcomes: list[CandidateOutcome] = []
    for i, cand in enumerate(cands):
        try:
            result: "AutoRietveldResult | None" = run(cand)
            error = ""
        except Exception as exc:  # noqa: BLE001 — 失敗は結果へ縮退させる (不変条件)
            result, error = None, repr(exc)[:200]
        outcome = CandidateOutcome(index=i, candidate=cand, result=result, error=error)
        outcomes.append(outcome)
        ledger.append(
            "m7_search_candidate",
            outcome.to_dict(require_convergence=config.require_convergence),
        )

    summary = summarize_search(outcomes, config)
    if candidates is None:
        missing = [n for n in requested if n not in {c.name for c in cands}]
        if missing:
            summary = replace(
                summary,
                warnings=summary.warnings
                + tuple(
                    f"候補 {n!r} は立ちませんでした "
                    "(観測パターンを読めない/自動判定が固定候補と同一)"
                    for n in missing
                ),
            )
    ledger.append(
        "m7_search_select",
        {
            "selected": None if summary.selected is None else summary.selected.candidate.name,
            "selection_reason": summary.selection_reason,
            "n_candidates": len(outcomes),
            "rwp": finite_or_none(summary.selected.rwp) if summary.selected else None,
            "convergence_fallback": summary.convergence_fallback,
            "order_dependent": summary.order_dependent,
            "warnings": list(summary.warnings),
        },
    )
    return summary
