"""JSON Kα2 spec ↔ `KAlpha2` 変換の共有ヘルパ (Issue #118)。

① `reference.kalpha.KAlpha2` は frozen dataclass であり、③ (JSON しか送れない LLM) から直接
構築できない。`identify_phases`/`identify_phase_mixtures` の ``kalpha2`` 引数は JSON dict を受け、
本モジュールがそれを ``KAlpha2`` へ変換する唯一の実装とする (二重実装を作らない, ``_recipe_spec.py``
と同じ方針)。

**不正なキー/型は無視せず `ValueError` に正規化する** — 呼び出し側が
``{"status":"error","error":...,"error_type":...}`` dict へ縮退する契約 (CLAUDE.md ② 不変条件)。
黙って無視すると「指定した Kα2 補正が静かに効かない」という「呼べるが黙って間違う」を再導入するため、
構造的な誤りは大声で失敗させる。
"""

from __future__ import annotations

from typing import Mapping

from ..reference.kalpha import KAlpha2

__all__ = ["kalpha2_from_spec"]

#: KAlpha2 の JSON 表現が許すキー。それ以外はタイポ/誤用として拒否する。
_ALLOWED_KALPHA2_KEYS = frozenset({"intensity_ratio", "wavelength_ratio"})


def kalpha2_from_spec(spec: Mapping[str, object] | None) -> KAlpha2 | None:
    """Kα2 spec (JSON dict) を `KAlpha2` へ変換する。``None`` は Kα2 無効のまま ``None`` を返す。

    :param spec: ``{"intensity_ratio": float (省略可), "wavelength_ratio": float (省略可)}``。
        省略したフィールドは ``KAlpha2`` の既定値 (Cu Kα1/Kα2) を使う。
    :raises ValueError: dict (Mapping) でない・不明なキーを含む・値が数値 (bool を除く) でない
    """
    if spec is None:
        return None
    if not isinstance(spec, Mapping):
        raise ValueError(f"kalpha2 は dict である必要があります: {type(spec).__name__}")
    unknown = set(spec) - _ALLOWED_KALPHA2_KEYS
    if unknown:
        raise ValueError(
            f"kalpha2 に不明なキー {sorted(unknown)} があります "
            f"(許容キー: {sorted(_ALLOWED_KALPHA2_KEYS)})"
        )
    kwargs: dict[str, float] = {}
    for key in _ALLOWED_KALPHA2_KEYS:
        if key not in spec:
            continue
        value = spec[key]
        # bool は int のサブクラスなので明示的に弾く (True/False を強度比に誤って渡す事故防止) 🔵
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"kalpha2.{key} は数値である必要があります: {value!r}")
        kwargs[key] = float(value)
    return KAlpha2(**kwargs)
