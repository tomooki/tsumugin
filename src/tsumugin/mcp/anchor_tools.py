"""薄い MCP ツール (M10 要素) — アンカー基準双方向 operando 解析の計器 (Issue #97)。

M10 anchor (`insitu.anchor`, FR-330) は 715 行の ① 実装があるのに ② ツール 0・③ skill 言及 0
だったため、実 operando 解析 (K2Mn[Fe(CN)6]) で使われず、**M10 が設計上すでに解いている病理**
(偽 tetra が全域に湧く / 分率 0 近傍で esd 発散 / `check_phase_set` 全相 flagged) を ③ が
per-frame 独立 3 相固定 fit で再生産した。本ツールはその ②露出。

**なぜ前方単一パス (`sequential_rietveld`) でなく anchored か** (`anchor/select.py` 設計判断①):
> 相集合が異なる前方 (少数相) / 後方 (多相) の比較は **Rwp 生値でなく bic** で行う。Rwp は
> 自由パラメータ増で単調減少するため、相数の多い後方が必ず勝ち偽相を全域へ広げてしまう。

**runner/identifier は callable のため #93 と同型の JSON spec で到達可能にする**:
- runner → ``instrument`` spec。M9 と**同一の runner 契約** ((frame, phases, initial_cells)→
  AutoRietveldResult) なので ``insitu_tools._runner_from_instrument`` を**共有**する (二重実装しない)。
- identifier → ``anchor_table`` {frame_index: [phase_name]} (publication_m10.py の `_anchors.json`
  方式そのもの)。省略時は identifier=None で M9 単一アンカー fallback (相同定ベースの既定同定は
  M6 `identify_phases` が計量縮退系で機能しないため本ツールでは提供しない — anchor_table 必須)。

**SDK 非依存**: 素の型 dict のみ。GSAS は instrument 経由の runner 内で遅延 import。runner は
注入可能 (テストは決定論スタブ)。系列結果は M9 と同型なので ``seq_result_to_dict`` を流用し、
アンカー/crossover 要約 (per-segment bic を含む) を ledger から抽出して添える。

信頼性: 🔵 architecture.md §4.5 到達可能性④ / Issue #97 / FR-330。
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from .._json import finite_or_none
from ..autorietveld import PhaseSpec
from ..insitu.anchor.model import AnchorConfig
from ..insitu.model import FrameSpec
from ._degrade import degrade_oserror
from .insitu_tools import (
    _apply_charge_constraint_spec,
    _parse_two_theta_limits,
    _runner_from_instrument,
    seq_result_to_dict,
)

__all__ = ["ANCHOR_TOOLS", "anchored_sequential"]


def _identifier_from_table(
    anchor_table: Mapping[str, Sequence[str]],
    frame_specs: Sequence[FrameSpec],
    catalog: Mapping[str, PhaseSpec],
    confidence: float,
):
    """anchor_table {frame_index: [phase_name]} から M10 identifier を組む。

    identifier は「フレーム → (信頼度, 相集合 specs) or None」。**frames リスト位置 (frame_index)**
    で引く — axis_value は実 operando では時間/温度であって index ではないため、位置キーが唯一
    頑健な指定である。

    **``id()`` を鍵にしない** (`_instrument_path_resolver` と同じ根治): 実運用では engine が同一
    ``FrameSpec`` オブジェクトを渡すため id ベースでも安全だが、``id()`` は GC 後に再利用される
    ため、テスト注入や再構築フレームでは stale ヒットの脆さがある。フレームの内容で解決する:
    data_path が一意なら data_path 索引、重複系列は ``FrameSpec`` 全体 (frozen dataclass =
    値ハッシュ/値等価) を鍵にした位置解決へ落ちる。

    アンカーフレームには ``confidence`` (既定 1.0, 段階 A スクリーニングを通す値) を返し、
    非アンカーフレームは None (信頼度 0 で段階 A を通らない)。相名が catalog に無ければ KeyError
    (呼び出し側が error dict へ縮退させる — ③ の typo を黙って無視しない)。
    """
    table = {int(k): tuple(v) for k, v in anchor_table.items()}
    by_frame: dict[FrameSpec, tuple[PhaseSpec, ...]] = {}
    data_paths: list[str] = []
    anchored_data: dict[str, tuple[PhaseSpec, ...]] = {}
    for idx, fs in enumerate(frame_specs):
        data_paths.append(fs.data_path)
        if idx not in table:
            continue
        specs = tuple(catalog[name] for name in table[idx])  # KeyError → 呼び出し側で縮退
        by_frame[fs] = specs
        anchored_data[fs.data_path] = specs
    # data_path が一意なときのみ data_path 索引を使う (重複時は最後のアンカーで上書きされ静かに
    # 誤るため無効化し、値キーの位置解決に委ねる)。
    by_data = anchored_data if len(set(data_paths)) == len(data_paths) else None

    def identify(frame: FrameSpec):
        specs = by_frame.get(frame)  # 完全一致 (最も特定的)
        if specs is None and by_data is not None:
            specs = by_data.get(frame.data_path)
        return (confidence, specs) if specs else None

    return identify


def _json_alkali(alkali: Mapping[str, object]) -> dict:
    """alkali_* dict を JSON 安全化する (float は finite_or_none, dict は再帰 1 段)。"""
    out: dict = {}
    for k, v in alkali.items():
        if isinstance(v, float):
            out[k] = finite_or_none(v)
        elif isinstance(v, Mapping):
            out[k] = {
                str(kk): (finite_or_none(vv) if isinstance(vv, float) else vv)
                for kk, vv in v.items()
            }
        else:
            out[k] = v
    return out


def _anchor_summary(ledger) -> tuple[list[dict], list[dict]]:
    """ledger の m10 エントリからアンカー/crossover 要約を抽出する (非有限は None 化)。

    ``run_anchored_sequential`` は ``m10_anchor`` / ``m10_segment_choice`` を追記する。生 payload の
    rwp/total_bic は inf を含みうるので finite_or_none で json 安全化する。**crossover の total_bic**
    が「BIC で相数抑制」の可視化点 = ③ が相数の増減を bic で追える (#97 の核心)。
    """
    anchors: list[dict] = []
    crossovers: list[dict] = []
    for e in ledger.entries:
        p = e.payload
        if e.kind == "m10_anchor":
            anchors.append({
                "frame": p["frame"],
                "phases": list(p["phases"]),
                "rwp": finite_or_none(p["rwp"]),
                "confidence": finite_or_none(p["confidence"]),
                "fallback": bool(p["fallback"]),
                # FR-318 (F1): 単相アンカーの alkali_x_xrd / alkali_per_phase が
                # `charge_constraint.per_phase_content` の出所 (§4.5 到達可能性)。
                "alkali": _json_alkali(p.get("alkali") or {}),
            })
        elif e.kind == "m10_segment_choice":
            crossovers.append({
                "left": p["left"],
                "right": p["right"],
                "inner": list(p["inner"]),
                "crossover_frame": p["crossover_frame"],
                "total_bic": finite_or_none(p["total_bic"]),
                "onset_frame": p["onset_frame"],
                "monotonic": bool(p["monotonic"]),
                "reason": p["reason"],
            })
    return anchors, crossovers


@degrade_oserror
def anchored_sequential(
    frames: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    *,
    anchor_table: Mapping[str, Sequence[str]] | None = None,
    base_phases: Sequence[Mapping[str, object]] | None = None,
    anchor_confidence: float = 1.0,
    anchor_config: Mapping[str, object] | None = None,
    two_theta_limits: Sequence[float] | None = None,
    instrument: Mapping[str, object] | None = None,
    charge_constraint: Mapping[str, object] | None = None,
    runner: Callable | None = None,
    reason: str = "",
) -> dict:
    """アンカー基準双方向 operando 解析を JSON spec で実行し系列結果を返す (M10 の ②露出)。

    転移を含む operando 系列では前方単一パス (``sequential_rietveld``) が初期フレーム依存 +
    転移域セル汚染で脆い。本ツールは信頼フレーム (アンカー) 起点の双方向精密化 + **区間の相集合が
    違うとき bic で経路選定** (相数を Rwp でなく bic で抑制) して頑健化する。

    :param frames: FrameSpec.to_dict の列 (系列; 位置 = frame_index)
    :param phases: PhaseSpec.to_dict の列。**anchor_table が参照する全相名の catalog** (union)。
        名前→PhaseSpec の索引に使う
    :param anchor_table: {frame_index (str): [phase_name, ...]} — どのフレームをアンカーにし、その
        相集合を何にするか (publication_m10.py の `_anchors.json` 方式)。**None は identifier 無効**
        → M9 単一アンカー fallback に縮退 (前方単一パス相当)。相名は phases catalog に在ること
    :param base_phases: 既定相集合 (アンカーが無い区間の warm-start 起点)。None なら phases 全体
    :param anchor_confidence: anchor_table のフレームに与える段階 A 信頼度 (既定 1.0)。
        ``anchor_config.anchor_confidence_min`` 以上であること (既定 0.5 なので 1.0 で通る)
    :param anchor_config: AnchorConfig のフィールド dict (JSON)。``anchor_rwp_max`` /
        ``anchor_confidence_min`` / ``base_params`` / ``per_phase_params`` (bic の n_params 推定) 等。
        未知キーは error dict。None は全既定 (`AnchorConfig.from_dict`)
    :param instrument: **実運用の runner を組む JSON spec** (#93 と共有; sequential_rietveld と同一キー
        path/paths/radiation/geometry/background_coeffs/max_cyc/auto_freeze_minor_cells)。runner 未指定
        時のみ使う。None かつ runner も None なら engine 既定 GSAS runner (実験室 X 線)
    :param charge_constraint: **FR-318 電気化学制約の JSON spec** (sequential_rietveld と同一形:
        ``config`` + ``targets`` [= ``alkali_budget`` 出力] + ``per_phase_content``)。有効時は
        (1) 単相アンカーで制約有無 A/B → ΔRwp 超過で不可逆容量疑いの警告 + **x₀ 校正の提案**
        (提案≠適用; ledger ``fr318_x0_calibration_proposal``)、(2) per-frame の alkali_* 診断。
        出力に ``anchors[].ab_check`` が付く。None で従来動作
    :param runner: **注入/テスト用** callable ((frame, phases, initial_cells)→AutoRietveldResult)。
        JSON 越しには渡せない。明示指定時は instrument より優先
    :returns: M9 と同型の系列結果 dict (frames/phase_names/appearances/warnings; per-frame に出版値
        重量分率±esd を含む) + ``anchors`` (確定アンカー要約) + ``crossovers`` (区間選定の **total_bic**
        を含む経路要約) + ``ledger_verified``。spec 不正・未知相名・未知 config キーは
        ``{"error", "error_type"}`` (③ は LLM なので例外は回復不能)
    """
    from ..insitu.anchor.engine import run_anchored_sequential
    from ..store.ledger import Ledger

    try:
        frame_specs = [FrameSpec.from_dict(f) for f in frames]
        catalog: dict[str, PhaseSpec] = {}
        for p in phases:
            spec = PhaseSpec.from_dict(p)
            catalog[spec.phase_name] = spec
        base = (
            tuple(PhaseSpec.from_dict(p) for p in base_phases)
            if base_phases is not None
            else tuple(catalog.values())
        )
        cfg = AnchorConfig.from_dict(anchor_config or {})
        cc_cfg = None
        if charge_constraint is not None:
            cc_cfg, frame_specs = _apply_charge_constraint_spec(charge_constraint, frame_specs)
        limits = _parse_two_theta_limits(two_theta_limits)
        if runner is None and instrument is not None:
            runner = _runner_from_instrument(instrument, frame_specs, limits, cc_cfg)
        identifier = (
            _identifier_from_table(anchor_table, frame_specs, catalog, anchor_confidence)
            if anchor_table is not None
            else None
        )
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        # AttributeError も捕捉 (F-final-1 安全網): charge_constraint の深い入れ子のゴミは
        # AttributeError になる — ② は例外を送出しない。
        return {"error": str(exc), "error_type": type(exc).__name__}

    if runner is None:
        # `run_anchored_sequential` の runner は必須 (デフォルト無し)。instrument も runner も
        # 無いとき無音のラボ X 線既定へ落とすのは §4.5 が警告する zero-config の罠 (operando は
        # 放射光/中性子が主戦場) なので、明示的に error dict にして instrument を要求する。
        return {
            "error": (
                "anchored_sequential には instrument spec (instprm path を含む JSON) か、"
                "注入 runner が必要です。operando の装置は放射光/中性子が多く、既定のラボ X 線に"
                "黙って落とすと系統的に誤るため。instrument 例: "
                '{"path": "series.instprm", "radiation": "xray_synchrotron", '
                '"geometry": "debye_scherrer", "background_coeffs": 18}'
            ),
            "error_type": "MissingInstrumentError",
        }

    ledger = Ledger()
    result = run_anchored_sequential(
        frame_specs, base, runner=runner, identifier=identifier, cfg=cfg, ledger=ledger,
        charge_constraint=cc_cfg,
    )
    out = seq_result_to_dict(result)
    anchors, crossovers = _anchor_summary(ledger)
    _attach_ab_checks(anchors, ledger)
    out["anchors"] = anchors
    out["crossovers"] = crossovers
    out["ledger_verified"] = ledger.verify()
    out["reason"] = reason
    return out


def _attach_ab_checks(anchors: "list[dict]", ledger) -> None:
    """FR-318 アンカー A/B 検証 (fr318_anchor_ab) を anchors 要約へ付す (無ければ何もしない)。

    ``ab_check`` = {rwp_free, rwp_constrained, delta_rwp, ``x_refined``|``x_model``, x_echem}。
    **x のキーは由来で変わる**: ``x_refined`` = 占有率が実際に精密化された (esd 付き) /
    ``x_model`` = 占有率固定 (既定) の CIF 由来モデル値で **x₀ 校正の根拠にならない**。
    校正の**提案**は x_refined のときのみ ledger ``fr318_x0_calibration_proposal``
    (applied=False) と系列 warnings に出る (提案≠適用)。
    """
    by_frame: dict[int, dict] = {}
    for e in ledger.entries:
        if e.kind == "fr318_anchor_ab":
            p = dict(e.payload)
            frame = int(p.pop("frame"))
            by_frame[frame] = {k: finite_or_none(v) if isinstance(v, float) else v
                               for k, v in p.items()}
    for a in anchors:
        ab = by_frame.get(int(a["frame"]))
        if ab is not None:
            a["ab_check"] = ab


#: MCP_TOOLS へマージする M10 ツール (Issue #97: ①→② カバレッジ規則④)。
ANCHOR_TOOLS: Mapping[str, object] = {
    "anchored_sequential": anchored_sequential,
}
