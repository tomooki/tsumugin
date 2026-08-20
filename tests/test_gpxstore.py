"""`tsumugin.gpxstore` — 成果物 (.gpx / TOPAS プロジェクト) の保存先解決・命名・索引。

**規定**: 全解析で成果物を保存する (2026-08-20 ユーザー決定)。既定の置き場所は
**観測データ隣接** ``<data_dir>/tsumugin_gpx/<run_id>/``、粒度は **精密化 1 回 = 1 成果物**
(フレーム・棄却トライアル・前方/後方パス・マルチスタートの各開始点も 1 つずつ)。

本モジュールは**置き場所と名前だけ**を決める。物理 (精密化の入力) には一切影響しない。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tsumugin.gpxstore import (
    DISABLED,
    ENV_VAR,
    GpxContext,
    ManifestEntry,
    plan_artifact,
    read_manifest,
    record_artifact,
    resolve_run_dir,
    sanitize_label,
)

# ---------------------------------------------------------------------------
# 保存先の解決 (既定はデータ隣接・env で上書き・"none" で無効化)
# ---------------------------------------------------------------------------


def test_default_root_is_next_to_the_data_file(tmp_path, monkeypatch):
    """既定の保存先は観測データ隣接 ``<data_dir>/tsumugin_gpx/<run_id>/``。"""
    monkeypatch.delenv(ENV_VAR, raising=False)
    data = tmp_path / "raw" / "frame000.xrdml"
    data.parent.mkdir(parents=True)
    data.write_text("x", encoding="utf-8")

    run_dir = resolve_run_dir(str(data))

    assert run_dir is not None
    assert Path(run_dir).parent == tmp_path / "raw" / "tsumugin_gpx"
    assert Path(run_dir).is_dir()


def test_env_var_overrides_the_default_root(tmp_path, monkeypatch):
    """``TSUMUGIN_GPX_DIR`` を指定するとそこが根になる (データ隣接に書けない運用の逃げ道)。"""
    root = tmp_path / "elsewhere"
    monkeypatch.setenv(ENV_VAR, str(root))
    data = tmp_path / "raw" / "frame000.xrdml"
    data.parent.mkdir(parents=True)

    run_dir = resolve_run_dir(str(data))

    assert run_dir is not None
    assert Path(run_dir).parent == root


def test_env_none_disables_saving(tmp_path, monkeypatch):
    """``TSUMUGIN_GPX_DIR=none`` で保存を止められる (ディスクを使わせない明示の逃げ道)。"""
    monkeypatch.setenv(ENV_VAR, DISABLED)
    data = tmp_path / "frame000.xrdml"

    assert resolve_run_dir(str(data)) is None


def test_explicit_dir_beats_the_env_var(tmp_path, monkeypatch):
    """明示指定は env より強い (呼び出し側の指定を環境に上書きさせない)。"""
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "env"))
    explicit = tmp_path / "explicit"
    data = tmp_path / "frame000.xrdml"

    run_dir = resolve_run_dir(str(data), explicit_dir=str(explicit))

    assert run_dir is not None and Path(run_dir).parent == explicit


def test_explicit_dir_beats_env_none(tmp_path, monkeypatch):
    """明示指定は ``none`` 無効化よりも強い (頼まれた保存を環境変数で黙って捨てない)。"""
    monkeypatch.setenv(ENV_VAR, DISABLED)
    explicit = tmp_path / "explicit"

    run_dir = resolve_run_dir(str(tmp_path / "f.xye"), explicit_dir=str(explicit))

    assert run_dir is not None and Path(run_dir).parent == explicit


def test_run_dirs_do_not_collide_across_runs(tmp_path, monkeypatch):
    """同じ根に 2 回解決しても**別の run ディレクトリ**になる (P2: 前の実行を上書きしない)。"""
    monkeypatch.delenv(ENV_VAR, raising=False)
    data = tmp_path / "frame000.xrdml"

    first = resolve_run_dir(str(data), now="20260820-134501")
    second = resolve_run_dir(str(data), now="20260820-134501")

    assert first != second
    assert Path(first).is_dir() and Path(second).is_dir()


def test_unwritable_data_dir_falls_back_and_says_so(tmp_path, monkeypatch):
    """データ隣接に書けないときは temp へ退避し**理由を返す** (黙って保存を諦めない)。

    750 フレームの系列が「読み取り専用の共有ディスクにデータがある」だけで落ちるのは
    受け入れられない。一方、黙って保存しないのは「規定で保存する」の裏切りなので、
    退避したことを呼び出し側が ledger/警告に載せられる形で返す。
    """
    monkeypatch.delenv(ENV_VAR, raising=False)
    real_makedirs = os.makedirs
    blocked = str(tmp_path)

    def _boom(name, *a, **k):
        if str(name).startswith(blocked):
            raise PermissionError("read-only")
        return real_makedirs(name, *a, **k)

    monkeypatch.setattr(os, "makedirs", _boom)
    run_dir, reason = resolve_run_dir(str(tmp_path / "f.xye"), report_fallback=True)

    assert run_dir is not None and Path(run_dir).is_dir()
    assert "PermissionError" in reason


# ---------------------------------------------------------------------------
# 命名 (人が読んで「どの精密化か」が分かること)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("delta-CaTeO3", "delta-CaTeO3"),
        ("Ca/Te O3", "Ca-Te-O3"),
        ("../../etc/passwd", "etc-passwd"),
        ("", "unnamed"),
        ("a" * 80, "a" * 60),
    ],
)
def test_sanitize_label(raw, expected):
    """ラベルはパス安全な文字だけに畳む (相名や CIF 名がそのままファイル名になるため)。"""
    assert sanitize_label(raw) == expected


def test_artifact_names_are_self_describing(tmp_path):
    """ファイル名だけで役割が分かる (フレーム番号・トライアル候補名・区間/方向)。"""
    ctx = GpxContext(run_dir=str(tmp_path))
    frame = plan_artifact(["/data/frame0180.xrdml"], ctx.child(role="frame", index=180))
    trial = plan_artifact(
        ["/data/frame0180.xrdml"],
        ctx.child(role="trial", index=180, label="delta-CaTeO3"),
    )
    back = plan_artifact(["/data/f5.xye"], ctx.child(role="backward", index=5, label="seg01"))

    assert Path(frame.path).name == "f0180_frame.gpx"
    assert Path(trial.path).name == "f0180_trial_delta-CaTeO3.gpx"
    assert Path(back.path).name == "f0005_backward_seg01.gpx"


def test_plan_without_context_uses_the_data_stem(tmp_path, monkeypatch):
    """文脈なしの単発解析でもデータ名から決まる (どのデータの精密化か分かる)。"""
    monkeypatch.delenv(ENV_VAR, raising=False)
    data = tmp_path / "PbSO4.fxye"
    data.write_text("x", encoding="utf-8")

    plan = plan_artifact([str(data)], None)

    assert plan.path is not None and Path(plan.path).name == "PbSO4.gpx"


def test_plan_never_overwrites_an_existing_artifact(tmp_path):
    """既存ファイルは上書きしない (P2 非破壊性: 保存した成果物を後の実行が消さない)。"""
    ctx = GpxContext(run_dir=str(tmp_path))
    first = plan_artifact(["/data/a.xye"], ctx)
    Path(first.path).write_text("gpx", encoding="utf-8")

    second = plan_artifact(["/data/a.xye"], ctx)

    assert second.path != first.path
    assert Path(first.path).read_text(encoding="utf-8") == "gpx"


def test_disabled_context_plans_no_path(tmp_path):
    """``enabled=False`` の文脈では保存先を作らない (opt-out が効くこと)。"""
    plan = plan_artifact(["/data/a.xye"], GpxContext(run_dir=str(tmp_path), enabled=False))

    assert plan.path is None
    assert list(tmp_path.iterdir()) == []


def test_topas_project_uses_a_directory_name(tmp_path):
    """TOPAS は .gpx ではなくプロジェクト**ディレクトリ**なので拡張子なしで計画する。"""
    ctx = GpxContext(run_dir=str(tmp_path))
    plan = plan_artifact(["/data/a.xye"], ctx.child(role="frame", index=3), ext="")

    assert Path(plan.path).name == "f0003_frame"


# ---------------------------------------------------------------------------
# 索引 (manifest.jsonl) — 「全部保存」は「後から探せる」までが要件
# ---------------------------------------------------------------------------


def test_manifest_is_append_only_and_readable(tmp_path):
    """manifest は追記のみ (P2)。役割/Rwp/相/データ元が 1 行 1 成果物で残る。"""
    record_artifact(
        str(tmp_path),
        ManifestEntry(
            path=str(tmp_path / "f0000_frame.gpx"),
            role="frame",
            label="",
            index=0,
            data_paths=("/data/f0.xrdml",),
            phases=("alpha",),
            rwp=13.4,
            gof=1.44,
            backend="gsasii",
        ),
    )
    record_artifact(
        str(tmp_path),
        ManifestEntry(
            path=str(tmp_path / "f0000_trial_delta.gpx"),
            role="trial",
            label="delta",
            index=0,
            data_paths=("/data/f0.xrdml",),
            phases=("alpha", "delta"),
            rwp=30.19,
            gof=2.0,
            backend="gsasii",
        ),
    )

    entries = read_manifest(str(tmp_path))

    assert [e["role"] for e in entries] == ["frame", "trial"]
    assert entries[1]["label"] == "delta"
    assert entries[0]["rwp"] == pytest.approx(13.4)
    # 生の行が JSON Lines であること (外部ツール/後日の grep で読める形)
    lines = (tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(json.loads(ln) for ln in lines)


def test_manifest_entry_rejects_non_finite_numbers(tmp_path):
    """inf/NaN は JSON に落とさず null にする (json.dumps allow_nan=False 安全; ② 境界と同じ規律)。"""
    record_artifact(
        str(tmp_path),
        ManifestEntry(
            path=str(tmp_path / "x.gpx"),
            role="frame",
            label="",
            index=0,
            data_paths=(),
            phases=(),
            rwp=float("inf"),
            gof=float("nan"),
            backend="gsasii",
        ),
    )

    entry = read_manifest(str(tmp_path))[0]
    assert entry["rwp"] is None and entry["gof"] is None


def test_read_manifest_of_missing_dir_is_empty(tmp_path):
    """索引が無い (保存無効/未実行) ディレクトリは空リスト — 例外にしない。"""
    assert read_manifest(str(tmp_path / "nope")) == []


# ---------------------------------------------------------------------------
# 方針関数 (両エンジン共通): 明示 > 無効化 > 既定保存
# ---------------------------------------------------------------------------


def test_plan_output_keeps_explicit_path_verbatim(tmp_path):
    """``keep=`` の明示パスはそのまま使う (workbench 等の既存呼び出しの非回帰)。"""
    from tsumugin.gpxstore import plan_output

    target = tmp_path / "workbench_out" / "refined.gpx"
    plan = plan_output(["/data/a.xye"], keep=str(target))

    assert plan.path == str(target)
    # 索引を書かない印: 明示パスは呼び出し側の取り決めなので run ディレクトリを名乗らない
    assert plan.run_dir == ""


def test_plan_output_saves_by_default(tmp_path, monkeypatch):
    """★規定: 何も指定しなければ**保存する** (これが本変更の中心)。"""
    from tsumugin.gpxstore import plan_output

    monkeypatch.delenv(ENV_VAR, raising=False)
    data = tmp_path / "PbSO4.fxye"
    data.write_text("x", encoding="utf-8")

    plan = plan_output([str(data)])

    assert plan.path is not None
    assert Path(plan.path).parent.parent == tmp_path / "tsumugin_gpx"
    assert plan.run_dir  # 索引を書く先を名乗る


def test_plan_output_save_false_is_the_opt_out(tmp_path):
    """``save=False`` で完全に無効化できる (ディスクを使わせない明示の逃げ道)。"""
    from tsumugin.gpxstore import plan_output

    plan = plan_output([str(tmp_path / "a.xye")], save=False)

    assert plan.path is None


def test_plan_output_uses_the_ambient_context_for_naming(tmp_path, monkeypatch):
    """ambient 文脈があれば run ディレクトリと名前をそこから採る (系列の全成果物が 1 か所に集まる)。"""
    from tsumugin.gpxstore import gpx_context, plan_output

    monkeypatch.delenv(ENV_VAR, raising=False)
    run = tmp_path / "series"
    run.mkdir()
    with gpx_context(GpxContext(run_dir=str(run), role="frame", index=7)):
        plan = plan_output(["/data/frame007.xrdml"])

    assert Path(plan.path).name == "f0007_frame.gpx"
    assert Path(plan.path).parent == run
