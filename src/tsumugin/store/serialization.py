"""PhaseInstance <-> dict 相互変換 (TASK-0012 store/serialization)。

【機能概要】: M2 永続化基盤の最下層として、PhaseInstance と「json.dumps 可能な素の dict」
の間を相互変換する純関数 phase_to_dict / phase_from_dict を提供する。
【実装方針】: 標準ライブラリ (math / typing) のみで完結。上位レイヤ (search/refinement) を
import しないレイヤ制約を守り、非有限判定は共有葉モジュール _json.finite_or_none へ委譲する
(TASK-0023 で 3 箇所の重複を単一情報源へ統合。M1 教訓の JSON 純化はそのまま踏襲)。
【テスト対応】: tests/test_serialization.py の 15 件 (N-01〜N-06 / E-01〜E-03 / B-01〜B-06)。
🔵 信頼性レベル: 要件定義 §2 の dict スキーマ / interfaces.py L256-292 に依拠。
"""

from __future__ import annotations

import math
from typing import Any, Mapping, get_args

from tsumugin._json import finite_or_none
from tsumugin.model import (
    LatticeParams,
    PhaseInstance,
    PhaseLifecycle,
    RefinementMetrics,
    SigmaSource,
    TofBankParams,
)

# 【sigma_source 許容値】: SigmaSource Literal から導出した単一情報源。許容外の文字列
#   (旧データ/破損) は復元時に "" へ縮退させる (後方互換, Issue #66 レビュー対応) 🔵
_SIGMA_SOURCES: frozenset[str] = frozenset(get_args(SigmaSource))

__all__ = [
    "bank_params_from_dict",
    "bank_params_to_dict",
    "metrics_from_dict",
    "metrics_to_dict",
    "phase_from_dict",
    "phase_to_dict",
]


def _finite_map(mapping: Mapping[str, float]) -> dict[str, float | None]:
    """【機能概要】: Mapping を素の dict にコピーしつつ各値を JSON 純化する。
    【実装方針】: sigma / occupancies 共通の変換 (tuple や Mapping 実装型を残さない)。
    【テスト対応】: N-05 (sigma/occupancies 保存)、E-02/E-03 (Mapping 内の非有限 → None)。
    🔵 信頼性レベル: 要件定義 §2.1 「dict(mapping) で素の dict へコピー」に依拠。
    """
    return {key: finite_or_none(value) for key, value in mapping.items()}


def _value_or_default(value: float | None, default: float) -> float:
    """【機能概要】: None (欠損または非有限純化済み) を既定値へ置き換える。
    【実装方針】: 0.0 など falsy な有限値を既定に潰さないよう `is None` で判定する。
    【テスト対応】: B-04 (欠損補完)、B-06 (confidence=0.0 を保持)。
    🟡 信頼性レベル: 要件定義 §2.2 欠損補完 / None 頑健性からの妥当な具体化。
    """
    return default if value is None else value


def _coerce_sigma_source(value: Any) -> SigmaSource:
    """【機能概要】: 復元した sigma_source を SigmaSource の許容値へ縮退させる。
    【実装方針】: 欠落 (None) と許容外文字列 (旧データ/破損) は "" へフォールバックし、
    fail-loud しない (σ 由来は精密化成否そのものではない)。許容値は Literal から導出した
    ``_SIGMA_SOURCES`` を単一情報源とする。``value in _SIGMA_SOURCES`` は非 hashable な値
    (list/dict 等) で ``TypeError`` を送出しうるため、先に ``isinstance(value, str)`` で
    型を確認してから集合判定する (str 以外は判定を試みず即座に "" へ縮退, レビュー対応)。
    【テスト対応】: test_unknown_sigma_source_degrades_to_empty /
    test_non_string_sigma_source_degrades_to_empty / 既存 roundtrip テスト。
    🔵 信頼性レベル: Issue #66 レビュー対応 (許容外文字列 → "" 縮退、非 hashable クラッシュ回避)。
    """
    if not isinstance(value, str):
        return ""
    return value if value in _SIGMA_SOURCES else ""


