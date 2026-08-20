"""GSAS-II 駆動の自動 Rietveld エンジン (M7)。

HistogramSpec/PhaseSpec を GSAS-II プロジェクトに変換し、段階解放レシピ (recipe.py) の
宣言的フラグを GSAS-II 呼び出しへ翻訳して順に精密化する。各段階で Rwp が悪化した場合は
直前スナップショット (.gpx コピー) へ revert して当該段階なしで継続する (REQ-105 / FR-202)。
精密化失敗は例外でなく chi2=inf 相当 (converged=False, rwp=inf) に変換しガードレール的に
扱う (REQ-403)。全段階遷移を Ledger へ追記する (NFR-105)。

GSAS-II は本モジュール内で遅延 import するため、tsumugin コア import は numpy のみを維持する。

信頼性: 🔵 T1 プロトタイプの段階進行 (Rwp 45→13.7→11.2→9.84) を production 化。
"""

from __future__ import annotations

import contextlib
import math
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from .._json import finite_or_none
from ..store import Ledger
from .absorption import apply_absorption_correction
from .atomrows import (
    atom_row,
    coord_esd_states,
    free_index_from_site_symmetry,
)
from .bounds import (
    BoundHit,
    BoxBound,
    cell_box_bounds,
    detect_bound_hits,
    displacement_box_bounds,
    size_strain_box_bounds,
)
from .diagnostics import (
    RefinementDiagnostics,
    WeakVariable,
    data_term_rwp,
    read_diagnostics,
    read_variable_esds,
    read_variable_values,
    split_weak_variables,
)
from .model import (
    AutoRietveldResult,
    CellEsd,
    CoordEsd,
    FinalPolish,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
    StabilityOptions,
    StageResult,
    ValidityReport,
)
from .recipe import build_recipe, validate_correlation_groups
from .restraint_dlg import RefineProgressStub
from .stagepolicy import StageMetrics, decide_stage
from .validity import (
    check_initial_uiso,
    check_profile_physicality,
    check_validity,
    warn_occupancy_uiso_coupling,
)


def _g2sc():
    """遅延 import + 出力抑制済みの GSASIIscriptable モジュール。"""
    from GSASII import GSASIIscriptable as G2sc

    try:
        G2sc.SetPrintLevel("none")
    except Exception:
        pass
    return G2sc


class RefinementFailedError(RuntimeError):
    """GSAS-II の精密化が失敗したことを示す (段階ごとの inf 化 → revert 経路に載せるため)。"""


def _refine_failure_message(ok: object, rvals: object) -> str | None:
    """``GSASIIstrMain.Refine`` の戻り値 ``(OK, Rvals)`` を失敗文 (or None) に写す。

    ``OK`` が偽なら失敗。GSAS の ``Rvals['msg']`` があれば理由として添える (ledger に残す)。
    msg が無くても**失敗は失敗**として扱う (沈黙させない)。
    """
    if ok:
        return None
    msg = ""
    if isinstance(rvals, Mapping):
        msg = str(rvals.get("msg", "") or "").strip()
    return f"GSAS-II 精密化が失敗を返しました: {msg}" if msg else "GSAS-II 精密化が失敗を返しました"


@contextlib.contextmanager
def _capture_refine_status(_module: object | None = None, dlg: object | None = None):
    """``GSASIIstrMain.Refine`` の戻り値を捕まえる scoped パッチ (``{"ok","msg","calls"}`` を yield)。

    **なぜ必要か (CaTeO3 frame180 実測)**: GSAS-II の ``G2Project.refine`` は
    ``G2strMain.Refine(self.filename, makeBack=makeBack)`` を**戻り値を受け取らずに**呼ぶ。
    ``Refine`` は失敗を例外でなく ``(False, {'msg': …})`` で返すため (実測:
    ``'divide by zero encountered in scalar divide'`` / ``'**** ERROR: Refinement failed ****'``)、
    **失敗しても例外が飛ばない**。その場合 ``Refine`` は covData を書かずに戻るので gpx の
    ``Covariance`` は前段のまま残り、`_rvals` は**前段とビット同一**の rwp/gof/n_params を返す。
    段階ループは「悪化していない」と判断して revert しないため、**その段で立てた精密化フラグが
    残ったまま次段へ進み、以降の全段が同じ理由で失敗し続ける** (実測: 二相試行が S2 以降 7 段
    すべて no-op = 相分率と背景しか精密化されていない fit が「完走」した)。Rwp にも
    ``reverted`` フラグにも一切現れない。

    ここで戻り値を捕まえて `RefinementFailedError` に変換すると、既存の
    ``except Exception → chi2=inf → 直前スナップショットへ revert + ledger`` 経路にそのまま
    載る (CLAUDE.md 不変条件「精密化バックエンドの失敗は例外でなく chi2=inf の結果に変換し、
    ガードレールに処理させる」)。revert はフラグごと巻き戻すので**後続段の連鎖失敗も止まる**。

    **同じパッチ点で ``dlg`` も注入する** (REQ-SAR-203): ``G2Project.refine`` は
    ``G2strMain.Refine(self.filename, makeBack=makeBack)`` としか呼ばず ``dlg`` を渡す口が無い。
    ``Refine`` 自身は ``dlg`` を公開パラメータに持つので、既にここで包んでいる呼び出しへ
    キーワードとして挿し込むのが**唯一の非侵襲な経路**である (GSAS 本体を書き換えない)。
    ``dlg`` を渡すと ``Refine`` は成功時に ``(True, Rvals)`` を返す (無指定時は暗黙 ``None``) が、
    失敗判定は既存の `_refine_failure_message` がそのまま扱える。

    :param _module: パッチ対象モジュール (テスト注入用)。None なら ``GSASII.GSASIIstrMain``
    :param dlg: 注入する duck-typed プログレス受け口 (`restraint_dlg.RefineProgressStub`)。
        None (既定) なら**一切触らない** = 現行と完全に同一の呼び出し。既に ``dlg`` が
        与えられている呼び出し (位置引数 2 個目/キーワード) は上書きしない — GSAS 内部の
        ``Refine(..., None, allDerivs=True)`` のような別用途を壊さないため
    :returns: ``{"ok": bool, "msg": str, "calls": int}``。1 回でも失敗があれば ``ok=False``。
        GSAS 不在・``Refine`` 属性なし・一度も呼ばれなかった場合は **fail open** (``ok=True``)
    """
    status: dict[str, object] = {"ok": True, "msg": "", "calls": 0}
    mod = _module
    if mod is None:
        try:
            from GSASII import GSASIIstrMain as mod  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001 — GSAS 不在は fail open (numpy-only 経路を壊さない)
            mod = None
    if mod is None or not hasattr(mod, "Refine"):
        yield status
        return

    original = mod.Refine

    def _wrapped(*args, **kwargs):
        if dlg is not None and len(args) < 2 and "dlg" not in kwargs:
            kwargs["dlg"] = dlg
        out = original(*args, **kwargs)
        status["calls"] = int(status["calls"]) + 1  # type: ignore[arg-type]
        ok = out[0] if isinstance(out, tuple) and out else True
        rvals = out[1] if isinstance(out, tuple) and len(out) > 1 else None
        failure = _refine_failure_message(ok, rvals)
        if failure is not None and status["ok"]:
            status["ok"] = False
            status["msg"] = failure
        return out

    mod.Refine = _wrapped
    try:
        yield status
    finally:
        mod.Refine = original


def _rvals(gpx) -> tuple[float, float, int]:
    """精密化後の (Rwp, GOF, nvar) を Covariance から取り出す。"""
    cov = gpx.data["Covariance"]["data"]
    rv = cov.get("Rvals", {})
    rwp = float(rv.get("Rwp", float("inf")))
    gof = float(rv.get("GOF", float("inf")))
    nvar = len(cov.get("varyList", []))
    return rwp, gof, nvar


def _data_rwp(gpx, rwp: float, *, split: bool) -> "tuple[float, float | None, float]":
    """段の判定に使う **データ項 Rwp** と、penalty 込みの生 Rwp / penalty 量を返す。

    :param split: 分離を試みるか。**``StabilityOptions.enable_restraints`` が真のときだけ真**に
        すること。penalty が χ² に入るのは ``dlg`` を渡した精密化だけであり、渡していない
        精密化でも ``Rvals['RestraintSum']`` はゲートの外で報告される (実測 4.66e9) ため、
        フラグを見ずに引くと**拘束を登録しただけの既定経路で値が変わる**。
        偽なら `Rvals` を 1 度も読まず ``(rwp, None, 0.0)`` を返す = 現行とビット同一。
    :returns: ``(データ項 Rwp, penalty 込み Rwp or None, RestraintSum)``。
        第 2 要素は**実際に penalty が分離できたときだけ**非 None (None = 分離不要)。
    """
    if not split or not math.isfinite(rwp):
        return rwp, None, 0.0
    try:
        rv = gpx.data["Covariance"]["data"].get("Rvals", {})
    except (KeyError, TypeError, AttributeError):  # 共分散なし → 分離材料なし (fail open)
        return rwp, None, 0.0
    penalty = float(rv.get("RestraintSum", 0.0) or 0.0)
    data = data_term_rwp(rwp, rv.get("chisq"), penalty)
    if data is None or data == rwp:
        return rwp, None, penalty
    return data, rwp, penalty


def _restraint_sum(gpx) -> float:
    """gpx の現在状態の ``Rvals['RestraintSum']`` (= penalty の二乗和) を返す。

    最終報告 (`AutoRietveldResult.final_restraint_penalty`) を「採用状態」に揃えるための
    読み出し。共分散が無い/読めない場合は 0.0 へ縮退する (fail open)。
    """
    try:
        rv = gpx.data["Covariance"]["data"].get("Rvals", {})
        return float(rv.get("RestraintSum", 0.0) or 0.0)
    except (KeyError, TypeError, AttributeError, ValueError):
        return 0.0


def _converged(gpx) -> bool:
    cov = gpx.data["Covariance"]["data"]
    return bool(cov.get("Rvals", {}).get("converged", True))


def _nobs(gpx) -> int:
    """精密化に用いた実観測点数 (全ヒストグラム総和) を Covariance の Rvals から取り出す。

    レンジ制限 (two_theta_limits) 適用後の点数を反映する。未取得は 0 (利用側が代替源へ縮退)。
    """
    rv = gpx.data["Covariance"]["data"].get("Rvals", {})
    try:
        return int(rv.get("Nobs", 0))
    except (TypeError, ValueError):
        return 0


def _refine_once(gpx, dlg: object | None = None) -> None:
    """1 回精密化し、GSAS が**戻り値で返す**失敗を例外へ変換する。

    `_capture_refine_status` の唯一の呼び出し口。段の初回精密化と、未収束時の追加サイクル
    (REQ-SAR-101) の**両方**がここを通ることで、「追加サイクルだけ無言失敗を見逃す」穴を
    作らない (無言失敗は rwp にも reverted にも現れないため、経路ごとに塞ぐしかない)。

    :param dlg: restraint を χ² に入れるための ``dlg`` スタブ (REQ-SAR-203)。None (既定) は
        現行と完全に同一の呼び出し。**ここも経路ごとに塞ぐ**対象なので、追加サイクルでも
        同じスタブが渡る (段の途中で拘束の有無が切り替わると段列の意味が壊れる)
    """
    with _capture_refine_status(dlg=dlg) as status:
        gpx.do_refinements([{}])
    if not status["ok"]:
        raise RefinementFailedError(str(status["msg"]))


def _run_convergence_cycles(
    diagnostics: RefinementDiagnostics,
    cycle,
    *,
    max_shift_esd: float,
    extra_cycles: int,
) -> "tuple[RefinementDiagnostics, object | None, int]":
    """未収束なら**同じ段のまま**追加サイクルで回し直す (REQ-SAR-101)。

    `is_converged` が ``None`` (判定材料なし = 共分散が無い) のときは**回さない** — 情報が
    無いことを「未収束」と断じると、共分散を持たない精密化で全段が無限に回ってしまう
    (fail open)。受理/revert の最終判断は呼び出し側が最終診断で行う。

    :param cycle: 1 サイクル精密化して ``(新しい診断, 付随値)`` を返す callable。付随値には
        engine 側の ``((rwp, gof, nvar), converged)`` を載せる (GSAS 依存をここへ持ち込まない)
    :param extra_cycles: 追加サイクルの上限 (負値は 0 に丸める)
    :returns: ``(最終診断, 最後の付随値 or None, 実際に回した追加サイクル数)``
    """
    used = 0
    payload: object | None = None
    limit = max(0, int(extra_cycles))
    while (
        diagnostics.is_converged(max_shift_esd=max_shift_esd) is False and used < limit
    ):
        used += 1
        diagnostics, payload = cycle()
    return diagnostics, payload, used


def _is_noop_stage(
    prev_rwp: float, prev_gof: float, prev_nvar: int, rwp: float, gof: float, nvar: int
) -> bool:
    """その段が「何もしていない」か — no-op 段の検出 (REQ-SAR-102)。

    **判定の本体は `autorietveld.stagepolicy` に一本化した** (M12 T7): 同じ方針を GSAS 経路と
    TOPAS 経路が別実装で持つと、片方で学んだ検出がもう片方に効かない (実際 TOPAS の T4 では
    S3/S5 がこのクラスのまま完走していた)。本関数は既存の呼び出し形を保つ薄い委譲である。
    """
    return decide_stage(
        StageMetrics(prev_rwp, prev_gof, prev_nvar), StageMetrics(rwp, gof, nvar)
    ).is_noop


def _prune_candidates(
    weak_vars: "Sequence[WeakVariable]", already_frozen: "set[str]", exempt: "Sequence[str]"
) -> "tuple[WeakVariable, ...]":
    """`esd >= |値|` の変数から**凍結の候補になり得るもの**を選ぶ (REQ-SAR-103, 純関数)。

    既に凍結済みの変数は除く (同じ凍結を二重登録しない)。``exempt`` は ``esd/|値|`` の比が
    構造的に意味を持たない変数名トークン (`diagnostics.split_weak_variables` に根拠)。

    ⚠ **これは「凍結すべき」ではなく「凍結できる」の列挙である。** 実際に凍結するかは
    タイミングの判断 (救済 / 最終研磨 / opt-in の毎段プルーニング) であり、呼び出し側が持つ。
    比の悪い順 (`weak_variables` の並び) を保つので、先頭が**最弱**の変数になる。
    """
    judged, _exempt = split_weak_variables(weak_vars, exempt)
    return tuple(w for w in judged if w.name not in already_frozen)


def _needs_rescue(diagnostics: RefinementDiagnostics, *, max_shift_esd: float) -> bool:
    """その段が**行き詰まっている**か — 救済プルーニングの発火条件 (純関数)。

    2 つの直接証拠だけを見る:

    * ``Rvals['SVD0'] > 0`` — GSAS が特異な変数を検出した = 悪条件の**直接**証拠。
      収束フラグが立っていても発火させる (特異行列の上に載った「収束」は信用できない)。
    * 収束していない (`is_converged` が明示的に ``False``)。判定材料が無い ``None`` は
      **発火させない** (情報が無いことを異常と断じない, fail open)。

    **``not reverted`` (= うまく行っている段) では発火しない**のが要点である。途中段階の
    大きな esd は「決定不能」ではなく「まだ決まっていない」だけなので、順調な段で凍結すると
    後段で決まるようになったパラメータを二度と解放できない (不可逆なラチェット)。
    """
    if diagnostics.svd_singularities > 0:
        return True
    return diagnostics.is_converged(max_shift_esd=max_shift_esd) is False


def _run_rescue_freezes(
    diagnostics: RefinementDiagnostics,
    freeze,
    cycle,
    *,
    max_shift_esd: float,
    exempt: "Sequence[str]",
    already_frozen: "set[str]",
    max_freeze: int,
    max_rounds: int,
) -> "tuple[RefinementDiagnostics, object | None, int, tuple[str, ...]]":
    """行き詰まった段を**最弱の変数を落として**回し直す (REQ-SAR-103 の救済経路)。

    GSAS-II 自身の `GSASIImath.HessianLSQ` の ``dropTerms`` と同じ思想 — 特異/悪条件のときだけ
    母数を減らす。違いは「何を落としたかを台帳に残す」ことである (GSAS は黙って落とす)。

    凍結は `Controls['parmFrozen']` に載るので、**段が revert されればスナップショット復元と
    一緒に巻き戻る** (呼び出し側が `already_frozen` の追跡からも外すこと)。

    :param freeze: 変数名の列を凍結し**実際に凍結できた名前**を返す callable (GSAS 依存を注入)
    :param cycle: 1 サイクル精密化して ``(新しい診断, 付随値)`` を返す callable
    :param max_freeze: 1 回あたり凍結する最大数 (0 以下は 1 に丸める — 「救済するが何も
        落とさない」は無限ループの元)
    :param max_rounds: 段あたりの救済回数上限 (0 で救済なし)
    :returns: ``(最終診断, 最後の付随値 or None, 実施回数, 凍結した変数名)``
    """
    frozen_all: list[str] = []
    payload: object | None = None
    rounds = 0
    limit = max(0, int(max_rounds))
    per_round = max(1, int(max_freeze))
    seen = set(already_frozen)
    while rounds < limit and _needs_rescue(diagnostics, max_shift_esd=max_shift_esd):
        candidates = _prune_candidates(diagnostics.weak_vars, seen, exempt)
        if not candidates:
            break  # 落とせる変数が無い = 救済では直せない (呼び出し側の revert に任せる)
        got = list(freeze([w.name for w in candidates[:per_round]]))
        if not got:
            break  # 1 つも凍結できなかった → 回しても同じ結果になる (無限ループを作らない)
        frozen_all.extend(got)
        seen.update(got)
        rounds += 1
        diagnostics, payload = cycle()
    return diagnostics, payload, rounds, tuple(frozen_all)


def _freeze_variables(gpx, names: "Sequence[str]") -> list[str]:
    """変数を GSAS の Frozen リストへ入れ、**以降の段の varyList から外す** (REQ-SAR-103)。

    `GSASIIstrMain.Refine` は精密化の直前に ``Controls['parmFrozen']['FrozenList']`` に載る
    変数を varyList から除く。値は動かさず「精密化しない」だけなので、非破壊であり
    スナップショット復元 (revert) でも一貫して巻き戻る (Controls は gpx ツリーの一部)。

    変数名が GSAS の変数記法として解釈できない等の失敗は**その変数だけ諦めて継続**する
    (診断由来の付加機能が精密化本体を落とさない, fail open)。

    :returns: 実際に凍結できた変数名
    """
    frozen: list[str] = []
    for name in names:
        try:
            if gpx.set_Frozen(name, mode="add"):
                frozen.append(name)
        except Exception:  # noqa: BLE001 — 解釈不能な変数名は当該変数のみスキップ
            continue
    return frozen


