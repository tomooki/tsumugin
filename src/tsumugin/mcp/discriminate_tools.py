"""薄い MCP ツール — FR-313 固溶体 vs 二相判別を実データ GSAS で実行する (Issue #130)。

``operando.discrimination.discriminate_interval`` (FR-313) は ``RefinementBackend`` Protocol に
完全抽象化されており、③ から呼ぶ経路が無かった (#76 で nested 裁定の物理尤度化は完成したが
呼び手 = discrimination 自体が ② 未露出)。本ツールが JSON 入力から実 ``GSASIIBackend`` を組み、
実回折データ + 実 CIF 構造 (``PhaseInstance.structure_ref``, route X) で判別を走らせる。

**判別の意味**: 同一区間を (A) 単相・格子連続変化 と (B) 端成分 2 相・分率変化 の 2 仮説で
精密化し、Evidence (bic 一次 + 僅差なら nested 物理尤度裁定 #76) で固溶体 vs 二相を判別する。
端成分は同構造 (phase_ref/structure_ref 共有)・別格子が前提 (異構造 2 相はスコープ外)。

**SDK 非依存**: 素の型 dict のみ。例外は ``{"error","error_type"}`` へ縮退し送出しない
(③ は LLM なので例外は回復不能)。GSAS 未導入・空/不正入力も error dict。

信頼性: 🔵 Issue #130 / architecture.md §4.5 到達可能性。
"""

from __future__ import annotations

from functools import partial
from typing import Mapping, Sequence

from ..multistart import MultistartConfig
from ..nested.arbitration import ArbitrationConfig
from ..nested.physical import PhysicalProblemConfig
from ..nested.sampler import NestedBackend
from ..operando.discrimination import (
    DiscriminationConfig,
    DiscriminationResult,
    discriminate_interval,
)
from ..reference.io import load_pattern
from ._discriminate_spec import (
    fixed_phase_from_dict,
    frame_series_from_spec,
    phase_instance_from_dict,
)

__all__ = ["DISCRIMINATE_TOOLS", "discriminate"]


def _build_config(config: Mapping[str, object]) -> DiscriminationConfig:
    """JSON config → ``DiscriminationConfig`` (未指定は既定)。

    ``physical_problem`` は既定 ON (dict でマージン上書き、``null`` 明示で v1 サロゲート退避)。
    ``nested_arbitration`` は既定 None (dict を与えるとオプトインで nested 物理尤度裁定)。
    """
    ms = config.get("multistart") or {}
    if not isinstance(ms, Mapping):
        raise ValueError("config.multistart は dict である必要があります")
    multistart = MultistartConfig(n_starts=int(ms.get("n_starts", 8)))

    # physical_problem: キー未指定は既定 ON、明示 null は None (サロゲート)、dict はマージン上書き
    physical: PhysicalProblemConfig | None
    if "physical_problem" in config and config["physical_problem"] is None:
        physical = None
    else:
        pp = config.get("physical_problem") or {}
        if not isinstance(pp, Mapping):
            raise ValueError("config.physical_problem は dict または null が必要です")
        physical = PhysicalProblemConfig(
            lattice_rel_margin=float(pp.get("lattice_rel_margin", 0.02)),
            scale_upper_factor=float(pp.get("scale_upper_factor", 4.0)),
        )

    nested_arb: ArbitrationConfig | None = None
    na = config.get("nested_arbitration")
    if na is not None:
        if not isinstance(na, Mapping):
            raise ValueError("config.nested_arbitration は dict または null が必要です")
        nested_arb = ArbitrationConfig(
            full_nested=bool(na.get("full_nested", False)),
            close_threshold=float(na.get("close_threshold", 10.0)),
            temperature=float(na.get("temperature", 1.0)),
        )

    return DiscriminationConfig(
        close_threshold=float(config.get("close_threshold", 10.0)),
        multistart=multistart,
        high_r_threshold=float(config.get("high_r_threshold", 30.0)),
        seq_max_cycles=int(config.get("seq_max_cycles", 10)),
        nested_arbitration=nested_arb,
        physical_problem=physical,
    )