def _require_finite_lattice(value: Any, field: str) -> float:
    """格子 a/b/c の復元値を検証する。None (非有限純化済み) と非有限は ValueError。

    格子長は構造的必須値で、既定値による捏造も None のままの復元 (下流の数値演算で
    沈黙破綻) も許されない。fail-loud で明示拒否する (PR #2 レビュー指摘対応)。
    """
    if value is None:
        raise ValueError(
            f"lattice.{field} が None (非有限として純化済み) のため PhaseInstance を"
            " 復元できません。非有限格子の相は永続化対象外です。"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"lattice.{field}={v!r} は非有限のため復元できません。")
    return v


def phase_to_dict(phase: PhaseInstance) -> dict[str, Any]:
    """【機能概要】: PhaseInstance を JSON ネイティブ型のみの dict へ直列化する。
    【実装方針】: 要件定義 §2.1 の固定スキーマに従い、全 float フィールドを
    finite_or_none で純化する。入力は変更しない純関数 (決定論 NFR-102)。
    【テスト対応】: N-01〜N-06 / E-01〜E-03 / B-01〜B-06 の直列化側。
    🔵 信頼性レベル: 要件定義 §2.1 dict スキーマ / interfaces.py L261 に依拠。

    Args:
        phase: 直列化する相インスタンス (frozen dataclass)。

    Returns:
        json.dumps(d, allow_nan=False) 可能な素の dict。
    """
    lattice = phase.lattice
    # 【lifecycle 変換】: None はそのまま null、値があればネスト dict へ展開 🔵
    lifecycle: dict[str, Any] | None = None
    if phase.lifecycle is not None:
        lifecycle = {
            "birth_frame": phase.lifecycle.birth_frame,  # 【int|None】: 純化不要 (float でない) 🔵
            "death_frame": phase.lifecycle.death_frame,
            "confidence": finite_or_none(phase.lifecycle.confidence),  # 【純化】: nan → None 🟡
        }

    # 【結果構造】: 要件定義 §2.1 の固定スキーマ (TASK-0014 が依存するため順序・キー名を固定) 🟡
    return {
        "phase_ref": phase.phase_ref,
        "lattice": {
            "a": finite_or_none(lattice.a),
            "b": finite_or_none(lattice.b),
            "c": finite_or_none(lattice.c),
            "alpha": finite_or_none(lattice.alpha),  # 【既定角明示】: 90.0 も省略せず出力 🔵
            "beta": finite_or_none(lattice.beta),
            "gamma": finite_or_none(lattice.gamma),
            "sigma": _finite_map(lattice.sigma),  # 【素 dict コピー】: 空なら {} 🔵
            # 【Issue #66 / FR-306】: σ 由来 ("covariance"/"proxy"/"") をラウンドトリップ保存 🔵
            "sigma_source": lattice.sigma_source,
        },
        "scale": finite_or_none(phase.scale),
        "wt_frac": finite_or_none(phase.wt_frac),  # 【None 保持】: 未定 None と消失 0.0 を区別 🟡
        "occupancies": _finite_map(phase.occupancies),
        "lifecycle": lifecycle,
    }