def _run_final_polish(
    gpx,
    g2sc,
    *,
    gpx_path: Path,
    snap_path: Path,
    undetermined: "Sequence[WeakVariable]",
    exempt: "Sequence[WeakVariable]",
    already_frozen: "set[str]",
    stab: StabilityOptions,
    stage_results: "list[StageResult]",
    dlg: object | None,
    split_penalty: bool,
    max_cyc: int,
    radiations,
    histograms,
    ledger: Ledger,
) -> "tuple[object, FinalPolish, tuple[WeakVariable, ...], tuple[WeakVariable, ...]]":
    """**最終研磨** (opt-in): 決まらなかった変数を凍結して 1 回だけ精密化し、再報告する。

    **なぜ既定 OFF なのか**: 研磨後の値は「一部の変数を凍結した fit」のものであり、拘束なしの
    run と同じ列に並べて比較できない。出版値の意味を黙って切り替えないため、有効化は明示に限り、
    有効時は ``final polish`` という**独立した段**を段列の末尾に足して結果から判別できるようにする
    (`FinalPolish` も同時に返る)。

    **なぜ悪化しても採用するのか**: 凍結は自由度を減らすので Rwp は普通わずかに悪化する。それを
    revert 条件にすると研磨は決して適用されない。破棄するのは**破綻**だけ — GSAS の失敗・
    非有限 Rwp・格子崩壊/プロファイル非物理 (既存の revert ガードと同じ基準)。

    **``exempt`` を引数で受けるのは早期 return のためである**: 研磨しなかった (凍結対象なし) /
    revert した経路では、呼び出し側が**研磨前に算出して ledger `m7_undetermined` へ書いた**
    判定対象外リストがそのまま正しい。ここで空タプルを返すと呼び出し側の再代入で握り潰され、
    結果 (`AutoRietveldResult.undetermined_exempt` → ② の同名キー) が **ledger の
    ``exempt_variables`` と食い違う**。実測 T1 で ``dA*`` 12 個が exempt に載るので実データで
    必ず踏む。「捨てずに別列で返す — 報告が何を見なかったかを隠さない」(REQ-SAR-103) は
    **研磨の有無で切り替わってはならない**。

    :param undetermined: 研磨前に判定した「決まらなかったパラメータ」
    :param exempt: 研磨前に判定した「判定対象外」(``dAx`` 等)。早期 return ではこれをそのまま返す
    :returns: ``(gpx, 研磨の記録, 研磨後の undetermined, 研磨後の判定対象外)``。gpx は
        revert 時にスナップショットから読み直した**新しい** `G2Project` になり得る
    """
    names = [w.name for w in undetermined if w.name not in already_frozen]
    rwp_before = stage_results[-1].rwp if stage_results else float("inf")
    if not names:
        # 「決まらなかった変数が無い」= 研磨する対象が無い。**成功でも失敗でもない**ので
        #   理由を残す (有効にしたのに何も起きなかった、を静かにしない)。
        polish = FinalPolish(
            applied=False,
            rwp_before=rwp_before,
            rwp_after=rwp_before,
            reason="凍結対象なし (決まらなかったパラメータが無い)",
        )
        ledger.append("m7_final_polish", polish.to_dict())
        # 研磨していない = 研磨前の判定がそのまま最終判定。**exempt を空で潰さない**。
        return gpx, polish, tuple(undetermined), tuple(exempt)

    gpx.save()
    shutil.copyfile(gpx_path, snap_path)
    frozen = tuple(_freeze_variables(gpx, names))
    reason = ""
    try:
        if not frozen:
            raise RefinementFailedError("凍結できた変数が 0 個 (GSAS が変数名を解釈できない)")
        _refine_once(gpx, dlg)
        rwp, gof, nvar = _rvals(gpx)
        rwp, penalized, _penalty = _data_rwp(gpx, rwp, split=split_penalty)
        if not math.isfinite(rwp):
            raise RefinementFailedError("研磨後の Rwp が非有限")
        if not _cells_physical(gpx.phases()) or not _profiles_physical(
            gpx.histograms(), radiations, histograms
        ).passed:
            raise RefinementFailedError("研磨後の格子/プロファイルが非物理")
    except Exception as exc:  # noqa: BLE001 — 破綻は revert に変換 (既存ガードと同じ規律)
        reason = repr(exc)[:200]
        shutil.copyfile(snap_path, gpx_path)
        gpx = g2sc.G2Project(gpxfile=str(gpx_path))
        gpx.data["Controls"]["data"]["max cyc"] = max_cyc
        polish = FinalPolish(
            applied=False,
            frozen=frozen,
            rwp_before=rwp_before,
            rwp_after=float("inf"),
            reverted=True,
            reason=reason,
        )
        ledger.append("m7_final_polish", polish.to_dict())
        # revert = 研磨前の状態へ戻した = 研磨前の判定がそのまま最終判定 (exempt も同じ)。
        return gpx, polish, tuple(undetermined), tuple(exempt)

    diag = read_diagnostics(gpx, corr_threshold=stab.corr_threshold)
    after, after_exempt = split_weak_variables(
        diag.weak_vars, stab.esd_ratio_exempt_tokens
    )
    stage_results.append(
        StageResult(
            label="final polish",
            rwp=rwp,
            gof=gof,
            n_params=nvar,
            converged=_converged(gpx),
            reverted=False,
            # 出版値がこの段の産物であることを ③ が読める形で残す (② は note を返す)。
            note=f"final polish; frozen_undetermined={len(frozen)}",
            # 研磨が最終段になると `final_rwp_penalized` はこの段から採られる。ここを None の
            # ままにすると「研磨を有効にしただけで penalty 込み Rwp が消える」= 出版値の
            # 一貫性が研磨の有無で切り替わってしまう (`final_restraint_penalty` は最終 gpx
            # から読むので、揃えないと両者が別の状態を指す)。
            rwp_penalized=penalized,
        )
    )
    polish = FinalPolish(
        applied=True, frozen=frozen, rwp_before=rwp_before, rwp_after=rwp
    )
    ledger.append(
        "m7_final_polish",
        {
            **polish.to_dict(),
            "n_undetermined_after": len(after),
            "variables_after": [w.to_dict() for w in after],
            "note": "出版値は一部の変数を凍結した fit のもの (REQ-SAR-103)",
        },
    )
    return gpx, polish, after, after_exempt


def _cells_physical(
    g2phases, min_length: float = 0.5, max_length: float = 1000.0
) -> bool:
    """全相の格子が物理的 (有限・妥当な長さ・幾何学的に可能な計量テンソル) かを判定する。

    多相・高分解能データではプロファイル/サイズ解放時に格子が 0 へ崩壊する発散が起こり得る
    (近ゼロ崩壊)。加えて Issue #49: 少数相の相分率が 0 に近づくと格子が悪条件化し、
    近ゼロ崩壊とは逆に長さが桁違いに**爆発**したり、角度が幾何学的に不可能な組み合わせ
    (計量テンソルが非正定値 = "Invalid cell metric tensor") に発散する場合がある。
    これらは chi2=inf 化されず validity のみ False になって結果に残留し得るため、
    revert 対象として検出する。参照格子 (前フレーム/CIF) に依存しないため operando の
    フレーム単位判定にもそのまま使える。

    判定は 3 種:
    1. 近ゼロ崩壊: a/b/c いずれかが非有限、または min_length 未満。
    2. 爆発: a/b/c いずれかが max_length を超過。
    3. 無効計量テンソル: α/β/γ が非有限、または体積項
       t = 1 - cos²α - cos²β - cos²γ + 2·cosα·cosβ·cosγ が非有限あるいは 0 以下
       (退化・非正定値 = 幾何学的に構成不可能な格子)。
    """
    for ph in g2phases:
        cell = ph.get_cell()
        for key in ("length_a", "length_b", "length_c"):
            v = float(cell[key])
            if not math.isfinite(v) or v < min_length or v > max_length:
                return False

        angles = []
        for key in ("angle_alpha", "angle_beta", "angle_gamma"):
            a = float(cell[key])
            if not math.isfinite(a):
                return False
            angles.append(a)
        alpha, beta, gamma = (math.radians(a) for a in angles)
        ca, cb, cg = math.cos(alpha), math.cos(beta), math.cos(gamma)
        t = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
        if not math.isfinite(t) or t <= 0.0:
            return False
    return True


# 内省・物理性判定で抽出するプロファイル関連キー (CW + TOF)。
# Lam (波長) は較正 (calibrate_instrument_from_standard, Issue #61) で hist_profile に露出するため含める。
# FWHM/物理性判定は U,V,W,X,Y のみを用いるので Lam の追加は非破壊 (余分キーは無視される)。
_PROFILE_INTROSPECT_KEYS = (
    "Lam", "U", "V", "W", "X", "Y", "SH/L", "Zero",
    "sig-0", "sig-1", "sig-2", "alpha", "beta-0", "beta-1", "difC", "difA",
)


def _extract_profile(g2hists) -> tuple[dict[str, tuple[float, bool]], ...]:
    """各ヒストグラムの GSAS Instrument Parameters から {key: (value, refined)} を抽出する。

    GSAS 格納形は ``hist.data['Instrument Parameters'][0][key] = [default, value, refine_flag]``。
    プロファイル関連キー (_PROFILE_INTROSPECT_KEYS) のみ拾い、値・解放フラグを取り出す。
    ``Instrument Parameters`` 不在や要素構造差は当該ヒストグラムを空 dict に縮退する (EDGE-001)。
    GSAS を import しない純データ抽出のため numpy 決定論テスト可能。
    """
    out: list[dict[str, tuple[float, bool]]] = []
    for h in g2hists:
        d: dict[str, tuple[float, bool]] = {}
        try:
            inst = h.data["Instrument Parameters"][0]
        except (KeyError, IndexError, TypeError, AttributeError):
            out.append(d)
            continue
        for key in _PROFILE_INTROSPECT_KEYS:
            entry = inst.get(key) if hasattr(inst, "get") else None
            if not entry:
                continue
            try:
                if len(entry) >= 2:
                    val = float(entry[1])
                    ref = bool(entry[2]) if len(entry) >= 3 else False
                else:
                    val = float(entry[0])
                    ref = False
            except (IndexError, TypeError, ValueError):
                continue
            d[key] = (val, ref)
        out.append(d)
    return tuple(out)


def _profile_ranges(
    g2hists, radiations, profiles, histograms=None
) -> tuple[tuple[float, float] | None, ...]:
    """各ヒストグラムのプロファイル評価レンジ (CW=2θ°, TOF=d) を返す。

    評価レンジは **精密化に用いる区間** に限定する: getdata("x") の観測範囲を、指定があれば
    HistogramSpec.two_theta_limits で切り詰める。プロファイルはこの区間でのみ実際に使われるため、
    区間外 (ノイズ tail 等) の幅関数負値で誤 revert しないための処置 (T4 非回帰)。TOF は切り詰め後の
    範囲 (TOF μs) を d≈(t-Zero)/difC で d に換算する (difC,Zero は profiles から)。getdata 失敗・空・
    difC 欠落/0 は None に縮退し、利用側がレンジ依存判定を skip する (EDGE-003)。
    """
    out: list[tuple[float, float] | None] = []
    for i, (h, rad, prof) in enumerate(zip(g2hists, radiations, profiles)):
        try:
            xs = h.getdata("x")
        except Exception:  # noqa: BLE001 — 取得失敗は非致命 skip
            out.append(None)
            continue
        if xs is None or len(xs) == 0:
            out.append(None)
            continue
        lo, hi = float(min(xs)), float(max(xs))
        # 精密化レンジ (two_theta_limits) で切り詰める (残差抽出のマスクと同じ区間)。
        if histograms is not None and i < len(histograms):
            lim = histograms[i].two_theta_limits
            if lim is not None:
                lo, hi = max(lo, float(lim[0])), min(hi, float(lim[1]))
                if lo >= hi:  # 交差が空 (限界指定が観測外) → レンジ判定を skip
                    out.append(None)
                    continue
        if getattr(rad, "is_tof", False):
            dif_c = prof.get("difC", (0.0, False))[0]
            zero = prof.get("Zero", (0.0, False))[0]
            if dif_c == 0.0:
                out.append(None)
                continue
            d_lo, d_hi = (lo - zero) / dif_c, (hi - zero) / dif_c
            out.append((min(d_lo, d_hi), max(d_lo, d_hi)))
        else:
            out.append((lo, hi))
    return tuple(out)


def _profiles_physical(g2hists, radiations, histograms=None) -> ValidityReport:
    """プロファイル物理性を判定する薄いラッパ (_cells_physical と同格の revert ガード用)。

    抽出不能 (全 hist が空 dict) は passed=True に縮退する (判定 skip, EDGE-001)。
    """
    profiles = _extract_profile(g2hists)
    if not any(profiles):
        return ValidityReport(passed=True)
    ranges = _profile_ranges(g2hists, radiations, profiles, histograms)
    return check_profile_physicality(
        profiles=profiles, radiations=radiations, ranges=ranges
    )


def _profile_keys(radiation: Radiation) -> list[str]:
    """CW (X 線/中性子) の Gaussian プロファイル係数キー U,V,W。

    Lorentzian (X,Y) + Zero は別段階 (recipe の "profile_lorentzian") で revert ガード付きで追加する
    (同段階に混ぜると悪化時に U,V,W ごと revert され T3/T4 が回帰するため分離)。TOF は本段階では
    精密化しない (呼び出し側でスキップ)。TOF の装置プロファイル (sig/alpha/beta) はキャリブレーション
    依存で、ピーク形状は size/mustrain で処理する。
    """
    return ["U", "V", "W"]


def _tof_profile_keys() -> list[str]:
    """TOF (PNT) 装置プロファイルの較正キー。

    近似 instprm (Z-Code Type0m → GSAS PNT の変換で厳密でない sig/alpha/beta) を実測へ寄せる較正用。
    支配的な **Gaussian 幅の d 依存 (sig-1/sig-2)** のみに限定する。alpha/beta (立ち上がり/減衰) は
    ``1/alpha``・``1/beta`` を含みゼロ近傍で発散するため既定では解放しない (実 GSAS で div-by-zero を確認)。
    opt-in 段階 (既定レシピには含めない, T4 非回帰)。実測で幅較正が Rwp を改善する (17.3→16.2%)。
    """
    return ["sig-1", "sig-2"]


def _phase_atom_info(ph, spec: PhaseSpec) -> dict:
    """相の原子メタ情報 (座標可変ラベル・全ラベル・混合占有ラベル) を収集する。

    座標精密化は自由座標を 1 つ以上持つ原子のみに限定する。対称性で完全に固定された特殊位置
    (例 garnet 16a/24d, 自由座標 0) の座標解放はセル発散を招く (T2 実測)。一方 Pnma 4c のような
    部分特殊位置 (自由座標 x,z) は精密化する。判定は GSAS-II の GetCSxinel(site symmetry) で行う。
    """
    from GSASII import GSASIIspc as G2spc

    atoms = ph.data["Atoms"]
    cx, ct, cs, cia = ph.data["General"]["AtomPtrs"]
    labels = [row[ct - 1] for row in atoms]
    coord_atoms = []
    for row in atoms:
        try:
            free = G2spc.GetCSxinel(row[cs])[0]
            has_free = any(free)
        except Exception:
            has_free = str(row[cs]).strip() == "1"
        if has_free:
            coord_atoms.append(row[ct - 1])
    # 原子ラベル→元素記号 (GSAS 原子行の type 列)。重原子順の段階解放に使う。
    element_of: dict[str, str] = {}
    for row in atoms:
        try:
            element_of[str(row[ct - 1])] = str(row[ct]).strip()
        except Exception:  # noqa: BLE001 — 形が違う行は元素不明として飛ばす (fail open)
            continue
    # 座標凍結ラベル (剛体固定原子) は coords 段の解放対象から除く。
    frozen = set(spec.frozen_coord_labels)
    if frozen:
        coord_atoms = [lab for lab in coord_atoms if lab not in frozen]
    mixed = {lab for grp in spec.mixed_occupancy_groups for lab in grp}
    free_occ = set(spec.free_occupancy_labels)
    equiv_occ = {lab for grp in spec.occupancy_equiv_groups for lab in grp}
    sum_occ = {lab for grp in spec.occupancy_sum_groups for lab in grp}
    return {
        "labels": labels, "coord_atoms": coord_atoms,
        "mixed": mixed, "free_occ": free_occ, "equiv_occ": equiv_occ | sum_occ,
        "uiso_labels": list(spec.free_uiso_labels),
        "refine_cell": spec.refine_cell,
        # 原子ラベル→元素記号 (重原子から順に解放する "本気フィット" 手順で使う)
        "element_of": element_of,
    }


#: 原子番号順の元素記号 (重原子から順に解放する "本気フィット" 手順の並び替えに使う)。
_Z_ORDER: dict[str, int] = {
    sym: i + 1
    for i, sym in enumerate(
        "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
        "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce "
        "Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn "
        "Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf".split()
    )
}


def _element_rank_labels(info: dict, labels: "list[str]", rank: object) -> "list[str]":
    """``labels`` のうち **重い方から rank 番目の元素**に属するものだけを返す。

    ``rank`` が bool (``{"coords": True}`` = 全解放) なら ``labels`` をそのまま返す。int なら
    そのランクの元素だけ (存在しない rank は空 = その段は no-op)。元素記号は先頭 2 文字までを
    見て正規化する (GSAS の type は "Fe+2" のように価数付きのことがある)。

    **それ以外の値は `ValueError`**。ここは以前 catch-all で ``labels`` を返していたが、
    `recipe.build_serious_recipe` が用意する**未実装の展開宣言** (``element_expansion=
    "heavy_first"`` の ``"heavy_first"``、``uiso_tiers`` の ``"shared"``/``"by_element"``/
    ``"individual"``) がそこへ落ち、「重原子から順に 1 元素ずつ」と宣言した段が**黙って
    1 段で全原子を解放する別物**になっていた (WS-3 3-3 未実装)。engine が解釈できない宣言は
    大声で失敗させ、既存の例外 → chi2=inf → revert → ledger ``m7_stage_error`` 経路に載せる
    (CLAUDE.md「呼べるが黙って間違う」の禁止)。② 入口でも `mcp._recipe_spec` が同じ語彙を弾く。
    """
    if isinstance(rank, bool):
        return list(labels)
    if not isinstance(rank, int):
        raise ValueError(
            f"元素ランクとして解釈できない値です: {rank!r}。bool (全解放) か int (ランク) の"
            " いずれかを指定してください"
            " (engine 側の展開が未実装の宣言値なら WS-3 3-3 の完了まで使えません)"
        )
    element_of = info.get("element_of") or {}

    def _z(label: str) -> int:
        raw = str(element_of.get(label, ""))
        sym = raw[:2].strip().capitalize()
        return _Z_ORDER.get(sym, _Z_ORDER.get(sym[:1].upper(), 0))

    order = sorted({_z(lab) for lab in labels}, reverse=True)
    if rank >= len(order):
        return []
    target = order[rank]
    return [lab for lab in labels if _z(lab) == target]



def _freeze_all(hists, phases, atom_flag_maps, radiations, keep: "set[str]") -> None:
    """現在解放されている精密化フラグを一旦すべて落とす (``keep`` の名前は残す)。

    GSAS の ``clear_refinements`` / ``clear_HAP_refinements`` を使う。背景とヒストグラム
    スケールは "本気フィット" 手順で常時解放の前提なので触らない。
    """
    if "cell" not in keep:
        for ph in phases:
            try:
                ph.clear_refinements({"Cell": True})
            except Exception:  # noqa: BLE001
                pass
    if "displacement" not in keep:
        for hist in hists:
            for keys in (["Shift", "Transparency"], ["DisplaceX", "DisplaceY"]):
                try:
                    hist.clear_refinements({"Sample Parameters": keys})
                except Exception:  # noqa: BLE001 — 当該ジオメトリに無いキーは無視
                    pass
    if "profile" not in keep:
        for hist in hists:
            for key in ("U", "V", "W", "X", "Y", "Zero", "SH/L", "alpha", "beta-0", "beta-1",
                        "sig-0", "sig-1", "sig-2"):
                try:
                    hist.clear_refinements({"Instrument Parameters": [key]})
                except Exception:  # noqa: BLE001
                    pass
    if "size_strain" not in keep:
        for ph in phases:
            for key in ("Size", "Mustrain", "Pref.Ori."):
                try:
                    ph.clear_HAP_refinements({key: True}, histograms=list(hists))
                except Exception:  # noqa: BLE001
                    pass
    if "atoms" not in keep:
        for ph, fmap in zip(phases, atom_flag_maps):
            try:
                ph.clear_refinements({"Atoms": list(fmap)})
            except Exception:  # noqa: BLE001
                pass
            fmap.clear()

def _update_atom_flags(flag_map: dict[str, str], info: dict, stage_flags) -> bool:
    """段階フラグに応じて per-atom フラグ (X/U/F) の集合を更新する。変化があれば True。

    - coords: 一般位置原子に "X"
    - uiso: 全原子に "U"
    - occupancy: 混合占有原子 + 単独解放原子 (free_occ) に "F"
    """
    changed = False

    def add(label: str, ch: str) -> None:
        nonlocal changed
        cur = flag_map.get(label, "")
        if ch not in cur:
            flag_map[label] = "".join(c for c in "XUF" if c in cur + ch)
            changed = True

    if "coords" in stage_flags:
        for lab in _element_rank_labels(info, info["coord_atoms"], stage_flags["coords"]):
            add(lab, "X")
    if "uiso" in stage_flags:
        # free_uiso_labels 指定時はその原子のみ、未指定なら全原子の Uiso を解放。
        uiso_targets = info.get("uiso_labels") or info["labels"]
        for lab in _element_rank_labels(info, list(uiso_targets), stage_flags["uiso"]):
            add(lab, "U")
    if "occupancy" in stage_flags:
        occ_labels = (
            list(info["mixed"]) + list(info.get("free_occ", set()))
            + list(info.get("equiv_occ", set()))
        )
        for lab in _element_rank_labels(info, occ_labels, stage_flags["occupancy"]):
            add(lab, "F")  # 等値グループ (例 Fe=C=N) も解放 ([0,1] 拘束は張らない)
    return changed


