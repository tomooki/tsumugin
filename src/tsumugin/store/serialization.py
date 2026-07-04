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
from typing import Any, Mapping

from tsumugin._json import finite_or_none
from tsumugin.model import LatticeParams, PhaseInstance, PhaseLifecycle, TofBankParams

__all__ = [
    "bank_params_from_dict",
    "bank_params_to_dict",
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
