"""確率較正評価ユーティリティ (M5 / REQ-014〜017/106/EDGE-012)。

reliability diagram / ECE により、仮説確率 (softmax + 温度較正の出力) の較正を評価する。
確率出力そのものは ``evidence.ranking.rank`` 側の責務であり、本モジュールは **予測確率入力のみ**
に依存する較正評価ユーティリティに徹する (evidence 値・nested サンプラに非依存, TASK-0052)。

bic と nested は別系列で評価する (§12-5)。``CalibrationSample.backend`` を系列分離キーとし、
``calibrate_by_backend`` が backend ごとに独立した ``CalibrationReport`` を返す (REQ-016/106/EDGE-012)。
各 report には確率の意味 (BIC 近似事後確率 vs logZ ベース事後確率) を明記する (REQ-015/NFR-004)。

コア依存は numpy のみ (較正計算は素の算術で決定論的に閉じる)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# 各 backend の確率の意味を明記する説明文 (REQ-015/NFR-004)。
_PROBABILITY_SEMANTICS: dict[str, str] = {
    "bic": "BIC 近似事後確率 (softmax(-BIC/2))",
    "laplace": "Laplace 近似事後確率 (softmax(-(-logZ_laplace)))",
    "nested": "logZ ベース事後確率 (softmax(-(-logZ)))",
}


@dataclass(frozen=True)
class CalibrationSample:
    """較正ベンチの 1 サンプル (予測確率 + 真偽ラベル + 由来 backend)。🔵 REQ-017/106

    backend フィールドで bic / nested の系列分離を行う (REQ-016/106/EDGE-012)。
    """

    predicted_probability: float  # 【予測確率 p∈[0,1]】 🔵 REQ-017
    correct: bool  # 【真偽 (正解ラベル)】 🔵 REQ-017
    backend: str = "bic"  # 【確率を出した evidence backend (系列分離キー)】 🔵 REQ-016/106


@dataclass(frozen=True)
class ReliabilityBin:
    """reliability diagram の 1 ビン。🔵 REQ-016/017"""

    lower: float  # 【ビン下端 (確率)】 🔵
    upper: float  # 【ビン上端 (確率)】 🔵
    mean_predicted: float  # 【ビン内平均予測確率】 🔵
    observed_frequency: float  # 【ビン内観測正解率】 🔵
    count: int  # 【ビン内サンプル数】 🔵


@dataclass(frozen=True)
class CalibrationReport:
    """1 backend 系列の較正評価 (reliability 曲線 + ECE)。🔵 REQ-016/017/NFR-004

    backend 名と確率の意味 (BIC 近似 vs logZ) をレポートに明記する (REQ-015/NFR-004)。
    """

    backend: str  # 【評価対象 backend (bic / nested)】 🔵 REQ-015/106
    bins: tuple[ReliabilityBin, ...]  # 【ビン分割済み reliability 曲線 (下端昇順)】 🔵 REQ-017/402
    ece: float  # 【Expected Calibration Error スカラ】 🔵 REQ-016
    n_samples: int  # 【評価サンプル数】 🔵
    probability_semantics: str = ""  # 【確率の意味の説明文 (BIC 近似 / logZ)】 🔵 REQ-015/NFR-004


def _bin_index(probability: float, n_bins: int) -> int:
    """予測確率 p のビン割当 (floor(p*n_bins)、p=1.0 は最終ビンへ clamp)。🔵 REQ-017"""
    idx = int(probability * n_bins)
    if idx >= n_bins:  # p=1.0 (以上) は最終ビンに含める
        idx = n_bins - 1
    if idx < 0:  # 数値誤差・範囲外の防御 (負値は先頭ビンへ)
        idx = 0
    return idx


def reliability_diagram(
    samples: Sequence[CalibrationSample], *, n_bins: int = 10
) -> tuple[ReliabilityBin, ...]:
    """予測確率を等幅ビンに分割し reliability 曲線を決定論的に構成する。🔵 REQ-016/017/EDGE-012

    【ビン割当】: [0,1] を n_bins 等分し floor(p*n_bins) で割り当てる。p=1.0 は最終ビンに含める。
    【決定論】: ビンは下端昇順で返す。空ビンは count=0 で保持し (mean_predicted/observed_frequency
      は定義値 0.0)、ビン順を固定する (REQ-402/NFR-102)。
    """
    width = 1.0 / n_bins
    sums = [0.0] * n_bins  # ビン内予測確率の総和
    corrects = [0] * n_bins  # ビン内正解数
    counts = [0] * n_bins  # ビン内サンプル数
    for s in samples:
        idx = _bin_index(s.predicted_probability, n_bins)
        sums[idx] += s.predicted_probability
        counts[idx] += 1
        if s.correct:
            corrects[idx] += 1

    bins: list[ReliabilityBin] = []
    for i in range(n_bins):
        count = counts[i]
        if count > 0:
            mean_predicted = sums[i] / count
            observed_frequency = corrects[i] / count
        else:  # 空ビンは定義値で保持 (決定論・ビン順固定, REQ-017/402)
            mean_predicted = 0.0
            observed_frequency = 0.0
        bins.append(
            ReliabilityBin(
                lower=i * width,
                upper=(i + 1) * width,
                mean_predicted=mean_predicted,
                observed_frequency=observed_frequency,
                count=count,
            )
        )
    return tuple(bins)


def expected_calibration_error(
    samples: Sequence[CalibrationSample], *, n_bins: int = 10
) -> float:
    """ECE = Σ (count_b / N) · |observed_freq_b − mean_predicted_b| を決定論的に計算する。🔵 REQ-016/017

    空サンプルは 0.0 を返す。ビンは reliability_diagram と同一分割を用いる。
    """
    n = len(samples)
    if n == 0:
        return 0.0
    bins = reliability_diagram(samples, n_bins=n_bins)
    ece = 0.0
    for b in bins:
        if b.count == 0:
            continue
        ece += (b.count / n) * abs(b.observed_frequency - b.mean_predicted)
    return ece


def calibrate_by_backend(
    samples: Sequence[CalibrationSample], *, n_bins: int = 10
) -> tuple[CalibrationReport, ...]:
    """samples を backend 別に分離し bic / nested を別系列で較正評価する。🔵 REQ-016/106/EDGE-012

    【系列分離】: samples を backend でグルーピングし各系列に CalibrationReport を生成する。返す tuple は
      backend 名昇順で決定論化する (REQ-402)。nested 系列があれば別 report として分離出力する (EDGE-012)。
    【確率の意味 (REQ-015/NFR-004)】: probability_semantics に backend に応じた説明文 (bic→BIC 近似事後
      確率、nested→logZ ベース事後確率 等) を格納する。
    """
    grouped: dict[str, list[CalibrationSample]] = {}
    for s in samples:
        grouped.setdefault(s.backend, []).append(s)

    reports: list[CalibrationReport] = []
    for backend in sorted(grouped):  # backend 名昇順で決定論化 (REQ-402)
        series = grouped[backend]
        reports.append(
            CalibrationReport(
                backend=backend,
                bins=reliability_diagram(series, n_bins=n_bins),
                ece=expected_calibration_error(series, n_bins=n_bins),
                n_samples=len(series),
                probability_semantics=_PROBABILITY_SEMANTICS.get(backend, ""),
            )
        )
    return tuple(reports)
