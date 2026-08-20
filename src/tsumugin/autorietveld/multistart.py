"""実構造 Rietveld のマルチスタート大域最適確認 (Issue #13)。

`run_auto_rietveld` を複数の初期格子摂動点から実行し、収束先をベイスン分類して大域最適の傍証
(全 valid 開始点が単一ベイスンへ収束) を得る。Rietveld は初期値依存の非線形最小二乗で局所解が
多く、単一開始点の自動解析は大域最適を保証しない。既存 `tsumugin.multistart` の摂動幅
(`PerturbationSpec`) と設定 (`MultistartConfig`) を再利用する。

開始点生成・ベイスン分類・最良選択は純関数 (numpy 非依存の決定論ロジック) でユニットテスト可能。
実行 (`run_multistart_rietveld`) のみ GSAS を遅延経由で使う。

**Phase B でスコープを広げた** (Issue #13 の「並列・原子座標摂動は M-later」を解消):

- **並列実行** — 開始点は互いに独立なので `ProcessPoolExecutor` で 1 開始点 1 プロセス。
  壁時計は N 倍にならず**1 開始点分**になる (実測: T3 で 3.7 分/開始点 → N=5 でも ≈3.7 分)。
  これが「収束確認を規定で回せる」根拠である。
- **座標摂動軸** — Rietveld の局所解は主に**構造**にあり、格子だけ振っても「格子のベイスンが
  1 つ」しか言えない (`engine._apply_coord_jitter`, 対称性が自由な軸のみ)。
- **ベイスン判定を `agreement` へ委譲** — 格子 a,b,c の固定許容・貪欲最初一致 (列挙順依存) を
  やめ、構造クラス全体を esd スケールで見る union-find に差し替えた。
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .._json import finite_or_none
from ..gpxstore import group_context
from ..multistart.perturb import MultistartConfig
from ..store import Ledger
from .agreement import (
    CorroborationReport,
    ProcedureProvenance,
    cluster_agreement_basins,
    effective_trajectory,
)
from .model import AutoRietveldResult, HistogramSpec, PhaseSpec


@dataclass(frozen=True)
class StartPerturbation:
    """1 開始点が適用する初期値摂動 (= `agreement` の ``start_key`` になる)。

    :param cell_scale: 相名→(fa,fb,fc) の格子倍率
    :param coord_jitter_ang: 座標摂動の振幅 (**Å**)。0 で座標軸を使わない
    :param jitter_seed: 座標摂動の乱数種 (開始点ごとに違う値。同じ種ならビット同一)
    """

    cell_scale: Mapping[str, tuple[float, float, float]]
    coord_jitter_ang: float = 0.0
    jitter_seed: int = 0

    @property
    def key(self) -> tuple[object, ...]:
        """独立性判定に使う**開始点キー**。これが違えば別の実験である。"""
        return (
            tuple(sorted((n, tuple(v)) for n, v in self.cell_scale.items())),
            float(self.coord_jitter_ang),
            int(self.jitter_seed),
        )

    @property
    def is_unperturbed(self) -> bool:
        return all(
            v == (1.0, 1.0, 1.0) for v in self.cell_scale.values()
        ) and self.coord_jitter_ang == 0.0


@dataclass(frozen=True)
class MultistartStart:
    """1 開始点: 適用した摂動と、その実行結果 (未実行は None)。

    :param n_axes_jittered: 座標摂動で**実際に動かした軸数**。0 は「その軸では試験していない」
        (高対称構造では全軸が対称固定になり得る) — 傍証を主張してよいかの判断材料
    """

    index: int
    perturbation: StartPerturbation
    result: AutoRietveldResult | None = None
    n_axes_jittered: int = 0
    error: str = ""

    @property
    def cell_scale(self) -> Mapping[str, tuple[float, float, float]]:
        """後方互換のための別名 (旧 `MultistartStart.cell_scale`)。"""
        return self.perturbation.cell_scale


@dataclass(frozen=True)
class RietveldMultistartResult:
    """マルチスタート大域最適確認の結果。

    :param best: 最良 (valid かつ最小 final_rwp) の AutoRietveldResult。valid が無ければ最小 Rwp。
        全開始点が実行失敗 (例外) の場合は None (best_index=-1)。
    :param best_index: best を与えた開始点 index。全滅時は -1。
    :param starts: 全開始点 (摂動と結果)。
    :param n_starts: 実行開始点数。
    :param n_diverged: 発散 (final_rwp 非有限) で除外した開始点数。
    :param n_basins: 収束先ベイスン数 (valid 開始点を格子一致でクラスタ)。
    :param is_global_corroborated: 大域最適の傍証あり = **1 ベイスン かつ valid が 2 点以上
        かつ発散なし**。「1 ベイスン」だけでは開始点 1 つで空虚に成立するため足りない
        (傍証の意味は「複数の独立な出発点が同じ解へ来た」であって「クラスタが 1 つ」ではない)。
    :param warnings: 縮退・全滅などの警告。
    """

    best: AutoRietveldResult | None
    best_index: int
    starts: tuple[MultistartStart, ...]
    n_starts: int
    n_diverged: int
    n_basins: int
    is_global_corroborated: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)
    # 【末尾追加】: 構造クラス全体の一致判定 (`agreement`, basis="start")。
    #   格子 a,b,c だけを見ていた旧実装との違いはモジュール docstring を参照。
    agreement: "CorroborationReport | None" = None
    # 【摂動が実際に効いたか】: 座標軸で動かせた軸の総数。0 は「その軸では試験していない」。
    n_axes_jittered: int = 0
    corroboration_reason: str = ""
    #: valid 開始点の Rwp のばらつき (max-min)。0 に近いほど同じ最小点へ来ている。
    rwp_spread: float = 0.0
    #: **パラメータクラスごとの収束**。単一 bool より遥かに有用である — 実測では T1 が歪で、
    #: T3 が格子で割れており、**処方が違う** (縮退の解消 vs 格子を決める情報の不足)。
    #: 「収束したか」ではなく「**何が**収束したか」が行動を決める。
    class_convergence: Mapping[str, str] = field(default_factory=dict)
    #: **初期値依存と判明したパラメータ** (開始点間で esd を超えて割れたもの)。
    #: 縮退は手順では解消できないが、**影響を受けた値を「決まっている」として出版しない**
    #: ことはできる。`undetermined_parameters` と同じ規律 (所見であって失敗ではない)。
    initial_value_dependent: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "best_index": self.best_index,
            "n_starts": self.n_starts,
            "n_diverged": self.n_diverged,
            "n_basins": self.n_basins,
            "is_global_corroborated": self.is_global_corroborated,
            "corroboration_reason": self.corroboration_reason,
            "n_axes_jittered": self.n_axes_jittered,
            "rwp_spread": finite_or_none(self.rwp_spread),
            "class_convergence": dict(self.class_convergence),
            "initial_value_dependent": list(self.initial_value_dependent),
            "starts": [
                {
                    "index": st.index,
                    "cell_scale": {k: list(v) for k, v in st.perturbation.cell_scale.items()},
                    "coord_jitter_ang": st.perturbation.coord_jitter_ang,
                    "jitter_seed": st.perturbation.jitter_seed,
                    "n_axes_jittered": st.n_axes_jittered,
                    "rwp": finite_or_none(st.result.final_rwp) if st.result else None,
                    "valid": bool(st.result.validity.passed) if st.result else None,
                    "error": st.error,
                }
                for st in self.starts
            ],
            "agreement": None if self.agreement is None else self.agreement.to_dict(),
            "warnings": list(self.warnings),
        }


def _grid_scales(n_starts: int, lattice_frac: float) -> list[float]:
    """1.0 を中心に ±lattice_frac へ対称に配した等方倍率列 (決定論)。

    ``t = -1 + 2i/(n-1)`` を用いるため両側を均等に探索する (M4: 偶数 n でも非対称/重複が出ない)。
    **奇数 n は中心 t=0 を持ち無摂動 1.0 を正確に含む** (整数演算で 1.0 が厳密)。n_starts==1 なら [1.0]。
    """
    if n_starts <= 1:
        return [1.0]
    return [1.0 + lattice_frac * (-1.0 + 2.0 * i / (n_starts - 1)) for i in range(n_starts)]


def generate_cell_scales(
    phase_names: Sequence[str], config: MultistartConfig
) -> tuple[dict[str, tuple[float, float, float]], ...]:
    """決定論的に n_starts 個の初期格子摂動 (相名→等方倍率 (f,f,f)) を生成する。

    全相に同一の等方倍率を与える (格子スケールの局所解確認)。1.0 を中心に ±lattice_frac へ対称配置。
    奇数 n_starts では中心に無摂動 1.0 を含む (偶数は両側対称・中心なし)。
    """
    scales = _grid_scales(config.n_starts, config.spec.lattice_frac)
    starts: list[dict[str, tuple[float, float, float]]] = []
    for f in scales:
        starts.append({name: (f, f, f) for name in phase_names})
    return tuple(starts)


def generate_perturbations(
    phase_names: Sequence[str],
    config: MultistartConfig,
    *,
    coord_jitter_ang: float = 0.0,
    seed: int = 0,
) -> tuple[StartPerturbation, ...]:
    """開始点の摂動列を決定論的に作る (格子 + 座標)。

    格子は現行の対称グリッドを踏襲し、座標は**開始点ごとに違う種**を与える。
    奇数 ``n_starts`` では中央が格子無摂動になるが、そこにも座標種を与える —
    「基準点」は格子だけの意味であり、座標軸を試験しない理由にはならない。
    ただし ``coord_jitter_ang == 0`` なら全開始点で座標は動かない (格子だけの試験)。
    """
    scales = generate_cell_scales(phase_names, config)
    return tuple(
        StartPerturbation(
            cell_scale=scale,
            coord_jitter_ang=float(coord_jitter_ang),
            # 種は開始点 index を混ぜる。同じ config なら何度でも同じ開始点集合になる。
            jitter_seed=int(seed) * 1_000_003 + i,
        )
        for i, scale in enumerate(scales)
    )


#: Rwp のばらつきが**この値を超えたら報告する**閾値 (valid 開始点の max-min, ポイント)。
#:
#: ⚠ **傍証の条件ではない** (一度そうしたが誤りだった)。収束の判定対象は
#: **構造 (格子・座標・占有率) と歪 (サイズ/微小歪み)** であり、Caglioti U/V/W のような
#: 装置側のプロファイルは nuisance である — **構造と歪が収束していれば、プロファイルについては
#: 最良フィットを選ぶだけでよい**。
#:
#: 実測 (T1, ±0.7% 格子, 3 開始点): 構造クラスは全て AGREE のまま ``hist0.U`` だけが z=4634 で
#: 割れ Rwp が 9.81 / 12.54 / 19.59 になった。これは「別の解へ落ちた」のではなく
#: 「**同じ解に対する当てはめの良し悪し**」であり、最良の 9.81 を採ればよい
#: (`select_best` が既にそうしている)。ばらつき自体は所見として報告する — プロファイルが
#: 初期値依存であることは、装置分解能の固定 (`instrument_profile`) を検討する材料になる。
RWP_SPREAD_REPORT_THRESHOLD = 0.5

#: クラス判定の深刻さ (小さいほど深刻)。全対を畳むときに**最悪の対**を採る。
_CLASS_SEVERITY = {
    "DISAGREE": 0, "UNDETERMINED": 1, "INCOMPARABLE": 2, "AGREE": 3,
}


def _is_valid(result: AutoRietveldResult) -> bool:
    return math.isfinite(result.final_rwp) and result.validity.passed


def select_best(
    starts: Sequence[MultistartStart],
) -> tuple[int, AutoRietveldResult | None]:
    """valid かつ最小 final_rwp の (index, result)。valid が無ければ最小 Rwp。

    実行済み開始点が 1 つも無い (全て result=None) 場合は (-1, None) を返す (M5: crash 回避)。
    """
    executed = [s for s in starts if s.result is not None]
    if not executed:
        return -1, None
    valid = [s for s in executed if _is_valid(s.result)]  # type: ignore[arg-type]
    pool = valid if valid else executed
    best = min(pool, key=lambda s: s.result.final_rwp)  # type: ignore[union-attr]
    return best.index, best.result


def summarize_multistart(
    starts: Sequence[MultistartStart],
    config: MultistartConfig,
    *,
    rwp_spread_report_threshold: float = RWP_SPREAD_REPORT_THRESHOLD,
) -> RietveldMultistartResult:
    """実行済み開始点群からベイスン・傍証・最良を集計する (純関数, GSAS 非依存)。

    ベイスン判定は `agreement.cluster_agreement_basins(basis="start")` に委譲する。
    ⚠ ``basis="start"`` が要点 — 全開始点は**同じ手順**を走るので実効軌跡が構造的に同一になり、
    既定の ``"procedure"`` のままだと全対が DUPLICATE になって**傍証が永久に成立しない**。
    """
    executed = [s for s in starts if s.result is not None]
    finite = [s for s in executed if _is_valid_or_finite(s.result)]  # type: ignore[arg-type]
    n_diverged = len(executed) - len(finite)
    valid = [s for s in executed if _is_valid(s.result)]  # type: ignore[arg-type]
    n_axes = sum(s.n_axes_jittered for s in starts)

    report: CorroborationReport | None = None
    n_basins = 0
    if valid:
        report = cluster_agreement_basins(
            [s.result for s in valid],
            [
                ProcedureProvenance(
                    label=f"start{s.index}",
                    trajectory=effective_trajectory(s.result),  # type: ignore[arg-type]
                    stage_metrics=tuple(
                        (st.rwp, st.gof, st.n_params)
                        for st in s.result.stage_results  # type: ignore[union-attr]
                    ),
                    n_obs=s.result.n_obs,  # type: ignore[union-attr]
                    start_key=s.perturbation.key,
                )
                for s in valid
            ],
            basis="start",
        )
        n_basins = len(report.basins)

    warnings: list[str] = []
    if not executed:
        warnings.append("実行された開始点がありません")
    # 【失敗の理由を落とさない】: 開始点は子プロセスで走るので例外は上がらず「結果なし」に
    #   化ける。理由を捨てると「収束確認が空振りした」ことは判っても**なぜか**が判らない
    #   (実測: エンジンが受け取らない引数を渡して全開始点が TypeError で落ちた)。
    failed = [s for s in starts if s.result is None and s.error]
    if failed:
        seen: list[str] = []
        for st in failed:
            if st.error not in seen:
                seen.append(st.error)
        warnings.append(
            f"{len(failed)}/{len(starts)} 開始点が失敗: " + " / ".join(seen[:3])
        )
    if valid and n_basins > 1:
        warnings.append(f"収束先が {n_basins} ベイスンに分岐 (大域最適は未確定)")
    if executed and not valid:
        warnings.append("valid な収束が得られませんでした (全開始点が発散/非物理)")
    if report is not None:
        warnings.extend(f"一致判定: {w}" for w in report.warnings)

    # 【傍証の条件】: 単一ベイスン ∧ valid ≥2 ∧ 発散なし ∧ **摂動が実際に効いた**。
    #   最後の条件が要点 — 座標摂動を要求したのに全軸が対称固定で 1 つも動かなかった場合、
    #   開始点は実質同じものになる。それを傍証と呼ぶのは `n_basins == 1` の空虚な True と同型。
    jitter_requested = any(s.perturbation.coord_jitter_ang > 0.0 for s in starts)
    rwps = [s.result.final_rwp for s in valid]  # type: ignore[union-attr]
    rwp_spread = (max(rwps) - min(rwps)) if len(rwps) >= 2 else 0.0
    conditions = (
        ("no_valid_start", bool(valid)),
        ("insufficient_valid_starts", len(valid) >= 2),
        ("diverged_starts", n_diverged == 0),
        ("multiple_basins", n_basins == 1),
        ("perturbation_had_no_effect", (not jitter_requested) or n_axes > 0),
    )
    reason = next((name for name, ok in conditions if not ok), "corroborated")
    corroborated = all(ok for _, ok in conditions)
    if reason == "insufficient_valid_starts" and valid:
        warnings.append(
            f"valid な開始点が {len(valid)} 点しかないため傍証にならない "
            "(1 点は必ず 1 ベイスンになる)"
        )
    if reason == "diverged_starts":
        warnings.append(f"{n_diverged} 点が発散したため傍証を主張しない")
    # 【報告するが傍証は妨げない】: 構造と歪が一致していればプロファイルは最良を選べばよい。
    if rwp_spread > rwp_spread_report_threshold and n_basins == 1:
        best_rwp = min(rwps) if rwps else float("nan")
        warnings.append(
            f"構造と歪は一致しているが Rwp が {rwp_spread:.3f} ポイントばらついている "
            f"(装置プロファイルの初期値依存)。**最良フィット {best_rwp:.4f} を採用**した — "
            "解が割れているのではなく当てはめの良し悪しである。恒常的なら装置分解能の固定 "
            "(instrument_profile) を検討する材料になる"
        )
    if reason == "perturbation_had_no_effect":
        warnings.append(
            "座標摂動を要求したが動かせた軸が 0 (全軸が対称拘束で固定) — "
            "**この軸では試験していない**ので傍証にはならない"
        )

    # 【クラス別の収束 + 初期値依存パラメータ】: 全対の判定を畳む。あるクラスがどこか 1 対でも
    #   割れていれば、そのクラスは「収束していない」— 開始点は同格なので最悪の対が結論になる。
    class_conv: dict[str, str] = {}
    dependent: dict[str, float] = {}
    if report is not None:
        for pair in report.pairs:
            for cls in pair.classes:
                if not cls.n_compared:
                    continue
                prev = class_conv.get(cls.param_class)
                if prev is None or _CLASS_SEVERITY.get(cls.verdict, 9) < _CLASS_SEVERITY.get(
                    prev, 9
                ):
                    class_conv[cls.param_class] = cls.verdict
                worst = cls.worst
                if worst is not None and worst.verdict == "DISAGREE":
                    z = worst.z if worst.z is not None else float("inf")
                    dependent[worst.key] = max(dependent.get(worst.key, 0.0), z)

    best_index, best = select_best(starts)
    return RietveldMultistartResult(
        best=best,
        best_index=best_index,
        starts=tuple(starts),
        n_starts=len(executed),
        n_diverged=n_diverged,
        n_basins=n_basins,
        is_global_corroborated=corroborated,
        warnings=tuple(warnings),
        agreement=report,
        n_axes_jittered=n_axes,
        corroboration_reason=reason,
        rwp_spread=float(rwp_spread),
        class_convergence=class_conv,
        initial_value_dependent=tuple(
            k for k, _ in sorted(dependent.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
    )


def _is_valid_or_finite(result: AutoRietveldResult) -> bool:
    return math.isfinite(result.final_rwp)


#: BLAS/OpenMP のスレッド数を縛る環境変数 (実装により名前が違うので全部立てる)。
_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


@contextmanager
def _pinned_blas_threads():
    """子プロセスが**継承する**環境で BLAS スレッド数を 1 に固定する。

    ⚠ **親側で pool 生成前に立てる必要がある**。ワーカー関数の中で設定しても遅い —
    子は起動直後にタスク関数のモジュールを import し、その時点で numpy/BLAS のスレッド
    プールが作られてしまうため、関数本体が走る頃には手遅れである (実測: 3 ワーカーで
    CPU 時間が 206s/58s/28s と偏り、壁時計が想定 40 秒に対して 6 分超になった = 過剰購読)。

    固定する理由は 2 つあり、**後者が本質**:

    1. N プロセス × M スレッドの過剰購読を避ける (上記の実測)。
    2. **BLAS の縮約順序はスレッド数で変わり得る**ので、スレッド数が実行時の負荷で揺れると
       浮動小数がビット同一にならない。マルチスタートは**ビット同一性そのものを証拠として
       読む**ため、ここが揺れると判定の土台が崩れる (NFR-102)。

    親の環境は文脈を抜けるとき元へ戻す (呼び出し側の設定を奪わない)。
    """
    import os

    saved = {k: os.environ.get(k) for k in _THREAD_ENV_VARS}
    try:
        for k in _THREAD_ENV_VARS:
            os.environ[k] = "1"
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _run_one_start(payload: tuple) -> tuple:
    """1 開始点を実行する (**別プロセスで走る**ので引数/戻り値は pickle 可能な形のみ)。

    スレッド固定は親が環境で行う (`_pinned_blas_threads`) — ここで設定しても遅い。
    """
    index, histograms, phases, perturbation, run_kwargs = payload
    from .engine import run_auto_rietveld

    jitter = (
        {p.phase_name: perturbation.coord_jitter_ang for p in phases}
        if perturbation.coord_jitter_ang > 0.0
        else None
    )
    try:
        result = run_auto_rietveld(
            list(histograms), list(phases),
            initial_cell_scale=dict(perturbation.cell_scale),
            initial_coord_jitter=jitter,
            jitter_seed=perturbation.jitter_seed,
            **run_kwargs,
        )
    except Exception as exc:  # noqa: BLE001 — 実行失敗は発散扱いで継続 (pickle 可能な文字列へ)
        return (index, None, 0, repr(exc)[:200])
    # 摂動を要求していないときは 0 (自由軸の本数ではなく**動かした軸数**である)。
    n_axes = _count_jittered_axes(result) if jitter is not None else 0
    return (index, result, n_axes, "")


def _count_jittered_axes(result: AutoRietveldResult) -> int:
    """結果から「座標摂動で**動かせた**軸数」を数える (engine が ledger に残した値の代替)。

    ⚠ 呼び出し側は**摂動を要求したときだけ**呼ぶこと — 本関数が数えるのは「自由軸の本数」で
    あり、摂動していなければそれは動いた軸ではない。

    ledger はワーカー内に閉じており親へ返さないので、**自由度指標から数え直す** —
    ``atom_coord_free_index`` の各原子について、``0`` でなく三つ組内で最初に現れる正値の
    軸数が「動かせた軸」である (`engine._apply_coord_jitter` と同じ規則)。
    """
    total = 0
    for atoms in result.atom_coord_free_index.values():
        for free in atoms.values():
            seen: set[int] = set()
            for fid in free:
                if fid == 0 or fid in seen:
                    continue
                seen.add(fid)
                total += 1
    return total


def run_multistart_rietveld(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    config: MultistartConfig | None = None,
    ledger: Ledger | None = None,
    coord_jitter_ang: float = 0.0,
    seed: int = 0,
    jobs: "int | None" = None,
    **run_kwargs: object,
) -> RietveldMultistartResult:
    """初期値を振った複数の開始点から `run_auto_rietveld` を**並列実行**し収束を確認する。

    開始点は互いに独立なので、``jobs = n_starts`` にすれば**壁時計は 1 開始点分**になる
    (N 倍にならない)。これが収束確認を規定で回せる根拠である。

    :param coord_jitter_ang: 座標摂動の振幅 (Å)。0 で格子軸のみ
    :param seed: 座標摂動の種 (開始点 index を混ぜる)
    :param jobs: 並列度 (None で ``min(n_starts, cpu_count)``)。**1 で直列** (デバッグ用)
    :param run_kwargs: `run_auto_rietveld` へ透過 (recipe / stability / max_cyc 等)

    ⚠ 決定論のため、結果は**完了順ではなく開始点 index 順**に並べ、**ledger も join 後に
    列挙順で再発行**する (`Ledger` はハッシュ鎖 / NFR-102。完了順の追記はビット同一性を壊す)。
    """
    import os
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    config = config if config is not None else MultistartConfig()
    ledger = ledger if ledger is not None else Ledger()
    phase_names = [p.phase_name for p in phases]
    perturbations = generate_perturbations(
        phase_names, config, coord_jitter_ang=coord_jitter_ang, seed=seed
    )
    n_jobs = jobs if jobs is not None else min(len(perturbations), os.cpu_count() or 1)
    n_jobs = max(1, int(n_jobs))

    # 【別ベイスンへ落ちた開始点の fit も残す (規定 2026-08-20)】: 収束確認の結論
    #   (単一ベイスン=大域最適の傍証) は「落ちなかった解がどんな構造だったか」を見て初めて
    #   意味を持つ。**並列実行は別プロセス**なので ambient 文脈は届かない — 明示文脈
    #   (frozen dataclass = pickle 可) を payload に載せて運ぶ。
    group, _reason = group_context(
        histograms[0].data_path if histograms else "",
        gpx_dir=run_kwargs.get("gpx_dir"),  # type: ignore[arg-type]
        save=bool(run_kwargs.get("save_gpx", True)),
    )
    payloads = [
        (
            i,
            tuple(histograms),
            tuple(phases),
            pert,
            {**run_kwargs, "gpx_context": group.child(role="multistart", index=i)},
        )
        for i, pert in enumerate(perturbations)
    ]
    raw: dict[int, tuple] = {}
    pool_error = ""
    # ⚠ 環境の固定は **pool 生成の外側**で行う (子は spawn 時に環境を継承する)。
    #   直列分岐も**中に入れる** — 固定の目的の半分は過剰購読の回避だが、本質は
    #   「縮約順序がスレッド数で変われば同じ入力でもビットが変わる」(NFR-102) であり、
    #   それは jobs=1 でも同じだからである (直列は再現の基準として使われる)。
    with _pinned_blas_threads():
        if n_jobs == 1:
            for payload in payloads:
                got = _run_one_start(payload)
                raw[got[0]] = got
        else:
            try:
                with ProcessPoolExecutor(max_workers=n_jobs) as pool:
                    for got in pool.map(_run_one_start, payloads):
                        raw[got[0]] = got
            except BrokenProcessPool as exc:
                # 【子の即死は例外にしない】: `_run_one_start` は自分の中の例外を捕まえるが、
                #   worker が OOM/segfault で落ちると `pool.map` 自身が投げる。これを通すと
                #   ② の境界を例外が越える (③ は LLM なので回復不能)。「全開始点が失敗」に
                #   畳んで既存の warnings/`no_valid_start` 経路へ載せる — バックエンドの失敗を
                #   結果に変換するという不変条件は、プロセスが死ぬ場合も同じである。
                pool_error = f"{type(exc).__name__}: {exc}"

    starts: list[MultistartStart] = []
    for i, pert in enumerate(perturbations):
        _idx, result, n_axes, error = raw.get(
            i, (i, None, 0, pool_error or "開始点の結果が返らなかった")
        )
        starts.append(
            MultistartStart(
                index=i, perturbation=pert, result=result,
                n_axes_jittered=int(n_axes), error=str(error),
            )
        )
    # 【ledger は列挙順で再発行】: 完了順に書くとハッシュ鎖が実行ごとに変わる (NFR-102)。
    for st in starts:
        if st.result is None:
            ledger.append("multistart_error", {"start": st.index, "error": st.error})
            continue
        ledger.append(
            "multistart_start",
            {
                "start": st.index,
                "scale": {k: list(v) for k, v in st.perturbation.cell_scale.items()},
                "coord_jitter_ang": st.perturbation.coord_jitter_ang,
                "jitter_seed": st.perturbation.jitter_seed,
                "n_axes_jittered": st.n_axes_jittered,
                "rwp": finite_or_none(st.result.final_rwp),
                "valid": bool(st.result.validity.passed),
            },
        )
    summary = summarize_multistart(starts, config)
    ledger.append(
        "multistart_summary",
        {
            "n_starts": summary.n_starts,
            "n_basins": summary.n_basins,
            "n_diverged": summary.n_diverged,
            "is_global_corroborated": summary.is_global_corroborated,
            "corroboration_reason": summary.corroboration_reason,
            "n_axes_jittered": summary.n_axes_jittered,
        },
    )
    return summary