def _fixed_profile_flags(histograms) -> list[bool]:
    """各ヒストグラムが装置プロファイル固定か (instrument_profile 指定) を返す (numpy, Issue #38)。"""
    return [getattr(h, "instrument_profile", None) is not None for h in histograms]


def _seed_instrument_profile(g2hist, profile) -> None:
    """InstrumentProfile.values を GSAS Instrument Parameters に書き込む (GSAS 依存, Issue #38)。

    inst[0][key][1] = value。存在しないキー・構造差は無視する (EDGE-001)。
    """
    try:
        inst = g2hist.data["Instrument Parameters"][0]
    except (KeyError, IndexError, TypeError, AttributeError):
        return
    for key, val in profile.values.items():
        entry = inst.get(key) if hasattr(inst, "get") else None
        if entry is None or len(entry) < 2:
            continue
        try:
            entry[1] = float(val)
        except (TypeError, ValueError):
            continue


def _should_refine_cell(info: dict, fraction: float | None, threshold: float | None) -> bool:
    """相のセル (格子) 解放可否を判定する (Issue #47 手動凍結 + Issue #80 自動閾値凍結)。

    ⚠ **`fraction`/`threshold` の basis は `phase_fractions` (= HAP Scale の Σ=1 正規化値) であり、
    `phase_weight_fractions` (wt%) ではない** (`_phase_fraction_map` 由来)。**答えは basis で割れる**:
    実測 K₂Mn[Fe(CN)₆] (cubic 1103.4 / tetra 517.8 amu) の `Scale {cubic .75, tetra .25}` は
    `wt% {cubic .865, tetra .135}` であり、`threshold=0.2` は **Scale では tetra を解放し wt% では
    凍結する**。出版値は wt% なので、閾値を wt% の直感で決めると静かに外れる (③ 側の警告は
    `skills/insitu`・`skills/operando-diagnose`・`AGENT_PLAYBOOK` の「分率の閾値は Scale 基準」節)。

    判定優先順位 (手動 > 自動 > 既定解放):

    1. 明示 ``PhaseSpec.refine_cell=False`` (手動, Issue #47) は常に優先し凍結する。
       自動閾値の有無や分率に関わらず解放しない (**手動が自動に勝つ**)。
    2. 自動閾値 (``threshold``) が ``None`` → 従来動作 (非回帰): 分率を見ず解放する。
    3. 分率が不明 (``fraction=None``, 例: 相分率抽出に失敗/精密化前で未取得) →
       **fail open** (凍結しない)。少数相と誤認して全相を凍結する事故を避ける。
    4. 分率が ``threshold`` 未満 → 自動凍結 (計量が近い相同士の相関による発散を防ぐ, Issue #80)。
    5. それ以外 (分率が閾値以上, 単相の分率 1.0 を含む) → 解放。
    """
    if not info.get("refine_cell", True):
        return False
    if threshold is None:
        return True
    if fraction is None:
        return True
    return fraction >= threshold


def _apply_stage(
    gpx, hists, phases, phase_infos, atom_flag_maps, radiations, stage, fixed_profile=None,
    auto_freeze_minor_cells: float | None = None,
) -> list[str]:
    """段階の宣言的フラグを GSAS-II 精密化フラグへ翻訳して適用する (enable のみ)。

    revert は .gpx スナップショット復元で行うため、ここでは有効化だけを担う。
    原子フラグは GSAS-II が「置換」セマンティクスのため、per-atom の累積マップを毎回設定する。
    `fixed_profile[i]=True` のヒストグラムは装置プロファイル (U,V,W/X,Y/SH·L) を解放しない (Issue #38)。

    :param auto_freeze_minor_cells: 分率連動の自動セル凍結閾値 (Issue #80)。**basis は Scale**
        (``_phase_fraction_map``; wt% ではない — `_should_refine_cell` 参照)。None で無効
        (従来動作)。有効時は "cell" 段の適用時点で ``_phase_fraction_map`` により**その時点の
        live な** g2phases/g2hists から相分率を取得し (フラグ解放前の直近値; 分率段が未実行の
        単相/初期状態では 1.0 または初期 Scale)、閾値未満の相のみ自動凍結する。
    :returns: この呼び出しで自動閾値により凍結された相名のリスト (手動凍結は含まない;
        cell 段以外や凍結なしなら空リスト)。ledger/StageResult で挙動を可視化するため。
    """
    auto_frozen: list[str] = []
    if fixed_profile is None:
        fixed_profile = [False] * len(hists)
    flags = stage.flags
    # 【凍結 (freeze_others)】: 段のフラグは既定で**累積 (enable のみ)** なので、一度解放した
    #   パラメータは以降ずっと自由 = 「段を分けた」だけでは相関は切れない。"本気フィット" の
    #   順次解放/凍結手順 (1 つ解放 → 精密化 → 凍結 → 次) を表現するために、段の適用前に
    #   **既存の解放を一旦落とす**。値に名前の列を与えるとそれらは凍結しない (例 cell を
    #   常時解放へ移行したあと)。背景/スケールは常時解放の前提なので対象外。
    keep = flags.get("freeze_others")
    if keep:
        keep_names = set(keep) if isinstance(keep, (list, tuple, set)) else set()
        _freeze_all(hists, phases, atom_flag_maps, radiations, keep_names)
    if "background" in flags:
        bg = flags["background"]
        default_n = int(bg.get("coeffs", 6))  # type: ignore[union-attr]
        by_index = bg.get("by_index", {})  # type: ignore[union-attr]
        bg_type = bg.get("type")  # type: ignore[union-attr]
        # ヒストグラム毎に背景項数を設定 (ND は正規化 TOF で背景が支配的なため過剰項を避け少なめに)。
        for i, hist in enumerate(hists):
            n = int(by_index.get(i, default_n))
            spec = {"no. coeffs": n, "refine": True}
            if bg_type is not None:
                spec["type"] = bg_type
            hist.set_refinements({"Background": spec})
    # scale: GSAS-II はヒストグラムスケールを既定で精密化するため単相では no-op。
    if "cell" in flags:
        # 【凍結 (cell: False)】: 段のフラグは既定で**累積 (enable のみ)** なので、一度解放した
        #   格子は以降の段でも自由なまま = 「段を分けた」だけでは相関は切れない。試料変位のように
        #   格子と強く相関するパラメータを**交互に**精密化する (cell → shift(cell 凍結) → cell)
        #   には明示的な凍結が要る。値 False の cell 段は全相の Cell 解放を落とす。
        if flags["cell"] is False:
            for ph in phases:
                ph.set_refinements({"Cell": False})
            return auto_frozen
        # refine_cell=False の相 (副相/不純物の格子固定, Issue #47) は Cell 解放をスキップする。
        # auto_freeze_minor_cells 有効時は加えて、この段階適用時点の live な相分率
        # (_phase_fraction_map, Issue #80) が閾値未満の相も自動でスキップする (手動 > 自動)。
        fraction_map: dict[str, float] | None = None
        if auto_freeze_minor_cells is not None:
            try:
                fraction_map = _phase_fraction_map(phases, hists)
            except Exception:  # noqa: BLE001 — 分率抽出不能は fail open (凍結しない)
                fraction_map = None
        for ph, info in zip(phases, phase_infos):
            fraction = fraction_map.get(ph.name) if fraction_map else None
            if _should_refine_cell(info, fraction, auto_freeze_minor_cells):
                ph.set_refinements({"Cell": True})
            elif info.get("refine_cell", True) and fraction is not None:
                # 手動凍結ではなく自動閾値により凍結された相のみ記録する。
                auto_frozen.append(ph.name)
    if "displacement" in flags:
        mapping = flags["displacement"]
        for idx, keys in mapping.items():  # type: ignore[union-attr]
            if 0 <= idx < len(hists):
                hists[idx].set_refinements({"Sample Parameters": list(keys)})
    if "profile" in flags:
        # フラグ値がキー列なら**そのキー集合**を解放する (分解能抽出で U,V,W,X,Y を同時解放して
        # 相関局所解を脱出するため; GSAS set_refinements は Instrument Parameters を置換するので
        # 別段階に分けると先の U,V,W が凍結される)。True/未指定なら CW 既定 U,V,W (build_recipe 互換)。
        pf = flags["profile"]
        for i, hist in enumerate(hists):
            rad = radiations[i] if i < len(radiations) else Radiation.XRAY_LAB
            # TOF の装置プロファイル (sig/alpha/beta) はキャリブレーション依存のため精密化しない。
            # TOF のピーク形状は最後の size/mustrain (HAP) で処理する (チュートリアル T4 準拠)。
            if rad.is_tof or fixed_profile[i]:
                continue
            keys = list(pf) if isinstance(pf, (list, tuple)) else _profile_keys(rad)
            hist.set_refinements({"Instrument Parameters": keys})
    if "absorption" in flags:
        # 試料吸収を解放する opt-in 段階。TOF 中性子は λ(=TOF) 依存吸収でピーク強度の d 依存を補正
        # (Cu/Fe 等の吸収)。既定レシピ非搭載。悪化時は本段階ごと revert。
        for hist in hists:
            hist.set_refinements({"Sample Parameters": ["Absorption"]})
    if "tof_profile" in flags:
        # TOF 装置プロファイル (sig/alpha/beta) を較正する opt-in 段階。既定レシピには含めない
        # (T4 非回帰)。近似 instprm 初期値を実測へ寄せ ND フィットを改善する。悪化時は本段階ごと revert。
        # フラグ値がリストならそのキー集合、True なら既定キー (_tof_profile_keys)。
        tp = flags["tof_profile"]
        keys = list(tp) if isinstance(tp, (list, tuple)) else _tof_profile_keys()
        for i, hist in enumerate(hists):
            rad = radiations[i] if i < len(radiations) else Radiation.XRAY_LAB
            if not rad.is_tof:
                continue
            hist.set_refinements({"Instrument Parameters": keys})
    if "preferred_orientation" in flags:
        # 選択配向 (preferred orientation) を解放する opt-in 段階。既定レシピには含めない。
        # 値が偶数なら球面調和 (SH) その次数、1 なら March-Dollase、True なら SH order 4。PBA 等の
        # 系統的ピーク強度ズレ (obs>calc) を配向分布で吸収する。悪化時は本段階ごと revert。
        val = flags["preferred_orientation"]
        order = 4 if val is True else int(val)
        for ph in phases:
            try:
                ph.HAPvalue("Pref.Ori.", order)
            except Exception:
                pass
            ph.set_HAP_refinements({"Pref.Ori.": True}, histograms=list(hists))
    if "profile_lorentzian" in flags:
        # Lorentzian (X,Y) + Zero を X 線に追加解放する (別段階, revert ガード)。実験室/放射光 X 線は
        # Lorentzian 成分が支配的で U,V,W だけでは実測ピーク形状に合わない (CaTeO3: 43%→13%)。悪化時は
        # 本段階ごと revert され U,V,W は保持される (T3/T4 非回帰)。TOF/中性子は除外。
        for i, hist in enumerate(hists):
            rad = radiations[i] if i < len(radiations) else Radiation.XRAY_LAB
            if rad.is_tof or rad.is_neutron or fixed_profile[i]:
                continue
            hist.set_refinements({"Instrument Parameters": ["X", "Y", "Zero"]})
    if "profile_asymmetry" in flags:
        # 軸発散非対称 (SH/L) を X 線に別段階で追加解放する (分割擬フォークト相当の経験的ピーク形状;
        # 物理解釈を要さない)。低角の非対称に効くが常には改善しないため X,Y,Zero とは分け、悪化時は
        # 本段階のみ revert する (X,Y,Zero を保持)。TOF/中性子は除外。
        for i, hist in enumerate(hists):
            rad = radiations[i] if i < len(radiations) else Radiation.XRAY_LAB
            if rad.is_tof or rad.is_neutron or fixed_profile[i]:
                continue
            hist.set_refinements({"Instrument Parameters": ["SH/L"]})
    if "size_strain" in flags:
        # サイズ/微小歪みは分解能の低い CW 中性子 (例 D1a) を多ヒストグラム時に除外し、
        # X 線/放射光・TOF (高分解能) に張る。理由: 低分解能 CW 中性子の幅は器械分解能に
        # 支配され試料由来の情報が乏しく、joint で張ると過剰母数化してフィットを希釈する
        # (T3 実測: X線+CW中性子で CW 中性子を外すと 8.4%→6.7%)。一方 TOF POWGEN は高分解能で
        # 試料ピーク幅情報を持つため張る (T4)。単一 or 全て CW 中性子なら全ヒストグラムに張る (T2)。
        # フラグ値が文字列なら mustrain type を選択 (isotropic/uniaxial/generalized)。True は既定
        # isotropic (後方互換)。**異方 (uniaxial/generalized) は X 線に限定**する: 中性子 (特に TOF)
        # はピーク幅が装置分解能関数 (difC/sig/alpha/beta) に支配され異方 mustrain を分離できず発散する
        # (NaCuHCF·nD₂O iMATERIA 実測: ND 一般化 mustrain で ND Rwp 15→51%・係数 0 崩壊)。
        val = flags["size_strain"]
        allowed = {"isotropic", "uniaxial", "generalized"}
        mtype = val if (isinstance(val, str) and val in allowed) else "isotropic"
        non_lowres = [
            h for h, r in zip(hists, radiations) if r is not Radiation.NEUTRON_CW
        ]
        if mtype == "isotropic":
            targets = non_lowres if (non_lowres and len(hists) > 1) else list(hists)
        else:
            # 異方 mustrain は X 線ヒストグラムに限定 (中性子は分離不能で発散するため除外)。
            # X 線が無ければ従来の non_lowres へフォールバック (revert ガードが最終的な安全網)。
            xray = [h for h, r in zip(hists, radiations) if r.is_xray]
            targets = xray or (non_lowres if (non_lowres and len(hists) > 1) else list(hists))
        for ph in phases:
            ph.set_HAP_refinements(
                {
                    "Size": {"type": "isotropic", "refine": True},
                    "Mustrain": {"type": mtype, "refine": True},
                },
                histograms=targets,
            )
    if "hydrostatic_strain" in flags:
        # ヒストグラム間の温度差を per-histogram の静水圧歪み Dij で吸収する (REQ-103)。
        # 格子は共有したまま各ヒストグラムに独立の実効格子ずれを許す。
        for ph in phases:
            ph.set_HAP_refinements({"HStrain": True})
    if "phase_fraction_sum" in flags:
        # 多相の相分率 (HAP Scale) を全ヒストグラムで解放する。和=1 制約は _setup_constraints で登録済み。
        for ph in phases:
            ph.set_HAP_refinements({"Scale": True}, histograms=list(hists))
    # 原子フラグ (per-atom, 累積)
    for ph, info, fmap in zip(phases, phase_infos, atom_flag_maps):
        if _update_atom_flags(fmap, info, flags):
            active = {lab: fl for lab, fl in fmap.items() if fl}
            if active:
                ph.set_refinements({"Atoms": active})
    return auto_frozen


def _bound_occupancy(gpx, frac: str) -> None:
    """占有率パラメータを物理範囲 [0,1] に登録拘束する (GSAS-II parmMin/parmMax)。

    範囲外へ出た占有率は GSAS-II が境界で凍結する (dropOOBvars)。部分占有水など**単独解放**
    (free_occupancy_labels) の占有率が [0,1] を外れるのを防ぐ。

    注意: **占有率和=1 (add_EqnConstr) を張った共有サイトには効かない**。和=1 拘束下では GSAS-II は
    個々の Afrac でなく制約生成変数を varyList に入れるため、個別 Afrac の parmMin/parmMax は
    freeze 判定に載らない (NaCuHCF の Na2/O1 は和=1 のため境界を超えても凍結されない)。共有サイトの
    非物理占有は**正しいモデル選択で解消する**のが本筋 (model5→model6 で Ow が過剰密度を吸収し物理化)。
    """
    try:
        gpx.set_Controls("parmMin", 0.0, variable=frac)
        gpx.set_Controls("parmMax", 1.0, variable=frac)
    except Exception:
        # 古い GSAS-II で parmMin/parmMax 未対応でも精密化自体は継続させる (ガードのみ諦める)。
        pass


def _apply_profile_bounds(gpx, histograms) -> None:
    """`HistogramSpec.profile_bounds` を GSAS parmMin/parmMax に登録する (Issue #38 拘束抽出)。

    装置パラメータの変数名は ``:{hist_index}:{key}`` (例 ``:0:X``)。片側 None は登録しない。
    分解能抽出で U,W,X,Y≥0 を課し、相関非物理解 (負の Lorentzian) を避け転写可能な分解能を得る。
    古い GSAS で parmMin/parmMax 未対応でも精密化継続 (拘束のみ諦める, `_bound_occupancy` 流儀)。
    """
    for i, h in enumerate(histograms):
        bounds = getattr(h, "profile_bounds", None)
        if not bounds:
            continue
        for key, (lo, hi) in bounds.items():
            var = f":{i}:{key}"
            try:
                if lo is not None:
                    gpx.set_Controls("parmMin", float(lo), variable=var)
                if hi is not None:
                    gpx.set_Controls("parmMax", float(hi), variable=var)
            except Exception:  # noqa: BLE001 — 拘束未対応でも継続
                pass


def _plan_box_bounds(
    g2phases, g2hists, histograms, stab: StabilityOptions
) -> "tuple[BoxBound, ...]":
    """`StabilityOptions` の箱拘束設定を GSAS 変数名つきの箱へ展開する (REQ-SAR-201)。

    展開に必要な「相 id / ヒストグラム id / 初期格子 / 宣言ジオメトリ」は GSAS オブジェクトと
    spec の両方に散っているため、engine 側で束ねて `bounds` の純関数へ渡す
    (`bounds` モジュールは GSAS を一切知らない = テストが `-m "not gsas"` で回る)。

    **構造パラメータ (占有率・Uiso・座標) は決して含めない** (P-SAR-1)。
    """
    planned: list[BoxBound] = []
    for i, ph in enumerate(g2phases):
        pid = getattr(ph, "id", i)
        if stab.bound_cell is not None:
            try:
                cell = ph.get_cell()
                cell6 = [
                    float(cell[k])
                    for k in (
                        "length_a", "length_b", "length_c",
                        "angle_alpha", "angle_beta", "angle_gamma",
                    )
                ]
            except (KeyError, TypeError, ValueError, AttributeError):
                cell6 = []  # 格子が読めない相は箱なし (fail open)
            if cell6:
                planned.extend(cell_box_bounds(pid, cell6, stab.bound_cell))
        if stab.bound_size_strain:
            for j, hist in enumerate(g2hists):
                hid = getattr(hist, "id", j)
                planned.extend(
                    size_strain_box_bounds(
                        pid,
                        hid,
                        min_size=stab.min_size,
                        max_size=stab.max_size,
                        min_mustrain=stab.min_mustrain,
                        max_mustrain=stab.max_mustrain,
                    )
                )
    if stab.bound_displacement is not None:
        for j, hist in enumerate(g2hists):
            hid = getattr(hist, "id", j)
            spec = histograms[j] if j < len(histograms) else None
            bragg = getattr(spec, "geometry", None) is not Geometry.DEBYE_SCHERRER
            planned.extend(
                displacement_box_bounds(
                    hid, stab.bound_displacement, bragg_brentano=bragg
                )
            )
    return tuple(planned)


def _apply_box_bounds(gpx, planned: "Sequence[BoxBound]") -> "tuple[BoxBound, ...]":
    """箱を GSAS の ``parmMin``/``parmMax`` へ登録する (REQ-SAR-201)。

    ⚠ **これは最適化中の制約ではない**: `GSASIIstrMain.dropOOBvars` が精密化**後**に
    「範囲外なら境界へ丸めて ``parmFrozen`` へ追加」する事後処理である。したがって拘束は
    発散を*防ぐ*のではなく*止める*。止めた事実は `detect_bound_hits` が所見にする
    (REQ-SAR-202 — 握り潰さない)。

    古い GSAS で parmMin/parmMax 未対応でも精密化は継続する (`_bound_occupancy` 流儀)。

    :returns: **実際に登録できた側だけ**を持つ箱。片側の登録に失敗しても、成功した側は
        境界検出の対象に残す — 登録された箱で凍結が起きたのに所見が出ない (= 検出できない
        失敗を作る, P-SAR-2) のを避けるため。両側とも失敗した箱は落とす
        (張っていない箱の「境界到達」は報告しない)。
    """
    applied: list[BoxBound] = []
    for b in planned:
        lo, hi = None, None
        if b.lo is not None:
            try:
                gpx.set_Controls("parmMin", float(b.lo), variable=b.variable)
                lo = b.lo
            except Exception:  # noqa: BLE001 — 未対応/解釈不能な変数名は当該側のみ諦める
                pass
        if b.hi is not None:
            try:
                gpx.set_Controls("parmMax", float(b.hi), variable=b.variable)
                hi = b.hi
            except Exception:  # noqa: BLE001
                pass
        if lo is None and hi is None:
            continue
        applied.append(BoxBound(variable=b.variable, lo=lo, hi=hi, kind=b.kind, reason=b.reason))
    return tuple(applied)


