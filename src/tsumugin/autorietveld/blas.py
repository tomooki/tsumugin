"""BLAS のスレッド数の固定 (fit-then-judge P1-1B, NFR-102)。

悪条件の最小二乗では総和順序がスレッド割り当てで変わり、結果がビット同一にならない (TOPAS の tc.exe で
実測した非決定性と同型 — `topas.driver` は 1 スレッドで起動している)。GSAS-II の精密化は numpy/scipy の
BLAS を使うので、`threadpoolctl` で同じことをする。

⚠ **プロセス全体に効く** — 同じプロセスで並行に走る精密化 (workbench のジョブ等) も同じ制限を受ける。
既定は無効 (``blas_threads=None`` は何もしない = 既存経路はビット同一)。
``threadpoolctl`` は ``gsas`` extra に入れてある (**遅延 import**。無ければ固定を頼んだ呼び出しが ImportError)。
"""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

__all__ = ["blas_thread_report", "with_blas_threads"]

F = TypeVar("F", bound=Callable[..., Any])


def _check(n: object) -> int:
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"blas_threads は 1 以上の整数です: {n!r}")
    return n


def _blas_infos() -> list[dict]:
    from threadpoolctl import threadpool_info

    return [i for i in threadpool_info() if i.get("user_api") == "blas"]


def blas_thread_report(requested: "int | None") -> dict[str, object]:
    """いま読み込まれている BLAS のスレッド数を報告する (ledger に載せる)。

    ``ok`` は BLAS を 1 つ以上検出し、すべてが ``requested`` スレッドのときだけ真 — 検出できなかったときに
    「固定できた」と答えない。
    """
    infos = _blas_infos()
    observed = [int(i.get("num_threads", -1)) for i in infos]
    return {
        "requested": requested,
        "observed": observed,
        "libraries": [str(i.get("internal_api", "")) for i in infos],
        "ok": bool(observed) and requested is not None and all(o == requested for o in observed),
    }


def with_blas_threads(fn: F) -> F:
    """キーワード引数 ``blas_threads`` が整数なら、その数に BLAS を制限した中で ``fn`` を呼ぶ。

    関数の本体を包む (戻り口が多い関数を字下げし直さずに済む)。``fn`` 自身も ``blas_threads`` を引数に持ち、
    制限の中から `blas_thread_report` で実際の数を記録できる。
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        n = kwargs.get("blas_threads")
        if n is None:
            return fn(*args, **kwargs)
        _check(n)
        from threadpoolctl import threadpool_limits

        # threadpool_limits は**読み込み済み**のライブラリにしか効かない。制限の中で初めて読み込まれる
        #   BLAS (GSAS が import する SciPy の BLAS など) を取りこぼさないよう先に読み込む (セルフレビュー L1)
        try:
            import scipy.linalg  # noqa: F401
        except ImportError:  # pragma: no cover — scipy は gsas extra
            pass

        with threadpool_limits(limits=n, user_api="blas"):
            return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
