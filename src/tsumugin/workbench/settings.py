"""ユーザ単位のアプリ設定 (資格情報) — Materials Project アクセストークン
(`docs/design/gui-workbench/api-contract.md` §アプリ設定 (資格情報))。

プロジェクトではなく ``~/.tsumugin/settings.json`` に保存する — project.json は共有・zip される
想定であり資格情報を置いてはならない。

【取り扱いの絶対規則 (契約)】:

- **API はキー本体を返さない**。返せるのは「設定されているか」と末尾数文字のマスク hint のみ。
- **ledger にキーを書かない**。呼び出し側 (`session.WorkbenchSession`) が記録する ``settings_change``
  payload は ``{"key", "action"}`` のみで値を含めない。
- **エージェントに読ませない**: 本モジュールを ``agent_mcp`` (shim) から呼ばない。
- **優先順位: 設定ファイル > 環境変数** ``MATERIALS_PROJECT_API``。``apply_mp_api_key_to_env`` が
  設定ファイルの値をプロセス env へ反映し、既存の ``MPRestClient()`` 遅延構築経路
  (``tsumugin.mp.client``, env → .env の順で読む) がそのまま使えるようにする (① は変更しない)。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..mp.client import _API_KEY_ENV as _MP_API_KEY_ENV

__all__ = [
    "SETTINGS_JSON_NAME",
    "load_settings",
    "save_setting",
    "clear_setting",
    "mp_api_key_status",
    "apply_mp_api_key_to_env",
    "mp_available",
]

#: ``~/.tsumugin/`` 直下の設定ファイル名。
SETTINGS_JSON_NAME = "settings.json"

#: 設定キー → 反映先の環境変数名 (現状 MP キーのみ)。``clear_setting`` が対応する env も消す。
_ENV_KEY_MAP: dict[str, str] = {"mp_api_key": _MP_API_KEY_ENV}


def _settings_path() -> Path:
    """``~/.tsumugin/settings.json`` (``Path.home()`` は呼び出し時に解決 — テストで monkeypatch 可)。"""
    return Path.home() / ".tsumugin" / SETTINGS_JSON_NAME


def load_settings() -> dict[str, Any]:
    """設定ファイルを読む。未作成/壊れている場合は例外を投げず空 dict を返す。"""
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return dict(data)


def _write_settings(data: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 【アトミック書き込み】: 一時ファイル + os.replace。直接上書きだと書き込み中のクラッシュで
    #   壊れた JSON が残り、load_settings がそれを {} として握りつぶすため**無言で設定が消える**。
    #   資格情報ファイルなので「気づかず失われる」を避ける (レビュー指摘)。
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    # 【POSIX 0600】: 所有者のみ読み書き可 (資格情報ファイル)。Windows では os.chmod が実効を
    #   持たないため best-effort — 失敗しても書き込み自体は成功として扱う (呼び出し元をブロックしない)。
    #   rename 前に付けることで、他者から読める窓を作らない。
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def save_setting(key: str, value: str) -> None:
    """``key`` の値を設定ファイルへ保存する (キー本体をログ出力/例外メッセージに含めない)。"""
    data = load_settings()
    data[key] = value
    _write_settings(data)


def clear_setting(key: str) -> None:
    """``key`` を設定ファイルから削除する。**アプリが env へ反映した分のみ**取り消す。

    【アプリ管理外の env を壊さない】: プロセス env から消してよいのは
    ``apply_mp_api_key_to_env``/``save_setting`` が「設定ファイルの値で上書きした分」だけ。
    ユーザがシェルで直接 export した ``MATERIALS_PROJECT_API`` を CLEAR で消すと、
    **アプリが一度も預かっていない資格情報を奪って MP 機能を全滅させる** (プロセス再起動
    まで復旧しない)。設定ファイルに値が無ければ env には触らない。
    ファイルに無い場合も例外にせず no-op として扱う (冪等)。
    """
    data = load_settings()
    if key not in data:
        # 設定ファイルに預かっていない = env はアプリ管理外。触らない。
        return
    stored = data.pop(key)
    _write_settings(data)
    env_key = _ENV_KEY_MAP.get(key)
    if env_key is None:
        return
    # 設定由来の値がそのまま env に載っているときだけ取り消す (ユーザ由来の別値は残す)。
    if os.environ.get(env_key) == stored:
        os.environ.pop(env_key, None)


def _mask_hint(value: str) -> str:
    """末尾 4 文字のみのマスク表示 (``"…ab12"``)。4 文字未満のキーは全マスク (``"…"``)。

    キー本体を露出させないため、戻り値には ``value`` の先頭〜中間部分を一切含めない。
    """
    if len(value) < 4:
        return "…"
    return f"…{value[-4:]}"



def _read_dotenv_mp_key() -> str | None:
    """``.env`` の ``MATERIALS_PROJECT_API`` を読む (① ``mp.client`` の解決経路を再利用)。

    ``mp`` extra 未導入などで import できない場合は ``None`` (判定は「未設定」へ倒す)。
    """
    try:
        from ..mp.client import _read_dotenv_key
    except Exception:  # noqa: BLE001 — mp 未導入/循環などは「未設定」扱いで十分
        return None
    try:
        raw = _read_dotenv_key(_MP_API_KEY_ENV, None)
    except Exception:  # noqa: BLE001 — .env の読み取り失敗で GUI を落とさない
        return None
    return raw.strip() if isinstance(raw, str) and raw.strip() else None

def mp_api_key_status() -> dict[str, Any]:
    """GET /api/settings が返すマスク済み状態。優先順位: settings > env。

    :returns: ``{"set": bool, "hint": str|None, "source": "settings"|"env"|None}``。
        ``hint`` はキー本体を絶対に含まない (末尾数文字のマスクのみ)。
    """
    settings_value = load_settings().get("mp_api_key")
    if isinstance(settings_value, str) and settings_value:
        return {"set": True, "hint": _mask_hint(settings_value), "source": "settings"}
    env_value = os.environ.get(_MP_API_KEY_ENV)
    if env_value:
        return {"set": True, "hint": _mask_hint(env_value), "source": "env"}
    # 【.env フォールバック】: ``MPRestClient`` は env → .env の順で読む (mp/client.py) ため、
    #   ここで .env を見ないと「実際には MP が動くのに mp_available=false になり UI が
    #   IDENTIFY を disabled にする」誤判定が起きる (実機スモークで踏んだ)。判定は必ず
    #   実際にキーを解決する側と同じ順序にする。source は利用者視点で "env" に含める。
    dotenv_value = _read_dotenv_mp_key()
    if dotenv_value:
        return {"set": True, "hint": _mask_hint(dotenv_value), "source": "env"}
    return {"set": False, "hint": None, "source": None}


def apply_mp_api_key_to_env() -> None:
    """設定ファイルに MP キーがあればプロセス環境変数へ反映する (設定 > env の優先順位実現)。

    起動時 (``__main__.main``) と保存時 (``WorkbenchSession.save_settings``) の双方から呼ぶ契約。
    設定ファイルにキーが無い場合は env を変更しない (既存の env/`.env` 由来キーをそのまま使わせる —
    ``MPRestClient()`` 自身が env → .env の順で読む既存経路に委ねる, ① 非変更)。
    """
    value = load_settings().get("mp_api_key")
    if isinstance(value, str) and value:
        os.environ[_MP_API_KEY_ENV] = value


def mp_available() -> bool:
    """設定 or 環境変数に MP API キーがあるか (``gsasii_available`` と同じ流儀の事前判定)。"""
    return mp_api_key_status()["set"]
