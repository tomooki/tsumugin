"""ベンチマークの**唯一の定義** — データセット spec と候補レシピのレジストリ。

親 (`bench_recipes.py`) と子 (`_bench_one.py`) の双方がここを import する。以前は spec が
子スクリプトの中にあり「gated テストと 1 対 1 で一致させること」という**コメントだけ**で
担保されていた。実測事故: T3 の ``temperature=295/10`` を落としたら `temp_diff` が立たず
`hydrostatic_strain` (Dij) 段が消えて Rwp 6.66% → **12.56%** になり、「回帰した」と誤読しかけた。
**ハーネスがテストと違う条件を測っていると、以降の全判断が狂う。**

レシピも同様に 1 箇所へ集約する。以前は子スクリプトの ``if/elif`` 連鎖で、親の ``RECIPES``
タプルと二重管理だった (11 案には耐えない)。``RECIPES = tuple(RECIPE_REGISTRY)`` にすることで
CLI の choices・表の列順・子の dispatch が構造的にずれなくなる。

**GSAS も tsumugin も import しない** (パス文字列と builder 名だけを持つ) ので、素の
`python -c "import tools.bench_specs"` で読める = レジストリ自体をテストできる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = _REPO / "docs" / "benchmark" / "testdata"


# ---------------------------------------------------------------------------
# データセット
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetSpec:
    """1 データセットの入力条件。**gated テストと 1 対 1** で一致させること。

    :param background_coeffs: 初期背景項数。CaTeO3 の 24 は**手で与えている値**であり、
        自動ルートは手で与えられない — これが背景エスカレーション候補 (A3) の動機である
    :param note: なぜこのデータを持つか (カバレッジの説明)
    """

    key: str
    files: tuple[str, ...]
    background_coeffs: int
    max_cyc: int
    note: str
    baseline_rwp: "float | None" = None
    tutorial_rwp: "float | None" = None
    slow: bool = False
    excluded_reason: str = ""

    @property
    def available(self) -> bool:
        return all((DATA_ROOT / f).exists() for f in self.files)


#: ⚠ **T4 は本キャンペーンから除外**している (1 本 ~3 時間 = 残り全部より長く、非収束の原因も
#: 未解明 = Issue #163)。除外の代償として**多相と TOF が検証範囲から丸ごと落ちる** —
#: `build_recipe` の多相分岐・`phase_fraction_sum`・全 TOF 経路は本キャンペーンで一度も走らない。
#: 代替として調べた Jana CandAt は同梱 aragonite CIF が `P 1` (60 座標が無拘束) のため
#: **一致判定を壊して見せる**ので採用しない (docs/benchmark/README.md 参照)。
DATASETS: dict[str, DatasetSpec] = {
    "T1": DatasetSpec(
        key="T1",
        files=("m7/labdata/FAP.XRA", "m7/labdata/INST_XRY.PRM", "m7/labdata/FAP.EXP"),
        background_coeffs=6,
        max_cyc=12,
        note="単相ラボ X 線 (fluoroapatite)。既定が最良のデータ",
        baseline_rwp=9.81,
        tutorial_rwp=10.38,
    ),
    "T2": DatasetSpec(
        key="T2",
        files=(
            "m7/cwneutron/garnet.raw",
            "m7/cwneutron/inst_d1a.prm",
            "m7/cwneutron/garnet_YFeAlO.cif",
        ),
        background_coeffs=6,
        max_cyc=12,
        note="CW 中性子 + 混合占有 (Fe/Al)。占有率→Uiso の順序分岐を踏む唯一のデータ",
        baseline_rwp=4.33,
        tutorial_rwp=5.18,
    ),
    "T3": DatasetSpec(
        key="T3",
        files=(
            "m7/cwcombined/PBSO4.XRA",
            "m7/cwcombined/INST_XRY.PRM",
            "m7/cwcombined/PBSO4.CWN",
            "m7/cwcombined/inst_d1a.prm",
            "PbSO4-Wyckoff.cif",
        ),
        background_coeffs=6,
        max_cyc=12,
        note=(
            "X 線 + CW 中性子 joint (PbSO4, 295K/10K)。温度差 Dij を踏む唯一のデータで、"
            "**既定が未収束 (GSAS converged=False @S4 uiso)** の唯一のデータでもある"
        ),
        baseline_rwp=6.66,
        tutorial_rwp=6.71,
    ),
    "T4": DatasetSpec(
        key="T4",
        files=(
            "m7/tofcw/11BM_NAC.fxye",
            "m7/tofcw/11bm_gsas.prm",
            "m7/tofcw/PG3_22048.gsa",
            "m7/tofcw/POWGEN_1066.instprm",
            "m7/tofcw/PG3_22049.gsa",
            "m7/tofcw/POWGEN_2665.instprm",
            "m7/tofcw/NAC.cif",
            "m7/tofcw/CaF2.cif",
        ),
        background_coeffs=6,
        max_cyc=12,
        note="多相 + TOF + 放射光 (NAC+CaF2)",
        baseline_rwp=12.8,
        tutorial_rwp=6.83,
        slow=True,
        excluded_reason=(
            "1 本 ~3 時間 (serious) でキャンペーン全体より長く、非収束の原因も未解明 "
            "(Issue #163)。除外により多相と TOF が検証範囲外になる"
        ),
    ),
    "CaTeO3": DatasetSpec(
        key="CaTeO3",
        files=(
            "m9/cateo3/NB-LM01MO_030.XRDML",
            "m9/cateo3/cateo3_CuKa.instprm",
            "m9/cateo3/alpha_CaTeO3_H2O.cif",
        ),
        background_coeffs=24,
        max_cyc=20,
        note=(
            "Jana2020 実験室 X 線 (Kα1 単色)。**背景 24 項を手で与えている**唯一のデータで、"
            "既定でも validity FAIL する唯一のデータでもある"
        ),
        baseline_rwp=12.20,
        tutorial_rwp=9.4,
    ),
}

#: 本キャンペーンで測るデータセット (列挙順が表の列順)。T4 は上記の理由で入れない。
CAMPAIGN_DATASETS: tuple[str, ...] = ("T1", "T2", "T3", "CaTeO3")


# ---------------------------------------------------------------------------
# 候補レシピ
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecipeBuild:
    """1 候補の作り方。

    :param builder: ``"default"`` (`build_recipe`) か ``"serious"`` (`build_serious_recipe`)
    :param recipe_kwargs: builder へ渡す追加引数 (軸を 1 つだけ動かす)
    :param stability: `StabilityOptions` へ渡す辞書。**観測列は全候補共通**で、
        ここに書くのは**ゲート列** (フィットを変える設定) だけ
    :param axis: この候補が動かしている軸 (経路多様性の判定に使う)
    :param reference: 比較の基準になる候補名 ("改善は単独で測る")
    :param eligible: 5 案の選定対象か。負の対照は False
    """

    name: str
    builder: str
    axis: str
    reference: str
    motivation: str
    recipe_kwargs: dict[str, object] = field(default_factory=dict)
    stability: dict[str, object] = field(default_factory=dict)
    max_cyc_scale: float = 1.0
    eligible: bool = True

    @property
    def is_gated(self) -> bool:
        """ゲート列 (フィットを変える設定) を持つか。観測列だけの候補は False。"""
        return bool(self.stability)


#: **全候補共通の観測列**。フィットを変えてはならない — 段ごとの収束状態を「精密化を変えずに」
#: 記録するためのもの (WS-0 0-3 でこれが可能になった)。`prune_weak_vars_each_stage` と箱拘束は
#: **絶対に入れない**: 前者は実測で S1 末に背景 6 項を全凍結して以降を痩せた母数で走らせ、
#: 後者は値を境界へ丸めて凍結する**判断**であって観測ではなく、N0 の格子発散を鈍らせて
#: 負の対照そのものを壊す。
OBSERVE_ONLY_STABILITY: dict[str, object] = {
    "detect_noop_stages": True,
    "record_weak_vars": True,
    "record_correlations": True,
    "report_undetermined": True,
}

#: 10 案 + 負の対照。**列挙順が固定** — `search.observation_groups` は「最初に結果を返した候補」を
#: 観測集合の基準にするので、A0 (既定) が index 0 でなければ基準が別物になる。
RECIPE_REGISTRY: dict[str, RecipeBuild] = {
    "A0-default": RecipeBuild(
        name="A0-default", builder="default", axis="(reference)", reference="A0-default",
        motivation="実測ベースライン: T1 9.80617 / T2 4.3331 / T3 6.6602 / CaTeO3 12.1975",
    ),
    "A1-profile-accum": RecipeBuild(
        name="A1-profile-accum", builder="default", axis="profile_granularity",
        reference="A0-default",
        motivation=(
            "F2 は交絡している — serious は freeze 意味論/granularity/rounds/段数が同時に違う。"
            "累積を凍結なしで単離する唯一の案 (終状態は A0 の S2 と同一)"
        ),
        recipe_kwargs={"profile_granularity": "accumulate"},
    ),
    "A2-sizestrain-last": RecipeBuild(
        name="A2-sizestrain-last", builder="default", axis="size_strain_placement",
        reference="A0-default",
        motivation=(
            "多相分岐が実測で採っている順序 (size/歪みを座標より先に出すと座標段が悪化して "
            "revert) は**単相で一度も測られていない**"
        ),
        recipe_kwargs={"size_strain_placement": "last"},
    ),
    "A3-bg-escalate": RecipeBuild(
        name="A3-bg-escalate", builder="default", axis="background",
        reference="A0-default",
        motivation=(
            "今 CaTeO3 が 12.2% に届くのは spec が 24 項を**手で与えている**から。自動ルートは"
            "手で与えられない (実測: 3 項 19% 頭打ち / 6 項 13.7% / 必要 24)"
        ),
        recipe_kwargs={"background_escalation": (12, 24, 36)},
    ),
    "A4-autorange": RecipeBuild(
        name="A4-autorange", builder="default_autorange", axis="observation_set",
        reference="A0-default",
        motivation=(
            "**観測集合が違う唯一の案** → 規則により tier でしか勝てない。本タスクでの真価は"
            "別のところにある: Rwp/BIC は比較不能でも**パラメータ一致は比較可能**なので、"
            "「答えはパターンをどこで切るかに依存しない」という最強の傍証になる"
        ),
    ),
    "A5-gated": RecipeBuild(
        name="A5-gated", builder="default", axis="convergence_policy",
        reference="A0-default",
        motivation=(
            "T1 の「成功」段は shift/esd 86/116/47 で未収束。ゲート単独では全段 revert するので"
            "収束予算とセットでしか使えない。**T3 で累積経路を tier 0 に入れ得る唯一の案**"
        ),
        stability={
            "require_convergence": True,
            "max_shift_esd": 1.0,
            "extra_cycles": 3,
            "rescue_freeze_on_failure": True,
            "rescue_max_freeze": 1,
            "rescue_max_rounds": 2,
        },
        max_cyc_scale=2.0,
    ),
    "A6-polish": RecipeBuild(
        name="A6-polish", builder="default", axis="final_polish", reference="A0-default",
        motivation=(
            "実測 T1 9.80617 → 9.67230 (:0:U を凍結)。**REQ-SAR-301 を破らずに T1 の最良値を"
            "超える唯一の実測レバー**"
        ),
        stability={"report_undetermined": True, "polish_frozen_undetermined": True},
    ),
    "B0-serious2": RecipeBuild(
        name="B0-serious2", builder="serious", axis="freeze_semantics",
        reference="A0-default",
        motivation="T3 6.0998 収束∧妥当 (既定は未収束 6.6602) / CaTeO3 12.1917 / T1 10.4524",
    ),
    "B1-serious1": RecipeBuild(
        name="B1-serious1", builder="serious", axis="rounds", reference="B0-serious2",
        motivation=(
            "実測 n_reverted = 53-59 段中 28-35。REQ-SAR-304 (周回入口の最良復元) が未実装なので"
            "round 2 は revert 連続の末尾から出発する — T1 の serious 劣化の第一容疑者。"
            "⚠ 「1 周少ない」と「最良復元が無い」を**交絡して**測っている (3-4 が入るまで解けない)"
        ),
        recipe_kwargs={"rounds": 1},
    ),
    "N0-NEGATIVE": RecipeBuild(
        name="N0-NEGATIVE", builder="negative_cell_alone", axis="(negative control)",
        reference="A0-default",
        motivation=(
            "F1 実測: T3 6.66 → **14.38% + 格子発散**。**判定機構の校正器** — tier で降格されず "
            "T3 で不一致にもならなければ、機構が差を見ていない"
        ),
        eligible=False,
    ),
}

#: `--recipes` の choices・表の列順・子の dispatch を**同一の列挙順**に縛る。
RECIPES: tuple[str, ...] = tuple(RECIPE_REGISTRY)

#: 5 案の選定対象 (負の対照を除く)。
ELIGIBLE_RECIPES: tuple[str, ...] = tuple(
    name for name, b in RECIPE_REGISTRY.items() if b.eligible
)