def _result_to_dict(result: DiscriminationResult) -> dict[str, object]:
    """``DiscriminationResult`` を JSON dict へ畳む (大配列は境界を跨がせない, §4.5)。

    両仮説は id + multistart basin 数の要約のみ (相集合の生 phases は境界に晒さない)。
    浮動小数フィールドは ``finite_or_none`` で非有限 (inf/nan) を None へ洗う (canonical JSON
    への Infinity 混入防止, ② 境界の防御 — discrimination の ledger 経路と同じ規律)。
    """
    from .._json import finite_or_none

    return {
        "verdict": result.verdict,
        "delta_evidence": finite_or_none(result.delta_evidence),
        "adjudicated_by": result.adjudicated_by,
        "nested_delta_evidence": finite_or_none(result.nested_delta_evidence),
        "escalations": list(result.escalations),
        "warnings": list(result.warnings),
        "hypothesis_single": {
            "id": result.hypothesis_single.id,
            "n_basins": len(result.multistart_single.basins),
            "n_starts": result.multistart_single.n_starts,
        },
        "hypothesis_two_phase": {
            "id": result.hypothesis_two_phase.id,
            "n_basins": len(result.multistart_two_phase.basins),
            "n_starts": result.multistart_two_phase.n_starts,
        },
    }


def discriminate(
    series: Mapping[str, object],
    initial_phases: Sequence[Mapping[str, object]],
    frame_range: Sequence[int],
    *,
    fixed_phases: Sequence[Mapping[str, object]] = (),
    config: Mapping[str, object] | None = None,
    wavelength: float | None = None,
    data_format: str = "XYE",
    reason: str = "",
) -> dict:
    """operando 1 区間の固溶体 vs 二相判別を実データ GSAS で実行する (FR-313)。

    :param series: 回折系列。``{"two_theta": [...], "intensities": [[...], ...]}`` 生配列、
        または ``{"data_paths": ["f0.xye", ...]}`` (各フレーム 1 ファイル、``data_format`` で読む)。
        data_paths の出所は ``convert_pattern`` 出力や ③ が持つデータファイル群。
    :param initial_phases: 活物質の初期相 [PhaseInstance dict]。実構造判別には各相に
        ``structure_ref`` (CIF パス, ``convert_pattern`` や相同定の出力) を入れる。
    :param frame_range: 判別対象区間 ``[start, end]`` (両端 inclusive)。
    :param fixed_phases: セル固定相 [FixedPhaseSpec dict] (既定 [])。
    :param config: 判別設定 (close_threshold / high_r_threshold / seq_max_cycles /
        multistart{n_starts} / physical_problem{...}|null / nested_arbitration{...}|null)。
        ``nested_arbitration`` を与えると僅差競合を nested 物理尤度で再裁定する (#76)。
    :param wavelength: GSASIIBackend の波長 (省略時は既定)。
    :param data_format: data_paths 経路のファイル形式 ("XYE"/"XY"/"GSAS"/"FXYE"/"XRDML")。
    :returns: ``{verdict, delta_evidence, adjudicated_by, nested_delta_evidence, escalations,
        warnings, hypothesis_single, hypothesis_two_phase}``。GSAS 未導入・不正入力・判別失敗は
        ``{"error","error_type"}`` へ縮退 (例外を送出しない)。
    """
    try:
        # 【GSAS backend 構築】: 未導入は GSASUnavailableError → error dict へ縮退
        from ..backends.gsasii import GSASIIBackend

        backend = (
            GSASIIBackend(wavelength=float(wavelength))
            if wavelength is not None
            else GSASIIBackend()
        )

        loader = partial(load_pattern, data_format=data_format)
        frames = frame_series_from_spec(series, loader=loader)

        phases = tuple(phase_instance_from_dict(p) for p in initial_phases)
        if not phases:
            raise ValueError("initial_phases が空です (活物質の初期相を 1 つ以上指定してください)")
        fixed = tuple(fixed_phase_from_dict(f) for f in fixed_phases)

        if len(frame_range) != 2:
            raise ValueError("frame_range は [start, end] の 2 要素が必要です")
        rng = (int(frame_range[0]), int(frame_range[1]))

        cfg = _build_config(config or {})
        nested_backend = NestedBackend() if cfg.nested_arbitration is not None else None

        result = discriminate_interval(
            backend,
            frames,
            rng,
            phases,
            config=cfg,
            fixed_phases=fixed,
            nested_backend=nested_backend,
        )
        return _result_to_dict(result)
    except Exception as exc:  # noqa: BLE001 — ② は例外を送出せず error dict へ縮退する
        return {"error": str(exc), "error_type": type(exc).__name__}


#: MCP レジストリへ合流させるツール群 (tools.py が ``**DISCRIMINATE_TOOLS`` で取り込む)。
DISCRIMINATE_TOOLS: Mapping[str, object] = {"discriminate": discriminate}
