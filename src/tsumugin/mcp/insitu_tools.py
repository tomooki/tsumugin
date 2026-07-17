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

**SDK 非依存**: 素の型 dict のみ (json.dumps allow_nan=False 安全)。GSAS/MP は runner/finder 内で
遅延 import。runner/finder/provider/materializer は注入可能 (テストは決定論スタブ)。

信頼性: 🔵 architecture.md §6 の M9 3 ツール表と 1:1。
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from .._json import finite_or_none
from ..autorietveld import PhaseSpec
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
                #   異なると乖離。実測 K2Mn[Fe(CN)6]: 65.6 Scale% は実は **47.2 wt%** = 2.1x)。
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
            )
        )
    return SequentialRietveldResult(
        frames=tuple(frames), phase_names=tuple(d.get("phase_names", ()))
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
    :param phase_id: {"elements": [...], "frac_min": .., "top_k": .., ...} (新相自動同定, None で無効)
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
          Issue #80: 例 0.2 なら相分率 0.2 未満の相のセルを解放しない)

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
    reason: str = "",
) -> dict:
    """系列結果 (JSON) の相 phase について 格子 vs 軸の熱膨張多項式 + 相分率転移を返す。"""
    from ..insitu.parametric import analyze_phase

    seq = _result_from_dict(result)
    pa = analyze_phase(seq, phase, component=component, degree=degree)  # type: ignore[arg-type]
    tr = pa.transition
    return {
        "phase": phase,
        "component": component,
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
