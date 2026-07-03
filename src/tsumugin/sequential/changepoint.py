"""複合指標 changepoint 検出 (仕様 §2.4 / interfaces.py L81-110 / dataflow.md 複合指標)。

直近 ``window`` 窓の中央値/MAD ロバスト z を 3 指標 (Rwp の跳ね / 格子フレーム間差分のジャンプ /
新規未マッチピーク数) の OR で判定する純関数 ``detect_changepoint`` を提供する (REQ-003 / FR-303)。
乱数・I/O・外部状態を持たず、同一入力・同一設定で ``ChangepointSignal`` がビット同一になる (REQ-402 決定論)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

# 【修正 z 定数】: modified z-score の正規化定数 0.6745 (= 標準正規分布の 0.75 分位) 🟡 §2.4
_MODIFIED_Z_CONST = 0.6745


@dataclass(frozen=True)
class ChangepointConfig:
    """複合指標 changepoint の設定 (窓/閾値/新規ピーク下限)。

    【機能概要】: ローリング窓幅・robust z 発火閾値・新規未マッチピークの下限を保持する不変設定。
    【実装方針】: interfaces.py L81-88 / D-Q3 の既定値 (W=5 / 閾値 5.0 / 下限 1) に一致させる。
    【テスト対応】: TC-C-B05 (既定値) を通す。
    🔵 信頼性レベル: interfaces.py L81-88 / design-interview D-Q3 に依拠 (既定値は 🟡)。
    """

    window: int = 5  # 【ローリング窓】: 直近 W フレーム 🟡 D-Q3
    z_threshold: float = 5.0  # 【発火閾値】: robust z の strict 超過閾値 🟡 D-Q3
    min_new_peaks: int = 1  # 【新規ピーク下限】: new_peaks 発火の下限 🟡 interfaces.py L88


@dataclass(frozen=True)
class ChangepointSignal:
    """1 フレームの changepoint 判定結果 (どの指標が発火したか)。

    【機能概要】: 現フレームの判定結果と各指標の逸脱量、発火した指標名 (説明可能性) を保持する。
    【実装方針】: interfaces.py L90-99 の frozen dataclass 契約に一致。triggered == (len(reasons) > 0)。
    【テスト対応】: TC-C-N06 (フィールド充足) / TC-C-E03 (frozen) を通す。
    🔵 信頼性レベル: interfaces.py L90-99 / 完了条件⑤ に依拠 (frame_index の由来は 🟡)。
    """

    frame_index: int  # 【フレーム番号】: 履歴末尾インデックス len(rwp_history)-1 由来 🟡
    triggered: bool  # 【発火有無】: 3 指標の OR (len(reasons) > 0) 🔵
    z_rwp: float  # 【Rwp 逸脱量】: 現フレーム Rwp の robust z 🔵
    z_lattice: float  # 【格子逸脱量】: 各軸フレーム間差分の robust z の最大絶対値 🔵
    new_unmatched: int  # 【新規ピーク数】: 現フレームの新規未マッチピーク数 🔵
    reasons: tuple[str, ...]  # 【発火指標名】: "rwp_jump"|"lattice_jump"|"new_peaks" を発生順に 🔵


def _robust_z(window: np.ndarray) -> float:
    """窓の中央値/MAD に対する末尾要素の修正 z スコアを返す (MAD=0 は 0.0 に縮退)。

    【機能概要】: 修正 z-score ``0.6745 * (x - median) / MAD`` (MAD = median(|x - median|)) を算出。
    【実装方針】: x は窓の末尾要素 (現フレーム値)。MAD=0 の縮退は例外化せず 0.0 に縮退し非有限を漏らさない。
    【テスト対応】: TC-C-N01/N02 (発火) / TC-C-E02 (MAD=0 縮退) を支える。
    🔵 信頼性レベル: §2.4 (modified z-score) / 完了条件⑥ / CLAUDE.md「非有限値を漏らさない」に依拠。
    @param window: 直近窓の値配列 (末尾が現フレーム値)
    @returns: 修正 z スコア (MAD=0 なら 0.0)
    """
    # 【中央値/MAD】: ロバスト統計。外れ値 (現フレームの跳ね) の影響を受けにくい中心/散布度 🔵
    median = np.median(window)
    mad = np.median(np.abs(window - median))
    # 【MAD=0 縮退ガード】: 窓内全同値では 0 除算になるため z=0.0 に縮退し発火させない (完了条件⑥) 🔵
    if mad == 0.0:
        return 0.0
    # 【修正 z 算出】: 末尾要素 (現フレーム) の中心からの逸脱を MAD で正規化 🔵
    return float(_MODIFIED_Z_CONST * (window[-1] - median) / mad)


def _axis_diff_series(lattice_history: Sequence[Mapping[str, float]], key: str) -> list[float]:
    """指定軸のフレーム間差分列を返す (両フレームに存在する連続対のみ)。

    【機能概要】: 生の格子値でなく隣接フレーム差分列を作る (線形熱膨張の滑らかなトレンドを誤発火させない)。
    【実装方針】: 存在軸のみで集約するため、両端に key が存在する連続対のみ差分を採る (格子キー可変対応)。
    【テスト対応】: TC-C-N02 (格子ジャンプ) / TC-C-N04 (線形膨張の非発火) を支える。
    🔵 信頼性レベル: §2.4 step3 「格子差分に robust z を適用」/ dataflow.md 複合指標に依拠。
    @param lattice_history: 各フレームの格子定数マッピング列 (末尾が現フレーム)
    @param key: 対象軸キー ("a"|"b"|"c" 等)
    @returns: フレーム間差分の並び (末尾が現フレーム差分)
    """
    # 【差分列構築】: 連続フレーム対の差分を採り、生値の滑らかなトレンドを打ち消す 🔵
    diffs: list[float] = []
    for i in range(1, len(lattice_history)):
        prev = lattice_history[i - 1]
        curr = lattice_history[i]
        if key in prev and key in curr:
            diffs.append(float(curr[key]) - float(prev[key]))
    return diffs


def _lattice_z(lattice_history: Sequence[Mapping[str, float]], *, window: int) -> float:
    """格子 a/b/c 各軸のフレーム間差分 robust z の最大絶対値を返す (§2.4 step3)。

    【機能概要】: 現フレームに存在する各軸について差分列末尾の robust z を求め、その最大絶対値を返す。
    【実装方針】: 軸キーはソートして決定論を担保 (dict 反復順非依存)。集約は max(|z|) 規則 (§2.4 / 完了条件)。
    【テスト対応】: TC-C-N02 (単独発火) / TC-C-B04 (複数キー決定論) を支える。
    🔵 信頼性レベル: §2.4 step3 (最大絶対 z) / REQ-402 (決定論) に依拠。
    @param lattice_history: 各フレームの格子定数マッピング列
    @param window: ロバスト窓幅 (差分列の末尾 window 要素を用いる)
    @returns: 各軸の robust z 絶対値の最大 (対象軸なしなら 0.0)
    """
    # 【対象軸決定】: 現フレームに存在する軸のみを対象とし、ソートで反復順非依存の決定論を担保 🔵
    if len(lattice_history) < 2:
        return 0.0
    axis_keys = sorted(lattice_history[-1].keys())
    z_values: list[float] = []
    for key in axis_keys:
        diffs = _axis_diff_series(lattice_history, key)
        if not diffs:
            continue
        # 【窓切り出し】: 差分列の末尾 window 要素を採り、末尾 (現フレーム差分) の robust z を評価 🔵
        window_diffs = np.asarray(diffs[-window:], dtype=float)
        z_values.append(abs(_robust_z(window_diffs)))
    # 【最大絶対 z】: いずれかの軸の逸脱が最大のものを z_lattice とする (対象なしは 0.0 縮退) 🔵
    return max(z_values) if z_values else 0.0


def detect_changepoint(
    rwp_history: Sequence[float],
    lattice_history: Sequence[Mapping[str, float]],
    new_unmatched: int,
    *,
    config: ChangepointConfig = ChangepointConfig(),
) -> ChangepointSignal:
    """直近窓のロバスト統計に対する現フレームの複合指標逸脱を判定する純関数。

    【機能概要】: (a) Rwp の跳ね / (b) 格子フレーム間差分のジャンプ / (c) 新規未マッチピーク数 の 3 指標を
      直近 window 窓の中央値/MAD robust z で評価し、OR で changepoint を判定する (REQ-003 / FR-303)。
    【実装方針】: warm-up (履歴 < window) と MAD=0 は例外化せず安全側縮退。乱数・I/O・外部状態なしで決定論。
    【テスト対応】: TC-C-N01〜N06 / TC-C-E01〜E03 / TC-C-B01〜B05 を通す。
    🔵 信頼性レベル: §2.4 判定ロジック / dataflow.md 複合指標 / REQ-402 (決定論) に依拠。
    @param rwp_history: 直近フレームまでの Rwp 値の並び (末尾が現フレーム)
    @param lattice_history: 各フレームの格子定数マッピングの並び (末尾が現フレーム)
    @param new_unmatched: 現フレームの新規未マッチピーク数 (非負整数)
    @param config: 窓/閾値/下限 (キーワード専用)
    @returns: 現フレーム 1 件の ChangepointSignal
    """
    # 【フレーム番号確定】: 履歴末尾インデックスを frame_index とする (縮退時も一貫) 🟡 §2.4
    frame_index = len(rwp_history) - 1

    # 【warm-up 縮退】: 母数不足 (履歴 < window) では検出せず全指標を安全側縮退 (完了条件④) 🟡
    if len(rwp_history) < config.window:
        return ChangepointSignal(
            frame_index=frame_index,
            triggered=False,
            z_rwp=0.0,
            z_lattice=0.0,
            new_unmatched=new_unmatched,
            reasons=(),
        )

    # 【指標(a) Rwp 逸脱】: 直近 window 個の Rwp に対する現フレーム値の robust z 🔵 §2.4 step2
    rwp_window = np.asarray(rwp_history[-config.window :], dtype=float)
    z_rwp = _robust_z(rwp_window)

    # 【指標(b) 格子逸脱】: 各軸フレーム間差分の robust z の最大絶対値 🔵 §2.4 step3
    z_lattice = _lattice_z(lattice_history, window=config.window)

    # 【OR 結合】: 発火した指標名を発生順 (rwp → lattice → new_peaks) に集約し説明可能性を担保 🔵 §2.4 step5
    reasons: list[str] = []
    if z_rwp > config.z_threshold:  # 【strict 判定】: dataflow「z > 5」の厳密解釈 🟡 §2.4
        reasons.append("rwp_jump")
    if z_lattice > config.z_threshold:
        reasons.append("lattice_jump")
    if new_unmatched >= config.min_new_peaks:  # 【下限包含】: 単純カウント閾値 (>=) 🟡 §2.4 step4
        reasons.append("new_peaks")

    # 【結果返却】: triggered は 3 指標 OR (len(reasons) > 0)。全フィールドが判定過程を反映 🔵
    return ChangepointSignal(
        frame_index=frame_index,
        triggered=len(reasons) > 0,
        z_rwp=z_rwp,
        z_lattice=z_lattice,
        new_unmatched=new_unmatched,
        reasons=tuple(reasons),
    )
