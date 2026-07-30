"""TOPAS 可用性境界 — コンソール実行体 ``tc.exe`` の解決 (M12 T1)。

``backends.gsasii.gsasii_available()`` / ``tests/conftest._dysnomia_available()`` と同型。
TOPAS は PyPI に存在しない商用ソフトなので optional extra ではなく**外部バイナリ**として扱い、
次の順で解決する:

1. 環境変数 ``TSUMUGIN_TOPAS_PATH`` (tc.exe そのもの / インストールディレクトリのどちらでも可)
2. 環境変数 ``TOPAS_PATH``
3. 既定インストール先 (``C:/TOPAS7`` 等)
4. ``PATH`` 上の ``tc``

**【sgcom6 教訓】** (実測): TOPAS は空間群の対称操作生成で ``sgcom6.exe`` を**子プロセスとして
起動する**。tc.exe を絶対パスで叩いても sgcom6 は PATH からしか引かれないため、PATH に
インストールディレクトリが無いと ``Cannot open file c:\\topas7\\sg\\<sg>.sg`` で異常終了する。
``topas_home()`` はそのために「tc.exe を含むディレクトリ」を返す (driver が PATH へ足す)。

本モジュールは stdlib のみ。TOPAS 未導入でも import は必ず成功する。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..errors import TopasUnavailableError

TOPAS_ENV_VARS: tuple[str, ...] = ("TSUMUGIN_TOPAS_PATH", "TOPAS_PATH")
"""tc.exe の場所を明示する環境変数 (先頭ほど優先)。"""

_TC_EXE_NAMES: tuple[str, ...] = ("tc.exe", "tc")
"""コンソール実行体のファイル名候補 (Windows / それ以外)。"""

_DEFAULT_INSTALL_DIRS: tuple[Path, ...] = (
    Path("C:/TOPAS7"),
    Path("C:/TOPAS6"),
    Path("C:/TOPAS5"),
)
"""環境変数が無いときに探す既定インストール先 (新しい版から順に)。"""

_DISABLED_VALUES: frozenset[str] = frozenset({"none", "off", "0", "disabled"})
"""環境変数に与えると TOPAS を「未導入」として扱う値 (導入済み機械で縮退経路を検証するため)。"""

_HINT = (
    "Bruker TOPAS の コンソール実行体 tc.exe が見つかりません。"
    "環境変数 TSUMUGIN_TOPAS_PATH に tc.exe またはインストールディレクトリ "
    "(例 C:/TOPAS7) を設定してください。"
)


def _tc_in_dir(directory: Path) -> "Path | None":
    """ディレクトリ直下の tc 実行体を返す (無ければ None)。"""
    for name in _TC_EXE_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _from_hint(raw: str) -> "Path | None":
    """環境変数の値 (実行体 or ディレクトリ) を tc.exe パスへ解決する。"""
    path = Path(raw).expanduser()
    if path.is_file():
        return path
    if path.is_dir():
        return _tc_in_dir(path)
    # 【指定されたのに実在しない】: 握って先へ進まず None を返す (fail closed)。
    return None


def resolve_tc_exe() -> "Path | None":
    """tc.exe の絶対パスを解決する。見つからなければ ``None`` (例外は出さない)。

    **【明示指定は権威的】**: 環境変数が設定されていれば、その値が解決できなくても既定
    インストール先や PATH へフォールバックしない。別の TOPAS を黙って掴んで「指定したのと
    違う版で回っていた」を起こさないため。``TSUMUGIN_TOPAS_PATH=none`` は明示的な無効化として
    使える (TOPAS 導入済みの機械で未導入時の縮退を検証する経路)。
    """
    for var in TOPAS_ENV_VARS:
        raw = os.environ.get(var)
        if raw is not None and raw.strip():
            if raw.strip().lower() in _DISABLED_VALUES:
                return None
            return _from_hint(raw)
    for directory in _DEFAULT_INSTALL_DIRS:
        found = _tc_in_dir(directory)
        if found is not None:
            return found
    which = shutil.which("tc")
    return Path(which) if which else None


def topas_available() -> bool:
    """TOPAS が利用可能か。**キャッシュしない** (環境変数で切り替わるため)。"""
    return resolve_tc_exe() is not None


def topas_home() -> "Path | None":
    """tc.exe を含むディレクトリ。driver が PATH へ足して sgcom6.exe を引けるようにする。"""
    exe = resolve_tc_exe()
    return exe.parent if exe is not None else None


def require_tc_exe() -> Path:
    """tc.exe を解決し、未導入なら :class:`TopasUnavailableError` を送出する。"""
    exe = resolve_tc_exe()
    if exe is None:
        raise TopasUnavailableError(_HINT)
    return exe


def describe() -> dict[str, object]:
    """② (MCP) 向けの素の dict。**例外を出さず** JSON 化可能な値のみを返す。"""
    exe = resolve_tc_exe()
    if exe is None:
        return {"available": False, "tc_path": None, "home": None, "hint": _HINT}
    return {"available": True, "tc_path": str(exe), "home": str(exe.parent)}