def phase_from_dict(data: Mapping[str, Any]) -> PhaseInstance:
    """【機能概要】: phase_to_dict が生成した dict から PhaseInstance を再構築する。
    【実装方針】: 明示キー取り出し (data.get) により未知キーを無視 (前方互換) し、
    欠損 optional キーは dataclass の既定値で補完する (後方互換)。
    【テスト対応】: N-01/N-03/N-04/N-05 (roundtrip)、B-01〜B-06 (縮退/欠損/未知キー)。
    🔵 信頼性レベル: 要件定義 §2.2 (未知キー無視・欠損補完・型復元) に依拠。

    Args:
        data: phase_to_dict の出力 (または後続スキーマ) の Mapping。

    Returns:
        復元された PhaseInstance (ネストは LatticeParams / PhaseLifecycle として型復元)。
    """
    # 【必須キー取り出し】: phase_ref / lattice は契約上必須 (欠落は KeyError に委ねる) 🔵
    lattice_data: Mapping[str, Any] = data["lattice"]
    lattice = LatticeParams(
        # 【格子検証】: a/b/c は構造的必須。None (非有限純化済み) は既定値で捏造せず
        #   fail-loud で拒否する (往復非対称の解消、PR #2 レビュー MEDIUM 対応)
        a=_require_finite_lattice(lattice_data["a"], "a"),
        b=_require_finite_lattice(lattice_data["b"], "b"),
        c=_require_finite_lattice(lattice_data["c"], "c"),
        # 【欠損補完】: 角欠落 (旧スキーマ) は既定 90.0 で補完 (後方互換) 🟡
        alpha=_value_or_default(lattice_data.get("alpha"), 90.0),
        beta=_value_or_default(lattice_data.get("beta"), 90.0),
        gamma=_value_or_default(lattice_data.get("gamma"), 90.0),
        sigma=dict(lattice_data.get("sigma") or {}),  # 【欠損補完】: sigma 欠落 → {} 🟡
        # 【欠損補完 + 許容値ガード】: sigma_source 欠落 (旧スキーマ) は "" 補完、許容外文字列
        #   (SigmaSource Literal 外) も "" へ縮退させる (後方互換, Issue #66) 🟡
        sigma_source=_coerce_sigma_source(lattice_data.get("sigma_source")),
    )

    # 【lifecycle 復元】: dict のままにせず PhaseLifecycle として型復元する (N-04) 🔵
    lifecycle_data: Mapping[str, Any] | None = data.get("lifecycle")
    lifecycle: PhaseLifecycle | None = None
    if lifecycle_data is not None:
        lifecycle = PhaseLifecycle(
            birth_frame=lifecycle_data.get("birth_frame"),
            death_frame=lifecycle_data.get("death_frame"),
            # 【None 頑健性】: 非有限で None 化された confidence は既定 1.0 へフォールバック 🟡
            confidence=_value_or_default(lifecycle_data.get("confidence"), 1.0),
        )

    return PhaseInstance(
        phase_ref=data["phase_ref"],
        lattice=lattice,
        # 【None 頑健性】: 非有限で None 化された scale は既定 1.0 へフォールバック 🟡
        scale=_value_or_default(data.get("scale"), 1.0),
        wt_frac=data.get("wt_frac"),  # 【None 保持】: wt_frac は None が正当値 (B-02) 🟡
        occupancies=dict(data.get("occupancies") or {}),  # 【欠損補完】: 欠落 → {} 🟡
        lifecycle=lifecycle,
    )


def bank_params_to_dict(params: TofBankParams) -> dict[str, Any]:
    """【機能概要】: TofBankParams を JSON ネイティブ dict へ直列化する (TASK-0036/TC-401-04)。
    【実装方針】: phase_to_dict と同じく全 float を finite_or_none で純化し、
    json.dumps(allow_nan=False) 可能な素の dict を返す純関数。
    🟡 信頼性レベル: interfaces.py bank_params_to_dict / TC-401-04 に依拠。

    Args:
        params: 直列化する TOF バンク較正パラメータ (frozen dataclass)。

    Returns:
        difc/difa/zero を持つ素の dict (非有限は None へ純化)。
    """
    return {
        "difc": finite_or_none(params.difc),
        "difa": finite_or_none(params.difa),  # 【既定明示】: 0.0 も省略せず出力
        "zero": finite_or_none(params.zero),
    }


def bank_params_from_dict(data: Mapping[str, Any]) -> TofBankParams:
    """【機能概要】: dict から TofBankParams を復元する (往復対称・欠損は既定値補完, TC-401-04/EDGE-002)。
    【実装方針】: 明示キー取り出し (data.get) で未知キーを無視 (前方互換) し、欠損 optional キーと
    非有限で None 化された値は dataclass 既定 (difc=0.0/difa=0.0/zero=0.0) で補完する (後方互換)。
    🟡 信頼性レベル: interfaces.py bank_params_from_dict / TC-401-04 に依拠。

    Args:
        data: bank_params_to_dict の出力 (または後続スキーマ) の Mapping。

    Returns:
        復元された TofBankParams。
    """
    return TofBankParams(
        difc=_value_or_default(data.get("difc"), 0.0),
        difa=_value_or_default(data.get("difa"), 0.0),
        zero=_value_or_default(data.get("zero"), 0.0),
    )


