"""相分率ウォームスタートの共有機構 (Issue #96) — runner への `initial_fractions` 受け渡し。

Issue #82 は `run_auto_rietveld(initial_fractions=)` を追加し、M9 逐次エンジン
(`insitu.engine._call_runner`) にだけ配線した。**他の 2 経路 (M10 双方向区間 `anchor.segment`・
不連続修復 `repair`) は取り残され、セルしかウォームスタートしていなかった**。実測
(K₂Mn[Fe(CN)₆] 247 フレーム M10 実行) では 9 フレームが 2 相の等分 seed (0.50/0.50) に**厳密に**
張り付き、うち 6 連続が tetragonal ドーム頂点の直前にあった (ドーム位置と高さが信用できない)。
Rwp は張り付いたフレームでも 8.4-8.5% と平凡で、統計量からは検出できなかった。

本モジュールは 3 経路が共有する**唯一の**受け渡し機構を持つ (再発防止: 経路ごとの実装は
また取り残される)。numpy すら要らない純ロジックで、engine (GSAS 遅延 import を含む重い
モジュール) に依存しないため `anchor.segment` / `repair` から循環なしに import できる。

**`Runner` の 3 引数プロトコル ``(frame, phases, initial_cells)`` は変更しない** (公開 API・
`insitu.anchor`・既存テストスタブが依存)。`initial_fractions` はシグネチャ検査で受け付ける
runner を検出した場合のみキーワード引数として渡す (Issue #82 の意図的な後方互換設計)。

信頼性: 🔵 Issue #96 (実データ 247 フレームで seed 張り付きを実測)。
"""

from __future__ import annotations

import inspect
import math
from typing import TYPE_CHECKING, Callable, Mapping, Sequence

if TYPE_CHECKING:
    from ..autorietveld.model import AutoRietveldResult, PhaseSpec
    from .model import Cell, FrameSpec

__all__ = ["call_runner", "runner_accepts_initial_fractions", "seed_fractions"]


def runner_accepts_initial_fractions(runner: Callable) -> bool:
    """runner が ``initial_fractions`` キーワード引数を受け付けるか判定する (Issue #82/#96)。

    ``**kwargs`` を持つ runner (転送ラッパ) と、``initial_fractions`` を明示的に持つ runner
    (`make_gsas_runner` が生成するもの) を受け付けとみなす。3 引数のみの runner (大半のテスト
    スタブ・カスタム runner) は False で、一切渡さない = TypeError を起こさない。

    シグネチャを取得できない callable (組み込み関数等) は False へ縮退する (例外を出さない)。
    """
    try:
        sig = inspect.signature(runner)
    except (TypeError, ValueError):
        return False
    params = sig.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    return "initial_fractions" in params


def call_runner(
    runner: Callable,
    frame: "FrameSpec",
    phases: "Sequence[PhaseSpec]",
    initial_cells: "dict[str, Cell] | None",
    initial_fractions: "Mapping[str, float] | None" = None,
) -> "AutoRietveldResult":
    """runner を呼ぶ。``initial_fractions`` は対応 runner のみへキーワード引数で渡す。

    ``initial_fractions`` が None/空、または runner が受け付けないシグネチャの場合は従来通り
    3 引数で呼ぶ (非回帰)。**M9 逐次 / M10 双方向区間 / repair の 3 経路はすべてこれを使う**
    (Issue #96: 経路ごとの実装は取り残される)。
    """
    if initial_fractions and runner_accepts_initial_fractions(runner):
        return runner(frame, phases, initial_cells, initial_fractions=dict(initial_fractions))
    return runner(frame, phases, initial_cells)


def seed_fractions(
    fractions: "Mapping[str, float] | None", names: "Sequence[str] | None" = None
) -> "dict[str, float] | None":
    """次フレームへ渡す分率の種を正規化する (種にできないものは None = 種なし)。

    ``run_auto_rietveld`` 側の fail-open 規律 (`autorietveld.engine._apply_initial_fractions`) と
    同じ判断を**呼ぶ前に**行う: 空・全値が非有限・全値ゼロ (単相 GSAS 結果は
    ``phase_fractions`` が空で、消費側が相名で 0.0 埋めするとこれになる) は種にせず、従来通りの
    3 引数呼びへ縮退させる (誤って全相 0 分率で開始する事故を避ける)。

    :param fractions: 直前フレーム (またはアンカー) の相名→相分率
    :param names: 実際に渡す相集合の相名。指定時はこれに含まれる相のみを残す
        (相集合が違う相の分率を持ち込まない)
    :returns: 種にする dict。渡すものが無ければ None (`call_runner` が 3 引数呼びに縮退する)
    """
    if not fractions:
        return None
    allowed = set(names) if names is not None else None
    out: dict[str, float] = {}
    for key, value in fractions.items():
        if allowed is not None and key not in allowed:
            continue
        val = float(value)
        if not math.isfinite(val):
            return None  # 非有限が混じる分率は種にしない (fail-open)
        out[str(key)] = val
    if not out or not any(v != 0.0 for v in out.values()):
        return None
    return out
