"""薄い MCP ツール — 電気化学同期 (align_echem, Issue #103)。

`interop.biologic` (FR-311, `parse_mpr`/`align_frames`) と `operando.echem` は callable 不要・
全引数 JSON 互換なのに ② 未露出で、K2Mn[Fe(CN)6] operando 解析では毎回 `merge_echem.py` で
① を直叩きしていた。③ の J8 (電気化学突合) は「未確定と書け」の消極的指示に留まっていた。

本ツールは BioLogic `.mpr` を読み、**回折フレーム列を電気化学曲線へ整列**して per-frame の
時刻/電位/積算電荷/状態 (rest/charge/discharge) を返す。転移点 (相分率シグモイド onset) を
電気化学イベント (充電カットオフ・CV 保持・レスト) と突合する材料になる。

**frame_epoch_s の到達可能性** (§4.5): 回折フレームの POSIX 時刻は FrameSpec が持たないため、③ は
(a) 明示 epoch 列、または (b) **一定ケイデンス** (offset_s + interval_s·i) のいずれかで与える。
operando は固定間隔取得が普通なので (b) が既定経路 (実測 K2Mn[Fe(CN)6]: offset 22.1s / 間隔 283s)。

**SDK 非依存**: 素の型 dict のみ。galvani は parse_mpr 内で遅延 import (未導入は error dict)。

信頼性: 🔵 Issue #103 / FR-311 / architecture.md §4.5 カバレッジ規則④。
"""

from __future__ import annotations

from typing import Sequence

from .._json import finite_or_none

__all__ = ["ECHEM_TOOLS", "align_echem"]


def align_echem(
    mpr_path: str,
    *,
    frame_epoch_s: Sequence[float] | None = None,
    offset_s: float | None = None,
    interval_s: float | None = None,
    n_frames: int | None = None,
    clamp: bool = False,
    reason: str = "",
) -> dict:
    """BioLogic .mpr を読み、回折フレーム列を電気化学曲線へ整列して per-frame 状態を返す (計器)。

    :param mpr_path: BioLogic ``.mpr`` ファイルパス
    :param frame_epoch_s: 各回折フレームの **POSIX 秒** (明示指定)。``offset_s``/``interval_s``/
        ``n_frames`` と排他。フレーム時刻を厳密に知っているとき (ファイル mtime 等から算出済み)
    :param offset_s: 曲線開始から先頭フレームまでの遅延 [s] (一定ケイデンス経路)。
        ``interval_s`` + ``n_frames`` と併用。フレーム i の時刻 = 曲線開始 + offset_s + interval_s·i
    :param interval_s: フレーム間隔 [s] (一定ケイデンス経路)
    :param n_frames: フレーム数 (一定ケイデンス経路)
    :param clamp: 曲線の時間範囲外フレームを端点値へ丸めるか (既定 False = 範囲外は voltage=None・
        state="unknown"。電圧の外挿捏造を避ける。丸めても ``in_span=False`` で区別可能)
    :returns: ``curve`` (開始時刻/点数/電位範囲) + ``frames[]`` ({frame, time_s, time_h,
        voltage_v, charge_mah, state, in_span}) + ``n_in_span``。galvani 未導入・入力不正は
        ``{"error", "error_type"}`` (③ は LLM なので例外は回復不能)

    使い方 (実測 K2Mn[Fe(CN)6]): ``align_echem("K-10.mpr", offset_s=22.1, interval_s=283.0,
    n_frames=247)`` → 各フレームの電位と充放電状態。転移ドーム頂点フレームの ``voltage_v`` を
    充電カットオフ電位と照合する (実測: tetra JT ドーム頂点 = 充電カットオフ 2.100 V で一致)。
    """
    import numpy as np

    from ..interop.biologic import EchemUnavailableError, align_frames, parse_mpr

    # --- フレーム時刻の解決 (明示 epoch or 一定ケイデンス) ---
    cadence = (offset_s is not None) or (interval_s is not None) or (n_frames is not None)
    if frame_epoch_s is not None and cadence:
        return {
            "error": "frame_epoch_s と (offset_s/interval_s/n_frames) は排他です。どちらか一方で",
            "error_type": "ValueError",
        }
    try:
        curve = parse_mpr(mpr_path)
    except EchemUnavailableError as exc:
        return {"error": str(exc), "error_type": "EchemUnavailableError"}
    except (OSError, ValueError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    try:
        if frame_epoch_s is not None:
            epochs = [float(e) for e in frame_epoch_s]
        elif cadence:
            if offset_s is None or interval_s is None or n_frames is None:
                raise ValueError(
                    "一定ケイデンス経路は offset_s・interval_s・n_frames をすべて要します"
                )
            base = float(curve.start_timestamp) + float(offset_s)
            epochs = [base + float(interval_s) * i for i in range(int(n_frames))]
        else:
            raise ValueError(
                "frame_epoch_s か (offset_s + interval_s + n_frames) のいずれかが必要です"
            )
        points = align_frames(curve, epochs, clamp=bool(clamp))
    except (ValueError, TypeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    v = np.asarray(curve.voltage_v, dtype=float)
    return {
        "curve": {
            "start_timestamp": finite_or_none(curve.start_timestamp),
            "n_points": len(curve.time_s),
            "duration_s": finite_or_none(curve.time_s[-1]) if curve.time_s else None,
            "voltage_min": finite_or_none(float(v.min())) if v.size else None,
            "voltage_max": finite_or_none(float(v.max())) if v.size else None,
            "source_path": curve.source_path,
        },
        "frames": [
            {
                "frame": p.frame_index,
                "time_s": finite_or_none(p.time_s),
                "time_h": finite_or_none(p.time_s / 3600.0),
                "voltage_v": finite_or_none(p.voltage_v) if p.voltage_v is not None else None,
                "charge_mah": finite_or_none(p.charge_mah) if p.charge_mah is not None else None,
                "state": p.state,
                "in_span": bool(p.in_span),
            }
            for p in points
        ],
        "n_in_span": sum(1 for p in points if p.in_span),
        "reason": reason,
    }


#: MCP_TOOLS へマージする電気化学同期ツール (Issue #103)。
ECHEM_TOOLS: dict[str, object] = {
    "align_echem": align_echem,
}
