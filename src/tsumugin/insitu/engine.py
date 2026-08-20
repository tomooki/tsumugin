"""M9 逐次実構造 Rietveld エンジン — run_sequential_rietveld (時間/温度系列)。

M7 `autorietveld.run_auto_rietveld` の**時間系列アナロジー**。温度/時間フレーム列を先頭から
逐次に実構造 Rietveld 精密化し、直前フレームの精密化格子を次フレームの初期値に引き継ぐ
(ウォームスタート)。Rwp/格子のジャンプ (変化点) で新相出現を疑い、`insitu.phaseid` で
Materials Project から新相を自動同定・物質化して相集合に追加、**受理基準 (相分率有意 ∧ Rwp 改善
∧ 妥当性維持)** を満たせば採用する。CaTeO3 の alpha→delta 転移で delta を自動発見する中核。

GSAS 駆動は既定 runner (`_default_gsas_runner`) 内の `run_auto_rietveld` に隔離し、コアの制御
ロジック (ウォームスタート・変化点・相追加・受理) は runner 注入で GSAS 非依存にテストできる
(M8 refine_loop と同じ設計)。全フレーム遷移を ledger に追記する。

信頼性: 🔵 architecture.md §3。M7 単一フレーム + M8 閉ループ + M6 相同定の統合。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable, Sequence

from .._json import finite_or_none
from ..autorietveld.model import AutoRietveldResult, PhaseSpec
from ..gpxstore import GpxContext, gpx_context, series_context

if TYPE_CHECKING:
    from ..autorietveld.model import RefinementStage
    from ..autorietveld.residual_report import ResidualReport
from ..reference.model import ReferencePhase
from ..sequential.changepoint import ChangepointConfig, detect_changepoint
from ..store.ledger import Ledger
from ._warmstart import call_runner, runner_accepts_initial_fractions
from .charge import alkali_fields, plan_frame_constraint
from .model import (
    Cell,
    ChargeConstraintConfig,
    FrameRietveldResult,
    FrameSpec,
    PhaseAppearance,
    PhaseIdConfig,
    SequentialConfig,
    SequentialRietveldResult,
)
from .phaseid import phasespec_to_reference
from .residual import residual_significance

# runner: (frame, phases, initial_cells) -> AutoRietveldResult
Runner = Callable[
    [FrameSpec, Sequence[PhaseSpec], "dict[str, Cell] | None"], AutoRietveldResult
]
# phase_finder: (frame, elements, exclude_formulas, workdir, known_phases) -> tuple[PhaseSpec, meta] 列
# known_phases: 現行相集合の ReferencePhase 列 (operando warm-start; identify_pattern の残差先減算用)。
PhaseFinder = Callable[
    [FrameSpec, Sequence[str], Sequence[str], str, Sequence[ReferencePhase]],
    "Sequence[tuple[PhaseSpec, dict]]",
]


def _child(
    ctx: "GpxContext | None", role: str, index: int | None, label: str = ""
) -> "GpxContext | None":
    """成果物文脈の子を作る (文脈が無ければ None = 命名しないだけで保存は既定どおり)。"""
    return None if ctx is None else ctx.child(role=role, index=index, label=label)


def _cell6(cell: Sequence[float]) -> Cell:
    """任意長の格子タプルを長さ 6 の (a,b,c,α,β,γ) へ整える (角度欠落は 90°)。"""
    vals = list(cell) + [90.0, 90.0, 90.0]
    return (
        float(vals[0]), float(vals[1]), float(vals[2]),
        float(vals[3]), float(vals[4]), float(vals[5]),
    )


def _residual_report_of(result: AutoRietveldResult) -> "ResidualReport | None":
    """AutoRietveldResult の残差配列をフレーム毎の `ResidualReport` に畳む (None = 復元不能)。

    【配列でなく報告を持つ】: 残差配列は 2392 点 × 3 本 ≈ 150KB/フレームで、247 フレーム系列では
      ~37MB になる。報告は数個の float + ~6 特徴と小さい。ここで畳んでおくことで、系列結果の
      消費側 (MCP `seq_result_to_dict` → ③) が**再精密化なしに** J2/J3 (未説明ピーク → 欠落相 /
      強度比異常 → 対称性低下) を判断できる (architecture.md §4.5 到達可能性 #3)。
    【縮退】: `residual_report_from_result` は残差フィールドが空/長さ不一致/全点非有限のとき
      None を返す (後方互換の既定は空タプル = スタブ runner や旧構築)。
    """
    from ..autorietveld.residual_report import residual_report_from_result

    return residual_report_from_result(result)


def _fractions_of(result: AutoRietveldResult, phase_names: Sequence[str]) -> dict[str, float]:
    """AutoRietveldResult から相名→相分率を取り出す (欠測は 0.0)。単相は {name:1.0} を補う。"""
    fr = dict(result.phase_fractions)
    if not fr and len(phase_names) == 1:
        return {phase_names[0]: 1.0}
    return {name: float(fr.get(name, 0.0)) for name in phase_names}


def _publication_of(result: AutoRietveldResult) -> dict[str, object]:
    """精密化結果の**出版値** (重量分率 ± esd・格子 esd) をフレーム構築 kwargs へ写す。

    **`phase_fractions` (Scale) では出版できない** (Issue #96 レビュー): Scale は単位胞の散乱能に
    対する比例係数で、単位胞質量が相間で異なると重量分率と大きく乖離する (実測 K₂Mn[Fe(CN)₆]
    tetra: **65.6 Scale% は同じ fit で 47.2 wt%** = この点で 1.39 倍の誤り)。**乖離はフレーム毎に
    違い** (実測 fr112 1.62 / fr120 1.48 / fr124 1.41 / fr126 1.39 倍)、その大きさは相の単位胞質量比
    (cubic 1103.4 / tetra 517.8 amu = 2.13 倍) と各フレームの分率で決まる — **単一の換算係数は
    存在しない**ので Scale に係数を掛けて wt% にはできない。operando の
    主要な報告値 (相分率 vs 時間) はここを通るため、**フレームに引き継がないと**
    `seq_result_to_dict` が幾ら serialize しても ③ には空 dict しか届かない
    (= ② に配線があっても ③ にとっては「無い」のと同じ)。esd も同様で、esd を伴わない精密化値は
    出版できない。

    `_fractions_of` と違い**相名でのフィルタ/0.0 埋めをしない**: 重量分率は GSAS 自身が
    `calcMassFracs` で全相まとめて算出した比であり、部分集合を取り出しても和=1 が保たれず、
    欠測を 0.0 で埋めると「その相は 0 wt%」という**測定していない主張**になる。持ち帰った値を
    そのまま渡し、無ければ空 dict へ縮退させる (後方互換: 3 引数スタブ runner/旧構築は空)。
    """
    return {
        "phase_weight_fractions": dict(result.phase_weight_fractions),
        "phase_weight_fraction_esd": dict(result.phase_weight_fraction_esd),
        "cell_esd": {name: tuple(esd) for name, esd in result.cell_esd.items()},
    }


#: 相分率ウォームスタートの受け渡しは `_warmstart` に一元化する (Issue #96)。M9 逐次 (本モジュール) /
#: M10 双方向区間 (`anchor.segment`) / 修復 (`repair`) の 3 経路が**同じ**機構を使う — Issue #82 が
#: ここにしか配線されず他 2 経路が seed に張り付いた実害の再発防止 (経路ごとの実装は取り残される)。
#: 旧 private 名は既存の呼び出し元/テスト互換のため別名として残す。
_runner_accepts_initial_fractions = runner_accepts_initial_fractions
_call_runner = call_runner


def _warn_runner_constraint_mismatch(
    runner: object,
    charge_constraint: "ChargeConstraintConfig | None",
    warnings: "list[str]",
) -> None:
    """runner が消費する charge_constraint とエンジン設定の不一致を 1 回警告する (レビュー H1)。

    エンジンの alkali 報告 (`_alkali_of`) は plan を**独立に再計算**するため、runner が拘束を
    消費していなくても `alkali_constraint_applied` が立つ。`make_gsas_runner` は消費する設定を
    ``_fr318_charge_constraint`` 属性で自己申告する — 属性が無い (カスタム/テスト runner) か
    設定が異なる場合、報告は「計画」であって「適用の証明」ではない旨を警告する。
    """
    consumed = getattr(runner, "_fr318_charge_constraint", None)
    engine_on = charge_constraint is not None and charge_constraint.enabled
    runner_on = consumed is not None and bool(getattr(consumed, "enabled", False))
    if not engine_on and not runner_on:
        return
    if engine_on and runner_on and consumed == charge_constraint:
        return
    if engine_on and not runner_on:
        msg = (
            "charge_constraint が有効ですが、runner がそれを消費する保証がありません "
            "(make_gsas_runner(charge_constraint=) 由来でない/設定が異なる)。"
            "alkali_constraint_applied は**計画**の報告であり、この runner での適用は未確認です"
        )
    elif runner_on and not engine_on:
        # 逆方向 (レビュー第2巡 F1): runner は拘束を適用するのにエンジン設定が無効 —
        # alkali 報告が一切出ないまま拘束だけが効く。アンカー A/B の「制約なし A」も
        # use_charge=False で目標を剥がさないため静かに汚染される。
        msg = (
            "runner は charge_constraint を消費しますが、エンジン側の設定が無効です — "
            "拘束が適用される一方で alkali_* 報告は出ず、アンカー A/B の『制約なし』も"
            "成立しません。run_sequential_rietveld/run_anchored_sequential にも同じ"
            " charge_constraint を渡してください"
        )
    else:
        msg = (
            "runner が消費する charge_constraint とエンジン設定が**異なります** — "
            "適用される拘束と報告される計画が食い違います。同一の設定を両方へ渡してください"
        )
    if msg not in warnings:
        warnings.append(msg)


def _alkali_of(
    frame: FrameSpec,
    charge_constraint: "ChargeConstraintConfig | None",
    phase_names: Sequence[str],
    result: AutoRietveldResult,
    warnings: "list[str]",
) -> dict[str, object]:
    """FR-318 の alkali_* フィールドを構築 kwargs へ写す (警告は系列 warnings へ重複除去で積む)。

    per-frame の目標は `FrameSpec.target_composition` が運ぶ (runner 第 5 引数を作らない設計 —
    `_warmstart.call_runner` を迂回する bare ``runner(...)`` 経路でも欠落しない)。機能無効なら
    空 dict = FrameRietveldResult の既定値のまま (後方互換)。
    """
    fields, warns = alkali_fields(
        frame.target_composition, charge_constraint, phase_names, result
    )
    for w in warns:
        if w not in warnings:
            warnings.append(w)
    return fields


def run_sequential_rietveld(
    frames: Sequence[FrameSpec],
    initial_phases: Sequence[PhaseSpec],
    *,
    config: SequentialConfig | None = None,
    runner: Runner | None = None,
    phase_finder: PhaseFinder | None = None,
    ledger: Ledger | None = None,
    workdir: str | None = None,
    gpx_dir: str | None = None,
    save_gpx: bool = True,
) -> SequentialRietveldResult:
    """温度/時間系列を逐次に実構造 Rietveld 精密化する (ウォームスタート + 自動相追加)。

    :param frames: フレーム列 (観測データ + 軸値)。先頭から単一パス
    :param initial_phases: フレーム 0 の既知相 (CaTeO3 は alpha のみ)
    :param config: 逐次設定 (ウォームスタート/レンジ/変化点窓/相同定)
    :param runner: (frame, phases, initial_cells)->AutoRietveldResult。None なら GSAS 駆動
    :param phase_finder: 新相探索器。None かつ phase_id 有効なら既定 (MP identify+物質化) を用いる
    :param ledger: 追記台帳 (None なら内部生成)
    :param workdir: 相同定で物質化する CIF の書き出し先。None なら永続 tempdir を作る
        (CWD を汚さず、採用相の structure_path がセッション中生存する)。相同定を行うフレームで
        初めて必要になった時点で遅延生成する
    :param gpx_dir: **精密化成果物の保存先の根** (2026-08-20 規定「全解析で保存する」)。
        系列全体で run ディレクトリを**1 つ**共有し、その下に
        ``f0000_frame.gpx`` / ``f0180_trial_<候補相>.gpx`` / ``f0032_consolidate_<相>.gpx``
        が並ぶ (フレームごとにディレクトリを分けると 754 個できて探せない)。
        None なら ``TSUMUGIN_GPX_DIR`` → 先頭フレームのデータ隣接
        ``<data_dir>/tsumugin_gpx/`` の順で決まる
    :param save_gpx: 保存の opt-out (既定 True = 保存する)。⚠ **系列こそ保存が要る** —
        フレーム 754 枚のうちどれが無言 no-op だったか、棄却トライアルがなぜ棄却されたかは、
        残った fit そのものからしか追えない。容量の目安は 0.5-1.5 MB/フレーム
    :returns: SequentialRietveldResult
    """

    config = config or SequentialConfig()
    ledger = ledger if ledger is not None else Ledger()
    # 【系列で run ディレクトリを 1 つ共有する】: 文脈は「置き場所と名前」だけを運ぶ側路で、
    #   物理には影響しない (`gpxstore` の説明を参照)。無効化時も文脈は張る (enabled=False) —
    #   下流の `run_auto_rietveld` が「保存しない」を一貫して読めるようにするため。
    series_ctx = _series_context(frames, gpx_dir=gpx_dir, save_gpx=save_gpx, ledger=ledger)
    with gpx_context(series_ctx):
        return _run_sequential_rietveld(
            frames, initial_phases, config=config, runner=runner, phase_finder=phase_finder,
            ledger=ledger, workdir=workdir, series_ctx=series_ctx,
        )


def _series_context(
    frames: Sequence[FrameSpec], *, gpx_dir: str | None, save_gpx: bool, ledger: Ledger,
    kind: str = "m9",
) -> GpxContext:
    """系列全体で共有する成果物文脈を作る (run ディレクトリは 1 つ) + ledger に残す。

    M9 逐次 / M10 アンカーの**両方**がこれを使う (経路ごとの実装は取り残される — Issue #96 の
    ウォームスタートで実際に起きた病理)。``kind`` は ledger の接頭辞だけを分ける。
    """
    ctx, reason = series_context(
        frames[0].data_path if frames else "", gpx_dir=gpx_dir, save=save_gpx
    )
    if not ctx.enabled:
        return ctx
    if reason:
        ledger.append(f"{kind}_gpx_fallback", {"run_dir": ctx.run_dir, "reason": reason})
    ledger.append(f"{kind}_gpx_run_dir", {"run_dir": ctx.run_dir})
    return ctx


def _run_sequential_rietveld(
    frames: Sequence[FrameSpec],
    initial_phases: Sequence[PhaseSpec],
    *,
    config: SequentialConfig,
    runner: Runner | None,
    phase_finder: PhaseFinder | None,
    ledger: Ledger,
    workdir: str | None,
    series_ctx: GpxContext,
) -> SequentialRietveldResult:
    """`run_sequential_rietveld` の本体 (成果物文脈を張った内側)。"""
    import tempfile

    # 物質化 CIF の出力先: 指定なしなら永続 tempdir を遅延生成 (CWD 汚染回避, M2)。
    _workdir_holder: dict[str, str] = {}

    def _resolve_workdir() -> str:
        if workdir is not None:
            return workdir
        if "path" not in _workdir_holder:
            _workdir_holder["path"] = tempfile.mkdtemp(prefix="tsumugin-insitu-")
        return _workdir_holder["path"]

    if runner is None:
        runner = _default_gsas_runner(config)
    pid = config.phase_id
    if phase_finder is None and pid is not None and pid.enabled:
        phase_finder = _default_phase_finder(pid)

    n = len(frames)
    if config.max_frames is not None:
        n = min(n, config.max_frames)

    cp_config = ChangepointConfig(window=config.changepoint_window)

    phases: list[PhaseSpec] = list(initial_phases)
    known_formulas: list[str] = []  # 初期相の CIF から組成式は不明。相名で近似除外
    appearances: list[PhaseAppearance] = []
    frame_results: list[FrameRietveldResult] = []
    warnings: list[str] = []
    # FR-318 (H1): runner が charge_constraint を消費する保証の照合 (不一致は 1 回警告)。
    _warn_runner_constraint_mismatch(runner, config.charge_constraint, warnings)

    rwp_history: list[float] = []
    lattice_history: list[dict[str, float]] = []
    prev_cells: dict[str, Cell] | None = None
    # 相分率ウォームスタート用の直前状態 (Issue #82 再スコープ)。prev_active_names は「その分率が
    # 有効だった相集合」を記録し、次フレーム開始時点の相集合と一致する時のみ引き継ぐ (核形成安全弁:
    # フレーム内で新相が追加された直後の 1 フレームは prev_active_names が旧相集合のままなので
    # 不一致となり fresh にリセットされる)。
    prev_fractions: dict[str, float] | None = None
    prev_active_names: tuple[str, ...] | None = None
    min_rwp = float("inf")
    # 直近に rwp_jump トリガで探索を実行した際の Rwp。同一水準での無駄な再探索 (既定 finder は MP
    # ネットワーク往復) を避けつつ、**未追加相が成長すると Rwp が動く**ため前回探索から有意に動いたら
    # 再探索する (M1: 単調上昇する転移で相を捉えるのに必須)。changepoint 発火は毎回許可する。
    last_search_rwp: float | None = None

    ledger.append("m9_seq_start", {"n_frames": n, "initial_phases": [p.phase_name for p in phases]})

    for i in range(n):
        frame = frames[i]
        cur_names_before = tuple(p.phase_name for p in phases)  # このフレーム開始時点の相集合
        init_cells = prev_cells if (config.warm_start and prev_cells) else None
        init_fractions: dict[str, float] | None = None
        if (
            config.warm_start_fractions and config.warm_start
            and prev_fractions is not None and prev_active_names == cur_names_before
        ):
            init_fractions = prev_fractions
        # 【成果物の名前だけを差し替える】: 保存そのものは下流 (`run_auto_rietveld`) が行う。
        with gpx_context(series_ctx.child(role="frame", index=i)):
            result = _call_runner(runner, frame, tuple(phases), init_cells, init_fractions)
        rwp = float(result.final_rwp)
        cells = {name: _cell6(c) for name, c in result.refined_cells.items()}
        rep = phases[0].phase_name  # 代表相 (格子ジャンプ監視)
        # ウォームスタート用の分率 (フレーム内の新相追加トライアル前, cur_names_before に対応)。
        # 新相追加トライアルの結果で `result` が差し替わっても、次フレームへ引き継ぐのはこの
        # 追加前の値 (核形成安全弁: 追加後の相集合は次フレームでのみ fresh から解禁する)。
        pre_addition_fractions = _fractions_of(result, cur_names_before)

        # --- 変化点判定 (Rwp/格子ジャンプ) ---
        rwp_history.append(rwp)
        rep_cell = cells.get(rep, (0.0, 0.0, 0.0, 90.0, 90.0, 90.0))
        lattice_history.append({"a": rep_cell[0], "b": rep_cell[1], "c": rep_cell[2]})
        signal = detect_changepoint(rwp_history, lattice_history, 0, config=cp_config)

        # --- 新相自動同定 (トリガ: 残差 S/N or 変化点 or Rwp 相対ジャンプ) ---
        appended_this_frame: PhaseAppearance | None = None
        _cap_reached = pid is not None and pid.max_new_phases > 0 and len(appearances) >= pid.max_new_phases
        if (
            phase_finder is not None and pid is not None and pid.enabled
            and rwp < float("inf") and not _cap_reached
        ):
            rwp_jump = min_rwp < float("inf") and rwp > min_rwp * pid.trigger_rwp_ratio
            # 【残差 S/N トリガ (2相目追加判定)】: 既存相 fit の残差に、計数統計ノイズを超える未説明
            #   ピーク (S/N > 閾値) があれば未同定相の証拠。恣意的 Rwp 比でなくノイズ基準で判定する。
            snr_trigger = False
            if pid.snr_trigger > 0 and result.residual_two_theta:
                _sig = residual_significance(
                    result.residual_two_theta, result.residual_intensity, result.residual_sigma
                )
                snr_trigger = _sig.warrants_new_phase(pid.snr_trigger)
            # 【空振り抑制 (moved ガード)】: 前回探索から Rwp が 5% 超動いた時のみ再探索する。相が
            #   採用されれば Rwp が動き→次の探索を許可、空振り (採用なし) なら Rwp 不変→再探索しない。
            #   これで S/N トリガが**自己抑制的**になり (新相の mis-fit で残差 S/N が高止まりしても無駄試行を
            #   繰り返さない)、恣意的な max_new_phases キャップは不要になる。changepoint は毎回許可。
            moved = last_search_rwp is None or abs(rwp - last_search_rwp) > 0.05 * max(rwp, 1.0)
            if signal.triggered or ((snr_trigger or rwp_jump) and moved):
                last_search_rwp = rwp
                result, appended_this_frame, warn = _try_add_phase(
                    frame, phases, known_formulas, result, rwp, pid, phase_finder,
                    runner, _resolve_workdir(), i, ledger, series_ctx,
                )
                if warn:
                    warnings.append(warn)
                if appended_this_frame is not None:
                    appearances.append(appended_this_frame)
                    rwp = float(result.final_rwp)
                    cells = {name: _cell6(c) for name, c in result.refined_cells.items()}
                    # 採用後は代表相の格子履歴も更新 (rwp_history と対称, M3)
                    _rc = cells.get(rep, (0.0, 0.0, 0.0, 90.0, 90.0, 90.0))
                    lattice_history[-1] = {"a": _rc[0], "b": _rc[1], "c": _rc[2]}
                    rwp_history[-1] = rwp  # 採用後の Rwp で履歴を更新

        min_rwp = min(min_rwp, rwp)
        active_names = tuple(p.phase_name for p in phases)
        fractions = _fractions_of(result, active_names)
        refine_failed = not (rwp < float("inf"))

        frame_results.append(
            FrameRietveldResult(
                frame_index=i,
                axis_value=frame.axis_value,
                data_path=frame.data_path,
                rwp=rwp,
                gof=float(result.final_gof),
                refined_cells=cells,
                phase_fractions=fractions,
                phase_names=active_names,
                changepoint=signal.triggered,
                changepoint_reasons=signal.reasons,
                validity_passed=result.validity.passed,
                refine_failed=refine_failed,
                # 【残差レポート同梱】: 新相追加トライアル後の最終 `result` から畳む (採用時は
                #   追加後モデルの残差 = 実際に報告する fit と一致させる) 🔵 §4.5
                residual_report=_residual_report_of(result),
                # 【出版値の引き継ぎ】: 重量分率 ± esd・格子 esd。残差レポートと同じく最終 `result`
                #   から取る (報告する fit と一致させる)。無ければ空 dict へ縮退 🔵 Issue #96 レビュー
                **_publication_of(result),  # type: ignore[arg-type]
                # 【電気化学制約の診断 (FR-318)】: x_XRD vs x_echem・適用拘束・実行可能性。
                #   機能無効なら空 dict = 既定値のまま (後方互換)。
                **_alkali_of(frame, config.charge_constraint, active_names, result, warnings),  # type: ignore[arg-type]
                # 【このフレームの成果物】: 保存は下流が済ませている (規定 2026-08-20)。
                gpx_path=str(result.gpx_path or ""),
            )
        )
        ledger.append(
            "m9_seq_frame",
            {
                "frame": i,
                "axis": frame.axis_value,
                "rwp": rwp,
                "phases": list(active_names),
                "changepoint": signal.triggered,
                "added": appended_this_frame.phase_name if appended_this_frame else None,
            },
        )

        # ウォームスタート用に直前セルを更新 (失敗フレームは据え置き)
        if not refine_failed and cells:
            prev_cells = {**(prev_cells or {}), **cells}
        # 分率ウォームスタート用に直前状態を更新 (失敗フレームは据え置き)。追加トライアル前の
        # cur_names_before/pre_addition_fractions を記録する (核形成安全弁, Issue #82)。
        if not refine_failed:
            prev_fractions = pre_addition_fractions
            prev_active_names = cur_names_before

    # --- 逆方向伝播 (operando 逆方向解析): 確立した新相を前フレームへ逆伝播し onset を精密化 ---
    if config.backward_propagation and pid is not None and pid.enabled and appearances:
        frame_results, appearances = _consolidate_phase_cells(
            frames, n, frame_results, appearances, phases, pid, runner, ledger,
            charge_constraint=config.charge_constraint, warn_sink=warnings,
            series_ctx=series_ctx,
        )

    all_phase_names = tuple(p.phase_name for p in phases)
    ledger.append("m9_seq_done", {"phases": list(all_phase_names), "appearances": len(appearances)})

    return SequentialRietveldResult(
        frames=tuple(frame_results),
        appearances=tuple(appearances),
        phase_names=all_phase_names,
        warnings=tuple(warnings),
        ledger=ledger,
        gpx_dir=series_ctx.run_dir if series_ctx.enabled else "",
    )


def _best_established_cell(
    frame_results: "list[FrameRietveldResult]", phase_name: str, from_frame: int
) -> "Cell | None":
    """from_frame 以降で phase_name の相分率が最大のフレームの精密化格子を返す (確立セル)。

    支配フレーム (分率最大) ほど新相のセル/プロファイルが良く決まるため、そのセルを逆伝播の初期値にする。
    """
    best_frac = -1.0
    best_cell: "Cell | None" = None
    for j in range(from_frame, len(frame_results)):
        fr = frame_results[j]
        if fr.refine_failed:
            continue
        frac = float(fr.phase_fractions.get(phase_name, 0.0))
        cell = fr.refined_cells.get(phase_name)
        if cell is not None and frac > best_frac:
            best_frac = frac
            best_cell = cell
    return best_cell


def _rebuild_frame(
    res, fr, names, frame_spec: "FrameSpec | None" = None,
    charge_constraint: "ChargeConstraintConfig | None" = None,
    warn_sink: "list[str] | None" = None,
) -> "FrameRietveldResult":
    """再精密化結果 res で FrameRietveldResult を作り直す (元 fr のメタは保持)。"""
    cells = {name: _cell6(c) for name, c in res.refined_cells.items()}
    # FR-318: 差し替え結果に対する alkali 診断も**再計算**する (残差/出版値と同じ規律)。
    # 警告も捨てない (最終レビュー F6: 再精密化固有の警告が消えていた)。
    alkali: dict[str, object] = {}
    if frame_spec is not None and charge_constraint is not None:
        alkali, warns = alkali_fields(
            frame_spec.target_composition, charge_constraint, tuple(names), res
        )
        if warn_sink is not None:
            for w in warns:
                if w not in warn_sink:
                    warn_sink.append(w)
    return FrameRietveldResult(
        frame_index=fr.frame_index, axis_value=fr.axis_value, data_path=fr.data_path,
        rwp=float(res.final_rwp), gof=float(res.final_gof), refined_cells=cells,
        phase_fractions=_fractions_of(res, tuple(names)), phase_names=tuple(names),
        changepoint=fr.changepoint, changepoint_reasons=fr.changepoint_reasons,
        validity_passed=res.validity.passed, refine_failed=False,
        # 再精密化結果の残差で**再計算**する (元 fr の古い報告を持ち越すと、③ が差し替え済みの
        # fit に対して陳腐化した未説明ピークを読むことになる)。
        residual_report=_residual_report_of(res),
        # 出版値も**再精密化結果のもの**で差し替える (同上: 古い wt%/esd の持ち越しは、
        # 差し替えた fit に対して陳腐化した定量値を報告させる) 🔵 Issue #96 レビュー
        **_publication_of(res),  # type: ignore[arg-type]
        **alkali,  # type: ignore[arg-type]
        # 再精密化で置き換わったフレームは**その fit** の成果物を指す (古い方を指すと、
        # 報告している数値と開ける gpx が食い違う)。
        gpx_path=str(getattr(res, "gpx_path", "") or ""),
    )


def _consolidate_phase_cells(
    frames, n, frame_results, appearances, all_phases, pid, runner, ledger,
    charge_constraint: "ChargeConstraintConfig | None" = None,
    warn_sink: "list[str] | None" = None,
    series_ctx: "GpxContext | None" = None,
):
    """確立した新相の**globally-best セル**で全フレームを再精密化し、onset を逆伝播で捕捉する。

    実測診断: 少数相 (delta) は onset 域では prealign がセルを誤整合し (支配相 alpha のピークにロック)、
    誤セルを warm-start 前進させると Rietveld が異方誤差を飛び越えられず Rwp 高止まり → 偽相を誘発する。
    prealign が正しいセル (誤差 <0.05Å) を返すのは**相が支配的なフレーム**のみ。そこで各新相 P について:

    **注記 (Issue #20 続き)**: 「支配的でないと prealign が誤整合する」根本原因は、prealign の FoM が
    観測ピーク基準で支配相のピークに占められることであり、`phaseid.make_residual_cell_refiner` が
    整合先を**既知相減算残差**へ変えて解消済み (delta 最大軸誤差 4.21%→0.51%)。本関数はそれでも残る
    セル誤差 — 相分率が極小のフレームでは残差自体が乏しくピーク位置の情報が足りない — を、
    支配フレームで確立したセルを配ることで埋める役割として残す (両者は独立に効く)。

    1. **前方再精密化**: P が最も支配的なフレームの確立セルを初期値に、P を含む全フレーム (k..n-1) を
       再 fit し Rwp 改善なら差し替える (onset 域の誤セル poison を除去)。
    2. **逆方向 onset**: その良いセルを初期値に k-1, k-2, ... を P 追加で再 fit、相分率有意 + Rwp 改善なら
       採用し onset を前へ、外れたら停止。

    「支配時に良いセルを確立 → 全フレームへ配る」ことで少数 onset のセル誤整合を回避する。
    """
    name_to_spec = {p.phase_name: p for p in all_phases}
    updated = list(frame_results)
    new_appearances = list(appearances)

    for idx, ap in enumerate(appearances):
        spec = name_to_spec.get(ap.phase_name)
        if spec is None:
            continue
        k = ap.frame_index
        est_cell = _best_established_cell(updated, ap.phase_name, from_frame=k)
        if est_cell is None:
            continue
        # 1) 前方再精密化: P を含む k..n-1 を globally-best セルで再 fit (onset 域の誤セル poison 除去)
        for j in range(k, n):
            fr = updated[j]
            if ap.phase_name not in fr.phase_names or fr.refine_failed:
                continue
            phases_j = tuple(name_to_spec[nm] for nm in fr.phase_names if nm in name_to_spec)
            warm = {nm: fr.refined_cells[nm] for nm in fr.phase_names if nm in fr.refined_cells}
            warm[ap.phase_name] = est_cell
            with gpx_context(_child(series_ctx, "consolidate", j, ap.phase_name)):
                res = runner(frames[j], phases_j, warm)
            if res.final_rwp < float("inf") and float(res.final_rwp) < fr.rwp - 1e-9:
                updated[j] = _rebuild_frame(
                    res, fr, fr.phase_names, frames[j], charge_constraint, warn_sink
                )
                ledger.append(
                    "m9_consolidate_forward",
                    {"frame": j, "phase": ap.phase_name, "rwp_before": fr.rwp,
                     "rwp_after": float(res.final_rwp)},
                )
        # 前方再精密化でセルが更新された可能性 → 良いセルを取り直す
        est_cell = _best_established_cell(updated, ap.phase_name, from_frame=k) or est_cell
        # 2) 逆方向 onset: pre-onset フレームに P を良いセルで追加
        onset = k
        for j in range(k - 1, -1, -1):
            fr = updated[j]
            if ap.phase_name in fr.phase_names or fr.refine_failed:
                continue
            existing = [name_to_spec[nm] for nm in fr.phase_names if nm in name_to_spec]
            if not existing:
                continue
            trial_phases = tuple(existing + [spec])
            warm: dict[str, Cell] = {
                nm: fr.refined_cells[nm] for nm in fr.phase_names if nm in fr.refined_cells
            }
            warm[ap.phase_name] = est_cell
            with gpx_context(_child(series_ctx, "backward", j, ap.phase_name)):
                res = runner(frames[j], trial_phases, warm)
            new_frac = float(res.phase_fractions.get(ap.phase_name, 0.0))
            base_rwp = fr.rwp
            accepted = (
                (res.final_rwp < float("inf"))
                and new_frac > pid.frac_min
                and float(res.final_rwp) < base_rwp - 1e-9
            )
            ledger.append(
                "m9_backward_trial",
                {"frame": j, "phase": ap.phase_name, "rwp_before": base_rwp,
                 "rwp_after": float(res.final_rwp), "fraction": new_frac, "accepted": bool(accepted)},
            )
            if not accepted:
                break  # onset 発見 (これ以上前に P はない)
            names = tuple(fr.phase_names) + (ap.phase_name,)
            updated[j] = _rebuild_frame(
                res, fr, names, frames[j], charge_constraint, warn_sink
            )
            onset = j
        if onset < k:
            # onset を前へ更新 (逆伝播で捕捉した最も早いフレーム)
            new_appearances[idx] = PhaseAppearance(
                phase_name=ap.phase_name, frame_index=onset, axis_value=frames[onset].axis_value,
                structure_path=ap.structure_path, source=ap.source,
                rwp_before=updated[onset].rwp, rwp_after=updated[onset].rwp,
                evidence={**dict(ap.evidence), "backward_onset": True, "forward_frame": k},
            )
    return updated, tuple(new_appearances)


def _model_bic(gof: float, n_obs: int, n_phases: int, base_params: int, per_phase: int) -> float:
    """モデルの bic = chi2 + n_params·ln(n_obs)。chi2≈gof²·(n_obs−n_params)。

    n_params = base_params + per_phase·相数。anchor/select・operando `_frame_bic` と同式 (単一情報源)。
    gof 非有限は inf。n_obs=0 (未設定) は penalty=0 に縮退 (bic≈chi2, テストスタブ互換)。
    """
    if not math.isfinite(gof):
        return float("inf")
    no = max(int(n_obs), 1)
    p = base_params + per_phase * max(int(n_phases), 1)
    dof = max(no - p, 1)
    return gof * gof * dof + p * math.log(no)


def _accept_new_phase(trial, new_name, base_rwp, trial_rwp, new_frac, pid, base_result=None) -> bool:
    """新相受理判定 (③ 受理閾値): 分率 ∧ 新相セル健全 ∧ (任意) 妥当性 ∧ スコア改善 (bic or 相対 Rwp)。

    共通ガード: (1) 新相分率 > frac_min、(2) 新相セル非崩壊、(3) require_validity 時のみ全相妥当性。
    転移域では旧相のセル急変で全相 validity が fail するが新相追加の是非とは独立なので既定では課さない。

    スコア基準 (Issue #23 層1): **bic_acceptance (既定)** なら base(N相) vs trial(N+1相) を bic で比較し
    ``trial_bic < base_bic`` で採用。Rwp はパラメータ増で単調減少し余分な相が常に「改善」に見えるため、
    bic のパラメータ罰で本当に説明力がある相のみ採る。base_result 不在時は相対 Rwp にフォールバック。
    """
    new_cell = trial.refined_cells.get(new_name)
    new_cell_ok = new_cell is not None and min(
        float(new_cell[0]), float(new_cell[1]), float(new_cell[2])
    ) > 1.0
    validity_ok = trial.validity.passed if pid.require_validity else True
    if not (new_frac > pid.frac_min and new_cell_ok and validity_ok):
        return False

    if pid.bic_acceptance and base_result is not None:
        n_base = max(len(base_result.phase_fractions), len(base_result.refined_cells), 1)
        base_bic = _model_bic(base_result.final_gof, base_result.n_obs, n_base,
                              pid.bic_base_params, pid.bic_per_phase_params)
        trial_bic = _model_bic(trial.final_gof, trial.n_obs, n_base + 1,
                               pid.bic_base_params, pid.bic_per_phase_params)
        return trial_bic < base_bic - 1e-9

    rwp_gain = (base_rwp - trial_rwp) / base_rwp if base_rwp > 0 else 0.0
    return rwp_gain > pid.min_rwp_gain


def _try_add_phase(
    frame, phases, known_formulas, base_result, base_rwp, pid, phase_finder, runner,
    workdir, frame_idx, ledger, series_ctx: "GpxContext | None" = None,
) -> "tuple[AutoRietveldResult, PhaseAppearance | None, str | None]":
    """新相候補を同定・追加して再精密化し、受理基準を満たす**最良候補**を採用する (可逆・提案≠適用)。

    受理基準 (③ 受理閾値, 過剰適合ガード): (1) 新相の相分率 > frac_min ∧ (2) Rwp が**相対**で
    min_rwp_gain 超改善 ∧ (3) 新相セルが健全 (非崩壊) ∧ (4) require_validity 時のみ全相妥当性。
    **旧相ドリフトの妥当性 fail で新相を巻き添え棄却しない** (転移域では旧相 alpha のセルが急変し
    valid=False になるが、それは delta 追加の是非とは無関係; 実データで frame 150 の delta 受理を確認)。
    junk 候補は Rwp が下がらず (frame 90 の O₂: Rwp 悪化) 弾かれる。**同定スコアゲート
    (`min_identify_score`) を通った候補を全て試し、受理基準を満たす中で最小 Rwp のものを採る**
    (Dara 順でなく Rietveld フィットで選ぶ)。⚠ ゲートで落ちた候補は**試行精密化に回らない** —
    Rwp は母数増で必ず下がるため、残差を説明していない候補 (スコア ≤ 閾値) を Rietveld で
    競わせると偽相が勝つ。落とした候補は ledger `m9_phaseid_skipped` に残る。

    :returns: (結果, 採用相 or None, 警告文 or None)。相同定失敗/全候補棄却は警告文を返す (L1)。
    """
    exclude = [p.phase_name for p in phases] + list(known_formulas)
    # 既知相はウォームスタート (base_result の精密化格子) で、追加相は CIF 既定格子で再精密化する。
    base_cells = {name: _cell6(c) for name, c in base_result.refined_cells.items()}

    # 【現行相の参照ピーク列】: 現行相を精密化格子付き ReferencePhase に変換し finder へ渡す。
    #   用途は 2 つあり、**片方は `warm_start_known_phases` の対象外**:
    #   (a) 同定 (一本化 B): identify_pattern が known_phases として先に残差から減算 → 少数新相を
    #       clean な残差で探せる。A/B スイッチ `warm_start_known_phases` が制御するのは**これだけ**
    #       (A = identify-all-then-exclude)。既定 finder が `identify_new_phases` へ渡す段で分岐する。
    #   (b) 異方セルプリアラインの整合先 (Issue #20 続き): 少数相のセルは**既知相を引いた残差**へ
    #       整合させないと支配相のピークに引っ張られて壊れる。これは同定戦略 A/B と無関係な
    #       **モデルの格子の話**なので、A でも同じ参照列が要る (実測: 参照列を渡さず整合を諦めると
    #       delta が受理されなくなる = A で自動同定が壊れる)。
    #   変換不能 (pymatgen 不在 / CIF 読込不可 / スタブ finder の擬似パス) は None を除き空集合へ縮退
    #   する (静的同定へ安全フォールバック; 提案≠適用・非回帰)。
    known_refs: list[ReferencePhase] = []
    for p in phases:
        ref = phasespec_to_reference(
            p, refined_cell=base_cells.get(p.phase_name), wavelength=pid.wavelength
        )
        if ref is not None:
            known_refs.append(ref)

    try:
        candidates = phase_finder(frame, list(pid.elements), exclude, workdir, known_refs)
    except Exception as exc:
        ledger.append("m9_phaseid_error", {"frame": frame_idx, "error": repr(exc)[:200]})
        return base_result, None, f"frame {frame_idx}: 相同定に失敗 ({type(exc).__name__})"
    best: "tuple[AutoRietveldResult, PhaseSpec, dict] | None" = None
    for cand_spec, meta in candidates:
        # 【同定スコアゲート】: 残差を説明していない候補 (score ≤ 閾値) は試行に回さない。
        #   後段の選択は「受理基準を満たす中で最小 Rwp」だが Rwp は母数増で必ず下がるため、
        #   大分率で残差を舐める偽相が正解相に勝つ (実測: Dara スコア負の Ca3TeO6/CaTe3O8 が
        #   delta CaTeO3 に勝った)。相数を Rwp で決めない規律を候補選択にも適用する。
        #   スコアを持たない供給元は fail open (足切りしない)。
        score = meta.get("dara_score")
        if pid.min_identify_score is not None and isinstance(score, (int, float)):
            if not math.isfinite(float(score)) or float(score) <= pid.min_identify_score:
                ledger.append(
                    "m9_phaseid_skipped",
                    {
                        "frame": frame_idx, "candidate": cand_spec.phase_name,
                        "phase_id": str(meta.get("phase_id", "")),
                        "score": finite_or_none(score),
                        "min_identify_score": pid.min_identify_score,
                    },
                )
                continue
        trial_phases = tuple(list(phases) + [cand_spec])
        # 【棄却トライアルも 1 成果物として残す】: 相分率 ~0 の棄却が「残差を説明できない相」
        #   なのか「セルがずれて説明**できなかった**相」なのかは rwp/fraction だけでは切れない。
        #   ledger の行 (下) にパスを載せ、fit そのものを後から開けるようにする。
        trial_ctx = (
            series_ctx.child(role="trial", index=frame_idx, label=cand_spec.phase_name)
            if series_ctx is not None
            else None
        )
        with gpx_context(trial_ctx):
            trial = runner(frame, trial_phases, base_cells)
        trial_rwp = float(trial.final_rwp)
        new_frac = float(trial.phase_fractions.get(cand_spec.phase_name, 0.0))
        accepted = _accept_new_phase(trial, cand_spec.phase_name, base_rwp, trial_rwp,
                                     new_frac, pid, base_result)
        ledger.append(
            "m9_phaseid_trial",
            {
                "frame": frame_idx, "candidate": cand_spec.phase_name,
                "phase_id": str(meta.get("phase_id", "")),
                "rwp_before": base_rwp, "rwp_after": trial_rwp,
                "fraction": new_frac, "accepted": bool(accepted),
                # 【棄却の切り分け (Issue #20 続き)】: 相分率 ~0 で棄却された候補が「残差を説明
                #   できない相」なのか「セルがずれていて説明**できなかった**相」なのかは、
                #   rwp/fraction だけでは区別できない。物質化時の等方 strain と異方セル補正の
                #   整合先を同じ行に残し、ledger だけで原因を切れるようにする。
                "strain": finite_or_none(meta.get("strain")),
                "prealign_basis": str(meta.get("prealign_basis", "")),
                "refined_cell": meta.get("refined_cell"),
                # 棄却されたトライアルの fit そのもの (規定「全解析で保存」)。"" = 未保存。
                "gpx_path": str(trial.gpx_path or ""),
            },
        )
        # 受理基準を満たす中で最小 Rwp の候補を保持する (Dara 順でなく Rietveld フィットで選ぶ)。
        if accepted and (best is None or trial_rwp < float(best[0].final_rwp)):
            best = (trial, cand_spec, meta)

    if best is not None:
        trial, cand_spec, meta = best
        phases.append(cand_spec)
        # 採用相の組成式を既知相に記録し、以降のフレームで同相を再同定しないようにする
        # (finder への exclude は formula キー; 相名は MP formula と一致しないため formula で除外)。
        cand_formula = str(meta.get("formula", ""))
        if cand_formula:
            known_formulas.append(cand_formula)
        return trial, PhaseAppearance(
            phase_name=cand_spec.phase_name,
            frame_index=frame_idx,
            axis_value=frame.axis_value,
            structure_path=cand_spec.structure_path,
            source=str(meta.get("source", "materials_project")),
            rwp_before=base_rwp,
            rwp_after=float(trial.final_rwp),
            evidence=meta,
        ), None
    # 候補はあったが受理基準を満たさず / 候補ゼロ (相同定不発)。
    warn = None
    if not candidates:
        warn = f"frame {frame_idx}: 変化点だが新相候補なし (未指数ピークが残存の可能性)"
    return base_result, None, warn


def _xrdml_to_xye(src_path: str, dst_path: str) -> None:
    """XRDML を GSAS-II が読める 3 列 XYE (deg intensity esd) に変換する (自作 parse_xrdml 利用)。

    GSAS-II の Panalytical importer は optional 依存 (xmltodict) を要するため、コア側の numpy
    ローダーで読んで XYE に落とし GSAS の Topas xye importer に渡す (自己完結・依存追加なし)。
    """
    import numpy as np

    from ..reference.io import load_xrdml

    tt, inten = load_xrdml(src_path)
    esd = np.sqrt(np.clip(inten, 1.0, None))
    with open(dst_path, "w", encoding="utf-8") as fh:
        for x, y, e in zip(tt, inten, esd):
            fh.write(f"{x:.6f} {y:.4f} {e:.4f}\n")


def make_gsas_runner(
    *,
    instrument_path: str | Callable[[FrameSpec], str],
    radiation: object,
    geometry: object,
    two_theta_limits: tuple[float, float] | None = None,
    max_cyc: int = 12,
    background_coeffs: int = 6,
    recipe: "Sequence[RefinementStage] | None" = None,
    auto_freeze_minor_cells: float | None = None,
    charge_constraint: "ChargeConstraintConfig | None" = None,
) -> Runner:
    """放射源/ジオメトリ/装置を指定して FrameSpec→run_auto_rietveld の runner を作る (実運用の推奨 API)。

    XRDML フレームは numpy ローダーで XYE に自己変換して GSAS に渡す (optional 依存 xmltodict 不要)。
    ``instrument_path`` はパス、またはフレーム→パスの関数 (フレーム毎に instprm が異なる系列に対応)。
    放射光 (CuCr₂O₄) は radiation=XRAY_SYNCHROTRON/geometry=DEBYE_SCHERRER で、実験室 X 線 (CaTeO3) は
    XRAY_LAB/BRAGG_BRENTANO で作る。``background_coeffs`` は Chebyshev 背景項数 (実験室 X 線は背景が
    複雑で 6 では不足、24 前後を推奨; CaTeO3 実測で 6→24 が Rwp を大きく下げた)。
    ``recipe`` を渡すと既定の ``build_recipe`` (7 段階) を使わず、そのまま ``run_auto_rietveld`` に
    渡す (Issue #52)。operando 系列で不要な段階をスキップした軽量レシピを注入する用途 — 未指定
    (None) なら従来通り ``build_recipe`` で組み立てる (非回帰)。``recipe`` 指定時は ``background_coeffs``
    はレシピ側の背景段階に委ねられるため使われない。

    返す runner は ``initial_fractions`` キーワード引数 (相名→相対相分率) を任意で受け付け、指定
    されれば ``run_auto_rietveld(initial_fractions=)`` へそのまま転送する (Issue #82:
    ``SequentialConfig.warm_start_fractions`` の分率ウォームスタート)。呼び出し側 (`run_sequential_rietveld`)
    がシグネチャ検査でこのキーワードの有無を検出するため、``Runner`` の 3 引数プロトコル自体は
    変わらない (未指定時は従来通り 3 引数呼び出しのみで動作する)。

    ``auto_freeze_minor_cells`` は ``run_auto_rietveld`` へそのまま転送する分率連動の自動セル凍結
    **閾値** (Issue #80; bool ではなく float — 例 0.2 なら "cell" 段適用時点の相分率が 0.2 未満の相の
    セル解放をスキップ)。None (既定) で無効 = 従来動作 (非回帰)。少数相のセル解放で発散する多相
    operando 系列 (#47/#50) の自動化で、M9 系列経路から到達できる唯一の口 (Issue #93)。

    ``charge_constraint`` (FR-318) を渡すと、各フレームの ``FrameSpec.target_composition`` から
    `insitu.charge.plan_frame_constraint` で拘束 kwargs (占有率凍結シード/相間 EqnConstr) を
    組み立てて ``run_auto_rietveld`` へ渡す。None (既定) で従来動作 (非回帰)。
    """
    import os
    import tempfile

    from ..autorietveld.engine import run_auto_rietveld
    from ..autorietveld.model import HistogramSpec
    from ..autorietveld.recipe import build_recipe

    def runner(
        frame: FrameSpec,
        phases: Sequence[PhaseSpec],
        initial_cells: "dict[str, Cell] | None",
        initial_fractions: "dict[str, float] | None" = None,
    ) -> AutoRietveldResult:
        instr = instrument_path(frame) if callable(instrument_path) else instrument_path
        limits = frame.two_theta_limits or two_theta_limits
        with tempfile.TemporaryDirectory(prefix="m9-frame-") as tmp:
            data_path, data_format = frame.data_path, frame.data_format
            if frame.data_format.upper() == "XRDML":
                data_path = os.path.join(tmp, "frame.xye")
                _xrdml_to_xye(frame.data_path, data_path)
                data_format = "XYE"
            hist = HistogramSpec(
                data_path=data_path,
                instrument_path=instr,
                radiation=radiation,  # type: ignore[arg-type]
                geometry=geometry,  # type: ignore[arg-type]
                data_format=data_format,
                two_theta_limits=limits,
                excluded_regions=frame.excluded_regions,
                temperature=frame.axis_value,
                absorber_layers=frame.absorber_layers,
            )
            recipe_ = (
                recipe
                if recipe is not None
                else build_recipe([hist], list(phases), background_coeffs=background_coeffs)
            )
            # FR-318: per-frame 目標 (FrameSpec.target_composition) → 拘束 kwargs (モード分岐・
            # 実行可能性ゲートは plan_frame_constraint の責務)。機能無効なら空 = 従来動作。
            plan_kwargs: dict = {}
            if charge_constraint is not None and charge_constraint.enabled:
                plan = plan_frame_constraint(
                    frame.target_composition, charge_constraint,
                    [p.phase_name for p in phases],
                )
                plan_kwargs = dict(plan.kwargs)
                # diagnose (plan kwargs 空) でも占有率から組成を導出する解析なので、
                # 初期 Uiso/結合の事前警告を有効化する (最終レビュー F3 / REQ-318-005)。
                plan_kwargs["check_occupancy_uiso"] = True
            return run_auto_rietveld(
                [hist], list(phases), recipe=recipe_, max_cyc=max_cyc,
                initial_cells=dict(initial_cells) if initial_cells else None,
                initial_fractions=dict(initial_fractions) if initial_fractions else None,
                auto_freeze_minor_cells=auto_freeze_minor_cells,
                **plan_kwargs,
            )

    # FR-318 (レビュー H1): この runner が消費する charge_constraint を自己申告する。エンジンの
    # 報告側は plan を独立に再計算するため、**別の設定を持つ/消費しない runner** だと
    # 「報告された拘束 ≠ 実際に適用された拘束」の乖離が黙って起きる — エンジンがこの属性を
    # 照合して不一致に警告を出す (`_warn_runner_constraint_mismatch`)。
    runner._fr318_charge_constraint = charge_constraint  # type: ignore[attr-defined]
    return runner


def _default_gsas_runner(config: SequentialConfig) -> Runner:
    """FrameSpec を run_auto_rietveld で実行する既定 runner (GSAS 遅延 import, ゼロ設定の便宜版)。

    既定は実験室 X 線 Bragg-Brentano・装置は data_path 隣接の ``.instprm``/``.prm`` 規約。放射光や
    フレーム毎装置指定など実運用では ``make_gsas_runner`` を注入する (AGENT_PLAYBOOK §1)。
    """
    from ..autorietveld.model import Geometry, Radiation

    return make_gsas_runner(
        instrument_path=_infer_instrument,
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        two_theta_limits=config.two_theta_limits,
        # FR-318 (レビュー H1): 既定 runner にも charge_constraint を渡す。渡し忘れると
        # 拘束 kwargs が run_auto_rietveld へ届かないのに、エンジンの報告側 (plan 再計算) は
        # alkali_constraint_applied を立てる = 「呼べるが黙って間違う」の典型になる。
        charge_constraint=config.charge_constraint,
    )


def _infer_instrument(frame: FrameSpec) -> str:
    """フレームの instrument パスを推定する (既定は data と同ディレクトリの慣習名)。

    実運用では FrameSpec に instrument を持たせるか、系列共通の instprm を用いる。M9 では
    HistogramSpec が要求するため、data_path 隣接の ``.prm``/``.instprm`` を規約とする。
    """
    from pathlib import Path

    p = Path(frame.data_path)
    for ext in (".instprm", ".prm"):
        cand = p.with_suffix(ext)
        if cand.exists():
            return str(cand)
    # 見つからなければ data_path をそのまま返す (GSAS 側でエラー化 → refine_failed)
    return str(p.with_suffix(".instprm"))


def _default_phase_finder(pid: PhaseIdConfig) -> PhaseFinder:
    """既定の新相探索器 (MP identify + 物質化, 遅延 import)。

    MP client は**初回探索時に遅延生成**する (変化点が一度も発火しない系列で、MATERIALS_PROJECT_API
    未設定でも run を先頭で中断させないため)。provider と materializer は単一 client を共有する。
    """
    box: dict[str, object] = {}

    def _ensure() -> tuple[object, object]:
        if "provider" not in box:
            from ..mp.client import MPRestClient
            from ..mp.provider import MPReferenceProvider
            from .phaseid import MPMaterializer

            client = MPRestClient()  # キーは環境変数 MATERIALS_PROJECT_API
            box["provider"] = MPReferenceProvider(client)
            box["materializer"] = MPMaterializer(client)
        return box["provider"], box["materializer"]

    def finder(
        frame: FrameSpec, elements: Sequence[str], exclude_formulas: Sequence[str], workdir: str,
        known_phases: Sequence[ReferencePhase] = (),
    ) -> "Sequence[tuple[PhaseSpec, dict]]":
        from ..reference.io import load_pattern
        from .phaseid import identify_new_phases, make_residual_cell_refiner

        provider, materializer = _ensure()
        two_theta, intensity = load_pattern(frame.data_path, frame.data_format)

        # 異方セル補正器 (Issue #20): 物質化 CIF を観測へ整合させた**異方セル**に置換する numpy
        # プリアライン。GSAS 非依存 (後段の run_auto_rietveld が Cell 段でさらに研磨する)。
        # 【整合先は残差】: プリアラインの FoM は観測ピーク基準なので、生パターンへ整合させると
        #   少数相の反射を**支配相のピーク**へばら撒くセルが選ばれる (実測 CaTeO3 frame180:
        #   delta の最大軸誤差が出発点 3.42% → 4.21% と悪化)。既知相を引いた残差では候補が支配的
        #   になり同じ FoM が正しく効く (同条件 0.51%)。既存相を引けないときは**プリアラインしない**
        #   (等方 strain のまま = 提案≠適用の安全側)。詳細は `make_residual_cell_refiner`。
        cell_refiner = None
        if pid.refine_new_phase_cell:
            tt_range = frame.two_theta_limits or (
                float(two_theta.min()), float(two_theta.max())
            )
            cell_refiner = make_residual_cell_refiner(
                two_theta, intensity,
                known_phases=known_phases,
                wavelength=pid.wavelength, two_theta_range=tt_range,
                subtract_bg=pid.subtract_bg,
                # 既存相が 1 つでもあるフレームでは、それを引けない限り整合しない。
                require_subtraction=bool(exclude_formulas),
            )

        found = identify_new_phases(
            two_theta, intensity, elements=list(elements), provider=provider,
            materializer=materializer, workdir=workdir, exclude_formulas=list(exclude_formulas),
            top_k=pid.top_k, hull_cutoff_ev=pid.hull_cutoff_ev, subtract_bg=pid.subtract_bg,
            name_prefix="new", cell_refiner=cell_refiner,
            rerank_top_k=pid.rerank_top_k, rerank_wavelength=pid.wavelength,
            require_full_element_system=pid.require_full_element_system,
            # operando warm-start (一本化 B): 現行相を先に残差減算。**A/B スイッチが効くのはここだけ** —
            # 上の cell_refiner (異方セル補正の整合先) は同定戦略と無関係なので A でも残差を使う。
            known_phases=known_phases if pid.warm_start_known_phases else (),
        )
        # ③ が「セルがどう決まったか」を追えるよう整合先を証拠に残す (ledger/appearance evidence)。
        if not pid.refine_new_phase_cell:
            basis = "off"           # 設定で無効
        elif cell_refiner is None:
            basis = "skipped"       # 既存相を引けず整合を見送り (等方 strain のまま)
        elif known_phases:
            basis = "residual"      # 既知相減算残差へ整合 (既定経路)
        else:
            basis = "pattern"       # 既存相なし = 候補が支配的なので生パターンへ整合
        return [
            (
                ip.phase_spec,
                {"source": ip.source, "phase_id": ip.phase_id, "formula": ip.formula,
                 "dara_score": ip.score, "strain": ip.strain,
                 "refined_cell": list(ip.refined_cell) if ip.refined_cell else None,
                 "prealign_basis": basis},
            )
            for ip in found
        ]

    return finder
