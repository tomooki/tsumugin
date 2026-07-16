"""薄い MCP 4 ツール (operando 診断 ②) — ① 決定論アドバイザの計器 (Issue architecture §2)。

閉ループ丸ごとは出さない。③ (`skills/operando-diagnose`) が以下を反復駆動して系列結果を疑う
(architecture.md §0/§2, 二重反転回避): **判断しない・返すだけ**。

- ``assess_data_quality``: 観測ファイル (+esd) → 背景減算検出 + 2θ 上限提案 (計器)。
- ``residual_report``: (x, yobs, ycalc[, weight]) → baseline/peak 分解 + 上位未説明特徴 (計器)。
- ``check_phase_set``: 系列結果 (JSON) → 相集合完全性 + 相ごとの非単調性フラグ + **seed 張り付き**
  (相分率が等分 seed に厳密一致 = 分率精密化が動いていない; Rwp では検出不能, Issue #96) (計器)。
- ``repair_frames``: 系列結果 + frames + phases → 不連続検出 + 近傍 warm-start 修復 (Rwp 改善時のみ
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
from .insitu_tools import _parse_two_theta_limits, _result_from_dict, _runner_from_instrument

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


#: 系列結果の各フレームが**判断に足る**ために最低限持つべきキー。``seq_result_to_dict`` は常に
#: この 3 つを出す (値が None でも可)。欠けた dict は ``_result_from_dict`` が既定値
#: (rwp=inf / phase_names=()) で黙って埋めるため、**キーの有無でしか欠落を検出できない**。
_REQUIRED_FRAME_KEYS = ("frame_index", "rwp", "phase_names")


def _validate_seq_result(result: Mapping[str, object]) -> None:
    """系列結果 dict が判断に足る形かを**判定/精密化の前に**検証する。

    ``_result_from_dict`` は寛容で、``frames`` キーの無い dict を **例外にせず空の系列**へ復元する
    (``d.get("frames", [])``)。そのため ``check_phase_set({"nope": 1})`` は ``is_complete=True`` /
    ``union=[]`` の「相集合は完全」を返していた。**J5 (Rwp が盲目な相集合の誤りを捕まえる) の
    判定器がゴミ入力から無罪放免を出すのは最悪の失敗様態**である: ③ に「疑わなくてよい」と
    告げることは、本設計が防ごうとしたまさにその失敗を招く。何も判断できないときは
    ``is_complete`` を返してはならず、error dict へ縮退する。

    ``frames`` が空の系列も**エラーとする**: 判断の対象が存在しない以上「完全」とは言えず、
    黙って完全と答えるのは上と同じ不安全である (系列結果は必ず 1 フレーム以上を持つ)。

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
            "そのまま渡してください (空の系列を「相集合は完全」と判定しないため打ち切ります)。"
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
            "result['frames'] が空です。判断の対象が無い系列を「相集合は完全」とは報告できません"
            "(系列を実行できていない可能性があります — sequential_rietveld の結果を確認してください)。"
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
                "欠けたキーは既定値 (rwp=inf / phase_names=()) で黙って埋まり、相集合の判定が"
                "入力の不備を反映しない誤った結論になります。"
            )


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

    :param result: ``sequential_rietveld`` 等が返す系列結果 (JSON dict)
    **seed 張り付き (Issue #96)**: 相分率が等分 seed (1/相数) に**厳密に**一致したままのフレームを
    ``seed_pinned_frames`` で併せて返す。分率精密化がそのフレームで一度も動かなかった徴候で、
    **Rwp は平凡なまま** (実測 8.4-8.5%) なので ``is_complete`` にも非単調性フラグにも出ない
    (張り付きは「平坦」であって振動ではない)。厳密な seed 一致が唯一の指紋である。

    :param min_amplitude: ``flag_nonmonotonic_fraction`` の振幅フィルタ (既定 0.1)
    :param max_turning_points: 同上の turning point 上限 (既定 2; 単一ドームまでは正常)
    :returns: ``is_complete``/``union``/``frames_with_missing``/``recommendation``/``phases``
        (和集合の全相について ``{phase, turning_points, flagged, reason}``)/``seed_pinned``/
        ``seed_pinned_frames`` (``{frame, axis_value, rwp, n_phases, seed_value, phase_fractions}``)/
        ``seed_pinning_recommendation``。
        系列結果が空/不正 (``frames`` 無し・空・必須キー欠落) または復元失敗のときは
        ``{"error", "error_type"}`` (``repair_frames`` と同じ縮退契約)。
        **「相集合は完全」という判定はこの場合返らない** (``_validate_seq_result`` 参照)
    """
    from ..insitu.phaseset import (
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
                "reason": rep.reason,
            }
        )

    # 【seed 張り付き (Issue #96)】: 相分率が seed から一度も動いていないフレーム。Rwp/is_complete/
    #   非単調性のどれにも出ないため、この検出器が無いと ③ は張り付いた分率を正常値として読む。
    pinning = flag_seed_pinned_frames(seq)

    return {
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
    two_theta_limits: Sequence[float] | None = None,
    instrument: Mapping[str, object] | None = None,
    runner: Callable | None = None,
    reason: str = "",
) -> dict:
    """不連続フレームを検出し近傍 warm-start で修復する (① ``insitu.repair`` へ委譲)。

    ``repairs`` は Rwp が ``rwp_tol`` 超改善した場合のみ採用 (自己検証可能な規則なので①/②に
    置ける安全部分集合)。改善しなかった/試せなかったフレームは ``needs_model_revision`` として
    ③ (モデル改訂の判断) へ上げる。

    :param result: ``sequential_rietveld`` 等が返す系列結果 (JSON dict)
    :param frames: ``result["frames"]`` と同順・同数の ``FrameSpec.to_dict()`` 列。**数が違えば
        精密化せず error dict を返す** (``repair_isolated`` は ``frames[i]`` を位置で引くため)
    :param phases: 系列で使われている全相の ``PhaseSpec.to_dict()`` 列 (相名で引く辞書のソース)。
        **系列に現れる相を 1 つでも欠くと精密化せず error dict を返す** (下記 相集合ガード)
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
    :returns: ``repairs``/``needs_model_revision``/``systematic_hint``/``discontinuities``/
        ``ledger_entries``。失敗 (系列結果が空/不正・フレーム数不一致・相集合の欠落・spec 復元
        失敗・instrument spec 不正・レンジ不正) は ``{"error", "error_type"}``
        (この場合 ``repairs`` 等のキーは返らない = 「不連続なし」と誤読されない)
    """
    from ..insitu.engine import _default_gsas_runner
    from ..insitu.model import SequentialConfig
    from ..insitu.repair import detect_discontinuities, repair_isolated
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

    discontinuities = detect_discontinuities(
        seq, rwp_abs=rwp_abs, rwp_delta=rwp_delta, frac_delta=frac_delta
    )

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
        "ledger_entries": [_ledger_entry_to_dict(e) for e in ledger.entries],
        "repairs": [
            {
                "frame": r.frame_index,
                "rwp_before": finite_or_none(r.rwp_before),
                "rwp_after": finite_or_none(r.rwp_after),
                "source": r.source,
                "phase_fractions": {k: finite_or_none(v) for k, v in r.phase_fractions.items()},
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
