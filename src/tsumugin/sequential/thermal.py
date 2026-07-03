"""熱膨張ベースライン + 転移温度推定 (仕様 FR-322/FR-323 / interfaces.py L169-203)。

昇温 (operando / 高温) 粉末回折の時系列解析向けに、乱数・I/O・外部状態を持たない純関数 2 本を提供する:

- ``fit_thermal_baseline``: 格子定数-温度曲線を多項式 (既定 1 次) でフィットし、残差の中央値/MAD
  ロバスト z が閾値を超えるフレームを ``outlier_frames`` (= ベースライン逸脱 = 転移候補) として分離する。
- ``estimate_transition``: 相分率のシグモイド遷移から転移温度を onset / midpoint (50% 交差の線形補間)
  ± σ で推定する。onset は direction に依らず「遷移開始側 (低温側・先行するエッジ)」を指し、
  appearing (0→1) では分率 10% 交差、disappearing (1→0) では分率 90% 交差を採る (Issue #4 / REQ-021)。
  いずれの方向でも onset < midpoint。遷移が無い (定数分率・交差なし・点数不足) 場合は ``None`` を返す。

いずれも同一入力で結果がビット同一になる決定論 (REQ-402 / NFR-102) を満たし、算出不能な縮退では例外化・
非有限漏洩 (M1 教訓 / CLAUDE.md) を避けて ``None`` / 空タプルへ安全側に縮退する。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np

# 【修正 z 定数】: modified z-score の正規化定数 0.6745 (= 標準正規分布の 0.75 分位)。changepoint.py と同一。
# 🔵 信頼性レベル: §2.4 / changepoint.py の踏襲。
_MODIFIED_Z_CONST = 0.6745

# 【逸脱閾値】: 残差ロバスト z の発火閾値。changepoint.py の z_threshold=5.0 と揃え、逸脱 (z≈12) と
#   正常 (z≲1.3) を明瞭に分離する。🟡 Green 決定 (changepoint.py の既定 5.0 に整合)。
_OUTLIER_Z_THRESHOLD = 5.0

# 【転移レベル】: onset は遷移開始側 = appearing なら分率 10% 交差 / disappearing なら 90% 交差。
#   midpoint は方向非依存に分率 50% 交差 (Issue #4 / REQ-021 / interfaces.py L372-373)。
# 【設計方針】: direction 別 onset レベルを named 定数として明示 (真理値表を module 先頭に集約) し、
#   呼び出し側からインライン算術 (1 - _ONSET_LEVEL) を排して意図を自己文書化する。
# 🔵 信頼性レベル: requirements §2 の direction 別 onset レベル真理値表に依拠。
_ONSET_LEVEL = 0.10  # 【appearing onset】: 分率 10% 交差 = 増加相の遷移開始側 (低温側)
# 【disappearing onset】: 分率 90% 交差 (= 1 - _ONSET_LEVEL) = 減少相の遷移開始側 (低温側)。
#   appearing の 10% と対称。両方向とも onset < midpoint となる。🔵
_DISAPPEARING_ONSET_LEVEL = 1.0 - _ONSET_LEVEL
_MIDPOINT_LEVEL = 0.50


@dataclass(frozen=True)
class ThermalBaseline:
    """格子 vs T の多項式ベースラインと逸脱フレーム (転移候補)。

    【機能概要】: 熱膨張ベースラインの多項式係数・点毎残差・逸脱フレーム index を保持する不変値オブジェクト。
    【実装方針】: interfaces.py L173-180 の frozen dataclass 契約に一致。coefficients は「低次から」。
    【テスト対応】: TB-N01〜N04 / TB-E01〜E03 / TB-B01〜B02 を通す。
    🔵 信頼性レベル: interfaces.py L173-180 / requirements §2.1 に依拠 (係数順は 🟡)。
    """

    parameter: str  # 【対象パラメータ名】: "lattice.a" 等の呼び出し側指定識別子 🟡
    coefficients: tuple[float, ...]  # 【多項式係数】: 低次→高次 (polyfit の高次→低次を反転) 🟡
    residuals: tuple[float, ...]  # 【点毎残差】: values[i] - フィット値、values と同長・同順 🔵
    outlier_frames: tuple[int, ...]  # 【逸脱フレーム】: 残差ロバスト z 超過 index 昇順 (転移候補) 🔵


@dataclass(frozen=True)
class TransitionEstimate:
    """相分率トラジェクトリからの転移温度推定 (onset / midpoint ± σ / 方向)。

    【機能概要】: 転移温度を onset(10%) / midpoint(50%) ± σ と遷移方向で保持する不変値オブジェクト。
    【実装方針】: interfaces.py L183-191 の frozen dataclass 契約に一致。遷移なしは呼び出し側で None 表現。
    【テスト対応】: TE-N01〜N03 / TE-E01〜E03 / TE-B01〜B03 を通す。
    🔵 信頼性レベル: interfaces.py L183-191 / requirements §2.2 に依拠 (onset/σ/方向は 🟡)。
    """

    phase_ref: str  # 【対象相識別子】: 入力 phase_ref を透過保持 🔵
    # 【onset】: 遷移開始側 (低温側) の分率交差温度 (線形補間、交差なしは None)。direction に依らず
    #   onset < midpoint。appearing=10% 交差 / disappearing=90% 交差 (Issue #4 / REQ-021) 🔵
    onset: float | None
    midpoint: float | None  # 【midpoint】: 分率 50% 交差温度 (線形補間) 🟡
    sigma: float | None  # 【σ】: 遷移幅の代理散布度 (隣接フレーム間隔ベース、> 0) 🟡
    direction: Literal["appearing", "disappearing"]  # 【方向】: 増加→出現 / 減少→消滅 🟡


def _outlier_frames(residuals: tuple[float, ...]) -> tuple[int, ...]:
    """点毎残差の中央値/MAD ロバスト z が閾値を超えるフレーム index を昇順で返す。

    【機能概要】: 残差の中央値/MAD に対する各点の修正 z-score の絶対値が閾値超過の index 集合を求める。
    【実装方針】: MAD=0 (完全フィット等の散布度ゼロ) は 0 除算になるため空タプルへ縮退し非有限を漏らさない。
    【テスト対応】: TB-N01 (逸脱分離) / TB-E01 (MAD=0 縮退) / TB-B01 (逸脱なし) を支える。
    🔵 信頼性レベル: changepoint.py `_robust_z` の MAD=0 縮退パターン / CLAUDE.md 非有限漏洩禁止に依拠。
    @param residuals: 点毎残差のタプル
    @returns: 逸脱フレーム index の昇順タプル (逸脱なし・空入力は空タプル)
    """
    # 【空入力縮退】: 残差が無ければ逸脱判定不能のため空タプルへ縮退 🔵
    if not residuals:
        return ()
    # 【ロバスト統計】: 外れ値に強い中央値/MAD を散布度とする (少数の逸脱点に引きずられない) 🔵
    arr = np.asarray(residuals, dtype=float)
    median = np.median(arr)
    mad = np.median(np.abs(arr - median))
    # 【MAD=0 縮退ガード】: 散布度ゼロでは z が定義できず 0 除算になるため逸脱なし () に縮退 🔵
    if mad == 0.0:
        return ()
    # 【修正 z 算出】: 各点の中心からの逸脱を MAD で正規化し、絶対値が閾値超過の index を昇順収集 🔵
    z_scores = _MODIFIED_Z_CONST * (arr - median) / mad
    return tuple(i for i in range(arr.size) if abs(float(z_scores[i])) > _OUTLIER_Z_THRESHOLD)


def fit_thermal_baseline(
    temperatures: Sequence[float],
    values: Sequence[float],
    *,
    degree: int = 1,
    parameter: str = "",
) -> ThermalBaseline:
    """格子-温度曲線の熱膨張ベースラインを多項式フィットし逸脱フレームを分離する純関数。

    【機能概要】: 温度に対する対象値 (格子定数等) を degree 次多項式でフィットし、点毎残差のロバスト z が
      閾値超過のフレームを outlier_frames (転移候補) として分離する (FR-322 / REQ-007)。
    【実装方針】: numpy.polyfit の係数は高次→低次のため反転して「低次から」格納。点数不足 (len < degree+1) は
      例外化せず定数フィットへ安全側縮退し、非有限を漏らさない。乱数・I/O なしで決定論 (同一入力ビット同一)。
    【テスト対応】: TB-N01〜N04 (フィット/係数順/残差/2 次) / TB-E01〜E03 (縮退/frozen) / TB-B01〜B02 (最小点数/決定論)。
    🔵 信頼性レベル: requirements §2.1 / interfaces.py L194-196 / TC-105-03 に依拠 (係数順・逸脱閾値は 🟡)。
    @param temperatures: フレーム毎の温度 (values と同長)
    @param values: フレーム毎の対象値 (格子定数等)
    @param degree: 多項式次数 (キーワード専用、既定 1 = 線形熱膨張)
    @param parameter: 対象パラメータ名の識別子 (キーワード専用、結果へ透過保持)
    @returns: ThermalBaseline (係数・点毎残差・逸脱フレーム)
    """
    # 【配列化】: numpy 演算のため float 配列へ変換 (決定論のため dtype を明示) 🔵
    temps = np.asarray(temperatures, dtype=float)
    vals = np.asarray(values, dtype=float)
    n = temps.size

    # 【点数不足の安全側縮退】: len < degree+1 では最小二乗解が一意でないため例外化せず縮退 (TB-E02) 🟡
    if n < degree + 1:
        # 【空入力縮退】: フレームが皆無なら全フィールドを空タプルへ縮退 🟡
        if n == 0:
            return ThermalBaseline(parameter, (), (), ())
        # 【定数フィット縮退】: 平均値の 0 次フィットへ退避し、非有限を漏らさず点毎残差を保つ 🟡
        mean = float(np.mean(vals))
        residuals = tuple(float(v) - mean for v in vals)
        return ThermalBaseline(parameter, (mean,), residuals, _outlier_frames(residuals))

    # 【多項式フィット】: numpy.polyfit で degree 次係数 (高次→低次) を最小二乗推定 🔵
    coeffs_high_to_low = np.polyfit(temps, vals, degree)
    # 【点毎残差】: 各温度でのフィット予測に対する実測との差 (SSR 単一値でなく点毎) 🔵
    predictions = np.polyval(coeffs_high_to_low, temps)
    residuals = tuple(float(r) for r in (vals - predictions))
    # 【係数順反転】: polyfit の高次→低次を「低次から」契約に合わせて反転格納 (off-by-order 防止) 🟡
    coefficients = tuple(float(c) for c in coeffs_high_to_low[::-1])
    # 【逸脱分離】: 点毎残差のロバスト z 超過フレームを転移候補として分離 🔵
    return ThermalBaseline(parameter, coefficients, residuals, _outlier_frames(residuals))


def _interpolate_crossing(
    temperatures: Sequence[float], fractions: Sequence[float], level: float
) -> tuple[float, int] | None:
    """分率が指定レベルを最初に横切る隣接フレーム対を線形補間し (温度, 開始 index) を返す。

    【機能概要】: 隣接対 (f_i, f_{i+1}) がレベルを挟む (端点一致含む) 最初の対を線形補間して交差温度を得る。
    【実装方針】: 増加/減少どちらの交差も符号積 <= 0 で検出。平坦対 (f_i == f_{i+1}) は 0 除算回避のため除外し、
      最初 (最小 index) の交差を選んで決定論を担保する。
    【テスト対応】: TE-N01 (midpoint) / TE-B01 (端点一致) / TE-E01 (交差なし→None) を支える。
    🟡 信頼性レベル: interfaces.py の 50%/10% 線形補間契約からの妥当な実装。
    @param temperatures: フレーム毎の温度
    @param fractions: フレーム毎の相分率
    @param level: 交差を判定するレベル (0.50 / 0.10 等)
    @returns: (交差温度, 交差開始 index)。交差が無ければ None
    """
    # 【交差探索】: 先頭から走査し、レベルを挟む最初の隣接対を採る (決定論的に 1 つを選ぶ) 🟡
    for i in range(len(fractions) - 1):
        f0 = float(fractions[i])
        f1 = float(fractions[i + 1])
        # 【平坦対の除外】: 両端が同値では補間の分母が 0 になるため交差候補から除外 (定数分率→交差なし) 🟡
        if f0 == f1:
            continue
        # 【交差判定】: レベルからの符号積 <= 0 で挟み込み (端点一致=積 0 も交差として含む) 🟡
        if (f0 - level) * (f1 - level) <= 0.0:
            # 【線形補間】: 交差レベルに対応する温度を隣接対で内挿 (f0 != f1 を保証済み) 🟡
            temp = float(temperatures[i]) + (level - f0) / (f1 - f0) * (
                float(temperatures[i + 1]) - float(temperatures[i])
            )
            return temp, i
    # 【交差なし】: レベルを横切らなければ None (偽の転移温度を出さない) 🔵
    return None


def estimate_transition(
    temperatures: Sequence[float], fractions: Sequence[float], *, phase_ref: str
) -> TransitionEstimate | None:
    """相分率シグモイド遷移から転移温度を onset/midpoint ± σ で推定する純関数。

    【機能概要】: 分率が 50% を横切る温度を midpoint、遷移開始側レベルを横切る温度を onset として
      線形補間で求め、遷移幅の代理散布度 σ (隣接フレーム間隔ベース) と方向を推定する (FR-323 / REQ-008)。
    【onset 意味論】: onset は direction に依らず「遷移が始まる側 (低温側・先行するエッジ)」を指す。
      appearing (0→1) は分率 10% 交差、disappearing (1→0) は分率 90% 交差を採り、いずれの方向でも
      onset < midpoint となる (Issue #4 / REQ-021 / TC-208-01)。
    【実装方針】: 補間に必要な隣接対が作れない (点数 < 2) / 50% 交差が無い (定数分率等) 場合は例外化せず
      None へ縮退。方向は分率の全体トレンドで判定。乱数・I/O なしで決定論 (同一入力ビット同一)。
    【テスト対応】: TE-N01〜N03 (midpoint/方向/識別子) / TE-E01〜E03 (定数・空/単一・frozen) / TE-B01〜B03 /
      TC-T-N02〜N03・TC-T-E01・TC-T-B01〜B04 (disappearing onset=90% 交差の意味論修正)。
    🔵 信頼性レベル: requirements §2.2 / interfaces.py L372-373 / TC-105-04 / TASK-0024 requirements §2 に依拠。
    @param temperatures: フレーム毎の温度 (fractions と同長)
    @param fractions: フレーム毎の相分率トラジェクトリ (0..1 想定)
    @param phase_ref: 対象相の識別子 (キーワード専用、結果へ透過保持)
    @returns: TransitionEstimate。遷移が無ければ None
    """
    # 【点数不足の縮退】: 線形補間は隣接対 (点数 >= 2) が必須。空/単一フレームは None へ一元化 (TE-E02) 🟡
    if len(temperatures) < 2 or len(fractions) < 2:
        return None

    # 【midpoint 推定】: 分率 50% を最初に横切る隣接対を線形補間。交差なし (定数分率等) は遷移なしとして None 🔵
    midpoint_hit = _interpolate_crossing(temperatures, fractions, _MIDPOINT_LEVEL)
    if midpoint_hit is None:
        return None
    midpoint, cross_index = midpoint_hit

    # 【方向判定】: 分率が増加基調なら出現 (appearing)、減少基調なら消滅 (disappearing) 🟡
    direction: Literal["appearing", "disappearing"] = (
        "appearing" if float(fractions[-1]) >= float(fractions[0]) else "disappearing"
    )

    # 【onset レベル選択】: onset は遷移開始側 (低温側) — appearing は 10% 交差、disappearing は
    #   90% 交差 (_DISAPPEARING_ONSET_LEVEL) を採る。direction 依存化はこの 1 点のみの最小修正 (Issue #4) 🔵
    onset_level = _ONSET_LEVEL if direction == "appearing" else _DISAPPEARING_ONSET_LEVEL
    # 【onset 推定】: 選択レベルを最初に横切る温度 (交差が無ければ None へ縮退し非有限を漏らさない) 🔵
    onset_hit = _interpolate_crossing(temperatures, fractions, onset_level)
    onset = onset_hit[0] if onset_hit is not None else None

    # 【σ 推定】: 遷移が起きた隣接フレームの温度間隔を遷移幅の代理散布度とする (> 0・有限・間隔オーダー) 🟡
    sigma = abs(float(temperatures[cross_index + 1]) - float(temperatures[cross_index]))

    # 【結果返却】: 推定した転移温度・散布度・方向を不変値オブジェクトへ格納 🔵
    return TransitionEstimate(
        phase_ref=phase_ref,
        onset=onset,
        midpoint=midpoint,
        sigma=sigma,
        direction=direction,
    )