def _frozen_variables(gpx) -> "set[str]":
    """``Controls['parmFrozen']['FrozenList']`` を文字列集合として読む。

    境界到達 (REQ-SAR-202) の検出源。`GSASIIstrMain.dropOOBvars` は箱の外へ出た変数を
    ここへ追加する。**esd プルーニング (REQ-SAR-103) も同じリストへ書く**ため、呼び出し側は
    「箱を張った変数だけ」に絞り (`detect_bound_hits`)、さらに**自分が凍らせた名前を差分の
    基準側へ入れる** (`_bound_hit_baseline`) ことで取り違えを避ける。
    """
    try:
        return {str(v) for v in gpx.get_Frozen()}
    except Exception:  # noqa: BLE001 — 未対応/未初期化は「凍結なし」へ縮退 (fail open)
        return set()


def _bound_hit_baseline(
    frozen_before: "Iterable[str]", rescue_frozen: "Iterable[str]"
) -> "set[str]":
    """境界到達の差分基準 = 精密化前の凍結集合 ∪ **自分が救済で凍らせた変数** (REQ-SAR-202)。

    `detect_bound_hits` は「箱を張った変数が新たに凍結された」を境界到達と読むが、救済
    プルーニング (REQ-SAR-103) は**同じ ``parmFrozen`` へ書く**うえ、その凍結対象は箱付きの
    変数と名前空間が重なる (``0::A0`` / ``:0:Shift`` / ``0:0:Size;i`` はいずれも弱くなり得る)。
    救済は精密化呼び出しの**後**に走るので、素の ``frozen_before`` と突き合わせると
    **自分で凍らせた変数を「箱の外へ出た」と誤報する** — 箱もモデルも正しいのに
    「箱が間違っている」と読める所見が出る、最悪の静かな嘘になる。

    救済で凍らせた名前を基準側へ入れることで、救済の再精密化サイクル中に**本当に**箱の外へ
    出た変数 (別名) は引き続き拾える (窓を狭めるのではなく、帰属の判っている分だけ除く)。
    """
    return set(frozen_before) | set(rescue_frozen)


def _equiv_positions(gpx, pid, idxs) -> None:
    """原子群の座標 (dAx/dAy/dAz shift) を等値拘束する (共有サイト/共位置を保つ)。

    GSAS-II の座標精密化は shift 変数 (dAx 等) で行うため、shift を等値にすれば共位置の原子が
    同じだけ動き相対位置を保つ (初期共位置が前提)。特殊位置で解放座標が無い成分は GSAS 側で無視される。
    """
    if len(idxs) < 2:
        return
    for coord in ("dAx", "dAy", "dAz"):
        try:
            gpx.add_EquivConstr([f"{pid}::{coord}:{i}" for i in idxs])
        except Exception:
            pass


def _setup_constraints(gpx, g2phases, g2hists, specs) -> None:
    """占有率和=1・Uiso 等価 (混合占有) と相分率和=1 (多相) の制約を登録する (REQ-102/104)。

    占有率和=1 (add_EqnConstr) がないと占有率解放が発散し、Uiso 等価 (add_EquivConstr) が
    ないと少数占有原子の Uiso が発散する (T2 実測)。混合占有・単独解放の占有率は物理範囲 [0,1] に
    拘束する。多相では各ヒストグラムで相分率和=1 を課す。
    """
    # 混合占有: 占有率和=1 + Uiso 等価 + [0,1] 拘束。単独解放 (free_occ) も [0,1] 拘束。
    for ph, spec in zip(g2phases, specs):
        atoms = ph.data["Atoms"]
        ct = ph.data["General"]["AtomPtrs"][1]
        label_to_idx = {row[ct - 1]: i for i, row in enumerate(atoms)}
        pid = ph.id
        for group in spec.mixed_occupancy_groups:
            idxs = [label_to_idx[lab] for lab in group if lab in label_to_idx]
            if len(idxs) < 2:
                continue
            fracs = [f"{pid}::Afrac:{i}" for i in idxs]
            uisos = [f"{pid}::AUiso:{i}" for i in idxs]
            gpx.add_EqnConstr(1.0, fracs, [1.0] * len(fracs))
            gpx.add_EquivConstr(uisos)
            for frac in fracs:
                _bound_occupancy(gpx, frac)
            # 共有サイトは共位置: 座標 (dAx/dAy/dAz) も等値拘束する。
            _equiv_positions(gpx, pid, idxs)
        # 明示的な座標等値グループ (共位置 H/D 対など)。
        for group in spec.position_equiv_groups:
            pidx = [label_to_idx[lab] for lab in group if lab in label_to_idx]
            if len(pidx) >= 2:
                _equiv_positions(gpx, pid, pidx)
        for lab in spec.free_occupancy_labels:
            if lab in label_to_idx:
                _bound_occupancy(gpx, f"{pid}::Afrac:{label_to_idx[lab]}")
        # 占有率等値 (D₂O の D を親水 O に連動): add_EquivConstr で 1 変数に束ねる。
        for group in spec.occupancy_equiv_groups:
            idxs = [label_to_idx[lab] for lab in group if lab in label_to_idx]
            if len(idxs) >= 2:
                gpx.add_EquivConstr([f"{pid}::Afrac:{i}" for i in idxs])
        # 占有率和 (H/D ミキシング): (親, 子1, 子2, ...) で Σ子 − 親 = 0 を課す。
        for group in spec.occupancy_sum_groups:
            if len(group) < 2 or group[0] not in label_to_idx:
                continue
            parent = label_to_idx[group[0]]
            children = [label_to_idx[lab] for lab in group[1:] if lab in label_to_idx]
            if not children:
                continue
            variables = [f"{pid}::Afrac:{i}" for i in children] + [f"{pid}::Afrac:{parent}"]
            gpx.add_EqnConstr(0.0, variables, [1.0] * len(children) + [-1.0])

    # 多相: 各ヒストグラムで相分率 (HAP Scale) 和 = 1 (REQ-104)
    if len(g2phases) > 1:
        for hist in g2hists:
            hid = hist.id
            scales = [f"{ph.id}:{hid}:Scale" for ph in g2phases]
            gpx.add_EqnConstr(1.0, scales, [1.0] * len(scales))


def _apply_content_constraint(gpx, g2phases, g2hists, content_constraint) -> None:
    """相間の線形 Scale 拘束 Σ cᵢ·Scaleᵢ = 0 を登録する (FR-318 lock_fractions, T12)。🔵

    総アルカリ量拘束はモル量 ∝ Scaleᵢ·Zᵢ を使うと Scale について**線形**:
    ``Σ Scaleᵢ·Zᵢ·(xᵢ − x_total) = 0``。係数 ``cᵢ = Zᵢ·(xᵢ − x_total)`` を相名キーで受け取り、
    各ヒストグラムの Scale 変数へ `add_EqnConstr` する (相 id 混在の前例 = 相分率和=1)。

    ⚠ **2 相では和=1 と合わせ相分率が完全決定される** — XRD は分率に寄与しなくなり Rwp が
    一致度の検定量になる。既定モードにしない理由 (設計 Correction A)。**実行可能性
    (feasibility) と縮退 (xᵢ 等値) のゲートは呼び出し側の責務** (`operando.coulometry.feasibility`)
    — 本関数は機械的に登録するだけ。係数が全て ~0 (縮退) の場合のみ安全側で skip する。
    """
    if not content_constraint or len(g2phases) < 2:
        return
    for hist in g2hists:
        hid = hist.id
        variables: list[str] = []
        mults: list[float] = []
        for ph in g2phases:
            c = content_constraint.get(ph.name)
            if c is None or not math.isfinite(float(c)):
                continue
            variables.append(f"{ph.id}:{hid}:Scale")
            mults.append(float(c))
        if len(variables) >= 2 and any(abs(m) > 1e-12 for m in mults):
            gpx.add_EqnConstr(0.0, variables, mults)


def _apply_coord_jitter(
    g2phases, jitter_ang: "Mapping[str, float]", seed: int, getcsxinel=None
) -> int:
    """原子座標に**対称性を壊さない**初期摂動を掛ける (マルチスタートの構造軸)。

    Rietveld の局所解は主に**構造 (原子座標)** にあり、格子だけ振っても「格子のベイスンが
    1 つ」しか言えない。ここが Issue #13 で「原子座標摂動は M-later」と書かれていた欠落である。

    **対称性が自由な軸だけを動かす**。特殊位置の原子を動かすと空間群が壊れるので、
    `GetCSxinel` の 3 状態 (`atomrows.free_index_from_site_symmetry`) を見て:

    - ``0`` (対称拘束で固定) の軸は**触らない**
    - 正値が他軸と一致する (結束) 軸は**代表軸だけ**動かす — 従属軸は GSAS の等値拘束が追随する

    :param jitter_ang: 相名 → 変位の大きさ (**Å**)。分率にしないのは軸ごとに意味が変わるため
        (a=5Å と c=20Å では分率 0.01 の実距離が 4 倍違う)
    :param seed: 乱数種。同じ種なら何度実行してもビット同一 (NFR-102)
    :returns: **実際に動かした軸の総数**。0 は「この軸では試験していない」を意味し、
        呼び出し側はそれを傍証と呼んではならない (高対称構造では全軸が固定され得る)
    """
    if not jitter_ang:
        return 0
    if getcsxinel is None:
        try:
            from GSASII import GSASIIspc as G2spc

            getcsxinel = G2spc.GetCSxinel
        except Exception:  # noqa: BLE001 — GSAS 無しは「動かさない」へ縮退 (fail open)
            return 0
    rng = np.random.default_rng(seed)
    moved = 0
    for ph in g2phases:
        amp = jitter_ang.get(ph.name)
        if not amp or not math.isfinite(float(amp)) or float(amp) <= 0.0:
            continue
        try:
            atoms = ph.data["Atoms"]
            ptrs = ph.data["General"]["AtomPtrs"]
            cx, cs = int(ptrs[0]), int(ptrs[2])
            cell = ph.get_cell()
            lengths = (
                float(cell["length_a"]), float(cell["length_b"]), float(cell["length_c"])
            )
        except Exception:  # noqa: BLE001 — 構造が読めない相はスキップ
            continue
        for row in atoms:
            free = free_index_from_site_symmetry(getcsxinel, row[cs])
            seen: set[int] = set()
            for axis in range(3):
                fid = free[axis]
                if fid == 0 or fid in seen:
                    # 0 = 対称固定 / 既出 = 結束軸の従属側 (代表軸だけ動かす)
                    continue
                seen.add(fid)
                length = lengths[axis] if lengths[axis] > 0 else 1.0
                # Å の変位を当該軸の分率へ直す (軸長で割る)。一様 [-amp, +amp]。
                delta = float(rng.uniform(-1.0, 1.0)) * float(amp) / length
                try:
                    row[cx + axis] = float(row[cx + axis]) + delta
                except Exception:  # noqa: BLE001 — 書けない行はスキップ
                    continue
                moved += 1
    return moved


def _apply_initial_occupancies(g2phases, occupancies: Mapping[str, Mapping[str, float]]) -> None:
    """原子占有率を initial_occupancies で初期化する (FR-318 fix/warm-start 用, T8)。🔵

    `_apply_initial_fractions` (Scale シーダー) の占有率版。add_phase 直後・制約登録前に呼ぶ。
    値のみ差し替え、精密化フラグ (F) は触らない — **fix (凍結) は構造的に実現される**:
    原子がどの占有率グループ (`mixed_occupancy_groups`/`free_occupancy_labels` 等) にも属さなければ
    `_update_atom_flags` が F フラグを立てず、seed 値のまま固定される。逆に diagnose の
    warm-start では占有率グループ宣言と併用し、seed から精密化を出発させる。

    fail-open: 未知の相名/ラベル・非有限値は無視 (分率シーダーと同じ規律)。
    **範囲検証 ([0,1]) は `run_auto_rietveld` 冒頭で実施済み** (GSAS に触れる前に大声で失敗)。
    """
    if not occupancies:
        return
    for ph in g2phases:
        vals = occupancies.get(ph.name)
        if not vals:
            continue
        try:
            atoms = ph.data["Atoms"]
            cx, ct, _cs, _cia = ph.data["General"]["AtomPtrs"]
            label_to_idx = {str(row[ct - 1]): i for i, row in enumerate(atoms)}
        except Exception:  # noqa: BLE001 — 構造差は相ごとスキップ
            continue
        for lab, v in vals.items():
            idx = label_to_idx.get(str(lab))
            if idx is None or not math.isfinite(float(v)):
                continue
            atoms[idx][cx + 3] = float(v)


def _apply_bond_restraints(gpx, g2phases, bond_restraints) -> None:
    """相名→結合距離ソフト拘束を GSAS-II Bond restraint として登録する (O–H/D 漂流防止の意図)。

    ``ph.addDistRestraint`` は**現在座標**で origin×target の距離が ``[bond/factor, bond*factor]`` に入る
    対を探して登録するため、**初期座標が理想幾何のうちに呼ぶ**必要がある (呼出は精密化開始前)。
    拘束は gpx データツリーに保存され revert (スナップショット復元) 後も保持される。不正 spec・GSAS
    未対応・ラベル不一致は当該拘束のみスキップして継続する (EDGE)。

    **weight は相単位**: GSAS の ``setDistRestraintWeight`` が相全体の wtFactor を設定するため、同一相の
    複数 spec で異なる weight を与えても**最後に指定された値**が相全体に適用される (per-bond 重みは不可)。
    通常は同一相の全 spec に同じ weight を渡す。既定 1000.0。

    ⚠ **本バージョンの GSAS-II では headless 最小二乗で距離拘束として機能しない** (Issue #112,
    PbSO4 統制実験で確定)。``_apply_chem_comp_restraints`` と同根: ``GSASIIstrMath.errRefine`` が
    penalty 残差を ``if len(pVals) and dlg:`` (L5203) でゲートし headless (dlg=None) では χ² から
    除外する。``penaltyFxn``/``penaltyDeriv`` は Bond/Angle/ChemComp を共有処理するため Bond も
    同じゲート下。ChemComp が完全不動なのに対し Bond は HessRefine 経由 (Vec/Hess は非ゲート) で
    **小さな飽和摂動**を注入するが、距離ターゲットには追従しない (実測: ターゲット 1.9/2.3 Å で
    最終 S–O2 がビット同一・データ値近傍に留まる = target-invariant) — 距離拘束としては非機能で、
    むしろ Rwp を僅かに悪化させる。よって**登録はするが拘束効果は期待しないこと**。NaCuHCF の
    「ND 18→14.7% 頑健改善」(PR #42) は bond restraint でなく水 O/D の **U (ADP) 自由精密化** が
    主因だった (memo [nacuhcf-dh-determinability] と整合)。GSAS-II 更新で修復された場合に検知する
    カナリアが ``tests/autorietveld/test_charge_constraint_gsas.py::TestBondRestraintHeadlessCanary``
    (target-invariance が破れたら fail → 本 caveat と依存機能を再検証する)。
    """
    if not bond_restraints:
        return
    rroot = gpx.data.setdefault("Restraints", {"data": {}})
    rdata = rroot.setdefault("data", {})
    for ph in g2phases:
        specs = bond_restraints.get(ph.name)
        if not specs:
            continue
        # 相ごとの Bond 拘束ツリーを初期化 (addDistRestraint が参照する既定構造)。
        entry = rdata.setdefault(ph.name, {})
        entry.setdefault("Bond", {"wtFactor": 1.0, "Range": 1.1, "Bonds": [], "Use": True})
        weight = 1000.0  # 相単位 wtFactor (最後に指定された spec の weight を採用)
        for spec in specs:
            try:
                # 必須/任意キーの取り出しも try 内 (不正 spec は当該拘束のみスキップ)。
                origin = [str(a) for a in spec["origin"]]  # type: ignore[index]
                target = [str(a) for a in spec["target"]]  # type: ignore[index]
                dist = float(spec["distance"])  # type: ignore[index]
                esd = float(spec.get("esd", 0.02))  # type: ignore[union-attr]
                factor = float(spec.get("factor", 1.5))  # type: ignore[union-attr]
                weight = float(spec.get("weight", weight))  # type: ignore[union-attr]
                ph.addDistRestraint(origin, target, dist, factor=factor, ESD=esd)
            except Exception:  # noqa: BLE001 — 不正 spec/ラベル不一致/未対応はスキップし継続
                continue
        try:
            ph.setDistRestraintWeight(weight)
        except Exception:  # noqa: BLE001
            pass


def _apply_chem_comp_restraints(gpx, g2phases, chem_comp_restraints) -> None:
    """相名→組成 (ChemComp) ソフト拘束を GSAS-II Restraints ツリーへ直接注入する (FR-318 T10)。🔵

    GSAS-II 本体は化学組成拘束を実装している (`GSASIIstrMath` の penalty:
    ``calc = Σ mult·occ·factor`` vs ``obs`` を ``esd`` 重みで罰し、``Afrac`` 微分も持つ) が、
    scriptable API は Bond 拘束しか露出していない。そこで `_apply_bond_restraints` と同じ手口で
    ``gpx.data['Restraints']['data'][phase]['ChemComp']['Sites']`` へ
    ``[ranIds, factors, obs, esd]`` を直接書く。Restraints ツリーは gpx に保存されるため
    revert (スナップショット復元) 後も保持される (Bond と同じ性質)。

    ⚠ **本バージョンの GSAS-II では headless 最小二乗で restraint penalty が機能しない**
    (FR-318 実測, 3 経路で確認):

    1. 既定 (analytic Hessian, dlg=None): `errRefine` が penalty 項を ``if len(pVals) and dlg:``
       ゲート内で χ² に連結するため **目的関数から除外** — Marquardt は penalty を無視して
       データ解へ収束する (ChemComp 目標 3.2 [occ 0.8] vs 収束 occ 1.018, 重み 4e8 でも不動)。
    2. ダミー dlg 注入 (penalty を χ² に含める): `HessRefine` の penalty 勾配符号がデータ側と
       逆 (`Vec -=` vs データ `Vec +=`, dy=obs−calc は同一) のためステップが**逆方向** (occ
       1.0→1.2) に出て全ステップ棄却 → `Aborted: True` でロールバック。
    3. analytic Jacobian + ダミー dlg: shift/esd 0.000 (全パラメータ不動)。

    よって **soft モードは注入まで実装するが実質無効** — `insitu.charge.plan_frame_constraint`
    は soft を diagnose へ縮退させ警告する。GSAS-II 更新で修復された場合に検知するカナリアが
    `tests/autorietveld/test_charge_constraint_gsas.py::TestChemCompRestraint` (fail したら
    soft モードを再有効化する)。既存 `bond_restraints` も同じゲートの影響下にある (Issue 化)。

    **単位**: ``total`` は **セルあたり原子数** (Σ mult·occ·factor の目標値)。式単位あたり量 x を
    拘束したい場合は呼び出し側が ``x × Z`` に換算して渡す (①コアは GSAS ネイティブ単位)。

    各 spec: ``{"labels": [原子ラベル…], "total": セルあたり目標, "esd": 目標の esd,
    "factors": ラベル毎係数 (省略時 1.0), "weight": 相単位 wtFactor}``。
    不正 spec・ラベル不一致は当該拘束のみスキップして継続する (Bond と同じ縮退規律)。
    """
    if not chem_comp_restraints:
        return
    rroot = gpx.data.setdefault("Restraints", {"data": {}})
    rdata = rroot.setdefault("data", {})
    for ph in g2phases:
        specs = chem_comp_restraints.get(ph.name)
        if not specs:
            continue
        entry = rdata.setdefault(ph.name, {})
        cc = entry.setdefault("ChemComp", {"wtFactor": 1.0, "Sites": [], "Use": True})
        try:
            atoms = ph.data["Atoms"]
            _cx, ct, _cs, cia = ph.data["General"]["AtomPtrs"]
            # ChemComp の ids は**原子 ranId** (row[cia+8])。行 index ではない。
            label_to_ranid = {str(row[ct - 1]): row[cia + 8] for row in atoms}
        except Exception:  # noqa: BLE001 — 構造差は相ごとスキップ
            continue
        weight = 1.0
        for spec in specs:
            try:
                labels = [str(x) for x in spec["labels"]]  # type: ignore[index]
                total = float(spec["total"])  # type: ignore[index]
                esd = float(spec.get("esd", 0.1))  # type: ignore[union-attr]
                factors = [
                    float(f)
                    for f in spec.get("factors", [1.0] * len(labels))  # type: ignore[union-attr]
                ]
                weight = float(spec.get("weight", weight))  # type: ignore[union-attr]
                if len(factors) != len(labels):
                    continue
                ids = [label_to_ranid[lab] for lab in labels]
                cc["Sites"].append([ids, factors, total, esd])
            except Exception:  # noqa: BLE001 — 不正 spec/ラベル不一致はスキップし継続
                continue
        cc["wtFactor"] = weight
        cc["Use"] = True