def metrics_to_dict(metrics: RefinementMetrics) -> dict[str, Any]:
    """【機能概要】: RefinementMetrics を dict へ直列化する (Issue #64 / FR-123 noise_scale 追加)。
    【実装方針】: PhaseInstance の格子 (a/b/c) と異なり、rwp/gof/chi2 は非有限 (chi2=inf) が
    「精密化失敗」を示す正常な状態 (EDGE-004) である。ここを finite_or_none で None へ純化する
    と、往復復元時に 0.0 等へフォールバックせざるを得ず「収束成功」を捏造して evidence
    (BIC/AIC) を汚染しかねない。よって rwp/gof/chi2/evidence は非有限のまま忠実に往復させる
    (呼び出し元の ledger/persistent は json.dumps に allow_nan=False を使わないため、Python
    内部の往復であれば inf/nan も安全に運べる)。外部 HTTP 配信向けの非有限→null 純化は
    webui._serialize_metrics が別途担う (用途が異なる: 内部永続化 vs 外部 JSON 配信)。
    optional フィールド (multistart/noise_scale) は未設定なら None のまま出力する。
    🟡 信頼性レベル: RefinementMetrics には往復変換の precedent がなく、既存 phase_to_dict /
    bank_params_to_dict の様式 (dict.get 前方互換・欠損補完) を踏襲した設計判断。

    Args:
        metrics: 直列化する精密化メトリクス。

    Returns:
        metrics_from_dict で復元可能な素の dict。
    """
    return {
        "rwp": float(metrics.rwp),
        "gof": float(metrics.gof),
        "chi2": float(metrics.chi2),
        "n_obs": int(metrics.n_obs),
        "n_params": int(metrics.n_params),
        "evidence": {str(key): float(value) for key, value in metrics.evidence.items()},
        # 【None 保持】: multistart 未設定 (非マルチスタート精密化) と後方互換のための None 🟡
        "multistart": dict(metrics.multistart) if metrics.multistart is not None else None,
        # 【None 保持 (Issue #64)】: noise_scale 未推定 (既定) と後方互換のための None 🔵
        "noise_scale": (
            float(metrics.noise_scale) if metrics.noise_scale is not None else None
        ),
    }


def metrics_from_dict(data: Mapping[str, Any]) -> RefinementMetrics:
    """【機能概要】: metrics_to_dict が生成した dict から RefinementMetrics を再構築する。
    【実装方針】: rwp/gof/chi2/n_obs/n_params は構造的必須フィールド (dataclass に既定値なし)
    のため明示キー取り出しとし、欠落は KeyError に委ねる (phase_to_dict の phase_ref/lattice
    と同じ fail-loud 方針)。evidence/multistart/noise_scale は optional (欠損 or None は
    既定値へ後方互換で補完, REQ-404): evidence は旧データ (キー欠落) で {}、multistart/
    noise_scale は旧データ (Issue #64 以前に永続化された dict) で None を補完する。
    🟡 信頼性レベル: metrics_to_dict と対称な設計判断 (precedent なし)。

    Args:
        data: metrics_to_dict の出力 (または後続スキーマ) の Mapping。

    Returns:
        復元された RefinementMetrics。

    Raises:
        KeyError: rwp/gof/chi2/n_obs/n_params のいずれかが欠落している (構造的必須値)。
    """
    multistart_data = data.get("multistart")
    noise_scale_data = data.get("noise_scale")
    return RefinementMetrics(
        rwp=float(data["rwp"]),
        gof=float(data["gof"]),
        chi2=float(data["chi2"]),
        n_obs=int(data["n_obs"]),
        n_params=int(data["n_params"]),
        # 【欠損補完】: evidence 欠落 (旧スキーマ/未計算) → {} 🟡
        evidence={str(key): float(value) for key, value in (data.get("evidence") or {}).items()},
        multistart=dict(multistart_data) if multistart_data is not None else None,
        noise_scale=float(noise_scale_data) if noise_scale_data is not None else None,
    )
