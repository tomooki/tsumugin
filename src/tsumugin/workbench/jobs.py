"""精密化ジョブ — `RefinementJobManager` (`docs/design/gui-workbench/architecture.md` §バックエンド
`jobs.py`)。先例なしの新設計。``run_auto_rietveld`` を ``threading.Thread`` で実行し、状態
``idle/running/done/failed`` を GET /api/refine/status 契約形で報告する。

runner は callable 注入可 (**テスト専用**、§4.5 到達可能性)。実運用の既定 runner は
``build_default_runner`` が project から組む (MCP ``auto_rietveld``/``_default_gsas_runner`` と
同じ組み方: ``build_recipe`` → ``run_auto_rietveld``)。
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Callable, Mapping

if TYPE_CHECKING:  # 【型のみ参照】: 実行時 import は不要 (numpy/GSAS 汚染回避と同じ流儀) 🔵
    from ..autorietveld.model import AutoRietveldResult
    from ..store.ledger import Ledger
    from .project import WorkbenchProject

__all__ = ["RefinementJobManager", "build_default_runner"]

RunnerFn = Callable[[], "AutoRietveldResult"]
SuccessCallback = Callable[["AutoRietveldResult"], None]
FailureCallback = Callable[[BaseException], None]


def build_default_runner(
    project: "WorkbenchProject",
    *,
    ledger: "Ledger | None" = None,
    stages_on: "Mapping[str, bool] | None" = None,
    initial_occupancies: "Mapping[str, Mapping[str, float]] | None" = None,
) -> RunnerFn:
    """project から実 ``run_auto_rietveld`` runner を組む (実運用の既定経路)。

    MCP ``auto_rietveld`` (``rietveld_tools._build_input`` + ``refine_loop.orchestrator.
    _default_gsas_runner``) と同じ組み方: ``build_recipe`` で段階解放レシピを生成し
    ``run_auto_rietveld`` を実行する。``ledger`` を渡すと精密化中の段階進捗
    (``m7_stage``/``m7_stage_error``) が同一台帳に追記され、``RefinementJobManager.status()``
    の ``last_event`` から進捗をポーリングできる (architecture.md §バックエンド jobs.py)。

    :param stages_on: 段階 nn ("01","02",...) → 解放するか (A1, api-contract.md POST /api/refine)。
        ``False`` の段は ``build_recipe`` が返す段列から**そのまま除外**する — 呼び出し側
        (``WorkbenchSession.request_refine``) が ``viewmodel.stages`` (``_stages_from_recipe``)
        と同じ 1 始まり連番採番を単一情報源として使う契約なので、本関数はここで nn を再定義しない。
        ``None``/空なら全段既定 (後方互換)。
    :param initial_occupancies: 相名→{原子ラベル→占有率} の初期値シーダー (A3, ``ReviseStructure``
        で適用された occ revisions)。``run_auto_rietveld`` へそのまま透過する。

    .. warning::
        ``RefinementJobManager.start`` の ``runner`` 引数への直接注入は**テスト専用**の内部シーム
        (§4.5)。実運用は本関数が返す既定 runner のみを経路とする。
    """

    def runner() -> "AutoRietveldResult":
        from ..autorietveld.engine import run_auto_rietveld
        from ..autorietveld.recipe import build_recipe

        recipe = build_recipe(
            project.histograms, project.phases, background_coeffs=project.background_coeffs
        )
        if stages_on:
            recipe = tuple(
                stage
                for i, stage in enumerate(recipe, start=1)
                if stages_on.get(f"{i:02d}", True)
            )
        return run_auto_rietveld(
            list(project.histograms),
            list(project.phases),
            recipe=recipe,
            ledger=ledger,
            max_cyc=project.max_cyc,
            keep_gpx=project.gpx_path or None,
            initial_occupancies=initial_occupancies,
        )

    return runner


class RefinementJobManager:
    """単一の精密化ジョブをバックグラウンドスレッドで駆動し状態を報告する。

    ``start`` は実行中なら ``False`` を返し二重起動を防ぐ (POST /api/refine の 409 に対応)。
    ``on_success``/``on_failure`` は完了/失敗時にバックグラウンドスレッドから呼ばれる — 呼び出し側
    (``WorkbenchSession``) はこれらの中で自身のロックを取って状態を更新する契約
    (architecture.md 「lock 下で」)。``runner()`` または ``on_success()`` が例外を送出した場合も
    本クラスが捕捉して ``failed`` へ縮退させ ``on_failure`` を呼ぶ (例外貫通禁止)。
    """

    def __init__(
        self,
        *,
        now: Callable[[], float] = time.monotonic,
        last_event: "Callable[[], str | None] | None" = None,
    ) -> None:
        """
        :param now: 経過時間計測用の時刻取得関数 (既定 ``time.monotonic``)。決定論テストのため注入可能。
        :param last_event: 直近イベントのテキストを返す callable (既定は常に ``None``)。
            実運用では session ledger の最新エントリ text を返す関数を注入する。
        """
        self._lock = threading.Lock()
        self._now = now
        self._last_event = last_event or (lambda: None)
        self._status: str = "idle"
        self._start_time: float | None = None
        self._end_time: float | None = None
        self._error: str | None = None
        self._thread: threading.Thread | None = None

    def start(
        self,
        runner: RunnerFn,
        on_success: SuccessCallback,
        on_failure: FailureCallback,
        *,
        on_started: "Callable[[], None] | None" = None,
    ) -> bool:
        """ジョブを開始する。実行中なら何もせず ``False`` を返す (二重起動防止)。

        :param on_started: 受理が確定した (二重起動でない) 直後・バックグラウンドスレッド起動前に
            呼ぶ callable (既定 None)。**ロックを保持したまま**呼ぶため、``on_started`` が
            ledger に "requested" 相当のエントリを追記する場合、そのエントリは背景スレッドが
            付け足す "finished"/"failed" エントリより**必ず先に**現れることが保証される
            (`on_started` が同期的に完了してから ``Thread.start()`` するため happens-before が
            成立する。逆順で追記すると、即座に失敗する runner との競合で ledger の並びが
            "finished 済み → 後から requested" のように逆転しうる)。
        """
        with self._lock:
            if self._status == "running":
                return False
            self._status = "running"
            self._start_time = self._now()
            self._end_time = None
            self._error = None
            if on_started is not None:
                on_started()

        def _run() -> None:
            try:
                result = runner()
                on_success(result)
            except Exception as exc:  # 【境界: 例外貫通禁止】: runner/on_success いずれの例外も捕捉 🔵
                with self._lock:
                    self._status = "failed"
                    self._error = str(exc)
                    self._end_time = self._now()
                on_failure(exc)
                return
            with self._lock:
                self._status = "done"
                self._end_time = self._now()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return True

    def join(self, timeout: "float | None" = None) -> None:
        """バックグラウンドスレッドの完了を待つ (テスト用の同期ヘルパ、未起動なら no-op)。"""
        if self._thread is not None:
            self._thread.join(timeout)

    def status(self) -> dict[str, object]:
        """GET /api/refine/status 契約形を返す。"""
        with self._lock:
            status = self._status
            if status == "running" and self._start_time is not None:
                elapsed: float | None = self._now() - self._start_time
            elif self._start_time is not None and self._end_time is not None:
                elapsed = self._end_time - self._start_time
            else:
                elapsed = None
            error = self._error
        return {
            "status": status,
            "elapsed_s": elapsed,
            "last_event": self._last_event(),
            "error": error,
        }
