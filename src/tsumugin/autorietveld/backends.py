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

__all__ = [
    "BACKEND_NAMES",
    "DEFAULT_BACKEND",
    "normalize_backend",
    "describe_backends",
    "resolve_backend",
    "resolve_protocol_backend",
    "resolve_recipe_builder",
]

DEFAULT_BACKEND = "gsasii"
BACKEND_NAMES: tuple[str, ...] = ("gsasii", "topas")


def normalize_backend(name: "str | None") -> str:
    """バックエンド名を正準形へ (``None``/大小/前後空白を吸収)。

    **比較は必ずこれを通す**: 解決系 (`resolve_backend`) が正規化しているのに呼び出し側が
    生文字列で比較すると、``None`` (JSON の ``null``) や ``"GSASII"`` が「既定ではない」と
    判定されて経路が食い違う。
    """
    return (name or DEFAULT_BACKEND).strip().lower()


class UnknownBackendError(TsumuginError):
    """未知の精密化エンジン名を指定されたとき。**既定へ黙って落とさない**。

    「topaz」と綴り間違えたまま GSAS で回って気づかない、を防ぐ。
    """


def resolve_backend(name: "str | None") -> Callable[..., object]:
    """バックエンド名から精密化関数を返す (遅延 import)。

    :raises UnknownBackendError: 未知の名前 (既定へフォールバックしない)
    """
    key = normalize_backend(name)
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


def resolve_protocol_backend(
    name: "str | None", *, wavelength: "float | None" = None
) -> object:
    """バックエンド名から **`RefinementBackend` Protocol の実装インスタンス**を返す。

    `resolve_backend` が返すのは実構造エンジン (`run_*_rietveld`) で、こちらは仮説探索/判別が
    使う境界 (``simulate`` / ``refine``) である。**名前の語彙は 1 か所に持つ** — ツールごとに
    文字列比較を書くと、``"topas"`` を受けるツールと受けないツールが混ざって ③ から見た
    振舞いが食い違う。

    :raises UnknownBackendError: 未知の名前 (既定へフォールバックしない)
    :raises GSASUnavailableError / TopasUnavailableError: エンジン未導入 (呼び出し側が
        ``{"error","error_type"}`` へ縮退させる)
    """
    key = normalize_backend(name)
    if key == "gsasii":
        from ..backends.gsasii import GSASIIBackend

        return GSASIIBackend(wavelength=wavelength) if wavelength is not None else GSASIIBackend()
    if key == "topas":
        from ..backends.topas import TopasBackend

        return TopasBackend(wavelength=wavelength) if wavelength is not None else TopasBackend()
    raise UnknownBackendError(
        f"未知の精密化バックエンドです: {name!r}。利用可能: {', '.join(BACKEND_NAMES)}。"
        f"綴り間違いを既定へ黙って落とすと、意図と違うエンジンで回った結果に気づけません。"
    )


def _topas_threads() -> int:
    """tc.exe を何スレッドで起動するか (`topas.driver` の既定と**同じ解決**を使う)。"""
    import os

    from ..topas.driver import thread_count

    return int(thread_count(os.environ.get("TSUMUGIN_TOPAS_THREADS")))


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
        "topas": {
            **dict(topas_describe()),
            # 【再現性の既定を ③ から見えるようにする】: tc.exe はスレッド数で結果が変わる
            #   ので既定は 1 スレッド (NFR-102)。速度が要る場面のための逃げ道も含めて
            #   ここに出さないと、③ からは「なぜ遅いのか」も「外せるのか」も分からない。
            "threads": _topas_threads(),
            "threads_note": (
                "tc.exe はスレッド数で結果が変わる (同一入力の T4 が 43.49/67.62/29.29% に "
                "散らばった実測) ため既定は 1 スレッド。環境変数 TSUMUGIN_TOPAS_THREADS で "
                "増やせるが、**再現性を捨てる選択**であり Rwp の比較・段の受理判定・"
                "ベンチマークが実行ごとに変わりうる。"
            ),
        },
    }


def resolve_recipe_builder(name: "str | None") -> Callable[..., object]:
    """バックエンド名から**既定レシピのビルダ**を返す。

    **エンジンだけ切り替えてレシピを共有してはならない**: GSAS は装置ファイルから較正済みの
    Caglioti U,V,W を読んで始まるので格子を先に解放しても収束するが、TOPAS の TCHZ は装置
    ファイルを参照せず汎用初期値から始まるため、ピーク幅が合わないまま格子を解放すると格子が
    幅の不一致を吸収して**悪化する** (実測 garnet: GSAS 順だと S1 cell が 42.7 → 50.7 で revert、
    最終 23.6% 頭打ち。TOPAS 順なら 11.8%)。

    :raises UnknownBackendError: 未知の名前
    """
    key = normalize_backend(name)
    if key == "gsasii":
        from . import build_recipe

        return build_recipe
    if key == "topas":
        from ..topas.recipe import build_topas_recipe

        return build_topas_recipe
    raise UnknownBackendError(
        f"未知の精密化バックエンドです: {name!r}。利用可能: {', '.join(BACKEND_NAMES)}。"
    )
