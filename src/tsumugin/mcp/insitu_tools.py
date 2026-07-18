"""薄い MCP 3 ツール (M9 要素3) — 高温 in situ 逐次 Rietveld の計器+アクチュエータ。

M8 の `rietveld_tools` と同じ設計 (二重反転回避): 閉ループ丸ごとは出さず、③ (Claude Code) が
以下を反復駆動して系列解析を進める。

- ``sequential_rietveld``: frames + initial_phases spec (JSON) を run_sequential_rietveld で実行 →
  フレーム別 Rwp/格子/相分率・変化点・自動出現相を構造化して返す。実運用の装置設定 (放射源/
  ジオメトリ/instprm/背景項数) は ``instrument`` spec (JSON) でサーバ側の runner 組み立てに渡す
  (Issue #93: ``runner`` callable は JSON 境界を越えられないため、③ の実データ解析には instrument が必須)。
- ``identify_and_add_phase``: 残差/生パターン + elements → MP で新相を同定・CIF 物質化し PhaseSpec を返す
  (相追加の候補提示; 実際の採否・再精密化は ③ が sequential_rietveld/refine で行う)。
- ``parametric_fit``: 系列結果 (JSON) + parameter/axis → 熱膨張多項式係数・転移 onset/midpoint±σ。
  転移は **既定で重量分率基準** (``basis="weight"`` = 出版値)。Scale 基準は明示要求時のみで、
  結果は常に ``fraction_basis`` にどちらで出したかを明示する (Scale 由来の転移値は出版不可)。

**SDK 非依存**: 素の型 dict のみ (json.dumps allow_nan=False 安全)。GSAS/MP は runner/finder 内で
遅延 import。runner/finder/provider/materializer は注入可能 (テストは決定論スタブ)。

信頼性: 🔵 architecture.md §6 の M9 3 ツール表と 1:1。
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from .._json import finite_or_none
from ..autorietveld import PhaseSpec
from ._degrade import degrade_oserror
from ..insitu.model import (
    FrameRietveldResult,
    FrameSpec,
    PhaseIdConfig,
    SequentialConfig,
    SequentialRietveldResult,
)

__all__ = [
    "INSITU_TOOLS",
    "identify_and_add_phase",
    "parametric_fit",
    "sequential_rietveld",
]


def _cells_dict(cells: Mapping[str, Sequence[float]]) -> dict[str, list[float | None]]:
    return {name: [finite_or_none(v) for v in cell] for name, cell in cells.items()}


def _frame_residual_report(f: "FrameRietveldResult") -> dict[str, object] | None:
    """フレームの残差レポートを素の型 dict へ (None = 残差なし; キーは常に存在させる)。

    【単一 serializer】: ``auto_rietveld`` 経路 (``rietveld_tools._result_to_dict``) と同じ
      ``operando_diag_tools.residual_report_to_dict`` を使い、③ から見た残差レポートの形が経路に
      よらず一致することを保証する (二重実装を作らない)。**関数内 import** なのは
      ``operando_diag_tools`` が本モジュールの ``_result_from_dict`` を module-level で import して
      いるため (module-level に上げると循環 import になる)。
    """
    from .operando_diag_tools import residual_report_to_dict

    rep = f.residual_report
    return None if rep is None else residual_report_to_dict(rep)


def seq_result_to_dict(result: SequentialRietveldResult) -> dict[str, object]:
    """SequentialRietveldResult を素の型 dict へ (③ の判断入力・parametric_fit 入力)。

    ⚠ **``phase_fractions`` は Scale であって重量分率ではない**。定量相分析・出版値には
    ``phase_weight_fractions`` (± ``phase_weight_fraction_esd``) を使うこと (Issue #96 レビュー)。

    各フレームには ``residual_report`` を同梱する (architecture.md §4.5 到達可能性 #3): 単独の
    ``residual_report`` ツールは配列入力を要し、``auto_rietveld`` フォールバックは ``FrameSpec``
    から作れない ``HistogramSpec`` を要するため、**同梱しないと系列フレームの J2/J3 (未説明ピーク
    → 欠落相 / 強度比異常 → 対称性低下) は ③ からは原理的に answer 不能**になる。残差配列自体は
    境界を跨がせない (engine が `ResidualReport` に畳んだものを直列化するだけ)。
    """
    return {
        "phase_names": list(result.phase_names),
        "frames": [
            {
                "frame_index": f.frame_index,
                "axis_value": f.axis_value,
                "data_path": f.data_path,
                "rwp": finite_or_none(f.rwp),
                "gof": finite_or_none(f.gof),
                "phase_names": list(f.phase_names),
                "refined_cells": _cells_dict(f.refined_cells),
                "phase_fractions": {k: finite_or_none(v) for k, v in f.phase_fractions.items()},
                "changepoint": bool(f.changepoint),
                "changepoint_reasons": list(f.changepoint_reasons),
                "validity_passed": bool(f.validity_passed),
                "refine_failed": bool(f.refine_failed),
                # 【残差レポート同梱】: 残差なし (スタブ runner 等) でもキーは None で存在させ、
                #   ③ から見たスキーマを安定させる (auto_rietveld 経路と同一規律) 🔵 §4.5
                "residual_report": _frame_residual_report(f),
                # 【出版値 (Issue #96 レビュー)】: operando の主要な報告値は「相分率 vs 時間」だが、
                #   上の `phase_fractions` は **Scale** であって重量分率ではない (単位胞質量が相間で
                #   異なると乖離。実測 K2Mn[Fe(CN)6] tetra: 65.6 Scale% は同じ fit で **47.2 wt%**)。
                #   乖離はフレーム毎に違い (実測 1.39-1.62 倍)、大きさは相の単位胞質量比
                #   (cubic 1103.4 / tetra 517.8 amu = 2.13 倍) と分率で決まる = **換算係数は無い**。
                #   ③ が Scale しか受け取れなければ報告する定量値がそのまま誤る。esd 無しでは出版も
                #   できない。キーは常に存在 (欠落と esd=0 の取り違えを防ぐ; 上と同一規律) 🔵
                "phase_weight_fractions": {
                    k: finite_or_none(v) for k, v in f.phase_weight_fractions.items()
                },
                "phase_weight_fraction_esd": {
                    k: finite_or_none(v) for k, v in f.phase_weight_fraction_esd.items()
                },
                "cell_esd": {
                    k: [finite_or_none(x) for x in esd] for k, esd in f.cell_esd.items()
                },
            }
            for f in result.frames
        ],
        "appearances": [
            {
                "phase_name": a.phase_name,
                "frame_index": a.frame_index,
                "axis_value": a.axis_value,
                "structure_path": a.structure_path,
                "source": a.source,
                "rwp_before": finite_or_none(a.rwp_before),
                "rwp_after": finite_or_none(a.rwp_after),
                "evidence": {k: _jsonable(v) for k, v in a.evidence.items()},
            }
            for a in result.appearances
        ],
        "warnings": list(result.warnings),
    }


def _jsonable(v: object) -> object:
    """evidence 値を json 安全化 (float は finite_or_none)。"""
    if isinstance(v, float):
        return finite_or_none(v)
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    return str(v)


def _result_from_dict(d: Mapping[str, object]) -> SequentialRietveldResult:
    """seq_result_to_dict の逆写像 (parametric_fit が受け取る系列結果)。最小フィールドのみ復元。

    ``residual_report`` は復元しない (往復先の消費者 — parametric_fit / check_phase_set /
    repair_frames — はいずれも残差を見ない。③ は同梱された dict を直接読む)。

    **``phase_weight_fractions`` は復元する** (Issue #96 レビュー第4巡 HIGH): `parametric_fit` は
    ここで復元した系列から転移 onset/midpoint を**導出する** = 出版値を作る表面であり、往復で
    重量分率が落ちると `basis="weight"` は「重量分率が無い」と答えるほかなく、③ から見て
    **重量分率基準の転移は原理的に到達不能**になる (実際に落ちていた: `seq_result_to_dict` は
    出力していたが本関数が捨てていたため、② の配線は片道しか繋がっていなかった)。
    esd は復元しない (転移推定は値のみを使い、esd が要る ③ は元の dict を直接読む)。
    """
    frames = []
    for fd in d.get("frames", []):  # type: ignore[union-attr]
        cells = {
            name: tuple(float(x) for x in cell)
            for name, cell in (fd.get("refined_cells") or {}).items()
            if all(x is not None for x in cell)
        }
        frames.append(
            FrameRietveldResult(
                frame_index=int(fd["frame_index"]),
                axis_value=fd.get("axis_value"),
                data_path=str(fd.get("data_path", "")),
                rwp=float(fd["rwp"]) if fd.get("rwp") is not None else float("inf"),
                gof=float(fd["gof"]) if fd.get("gof") is not None else float("inf"),
                refined_cells=cells,
                phase_fractions={
                    k: float(v) for k, v in (fd.get("phase_fractions") or {}).items() if v is not None
                },
                phase_names=tuple(fd.get("phase_names", ())),
                refine_failed=bool(fd.get("refine_failed", False)),
                phase_weight_fractions={
                    k: float(v)
                    for k, v in (fd.get("phase_weight_fractions") or {}).items()
                    if v is not None
                },
            )
        )
    return SequentialRietveldResult(
        frames=tuple(frames), phase_names=tuple(d.get("phase_names", ()))
    )


#: 系列結果の各フレームが**判断に足る**ために最低限持つべきキー。``seq_result_to_dict`` は常に
#: この 3 つを出す (値が None でも可)。欠けた dict は ``_result_from_dict`` が既定値
#: (rwp=inf / phase_names=()) で黙って埋めるため、**キーの有無でしか欠落を検出できない**。
_REQUIRED_FRAME_KEYS = ("frame_index", "rwp", "phase_names")


def _validate_seq_result(result: Mapping[str, object]) -> None:
    """系列結果 dict が判断に足る形かを**判定/精密化/導出の前に**検証する。

    **``_result_from_dict`` の寛容さの対**であるため本モジュール (復元器の隣) に置く。復元器は
    ``d.get("frames", [])`` で **``frames`` キーの無い dict を例外にせず空の系列**へ復元する。
    そのため検証を挟まない消費者は**ゴミ入力から自信のある答えを出す**:

    - ``check_phase_set({"nope": 1})`` → ``is_complete=True`` / ``union=[]`` (「相集合は完全」)。
    - ``parametric_fit({}, "tetra")`` → ``fraction_basis="weight"`` / ``transition=None``
      (「重量分率基準で見て転移なし」)。**0 フレームなら重量分率の欠測も 0 件**なので
      `FractionBasisUnavailableError` すら出ず、③ の
      ``assert pf["fraction_basis"] == "weight"`` (skills/insitu・AGENT_PLAYBOOK が指示する
      検算) は**素通りする**。

    どちらも **③ に「疑わなくてよい」と告げる**最悪の失敗様態である (CLAUDE.md ② 不変条件:
    空/不正入力を「正常」と答えない)。何も判断できないときは判断を返してはならず、error dict へ
    縮退する (``insitu.model.FractionBasisUnavailableError`` の「『転移なし』へ縮退するのも禁止 —
    本物の『転移なし』と区別が付かなくなる」と同じ規律)。

    ``frames`` が空の系列も**エラーとする**: 判断の対象が存在しない以上「完全」とも「転移なし」
    とも言えず、黙ってそう答えるのは上と同じ不安全である (系列結果は必ず 1 フレーム以上を持つ)。

    :raises ValueError: ``result`` が Mapping でない、``frames`` が無い/空/列でない、
        フレームが dict でない、フレームが ``_REQUIRED_FRAME_KEYS`` を欠くとき
    """
    if not isinstance(result, Mapping):
        raise ValueError(
            f"result は系列結果 dict である必要があります: {type(result).__name__}"
        )
    if "frames" not in result:
        raise ValueError(
            "result に 'frames' キーがありません。**sequential_rietveld** が返す系列結果 dict を"
            "そのまま渡してください (空の系列を「相集合は完全」/「転移なし」と判定しないため"
            "打ち切ります)。"
            "注: repair_frames の戻り値は系列結果ではない (repairs/needs_model_revision のみ) ので"
            "渡せません — 修復後の系列が要るなら sequential_rietveld を再実行してください。"
        )
    frames = result["frames"]
    if isinstance(frames, (str, bytes)) or not isinstance(frames, Sequence):
        raise ValueError(
            f"result['frames'] はフレーム dict の列である必要があります: {type(frames).__name__}"
        )
    if not frames:
        raise ValueError(
            "result['frames'] が空です。判断の対象が無い系列を「相集合は完全」「転移なし」とは"
            "報告できません (系列を実行できていない可能性があります — sequential_rietveld の"
            "結果を確認してください)。"
        )
    for i, fd in enumerate(frames):
        if not isinstance(fd, Mapping):
            raise ValueError(
                f"result['frames'][{i}] がフレーム dict ではありません: {type(fd).__name__}"
            )
        missing = [key for key in _REQUIRED_FRAME_KEYS if key not in fd]
        if missing:
            raise ValueError(
                f"result['frames'][{i}] に必須キーがありません: {missing}。"
                "欠けたキーは既定値 (rwp=inf / phase_names=()) で黙って埋まり、判定が"
                "入力の不備を反映しない誤った結論になります。"
            )


def _enum_from_value(enum_cls: type, value: object, key: str) -> object:
    """enum の **値** (小文字文字列) から enum メンバを引く。未知値は ValueError (→ error dict)。"""
    try:
        return enum_cls(str(value))
    except ValueError:
        allowed = ", ".join(sorted(str(m.value) for m in enum_cls))  # type: ignore[attr-defined]
        raise ValueError(f"unknown {key}: {value!r} (expected one of: {allowed})") from None


def _parse_two_theta_limits(
    two_theta_limits: Sequence[float] | None,
) -> tuple[float, float] | None:
    """``two_theta_limits`` を検証して ``(lo, hi)`` へ正規化する (None は制限なし)。

    呼び出し側は LLM が組んだ JSON なので、1 要素・3 要素・非数値の取り違えが起きやすい。素朴な
    ``limits[0], limits[1]`` は IndexError/TypeError を MCP 境界に貫かせるため、呼び出し側の try で
    error dict へ縮退できる ``ValueError`` に正規化する。``sequential_rietveld`` と
    ``operando_diag_tools.repair_frames`` の共有ヘルパ (レンジ解釈を一致させる)。

    :raises ValueError: 2 要素の数値ペアでない、または ``lo >= hi`` のとき
    """
    if two_theta_limits is None:
        return None
    try:
        values = list(two_theta_limits)
    except TypeError as exc:
        raise ValueError(
            f"two_theta_limits は [lo, hi] の 2 要素数値ペアです: {two_theta_limits!r}"
        ) from exc
    if len(values) != 2:
        raise ValueError(
            f"two_theta_limits は 2 要素 [lo, hi] である必要があります: "
            f"{two_theta_limits!r} (実際 {len(values)} 要素)"
        )
    try:
        lo, hi = float(values[0]), float(values[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"two_theta_limits の要素が数値ではありません: {two_theta_limits!r}"
        ) from exc
    if not (lo < hi):
        raise ValueError(f"two_theta_limits は lo < hi である必要があります: {two_theta_limits!r}")
    return (lo, hi)


def _instrument_path_resolver(
    spec: Mapping[str, object], frame_specs: Sequence[FrameSpec]
) -> str | Callable[[FrameSpec], str]:
    """instrument spec の ``path``/``paths`` を make_gsas_runner の instrument_path へ写す。

    ``paths`` は frames と 1:1 の列 (フレーム毎に instprm が異なる系列)。JSON からは callable を
    渡せないため、ここでフレーム→パスの解決関数を組み立てる (同一 FrameSpec オブジェクトが
    runner へ渡るため id で引き、保険として data_path でも引く)。
    """
    paths = spec.get("paths")
    if paths is not None:
        path_list = [str(p) for p in paths]  # type: ignore[union-attr]
        if len(path_list) != len(frame_specs):
            raise ValueError(
                f"instrument paths length {len(path_list)} != frames length {len(frame_specs)}"
            )
        by_id = {id(fs): p for fs, p in zip(frame_specs, path_list)}
        by_data = {fs.data_path: p for fs, p in zip(frame_specs, path_list)}

        def resolve(frame: FrameSpec) -> str:
            if id(frame) in by_id:
                return by_id[id(frame)]
            if frame.data_path in by_data:
                return by_data[frame.data_path]
            raise ValueError(f"no instrument path for frame {frame.data_path!r}")

        return resolve
    path = spec.get("path")
    if path is None:
        raise ValueError("instrument spec requires 'path' (str) or 'paths' (list matching frames)")
    return str(path)


def _runner_from_instrument(
    spec: Mapping[str, object],
    frame_specs: Sequence[FrameSpec],
    two_theta_limits: tuple[float, float] | None,
) -> Callable:
    """instrument spec (JSON) から make_gsas_runner で runner を組み立てる (Issue #93)。"""
    from ..autorietveld.model import Geometry, Radiation
    from ..insitu.engine import make_gsas_runner

    afmc = spec.get("auto_freeze_minor_cells")
    # ⚠ #80 の本体は **float 閾値** (bool ではない)。JSON の true をそのまま float 化すると 1.0 =
    # 「分率 1.0 未満の相を凍結」= 多相では全相のセル凍結という静かな事故になるため明示的に拒否する。
    if isinstance(afmc, bool):
        raise ValueError(
            "auto_freeze_minor_cells is a phase-fraction threshold (float, e.g. 0.2), not a bool; "
            "pass null to disable (bool true would freeze every phase in a multiphase run)"
        )
    return make_gsas_runner(
        instrument_path=_instrument_path_resolver(spec, frame_specs),
        radiation=_enum_from_value(Radiation, spec.get("radiation", "xray_lab"), "radiation"),
        geometry=_enum_from_value(Geometry, spec.get("geometry", "bragg_brentano"), "geometry"),
        two_theta_limits=two_theta_limits,
        max_cyc=int(spec.get("max_cyc", 12)),  # type: ignore[arg-type]
        background_coeffs=int(spec.get("background_coeffs", 6)),  # type: ignore[arg-type]
        auto_freeze_minor_cells=None if afmc is None else float(afmc),  # type: ignore[arg-type]
    )


@degrade_oserror
def sequential_rietveld(
    frames: Sequence[Mapping[str, object]],
    initial_phases: Sequence[Mapping[str, object]],
    *,
    phase_id: Mapping[str, object] | None = None,
    warm_start: bool = True,
    warm_start_fractions: bool = False,
    two_theta_limits: Sequence[float] | None = None,
    max_frames: int | None = None,
    workdir: str = ".",
    instrument: Mapping[str, object] | None = None,
    runner: Callable | None = None,
    phase_finder: Callable | None = None,
    reason: str = "",
) -> dict:
    """frames/initial_phases spec (JSON) を run_sequential_rietveld で実行し構造化結果を返す。

    :param frames: FrameSpec.to_dict の列
    :param initial_phases: PhaseSpec.to_dict の列 (フレーム 0 の既知相)
    :param phase_id: {"elements": [...], "frac_min": .., "top_k": .., ...} (新相自動同定, None で無効)。
        ⚠ ``frac_min`` (既定 0.02) は新相採用に要する**最小 Scale** — `phase_fractions` (HAP Scale の
        Σ=1 正規化値) と比較する。**wt% (`phase_weight_fractions`) ではない** (下の
        ``auto_freeze_minor_cells`` と同じ basis 注意)
    :param warm_start_fractions: 直前フレームの精密化相分率も次フレームの初期値に引き継ぐか
        (Issue #82; 分率が seed に張り付くフレームの是正。``warm_start`` 有効時のみ効く)
    :param instrument: **JSON クライアント (③) の実運用経路** (Issue #93)。指定かつ ``runner`` 未指定
        なら、この spec からサーバ側で ``make_gsas_runner`` を組み立てる。指定なし (None) は従来通り
        engine 既定の ``_default_gsas_runner`` (実験室 X 線 Bragg-Brentano・背景 6 項・装置は data_path
        隣接の ``.instprm`` 規約) — 放射光や背景項数の変更はこの spec でしか届かない。キー:

        - ``path``: instprm パス (str, 必須。``paths`` と排他)
        - ``paths``: frames と 1:1 の instprm パス列 (フレーム毎に装置が異なる系列)
        - ``radiation``: ``Radiation`` の **値** ("xray_lab"/"xray_synchrotron"/"neutron_cw"/
          "neutron_tof"、既定 "xray_lab")
        - ``geometry``: ``Geometry`` の値 ("bragg_brentano"/"debye_scherrer"、既定 "bragg_brentano")
        - ``background_coeffs``: Chebyshev 背景項数 (int, 既定 6。実験室 X 線/放射光は 18-24 推奨)
        - ``max_cyc``: 各段階の最大精密化サイクル (int, 既定 12)
        - ``auto_freeze_minor_cells``: 分率連動の自動セル凍結**閾値** (float|None, 既定 None=無効。
          Issue #80: 例 0.2 なら相分率 0.2 未満の相のセルを解放しない)。⚠ **basis は
          `phase_fractions` (= HAP Scale の Σ=1 正規化値) で `phase_weight_fractions` (wt%) では
          ない** — 実測 ``Scale {cubic .75, tetra .25}`` = ``wt% {cubic .865, tetra .135}`` なので
          0.2 は **Scale では tetra を解放し wt% では凍結する**。出版値は wt% なので wt% の直感で
          数字を決めると静かに外れる (③ 向けの警告は skills/insitu・skills/operando-diagnose・
          AGENT_PLAYBOOK の「分率の閾値は Scale 基準」節)

        ``two_theta_limits`` は本引数の runner にも転送される (フレーム側指定が優先)。
    :param runner: **注入/テスト用**の Python callable ((frame, phases, initial_cells)→
        AutoRietveldResult)。JSON 境界越しには渡せない。明示指定時は ``instrument`` より優先する
        (後方互換)。None かつ ``instrument`` も None なら engine 既定 GSAS runner
    :param phase_finder: 新相探索器 (注入可能、既定 MP 駆動)
    :returns: 系列構造化結果。instrument spec 不正は ``{"error", "error_type"}``
    """
    from ..insitu.engine import run_sequential_rietveld

    frame_specs = [FrameSpec.from_dict(f) for f in frames]
    phase_specs = [PhaseSpec.from_dict(p) for p in initial_phases]
    # 【レンジ検証を縮退契約に載せる】: 旧実装は `two_theta_limits[0]` を直接引いており、1 要素等の
    #   取り違えで IndexError が MCP 境界を貫いていた (error dict へ縮退する契約に反する)。
    try:
        limits = _parse_two_theta_limits(two_theta_limits)
        if runner is None and instrument is not None:
            runner = _runner_from_instrument(instrument, frame_specs, limits)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}
    pid = None
    if phase_id is not None:
        pid = PhaseIdConfig(
            elements=tuple(str(e) for e in phase_id.get("elements", ())),
            frac_min=float(phase_id.get("frac_min", 0.02)),
            rwp_eps=float(phase_id.get("rwp_eps", 1e-6)),
            top_k=int(phase_id.get("top_k", 1)),
            hull_cutoff_ev=phase_id.get("hull_cutoff_ev", 0.1),  # type: ignore[arg-type]
            subtract_bg=bool(phase_id.get("subtract_bg", True)),
            trigger_rwp_ratio=float(phase_id.get("trigger_rwp_ratio", 1.25)),
        )
    config = SequentialConfig(
        warm_start=warm_start,
        warm_start_fractions=warm_start_fractions,
        two_theta_limits=limits,
        max_frames=max_frames,
        phase_id=pid,
    )
    result = run_sequential_rietveld(
        frame_specs, phase_specs, config=config, runner=runner,
        phase_finder=phase_finder, workdir=workdir,
    )
    out = seq_result_to_dict(result)
    out["reason"] = reason
    return out


@degrade_oserror
def identify_and_add_phase(
    two_theta: Sequence[float],
    intensity: Sequence[float],
    elements: Sequence[str],
    workdir: str,
    *,
    exclude_formulas: Sequence[str] = (),
    top_k: int = 1,
    hull_cutoff_ev: float | None = 0.1,
    subtract_bg: bool = True,
    provider: object | None = None,
    materializer: object | None = None,
    reason: str = "",
) -> dict:
    """残差/生パターン + elements から新相を同定し CIF 物質化して PhaseSpec 候補を返す (相追加提示)。

    採否・再精密化は行わない (提案≠適用): ③ が返された PhaseSpec を initial_phases に足して
    sequential_rietveld/refine を再実行する。provider/materializer 未指定なら MP を遅延生成。
    """
    import numpy as np

    from ..insitu.phaseid import MPMaterializer, identify_new_phases

    if provider is None:
        from ..mp.provider import MPReferenceProvider

        provider = MPReferenceProvider()
    if materializer is None:
        materializer = MPMaterializer()

    found = identify_new_phases(
        np.asarray(two_theta, dtype=float),
        np.asarray(intensity, dtype=float),
        elements=list(elements),
        provider=provider,  # type: ignore[arg-type]
        materializer=materializer,  # type: ignore[arg-type]
        workdir=workdir,
        exclude_formulas=list(exclude_formulas),
        top_k=top_k,
        hull_cutoff_ev=hull_cutoff_ev,
        subtract_bg=subtract_bg,
    )
    return {
        "candidates": [
            {
                "phase_spec": ip.phase_spec.to_dict(),
                "phase_id": ip.phase_id,
                "formula": ip.formula,
                "score": finite_or_none(ip.score),
                "strain": finite_or_none(ip.strain),
                "source": ip.source,
            }
            for ip in found
        ],
        "n_candidates": len(found),
        "reason": reason,
    }


def parametric_fit(
    result: Mapping[str, object],
    phase: str,
    *,
    component: str = "a",
    degree: int = 1,
    basis: str = "weight",
    reason: str = "",
) -> dict:
    """系列結果 (JSON) の相 phase について 格子 vs 軸の熱膨張多項式 + 相分率転移を返す。

    :param result: ``sequential_rietveld`` が返す系列結果 (JSON dict)。**空/不正 (``frames`` 無し・
        空・必須キー欠落・フレームが dict でない) は判断せず error dict** — 0 フレームの
        「転移なし」は本物の「転移なし」と区別が付かない (``_validate_seq_result``)
    :param basis: 転移推定に使う相分率の基準。**既定 ``"weight"`` (重量分率 = 出版値)**。
        ``"scale"`` は HAP Scale 由来で**診断・相対比較専用** (出版不可)。
    :returns: ``fraction_basis`` に**どちらで出したかを明示**した結果。重量分率が系列に無い/
        系列結果が空・不正/未知 basis は ``{"error", "error_type"}`` dict (Scale へも
        「転移なし」へも縮退しない)。この場合 ``transition``/``fraction_basis`` キーは返らない
        (③ の ``assert pf["fraction_basis"] == "weight"`` が**素通りしない**)

    ⚠ **転移 onset/midpoint は basis で答えが変わる**: `sequential.thermal.estimate_transition` が
    返すのは「曲線が**絶対レベル** 0.50 / 0.10 を横切る軸値」であり、y 軸が Scale か wt% かで
    交差位置が動く。実測 K₂Mn[Fe(CN)₆] tetra 充電域では、同じ精密化から Scale は
    「midpoint 9.515 h」を、wt% は「**転移なし**」を出した (Scale 0→0.656 は 0.50 を横切るが
    wt% は 0→0.472 で届かない。Scale=0.50 のフレームは実際には 34.0 wt%)。

    **既定を "weight" にした理由** (① `parametric.transition_from_fractions` の既定 "scale" と
    異なる): ② は JSON しか送れない LLM (③) が呼ぶ表面であり、**既定がそのまま ③ にとっての
    実質的な振る舞い**になる (architecture.md §4.5)。既定を Scale にすると ③ は「出版できる
    転移温度」だと信じて Scale 由来の数字を受け取る — それが本 HIGH の実害そのものである。
    ① は Python の呼び出し側が call site で意図を書ける層なので後方互換を優先している。
    """
    from ..insitu.parametric import analyze_phase

    # 【縮退契約】: ② は例外を送出しない (③ は LLM なので例外は回復不能なハード失敗)。
    #   重量分率の欠如 (`FractionBasisUnavailableError`, ValueError の派生) と未知 basis は
    #   error dict にして**復旧方法を示す** — ここで Scale に落ちたり「転移なし」を返したり
    #   すると、③ は静かに違う数字を出版する (CLAUDE.md ② 不変条件)。`error_type` に
    #   例外クラス名が入るので ③ は「重量分率が無い」と「入力が壊れている」を区別できる。
    # 【入力検証を先に (レビュー第4巡 MEDIUM-HIGH)】: `_result_from_dict` は寛容で、`frames` の
    #   無い dict を空の系列へ黙って復元する。0 フレームなら重量分率の**欠測も 0 件**なので
    #   `FractionBasisUnavailableError` すら出ず、`{}` に対して `fraction_basis="weight"` +
    #   `transition=None` = 「重量分率基準で見て転移なし」という**自信のある嘘**を返していた。
    #   ③ に指示してある検算 (`assert pf["fraction_basis"] == "weight"`) も素通りする。
    #   `model.FractionBasisUnavailableError` が「『転移なし』へ縮退するのも禁止」と定めた当の
    #   失敗様態そのものなので、判断の前に形を検証する (`check_phase_set` と同じ縮退契約)。
    # 【AttributeError も捕らえる】: `_result_from_dict` は `d.get(...)` / `fd.get(...)` を呼ぶため、
    #   result が str/list、frames が dict、フレーム要素が str/None のとき AttributeError が
    #   MCP 境界を貫いていた (② は例外を送出しない契約に反する)。`check_phase_set` は同じ復元器を
    #   呼びながら AttributeError を捕らえており、兄弟ツール間で縮退契約が食い違っていた。
    try:
        _validate_seq_result(result)
        seq = _result_from_dict(result)
        pa = analyze_phase(seq, phase, component=component, degree=degree, basis=basis)  # type: ignore[arg-type]
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}
    tr = pa.transition
    return {
        "phase": phase,
        "component": component,
        # 【basis の明示】: Scale 由来の数字が出版値と取り違えられないよう、**常に**どちらで
        #   出したかを返す (③ が見落としても既定が weight なので安全側に倒れる) 🔵 §4.5
        "fraction_basis": pa.fraction_basis,
        "baseline": {
            "parameter": pa.baseline.parameter,
            "coefficients": [finite_or_none(c) for c in pa.baseline.coefficients],
            "outlier_frames": list(pa.baseline.outlier_frames),
        },
        "transition": None
        if tr is None
        else {
            "phase_ref": tr.phase_ref,
            "onset": finite_or_none(tr.onset) if tr.onset is not None else None,
            "midpoint": finite_or_none(tr.midpoint) if tr.midpoint is not None else None,
            "sigma": finite_or_none(tr.sigma) if tr.sigma is not None else None,
            "direction": tr.direction,
        },
        "reason": reason,
    }


# 【M9 ツールレジストリ】: MCP_TOOLS へマージする 3 ツール (architecture.md §6)。
INSITU_TOOLS: Mapping[str, object] = {
    "sequential_rietveld": sequential_rietveld,
    "identify_and_add_phase": identify_and_add_phase,
    "parametric_fit": parametric_fit,
}
