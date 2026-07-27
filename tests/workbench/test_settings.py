"""``tsumugin.workbench.settings`` の TDD テスト (MP アクセストークンのユーザ単位設定)。

対象: ``load_settings``/``save_setting``/``clear_setting``/``mp_api_key_status``/
``apply_mp_api_key_to_env``/``mp_available``。契約の絶対規則 (api-contract.md §アプリ設定):
API はキー本体を返さない・優先順位は設定 > 環境変数。

``Path.home()`` は ``tests/workbench/conftest.py`` の autouse fixture (``_isolated_home``) で
テスト専用ディレクトリへ隔離済み — 実ユーザーの ``~/.tsumugin/settings.json`` は汚染されない。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tsumugin.workbench import settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """MP API キー環境変数をテストごとに未設定へ揃える (実行環境の実キーに左右されないため)。"""
    monkeypatch.delenv("MATERIALS_PROJECT_API", raising=False)


# ---------------------------------------------------------------------------
# load_settings / save_setting / clear_setting
# ---------------------------------------------------------------------------


def test_load_settings_returns_empty_dict_when_file_missing():
    assert settings.load_settings() == {}


def test_save_then_load_roundtrips_value():
    settings.save_setting("mp_api_key", "sk-abcd1234")

    assert settings.load_settings()["mp_api_key"] == "sk-abcd1234"


def test_save_setting_creates_file_under_home_dot_tsumugin():
    settings.save_setting("mp_api_key", "sk-abcd1234")

    path = Path.home() / ".tsumugin" / "settings.json"
    assert path.exists()


def test_save_setting_overwrites_existing_value():
    settings.save_setting("mp_api_key", "sk-first111")
    settings.save_setting("mp_api_key", "sk-second22")

    assert settings.load_settings()["mp_api_key"] == "sk-second22"


def test_load_settings_tolerates_corrupt_json():
    path = Path.home() / ".tsumugin" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")

    assert settings.load_settings() == {}


def test_load_settings_tolerates_non_dict_json():
    path = Path.home() / ".tsumugin" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert settings.load_settings() == {}


def test_clear_setting_removes_key():
    settings.save_setting("mp_api_key", "sk-abcd1234")

    settings.clear_setting("mp_api_key")

    assert "mp_api_key" not in settings.load_settings()


def test_clear_setting_on_missing_key_is_noop():
    settings.clear_setting("mp_api_key")  # ファイル自体が無くても例外を投げない

    assert settings.load_settings() == {}


def test_clear_setting_removes_env_the_app_applied(monkeypatch: pytest.MonkeyPatch):
    """アプリが反映した値のみ env から取り消す (アプリ管理外の値は TestClearDoesNotStealUnmanagedEnv)。"""
    monkeypatch.delenv("MATERIALS_PROJECT_API", raising=False)
    settings.save_setting("mp_api_key", "sk-abcd1234")
    settings.apply_mp_api_key_to_env()
    assert os.environ.get("MATERIALS_PROJECT_API") == "sk-abcd1234"

    settings.clear_setting("mp_api_key")

    assert "MATERIALS_PROJECT_API" not in os.environ


# ---------------------------------------------------------------------------
# mp_api_key_status: マスク + 優先順位
# ---------------------------------------------------------------------------


def test_status_unset_everywhere():
    status = settings.mp_api_key_status()

    assert status == {"set": False, "hint": None, "source": None}


def test_status_hint_masks_all_but_last_four_chars():
    settings.save_setting("mp_api_key", "sk-verylongkeyab12")

    status = settings.mp_api_key_status()

    assert status["set"] is True
    assert status["source"] == "settings"
    assert status["hint"] == "…ab12"


def test_status_hint_fully_masks_short_key():
    settings.save_setting("mp_api_key", "ab")

    status = settings.mp_api_key_status()

    assert status["hint"] == "…"


def test_status_hint_never_contains_key_body():
    # 【返り値全体を str 化してもキー本体が含まれない】: マスク実装のミスで先頭側が漏れる
    #   類のリグレッションを検出する (契約「キー本体を返さない」の直接検証)。
    secret = "sk-super-secret-value-999"
    settings.save_setting("mp_api_key", secret)

    status = settings.mp_api_key_status()

    assert secret not in str(status)
    assert secret[:-4] not in str(status)


def test_status_source_env_when_only_env_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MATERIALS_PROJECT_API", "env-key-value9")

    status = settings.mp_api_key_status()

    assert status == {"set": True, "hint": "…lue9", "source": "env"}


def test_status_prefers_settings_over_env(monkeypatch: pytest.MonkeyPatch):
    # 【優先順位: 設定 > env】: 両方に値がある場合 settings 側が勝つ (契約の絶対規則)。
    monkeypatch.setenv("MATERIALS_PROJECT_API", "env-key-value9")
    settings.save_setting("mp_api_key", "settings-key-abcd")

    status = settings.mp_api_key_status()

    assert status["source"] == "settings"
    assert status["hint"] == "…abcd"


# ---------------------------------------------------------------------------
# apply_mp_api_key_to_env / mp_available
# ---------------------------------------------------------------------------


def test_apply_mp_api_key_to_env_sets_process_env():
    settings.save_setting("mp_api_key", "sk-from-settings")

    settings.apply_mp_api_key_to_env()

    assert os.environ.get("MATERIALS_PROJECT_API") == "sk-from-settings"


def test_apply_mp_api_key_to_env_overrides_existing_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MATERIALS_PROJECT_API", "old-env-value")
    settings.save_setting("mp_api_key", "new-settings-value")

    settings.apply_mp_api_key_to_env()

    assert os.environ["MATERIALS_PROJECT_API"] == "new-settings-value"


def test_apply_mp_api_key_to_env_noop_when_settings_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MATERIALS_PROJECT_API", "keep-me")

    settings.apply_mp_api_key_to_env()

    assert os.environ.get("MATERIALS_PROJECT_API") == "keep-me"


def test_mp_available_false_when_unset():
    assert settings.mp_available() is False


def test_mp_available_true_from_settings():
    settings.save_setting("mp_api_key", "sk-abcd1234")

    assert settings.mp_available() is True


def test_mp_available_true_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MATERIALS_PROJECT_API", "env-value")

    assert settings.mp_available() is True


class TestDotenvFallbackAvailability:
    """`.env` のキーも「設定済み」と判定する (実機スモークで踏んだ誤判定の回帰)。

    ``MPRestClient`` は env → `.env` の順でキーを解決する (mp/client.py)。判定側が `.env` を
    見ないと「実際には MP が動くのに mp_available=false → UI が IDENTIFY を disabled」と
    いう**使えるのに使わせない**誤判定になる。判定は必ず解決側と同じ順序にする。
    """

    def test_dotenv_key_makes_mp_available(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("MATERIALS_PROJECT_API", raising=False)
        monkeypatch.setattr(
            settings, "_read_dotenv_mp_key", lambda: "DOTENV_ONLY_KEY_abcd"
        )
        status = settings.mp_api_key_status()
        assert status["set"] is True
        assert status["source"] == "env"
        assert status["hint"] == "…abcd"
        assert settings.mp_available() is True

    def test_dotenv_key_does_not_leak_in_status(self, tmp_path, monkeypatch) -> None:
        secret = "DOTENV_ONLY_KEY_abcd"
        monkeypatch.delenv("MATERIALS_PROJECT_API", raising=False)
        monkeypatch.setattr(settings, "_read_dotenv_mp_key", lambda: secret)
        text = str(settings.mp_api_key_status())
        assert secret not in text and secret[:-4] not in text

    def test_settings_file_still_wins_over_dotenv(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("MATERIALS_PROJECT_API", raising=False)
        monkeypatch.setattr(settings, "_read_dotenv_mp_key", lambda: "DOTENV_KEY_zzzz")
        settings.save_setting("mp_api_key", "SETTINGS_KEY_wxyz")
        status = settings.mp_api_key_status()
        assert status["source"] == "settings"
        assert status["hint"] == "…wxyz"

    def test_no_key_anywhere_reports_unset(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("MATERIALS_PROJECT_API", raising=False)
        monkeypatch.setattr(settings, "_read_dotenv_mp_key", lambda: None)
        assert settings.mp_available() is False


class TestClearDoesNotStealUnmanagedEnv:
    """CLEAR はアプリが預かっていない env を壊さない (レビュー指摘の実害)。

    ユーザがシェルで export した ``MATERIALS_PROJECT_API`` を CLEAR が消すと、アプリが
    一度も預かっていない資格情報を奪い MP 機能がプロセス再起動まで全滅する。
    """

    def test_clear_keeps_user_exported_env_when_never_saved(self, monkeypatch) -> None:
        monkeypatch.setenv("MATERIALS_PROJECT_API", "USER_EXPORTED_KEY_abcd")
        settings.clear_setting("mp_api_key")  # アプリは一度も保存していない
        assert os.environ.get("MATERIALS_PROJECT_API") == "USER_EXPORTED_KEY_abcd"
        assert settings.mp_available() is True

    def test_clear_removes_only_the_value_the_app_applied(self, monkeypatch) -> None:
        monkeypatch.delenv("MATERIALS_PROJECT_API", raising=False)
        settings.save_setting("mp_api_key", "APP_MANAGED_KEY_wxyz")
        settings.apply_mp_api_key_to_env()
        assert os.environ.get("MATERIALS_PROJECT_API") == "APP_MANAGED_KEY_wxyz"
        settings.clear_setting("mp_api_key")
        assert "MATERIALS_PROJECT_API" not in os.environ

    def test_clear_keeps_env_that_differs_from_stored_value(self, monkeypatch) -> None:
        settings.save_setting("mp_api_key", "APP_MANAGED_KEY_wxyz")
        monkeypatch.setenv("MATERIALS_PROJECT_API", "USER_OVERRODE_LATER_1234")
        settings.clear_setting("mp_api_key")
        assert os.environ.get("MATERIALS_PROJECT_API") == "USER_OVERRODE_LATER_1234"
