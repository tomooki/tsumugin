"""薄い MCP 4 ツール (M8 要素3 + REQ-SAR-40x) — 実構造自動 Rietveld の計器+アクチュエータ。

閉ループの丸ごと (agentic_analyze) は **出さない**。③ (Claude Code) が以下を反復駆動して回す
(architecture.md §0, §6, 二重反転回避):

- ``auto_rietveld``: spec (JSON) を run_auto_rietveld で実行 → 段階別/最終 Rwp・格子・validity・
  **残差レポート**・**出版値** (重量分率 ± esd・格子 esd) を構造化して返す。spec ハンドルは
  stateless echo (サーバ状態なし)。残差配列
  (実データで 2392 点 × 3 本 ≈ 150KB) は跨がせず、小さなレポートのみサーバ側で算出して同梱する
  (operando 診断 ②, docs/design/operando-diagnosis/architecture.md §2)。
  ⚠ **``phase_weight_fractions`` が定量相分析の出版値**であり ``phase_fractions`` (Scale) ではない。
- ``propose_next_actions``: 直前結果 + 残差シグネチャ → ActionProposal[] (rationale/priority/**safe**)。
- ``refine_with_revisions``: spec + ③ が決めた AnalysisAction[] を適用して再実行。
- ``propose_data_preprocessing``: 観測ファイル → **データレンジ / 背景項数 / 除外領域候補**
  (① `autorietveld.autorange`, REQ-SAR-401/402/403)。**提案のみ** — 除外領域は自動適用しない
  (P-SAR-3: 未知相のピークをアーチファクトとして消すと相同定を殺す)。手で決めていた前処理
  (CaTeO3 の背景 24 項・T4 のデータリミット) を関数化したもので、返り値は ``auto_rietveld`` /
  ``sequential_rietveld`` の入力へそのまま貼れる。

**SDK 非依存**: 素の型 dict のみを返す (json.dumps allow_nan=False 安全)。GSAS は runner 内で遅延
import。runner は注入可能 (既定 GSAS 駆動; テストは決定論スタブ)。

信頼性: 🔵 architecture.md §6 の 3 ツール表 + docs/design/stable-auto-rietveld/architecture.md WS-4。
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from .._json import finite_or_none
from ..autorietveld import (
    AutoRietveldResult,
    HistogramSpec,
    PhaseSpec,
    StabilityOptions,
    ValidityReport,
)
from ..autorietveld.search import (
    CANDIDATE_NAMES,
    DEFAULT_CANDIDATES,
    RecipeCandidate,
    SearchConfig,
    run_recipe_search,
)
from ._degrade import degrade_oserror
from ._recipe_spec import stage_to_dict, stages_from_dicts
from ..refine_loop.action import AnalysisInput
from ..refine_loop.diagnostics import propose_next_actions as _propose
from ..refine_loop.orchestrator import _default_gsas_runner
from ..refine_loop.serialization import (
    action_from_dict,
    features_from_dicts,
    proposal_to_dict,
)
#: 反射位置を自前で立てるときの既定波長 (Cu Kα1 = 実験室 X 線であるという**主張**)。
#: `identify_and_add_phase` と**同じ定数を共有する** — 値を 2 系統持つと片方だけが古くなる。
from .insitu_tools import _CU_KA1
from .operando_diag_tools import residual_report_to_dict

Runner = Callable[[AnalysisInput], AutoRietveldResult]
#: 探索 (REQ-SAR-500) 用の候補ランナー。``Runner`` (AnalysisInput 版) とは**別の型**である —
#: 候補はレシピもヒストグラム (適応層のレンジ) も変えるので `AnalysisInput` では表せない。
#: `runner` と同じくテスト注入専用のシームで、実運用経路は JSON spec (``search``) である。
SearchRunner = Callable[[RecipeCandidate], AutoRietveldResult]

__all__ = [
    "RIETVELD_TOOLS",
    "auto_rietveld",
    "propose_data_preprocessing",
    "propose_next_actions",
    "refine_with_revisions",
]


def _specs_dict(inp: AnalysisInput) -> dict[str, object]:
    """spec ハンドル (stateless echo): ③ が refine_with_revisions へ差し戻すための往復可能な spec。

    ``stages`` (Issue #101: ③ が渡した追加段階 = ``AnalysisInput.extra_stages``) も同梱する —
    背景係数と同じく、渡した spec がそのまま往復できないと ③ は次呼び出しで追加段階を失う。
    """
    return {
        "histograms": [h.to_dict() for h in inp.histograms],
        "phases": [p.to_dict() for p in inp.phases],
        "background_coeffs": inp.background_coeffs,
        "stages": [stage_to_dict(s) for s in inp.extra_stages],
    }


def _residual_report_dict(result: AutoRietveldResult) -> dict[str, object] | None:
    """精密化結果から残差レポートを**サーバ側で**算出し素の型 dict で返す (None = 残差なし)。

    【配列を跨がせない】: ``residual_two_theta``/``residual_intensity``/``residual_sigma`` は実データで
      2392 点 × 3 本 ≈ 150KB あり、MCP 境界を跨がせるべきでない。一方レポートは数個の float +
      ~6 特徴と小さいため、ここで算出して同梱する。これにより ③ (MCP しか触れない skill) が
      残差診断 (J2/J3: 未説明ピーク → 欠落相/対称性低下) を**再精密化なしに**行える
      (architecture.md §2 の ``residual_report`` 行)。
    【縮退】: ``residual_report_from_result`` は残差フィールドが空/長さ不一致/全点非有限のとき
      None を返す (後方互換の既定は空タプル = スタブ runner や旧構築)。その場合は None を返し、
      呼び出し側が ``"residual_report": None`` として出す (キーは常に存在させスキーマを安定させる)。
    """
    from ..autorietveld.residual_report import residual_report_from_result

    rep = residual_report_from_result(result)
    if rep is None:
        return None
    return residual_report_to_dict(rep)


def _result_to_dict(result: AutoRietveldResult, inp: AnalysisInput) -> dict[str, object]:
    """AutoRietveldResult + spec を素の型 dict へ (③ の判断入力)。"""
    return {
        "specs": _specs_dict(inp),
        # 【final_rwp は常に**データ項のみ**】: restraint を χ² に入れても意味が切り替わらない
        #   (`AutoRietveldResult.final_rwp` の契約)。penalty 込みの生 Rwp は別キーで並べる —
        #   ③ が 2 つの値を**同じ列**として比較しないための分離。
        "final_rwp": finite_or_none(result.final_rwp),
        "final_gof": finite_or_none(result.final_gof),
        # 拘束を χ² に入れたときだけ非 None (None = penalty なし = final_rwp と同義)。
        #   ここを落とすと ③ から見て「拘束がどれだけ引いているか」が結果に一切現れない。
        "final_rwp_penalized": finite_or_none(result.final_rwp_penalized),
        "final_restraint_penalty": finite_or_none(result.final_restraint_penalty),
        "n_obs": result.n_obs,
        "stages": [
            {
                "label": s.label,
                "rwp": finite_or_none(s.rwp),
                "rwp_penalized": finite_or_none(s.rwp_penalized),
                "gof": finite_or_none(s.gof),
                "n_params": s.n_params,
                "converged": bool(s.converged),
                "reverted": bool(s.reverted),
                # 【note を落とさない (★ ②到達可能性)】: 段の所見 (``unconverged`` /
                #   ``noop`` / ``pruned=N`` / ``bound_hits=N`` / ``auto_frozen_cells=…``) は
                #   **ここにしか出ない**。ledger は ② の戻り値に含まれないので、note を落とすと
                #   ③ から見て診断ゲートも箱拘束も「結果に何も現れない」機能になる。
                "note": s.note,
            }
            for s in result.stage_results
        ],
        "refined_cells": {
            # 発散/崩壊した精密化で GSAS が NaN/Inf セルを返しうるため finite_or_none で None 化
            # (allow_nan=False の json.dumps クラッシュを防ぐ; 他フィールドと同一規律)。
            name: [finite_or_none(x) for x in cell] for name, cell in result.refined_cells.items()
        },
        "validity": {
            "passed": bool(result.validity.passed),
            "checks": [[name, bool(ok), detail] for name, ok, detail in result.validity.checks],
            "warnings": list(result.validity.warnings),
        },
        # 【残差レポート同梱 (operando 診断 ②)】: 大きな残差配列は跨がせず、小さなレポートのみを
        #   サーバ側で算出して返す。残差フィールドが空 (既定/スタブ) なら None (キーは常に存在) 🔵
        "residual_report": _residual_report_dict(result),
        # 【出版値 (Issue #96 レビュー)】: `phase_fractions` は **Scale** であって重量分率ではない。
        #   単位胞質量が相間で異なると乖離する (実測 K2Mn[Fe(CN)6] tetra: 同じ fit で 65.6 Scale%
        #   が 47.2 wt%。乖離はフレーム毎に違い [実測 1.39-1.62 倍]、大きさは単位胞質量比
        #   [cubic 1103.4 / tetra 517.8 amu = 2.13 倍] と分率で決まる = **換算係数は無い**)。
        #   定量相分析の出版値は重量分率であり、esd を伴わない
        #   精密化値は出版できない。① にあっても ② に無ければ ③ は受け取れない (★ 規則)。
        #   キーは常に存在させる (欠落と「esd=0」を ③ が取り違えないため; residual_report と同一規律)。
        "phase_weight_fractions": {
            name: finite_or_none(v) for name, v in result.phase_weight_fractions.items()
        },
        "phase_weight_fraction_esd": {
            name: finite_or_none(v) for name, v in result.phase_weight_fraction_esd.items()
        },
        "cell_esd": {
            name: [finite_or_none(x) for x in esd] for name, esd in result.cell_esd.items()
        },
        # 【精密化座標 + esd】: 座標は出版値なので esd とセットで出す。**esd の 3 状態を潰さない** —
        #   ``>0.0`` = 精密化した su / ``0.0`` = 対称拘束で厳密に固定 (真の陳述) /
        #   ``null`` = この精密化では決まっていない。0.0 と null を同一視すると「厳密に固定された
        #   座標」と「決まらなかった座標」が読み分けられなくなる (`cell_esd` と同じ規律)。
        "atom_coords": {
            phase: {label: [finite_or_none(x) for x in xyz] for label, xyz in atoms.items()}
            for phase, atoms in result.atom_coords.items()
        },
        # 【微細構造 (サイズ/微小歪み) + esd】: **収束の判定対象は「構造 + 歪」**なので、
        #   歪は装置プロファイル (nuisance) と分けて出す。
        "hap_size": {
            ph: {h: finite_or_none(v) for h, v in d.items()}
            for ph, d in result.hap_size.items()
        },
        "hap_mustrain": {
            ph: {h: finite_or_none(v) for h, v in d.items()}
            for ph, d in result.hap_mustrain.items()
        },
        "hap_size_esd": {
            ph: {h: finite_or_none(v) if v is not None else None for h, v in d.items()}
            for ph, d in result.hap_size_esd.items()
        },
        "hap_mustrain_esd": {
            ph: {h: finite_or_none(v) if v is not None else None for h, v in d.items()}
            for ph, d in result.hap_mustrain_esd.items()
        },
        "atom_coord_esd": {
            phase: {label: [finite_or_none(x) for x in esd] for label, esd in atoms.items()}
            for phase, atoms in result.atom_coord_esd.items()
        },
        # 【決まらなかったパラメータ (REQ-SAR-103)】: 最終収束後に残った ``esd >= |値|``。
        #   **これは失敗ではなく所見** — 「このデータではこのパラメータは決まらない」という
        #   情報であり、③ がモデルを疑う材料になる (NaCuHCF の占有率発散が Ow 必要性の決め手に
        #   なったのと同種の診断信号)。凍結して隠さず、そのまま渡す。
        #   ⚠ 空リストは「弱い変数が無かった」**ではなく**「診断を要求していない」ことがある —
        #   `stability.report_undetermined` を立てて初めて埋まる。
        "undetermined_parameters": [w.to_dict() for w in result.undetermined_parameters],
        # 比 (``esd/|値|``) が構造的に意味を持たないため判定対象外にした変数 (既定 dAx/dAy/dAz)。
        #   捨てずに並べるのは、報告が**何を見なかったか**を隠さないため。
        "undetermined_exempt": [w.to_dict() for w in result.undetermined_exempt],
        # この結果の fit で凍結されていた変数 (救済 + 毎段プルーニング + 最終研磨)。
        #   出版値がどの母数集合の上に載っているかを ③ が読める唯一の窓。
        "frozen_parameters": list(result.frozen_parameters),
        # 最終研磨 (opt-in) の記録。null = 研磨していない。非 null かつ ``applied`` なら
        #   **final_rwp は一部の変数を凍結した fit の値**である (黙って意味を変えない)。
        "final_polish": result.final_polish.to_dict() if result.final_polish else None,
        "gpx_path": result.gpx_path,
    }


def _result_from_dict(result: Mapping[str, object]) -> AutoRietveldResult:
    """propose_next_actions が使う最小フィールドで AutoRietveldResult を復元する。"""
    v = result.get("validity") or {}
    validity = ValidityReport(
        passed=bool(v.get("passed", True)),
        checks=tuple(
            (str(name), bool(ok), str(detail)) for name, ok, detail in v.get("checks", ())
        ),
        warnings=tuple(str(w) for w in v.get("warnings", ())),
    )
    cells = {
        name: tuple(float(x) for x in cell)
        for name, cell in (result.get("refined_cells") or {}).items()
    }
    rwp = result.get("final_rwp")
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=float(rwp) if rwp is not None else float("inf"),
        final_gof=float(result.get("final_gof") or 0.0),
        refined_cells=cells,
        validity=validity,
        n_obs=int(result.get("n_obs") or 0),
    )


def _build_input(
    histograms: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    background_coeffs: int,
    extra_stages: Sequence[Mapping[str, object]] | None = None,
) -> AnalysisInput:
    """spec (JSON) を `AnalysisInput` へ変換する。

    :param extra_stages: 段階解放レシピの追加段階 spec (Issue #101: ``AnalysisInput.extra_stages``
        への到達口)。不正な段階 spec は `stages_from_dicts` が ``ValueError`` を送出する
        (呼び出し側が error dict へ縮退する)。
    """
    return AnalysisInput(
        histograms=tuple(HistogramSpec.from_dict(h) for h in histograms),
        phases=tuple(PhaseSpec.from_dict(p) for p in phases),
        background_coeffs=background_coeffs,
        extra_stages=stages_from_dicts(extra_stages),
    )


def _run_search(
    inp: AnalysisInput,
    names: Sequence[str],
    search_config: Mapping[str, object] | None,
    max_cyc: int,
    opts: StabilityOptions,
    search_runner: "SearchRunner | None",
) -> dict:
    """レシピ探索を実行し「採用候補の結果 + 候補表」を返す (REQ-SAR-500/501)。

    返り値は**通常の `auto_rietveld` と同じ形**に ``search`` キーを足したものにする。③ が
    「探索したときだけ別の読み方をする」必要が無いようにするためで、``specs`` は**採用候補の
    入力** (適応層が変えたレンジ/背景を含む) を返すので、そのまま `refine_with_revisions` へ
    持ち回れる。
    """
    from dataclasses import replace as _replace

    summary = run_recipe_search(
        inp.histograms,
        inp.phases,
        names=names,
        background_coeffs=inp.background_coeffs,
        config=SearchConfig.from_dict(search_config),
        runner=search_runner,
        # ③ が渡した追加段階は**全候補の末尾**に足す (どの候補で試したかで意味が変わらない)。
        candidates=None if not inp.extra_stages else _with_extra_stages(inp, names),
        max_cyc=max_cyc,
        stability=opts,
    )
    selected = summary.selected
    if selected is None or selected.result is None:
        return {
            "error": "探索の全候補が失敗しました: " + " / ".join(summary.warnings),
            "error_type": "RecipeSearchFailed",
            "search": summary.to_dict(),
        }
    chosen = _replace(
        inp,
        histograms=selected.candidate.histograms,
        background_coeffs=selected.candidate.background_coeffs,
    )
    payload = _result_to_dict(selected.result, chosen)
    payload["search"] = summary.to_dict()
    return payload


#: `multistart` spec が受け付けるキー (閉じた語彙 — 未知キーは大声で落とす)。
_MULTISTART_KEYS = frozenset(
    {"n_starts", "lattice_frac", "coord_jitter_ang", "jitter_seed", "jobs"}
)


def _run_convergence(
    inp: AnalysisInput,
    names: "Sequence[str]",
    search_config: "Mapping[str, object] | None",
    multistart: "Mapping[str, object]",
    max_cyc: int,
    opts: StabilityOptions,
    search_runner: "SearchRunner | None",
) -> dict:
    """規定の標準経路 (手順最適化 → 収束確認) を実行する。

    返り値は**通常の `auto_rietveld` と同じ形**に ``search`` と ``convergence`` を足したもの。
    ③ が「収束確認したときだけ別の読み方をする」必要が無いようにする (探索と同じ規律)。

    ⚠ ``final_rwp`` 以下は**収束確認の最良フィット**である (単発ではなく)。同じ手順で複数点
    走らせた最良は単発と同等以上なので、単発を返すと確認のために回した計算を捨てることになる。
    """
    from dataclasses import replace as _replace

    from ..autorietveld.confirm import optimize_then_confirm

    unknown = set(multistart) - _MULTISTART_KEYS
    if unknown:
        raise ValueError(
            f"multistart に未知のキー {sorted(unknown)} があります "
            f"(許容キー: {sorted(_MULTISTART_KEYS)})"
        )
    if inp.extra_stages:
        # 【黙って落とさない】: `optimize_then_confirm` は候補を**名前**で受けるので、③ が
        #   渡した追加段階を運ぶ口が無い。黙って無視すると「追加段階つきで収束確認した」と
        #   読まれる — 実際には確認していない手順の傍証になる。
        raise ValueError(
            "extra_stages と multistart は同時に指定できません "
            "(収束確認は候補名で手順を固定するため追加段階を運べない)。"
            "追加段階を試すなら search 単独で、収束確認するなら extra_stages なしで呼ぶ"
        )
    kwargs = {k: multistart[k] for k in _MULTISTART_KEYS if k in multistart}
    report = optimize_then_confirm(
        inp.histograms,
        inp.phases,
        candidates=tuple(names),
        search_config=SearchConfig.from_dict(search_config),
        background_coeffs=inp.background_coeffs,
        max_cyc=max_cyc,
        stability=opts,
        search_runner=search_runner,
        **kwargs,  # type: ignore[arg-type]
    )
    if report.best is None:
        return {
            "error": "手順が 1 つも立たなかったため収束確認へ進めませんでした: "
            + " / ".join(report.warnings),
            "error_type": "ConvergenceNotAttempted",
            "convergence": report.to_dict(),
        }
    selected = report.search.selected if report.search is not None else None
    chosen = inp
    if selected is not None:
        chosen = _replace(
            inp,
            histograms=selected.candidate.histograms,
            background_coeffs=selected.candidate.background_coeffs,
        )
    payload = _result_to_dict(report.best, chosen)
    if report.search is not None:
        payload["search"] = report.search.to_dict()
    payload["convergence"] = report.to_dict()
    return payload


def _with_extra_stages(inp: AnalysisInput, names: Sequence[str]) -> tuple[RecipeCandidate, ...]:
    """全候補のレシピ末尾に ``AnalysisInput.extra_stages`` を足した候補列を組む。"""
    from dataclasses import replace as _replace

    from ..autorietveld.search import build_candidates

    base = build_candidates(
        inp.histograms, inp.phases, background_coeffs=inp.background_coeffs, names=names
    )
    return tuple(_replace(c, stages=(*c.stages, *inp.extra_stages)) for c in base)


def _search_names(search: "bool | Sequence[str]") -> tuple[str, ...]:
    """``search`` 引数を候補名の列へ正規化する。

    ``True`` は全候補、名前の列は**その部分集合**を意味する。名前を 1 つだけ渡す使い方
    (``["serious"]``) は「そのレシピ 1 本で回す」に等しく、**探索で勝ったレシピを次の反復でも
    使い続ける唯一の JSON 経路**である (② には既定レシピを丸ごと差し替える引数が無い)。

    **空列 (``[]``/``""``) は ``ValueError``** (レビュー LOW-5): 空は「探索しない」ではなく
    「探索したい候補が 1 つも残らなかった」であり、両者を同一視すると**候補名をフィルタして空に
    なった呼び手が黙って別経路 (探索なし) を踏む** — 返り値から ``search`` キーが消えるだけで、
    ③ には「探索したが全滅した」との区別が付かない。PR #129 で塞いだ ``instrument.recipe: []``
    のサイレント失敗と同型なので、同じ規律 (② は error dict へ縮退) を適用する。
    明示的に探索しないときは ``search`` を省略するか ``false``/``null`` を渡す。
    """
    if search is True:
        # ★``true`` は**実測で選んだ既定集合**を回す。`CANDIDATE_NAMES` は「選べる名前」の
        #   集合であり、測定で支配された候補 (後方互換のために残してある `serious` 2 周) を
        #   含む — それを既定で回すと ③ は毎回 1.4 倍の時間を払って何も得ない。
        return DEFAULT_CANDIDATES
    if isinstance(search, str):  # "serious" のような単一名を親切に受ける
        if not search:
            raise ValueError(
                "search が空文字です。探索しないなら search を省略 (または false) してください "
                f"(候補名: {list(CANDIDATE_NAMES)})"
            )
        return (search,)
    names = tuple(str(n) for n in search)
    if not names:
        raise ValueError(
            "search が空列です。空は「探索しない」ではなく「候補が 1 つも残らなかった」なので "
            "黙って探索なし経路へは落としません。探索しないなら search を省略 (または false)、"
            f"探索するなら候補名を 1 つ以上指定してください (候補名: {list(CANDIDATE_NAMES)})"
        )
    return names


@degrade_oserror
def auto_rietveld(
    histograms: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    *,
    background_coeffs: int = 6,
    stages: Sequence[Mapping[str, object]] | None = None,
    max_cyc: int = 12,
    stability: Mapping[str, object] | None = None,
    search: "bool | Sequence[str] | None" = None,
    search_config: Mapping[str, object] | None = None,
    multistart: Mapping[str, object] | None = None,
    seed: int = 0,
    runner: Runner | None = None,
    search_runner: SearchRunner | None = None,
) -> dict:
    """spec (JSON) を run_auto_rietveld で実行し段階別/最終メトリクスを構造化して返す (計器)。

    :param histograms: HistogramSpec.to_dict の列
    :param phases: PhaseSpec.to_dict の列
    :param background_coeffs: 初期背景係数数
    :param stages: **段階解放レシピの追加段階** (Issue #101)。``build_recipe`` が生成する既定
        レシピの末尾に追加される (``AnalysisInput.extra_stages`` と同じ意味論)。各要素は
        ``{"label": str, "flags": {GSAS 語彙}, "note": str (省略可)}``
        (語彙は ``autorietveld.recipe`` docstring 参照: ``profile_lorentzian``/``tof_profile``/
        ``size_strain``/``preferred_orientation``/``absorption`` 等)。不正なキー/型は
        ``{"error","error_type"}`` へ縮退する (黙って無視しない)。既定 None (追加段階なし・非回帰)。
    :param max_cyc: 各段階の最大精密化サイクル (``run_auto_rietveld`` へ転送。既定 12 は非回帰)。
        ``runner`` を明示注入した場合はそちらの責務になり本引数は無視される。
    :param stability: **安定性診断ゲート + 箱拘束** (stable-auto-rietveld)。
        診断 (WS-1): ``{"require_convergence": true, "max_shift_esd": 1.0, "extra_cycles": 1,
        "detect_noop_stages": true, "record_weak_vars": true, "report_undetermined": true,
        "record_correlations": true}``。
        収束判定 (未収束段を追加サイクル → 駄目なら revert) / no-op 段の警告 / 弱い変数
        (``esd >= |値|``) の観測と報告 / 高相関ペアの記録を opt-in で有効化する。
        **弱い変数の扱いはタイミングで分かれる** (REQ-SAR-103。軸は「凍結は判断、記録は観測」):
        ``record_weak_vars`` = 各段で ledger に記録するだけ (凍結しない) /
        ``report_undetermined`` = 最終収束後に残ったものを ``undetermined_parameters`` へ
        **所見として報告** /
        ``polish_frozen_undetermined`` = それを凍結して 1 回精密化し直す (opt-in。有効時
        ``final_rwp`` は**一部を凍結した fit** の値になり ``final_polish`` で判別できる) /
        ``rescue_freeze_on_failure`` = 段が収束しない/``SVD0>0`` のときだけ最弱を凍結して再試行 /
        ``prune_weak_vars_each_stage`` = **旧挙動** (受理された段のたびに永続凍結)。母数が
        不可逆に痩せる (実測 ``n_params`` が S2 で 7→4) ため既定 OFF の逃げ道。
        拘束 (WS-2): ``{"bound_cell": 0.05, "bound_displacement": 5000.0,
        "bound_size_strain": true, "enable_restraints": true}``。**装置・幾何パラメータだけ**に
        箱拘束 (格子 ±X% / 試料変位 µm / Size・Mustrain の正値性) を張り、境界に到達したら
        所見にする (握り潰さない)。⚠ **占有率・Uiso・座標には箱を張らない** — 異常値はモデル
        誤りの診断信号であり、握り潰すと NaCuHCF model5/model6 のような判別ができなくなる
        (そのためのキーは存在しない)。``enable_restraints`` は登録済み restraint
        (``bond_restraints``/``chem_comp_restraints``) を χ² に入れる (既定 OFF — GSAS-II は
        headless では penalty を目的関数から外すため、有効にしない限り拘束は効かない)。
        ⚠ **``report_undetermined`` との併用が必須**で、単独指定は error dict になる
        (拘束は実質的に母数を増やすので、何が決まらなかったかを見ないまま回させない)。
        有効時、``final_rwp`` / ``stages[*].rwp`` は **penalty を除いたデータ項のみの Rwp**
        (段の受理/revert もこの値で判定する — 拘束は「引く力」であって適合の悪化ではない)。
        penalty 込みの GSAS 生値は ``final_rwp_penalized`` / ``stages[*].rwp_penalized``、
        penalty の絶対量は ``final_restraint_penalty`` に別キーで出る (拘束なしなら ``null``)。
        ⚠ **これら 3 つは「採用状態」(段が revert されたなら revert 後) の値**で揃えてある。
        拘束が**捨てられた試行の中で**どう振る舞ったか (誤ったターゲットなら段は正しく
        revert されるので、そこにしか痕跡が残らない) は ledger
        ``m7_stage_restraint_split`` の ``trial_*`` を見ること — ② の戻り値には**載せない**
        (出版される fit を説明する数字と混ぜないため)。
        判定結果は返り値の ``undetermined_parameters`` / ``undetermined_exempt`` /
        ``frozen_parameters`` / ``final_polish`` と、ledger (``m7_stage_unconverged``/
        ``m7_stage_noop``/``m7_stage_weak_vars``/``m7_stage_rescue``/``m7_stage_prune``/
        ``m7_undetermined``/``m7_final_polish``/``m7_stage_correlation``/``m7_box_bounds``/
        ``m7_stage_bound_hit``) と ``stages[*].note``
        (``unconverged``/``noop``/``rescue_frozen=N``/``pruned=N``/``bound_hits=N``) に出る。
        **未知キーは error dict へ縮退**する (黙って無視しない)。
        既定 None = 現行と同一挙動 (共分散も Controls も触らない)。``runner`` 注入時は無視される。
    :param search: **レシピ探索** (REQ-SAR-500)。``true`` で全候補
        (``["default", "serious", "adaptive"]``)、名前の列でその部分集合を実行し、
        **「収束したものの中で最良」**を採る。単一レシピは全データで勝てない (実測: T1 は
        ``default`` 9.81% / T3 は ``serious`` 6.10% が勝つ) ので、本気の単一フレーム解析では
        探索を既定の一手にする。返り値に ``search`` (候補ごとの Rwp/収束/tier/採否と警告) が
        付き、``final_rwp`` 以下は**採用候補の結果**になる。``specs`` も採用候補の入力を返すので
        持ち回れば同じ土俵で継続できる。⚠ **operando (`sequential_rietveld`) では使わない**
        — フレーム数 × 候補数の積は時間予算に収まらない (REQ-SAR-502)。既定 None (探索なし・
        現行と同一)。``false``/``null`` は明示的に「探索しない」。**空列 ``[]`` は error dict**
        (「探索しない」ではなく「候補が 1 つも残らなかった」なので黙って別経路へ落とさない)。
    :param search_config: 探索の判定閾値 ``{"rwp_tie_eps": 0.1, "disagreement_rwp_eps": 0.5,
        "cell_rel_tol": 0.001, "fraction_abs_tol": 0.02, "require_convergence": true}``。
        ``rwp_tie_eps`` 以内の同点は **BIC** で裁定し (母数の違う候補を Rwp だけで比べない)、
        ``disagreement_rwp_eps`` 以内で答えが割れたら**順序依存の警告**を出す (REQ-SAR-501)。
        未知キーは error dict へ縮退する。既定 None (既定値)。
    :param multistart: **収束確認** (規定の標準経路)。``{"n_starts": 5, "lattice_frac": 0.007,
        "coord_jitter_ang": 0.05, "jitter_seed": 0, "jobs": 5}``。渡すと手順最適化 (Phase A) の
        あと、採用手順を固定したまま初期値を振って (Phase B) **何が収束し何が初期値依存か**を
        返す。返り値の ``convergence.structure_is_corroborated`` が解の採用可否、
        ``convergence.undetermined_by_initial_values`` が**出版してはならない値**である。
        引数はすべてスカラなので他ツールの出力を要しない (§4.5 到達可能性)
    :param seed: 既定 GSAS runner 用乱数種
    :param runner: 注入 runner (None なら GSAS 駆動)。テスト用の内部シーム
    :param search_runner: 探索用の候補ランナー注入 (テスト用の内部シーム)。``search`` 指定時に
        ``runner`` ではなくこちらが使われる — 候補はレシピもレンジも変えるため
        ``AnalysisInput`` では表現できない
    """
    try:
        inp = _build_input(histograms, phases, background_coeffs, stages)
        opts = StabilityOptions.from_dict(stability)
        # 【`if search:` にしない】: 空列 `[]` は falsy なので**黙って探索なし経路**へ落ちる。
        #   「探索しない」(None/false) と「候補が空」(=[]) を区別し、後者は _search_names が
        #   ValueError → error dict へ縮退させる (LOW-5)。
        if multistart is not None:
            # 【収束確認は探索を含む】: 規定の標準経路は「手順最適化 → 収束確認」なので、
            #   `multistart` を渡したら Phase A も回す (`search` 未指定なら既定候補集合)。
            #   分けて渡させると「探索せずに収束確認」= 決めていない手順を確認する、という
            #   意味を成さない呼び方が可能になる。
            names = _search_names(search) if search not in (None, False) else DEFAULT_CANDIDATES
            return _run_convergence(
                inp, names, search_config, multistart, max_cyc, opts, search_runner
            )
        if search is not None and search is not False:
            return _run_search(
                inp, _search_names(search), search_config, max_cyc, opts, search_runner
            )
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}
    run = runner or _default_gsas_runner(seed, max_cyc=max_cyc, stability=opts)
    return _result_to_dict(run(inp), inp)


def propose_next_actions(
    result: Mapping[str, object], features: Sequence[Mapping[str, object]]
) -> dict:
    """直前結果 + 残差シグネチャから次手候補を返す (計器・提案のみ)。

    :param result: auto_rietveld / refine_with_revisions の出力
    :param features: ResidualFeatures 相当の dict 列 (③ or 別ツールが供給)
    """
    reconstructed = _result_from_dict(result)
    feats = features_from_dicts(features)
    proposals = _propose(reconstructed, feats)
    return {"proposals": [proposal_to_dict(p) for p in proposals]}


@degrade_oserror
def refine_with_revisions(
    histograms: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    actions: Sequence[Mapping[str, object]],
    *,
    background_coeffs: int = 6,
    stages: Sequence[Mapping[str, object]] | None = None,
    max_cyc: int = 12,
    stability: Mapping[str, object] | None = None,
    seed: int = 0,
    runner: Runner | None = None,
) -> dict:
    """③ が決めた AnalysisAction[] を spec に適用して再実行する (アクチュエータ)。

    SafeAction (背景/パラメータ) も ModelAction (リミット/相追加/構造改訂) も適用できる。
    採否の判断は ③ が済ませた前提 (このツールは適用+再実行のみ)。

    :param stages: `auto_rietveld` と同じ意味論の追加段階 spec (Issue #101)。``ReleaseParams``
        action が足す段階 (`AnalysisAction.apply` 経由) と共存する。合成順は
        **``stages`` が先 (既定レシピ直後) → action 由来の段階が末尾**
        (`_build_input` が stages を extra_stages に置いた後、actions ループが apply で末尾に足す)。
        不正な段階 spec は error dict へ縮退する。
    :param max_cyc: `auto_rietveld` と同じ (既定 GSAS runner への転送)。
    :param stability: `auto_rietveld` と同じ安定性診断ゲート + 箱拘束 spec (既定 None = 非回帰)。
        箱拘束 (``bound_cell``/``bound_displacement``/``bound_size_strain``) と restraint 有効化
        (``enable_restraints``, 要 ``report_undetermined``) も同じキーで到達できる。
    """
    try:
        inp = _build_input(histograms, phases, background_coeffs, stages)
        for a in actions:
            inp = action_from_dict(a).apply(inp)
        opts = StabilityOptions.from_dict(stability)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}
    run = runner or _default_gsas_runner(seed, max_cyc=max_cyc, stability=opts)
    return _result_to_dict(run(inp), inp)


# ===========================================================================
# データ前処理の提案 (REQ-SAR-401/402/403) — ① `autorietveld.autorange` の ② 露出
# ===========================================================================


def _explained_positions(
    phases: Sequence[Mapping[str, object]],
    wavelength: float | None,
    two_theta_range: "tuple[float, float]",
) -> "tuple[tuple[float, ...], str]":
    """相 spec (CIF) から「相が説明する反射位置」を立てる → ``(位置, 出所)``。

    ``propose_excluded_regions(explained_two_theta=)`` の**到達可能性**を作るための層である
    (§4.5: 各引数について「どの ② ツールの出力から来るのか」を言えること)。② に反射位置を返す
    ツールは無いので、③ が既に持っている **`PhaseSpec` (+ `refined_cells`)** から
    サーバ側で立てる — `identify_and_add_phase(known_phases=)` と同じ入力の形にしてある。

    **波長を知らない (`None`) なら立てない**: hkl→2θ は波長に直接効くため、λ=0.7996 の放射光を
    Cu Kα1 として扱うと 2θ が数度ずれ、「説明済み」判定が丸ごと誤る。推測するより
    「未確認」と答える方が安全である (③ には ``explained_source`` で見える)。

    :returns: ``(2θ 位置の昇順タプル, 出所)``。出所は ``"phases"`` / ``"none"`` (相未指定) /
        ``"unavailable"`` (pymatgen 不在 or CIF 読込失敗) / ``"wavelength_unknown"``
    """
    if not phases:
        return (), "none"
    if wavelength is None:
        return (), "wavelength_unknown"

    from ..insitu.phaseid import phasespec_to_reference
    from .insitu_tools import _parse_known_phases

    positions: list[float] = []
    converted = 0
    for spec, cell in _parse_known_phases(phases):
        ref = phasespec_to_reference(
            spec,
            refined_cell=cell,
            wavelength=float(wavelength),
            two_theta_range=two_theta_range,
        )
        if ref is None:  # pymatgen 不在 / CIF 読込失敗 → 安全側 (未確認) へ縮退
            continue
        converted += 1
        positions.extend(float(p.position) for p in ref.peaks)
    if converted == 0:
        return (), "unavailable"
    return tuple(sorted(positions)), "phases"


@degrade_oserror
def propose_data_preprocessing(
    path: str,
    *,
    data_format: str | None = None,
    excluded_regions: Sequence[Sequence[float]] | None = None,
    phases: Sequence[Mapping[str, object]] = (),
    wavelength: float | None = _CU_KA1,
    explained_two_theta: Sequence[float] | None = None,
    background_ladder: Sequence[int] | None = None,
    snr_min: float = 5.0,
    min_fraction_kept: float = 0.15,
    reason: str = "",
) -> dict:
    """観測ファイル → **データレンジ / 背景項数 / 除外領域候補**を提案する (計器・提案のみ)。

    ① `autorietveld.autorange` (REQ-SAR-401/402/403) の ② 露出。**人が手で決めていた前処理**を
    関数にしたもので、返り値は `auto_rietveld` / `sequential_rietveld` の入力へそのまま貼れる:

    | 返り値 | 貼り先 |
    |---|---|
    | ``two_theta_range.two_theta_limits`` | ``HistogramSpec.two_theta_limits`` / ``FrameSpec`` 同名 |
    | ``background_terms.recommended`` (or ``candidates``) | ``auto_rietveld(background_coeffs=)`` |
    | ``excluded_region_candidates.candidates[].{lower,upper}`` | ``HistogramSpec.excluded_regions`` |

    **⛔ 除外領域は自動適用しない** (P-SAR-3)。除外は解析の解釈を変える操作であり、未知相の
    ピークをアーチファクトとして消せば相同定を殺す。``requires_human_approval`` は常に true で、
    **本ツール自身も提案候補を自分のレンジ判定へ流し込まない** — 承認済みの区間だけを
    ``excluded_regions`` 引数で明示的に渡すこと (提案を内部で自己適用したら「提案のみ」が嘘になる)。

    `assess_data_quality` との違い: あちらは operando の**背景減算検出 + 上限 1 値**の助言
    (esd 非対応・切り詰めガードなし)。本ツールは **下限/上限の組**を返し esd を noise 推定に使い、
    切り詰め量にガードを掛ける。契約が違うので統合していない (同じ信号終端域を指すことは
    ``test_range_upper_is_consistent_with_dataquality_single_limit`` が縛っている)。

    :param path: 観測データファイルパス (``HistogramSpec.data_path`` と同じもの)
    :param data_format: 形式名。語彙は `assess_data_quality` / ``reference.io.load_pattern`` と共通
        ("XY"/"XYE"/"XRDML"/"FXYE"/"GSAS"/"INT"/"IGOR")。None は "XY"。
        3 列 ascii の "XY"/"XYE" のみ esd を保持し、noise 推定を計数統計にできる
    :param excluded_regions: **既に承認済み**の除外区間 ``[lo, hi]`` の列。上限判定から外す
        (寄生ピークを混ぜると上限がそこまで押し出される)
    :param phases: 相 spec の列 (``PhaseSpec.to_dict()`` + 任意の ``refined_cell`` [a,b,c,α,β,γ])。
        除外候補の「どの相でも説明できない」判定に使う反射位置を CIF から立てる。
        ``auto_rietveld`` に渡した ``phases`` と ``refined_cells`` をそのまま貼れる。
        **渡さないと偽陽性が増える** (``note`` に警告が出る)
    :param wavelength: 反射位置生成の線源波長 (Å)。既定 Cu Kα1。**放射光/中性子では実波長を必ず
        渡す**。判らないときは ``None`` — 推測せず反射位置生成を止める (``explained_source``)
    :param explained_two_theta: 反射位置を**既に手元に持つ**呼び手のための明示入力
        (``phases`` より優先)。算出元は問わない
    :param background_ladder: 背景項数の梯子 (既定 ``[6, 12, 18, 24, 36]``)
    :param snr_min: レンジ判定の窓内 S/N 閾値
    :param min_fraction_kept: 残さなければならない点数比の下限 (これを割る提案は中心を保って広げる)
    :returns: ``two_theta_range`` / ``background_terms`` / ``excluded_region_candidates`` /
        ``explained_source`` / ``reason``。読み込み失敗・引数不正は ``{"error", "error_type"}``
    """
    from dataclasses import asdict

    from ..autorietveld.autorange import (
        propose_excluded_regions,
        suggest_background_terms,
        suggest_two_theta_range,
    )
    from .operando_diag_tools import _load_pattern_with_esd, _parse_excluded_regions

    try:
        regions = _parse_excluded_regions(excluded_regions)
        x, y, esd = _load_pattern_with_esd(path, data_format)
        if x.size == 0:
            raise ValueError(
                f"観測データが空です: {path!r}。空パターンを「切り詰め不要」とは答えません。"
            )
        tt_range = (float(x.min()), float(x.max()))
        explained: "tuple[float, ...] | None" = None
        if explained_two_theta is not None:
            explicit = tuple(float(v) for v in explained_two_theta)
            # 【空を「供給された」と扱わない】: 空列で判定できることは何も無いのに、
            #   `propose_excluded_regions` は supplied=True と読んで note の警告を落とす。
            #   ③ は「未説明を確認済み」と誤読するので、空は未供給へ正規化する。
            explained, source = (explicit, "explicit") if explicit else (None, "none")
        else:
            found, source = _explained_positions(phases, wavelength, tt_range)
            if source == "phases":
                explained = found
        ladder = (
            tuple(int(v) for v in background_ladder)
            if background_ladder is not None
            else (6, 12, 18, 24, 36)
        )
        rng = suggest_two_theta_range(
            x, y, esd,
            snr_min=snr_min,
            min_fraction_kept=min_fraction_kept,
            excluded_regions=regions,
        )
        bg = suggest_background_terms(x, y, ladder=ladder)
        excl = propose_excluded_regions(x, y, explained_two_theta=explained)
    # OSError は**捕まえない** — `@degrade_oserror` が実クラス名 (FileNotFoundError 等) を
    # error_type に入れて縮退させるので、③ は「入力ファイルが無い」と「別の失敗」を区別できる。
    except (ValueError, TypeError, IndexError, KeyError, AttributeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    range_out = {k: finite_or_none(v) if isinstance(v, float) else v
                 for k, v in asdict(rng).items()}
    range_out["two_theta_limits"] = [finite_or_none(rng.lower), finite_or_none(rng.upper)]
    return {
        "two_theta_range": range_out,
        "background_terms": {
            "candidates": list(bg.candidates),
            "recommended": bg.recommended,
            "n_inflections": bg.n_inflections,
            "noise_level": finite_or_none(bg.noise_level),
            "misfits": [[t, finite_or_none(r)] for t, r in bg.misfits],
            "reason": bg.reason,
        },
        "excluded_region_candidates": {
            "candidates": [
                {
                    "center": finite_or_none(c.center),
                    "lower": finite_or_none(c.lower),
                    "upper": finite_or_none(c.upper),
                    "height": finite_or_none(c.height),
                    "snr": finite_or_none(c.snr),
                    "fwhm": finite_or_none(c.fwhm),
                    "sharpness": finite_or_none(c.sharpness),
                    "nearest_explained": finite_or_none(c.nearest_explained)
                    if c.nearest_explained is not None
                    else None,
                    "reason": c.reason,
                }
                for c in excl.candidates
            ],
            "requires_human_approval": excl.requires_human_approval,
            "note": excl.note,
            "n_peaks_examined": excl.n_peaks_examined,
            "median_fwhm": finite_or_none(excl.median_fwhm),
            "noise_level": finite_or_none(excl.noise_level),
        },
        "explained_source": source,
        "reason": reason,
    }


# 【ツールレジストリ断片】: tools.py の MCP_TOOLS へ合流する 4 ツール (要素3 + REQ-SAR-40x)。
RIETVELD_TOOLS: Mapping[str, object] = {
    "auto_rietveld": auto_rietveld,
    "propose_next_actions": propose_next_actions,
    "propose_data_preprocessing": propose_data_preprocessing,
    "refine_with_revisions": refine_with_revisions,
}
