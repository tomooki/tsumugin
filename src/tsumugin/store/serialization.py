"""PhaseInstance <-> dict 相互変換 (TASK-0012 store/serialization)。

【機能概要】: M2 永続化基盤の最下層として、PhaseInstance と「json.dumps 可能な素の dict」
の間を相互変換する純関数 phase_to_dict / phase_from_dict を提供する。
【実装方針】: 標準ライブラリ (math / typing) のみで完結。上位レイヤ (search/refinement) を
import しないレイヤ制約を守り、非有限判定はローカル _finite_or_none で行う (M1 教訓)。
【テスト対応】: tests/test_serialization.py の 15 件 (N-01〜N-06 / E-01〜E-03 / B-01〜B-06)。
🔵 信頼性レベル: 要件定義 §2 の dict スキーマ / interfaces.py L256-292 に依拠。
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from tsumugin.model import LatticeParams, PhaseInstance, PhaseLifecycle

__all__ = ["phase_from_dict", "phase_to_dict"]


def _finite_or_none(value: float | None) -> float | None:
    """【機能概要】: 有限 float はそのまま、非有限 (inf/-inf/NaN) と None は None を返す。
    【実装方針】: json.dumps(allow_nan=False) を通す JSON 純化 (M1 レビュー教訓)。
    【テスト対応】: E-01/E-02/E-03 (非有限 → None)、B-06 (有限端点 0.0/1.0 は保持)。
    🔵 信頼性レベル: 要件定義 §2.1 非有限値の純化 / search/tree.py の同名契約に倣う。
    """
    # 【入力値検証】: None (未定値) はそのまま None として通す 🔵
    if value is None:
        return None
    # 【純化判定】: math.isfinite が False の値 (inf/NaN) を None へ写像 🔵
    v = float(value)
    return v if math.isfinite(v) else None


def _finite_map(mapping: Mapping[str, float]) -> dict[str, float | None]:
    """【機能概要】: Mapping を素の dict にコピーしつつ各値を JSON 純化する。
    【実装方針】: sigma / occupancies 共通の変換 (tuple や Mapping 実装型を残さない)。
    【テスト対応】: N-05 (sigma/occupancies 保存)、E-02/E-03 (Mapping 内の非有限 → None)。
    🔵 信頼性レベル: 要件定義 §2.1 「dict(mapping) で素の dict へコピー」に依拠。
    """
    return {key: _finite_or_none(value) for key, value in mapping.items()}


def _value_or_default(value: float | None, default: float) -> float:
    """【機能概要】: None (欠損または非有限純化済み) を既定値へ置き換える。
    【実装方針】: 0.0 など falsy な有限値を既定に潰さないよう `is None` で判定する。
    【テスト対応】: B-04 (欠損補完)、B-06 (confidence=0.0 を保持)。
    🟡 信頼性レベル: 要件定義 §2.2 欠損補完 / None 頑健性からの妥当な具体化。
    """
    return default if value is None else value


def phase_to_dict(phase: PhaseInstance) -> dict[str, Any]:
    """【機能概要】: PhaseInstance を JSON ネイティブ型のみの dict へ直列化する。
    【実装方針】: 要件定義 §2.1 の固定スキーマに従い、全 float フィールドを
    _finite_or_none で純化する。入力は変更しない純関数 (決定論 NFR-102)。
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
            "confidence": _finite_or_none(phase.lifecycle.confidence),  # 【純化】: nan → None 🟡
        }

    # 【結果構造】: 要件定義 §2.1 の固定スキーマ (TASK-0014 が依存するため順序・キー名を固定) 🟡
    return {
        "phase_ref": phase.phase_ref,
        "lattice": {
            "a": _finite_or_none(lattice.a),
            "b": _finite_or_none(lattice.b),
            "c": _finite_or_none(lattice.c),
            "alpha": _finite_or_none(lattice.alpha),  # 【既定角明示】: 90.0 も省略せず出力 🔵
            "beta": _finite_or_none(lattice.beta),
            "gamma": _finite_or_none(lattice.gamma),
            "sigma": _finite_map(lattice.sigma),  # 【素 dict コピー】: 空なら {} 🔵
        },
        "scale": _finite_or_none(phase.scale),
        "wt_frac": _finite_or_none(phase.wt_frac),  # 【None 保持】: 未定 None と消失 0.0 を区別 🟡
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
        a=lattice_data["a"],
        b=lattice_data["b"],
        c=lattice_data["c"],
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