@dataclass(frozen=True)
class AtomMaps:
    """`_atom_result_maps` の戻り値 — **タプルではなく dataclass** にしてある理由。

    元は 4 要素タプルで、事前警告の呼び出し側が ``_, uiso_init, _, _ = ...`` と位置で
    受けていた。座標/座標 esd/自由度指標/Uiso esd を足して 8 要素にすると、次に 9 要素目を
    足した人が**位置をずらして静かに別の値を読む**。名前で受ければその事故が起きない。
    """

    occupancy: dict[str, dict[str, float]]
    uiso: dict[str, dict[str, float]]
    multiplicity: dict[str, dict[str, float]]
    occupancy_esd: dict[str, dict[str, "float | None"]]
    coords: dict[str, dict[str, tuple[float, float, float]]]
    coord_esd: dict[str, dict[str, CoordEsd]]
    coord_free_index: dict[str, dict[str, tuple[int, int, int]]]
    uiso_esd: dict[str, dict[str, "float | None"]]


def _atom_result_maps(g2phases, *, getcsxinel=None) -> AtomMaps:
    """ラベルキーの原子パラメータを抽出する (FR-318 T7/T11 + 構造一致判定の土台)。🔵

    `AutoRietveldResult.atom_occupancy`/`atom_uiso` は宣言されながら未配線だった
    (`_extract_state` は validity 用の位置リストしか作らない)。本関数がラベルキーで充填する。

    esd は `diagnostics.read_variable_esds` 経由で引く (``depSigDict`` を第一情報源にする唯一の
    実装)。**得られなかった変数は写像に載らない**ので、載っていないこと自体が「決まっていない」
    の信号になる — 呼び出し側が第 2 の規則を持たなくてよい。占有率/Uiso は 2 状態
    (``>0.0``/``None``)、座標は 3 状態 (対称固定の ``0.0`` を含む, `atomrows.coord_esd_states`)。

    抽出不能は当該相をスキップし例外を送出しない。⚠ **自由度指標の失敗で相を落としてはならない**
    — `GetCSxinel` は sytsym 名の変更で KeyError を出すことがあり (GSAS 自身が
    `GSASIIstrIO.py:1746-1749` でその場パッチしている)、それが相ごとの ``except`` に届くと
    その相の ``uiso`` まで落ちて `check_initial_uiso` が黙って弱まる。実際の防御は
    `atomrows.free_index_from_site_symmetry` の内部縮退にあり、ここで try を重ねる必要はない。

    :param getcsxinel: `GSASIIspc.GetCSxinel` の注入シーム (None で遅延 import)。
        **テストがこの機械に GSAS が入っているかで結果を変えないため**に必須の引数である —
        注入が無いと、GSAS 有りの環境では実関数が走り無しの環境では縮退経路が走るので、
        同じテストが CI とローカルで別の答えを出す (CI 導入時に 44 件が踏んだ穴と同型)。
    """
    occ: dict[str, dict[str, float]] = {}
    uiso: dict[str, dict[str, float]] = {}
    mult: dict[str, dict[str, float]] = {}
    occ_esd: dict[str, dict[str, float | None]] = {}
    coords: dict[str, dict[str, tuple[float, float, float]]] = {}
    coord_esd: dict[str, dict[str, CoordEsd]] = {}
    free_index: dict[str, dict[str, tuple[int, int, int]]] = {}
    uiso_esd: dict[str, dict[str, float | None]] = {}
    if getcsxinel is None:
        try:
            from GSASII import GSASIIspc as G2spc

            getcsxinel = G2spc.GetCSxinel
        except Exception:  # noqa: BLE001 — GSAS 無しは一般位置判定へ縮退 (fail open)

            def getcsxinel(_sym):  # type: ignore[misc]
                raise KeyError("GSASIIspc unavailable")

    for ph in g2phases:
        try:
            atoms = ph.data["Atoms"]
            ptrs = ph.data["General"]["AtomPtrs"]
            cs = int(ptrs[2])
            try:
                esds = read_variable_esds(ph.proj)
            except Exception:  # noqa: BLE001 — 共分散なしは「未精密化」に縮退
                esds = {}
            lookup = esds.get
            pid = ph.id
            p_occ: dict[str, float] = {}
            p_uiso: dict[str, float] = {}
            p_mult: dict[str, float] = {}
            p_occ_esd: dict[str, float | None] = {}
            p_coords: dict[str, tuple[float, float, float]] = {}
            p_coord_esd: dict[str, CoordEsd] = {}
            p_free: dict[str, tuple[int, int, int]] = {}
            p_uiso_esd: dict[str, float | None] = {}
            for i, row in enumerate(atoms):
                info = atom_row(row, ptrs)
                label = info.label
                p_occ[label] = info.occupancy
                p_mult[label] = info.multiplicity
                p_coords[label] = info.coords
                if info.uiso is not None:
                    p_uiso[label] = info.uiso
                    p_uiso_esd[label] = lookup(f"{pid}::AUiso:{i}")
                p_occ_esd[label] = lookup(f"{pid}::Afrac:{i}")
                # `GetCSxinel` の失敗は `free_index_from_site_symmetry` が内部で吸って
                # 保守的な縮退値を返す (ここで try を重ねても到達しない)。相ごとの
                # ``except`` に巻き込まれず uiso が生き残ることは
                # `test_a_failing_getcsxinel_does_not_drop_the_phase` が振る舞いで固定する。
                fi = free_index_from_site_symmetry(getcsxinel, row[cs])
                p_free[label] = fi
                p_coord_esd[label] = coord_esd_states(
                    fi, pid=pid, index=i, esd_lookup=lookup
                )
            occ[ph.name] = p_occ
            uiso[ph.name] = p_uiso
            mult[ph.name] = p_mult
            occ_esd[ph.name] = p_occ_esd
            coords[ph.name] = p_coords
            coord_esd[ph.name] = p_coord_esd
            free_index[ph.name] = p_free
            uiso_esd[ph.name] = p_uiso_esd
        except Exception:  # noqa: BLE001 — 構造差/抽出失敗は当該相をスキップし継続
            continue
    return AtomMaps(
        occupancy=occ,
        uiso=uiso,
        multiplicity=mult,
        occupancy_esd=occ_esd,
        coords=coords,
        coord_esd=coord_esd,
        coord_free_index=free_index,
        uiso_esd=uiso_esd,
    )


def _profile_esd_map(g2hists) -> tuple[dict[str, "float | None"], ...]:
    """ヒストグラム毎のプロファイル項 esd (索引順)。**2 状態** (``>0.0``/``None``)。

    ⚠ GSAS の装置変数名は ``:{hist.id}:{key}`` であって列挙索引ではない。単一プロジェクトでは
    一致するので既存の `_apply_profile_bounds` (enumerate 索引を使用) は実害を出していないが、
    ここは読み取りなので実 id を使う。
    """
    out: list[dict[str, float | None]] = []
    for h in g2hists:
        row: dict[str, float | None] = {}
        try:
            esds = read_variable_esds(h.proj)
            inst = h.data["Instrument Parameters"][0]
            hid = h.id
            for key in _PROFILE_INTROSPECT_KEYS:
                if key in inst:
                    row[key] = esds.get(f":{hid}:{key}")
        except Exception:  # noqa: BLE001 — 抽出不能は空 dict (EDGE-001 と同じ縮退)
            row = {}
        out.append(row)
    return tuple(out)


def _extract_state(phases):
    """validity 用に各相の格子/Uiso/占有率を GSAS-II から抽出する。"""
    refined_cells = {}
    uiso = {}
    occ = {}
    for ph in phases:
        cell = ph.get_cell()
        refined_cells[ph.name] = (
            float(cell["length_a"]),
            float(cell["length_b"]),
            float(cell["length_c"]),
            float(cell["angle_alpha"]),
            float(cell["angle_beta"]),
            float(cell["angle_gamma"]),
        )
        atoms = ph.data["Atoms"]
        cx, ct, cs, cia = ph.data["General"]["AtomPtrs"]
        occ[ph.name] = [float(row[cx + 3]) for row in atoms]
        uvals = []
        for row in atoms:
            if row[cia] == "I":
                uvals.append(float(row[cia + 1]))
        uiso[ph.name] = uvals
    return refined_cells, uiso, occ


def _phase_fraction_map(g2phases, g2hists) -> dict[str, float]:
    """相名→相分率 (先頭ヒストグラムの HAP Scale, 和=1 正規化) を返す (M9 逐次解析用)。

    単相は {name: 1.0}。多相は HAP Scale を抽出し総和で正規化する (和=1 制約下では概ね規格化済み)。
    抽出失敗の相は 0.0 を入れる。名前重複時は後勝ち (相名は一意想定)。
    """
    if not g2phases:
        return {}
    if len(g2phases) == 1:
        return {g2phases[0].name: 1.0}
    fracs = _extract_phase_fractions(g2phases, g2hists)  # g2phases 順に整列
    total = sum(f for f in fracs if math.isfinite(f) and f > 0)
    out: dict[str, float] = {}
    for ph, f in zip(g2phases, fracs):
        val = float(f) if math.isfinite(f) else 0.0
        out[ph.name] = (val / total) if total > 0 else 0.0
    return out


def _finite_or_zero(x: object) -> float:
    """非有限 (NaN/inf) を 0.0 に落として float 化する (esd の JSON 安全化)。

    esd の 0.0 は GSAS-II の慣習で「精密化していない/不確かさ不明」を表す
    (`get_cell_and_esd` も共分散なしの場合 0.0 を返す)。算出不能を同じ表現へ寄せる。
    """
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def _weight_esd_or_none(x: object) -> float | None:
    """多相の重量分率 esd を純化する。**0.0 / 非有限 / 負は `None`**、正のみ値を残す (捏造防止)。

    **0.0 を捏造しない** (レビュー第6巡 HIGH — R5 の cell_esd と同型の再発): GSAS-II の
    `calcMassFracs` は相分率 (HAP Scale) が**最終精密化の共分散 varyList に無い**とき、当該
    ヒストグラムの**全相**の su を厳密に ``0.0`` にする (導関数ベクトル `Avec` が全 0 → sqrt(0))。
    これは「精密化して 0 に決まった」ではなく「**この精密化からは決まっていない**」を意味する。

    実測 (K₂Mn[Fe(CN)₆] M10 双方向解析 `publication_m10.csv`): fr213 は直前 fr212 と重量分率が
    **完全一致** (0.80115/0.19885) で su だけ 0.0、fr224 も fr223 と一致で su 0.0 — 全段 revert
    (warm-start 種のまま) で共分散に Scale が残らなかったフレームである。素通しすると
    ``wt = 0.199(0)`` = 無限精度の捏造が出版経路 (`phase_weight_fraction_esd`) へ流れる。

    **多相の real な決定では su>0 が保証される** (両分率が (0,1) にあれば `Avec` は非零・共分散の
    Scale 部分は正定値) ため、多相で su==0.0 は一意に「未決定」を指す。単相の自明な ``0.0``
    (`_weight_fraction_maps` の早期 return) は本関数を通さないので影響しない。
    """
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0.0:
        return None
    return v


#: `G2Phase.get_cell_and_esd()` の esd dict のキー (`refined_cells` と同じ a,b,c,α,β,γ 順)。
_CELL_ESD_KEYS = (
    "length_a", "length_b", "length_c", "angle_alpha", "angle_beta", "angle_gamma",
)
#: 逆格子計量テンソル項 `<pId>::A0..A5`。GSAS が格子を精密化するときの**実際の変数名**。
_CELL_A_TERMS = tuple(f"A{i}" for i in range(6))


def _cell_was_refined(ph) -> bool:
    """この相の格子が**最後に受理された精密化で実際に変数だったか**を Covariance から判定する。

    **典拠**: GSAS は格子を逆格子計量テンソル項 ``<pId>::A0..A5`` として精密化し、その名前は
    ``Covariance/data/varyList`` に載る。esd を作る `G2lat.getCellEsd` 自身が
    ``getVCov(RMnames, varyList, covMatrix)`` を引く — つまり **varyList に無い A 項の分散は 0** に
    なる。よって「varyList に A 項があるか」は「GSAS が esd を計算し得たか」と**厳密に同値**であり、
    `_cell_esd_map` の 0.0 が「精密化して 0」なのか「精密化していない」なのかを分ける authoritative
    な情報源である。

    **エンジン側の記録 (`refine_cell` / `auto_frozen`) を使わない理由**: 段階が revert されると
    gpx はセル解放前のスナップショットへ戻る (= 報告されるセルは入力 CIF 値のまま) が、
    エンジン側の「解放しようとした」という記録は残る。varyList は**報告するセルを実際に作った
    精密化**を指すため、revert を自動的に正しく扱う。

    判定不能 (Covariance 無し・構造差・未精密化) は **False** (= esd を主張しない) に倒す。
    捏造を防ぐのが目的なので、疑わしきは「無い」側が安全である。
    """
    try:
        cov = ph.proj["Covariance"]["data"]
        vary = {str(v) for v in (cov.get("varyList") or ())}
        pfx = f"{ph.id}::"
    except Exception:  # noqa: BLE001 — 共分散/構造差は「精密化していない」に縮退
        return False
    return any(f"{pfx}{term}" in vary for term in _CELL_A_TERMS)


def _cell_esd_map(g2phases) -> dict[str, CellEsd]:
    """相名→格子の標準不確かさ (a,b,c,α,β,γ) を GSAS-II の共分散から抽出する。

    出典 `G2Phase.get_cell_and_esd()` → (cellDict, esdDict)。両者は length_a/b/c・angle_alpha/beta/
    gamma・volume をキーに持つが、``refined_cells`` は**体積を含まない 6 要素**なので同一レイアウトへ
    揃える (体積 esd は落とす)。

    **0.0 を捏造しない** (レビュー第5巡 HIGH): `get_cell_and_esd()` は**凍結した格子でも例外を出さず
    全 0.0 を返す**ため、素通しすると「精密化して 0 に決まった」と読める値が出版経路へ流れる
    (実測: 論文用 CSV の `mono_a_esd=0.0` 192/192 フレーム・`cubic` 34/211 = `auto_freeze_minor_cells`
    が凍結した分)。よって `_cell_was_refined` で解放の有無を分け、**③ が 3 状態を区別できる**表現にする:

    | 状態 | 表現 |
    |---|---|
    | 解放して精密化した項 | ``>0.0`` (共分散由来の su) |
    | 解放したセルの**対称拘束項** | ``0.0`` — mono の α/γ は厳密に 90°。**真の陳述なので残す** |
    | 格子を解放していない相 | ``None`` × 6 (手動 `refine_cell=False` / `auto_freeze_minor_cells` / |
    |  | セル段が revert された / そもそも未精密化)。このデータからは決まっていない |
    | 抽出できなかった相 | **キーごと欠落** (`get_cell_and_esd()` が例外) |

    非有限 (NaN/inf) も ``None`` にする — 「値が無い」であって「厳密に 0」ではない。
    抽出不能な相はキーごと落とし、**例外は送出しない** (バックエンド失敗は結果へ縮退する不変条件)。
    """
    out: dict[str, CellEsd] = {}
    for ph in g2phases:
        try:
            _cell, esd = ph.get_cell_and_esd()
            if not _cell_was_refined(ph):
                out[ph.name] = (None, None, None, None, None, None)
                continue
            values = tuple(finite_or_none(esd[key]) for key in _CELL_ESD_KEYS)
            out[ph.name] = values  # type: ignore[assignment]
        except Exception:  # noqa: BLE001 — 共分散欠落/キー欠落は当該相をスキップし継続
            continue
    return out


def _weight_fraction_maps(g2phases, g2hists) -> tuple[dict[str, float], dict[str, float | None]]:
    """相名→(重量分率, その esd) を GSAS-II 自身の質量分率計算から抽出する。

    出典 `G2PwdrData.ComputeMassFracs()` → `GSASIIstrMath.calcMassFracs(varyList, covMatrix,
    Phases, hist, hId)`。正準式は ``wtSum = Σ mass[p]*Scale[p]``・``WgtFrac[j] =
    mass[j]*Scale[j]/wtSum`` で、esd は Jacobian と共分散行列から伝播される。

    **`phase_fractions` (Scale の和=1 正規化) との違い**: Scale は単位胞の散乱能に対する係数であり、
    単位胞質量が相間で異なると重量分率と大きく乖離する。さらに mass は精密化された占有率に依存して
    フレーム毎に変わるため、静的 CIF 質量からの後付け換算では正しくない → GSAS に毎回計算させる。

    先頭ヒストグラム基準 (`phase_fractions` と同じ規約)。単相は calcMassFracs が空を返す仕様
    (``len(valDict)==1`` で早期 return) なので、自明な ({name: 1.0}, {name: 0.0}) を返す。
    共分散が無い/取得不能なら空 dict へ縮退し**例外は送出しない**。

    **esd の 3 状態を区別する** (レビュー第6巡 HIGH; R5 の cell_esd と同型): 分率精密化 (相 Scale) が
    最終共分散に残った相は ``>0.0`` (calcMassFracs の伝播 su)、単相は自明な ``{name: 0.0}`` (真の
    陳述; 早期 return)、**多相で su==0.0 は「決まっていない」**ので ``None`` に倒す
    (`_weight_esd_or_none`)。旧実装は `_finite_or_zero` で全段 revert フレームの su を ``0.0`` として
    出版経路へ流していた (実測 fr213/fr224 が直前フレームと分率一致・su=0.0 = 無限精度の捏造)。

    **値側も洗浄しない (Issue #107 事象2)**: 分率の値 (pair[0]) が非有限なら捏造 0.0 に丸めず、
    正規化 wtSum を共有する組全体を「出版値なし」({}, {}) へ縮退する (ComputeMassFracs 例外
    経路と同じ縮退)。空 dict は消費側 (insitu/model.py) が「未計算」として扱う既存契約。
    """
    if not g2phases or not g2hists:
        return {}, {}
    if len(g2phases) == 1:
        return {g2phases[0].name: 1.0}, {g2phases[0].name: 0.0}
    try:
        vals = g2hists[0].ComputeMassFracs()
    except Exception:  # noqa: BLE001 — 共分散なし (未収束/未精密化) 等は空へ縮退
        return {}, {}
    fracs: dict[str, float] = {}
    esds: dict[str, float | None] = {}
    for name, pair in dict(vals).items():
        value = pair[0]
        # 【値側の洗浄禁止 (Issue #107 事象2)】: 非有限の値を `_finite_or_zero` で捏造 0.0 に
        #   して出版経路へ流さない (esd 側 R6 と同じ「計算された 0 と計算されなかったを区別」
        #   規律)。重量分率は正規化 wtSum を全相で共有するため、1 つでも非有限なら組全体が
        #   信頼できない → ComputeMassFracs 例外と同じ「出版値なし」({}, {}) へ縮退する。
        try:
            fvalue = float(value)
        except (TypeError, ValueError):
            return {}, {}
        if not math.isfinite(fvalue):
            return {}, {}
        fracs[str(name)] = fvalue
        esds[str(name)] = _weight_esd_or_none(pair[1])
    return fracs, esds


