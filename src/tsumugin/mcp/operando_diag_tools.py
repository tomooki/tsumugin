"""薄い MCP 4 ツール (operando 診断 ②) — ① 決定論アドバイザの計器 (Issue architecture §2)。

閉ループ丸ごとは出さない。③ (`skills/operando-diagnose`) が以下を反復駆動して系列結果を疑う
(architecture.md §0/§2, 二重反転回避): **判断しない・返すだけ**。

- ``assess_data_quality``: 観測ファイル (+esd) → 背景減算検出 + 2θ 上限提案 (計器)。
- ``residual_report``: (x, yobs, ycalc[, weight]) → baseline/peak 分解 + 上位未説明特徴 (計器)。
- ``check_phase_set``: 系列結果 (JSON) → 相集合完全性 + 相ごとの非単調性フラグ + **分率が動かなかった
  フレームの 2 指紋** (``seed_pinned``= 等分 seed に厳密一致 = warm-start が効いていない /
  ``fractions_frozen``= 直前フレームの値に厳密一致 = warm-start 下で分率精密化が死んでいる)。
  いずれも Rwp では検出不能 (Issue #96) (計器)。
- ``repair_frames``: 系列結果 + frames + phases → 不連続検出 (or ``target_frames`` で明示指定) +
  近傍 warm-start 修復 (Rwp 改善時のみ
  採用の自己検証可能な規則なので①/②に置ける安全部分集合)。改善しなかったものは
  ``needs_model_revision`` として③へ上げる。入力の整合性 (フレーム数一致・相集合の完全性) は
  **精密化前に**検証し、破れていれば error dict を返す (相を黙って落とした fit を「修復成功」と
  報告しない = J5 の失敗様態を隠さない)。試行記録は ``ledger_entries`` で返す (P2 非破壊)。

**SDK 非依存**: 素の型 dict のみを返す (json.dumps allow_nan=False 安全, 浮動小数は
``finite_or_none``)。GSAS は ``repair_frames`` の既定 runner でのみ遅延 import。runner は注入可能
(テストは決定論スタブ)。エラーは既存ツール群 (``mem_tools``/``tools.identify_phases``) と同型の
``{"error", "error_type"}`` (or ``{"error": ...}``) dict へ縮退し、例外を送出しない。

信頼性: 🔵 docs/design/operando-diagnosis/architecture.md §2 の ② 4 ツール表と 1:1。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Mapping, Sequence

import numpy as np

from .._json import finite_or_none
from ..autorietveld import PhaseSpec
from ..insitu.model import FrameSpec
from .insitu_tools import (
    _parse_two_theta_limits,
    _result_from_dict,
    _runner_from_instrument,
    _validate_seq_result,
)

if TYPE_CHECKING:
    from ..autorietveld.residual_report import ResidualReport
    from ..store.ledger import LedgerEntry

__all__ = [
    "OPERANDO_DIAG_TOOLS",
    "assess_data_quality",
    "check_phase_set",
    "repair_frames",
    "residual_report",
    "residual_report_to_dict",
]


def residual_report_to_dict(rep: "ResidualReport") -> dict[str, object]:
    """``ResidualReport`` を素の型 dict へ (json.dumps allow_nan=False 安全)。

    **単一情報源**: 本ツールの ``residual_report`` と ``rietveld_tools._result_to_dict``
    (``auto_rietveld`` の出力に同梱する経路) の双方がこれを使い、③ から見た残差レポートの
    形が経路によらず一致することを保証する。
    """
    return {
        "rwp": finite_or_none(rep.rwp),
        "peak_only_rwp": finite_or_none(rep.peak_only_rwp),
        "baseline_numerator_fraction": finite_or_none(rep.baseline_numerator_fraction),
        "peak_numerator_fraction": finite_or_none(rep.peak_numerator_fraction),
        "angular_rwp": [
            [finite_or_none(lo), finite_or_none(hi), finite_or_none(v)]
            for lo, hi, v in rep.angular_rwp
        ],
        "top_features": [
            {
                "two_theta": finite_or_none(f.two_theta),
                "residual": finite_or_none(f.residual),
                "obs": finite_or_none(f.obs),
            }
            for f in rep.top_features
        ],
    }


def _ledger_entry_to_dict(entry: "LedgerEntry") -> dict[str, object]:
    """``LedgerEntry`` を素の型 dict へ平坦化 (json.dumps allow_nan=False 安全)。

    ``repair_isolated`` が追記する ``insitu_repair_adopted`` / ``_rejected`` / ``_no_neighbour``
    の payload はスカラ (frame/rwp*/source) と文字列列 (reasons) のみ。float は非有限を None へ
    落とす (`finite_or_none`) ことで allow_nan=False を担保する。
    """
    out: dict[str, object] = {"index": entry.index, "kind": entry.kind}
    for key, value in entry.payload.items():
        if isinstance(value, float):
            out[key] = finite_or_none(value)
        elif isinstance(value, (list, tuple)):
            out[key] = [str(v) for v in value]
        else:
            out[key] = value
    return out


def _parse_excluded_regions(
    excluded_regions: Sequence[Sequence[float]] | None,
) -> tuple[tuple[float, float], ...] | None:
    """``excluded_regions`` を検証して ``((lo, hi), ...)`` へ正規化する。

    呼び出し側は LLM が組んだ JSON なので、3 要素の区間・スカラ・逆順 (lo >= hi) といった
    取り違えが起きやすい。素朴に ``for lo, hi in ...`` と展開すると ValueError が MCP 境界を
    貫くため、問題の区間を名指しする ``ValueError`` に正規化して呼び出し側の try で捕らえさせる。

    :raises ValueError: 区間が 2 要素の数値ペアでない、または ``lo >= hi`` のとき
    """
    if not excluded_regions:
        return None
    out: list[tuple[float, float]] = []
    for i, region in enumerate(excluded_regions):
        if isinstance(region, (str, bytes)):
            raise ValueError(
                f"excluded_regions[{i}] が区間になっていません: {region!r} "
                "([lo, hi] の 2 要素数値ペアの列で渡してください)"
            )
        try:
            values = list(region)
        except TypeError as exc:  # スカラ (非反復) を区間として渡した
            raise ValueError(
                f"excluded_regions[{i}] が区間になっていません: {region!r} "
                "([lo, hi] の 2 要素数値ペアの列で渡してください)"
            ) from exc
        if len(values) != 2:
            raise ValueError(
                f"excluded_regions[{i}] は 2 要素 [lo, hi] である必要があります: "
                f"{region!r} (実際 {len(values)} 要素)"
            )
        try:
            lo, hi = float(values[0]), float(values[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"excluded_regions[{i}] の要素が数値ではありません: {region!r}"
            ) from exc
        if not (lo < hi):
            raise ValueError(
                f"excluded_regions[{i}] は lo < hi である必要があります: {region!r}"
            )
        out.append((lo, hi))
    return tuple(out)


def _load_pattern_with_esd(
    path: str, data_format: str | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """観測ファイルを (two_theta, intensity, esd|None) へ読む。

    ``reference.io`` の各ローダーは esd (3 列目) を破棄する (``XYE`` も ``load_xy`` へ写像され
    3 列目が捨てられる) ため、**3 列 ascii の ``XY``/``XYE`` は numpy で直接読み esd を保持する**。
    ``XYE`` は esd を実際に持つ唯一の形式であり、J1 (背景減算済みデータの esd=√I 過大重み) の
    主要な証拠がまさに esd ケースなので、ここで落としてはならない。

    他形式 (XRDML/FXYE/GSAS 等) は ``reference.io.load_pattern`` に委譲し esd は None
    (未対応形式では esd を判別的に使わない; ``detect_background_subtracted`` も esd を
    補助情報としてのみ使う設計と整合)。
    """
    fmt = (data_format or "XY").upper()
    if fmt in {"XY", "XYE"}:
        # 【ndmin=2】: 1 次元結果を reshape(1, -1) すると **1 行ファイルと 1 列ファイルを区別できず**、
        #   強度だけの 1 列ファイル (N,) が (1, N) の「1 点パターン」に化けて 2 列ガードをすり抜ける。
        #   ndmin=2 は元の行/列構造を保つ (1 列 N 行 → (N, 1) / 1 行 3 列 → (1, 3)) ので両者を弁別できる。
        arr = np.loadtxt(path, comments="#", ndmin=2)
        if arr.shape[1] < 2:
            raise ValueError(f"{fmt} データは2列以上必要です: {path!r} (実際 {arr.shape[1]} 列)")
        x = arr[:, 0].astype(float)
        y = arr[:, 1].astype(float)
        esd = arr[:, 2].astype(float) if arr.shape[1] >= 3 else None
        return x, y, esd

    from ..reference.io import load_pattern

    x, y = load_pattern(path, fmt)
    return x, y, None


def assess_data_quality(
    path: str,
    *,
    data_format: str | None = None,
    excluded_regions: Sequence[Sequence[float]] | None = None,
    reason: str = "",
) -> dict:
    """観測ファイルの背景減算検出 + 2θ 上限提案を返す (計器・① ``dataquality`` へ委譲)。

    J1 (データ品質を精密化前に問う) の入力。``is_subtracted=True`` は「生データがあれば使うべき」
    という助言のみで、ここでは何も変更しない (提案≠適用)。

    :param path: 観測データファイルパス
    :param data_format: 形式名の**語彙**は ``reference.io.load_pattern`` /
        ``FrameSpec.data_format`` と共通 ("XY"/"XYE"/"XRDML"/"FXYE"/"GSAS"/"INT"/"IGOR")。
        **既定値は共通でない**: ``FrameSpec.data_format`` の既定は "XRDML" だが、本ツールは
        単発のファイル診断であり、None は "XY" (プレーン ascii) 扱いとする。
        3 列 ascii の "XY"/"XYE" のみ esd (3 列目) を保持する (他形式は esd を破棄)
    :param excluded_regions: 寄生ピーク等を 2θ 上限提案から除外する区間 ``[lo, hi]`` の列
        (渡さないと寄生ピークまで信号終端として拾われる, architecture.md §3 手順1 の注意)。
        各区間は ``lo < hi`` の 2 要素数値ペアであること (破れば error dict)
    :returns: ``is_subtracted``/``confidence``/``reasons``/``recommendation``/``baseline_level``/
        ``peak_max``/``suggested_two_theta_limit``。読み込み失敗・``excluded_regions`` 不正は
        ``{"error", "error_type"}``
    """
    from ..autorietveld.dataquality import detect_background_subtracted, suggest_two_theta_limit

    # 【入力検証を try 内へ】: 区間の展開 (旧 `for lo, hi in ...`) は try の外にあり、3 要素区間や
    #   スカラで ValueError が MCP 境界を貫いていた (module docstring の「例外を送出しない」違反)。
    try:
        regions = _parse_excluded_regions(excluded_regions)
        x, y, esd = _load_pattern_with_esd(path, data_format)
    except (OSError, ValueError, TypeError, IndexError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    report = detect_background_subtracted(x, y, esd)
    limit = suggest_two_theta_limit(x, y, excluded_regions=regions)

    return {
        "is_subtracted": bool(report.is_subtracted),
        "confidence": finite_or_none(report.confidence),
        "reasons": list(report.reasons),
        "recommendation": report.recommendation,
        "baseline_level": finite_or_none(report.baseline_level),
        "peak_max": finite_or_none(report.peak_max),
        "suggested_two_theta_limit": finite_or_none(limit),
        "reason": reason,
    }


def residual_report(
    x: Sequence[float],
    yobs: Sequence[float],
    ycalc: Sequence[float],
    weight: Sequence[float] | None = None,
    *,
    baseline_cut: float | None = None,
    baseline_k: float = 3.0,
    n_bins: int = 5,
    n_features: int = 6,
    feature_min_separation: float = 0.15,
    reason: str = "",
) -> dict:
    """残差 (obs-calc) を baseline/peak 寄与・角度ビン・上位特徴に分解する (計器・① へ委譲)。

    **本ツールは ③ の主経路ではない**。実データの残差配列は 2392 点 × 3 本 ≈ 150KB あり、
    **配列を MCP 境界に跨がせてはならない**。レポート自体は小さい (数個の float + ~6 特徴) ため、
    サーバ側で算出して返すのが正しい: ``auto_rietveld`` の出力に ``residual_report`` キーとして
    同梱してある (``rietveld_tools._result_to_dict`` → ``residual_report_from_result``)。
    ③ (MCP しか触れない skill) は通常そちらを読む。

    本ツールは**既に配列を手元に持つ呼び出し側**のための明示入力経路として残す (算出元を問わない)。

    :param x: 2θ (または TOF) 配列
    :param yobs: 観測強度
    :param ycalc: 計算強度
    :param weight: Rwp の重み。None なら計数統計慣習 ``w=1/max(yobs,1)`` を自動導出
    :returns: ``rwp``/``peak_only_rwp``/``baseline_numerator_fraction``/``peak_numerator_fraction``/
        ``angular_rwp``/``top_features``。失敗 (長さ不一致・空配列・型不正等) は
        ``{"error", "error_type"}``
    """
    from ..autorietveld.residual_report import residual_report as _residual_report

    try:
        # 空配列は「完璧なフィット」(rwp=0.0) を返してしまう。J5 の garbage→"clean" と同型の
        # 最悪の失敗形 (③ が疑うのをやめる) なのでエラー化する。
        if len(x) == 0 or len(yobs) == 0 or len(ycalc) == 0:
            raise ValueError(
                "残差配列が空です。空配列は rwp=0.0 (完璧なフィット) を意味しないため"
                "打ち切ります。x/yobs/ycalc に実際の残差を渡してください。"
            )
        rep = _residual_report(
            x,
            yobs,
            ycalc,
            weight,
            baseline_cut=baseline_cut,
            baseline_k=baseline_k,
            n_bins=n_bins,
            n_features=n_features,
            feature_min_separation=feature_min_separation,
        )
    except (KeyError, ValueError, TypeError, AttributeError, IndexError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    out = residual_report_to_dict(rep)
    out["reason"] = reason
    return out


def check_phase_set(
    result: Mapping[str, object],
    *,
    min_amplitude: float = 0.1,
    max_turning_points: int = 2,
    reason: str = "",
) -> dict:
    """相集合の完全性 + 相ごとの分率非単調性を返す (計器・① ``insitu.phaseset`` へ委譲)。

    J5/J7 (計量の近い相が互いの強度を肩代わりし、Rwp が良好なまま非物理な描像を生む) の検出器。
    ``sequential_rietveld`` が返す系列結果 dict をそのまま渡せる
    (``insitu_tools._result_from_dict`` と往復可能)。

    **``repair_frames`` の戻り値は渡せない** — あれは系列結果ではなく修復レポート
    (``repairs``/``needs_model_revision``) であり ``frames`` キーを持たない (architecture.md §2)。

    **分率が動かなかったフレームの 2 つの指紋 (Issue #96)**: どちらも **Rwp は平凡なまま**
    (実測 8.4-8.5%) で ``is_complete`` にも非単調性フラグにも出ない (**張り付きは「平坦」であって
    振動ではない**)。両者は同じ欠陥が warm-start の有無で残す別の痕跡であり、**両方を見る**こと。

    - ``seed_pinned`` / ``seed_pinned_frames``: 分率が等分 seed (1/相数) に**厳密に**一致。
      = **分率ウォームスタートが効いていない** canary。
    - ``fractions_frozen`` / ``frozen_fraction_frames``: 分率が**直前フレームの値**と**厳密に**一致。
      = ウォームスタート下で**そのフレームの分率精密化が死んでいる**。種が 1/n ではないため
      上の seed 検査には**出ない**。

    いずれも ``[].frame`` を集めて ``repair_frames`` の ``target_frames`` へ渡すのが修復経路
    (**疑わしいフレームは 1 回の呼び出しで全て渡すこと** — 1 つずつ呼ぶと、両隣も同欠陥の区間で
    欠陥を持つ隣から warm-start してしまう)。張り付きは「平坦」なので ``target_frames`` 無しの
    自動検出では**原理的に到達できない**。

    **本ツールの判定は全て Scale 基準** (``fraction_basis="scale"`` を必ず返す。レビュー第4巡 HIGH)。
    重量分率基準の版は**無い** — 意図的である:

    - **J7 (肩代わり) の病理は Scale に現れる**: 「計量の近い相が互いの**強度**を吸収し合う」の
      であり、ある相へ割り付けられた散乱寄与 = Scale が振動する。wt% は Scale × 単位胞質量の
      **派生量**であって、検出したい現象そのものではない。
    - **``seed_pinned``/``fractions_frozen`` は Scale でしか定義できない**: 指紋は「等分 seed
      (1/相数) との**厳密一致**」「直前フレーム値との**厳密一致**」である。wt% へ換算すると
      1/n との一致が壊れ、**検出器そのものが成立しない**。
    - wt% は共分散の無い精密化では**そもそも空**であり、判定不能な系列が大量に出る。

    ⚠ **``min_amplitude`` は Scale 単位の絶対閾値であり、等価な wt% 感度は相の単位胞質量と
    分率レベルで変わる**。Scale→wt% は単調写像なので turning point の**位置**は basis で動かないが、
    **振幅フィルタの通過可否は動く**。重い相が低 Scale 域にあるとき wt% 側の振幅は最大で
    質量比倍に拡大する (実測 K₂Mn[Fe(CN)₆] cubic 1103.4 / tetra 517.8 amu = 2.13 倍の質量比:
    cubic Scale 0.02↔0.11 の振幅 0.09 は wt% では 0.042↔0.209 = 振幅 0.167)。よって
    **``flagged=False`` は「Scale 振幅が閾値未満」の意味であって「相量が動いていない」ではない**。
    判定の根拠を ③ が自分で見直せるよう、``phases[].fractions`` に**判定した系列そのもの**を返す
    (境界を跨ぐのはフレーム数個の float であり配列問題にはならない)。少数相・重い相の微小振動を
    疑うときは ``min_amplitude`` を下げて再実行すること。

    :param result: ``sequential_rietveld`` 等が返す系列結果 (JSON dict)
    :param min_amplitude: ``flag_nonmonotonic_fraction`` の振幅フィルタ (既定 0.1)。
        **Scale 単位** (上記の basis 注意を参照)
    :param max_turning_points: 同上の turning point 上限 (既定 2; 単一ドームまでは正常)
    :returns: ``fraction_basis`` (常に ``"scale"``)/``is_complete``/``union``/
        ``frames_with_missing``/``recommendation``/``phases``
        (和集合の全相について ``{phase, turning_points, flagged, fractions, reason}`` —
        ``fractions`` は**実際に判定した Scale 系列**)/``seed_pinned``/
        ``seed_pinned_frames`` (``{frame, axis_value, rwp, n_phases, seed_value, phase_fractions}``)/
        ``seed_pinning_recommendation``/``fractions_frozen``/``frozen_fraction_frames``
        (``{frame, previous_frame, axis_value, rwp, n_phases, phase_fractions}``)/
        ``frozen_fraction_recommendation``。**``phase_fractions``/``fractions`` は全て Scale** —
        出版値ではない (flag されたフレームは定義上壊れており報告対象でもない)。
        系列結果が空/不正 (``frames`` 無し・空・必須キー欠落) または復元失敗のときは
        ``{"error", "error_type"}`` (``repair_frames`` と同じ縮退契約)。
        **「相集合は完全」という判定はこの場合返らない** (``_validate_seq_result`` 参照)
    """
    from ..insitu.phaseset import (
        flag_frozen_fraction_frames,
        flag_nonmonotonic_fraction,
        flag_seed_pinned_frames,
        suggest_phase_set_completion,
    )

    # 【縮退契約の統一】: 本モジュールの 4 ツールは例外を送出せず error dict へ縮退する
    #   (module docstring)。`_result_from_dict` は壊れた系列結果で KeyError/ValueError/TypeError を
    #   投げるため、`repair_frames` と同じ形で捕らえる。
    # 【前段の入力検証】: ただし `_result_from_dict` は **投げない壊れ方** (frames キー無し → 空系列)
    #   があり、それが素通りすると「相集合は完全」という最悪の誤答になる。先に形を検証する。
    try:
        _validate_seq_result(result)
        seq = _result_from_dict(result)
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    completion = suggest_phase_set_completion(seq)

    phases = []
    for phase_name in completion.union:
        rep = flag_nonmonotonic_fraction(
            seq, phase_name, min_amplitude=min_amplitude, max_turning_points=max_turning_points
        )
        phases.append(
            {
                "phase": rep.phase_name,
                "turning_points": rep.turning_points,
                "flagged": bool(rep.flagged),
                # 【判定した系列を返す (レビュー第4巡 HIGH)】: `flagged` は Scale 単位の絶対振幅
                #   閾値を通ったかであり、「相量が動いていない」ではない。① の `NonMonotonicReport`
                #   は判定に使った系列を持っているのに ② が捨てていたため、③ は boolean を信じる
                #   以外に無く、閾値際 (実測: Scale 振幅 0.09 < 0.1 は wt% では 0.167) の
                #   偽陰性を**自分で見直す材料が無かった** (① にあっても ② に無ければ「無い」)。
                "fractions": [finite_or_none(v) for v in rep.fractions],
                "reason": rep.reason,
            }
        )

    # 【seed 張り付き (Issue #96)】: 相分率が seed から一度も動いていないフレーム。Rwp/is_complete/
    #   非単調性のどれにも出ないため、この検出器が無いと ③ は張り付いた分率を正常値として読む。
    pinning = flag_seed_pinned_frames(seq)
    # 【分率凍結 (Issue #96 レビュー)】: 分率 warm-start 下では死んだ分率精密化が **1/n ではなく
    #   直前フレームの値** に張り付き、上の seed 検査の視野の外に出る。同じ欠陥の別の指紋。
    frozen = flag_frozen_fraction_frames(seq)

    return {
        # 【basis の明示 (レビュー第4巡 HIGH)】: 本ツールが返す分率も、判定に使った振幅閾値も
        #   **全て Scale 基準**である。ラベルが無ければ ③ は wt% の話だと読みうる (`parametric_fit`
        #   は `fraction_basis` を返すので、返さないツールは「basis 非依存」と誤読される)。
        #   Scale が正しい basis である理由と、閾値の basis 依存性は docstring 参照。
        "fraction_basis": "scale",
        "is_complete": bool(completion.is_complete),
        "union": list(completion.union),
        "frames_with_missing": [
            [frame_index, list(missing)] for frame_index, missing in completion.frames_with_missing
        ],
        "recommendation": completion.recommendation,
        "phases": phases,
        "seed_pinned": bool(pinning.flagged),
        "seed_pinned_frames": [
            {
                "frame": f.frame_index,
                "axis_value": finite_or_none(f.axis_value) if f.axis_value is not None else None,
                "rwp": finite_or_none(f.rwp),
                "n_phases": f.n_phases,
                "seed_value": finite_or_none(f.seed_value),
                "phase_fractions": {k: finite_or_none(v) for k, v in f.phase_fractions.items()},
            }
            for f in pinning.frames
        ],
        "seed_pinning_recommendation": pinning.recommendation,
        "fractions_frozen": bool(frozen.flagged),
        "frozen_fraction_frames": [
            {
                "frame": f.frame_index,
                "previous_frame": f.previous_frame_index,
                "axis_value": finite_or_none(f.axis_value) if f.axis_value is not None else None,
                "rwp": finite_or_none(f.rwp),
                "n_phases": f.n_phases,
                "phase_fractions": {k: finite_or_none(v) for k, v in f.phase_fractions.items()},
            }
            for f in frozen.frames
        ],
        "frozen_fraction_recommendation": frozen.recommendation,
        "reason": reason,
    }


def repair_frames(
    result: Mapping[str, object],
    frames: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    *,
    rwp_abs: float | None = None,
    rwp_delta: float = 1.8,
    frac_delta: float = 0.15,
    rwp_tol: float = 0.1,
    min_block: int = 2,
    target_frames: Sequence[int] | None = None,
    two_theta_limits: Sequence[float] | None = None,
    instrument: Mapping[str, object] | None = None,
    runner: Callable | None = None,
    reason: str = "",
) -> dict:
    """不連続フレームを検出 (or 明示指定) し近傍 warm-start で修復する (① ``insitu.repair`` へ委譲)。

    ``repairs`` は Rwp が ``rwp_tol`` 超改善した場合のみ採用 (自己検証可能な規則なので①/②に
    置ける安全部分集合)。改善しなかった/試せなかったフレームは ``needs_model_revision`` として
    ③ (モデル改訂の判断) へ上げる。

    **自動検出は Scale 基準** (``fraction_basis="scale"`` を必ず返す。レビュー第4巡 HIGH)。
    ``detect_discontinuities`` の 3 基準は ``rwp_abs`` / ``rwp_local_median`` /
    ``fraction_deviation`` であり、**3 つ目は ``phase_fractions`` (Scale) から発火する**
    (**格子を見る基準は無い**)。Scale が正しい basis である理由:

    - 検出したいのは「そのフレームの**精密化**が近傍と食い違う (局所解にトラップされた)」こと
      であり、Scale は GSAS が実際に動かす**精密化パラメータそのもの**である。
    - 修復側 (``repair.repair_isolated``) は近傍の **Scale** を warm-start の種として GSAS へ
      戻す (``_warmstart.seed_fractions``)。検出器と作動器が**同じ座標で喋る**必要がある。
    - wt% は共分散の無い精密化では**そもそも空**であり、wt% 基準の検出器は大量の系列で
      定義できない。Scale は常に在る。

    ⚠ **``frac_delta`` は Scale 単位の絶対閾値**であり、**選ばれるフレーム集合は basis 依存**
    である (実測: Scale ``[0.10, 0.12, 0.45, 0.16, 0.18]`` は 3 フレームを、同じ系列の wt% は
    1 フレームを選ぶ)。再精密化されたフレーム集合は ledger に残る状態変化なので、この閾値を
    動かしたときは**何を直したか**を報告に含めること。少数相・重い相の微小なズレを拾いたい
    ときは ``frac_delta`` を下げる (基準名は ``discontinuities[].reasons`` に出る)。

    :param result: ``sequential_rietveld`` 等が返す系列結果 (JSON dict)
    :param frames: ``result["frames"]`` と同順・同数の ``FrameSpec.to_dict()`` 列。**数が違えば
        精密化せず error dict を返す** (``repair_isolated`` は ``frames[i]`` を位置で引くため)
    :param phases: 系列で使われている全相の ``PhaseSpec.to_dict()`` 列 (相名で引く辞書のソース)。
        **系列に現れる相を 1 つでも欠くと精密化せず error dict を返す** (下記 相集合ガード)
    :param rwp_abs: Rwp 絶対閾値 (None なら無効)。``rwp_abs`` 基準で発火する
    :param rwp_delta: Rwp の局所中央値 (幅3) からの許容超過幅 (%ポイント)。
        ``rwp_local_median`` 基準で発火する
    :param frac_delta: 相分率が両隣 2 フレームの平均から乖離したとみなす許容差。**Scale 単位の
        絶対値**であり、これが ``fraction_deviation`` 基準 = **本ツール唯一の分率由来の検出器**
        (上記 basis 注意)。``target_frames`` 指定時は使わない
    :param rwp_tol: 修復を採用するのに要する最小 Rwp 改善幅 (%ポイント)
    :param min_block: ``systematic_hint`` (参考情報) の run 判定の最小連続長。修復可否には影響しない
    :param target_frames: **修復するフレーム番号を明示指定する** (指定時は ``rwp_abs``/``rwp_delta``/
        ``frac_delta`` による自動検出を行わない)。``check_phase_set`` の
        ``seed_pinned_frames[].frame`` / ``frozen_fraction_frames[].frame`` をそのまま渡す経路
        (§4.5 到達可能性: 各引数が「どの ② ツールの出力から来るか」を言えること)。

        **なぜ必要か**: 自動検出は Rwp/相分率の**ジャンプ**でしか発火しないが、**分率の張り付き
        /凍結は定義上「平坦」**であり、Rwp も平凡 (実測 8.4-8.5%) なので**どの閾値を選んでも
        到達できない** (``rwp_delta`` は張り付き区間の内側で局所中央値が当該フレームの Rwp
        そのものになるため届かず、``frac_delta`` は逆に**健全な**近傍を拾う)。指定なしでは
        ``discontinuities=[]``/``repairs=[]` = 「直すものは無い」を、③ が直前に「信用するな」と
        告げられたフレームに対して返してしまう。

        **1 回の呼び出しで疑わしいフレームを全て渡すこと**: 指定したフレームは互いに warm-start
        元から除外される (``repair._nearest_good``)。1 フレームずつ呼ぶと、両隣も同欠陥の区間
        (実測 125-130 の 6 連続) で**欠陥を持つ隣から種を貰い**、欠陥を引き継いだまま「修復成功」
        になる。空リストは error (「異常なし」と誤読させないため; 自動検出は None で指定なし)
    :param two_theta_limits: 修復試行の精密化レンジ ``[lo, hi]``。**系列を精密化したのと同じレンジを
        渡すこと**: 採用規則 ``rwp_after < rwp_before - rwp_tol`` は系列側の Rwp と比較するため、
        レンジが違うと**別のデータ域どうしの Rwp を比べる**ことになり採否の判断が無効になる
        (実測: 2θ≤18° で回した系列を全域で修復試行すると比較が成立しない)。``instrument`` 指定時は
        その runner へ、未指定時は既定 runner の ``SequentialConfig`` へ渡す (どちらの経路でも効く)
    :param instrument: **JSON クライアント (③) の実運用経路** (Issue #93)。指定かつ ``runner`` 未指定
        ならこの spec からサーバ側で ``make_gsas_runner`` を組み立てる。キー/既定は
        ``sequential_rietveld`` の同名引数と**完全に同一** (同じ ``_runner_from_instrument`` を
        共有する): ``path``/``paths``/``radiation``/``geometry``/``background_coeffs``/``max_cyc``/
        ``auto_freeze_minor_cells`` (float 閾値; bool は拒否)。指定なし (None) は従来通り
        実験室 X 線 Bragg-Brentano・背景 6 項・data_path 隣接 ``.instprm`` 規約の既定 runner
        — **放射光データはこの spec 無しでは修復できない**
    :param runner: **注入/テスト用**の Python callable
        ``(frame, phases, initial_cells) -> AutoRietveldResult``。JSON 境界越しには渡せない。
        明示指定時は ``instrument`` より優先する (``sequential_rietveld`` と同じ優先順)
    :returns: ``fraction_basis`` (常に ``"scale"`` = **検出**に使った基準)/``repairs``/
        ``needs_model_revision``/``systematic_hint``/``discontinuities``/
        ``ledger_entries``。``repairs[]`` は ``{frame, rwp_before, rwp_after, source,
        phase_fractions, phase_weight_fractions, phase_weight_fraction_esd, cell_esd}`` —
        ⚠ ``phase_fractions`` は **Scale** であって wt% ではない。**修復後の出版値は
        ``phase_weight_fractions`` ± ``phase_weight_fraction_esd``**。
        (``fraction_basis`` は検出基準のラベルであって ``repairs[]`` の出版値に掛かるものではない:
        出版値は ``phase_weight_fractions`` という**キー名で**基準が判る。)
        出版値の 3 キーは常に存在し、値が得られなかった精密化では空 dict (esd=0 ではない)。
        失敗 (系列結果が空/不正・フレーム数不一致・相集合の欠落・spec 復元
        失敗・instrument spec 不正・レンジ不正・``target_frames`` が空/範囲外/非整数) は
        ``{"error", "error_type"}``
        (この場合 ``repairs`` 等のキーは返らない = 「不連続なし」と誤読されない)
    """
    from ..insitu.engine import _default_gsas_runner
    from ..insitu.model import SequentialConfig
    from ..insitu.repair import (
        detect_discontinuities,
        discontinuities_from_frames,
        repair_isolated,
    )
    from ..store.ledger import Ledger

    # 【前段の入力検証】: 空/壊れた系列結果は `_result_from_dict` を素通りして空の系列になり、
    #   フレーム数ガード (0 == 0) すら通り抜けて `repairs=[]`/`needs_model_revision=[]` の
    #   「異常なし」を返していた (check_phase_set と同じ失敗様態)。判定の前に形を検証する。
    try:
        _validate_seq_result(result)
        seq = _result_from_dict(result)
        frame_specs = [FrameSpec.from_dict(f) for f in frames]
        phase_specs = [PhaseSpec.from_dict(p) for p in phases]
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    # 【フレーム数ガード】: repair_isolated は frames[i] を **位置**で引く (i は result 側の
    #   フレーム番号)。数が違うと IndexError で落ちるか、最悪の場合 **別フレームのデータで**
    #   精密化してしまう。docstring が約束する error dict を明示的に返す (捕まえた IndexError より
    #   原因が分かるメッセージを出せる)。
    if len(frame_specs) != len(seq.frames):
        return {
            "error": (
                f"frames と result のフレーム数が一致しません: frames={len(frame_specs)}, "
                f"result['frames']={len(seq.frames)}。同順・同数で渡してください。"
            ),
            "error_type": "ValueError",
        }

    # 【相集合ガード】: repair_isolated は `phases` に無い相名を **黙って捨てて** 精密化する
    #   (`if nm in name_to_spec`)。相が 1 つ落ちた状態の fit は Rwp が下がることすらあり
    #   (計量の近い相が互いの強度を肩代わりする = J5 の失敗様態)、「相の削除」が「修復成功」として
    #   報告されてしまう。系列途中で自動追加された相は `appearances` に phase_name/structure_path
    #   しか持たず、呼び出し側が `phases` に入れ忘れやすい。よって**精密化前に**完全性を検証する。
    known = {p.phase_name for p in phase_specs}
    used = set(seq.phase_names) | {nm for fr in seq.frames for nm in fr.phase_names}
    missing = sorted(used - known)
    if missing:
        return {
            "error": (
                f"系列で使われている相が phases に含まれていません: {missing}。"
                "欠けたまま精密化すると相が黙って削除され、Rwp が改善しても物理的に誤った描像に"
                "なります (相の削除が修復成功として報告される)。系列途中で自動追加された相 "
                "(result['appearances']) の PhaseSpec も含めて渡してください。"
            ),
            "error_type": "ValueError",
        }

    # 【明示ターゲット (§4.5 到達可能性)】: 張り付き/凍結は「平坦」なので自動検出には**原理的に**
    #   映らない。③ が check_phase_set の seed_pinned_frames/frozen_fraction_frames から直接
    #   フレームを指定する経路。指定時は検出閾値を一切使わない (無関係な統計で対象を上書きしない)。
    #   **runner を組む前に**検証する (対象が不正なら精密化は走らせない = GSAS を起こさない)。
    try:
        if target_frames is not None:
            discontinuities = discontinuities_from_frames(seq, target_frames)
        else:
            discontinuities = detect_discontinuities(
                seq, rwp_abs=rwp_abs, rwp_delta=rwp_delta, frac_delta=frac_delta
            )
    except (ValueError, TypeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    # 【実運用設定への到達可能性 (architecture.md §4.5 #2)】: 旧実装は `_default_gsas_runner(
    #   SequentialConfig())` 決め打ちで、③ (JSON しか送れない) からは放射源も背景項数もレンジも
    #   届かなかった。結果 (a) 2θ≤18° で回した系列を**全域**で修復試行し、採用規則が異なるデータ域の
    #   Rwp を比較する無効判定になる (b) 放射光データは修復不能。優先順は sequential_rietveld と同一:
    #   明示 runner > instrument spec > 既定 (レンジは既定 runner にも配線する)。
    try:
        limits = _parse_two_theta_limits(two_theta_limits)
        if runner is not None:
            run = runner
        elif instrument is not None:
            run = _runner_from_instrument(instrument, frame_specs, limits)
        else:
            run = _default_gsas_runner(SequentialConfig(two_theta_limits=limits))
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    # 【P2 非破壊・監査可能性】: repair_isolated は採用/棄却/近傍なしを ledger へ追記する
    #   (architecture.md §1「P2 非破壊・ledger 追記」)。実 GSAS 精密化が走る以上、その試行記録は
    #   MCP 越しにも辿れなければならない。追記専用 Ledger を用意し、素の型で返す。
    ledger = Ledger()

    report = repair_isolated(
        frame_specs,
        seq,
        phase_specs,
        run,
        discontinuities,
        rwp_tol=rwp_tol,
        min_block=min_block,
        ledger=ledger,
    )

    return {
        # 【basis の明示 (レビュー第4巡 HIGH)】: `fraction_deviation` 基準 = 本ツールの**検出**は
        #   Scale から発火する (格子基準は存在しない)。`frac_delta` は Scale 単位の絶対閾値なので
        #   **再精密化されるフレーム集合は basis 依存**である (ledger に残る状態変化)。
        #   Scale を選ぶ理由は docstring 参照 (検出器と warm-start の作動器が同じ座標で喋る)。
        "fraction_basis": "scale",
        "ledger_entries": [_ledger_entry_to_dict(e) for e in ledger.entries],
        "repairs": [
            {
                "frame": r.frame_index,
                "rwp_before": finite_or_none(r.rwp_before),
                "rwp_after": finite_or_none(r.rwp_after),
                "source": r.source,
                "phase_fractions": {k: finite_or_none(v) for k, v in r.phase_fractions.items()},
                # 【出版値 (Issue #96 レビュー 第2巡)】: 上の `phase_fractions` は **Scale** であって
                #   重量分率ではない (実測 K2Mn[Fe(CN)6] tetra: 65.6 Scale% は同じ fit で 47.2 wt%。
                #   乖離はフレーム毎に違い [実測 1.39-1.62 倍] **換算係数は無い**)。
                #   **修復したフレームこそ出版値が要る**: ③ が `target_frames` で名指しするのは
                #   `check_phase_set` が張り付き/凍結を報告したフレームであり、張り付きは分率が
                #   動く転移域で起きやすい = 定量相分析の要求が最も高い区間である。Scale だけ返すと
                #   ③ は「wt% として誤って報告する」(skills/operando-diagnose の禁止事項) か
                #   「直したフレームの出版値が無い」の二択に追い込まれる。
                #   キーは常に存在させる (欠落と esd=0 の取り違え防止; auto_rietveld /
                #   seq_result_to_dict と同一規律) 🔵
                "phase_weight_fractions": {
                    k: finite_or_none(v) for k, v in r.phase_weight_fractions.items()
                },
                "phase_weight_fraction_esd": {
                    k: finite_or_none(v) for k, v in r.phase_weight_fraction_esd.items()
                },
                "cell_esd": {
                    k: [finite_or_none(x) for x in esd] for k, esd in r.cell_esd.items()
                },
            }
            for r in report.repairs
        ],
        "needs_model_revision": list(report.needs_model_revision),
        "systematic_hint": [list(block) for block in report.systematic_hint],
        "discontinuities": [
            {
                "frame": d.frame_index,
                "rwp": finite_or_none(d.rwp),
                "reasons": list(d.reasons),
            }
            for d in discontinuities
        ],
        "reason": reason,
    }


# 【M-later ツールレジストリ】: MCP_TOOLS へマージする 4 ツール (architecture.md §2)。
OPERANDO_DIAG_TOOLS: Mapping[str, object] = {
    "assess_data_quality": assess_data_quality,
    "residual_report": residual_report,
    "check_phase_set": check_phase_set,
    "repair_frames": repair_frames,
}
