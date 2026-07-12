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

from ..autorietveld.model import AutoRietveldResult, PhaseSpec

if TYPE_CHECKING:
    from ..autorietveld.model import RefinementStage
from ..reference.model import ReferencePhase
from ..sequential.changepoint import ChangepointConfig, detect_changepoint
from ..store.ledger import Ledger
from .model import (
    Cell,
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


def _cell6(cell: Sequence[float]) -> Cell:
    """任意長の格子タプルを長さ 6 の (a,b,c,α,β,γ) へ整える (角度欠落は 90°)。"""
    vals = list(cell) + [90.0, 90.0, 90.0]
    return (
        float(vals[0]), float(vals[1]), float(vals[2]),
        float(vals[3]), float(vals[4]), float(vals[5]),
    )


def _fractions_of(result: AutoRietveldResult, phase_names: Sequence[str]) -> dict[str, float]:
    """AutoRietveldResult から相名→相分率を取り出す (欠測は 0.0)。単相は {name:1.0} を補う。"""
    fr = dict(result.phase_fractions)
    if not fr and len(phase_names) == 1:
        return {phase_names[0]: 1.0}
    return {name: float(fr.get(name, 0.0)) for name in phase_names}


def run_sequential_rietveld(
    frames: Sequence[FrameSpec],
    initial_phases: Sequence[PhaseSpec],
    *,
    config: SequentialConfig | None = None,
    runner: Runner | None = None,
    phase_finder: PhaseFinder | None = None,
    ledger: Ledger | None = None,
    workdir: str | None = None,
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
    :returns: SequentialRietveldResult
    """
    import tempfile

    config = config or SequentialConfig()
    ledger = ledger if ledger is not None else Ledger()
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

    rwp_history: list[float] = []
    lattice_history: list[dict[str, float]] = []
    prev_cells: dict[str, Cell] | None = None
    min_rwp = float("inf")
    # 直近に rwp_jump トリガで探索を実行した際の Rwp。同一水準での無駄な再探索 (既定 finder は MP
    # ネットワーク往復) を避けつつ、**未追加相が成長すると Rwp が動く**ため前回探索から有意に動いたら
    # 再探索する (M1: 単調上昇する転移で相を捉えるのに必須)。changepoint 発火は毎回許可する。
    last_search_rwp: float | None = None

    ledger.append("m9_seq_start", {"n_frames": n, "initial_phases": [p.phase_name for p in phases]})

    for i in range(n):
        frame = frames[i]
        init_cells = prev_cells if (config.warm_start and prev_cells) else None
        result = runner(frame, tuple(phases), init_cells)
        rwp = float(result.final_rwp)
        cells = {name: _cell6(c) for name, c in result.refined_cells.items()}
        rep = phases[0].phase_name  # 代表相 (格子ジャンプ監視)

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
                    runner, _resolve_workdir(), i, ledger,
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

    # --- 逆方向伝播 (operando 逆方向解析): 確立した新相を前フレームへ逆伝播し onset を精密化 ---
    if config.backward_propagation and pid is not None and pid.enabled and appearances:
        frame_results, appearances = _consolidate_phase_cells(
            frames, n, frame_results, appearances, phases, pid, runner, ledger,
        )

    all_phase_names = tuple(p.phase_name for p in phases)
    ledger.append("m9_seq_done", {"phases": list(all_phase_names), "appearances": len(appearances)})

    return SequentialRietveldResult(
        frames=tuple(frame_results),
        appearances=tuple(appearances),
        phase_names=all_phase_names,
        warnings=tuple(warnings),
        ledger=ledger,
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


def _rebuild_frame(res, fr, names) -> "FrameRietveldResult":
    """再精密化結果 res で FrameRietveldResult を作り直す (元 fr のメタは保持)。"""
    cells = {name: _cell6(c) for name, c in res.refined_cells.items()}
    return FrameRietveldResult(
        frame_index=fr.frame_index, axis_value=fr.axis_value, data_path=fr.data_path,
        rwp=float(res.final_rwp), gof=float(res.final_gof), refined_cells=cells,
        phase_fractions=_fractions_of(res, tuple(names)), phase_names=tuple(names),
        changepoint=fr.changepoint, changepoint_reasons=fr.changepoint_reasons,
        validity_passed=res.validity.passed, refine_failed=False,
    )


def _consolidate_phase_cells(
    frames, n, frame_results, appearances, all_phases, pid, runner, ledger,
):
    """確立した新相の**globally-best セル**で全フレームを再精密化し、onset を逆伝播で捕捉する。

    実測診断: 少数相 (delta) は onset 域では prealign がセルを誤整合し (支配相 alpha のピークにロック)、
    誤セルを warm-start 前進させると Rietveld が異方誤差を飛び越えられず Rwp 高止まり → 偽相を誘発する。
    prealign が正しいセル (誤差 <0.05Å) を返すのは**相が支配的なフレーム**のみ。そこで各新相 P について:

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
            res = runner(frames[j], phases_j, warm)
            if res.final_rwp < float("inf") and float(res.final_rwp) < fr.rwp - 1e-9:
                updated[j] = _rebuild_frame(res, fr, fr.phase_names)
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
            updated[j] = _rebuild_frame(res, fr, names)
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
    workdir, frame_idx, ledger,
) -> "tuple[AutoRietveldResult, PhaseAppearance | None, str | None]":
    """新相候補を同定・追加して再精密化し、受理基準を満たす**最良候補**を採用する (可逆・提案≠適用)。

    受理基準 (③ 受理閾値, 過剰適合ガード): (1) 新相の相分率 > frac_min ∧ (2) Rwp が**相対**で
    min_rwp_gain 超改善 ∧ (3) 新相セルが健全 (非崩壊) ∧ (4) require_validity 時のみ全相妥当性。
    **旧相ドリフトの妥当性 fail で新相を巻き添え棄却しない** (転移域では旧相 alpha のセルが急変し
    valid=False になるが、それは delta 追加の是非とは無関係; 実データで frame 150 の delta 受理を確認)。
    junk 候補は Rwp が下がらず (frame 90 の O₂: Rwp 悪化) 弾かれる。**複数候補 (top_k) を全て試し、
    受理基準を満たす中で最小 Rwp のものを採る** (Dara 順でなく Rietveld フィットで選ぶ)。

    :returns: (結果, 採用相 or None, 警告文 or None)。相同定失敗/全候補棄却は警告文を返す (L1)。
    """
    exclude = [p.phase_name for p in phases] + list(known_formulas)
    # 既知相はウォームスタート (base_result の精密化格子) で、追加相は CIF 既定格子で再精密化する。
    base_cells = {name: _cell6(c) for name, c in base_result.refined_cells.items()}

    # 【operando warm-start (一本化 B)】: 現行相を精密化格子付き ReferencePhase に変換し finder へ渡す。
    #   identify_pattern が known_phases として先に残差から減算 → 少数新相を clean な残差で探せる。
    #   変換不能 (pymatgen 不在 / CIF 読込不可 / スタブ finder の擬似パス) は None を除き空集合へ縮退
    #   する (静的同定=identify-all-then-exclude に安全フォールバック; 提案≠適用・非回帰)。
    known_refs: list[ReferencePhase] = []
    if pid.warm_start_known_phases:
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
        trial_phases = tuple(list(phases) + [cand_spec])
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
    """
    import os
    import tempfile

    from ..autorietveld.engine import run_auto_rietveld
    from ..autorietveld.model import HistogramSpec
    from ..autorietveld.recipe import build_recipe

    def runner(
        frame: FrameSpec, phases: Sequence[PhaseSpec], initial_cells: "dict[str, Cell] | None"
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
                temperature=frame.axis_value,
            )
            recipe_ = (
                recipe
                if recipe is not None
                else build_recipe([hist], list(phases), background_coeffs=background_coeffs)
            )
            return run_auto_rietveld(
                [hist], list(phases), recipe=recipe_, max_cyc=max_cyc,
                initial_cells=dict(initial_cells) if initial_cells else None,
            )

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
        from .phaseid import identify_new_phases

        provider, materializer = _ensure()
        two_theta, intensity = load_pattern(frame.data_path, frame.data_format)

        # 異方セル補正器 (Issue #20): 物質化 CIF を観測へ整合させた**異方セル**に置換する numpy
        # プリアライン。GSAS 非依存 (後段の run_auto_rietveld が Cell 段でさらに研磨する)。
        cell_refiner = None
        if pid.refine_new_phase_cell:
            from ..autorietveld.cell_refine import prealign_cell_from_structure

            tt_range = frame.two_theta_limits or (
                float(two_theta.min()), float(two_theta.max())
            )

            def cell_refiner(cif_path: str):  # noqa: F811 (条件付き定義)
                sol = prealign_cell_from_structure(
                    cif_path, two_theta, intensity,
                    wavelength=pid.wavelength, two_theta_range=tt_range,
                    subtract_bg=pid.subtract_bg,
                )
                return sol.cell if sol is not None else None

        found = identify_new_phases(
            two_theta, intensity, elements=list(elements), provider=provider,
            materializer=materializer, workdir=workdir, exclude_formulas=list(exclude_formulas),
            top_k=pid.top_k, hull_cutoff_ev=pid.hull_cutoff_ev, subtract_bg=pid.subtract_bg,
            name_prefix="new", cell_refiner=cell_refiner,
            rerank_top_k=pid.rerank_top_k, rerank_wavelength=pid.wavelength,
            require_full_element_system=pid.require_full_element_system,
            known_phases=known_phases,  # operando warm-start (一本化 B): 現行相を先に残差減算
        )
        return [
            (
                ip.phase_spec,
                {"source": ip.source, "phase_id": ip.phase_id, "formula": ip.formula,
                 "dara_score": ip.score, "strain": ip.strain,
                 "refined_cell": list(ip.refined_cell) if ip.refined_cell else None},
            )
            for ip in found
        ]

    return finder
