"""② の成果物保存指定 (``gpx_dir`` / ``save_gpx``) の検査・正規化 (2026-08-20 規定「全解析で保存」)。

MCP の入力スキーマは緩い object (`server.py`: ``additionalProperties: True``) なので、型は
実処理側が守るしかない。保存指定は**型を間違えると黙って別の意味になる**:

- ``save_gpx: null`` — ``bool(None)`` も ``not None`` も「保存しない」に倒れる。他の引数
  (``gpx_dir``/``search``/``stability``) の null はどれも「既定」なので、``save_gpx`` だけ null が
  既定の**逆**になると ③ は気づかずに保存を止める。規定の opt-out は**明示 ``false`` だけ**。
- ``save_gpx: "false"`` は truthy なので保存し、``0`` は falsy なので止める — ③ の意図と無関係。
- ``gpx_dir: 123`` は単発経路では**精密化の後** (成果物の保存時) に ``TypeError`` が ② の境界を越える。

ここで ``TypeError`` にしておけば、各ツールの既存の ``except`` が ``{"error","error_type"}`` へ
縮退する (② は例外を送出しない)。
"""

from __future__ import annotations


def gpx_args(gpx_dir: object, save_gpx: object) -> tuple[str | None, bool]:
    """``(gpx_dir, save_gpx)`` を検査し、正規化した組を返す。

    :param gpx_dir: 保存先の根。``None`` (既定の解決に委ねる) か文字列
    :param save_gpx: 保存の opt-out。``True``/``False``。``None`` は**既定 (True)** として扱う
    :raises TypeError: 型が違う (呼び出し側が error dict へ縮退する)
    """
    if save_gpx is None:
        save_gpx = True
    elif not isinstance(save_gpx, bool):
        raise TypeError(
            f"save_gpx は true/false で指定してください (受け取った値 {save_gpx!r}: "
            f"{type(save_gpx).__name__})。保存を止める opt-out は明示の false だけです"
        )
    if gpx_dir is not None and not isinstance(gpx_dir, str):
        raise TypeError(
            f"gpx_dir は保存先の根のパス (文字列) か null で指定してください "
            f"(受け取った値 {gpx_dir!r}: {type(gpx_dir).__name__})"
        )
    return gpx_dir, save_gpx