def _microstructure_maps(g2phases, g2hists):
    """相×ヒストグラムの結晶子サイズ / 微小歪み (+ esd) を抽出する。

    **収束の判定対象は「構造 + 歪」**である (プロファイルの Caglioti は装置側の nuisance で、
    構造と歪が一致していれば最良フィットを選べば足りる)。しかし size/mustrain は HAP
    パラメータなので `hist_profile` (装置パラメータ) には入らず、これまで結果に載っていなかった
    = **歪の一致を確かめる術が無かった**。

    異方 (uniaxial/generalized) は代表成分 (先頭値) のみを載せる — 成分数が設定で変わるため
    そのまま比較すると「モデルが違う」ことと「値が違う」ことが混ざる。
    :returns: (size, mustrain, size_esd, mustrain_esd) — いずれも 相名→"hist{i}"→値
    """
    size: dict[str, dict[str, float]] = {}
    strain: dict[str, dict[str, float]] = {}
    size_esd: dict[str, dict[str, float | None]] = {}
    strain_esd: dict[str, dict[str, float | None]] = {}
    for ph in g2phases:
        try:
            esds = read_variable_esds(ph.proj)
        except Exception:  # noqa: BLE001 — 共分散なしは未精密化へ縮退
            esds = {}
        for hi, hist in enumerate(g2hists):
            try:
                hap = ph.getHAPvalues(hist)
            except Exception:  # noqa: BLE001 — HAP が無い組合せはスキップ
                continue
            key = f"hist{hi}"
            for name, values, esd_map, var in (
                ("Size", size, size_esd, "Size;i"),
                ("Mustrain", strain, strain_esd, "Mustrain;i"),
            ):
                try:
                    entry = hap[name]
                    # GSAS の HAP は [type, [値...], [refine flags...], ...] の形。
                    raw = entry[1][0] if isinstance(entry[1], (list, tuple)) else entry[1]
                    values.setdefault(ph.name, {})[key] = float(raw)
                except Exception:  # noqa: BLE001 — 形が違えばその項だけ落とす
                    continue
                esd_map.setdefault(ph.name, {})[key] = esds.get(
                    f"{ph.id}:{getattr(hist, 'id', hi)}:{var}"
                )
    return size, strain, size_esd, strain_esd


def _extract_phase_fractions(g2phases, g2hists) -> list[float]:
    """先頭ヒストグラムにおける各相の相分率 (HAP Scale) を返す (多相の和=1 検査用, M6)。

    抽出失敗の相は NaN を入れて**長さを相数に保つ** (欠落で continue すると len が縮み、
    check_validity の和=1 検査が黙って skip され偽 valid になるため)。NaN があれば和検査は fail する。
    """
    if not g2hists:
        return []
    hist = g2hists[0]
    fractions: list[float] = []
    for ph in g2phases:
        try:
            fractions.append(float(ph.getHAPvalues(hist)["Scale"][0]))
        except Exception:
            fractions.append(float("nan"))
    return fractions


def _set_initial_cell(ph, cell: tuple[float, ...]) -> None:
    """相の初期格子を絶対値 cell=(a,b,c[,α,β,γ]) に設定し体積を再計算する (ウォームスタート用)。

    add_phase 直後・精密化前に呼ぶ。逐次 (sequential) 精密化で直前フレームの精密化格子を次フレームの
    初期値として引き継ぐのに用いる。角度は与えられなければ現在値を保つ。``initial_cell_scale``
    (相対摂動) と排他: こちらは絶対セルを与える。
    """
    from GSASII import GSASIIlattice as G2lat

    cur = ph.data["General"]["Cell"]
    a, b, c = float(cell[0]), float(cell[1]), float(cell[2])
    alpha = float(cell[3]) if len(cell) > 3 else float(cur[4])
    beta = float(cell[4]) if len(cell) > 4 else float(cur[5])
    gamma = float(cell[5]) if len(cell) > 5 else float(cur[6])
    new = [a, b, c, alpha, beta, gamma]
    ph.data["General"]["Cell"][1:7] = new
    ph.data["General"]["Cell"][7] = G2lat.calc_V(G2lat.cell2A(new))


def _perturb_initial_cell(ph, scale: tuple[float, float, float]) -> None:
    """相の初期格子 a/b/c を scale 倍に摂動し体積を再計算する (マルチスタート用)。

    add_phase 直後・精密化前に呼ぶ。GSAS-II の Cell 配列 [refine, a, b, c, α, β, γ, V] の
    長さ 3 成分を掛け、体積を cell2A→calc_V で整合させる (get_cell に反映される)。
    """
    from GSASII import GSASIIlattice as G2lat

    cell = ph.data["General"]["Cell"]
    a, b, c = float(cell[1]) * scale[0], float(cell[2]) * scale[1], float(cell[3]) * scale[2]
    new = [a, b, c, float(cell[4]), float(cell[5]), float(cell[6])]
    ph.data["General"]["Cell"][1:7] = new
    ph.data["General"]["Cell"][7] = G2lat.calc_V(G2lat.cell2A(new))


def _apply_initial_fractions(g2phases, g2hists, fractions: Mapping[str, float]) -> None:
    """相分率 (HAP Scale) を initial_fractions で初期化する (逐次精密化ウォームスタート用, Issue #82)。

    実測動機: `run_sequential_rietveld` の warm_start は格子のみを引き継ぎ、相分率は毎フレーム既定
    HAP Scale (単相 1.0/多相は add_phase 既定の等分) から再出発するため、転移ドーム域で分率精密化が
    局所的に動かず既定値に張り付くフレームが生じる (実測 2 相 cubic+tetragonal 系列: f112 0.48, f116
    0.55, f120 0.60, **f124 0.50, f128 0.50** (未着手の seed 値そのまま), f132 0.59 — 分率 warm-start
    ありの系列は同域で ≈0.69 まで滑らかに追従した)。

    add_phase 直後・精密化前に `initial_cells` と対称の位置で呼ぶ。値は**相対値**で良い — GSAS の
    相分率和=1 制約 (`_setup_constraints` の `phase_fraction_sum`, 多相のみ登録) が精密化開始時に
    正規化する。既存の refine フラグ (解放/固定) は変更せず値のみ差し替える。

    :param g2phases: 相追加済みの G2Phase 列
    :param g2hists: 精密化対象ヒストグラム列 (Scale は HAP = 相×ヒストグラムの組ごとに持つ)
    :param fractions: 相名→相対分率。未知の相名は無視する

    fail-open (Issue #82 要件): fractions が空、または全値が非有限/ゼロなら何もしない。誤って
    全相を 0 分率に固定してしまう事故 (精密化が動けなくなる) を避けるための安全側フォールバック。
    """
    if not fractions or not g2hists:
        return
    finite_vals = [v for v in fractions.values() if math.isfinite(v)]
    if not finite_vals or not any(v != 0.0 for v in finite_vals):
        return
    for ph in g2phases:
        frac = fractions.get(ph.name)
        if frac is None or not math.isfinite(frac):
            continue
        for hist in g2hists:
            try:
                cur = ph.getHAPvalues(hist)["Scale"]
                refine_flag = cur[1]
            except (KeyError, IndexError, TypeError):
                refine_flag = True
            ph.setHAPvalues({"Scale": [float(frac), refine_flag]}, targethistlist=[hist])


