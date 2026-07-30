"""精密化エンジンの選択 (M12) — 文字列キー → ``run_*_rietveld``。

`run_auto_rietveld` (GSAS-II) と `run_topas_rietveld` (Bruker TOPAS) は**同一の入出力契約**を
持つ兵行実装なので、消費側は文字列キーで選べる。これが無いと ③ (LLM) は JSON しか送れないため
TOPAS 経路に到達できない (``runner`` の callable 引数はテスト注入専用; CLAUDE.md §4.5)。

**エンジンは遅延 import する**: ``import tsumugin.autorietveld`` が GSAS-II や TOPAS の有無に
依存しないという既存の性質を壊さない。
"""

from __future__ import annotations

from typing import Callable

from ..errors import TsumuginError

__all__ = ["BACKEND_NAMES", "DEFAULT_BACKEND", "describe_backends", "resolve_backend"]

DEFAULT_BACKEND = "gsasii"
BACKEND_NAMES: tuple[str, ...] = ("gsasii", "topas")


class UnknownBackendError(TsumuginError):
    """未知の精密化エンジン名を指定されたとき。**既定へ黙って落とさない**。

    「topaz」と綴り間違えたまま GSAS で回って気づかない、を防ぐ。
    """


def resolve_backend(name: "str | None") -> Callable[..., object]:
    """バックエンド名から精密化関数を返す (遅延 import)。

    :raises UnknownBackendError: 未知の名前 (既定へフォールバックしない)
    """
    key = (name or DEFAULT_BACKEND).strip().lower()
    if key == "gsasii":
        # 【パッケージ属性経由で引く】: `.engine` から直接引くと
        #   ``monkeypatch.setattr("tsumugin.autorietveld.run_auto_rietveld", …)`` を素通りする。
        #   既存の注入経路 (テスト・呼び出し側) を壊さないため解決点を変えない。
        from . import run_auto_rietveld

        return run_auto_rietveld
    if key == "topas":
        from ..topas.engine import run_topas_rietveld

        return run_topas_rietveld
    raise UnknownBackendError(
        f"未知の精密化バックエンドです: {name!r}。利用可能: {', '.join(BACKEND_NAMES)}。"
        f"綴り間違いを既定へ黙って落とすと、意図と違うエンジンで回った結果に気づけません。"
    )


def describe_backends() -> dict[str, dict[str, object]]:
    """② 向けの可用性一覧 (素の dict・**例外を出さない**)。

    ③ が「今この環境で何が使えるか」を問える唯一の窓口。
    """
    from ..backends.gsasii import gsasii_available
    from ..topas.availability import describe as topas_describe

    return {
        "gsasii": {
            "available": bool(gsasii_available()),
            "hint": (
                "GSAS-II は PyPI に無い。ソースツリー + buildtools バイナリを導入し "
                "`from GSASII import GSASIIscriptable` が通る状態にする。"
            ),
        },
        "topas": dict(topas_describe()),
    }
