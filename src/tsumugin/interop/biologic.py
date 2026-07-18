"""BioLogic EC-Lab (``.mpr``) 電気化学データの読み取りと operando 回折フレームへの整列。

operando 測定では、回折フレーム列 (時刻付き) と電気化学曲線 (時刻付き) が**別ファイル**に出る。
本モジュールは両者を共通時間軸で突き合わせ、各回折フレームに (電圧, 容量, 充放電状態) を与える。
これにより相分率・格子定数を電圧/容量に対してプロットできる (M10 operando 電気化学同期)。

- :func:`parse_mpr` — EC-Lab ``.mpr`` を :class:`EchemCurve` へ読む (**galvani を遅延 import**)。
- :func:`curve_from_mpr_data` — galvani の構造化配列 → :class:`EchemCurve` (numpy-only の純関数)。
- :func:`align_frames` — フレームの POSIX 時刻列 → :class:`FramePoint` 列 (線形補間 + 状態ラベル)。

【遅延 import 契約】: ``import tsumugin.interop.biologic`` は コア (numpy) のみで成功し、galvani を
  引き込まない。galvani を要求するのは :func:`parse_mpr` の呼び出し時点のみで、未導入なら
  :class:`EchemUnavailableError` を送出して optional extra ``echem`` の導入手順を案内する
  (``MPUnavailableError`` / ``GSASUnavailableError`` と対称の「available + 専用例外」パターン)。

【フィールド名の版差】: EC-Lab の列名はバージョン/テクニックで変わる (``Ewe/V`` / ``<Ewe>/V``、
  ``(Q-Qo)/mA.h`` / ``(Q-Qo)/C`` 等)。決め打ちせず別名候補を順に探し、見つからなければ**探した
  候補名と実在フィールド名の双方**を挙げて ``ValueError`` で fail-loud する (静かな 0 埋めをしない)。

【時間軸の規約】: :attr:`EchemCurve.start_timestamp` は取得開始の POSIX 秒。galvani の
  ``MPRfile.timestamp`` は tz 情報を持たない ``datetime`` のため、**測定 PC のローカルタイムゾーン**
  として POSIX 秒へ換算する。回折フレーム側の時刻も同じ規約で POSIX 秒に揃えて渡すこと。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..errors import TsumuginError

__all__ = [
    "EchemCurve",
    "EchemUnavailableError",
    "FramePoint",
    "align_frames",
    "curve_from_mpr_data",
    "parse_mpr",
]


class EchemUnavailableError(TsumuginError):
    """optional extra ``echem`` (galvani) 未導入で ``.mpr`` の読み取りを要求したとき。🔵

    ``MPUnavailableError`` / ``WebUIUnavailableError`` と対称。``import tsumugin.interop.biologic``
    自体はコア (numpy) のみで成功し、:func:`parse_mpr` の呼び出し時にのみ本例外を送出する。
    :func:`curve_from_mpr_data` / :func:`align_frames` は本例外に依存せずコアのみで動作する。
    """


# --------------------------------------------------------------------------------------
# フィールド名の別名表 (EC-Lab のバージョン/テクニック差を吸収する)
# --------------------------------------------------------------------------------------
_TIME_ALIASES: tuple[str, ...] = ("time/s", "time/S", "Time/s")
_VOLTAGE_ALIASES: tuple[str, ...] = ("Ewe/V", "<Ewe>/V", "Ecell/V", "<Ecell>/V", "E/V")
# 電荷は単位が版で異なる。(フィールド名, mA.h への換算係数) で持つ (1 C = 1/3.6 mA.h)。
_CHARGE_ALIASES: tuple[tuple[str, float], ...] = (
    ("(Q-Qo)/mA.h", 1.0),
    ("(Q-Qo)/C", 1.0 / 3.6),
    ("Q charge/discharge/mA.h", 1.0),
    ("Capacity/mA.h", 1.0),
)
_STEP_ALIASES: tuple[str, ...] = ("Ns",)
_HALF_CYCLE_ALIASES: tuple[str, ...] = ("half cycle",)

_STATE_REST = "rest"
_STATE_CHARGE = "charge"
_STATE_DISCHARGE = "discharge"
_STATE_UNKNOWN = "unknown"

_REST_REL_TOL = 0.01
"""ステップを rest と見なす正味電荷変化の相対閾値 (全ステップ中の最大 |ΔQ| に対する比)。"""


@dataclass(frozen=True)
class EchemCurve:
    """BioLogic ``.mpr`` 1 本の電気化学曲線 (供給元非依存のコア値オブジェクト)。🔵

    :param time_s: 取得開始からの経過時間 [s] (時間昇順に整列済み)
    :param voltage_v: 作用極電位 ``Ewe`` [V]
    :param charge_mah: 積算電荷 ``(Q-Qo)`` [mA·h] (充電で増加・放電で減少)
    :param half_cycle: EC-Lab の ``half cycle`` (0=充電 / 1=放電)。欠落時は 0 埋め
    :param step_index: EC-Lab の技法ステップ番号 ``Ns``。欠落時は 0 埋め
    :param start_timestamp: 取得開始の POSIX 秒 (モジュール docstring の時間軸規約を参照)
    :param source_path: 読み取り元パス (来歴)
    """

    time_s: tuple[float, ...]
    voltage_v: tuple[float, ...]
    charge_mah: tuple[float, ...]
    half_cycle: tuple[float, ...]
    step_index: tuple[float, ...]
    start_timestamp: float
    source_path: str

    @property
    def duration_s(self) -> float:
        """曲線の時間幅 [s] (末尾 − 先頭)。点が無ければ 0.0。🔵"""
        if not self.time_s:
            return 0.0
        return self.time_s[-1] - self.time_s[0]


@dataclass(frozen=True)
class FramePoint:
    """回折フレーム 1 枚に整列した電気化学状態。🔵

    :param frame_index: 入力 ``frame_epoch_s`` 中の位置 (回折フレーム番号との対応を保つため、
        時系列で並べ替えない)
    :param time_s: ``curve.start_timestamp`` を基準とした相対時刻 [s] (範囲外でも実値を返す)
    :param voltage_v: 補間電位 [V]。曲線の時間範囲外かつ ``clamp=False`` なら None
    :param charge_mah: 補間積算電荷 [mA·h]。同上
    :param state: ``"rest"`` / ``"charge"`` / ``"discharge"`` (曲線から導出)。範囲外かつ
        ``clamp=False`` なら ``"unknown"``
    :param in_span: フレーム時刻が曲線の時間範囲 (端点を含む) の内側か
    """

    frame_index: int
    time_s: float
    voltage_v: float | None
    charge_mah: float | None
    state: str
    in_span: bool


def _field_names(data: np.ndarray) -> tuple[str, ...]:
    """構造化配列のフィールド名 (dtype.names)。"""
    names = data.dtype.names
    if names is None:
        raise ValueError(
            "BioLogic データが構造化配列ではありません (galvani MPRfile.data 相当が必要です)。"
        )
    return tuple(names)


def _pick(
    data: np.ndarray, aliases: Sequence[str], present: Sequence[str]
) -> tuple[str, np.ndarray] | None:
    """``aliases`` の先頭から実在するフィールドを探して ``(名前, 値)`` を返す。無ければ None。"""
    for name in aliases:
        if name in present:
            return name, np.asarray(data[name], dtype=float)
    return None


def _require(
    data: np.ndarray, aliases: Sequence[str], present: Sequence[str], label: str
) -> np.ndarray:
    """必須フィールドを取り出す。見つからなければ候補名と実在名を挙げて fail-loud する。"""
    found = _pick(data, aliases, present)
    if found is None:
        raise ValueError(
            f"BioLogic .mpr に{label}のフィールドが見つかりません。"
            f" 探した候補: {list(aliases)} / 実在するフィールド: {list(present)}。"
            " EC-Lab はバージョン・テクニックで列名が変わります"
            " (別名なら tsumugin.interop.biologic の別名表に追加してください)。"
        )
    return found[1]


def _optional(
    data: np.ndarray, aliases: Sequence[str], present: Sequence[str], size: int
) -> np.ndarray:
    """任意フィールドを取り出す (欠落は 0 埋め)。"""
    found = _pick(data, aliases, present)
    return found[1] if found is not None else np.zeros(size, dtype=float)


def curve_from_mpr_data(
    data: np.ndarray, *, start_timestamp: float, source_path: str = ""
) -> EchemCurve:
    """galvani の構造化配列 (``MPRfile.data``) を :class:`EchemCurve` へ変換する。🔵

    galvani に非依存の純関数 (numpy-only・決定論)。時間昇順でない入力は安定ソートで整列する。

    Raises:
        ValueError: 構造化配列でない / 時間・電圧・電荷の必須フィールドがどの別名でも見つからない。
    """
    present = _field_names(data)
    time_s = _require(data, _TIME_ALIASES, present, "時間 (time)")
    voltage = _require(data, _VOLTAGE_ALIASES, present, "電圧 (voltage)")

    charge_found = next(
        ((name, factor) for name, factor in _CHARGE_ALIASES if name in present), None
    )
    if charge_found is None:
        raise ValueError(
            "BioLogic .mpr に電荷 (charge) のフィールドが見つかりません。"
            f" 探した候補: {[name for name, _f in _CHARGE_ALIASES]}"
            f" / 実在するフィールド: {list(present)}。"
            " EC-Lab はバージョン・テクニックで列名が変わります"
            " (別名なら tsumugin.interop.biologic の別名表に追加してください)。"
        )
    charge = np.asarray(data[charge_found[0]], dtype=float) * charge_found[1]

    n = int(time_s.size)
    half_cycle = _optional(data, _HALF_CYCLE_ALIASES, present, n)
    step_index = _optional(data, _STEP_ALIASES, present, n)

    order = np.argsort(time_s, kind="stable")
    return EchemCurve(
        time_s=tuple(time_s[order].tolist()),
        voltage_v=tuple(voltage[order].tolist()),
        charge_mah=tuple(charge[order].tolist()),
        half_cycle=tuple(half_cycle[order].tolist()),
        step_index=tuple(step_index[order].tolist()),
        start_timestamp=float(start_timestamp),
        source_path=str(source_path),
    )


def parse_mpr(path: str | Path) -> EchemCurve:
    """BioLogic EC-Lab ``.mpr`` を読み :class:`EchemCurve` を返す。🔵

    galvani (``from galvani import BioLogic``) を**呼び出し時に遅延 import** する。

    Raises:
        EchemUnavailableError: galvani (optional extra ``echem``) 未導入のとき。
        ValueError: 必須フィールドがどの別名でも見つからないとき (:func:`curve_from_mpr_data`)。
    """
    try:
        from galvani import BioLogic  # 遅延 import (モジュール import では引き込まない)
    except ImportError as exc:  # pragma: no cover - 導入環境では通らない
        raise EchemUnavailableError(
            "BioLogic .mpr の読み取りには galvani が必要です (optional extra 'echem')。"
            " `uv sync --extra echem` (既存の extra と併用するなら"
            " `uv sync --extra gsas --extra echem`) で導入してください。"
        ) from exc

    mpr = BioLogic.MPRfile(str(path))
    return curve_from_mpr_data(
        mpr.data,
        start_timestamp=mpr.timestamp.timestamp(),  # naive datetime → ローカル tz で POSIX 秒
        source_path=str(path),
    )


def _sample_states(curve: EchemCurve) -> np.ndarray:
    """各測定点の状態ラベル (``rest``/``charge``/``discharge``) を**曲線から導出**する。🔵

    ``Ns`` の連続する同値ブロック (= 技法ステップ) ごとに正味電荷変化 ΔQ = Q[末] − Q[先] を取り、
    全ステップ中の最大 |ΔQ| に対して相対 1% 以下なら rest、正なら charge、負なら discharge とする。
    電流列を必要とせず (版により列名が最も揺れる)、rest/charge/discharge を電荷の実測から決める。
    ``Ns`` が無い ``.mpr`` では全点が 1 ステップになり、曲線全体の正味 ΔQ で 1 ラベルが付く。
    """
    n = len(curve.time_s)
    if n == 0:
        return np.empty(0, dtype="<U9")
    charge = np.asarray(curve.charge_mah, dtype=float)
    step = np.asarray(curve.step_index, dtype=float)

    # 連続する同値ブロックの境界 (サイクリングで Ns が再出現しても別ブロックとして扱う)。
    starts = [0, *(int(i) for i in np.flatnonzero(np.diff(step) != 0.0) + 1)]
    ends = [*(s for s in starts[1:]), n]
    deltas = np.array([charge[e - 1] - charge[s] for s, e in zip(starts, ends)], dtype=float)

    span = float(np.max(np.abs(deltas))) if deltas.size else 0.0
    tol = max(_REST_REL_TOL * span, 1.0e-12)

    states = np.empty(n, dtype="<U9")
    for (s, e), d in zip(zip(starts, ends), deltas.tolist()):
        if abs(d) <= tol:
            states[s:e] = _STATE_REST
        else:
            states[s:e] = _STATE_CHARGE if d > 0.0 else _STATE_DISCHARGE
    return states


def align_frames(
    curve: EchemCurve, frame_epoch_s: Sequence[float], *, clamp: bool = False
) -> tuple[FramePoint, ...]:
    """回折フレームの POSIX 時刻列を電気化学曲線へ整列する。🔵

    各フレーム時刻を ``curve.start_timestamp`` 基準の相対時刻へ直し、電圧・積算電荷を**線形補間**、
    状態は最近傍測定点のラベル (:func:`_sample_states`) を採る。返り値は入力順 (時系列へ並べ替え
    しない — ``frame_index`` が回折フレーム番号に対応する)。

    **範囲外フレームは外挿しない** (電圧の捏造を避ける): 既定 (``clamp=False``) では
    ``voltage_v``/``charge_mah`` を None、``state`` を ``"unknown"`` にする。``clamp=True`` では
    最寄り端点の値で丸めるが、丸めた事実は ``in_span=False`` に残る (下流が区別できる)。

    Args:
        curve: :func:`parse_mpr` 等で得た電気化学曲線。
        frame_epoch_s: 回折フレーム 1 枚ごとの POSIX 秒。
        clamp: True で範囲外を端点値へ丸める。

    Raises:
        ValueError: ``curve`` が空 / ``frame_epoch_s`` に非有限値が含まれるとき。
    """
    epochs = np.asarray(list(frame_epoch_s), dtype=float)
    if epochs.size == 0:
        return ()
    if not np.all(np.isfinite(epochs)):
        raise ValueError("frame_epoch_s に有限でない値 (NaN/inf) が含まれています。")
    if not curve.time_s:
        raise ValueError("EchemCurve が空です (整列できません)。")

    t = np.asarray(curve.time_s, dtype=float)
    v = np.asarray(curve.voltage_v, dtype=float)
    q = np.asarray(curve.charge_mah, dtype=float)
    states = _sample_states(curve)

    rel = epochs - curve.start_timestamp
    inside = (rel >= t[0]) & (rel <= t[-1])
    # np.interp は範囲外を端点値で丸める = clamp の意味論そのもの。
    v_i = np.interp(rel, t, v)
    q_i = np.interp(rel, t, q)
    # 状態は最近傍測定点から (補間しない離散ラベル)。
    nearest = np.clip(np.searchsorted(t, rel), 0, t.size - 1)
    left = np.clip(nearest - 1, 0, t.size - 1)
    take_left = np.abs(rel - t[left]) <= np.abs(t[nearest] - rel)
    nearest = np.where(take_left, left, nearest)

    points: list[FramePoint] = []
    for i in range(rel.size):
        ok = bool(inside[i])
        if ok or clamp:
            points.append(
                FramePoint(
                    frame_index=i,
                    time_s=float(rel[i]),
                    voltage_v=float(v_i[i]),
                    charge_mah=float(q_i[i]),
                    state=str(states[nearest[i]]),
                    in_span=ok,
                )
            )
        else:
            points.append(
                FramePoint(
                    frame_index=i,
                    time_s=float(rel[i]),
                    voltage_v=None,
                    charge_mah=None,
                    state=_STATE_UNKNOWN,
                    in_span=False,
                )
            )
    return tuple(points)