def run_auto_rietveld(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    recipe: Sequence[RefinementStage] | None = None,
    reference_cells: dict[str, tuple[float, ...]] | None = None,
    ledger: Ledger | None = None,
    max_cyc: int = 12,
    worsen_eps: float = 1e-6,
    keep_gpx: str | None = None,
    initial_cell_scale: dict[str, tuple[float, float, float]] | None = None,
    initial_cells: dict[str, tuple[float, ...]] | None = None,
    initial_fractions: Mapping[str, float] | None = None,
    bond_restraints: dict[str, Sequence[Mapping[str, object]]] | None = None,
    auto_freeze_minor_cells: float | None = None,
    initial_occupancies: Mapping[str, Mapping[str, float]] | None = None,
    initial_coord_jitter: Mapping[str, float] | None = None,
    jitter_seed: int = 0,
    chem_comp_restraints: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
    content_constraint: Mapping[str, float] | None = None,
    check_occupancy_uiso: bool = False,
    stability: StabilityOptions | None = None,
) -> AutoRietveldResult:
    """実構造 Rietveld を段階解放で自動実行する (単相/単一ヒストグラムから対応)。

    :param histograms: 観測ヒストグラム仕様
    :param phases: 相仕様 (実 CIF/EXP)
    :param recipe: 段階解放レシピ (None なら build_recipe で生成)
    :param reference_cells: 妥当性判定の参照格子 (None なら初期格子を採用)
    :param ledger: 遷移を追記する Ledger (None なら内部生成)
    :param max_cyc: 各段階の最大精密化サイクル
    :param worsen_eps: Rwp 悪化とみなす閾値
    :param keep_gpx: 最終 .gpx をこのパスへ保存 (None なら破棄)
    :param bond_restraints: 相名→結合距離ソフト拘束の列 (GSAS-II Bond restraint)。各拘束は
        ``{"origin": (ラベル…), "target": (ラベル…), "distance": Å, "esd": Å, "factor": 探索係数,
        "weight": wtFactor}`` の dict (origin/target/distance 必須, 他は既定 esd0.02/factor1.5/weight1000)。
        **初期座標が理想幾何のうちに**登録し、精密化中に O–H/D 結合長が理想値から外れる罰を与える
        (無秩序水の軽原子座標の漂流を防ぐ; 配向は自由)。weight は**相単位** (最後の spec 値が相全体に適用)。
        既定 None (拘束なし)。⚠ D/H の等値/占有率和など**対称・等値制約と併用すると GSAS scriptable が
        拘束勾配を制約変数へ伝播せず無効**になる (実測)。硬拘束が要るなら `PhaseSpec.frozen_coord_labels`。
    :param initial_cell_scale: 相名→(fa,fb,fc) の初期格子摂動倍率 (マルチスタート用, None で無摂動)。
        **参照格子は摂動前の初期値を採用**する (妥当性判定を摂動でずらさないため)。
    :param initial_cells: 相名→(a,b,c[,α,β,γ]) の絶対初期格子 (逐次精密化のウォームスタート用,
        None で CIF 既定)。直前フレームの精密化格子を次フレームの初期値に引き継ぐのに用いる。
        ``initial_cell_scale`` と併用時は本絶対セルを先に適用し、その上に摂動倍率を掛ける。
    :param initial_fractions: 相名→相対相分率 (逐次精密化の分率ウォームスタート用, Issue #82,
        None で GSAS 既定 HAP Scale)。直前フレームの精密化相分率を次フレームの HAP Scale 初期値に
        引き継ぐ。相分率和=1 制約 (多相のみ) が精密化開始時に正規化するため絶対値である必要はない。
        未知の相名は無視、全値が非有限/ゼロなら fail-open でシーディングを丸ごとスキップする。
    :param auto_freeze_minor_cells: 分率連動の自動セル凍結閾値 (opt-in, Issue #80: #47/#50 の
        自動化)。⚠ **basis は `phase_fractions` (= HAP Scale の Σ=1 正規化値) であり
        `phase_weight_fractions` (wt%) ではない** — 実測 K₂Mn[Fe(CN)₆] で ``Scale {cubic .75,
        tetra .25}`` = ``wt% {cubic .865, tetra .135}`` なので **0.2 は Scale では tetra を解放し
        wt% では凍結する** (`_should_refine_cell` 参照)。出版値は wt% なので wt% の直感で数字を
        決めると静かに外れる。None (既定) なら従来動作 (非回帰): "cell" 段は ``PhaseSpec.refine_cell`` の
        明示指定のみに従う。float (例 0.2) を与えると、"cell" 段の適用時点で live な
        ``g2phases``/``g2hists`` から ``_phase_fraction_map`` により取得した現在の相分率が
        閾値未満の相は、その段階の Cell 解放をスキップする (計量が近い相同士の相関で少数相
        セルを解放すると発散する実測知見, Issue #80 背景)。**手動が自動に勝つ**:
        ``PhaseSpec.refine_cell=False`` は本閾値の値に関わらず常に凍結を維持する。単相は
        分率 1.0 のため凍結されない。分率が取得できない場合は fail open (凍結しない) — 全相を
        誤って凍結する事故を避ける。自動凍結された相名は各段の ledger エントリ
        (``m7_stage`` の ``auto_frozen_cells``) に記録され、挙動が監査可能になる。
    :param initial_occupancies: 相名→{原子ラベル→占有率} の初期値シーダー (FR-318)。値のみ差し替え、
        精密化フラグは触らない — 占有率グループ非宣言の原子は seed 値のまま**固定**される (fix モード)。
        範囲外 ([0,1] 超) は GSAS import 前に ValueError (物理的に不可能な要求は大声で失敗)。
        非有限/未知ラベルは fail-open で無視。既定 None。
    :param chem_comp_restraints: 相名→組成 (ChemComp) ソフト拘束の列 (FR-318 soft モード)。各 spec は
        ``{"labels": [...], "total": セルあたり原子数目標, "esd": 目標 esd, "factors": 係数,
        "weight": 相単位 wtFactor}``。**total はセルあたり** (式単位量 x は呼び出し側で x×Z に換算)。
        GSAS 本体の ChemComp penalty を Restraints ツリー直接注入で使う。既定 None。
    :param content_constraint: 相名→係数 cᵢ の相間線形 Scale 拘束 ``Σ cᵢ·Scaleᵢ = 0``
        (FR-318 lock_fractions)。総アルカリ量拘束は cᵢ = Zᵢ·(xᵢ − x_total)。⚠ 2 相では相分率が
        完全決定され XRD は分率に寄与しなくなる。実行可能性/縮退ゲートは呼び出し側の責務
        (`operando.coulometry.feasibility`)。既定 None。
    :param stability: 安定性最優先の**診断ゲート + 箱拘束** (stable-auto-rietveld)。収束判定
        (REQ-SAR-101) / no-op 段の検出 (102) / 弱い変数の観測・報告・凍結 (103) / 高相関の記録 (104) と、
        装置・幾何パラメータの箱拘束 (201) / 境界到達の報告 (202) / restraint の有効化 (203) を
        opt-in で有効化する。**既定 None は現行と完全に同一の挙動** (共分散も Controls も
        1 度も触らず、``Refine`` の呼び出しも現行のまま)。詳細は `StabilityOptions`。
        ⚠ **箱拘束は装置・幾何だけ** — 占有率/Uiso/座標には張らない (P-SAR-1)。
    :returns: AutoRietveldResult
    """
    # FR-318: 占有率シーダーの範囲検証は GSAS import 前に行う (物理的に不可能な要求は即時失敗)。
    if initial_occupancies:
        for _ph_name, _vals in initial_occupancies.items():
            for _lab, _v in _vals.items():
                if math.isfinite(float(_v)) and not (0.0 <= float(_v) <= 1.0 + 1e-9):
                    raise ValueError(
                        f"初期占有率が物理範囲 [0,1] を外れています: "
                        f"{_ph_name}/{_lab} = {_v}"
                    )
    if recipe is not None:
        stages = tuple(recipe)
        # 【REQ-SAR-301 を engine 入口でも強制する】: `validate_correlation_groups` は
        #   `recipe._finalize` からしか呼ばれておらず、**builder の不変条件にすぎなかった**。
        #   ``recipe=`` で手組みの段列を渡す経路 (② の `stages` spec / `insitu` の recipe 注入 /
        #   探索候補) は検証を丸ごと素通りしていた。相関群を割った段は **revert としてしか
        #   現れず、原因が群の分割であることは Rwp から読めない** (`CorrelationGroupViolation`
        #   の docstring) ので、GSAS を叩く前に大声で落とす。
        validate_correlation_groups(stages, histograms=histograms)
    else:
        stages = build_recipe(histograms, phases)
    # 検証は GSAS の解決より**前**に済ませる — 不正なレシピは GSAS が無い環境でも同じ
    # ``CorrelationGroupViolation`` で落ちるべきであり (入力の誤りは backend の有無と無関係)、
    # そうしないと本検証のテストが GSAS 導入環境でしか回らなくなる。
    g2sc = _g2sc()
    ledger = ledger if ledger is not None else Ledger()
    radiations = [h.radiation for h in histograms]

    with tempfile.TemporaryDirectory(prefix="tsumugin-m7-") as tmp:
        tmp_path = Path(tmp)
        gpx_path = tmp_path / "auto.gpx"
        gpx = g2sc.G2Project(newgpx=str(gpx_path))

        # --- ヒストグラム追加 ---
        g2hists = []
        for h in histograms:
            hist = gpx.add_powder_histogram(
                h.data_path, h.instrument_path, fmthint=_data_fmthint(h)
            )
            # 【宣言ジオメトリを正とする】: GSAS は Sample Parameters の Type を instprm から
            #   推定するため、Kα1 単色 instprm の反射光学系が Debye-Scherrer 扱いになり
            #   `Shift` 解放が例外 → cell 段ごと revert → 格子が一切精密化されない、という
            #   無言の失敗が起きる。他の Sample Parameters 書き込み (absorption 等) より先に置く。
            _apply_sample_geometry(hist, h.geometry)
            if h.two_theta_limits is not None:
                lo, hi = h.two_theta_limits
                hist.set_refinements({"Limits": [lo, hi]})
            if h.excluded_regions:
                # GSAS-II の Limits は [(orig_min,orig_max), [used_lo,used_hi], *excluded_pairs] で、
                # set_refinements に 'Exclude' キーは存在しない (実測で例外)。使用域確定後に
                # [lo, hi] を直接 append する (Issue #53)。
                for r in h.excluded_regions:
                    hist.data["Limits"].append([float(r[0]), float(r[1])])
            if h.absorber_layers:
                # 固定吸収体レイヤー (electrolyte/window, Issue #54): 角度依存の透過補正を
                # Yobs/weight へ直接適用する (定数部はスケール因子と縮退するため含めない)。
                d = hist.data["data"][1]  # [x, Yobs, weight, Ycalc, Ybkg, Ydiff]
                x = np.asarray(d[0])
                y = np.asarray(d[1])
                w = np.asarray(d[2])
                y2, w2 = apply_absorption_correction(x, y, w, h.absorber_layers)
                d[1] = y2
                d[2] = w2
            if h.weight != 1.0:
                # ヒストグラム重み係数 (GSAS-II wtFactor)。joint の相対重み調整。
                try:
                    hist.data["data"][0]["wtFactor"] = float(h.weight)
                except (KeyError, IndexError, TypeError):
                    pass
            if h.absorption != 0.0:
                # 試料吸収係数の初期値 (Sample Parameters Absorption)。TOF は λ 依存吸収を与える。
                try:
                    hist.data["Sample Parameters"]["Absorption"][0] = float(h.absorption)
                except (KeyError, IndexError, TypeError):
                    pass
            if h.instrument_profile is not None:
                # 標準試料から実測した装置分解能を seed し、以降の段階解放では固定する (Issue #38)。
                _seed_instrument_profile(hist, h.instrument_profile)
            g2hists.append(hist)

        # --- 相追加 ---
        g2phases = []
        for p in phases:
            ph = gpx.add_phase(
                p.structure_path,
                phasename=p.phase_name,
                histograms=g2hists,
                fmthint=p.format_hint,
            )
            g2phases.append(ph)

        # --- 参照格子 (妥当性判定の基準) を先に確保 ---
        # 既定は各相の CIF 初期格子。ただしウォームスタート (initial_cells) を与えた相は、その
        # **前フレームの精密化格子**を参照にする (逐次精密化 M9): 高温系列では格子が熱膨張で CIF
        # 室温値から系統的にずれるため、CIF 基準だと後半フレームが必ず妥当性 fail し、格子ドリフトを
        # 理由に転移フレームの新相を誤棄却する。フレーム間ドリフト基準なら滑らかな系列は各段小さく
        # 妥当、真の急変 (転移) のみ検出できる。新規追加相 (initial_cells になし) は CIF 基準のまま。
        if reference_cells is None:
            reference_cells = {}
            for ph in g2phases:
                cif_cell = tuple(
                    float(ph.get_cell()[k])
                    for k in (
                        "length_a", "length_b", "length_c",
                        "angle_alpha", "angle_beta", "angle_gamma",
                    )
                )
                seed = initial_cells.get(ph.name) if initial_cells else None
                if seed is not None:
                    reference_cells[ph.name] = (
                        float(seed[0]), float(seed[1]), float(seed[2]),
                        float(seed[3]) if len(seed) > 3 else cif_cell[3],
                        float(seed[4]) if len(seed) > 4 else cif_cell[4],
                        float(seed[5]) if len(seed) > 5 else cif_cell[5],
                    )
                else:
                    reference_cells[ph.name] = cif_cell

        # --- 初期格子ウォームスタート (逐次精密化, 任意): 絶対セルを先に適用 ---
        if initial_cells:
            for ph in g2phases:
                cell = initial_cells.get(ph.name)
                if cell is not None:
                    _set_initial_cell(ph, cell)

        # --- 初期格子摂動 (マルチスタート, 任意) ---
        if initial_cell_scale:
            for ph in g2phases:
                scale = initial_cell_scale.get(ph.name)
                if scale is not None:
                    _perturb_initial_cell(ph, scale)

        # --- 初期相分率ウォームスタート (逐次精密化, 任意, Issue #82) ---
        if initial_fractions:
            _apply_initial_fractions(g2phases, g2hists, initial_fractions)

        # --- 初期占有率シーダー (FR-318: fix モード/占有率 warm-start, 任意) ---
        if initial_occupancies:
            _apply_initial_occupancies(g2phases, initial_occupancies)

        # --- 初期座標ジッタ (マルチスタートの構造軸, 任意) ---
        #     対称性が自由な軸だけを動かす。動かせた軸数は ledger に残す — 0 なら
        #     「この軸では試験していない」であって「摂動しても動かなかった」ではない。
        n_jittered = 0
        if initial_coord_jitter:
            n_jittered = _apply_coord_jitter(
                g2phases, initial_coord_jitter, jitter_seed
            )
            ledger.append(
                "m7_coord_jitter",
                {
                    "seed": int(jitter_seed),
                    "amplitude_ang": {k: float(v) for k, v in initial_coord_jitter.items()},
                    "n_axes_moved": n_jittered,
                },
            )

        # --- 初期 Uiso 妥当性 + 占有率/Uiso 結合の事前警告 (FR-318 / REQ-318-005) ---
        # **FR-318 の入力 (シーダー/組成拘束/分率拘束/明示フラグ) があるときのみ**検査する。
        # レビュー M4: 「占有率段があるか」で発火させると、既存の混合占有ワークフロー
        # (T2 garnet / NaCuHCF は occupancy 段 + uiso 段が正規レシピ) に新警告が出て非回帰契約が
        # 破れる。``check_occupancy_uiso`` は FR-318 の diagnose + 占有率解放 (x₀ 導出) フロー用 —
        # plan kwargs が空でも組成を占有率から導出する以上この検査が要る (最終レビュー F3;
        # `make_gsas_runner` が charge_constraint 有効時に立てる)。
        pre_warnings: tuple[str, ...] = ()
        _touches_occupancy = bool(
            initial_occupancies or chem_comp_restraints or content_constraint
            or check_occupancy_uiso
        )
        if _touches_occupancy:
            uiso_init = _atom_result_maps(g2phases).uiso
            pre_warnings = check_initial_uiso(uiso_init) + warn_occupancy_uiso_coupling(stages)

        # --- 制約登録 (混合占有: 占有率和=1 + Uiso 等価; 多相: 相分率和=1) ---
        _setup_constraints(gpx, g2phases, g2hists, phases)
        # 相間の総量線形拘束 (FR-318 lock_fractions; feasibility ゲートは呼び出し側)。
        _apply_content_constraint(gpx, g2phases, g2hists, content_constraint)
        # 結合距離ソフト拘束 (初期座標が理想幾何のうちに登録; O–H/D の漂流防止)。
        _apply_bond_restraints(gpx, g2phases, bond_restraints)
        # 組成 (ChemComp) ソフト拘束 (FR-318 soft モード; Restraints ツリー直接注入)。
        _apply_chem_comp_restraints(gpx, g2phases, chem_comp_restraints)
        # 装置パラメータの物理拘束 (profile_bounds; 分解能抽出の U,W,X,Y≥0 等) を登録する (Issue #38)。
        _apply_profile_bounds(gpx, histograms)
        # 【WS-2 箱拘束 (REQ-SAR-201)】: 装置・幾何パラメータのみ。**構造パラメータには張らない**
        #   (P-SAR-1: 占有率/Uiso/座標の逸脱はモデル誤りの診断信号であり、握り潰してはならない)。
        #   既定 (stability=None) では `has_box_bounds` が False なので Controls を 1 度も触らない。
        stab = stability if stability is not None else StabilityOptions()
        box_bounds: tuple[BoxBound, ...] = ()
        if stab.has_box_bounds:
            box_bounds = _apply_box_bounds(
                gpx, _plan_box_bounds(g2phases, g2hists, histograms, stab)
            )
            ledger.append(
                "m7_box_bounds",
                {"n_bounds": len(box_bounds), "bounds": [b.to_dict() for b in box_bounds]},
            )
        # 【WS-2 restraint 有効化 (REQ-SAR-203)】: 既定 OFF。有効時のみ dlg スタブを作り、
        #   `_refine_once` 経由で `GSASIIstrMain.Refine(dlg=…)` へ挿し込む (restraint_dlg 参照)。
        refine_dlg = RefineProgressStub() if stab.enable_restraints else None
        if refine_dlg is not None:
            # 「有効にしたのに拘束を 1 つも渡していない」を**見える形にする** — 何も登録が
            # 無ければ効くものが無いのに Rwp だけ penalty 込みの値に変わるので、
            # 「有効にしたつもり」の静かな失敗になりやすい (P-SAR-2)。
            ledger.append(
                "m7_restraints_enabled",
                {
                    "bond_phases": sorted(bond_restraints or {}),
                    "chem_comp_phases": sorted(chem_comp_restraints or {}),
                    "note": (
                        "restraint を χ² に入れた (Rwp は penalty 込みの値になる)"
                        if (bond_restraints or chem_comp_restraints)
                        else "⚠ 有効化したが bond/ChemComp 拘束が 1 つも渡されていない"
                    ),
                },
            )
        phase_infos = [_phase_atom_info(ph, p) for ph, p in zip(g2phases, phases)]
        # 装置プロファイル固定 (instrument_profile 指定) の per-hist フラグ (Issue #38)。
        fixed_profile = _fixed_profile_flags(histograms)

        gpx.data["Controls"]["data"]["max cyc"] = max_cyc

        stage_results: list[StageResult] = []
        # 「直前の受理状態」の指標を明示追跡する (復帰時に nvar/gof を正しく巻き戻すため, H1)。
        # 【prev_rwp は常に**データ項**】: 拘束無効時は GSAS の Rwp とビット同一なので非回帰。
        prev_rwp = float("inf")
        prev_gof = float("inf")
        prev_nvar = 0
        prev_penalized: float | None = None
        # 【受理状態の RestraintSum】: `prev_penalized` と**同じ状態**を指す penalty 量。
        #   revert したら penalty も一緒に巻き戻さないと、「rwp/rwp_penalized は採用状態・
        #   restraint_sum は捨てた試行」という**別々の状態を混ぜた報告**になる (下の revert 分岐)。
        prev_penalty = 0.0
        # 拘束を χ² に入れたときだけ penalty を分離する (`_data_rwp` の split 引数)。
        split_penalty = bool(stab.enable_restraints)
        last_penalty = 0.0
        atom_flag_maps: list[dict[str, str]] = [{} for _ in g2phases]
        # 【WS-1 診断ゲート】: 既定 (stability=None) は全項目 False なので、以降の追加処理は
        #   1 行も走らない (共分散すら読まない) = 現行と完全に同一の挙動。`stab` は箱拘束の
        #   登録 (上) で既に解決済み。
        # 【凍結の追跡】: 救済 (`rescue_freeze_on_failure`) と毎段プルーニング
        #   (`prune_weak_vars_each_stage`) で `parmFrozen` に入れた変数。段が revert されたら
        #   凍結もスナップショットごと巻き戻るので、この集合からも外す (追跡だけ残ると
        #   「凍結したつもりの変数」が以降の候補から永久に消える)。
        frozen_vars: set[str] = set()

        for stage in stages:
            snap = tmp_path / "snap.gpx"
            gpx.save()
            shutil.copyfile(gpx_path, snap)
            prev_atom_flag_maps = [dict(m) for m in atom_flag_maps]
            auto_frozen: list[str] = []
            # no-op 判定 (REQ-SAR-102) は「直前の受理状態」と比べるので、prev_* が更新される前に退避。
            before = (prev_rwp, prev_gof, prev_nvar)
            diagnostics: RefinementDiagnostics | None = None
            extra_cycles_used = 0
            rescue_rounds = 0
            rescue_frozen: tuple[str, ...] = ()
            convergence_ok: bool | None = None
            bound_hits: tuple[BoundHit, ...] = ()
            # penalty 込みの生 Rwp (拘束を χ² に入れたときだけ非 None)。
            rwp_penalized: float | None = None
            # 箱の境界到達 (REQ-SAR-202) の差分基準。dropOOBvars はこの段の**すべての**精密化
            # 呼び出し (初回・収束サイクル・救済サイクル) で走るので、窓は段全体に及ぶ。
            # 同じ parmFrozen へ書く esd プルーニング/救済との取り違えは、窓を狭めるのではなく
            # **凍らせた名前を基準側へ足す** ことで切り分ける (`_bound_hit_baseline`)。
            frozen_before = _frozen_variables(gpx) if box_bounds else set()
            try:
                auto_frozen = _apply_stage(
                    gpx, g2hists, g2phases, phase_infos, atom_flag_maps, radiations, stage,
                    fixed_profile, auto_freeze_minor_cells,
                )
                # 【無言失敗の検出】: `G2Project.refine` は `GSASIIstrMain.Refine` の
                #   (OK, Rvals) を捨てるため、精密化が失敗しても例外にならない。その場合
                #   Covariance が前段のまま残り `_rvals` が**前段とビット同一**の値を返すので、
                #   「悪化していない」と判断され revert されず、立てたフラグが残って
                #   **以降の全段が失敗し続ける** (実測 CaTeO3 frame180 二相: S2 以降 7 段 no-op)。
                #   戻り値を捕まえて例外化し、既存の inf→revert→ledger 経路に載せる。
                _refine_once(gpx, refine_dlg)
                rwp, gof, nvar = _rvals(gpx)
                rwp, rwp_penalized, last_penalty = _data_rwp(gpx, rwp, split=split_penalty)
                converged = _converged(gpx)
                if stab.needs_diagnostics:
                    diagnostics = read_diagnostics(gpx, corr_threshold=stab.corr_threshold)

                def _cycle():
                    """同じ段のまま 1 サイクル回し直す (収束サイクルと救済で共有)。"""
                    _refine_once(gpx, refine_dlg)
                    return (
                        read_diagnostics(gpx, corr_threshold=stab.corr_threshold),
                        (_rvals(gpx), _converged(gpx)),
                    )

                def _absorb(payload: object | None) -> None:
                    """サイクルの付随値を段の指標へ取り込む (penalty 分離を必ずやり直す)。"""
                    nonlocal rwp, gof, nvar, converged, rwp_penalized, last_penalty
                    if payload is None:
                        return
                    (rwp, gof, nvar), converged = payload  # type: ignore[misc]
                    # 追加サイクルも同じ ``dlg`` で回るので penalty の分離を**必ず**やり直す
                    #   (経路ごとに塞がないと「追加サイクルだけ penalty 込みで判定」になる)。
                    rwp, rwp_penalized, last_penalty = _data_rwp(gpx, rwp, split=split_penalty)

                if stab.require_convergence and diagnostics is not None:
                    # 【収束判定 (REQ-SAR-101)】: GSAS の「改善した」は max|shift|/esd が
                    #   258 でも成立する (実測ログ)。Rwp の改善だけを受理条件にすると
                    #   **収束していない段**が通過し、以降の段がその上に積み上がる。
                    #   未収束なら同じ段のまま追加サイクルを回し、駄目なら下の revert 経路へ。
                    diagnostics, payload, extra_cycles_used = _run_convergence_cycles(
                        diagnostics,
                        _cycle,
                        max_shift_esd=stab.max_shift_esd,
                        extra_cycles=stab.extra_cycles,
                    )
                    _absorb(payload)
                    convergence_ok = diagnostics.is_converged(
                        max_shift_esd=stab.max_shift_esd
                    )
                if stab.rescue_freeze_on_failure and diagnostics is not None:
                    # 【救済プルーニング (REQ-SAR-103)】: **同じ母数で回し切ってもなお**
                    #   収束しない、あるいは特異行列 (SVD0>0) が出た段だけ、最弱の変数を
                    #   落として回し直す。順序が重要 — 先に追加サイクル (母数はそのまま、
                    #   反復を増やす) を尽くし、それでも駄目なときに初めて母数を削る。
                    #   逆にすると「収束が遅いだけのパラメータ」を決定不能と誤断して捨てる。
                    diagnostics, payload, rescue_rounds, rescue_frozen = _run_rescue_freezes(
                        diagnostics,
                        lambda names: _freeze_variables(gpx, names),
                        _cycle,
                        max_shift_esd=stab.max_shift_esd,
                        exempt=stab.esd_ratio_exempt_tokens,
                        already_frozen=frozen_vars,
                        max_freeze=stab.rescue_max_freeze,
                        max_rounds=stab.rescue_max_rounds,
                    )
                    _absorb(payload)
                    if rescue_frozen:
                        frozen_vars.update(rescue_frozen)
                        if stab.require_convergence:
                            # 救済後の収束状態で受理/revert を判定し直す (救済前の判定を
                            # 引きずると「救済で収束した段」を未収束として捨ててしまう)。
                            convergence_ok = diagnostics.is_converged(
                                max_shift_esd=stab.max_shift_esd
                            )
                if box_bounds:
                    # 【境界到達の検出 (REQ-SAR-202)】: 箱の外へ出た変数は GSAS が境界値へ
                    #   丸めて凍結する = 結果にも Rwp にも現れない。**握り潰さず所見にする**
                    #   (箱が間違っているかモデルが間違っているかは人間が判断すべき事実)。
                    #   値は丸められる**前**の精密化値なので、どちら側へ出たかを断定できる。
                    #   基準側には**救済で自分が凍らせた変数**も入れる (`_bound_hit_baseline`) —
                    #   救済はこの窓の内側で同じ parmFrozen へ書くため、入れないと
                    #   「自分で凍らせた箱付き変数」を境界到達と誤報する。
                    bound_hits = detect_bound_hits(
                        box_bounds,
                        _bound_hit_baseline(frozen_before, rescue_frozen),
                        _frozen_variables(gpx),
                        read_variable_values(gpx),
                    )
                # 格子崩壊 (0 近傍/非有限) またはプロファイル非物理化 (幅関数がレンジ内で負・散乱/立上り
                # 係数が非物理) は発散とみなし inf 化 → 既存 revert 経路 (物理妥当性ガード)。
                # プロファイルガードは解放済パラメータのみ hard 判定するため T1〜T4 は非回帰。
                if not _cells_physical(g2phases) or not _profiles_physical(
                    g2hists, radiations, histograms
                ).passed:
                    rwp, gof, converged, rwp_penalized = (
                        float("inf"), float("inf"), False, None
                    )
            except Exception as exc:  # 精密化失敗 → inf 変換 (REQ-403)
                rwp, gof, nvar, converged = float("inf"), float("inf"), 0, False
                rwp_penalized = None
                # 失敗した精密化の penalty は**測れていない**。前段の値を残すと「この段の試行で
                # 観測した penalty」に化けるので、採用状態の値へ戻す (rwp=inf が失敗を示す)。
                last_penalty = prev_penalty
                diagnostics, convergence_ok = None, None
                ledger.append(
                    "m7_stage_error",
                    {"stage": stage.label, "error": repr(exc)[:200]},
                )

            # 【試行の観測 (REQ-SAR-203/205)】: revert は「この段の精密化そのもの」を無かった
            #   ことにするので、**段が実際に何をしたか**は revert の前に控えておくしかない。
            #   拘束の検証では特にこれが要る — 誤ったターゲットの拘束は「データが支持する位置
            #   から遠ざける」ので、拘束が正しく χ² に入っているほど**データ項は悪化し段は
            #   revert される**。最終状態だけを見ると「拘束が効いていない」と区別が付かない
            #   (実測: penalty 3.69e9 → 0.08 まで最小化された段が、正しく revert された)。
            #   **判定には一切使わない — 観測専用** (提案 ≠ 適用と同じ規律)。
            trial_rwp, trial_penalized, trial_penalty = rwp, rwp_penalized, last_penalty
            reverted = False
            # 追加サイクルを使い切っても未収束の段は**受理しない** (REQ-SAR-101)。Rwp が
            # 改善していても、収束していない解の上に次段を積むと段列全体が信用できなくなる。
            unconverged = convergence_ok is False
            if unconverged:
                ledger.append(
                    "m7_stage_unconverged",
                    {
                        "stage": stage.label,
                        "max_shift_esd": (
                            finite_or_none(diagnostics.max_shift_esd) if diagnostics else None
                        ),
                        "limit": stab.max_shift_esd,
                        "extra_cycles": extra_cycles_used,
                        "svd_singularities": (
                            diagnostics.svd_singularities if diagnostics else 0
                        ),
                    },
                )
            # 悪化 (または inf) なら直前スナップショット (この段階適用前の状態) へ revert して継続
            # (REQ-105/FR-202)。snap は各段階の冒頭で必ず取得済みなので、初段失敗でも
            # 「精密化前の健全なプロジェクト」へ戻せる (H2: prev_rwp==inf でも復帰する)。
            # 【比較は必ず**データ項 Rwp**】: 拘束を χ² に入れると GSAS の Rwp は penalty 込みに
            #   なる。拘束は「引く力」であって適合の悪化ではないので、penalty の増減で段を
            #   revert するのは誤りである (実測: bond weight 1e5 で Rwp 3558 → 全段 revert)。
            #   `rwp` は `_data_rwp` が分離済みで、拘束無効時は GSAS 値とビット同一。
            decision = decide_stage(
                StageMetrics(before[0], before[1], before[2]),
                StageMetrics(rwp, gof, nvar),
                worsen_eps=worsen_eps,
                unconverged=unconverged,
                detect_noop=stab.detect_noop_stages,
            )
            if decision.reverted:
                shutil.copyfile(snap, gpx_path)
                gpx = g2sc.G2Project(gpxfile=str(gpx_path))
                g2hists = gpx.histograms()
                g2phases = gpx.phases()
                phase_infos = [
                    _phase_atom_info(ph, p) for ph, p in zip(g2phases, phases)
                ]
                gpx.data["Controls"]["data"]["max cyc"] = max_cyc
                reverted = True
                atom_flag_maps = prev_atom_flag_maps
                # 【救済凍結も巻き戻る】: 凍結先の ``Controls['parmFrozen']`` は gpx ツリーの
                #   一部なのでスナップショット復元で消える。追跡集合だけ残すと、以降その変数が
                #   「凍結済み」として候補から永久に外れる (実際には解放されたまま)。
                if rescue_frozen:
                    frozen_vars.difference_update(rescue_frozen)
                # 復帰後の指標は「直前の受理状態」を反映する (H1: nvar も巻き戻す)。
                rwp, gof, nvar = prev_rwp, prev_gof, prev_nvar
                # penalty も rwp_penalized と**同じ状態**へ巻き戻す (片方だけ試行値を残すと
                # 報告が 2 つの状態を混ぜる)。試行の値は trial_* に控えてある。
                rwp_penalized, last_penalty = prev_penalized, prev_penalty
            else:
                prev_rwp, prev_gof, prev_nvar = rwp, gof, nvar
                prev_penalized, prev_penalty = rwp_penalized, last_penalty

            # 【no-op 段の検出 (REQ-SAR-102)】: revert されていないのに n_params が増えず
            #   rwp/gof がビット同一 = その段は何も精密化していない。**revert はしない**
            #   (検出のみ) — 段が効かない理由 (実元素数を超えた固定ランク段 / 全ヒストグラムが
            #   除外されるプロファイル段 / GSAS の無言失敗) は Rwp からは区別できないので、
            #   区別できる事実として台帳に残す。
            is_noop = decision.is_noop
            if is_noop:
                ledger.append(
                    "m7_stage_noop",
                    {
                        "stage": stage.label,
                        "rwp": rwp,
                        "gof": gof,
                        "n_params": nvar,
                        "prev_n_params": before[2],
                    },
                )

            # 【救済プルーニングの記録 (REQ-SAR-103)】: 何を落として回し直したかを残す。
            #   GSAS 自身の `dropTerms` は黙って落とすので、ここで見えるようにしないと
            #   「なぜこの段だけ母数が少ないのか」が後から追えない。
            if rescue_frozen:
                ledger.append(
                    "m7_stage_rescue",
                    {
                        "stage": stage.label,
                        "reason": "未収束 または SVD0>0 (悪条件) の救済 (REQ-SAR-103)",
                        "rounds": rescue_rounds,
                        "reverted": reverted,
                        "svd_singularities": (
                            diagnostics.svd_singularities if diagnostics else 0
                        ),
                        "variables": list(rescue_frozen),
                        "note": (
                            "段が revert されたので凍結も巻き戻った"
                            if reverted
                            else "凍結は以降の段でも維持される"
                        ),
                    },
                )

            # 【弱い変数の観測 (REQ-SAR-103)】: 各段では **記録するだけで凍結しない**。
            #   途中段階の大きな esd は「決定不能」の証拠ではなく「まだ決まっていない」だけで
            #   あり (座標がずれた段階の Uiso など)、ここで凍らせると後段で本来決まるように
            #   なっても二度と解放されない。**凍結は判断、記録は観測** (提案 ≠ 適用)。
            #   revert された段でも記録する — その段が壊れた理由の一次証拠だから。
            if stab.record_weak_vars and diagnostics is not None and diagnostics.weak_vars:
                judged, exempt_vars = split_weak_variables(
                    diagnostics.weak_vars, stab.esd_ratio_exempt_tokens
                )
                if judged:
                    ledger.append(
                        "m7_stage_weak_vars",
                        {
                            "stage": stage.label,
                            "reverted": reverted,
                            "n_weak": len(judged),
                            "n_exempt": len(exempt_vars),
                            # 変数数は母数に比例する — 台帳には比の悪い上位のみ載せる。
                            "variables": [
                                w.to_dict() for w in judged[: stab.max_recorded_pairs]
                            ],
                            "note": "観測のみ — 凍結していない (REQ-SAR-103)",
                        },
                    )

            # 【毎段プルーニング (opt-in の逃げ道)】: 受理された段の完了時に esd >= |値| の
            #   変数を凍結し、次段以降の varyList から外す。**既定 OFF** — 上記のとおり
            #   不可逆なラチェットになるため、条件数が本当に進行を妨げるデータ限定の手段。
            newly_frozen: list[str] = []
            if stab.prune_weak_vars_each_stage and not reverted and diagnostics is not None:
                candidates = _prune_candidates(
                    diagnostics.weak_vars, frozen_vars, stab.esd_ratio_exempt_tokens
                )
                newly_frozen = _freeze_variables(gpx, [w.name for w in candidates])
                frozen_vars.update(newly_frozen)
                if newly_frozen:
                    frozen_set = set(newly_frozen)
                    ledger.append(
                        "m7_stage_prune",
                        {
                            "stage": stage.label,
                            "reason": "esd >= |value| (毎段プルーニング, opt-in)",
                            "variables": [
                                w.to_dict() for w in candidates if w.name in frozen_set
                            ],
                        },
                    )

            # 【高相関の記録 (REQ-SAR-104)】: |r| >= 閾値 のペアを台帳に残す。**この段階では
            #   検出と記録のみ**で自動凍結はしない (同時解放を避けるのはレシピ側の判断: Phase 2)。
            #   revert された段でも記録する — 「なぜその段が壊れたか」の最有力の手がかりだから。
            if stab.record_correlations and diagnostics is not None and diagnostics.correlated_pairs:
                ledger.append(
                    "m7_stage_correlation",
                    {
                        "stage": stage.label,
                        "threshold": stab.corr_threshold,
                        "reverted": reverted,
                        "n_pairs": len(diagnostics.correlated_pairs),
                        # ペア数は O(n²) — 台帳には上位のみ載せ、総数は n_pairs で示す。
                        "pairs": [
                            p.to_dict()
                            for p in diagnostics.correlated_pairs[: stab.max_recorded_pairs]
                        ],
                    },
                )

            # 【箱の境界到達 (REQ-SAR-202)】: revert された段でも記録する — 「なぜその段が
            #   壊れたか」の一次証拠であり、revert で凍結ごと巻き戻っても事実は残すべきだから
            #   (高相関の記録と同じ規律)。
            if bound_hits:
                ledger.append(
                    "m7_stage_bound_hit",
                    {
                        "stage": stage.label,
                        "reverted": reverted,
                        "n_hits": len(bound_hits),
                        "hits": [h.to_dict() for h in bound_hits],
                    },
                )

            # 自動セル凍結 (Issue #80) が発生した相を note に付記し挙動を可視化する
            # (非破壊: stage.note 自体は変更せず、StageResult 側でのみ拡張する)。
            note = stage.note
            note_extras: list[str] = []
            if auto_frozen:
                note_extras.append(f"auto_frozen_cells={','.join(auto_frozen)}")
            if extra_cycles_used:
                note_extras.append(f"extra_cycles={extra_cycles_used}")
            if unconverged:
                note_extras.append("unconverged")
            if is_noop:
                note_extras.append("noop")
            if rescue_frozen:
                note_extras.append(f"rescue_frozen={len(rescue_frozen)}")
            if newly_frozen:
                note_extras.append(f"pruned={len(newly_frozen)}")
            if bound_hits:
                note_extras.append(f"bound_hits={len(bound_hits)}")
            for extra in note_extras:
                note = f"{note}; {extra}" if note else extra

            stage_results.append(
                StageResult(
                    label=stage.label,
                    rwp=rwp,
                    gof=gof,
                    n_params=nvar,
                    converged=converged,
                    reverted=reverted,
                    note=note,
                    rwp_penalized=rwp_penalized,
                )
            )
            # 【penalty 分離の記録】: 拘束を χ² に入れた段だけ、分離の**材料ごと**残す。
            #   既定経路では 1 エントリも増えない (ledger のハッシュ鎖は非回帰) — 判定は
            #   `split_penalty` が偽なら trial_penalized も rwp_penalized も None だから。
            #   「Rwp が下がったのは拘束を緩めたからでは?」を後から検算できるようにする。
            #   **無印は同じ状態を指す**: 採用状態 (revert 後)。``trial_*`` はこの段の試行
            #   そのもの。混ぜると「拘束が効いたのに revert された」段の読み方が壊れる。
            if rwp_penalized is not None or trial_penalized is not None:
                ledger.append(
                    "m7_stage_restraint_split",
                    {
                        "stage": stage.label,
                        "rwp_data": rwp,
                        "rwp_penalized": rwp_penalized,
                        "restraint_sum": last_penalty,
                        # 【試行の観測】: revert されても「この段の精密化が拘束をどう扱ったか」は
                        #   残す。penalty が試行中に大きく下がっていれば、段が採用されたか否かと
                        #   **無関係に** penalty が目的関数へ入っている証拠になる (REQ-SAR-203)。
                        #   ⚠ **② 非露出を明示的に宣言する** (CLAUDE.md の露出規則): これは
                        #   捨てた試行の値であり「出版される fit を説明する数字」ではないので、
                        #   ② の戻り値 (採用状態の `rwp_penalized`/`final_restraint_penalty`) と
                        #   混ぜない。用途は本カナリアと事後監査で、読み手は ledger を直接見る。
                        "trial_rwp_data": finite_or_none(trial_rwp),
                        "trial_rwp_penalized": trial_penalized,
                        "trial_restraint_sum": trial_penalty,
                        "reverted": reverted,
                        "note": "段の受理/revert は rwp_data で判定した (REQ-SAR-203)",
                    },
                )
            stage_entry: dict[str, object] = {
                "stage": stage.label,
                "rwp": rwp,
                "gof": gof,
                "n_params": nvar,
                # 【n_obs】: 段ごとの BIC (= χ² + n_params·ln(n_obs)) を**このエントリだけから**
                #   導出できるようにする (GUI の LEDGER 表示)。レンジ制限適用後の実点数。
                "n_obs": _nobs(gpx),
                "reverted": reverted,
                "auto_frozen_cells": list(auto_frozen),
            }
            if stab.needs_diagnostics and diagnostics is not None:
                # 【観測とゲートの分離 (REQ-SAR-101/103)】: これまで ``max_shift_esd`` は
                #   `m7_stage_unconverged` にしか載らず、そのエントリは
                #   ``require_convergence=True`` の時しか出なかった = **収束状態を観測するには
                #   精密化を変えるしかない**状態だった。レシピ候補を比較する計測では、観測列
                #   (フィットを変えない) とゲート列 (受理条件を変える) を分けられないと
                #   「どの案が収束していたか」を公平に測れない。
                #   ⚠ **条件付きで足す**こと — 無条件にキーを増やすと既定経路の ledger
                #   ハッシュ鎖が変わり、ビット同一性の非回帰契約 (NFR-102) を壊す。
                stage_entry["max_shift_esd"] = finite_or_none(diagnostics.max_shift_esd)
                stage_entry["svd_singularities"] = diagnostics.svd_singularities
                stage_entry["converged_flag"] = diagnostics.converged
                stage_entry["n_weak"] = len(diagnostics.weak_vars)
            ledger.append("m7_stage", stage_entry)

        # --- 決まらなかったパラメータの報告 (+ opt-in の最終研磨) ---
        # 【なぜ最終なのか】: ここで残っている ``esd >= |値|`` は「まだ決まっていない」ではなく
        #   **「このデータ・このモデルでは決まらない」**という所見である。段の途中の同じ値は
        #   単に収束の途上なので、両者は同じ数式でも意味が違う。所見はモデルの誤りを示唆する
        #   情報 (P-SAR-1) なので、凍結して隠さず結果へ載せる。
        undetermined: tuple[WeakVariable, ...] = ()
        undetermined_exempt: tuple[WeakVariable, ...] = ()
        final_polish: FinalPolish | None = None
        if stab.needs_final_diagnostics:
            final_diag = read_diagnostics(gpx, corr_threshold=stab.corr_threshold)
            undetermined, undetermined_exempt = split_weak_variables(
                final_diag.weak_vars, stab.esd_ratio_exempt_tokens
            )
            ledger.append(
                "m7_undetermined",
                {
                    "n_undetermined": len(undetermined),
                    "n_exempt": len(undetermined_exempt),
                    "variables": [w.to_dict() for w in undetermined],
                    # 判定対象外にした変数も件数と名前は残す (何を見なかったかを隠さない)。
                    "exempt_variables": [w.to_dict() for w in undetermined_exempt],
                    "exempt_tokens": list(stab.esd_ratio_exempt_tokens),
                    "note": (
                        "esd >= |値| = このデータでは決まらなかったパラメータ (所見; "
                        "凍結していない)"
                    ),
                },
            )
        if stab.polish_frozen_undetermined:
            gpx, final_polish, undetermined, undetermined_exempt = _run_final_polish(
                gpx,
                g2sc,
                gpx_path=gpx_path,
                snap_path=tmp_path / "polish.gpx",
                undetermined=undetermined,
                exempt=undetermined_exempt,
                already_frozen=frozen_vars,
                stab=stab,
                stage_results=stage_results,
                dlg=refine_dlg,
                split_penalty=split_penalty,
                max_cyc=max_cyc,
                radiations=radiations,
                histograms=histograms,
                ledger=ledger,
            )
            # 研磨は revert しても新しい `G2Project` を返す (スナップショット再読込) ので、
            # live オブジェクトは**常に**取り直す (片方だけ古いと最終抽出が食い違う)。
            g2hists, g2phases = gpx.histograms(), gpx.phases()
            frozen_vars.update(final_polish.frozen if final_polish.applied else ())

        # --- 妥当性判定 ---
        refined_cells, uiso, occ = _extract_state(g2phases)
        # 多相なら先頭ヒストグラムの相分率 (HAP Scale) を抽出し 和=1 制約の充足を検査する (M6)。
        # 制約は各ヒストグラムで同一 (和=1) のため代表として先頭を採る。単相は None (検査省略)。
        phase_fractions = _extract_phase_fractions(g2phases, g2hists) if len(g2phases) > 1 else None
        validity = check_validity(
            refined_cells=refined_cells,
            reference_cells=reference_cells,
            uiso=uiso,
            occupancies=occ,
            phase_fractions=phase_fractions,
            converged=stage_results[-1].converged if stage_results else False,
        )

        # --- プロファイル内省 + 物理性 (最終状態) ---
        # hist_profile を充填 (TASK-0001 で追加済・未配線だった内省フィールドを生かす → diagnose_residual
        # が実プロファイル値を使える)。物理性の checks/warnings (soft 上限含む) を validity にマージする。
        prof_full = _extract_profile(g2hists)
        prof_ranges = _profile_ranges(g2hists, radiations, prof_full, histograms)
        prof_report = (
            check_profile_physicality(
                profiles=prof_full, radiations=radiations, ranges=prof_ranges
            )
            if any(prof_full)
            else ValidityReport(passed=True)
        )
        validity = ValidityReport(
            passed=validity.passed and prof_report.passed,
            checks=validity.checks + prof_report.checks,
            warnings=validity.warnings + prof_report.warnings + pre_warnings,
        )
        hist_profile = tuple({k: v for k, (v, _) in d.items()} for d in prof_full)
        # 解放フラグは捨てない (esd の有無とは別の問いに答える — model.py の宣言を参照)。
        hist_profile_refined = tuple({k: bool(r) for k, (_, r) in d.items()} for d in prof_full)
        hist_profile_esd = _profile_esd_map(g2hists)

        # 【final_rwp は常にデータ項】: 拘束の有無で出版値の意味が変わらないようにする
        #   (penalty 込みの値は `final_rwp_penalized` に分けて載せる)。拘束無効時は
        #   `StageResult.rwp` が GSAS 生値そのものなので現行とビット同一。
        final_rwp = stage_results[-1].rwp if stage_results else float("inf")
        final_gof = stage_results[-1].gof if stage_results else float("inf")
        final_rwp_penalized = stage_results[-1].rwp_penalized if stage_results else None
        # 【penalty は最終 gpx から読む】: `final_rwp` / `final_rwp_penalized` は**採用状態**
        #   (revert 後・研磨後) の値なので、penalty も同じ状態から採らなければ 3 つの数字が
        #   別々の状態を指す。最終 gpx の ``Rvals`` は定義上その採用状態そのもの (revert は
        #   スナップショットのファイル復元、研磨は上書き) なので、変数の受け渡しで揃えるより
        #   **構造的に**一致する。⚠ 拘束無効時は `Rvals` を 1 度も読まない (既定経路の非回帰)。
        final_restraint_penalty = _restraint_sum(gpx) if split_penalty else 0.0
        final_nobs = _nobs(gpx) if stage_results else 0
        phase_fractions = _phase_fraction_map(g2phases, g2hists)
        # 出版用の不確かさ: 格子 esd と GSAS 自身が算出した重量分率 (±esd)。共分散が無ければ空へ縮退。
        cell_esd = _cell_esd_map(g2phases)
        wt_fracs, wt_frac_esd = _weight_fraction_maps(g2phases, g2hists)
        # 原子パラメータ (FR-318 T7/T11: ラベルキー占有率/Uiso/多重度 + 占有率 esd の 2 状態)。
        atom_maps = _atom_result_maps(g2phases)
        micro = _microstructure_maps(g2phases, g2hists)
        resid_tt, resid_int, resid_sig = _extract_residual(g2hists, histograms)

        out_gpx = ""
        if keep_gpx is not None:
            gpx.save()
            shutil.copyfile(gpx_path, keep_gpx)
            out_gpx = keep_gpx

    return AutoRietveldResult(
        stage_results=tuple(stage_results),
        final_rwp=final_rwp,
        final_gof=final_gof,
        refined_cells=refined_cells,
        validity=validity,
        gpx_path=out_gpx,
        n_obs=final_nobs,
        phase_fractions=phase_fractions,
        residual_two_theta=resid_tt,
        residual_intensity=resid_int,
        residual_sigma=resid_sig,
        hist_profile=hist_profile,
        cell_esd=cell_esd,
        phase_weight_fractions=wt_fracs,
        phase_weight_fraction_esd=wt_frac_esd,
        atom_uiso=atom_maps.uiso,
        atom_occupancy=atom_maps.occupancy,
        atom_multiplicity=atom_maps.multiplicity,
        atom_occupancy_esd=atom_maps.occupancy_esd,
        final_rwp_penalized=final_rwp_penalized,
        final_restraint_penalty=final_restraint_penalty,
        undetermined_parameters=undetermined,
        undetermined_exempt=undetermined_exempt,
        # 出版値がどの母数集合の上に載っているか (救済 + 毎段プルーニング + 研磨の総和)。
        frozen_parameters=tuple(sorted(frozen_vars)),
        final_polish=final_polish,
        atom_coords=atom_maps.coords,
        atom_coord_esd=atom_maps.coord_esd,
        atom_coord_free_index=atom_maps.coord_free_index,
        atom_uiso_esd=atom_maps.uiso_esd,
        hist_profile_refined=hist_profile_refined,
        hist_profile_esd=hist_profile_esd,
        hap_size=micro[0],
        hap_mustrain=micro[1],
        hap_size_esd=micro[2],
        hap_mustrain_esd=micro[3],
    )


