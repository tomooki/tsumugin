"""② 実行系ツールの I/O 例外縮退デコレータ (Issue #94)。

③ は LLM なので、GSAS/ローダーが投げる ``FileNotFoundError`` 等の I/O 例外が MCP 境界を越えると
**回復不能なハード失敗**になる (CLAUDE.md ② 不変条件: 例外を送出せず ``{"error","error_type"}``
へ縮退する)。精密化そのものの失敗は ① が ``chi2=inf`` の結果へ変換済みなので、ここで縮退するのは
主に**入力ファイル不在**の I/O エラー (実測: 存在しないパスで ``auto_rietveld``/``sequential_rietveld``/
``anchored_sequential`` が ``FileNotFoundError`` を送出していた)。

**テストシームを壊さない**: 注入 runner / monkeypatch を使う決定論テストはファイルに触れないため
``OSError`` を投げず、本デコレータは透過する (正常 dict をそのまま返す)。実 GSAS 経路で実ファイルが
無いときだけ縮退が発火する。

⚠ ``functools.wraps`` で ``__wrapped__`` を設定するため、``inspect.signature`` は元シグネチャを
辿る (server.py の session 判定が壊れない)。``inspect.getsource``/``__globals__`` を使う静的解析
(tests/test_layer_coverage.py の AST 網) は ``inspect.unwrap`` で元関数へ辿る必要がある。
"""

from __future__ import annotations

import functools
from typing import Callable, TypeVar

_F = TypeVar("_F", bound=Callable[..., dict])


def degrade_oserror(fn: _F) -> _F:
    """``OSError`` (ファイル不在等の I/O 失敗) を ``{"error","error_type"}`` dict へ縮退する。

    ``error_type`` に実際の例外クラス名 (``FileNotFoundError``/``PermissionError`` 等) を入れるので、
    ③ は「入力ファイルが無い」と「別の失敗」を区別できる。``OSError`` **以外**の例外は透過させる
    (論理バグを握り潰さない — 縮退対象は I/O 失敗に限る)。
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> dict:
        try:
            return fn(*args, **kwargs)
        except OSError as exc:
            return {"error": str(exc), "error_type": type(exc).__name__}

    return wrapper  # type: ignore[return-value]
