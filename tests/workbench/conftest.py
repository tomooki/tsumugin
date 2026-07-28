"""workbench テスト共通 fixture。

【背景】: recent プロジェクト一覧は ``Path.home()/.tsumugin`` に書かれる。個別テストの
monkeypatch 漏れが 1 つでもあると**実ユーザーの home を汚す** (実害: pytest tmp パスが
実 ``workbench_recent.json`` に混入し Welcome 画面の recent に露出した)。テスト側の規律に
依存せず、autouse fixture で workbench テスト全体の home を tmp へ隔離する。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """全 workbench テストで ``Path.home()`` をテスト専用ディレクトリへ差し替える。"""
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    return fake_home


@pytest.fixture(autouse=True)
def _isolated_dotenv_mp_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` の MP キーをテストから隔離する (既定は「未設定」)。

    【背景】: `settings.mp_api_key_status` は ``MPRestClient`` と同じ順序で env → `.env` を
    見る。隔離しないと**開発者のリポジトリに .env があるかどうかでテスト結果が変わる**
    (実際に「未設定」を期待するテストが実 .env を拾って落ちた)。`.env` 由来の挙動を検証したい
    テストは自分で ``monkeypatch.setattr(settings, "_read_dotenv_mp_key", ...)`` を上書きする。
    """
    from tsumugin.workbench import settings as _settings

    monkeypatch.setattr(_settings, "_read_dotenv_mp_key", lambda: None)


@pytest.fixture(autouse=True)
def _pretend_gsas_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """`gsasii_available()` を **True** に固定する (GSAS-II 不在環境でも GUI ロジックを回す)。

    【背景】: `session._guard_gsas_available` は Tier1 sidecar 用の意図的な preflight で、
    GSAS-II が import できない環境では refine/multistart/sequential の起動を 422
    (`GSASUnavailableError`) に縮退させる (`desktop/README.md`)。この判定は**実環境の import 可否**
    を見るため、隔離しないと workbench テストの合否が「その機械に GSAS-II が入っているか」で
    変わる — 開発機には常に入っているので**ローカルでは不可視**だった。

    実害 (2026-07-28, CI 初回): GitHub Actions (GSAS-II 不在) で fast tier
    (`-m "not gsas"`) が **49 failed** になり、うち 42 件がこの preflight で 202→422 に
    落ちたものだった。`-m "not gsas"` は「GSAS 非依存」を意味するはずなのに、実際は
    「GSAS が入っている前提の高速ティア」だった (上の 2 fixture が隔離した home/.env と
    同じ「環境で結果が変わる」病理)。

    ここで True に固定することで **fast tier が本当に GSAS 非依存**になり、CI が GUI ロジックまで
    カバーできる。**不在パスを検証したいテストは自分で `lambda: False` に上書きする**
    (autouse より後に適用されるので勝つ; 既存の
    `test_refine_job_returns_gsas_unavailable_when_missing` 等がその形)。

    ⚠ これは「GSAS があるフリ」なので、**実 GSAS 精密化の検証にはならない** — それは
    `@pytest.mark.gsas` の gated スイート (ローカル実行) の担当である。
    """
    from tsumugin.workbench import session as _session

    monkeypatch.setattr(_session, "gsasii_available", lambda: True)
