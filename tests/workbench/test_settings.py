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


def test_clear_setting_also_removes_process_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MATERIALS_PROJECT_API", "env-leftover")
    settings.save_setting("mp_api_key", "sk-abcd1234")

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