def _extract_residual(
    g2hists, histograms
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """先頭ヒストグラムの (2θ, Yobs−Ycalc, σ) を精密化レンジ内で返す (残差 S/N 判定用)。

    GSAS の getdata('Residual')=obs−calc、getdata('yweight')=1/σ² (計数統計の重み)。σ=1/√weight。
    レンジ外は calc=0 で残差=obs の偽ピークになるため two_theta_limits でマスクする。取得不能
    (getdata 失敗) は空タプルに縮退。numpy 不使用。
    """
    if not g2hists:
        return (), (), ()
    try:
        h0 = g2hists[0]
        xs = list(h0.getdata("x"))
        resid = list(h0.getdata("Residual"))
        weights = list(h0.getdata("yweight"))
    except Exception:
        return (), (), ()
    lim = histograms[0].two_theta_limits if histograms else None
    out_x: list[float] = []
    out_r: list[float] = []
    out_s: list[float] = []
    for xi, ri, wi in zip(xs, resid, weights):
        fx = float(xi)
        if lim is not None and not (lim[0] <= fx <= lim[1]):
            continue
        out_x.append(fx)
        out_r.append(float(ri))
        fw = float(wi)
        out_s.append((1.0 / math.sqrt(fw)) if fw > 0 else float("inf"))
    return tuple(out_x), tuple(out_r), tuple(out_s)


#: ジオメトリ別の GSAS Sample Parameters ``Type`` と、その分岐で使われるパラメータ既定値。
#: 値は GSAS-II 自身の初期化 (`GSASIIfiles.py` の ``Sample.update({...})``) と同一にする。
_SAMPLE_GEOMETRY: dict[Geometry, tuple[str, tuple[str, ...]]] = {
    Geometry.BRAGG_BRENTANO: (
        "Bragg-Brentano",
        ("Shift", "Transparency", "SurfRoughA", "SurfRoughB"),
    ),
    Geometry.DEBYE_SCHERRER: ("Debye-Scherrer", ("Absorption", "DisplaceX", "DisplaceY")),
}


def _apply_sample_geometry(hist, geometry: Geometry) -> None:
    """``HistogramSpec.geometry`` を GSAS の Sample Parameters ``Type`` に反映する。

    **宣言したジオメトリを正とする**。GSAS-II は ``Type`` を装置パラメータファイルから推定し
    (`GSASIIfiles.py`: ``Lam1`` があれば Bragg-Brentano、無ければ Debye-Scherrer)、Kα1 単色の
    instprm を使う実験室 X 線は反射光学系でも ``Debye-Scherrer`` になる。その状態で
    ``recipe._GEOMETRY_DISPLACEMENT`` の ``Shift`` を解放しようとすると
    ``ValueError('Unknown refinement parameter, Shift')`` で ``cell+displacement`` 段ごと
    revert され、**格子が一度も精密化されない**まま完走する (CaTeO3 M9 実データで発生)。

    ``Type`` はキー集合の問題ではない — `GSASIIstrIO` は ``Type`` で**変数にできる試料
    パラメータ**を選び、`GSASIIstrMath` は ``Type`` で**ピーク位置の補正式**を選ぶ
    (Bragg: ``Shift``/``Transparency`` · Debye: ``DisplaceX``/``DisplaceY``)。よって不足キーを
    足すだけでは変数にすらならず、無言で何も精密化しない状態が残る。

    既存の値は上書きしない (欠けているキーを補うだけ — GSAS 自身の ``Sample.update`` と同じ
    加算的な流儀)。他方のジオメトリのキーも消さない: どちらを使うかは ``Type`` だけが決める。
    """
    spec = _SAMPLE_GEOMETRY.get(geometry)
    if spec is None:
        return
    sample_type, keys = spec
    try:
        sample = hist.data["Sample Parameters"]
    except (KeyError, TypeError, AttributeError):
        return  # 想定外の形は fail open (精密化全体を落とさない)
    sample["Type"] = sample_type
    for key in keys:
        if key not in sample:
            sample[key] = [0.0, False]


def _data_fmthint(h: HistogramSpec) -> str:
    """HistogramSpec.data_format を GSAS-II importer ヒントへ写像する。"""
    return {
        "GSAS": "GSAS",
        "FXYE": "GSAS",  # .fxye も GSAS powder importer が読む
        "XYE": "xye",
        "XRDML": "Panalytical",  # Panalytical xrdml (xml) importer (実験室 X 線 in situ)
    }.get(h.data_format, "GSAS")
