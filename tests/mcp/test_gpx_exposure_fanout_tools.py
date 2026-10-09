"""★規定「全解析で gpx を保存する」の ② 露出 — **1 呼び出しで N 回精密化する** 2 ツール。

`compare_structure_models` (モデル比較の各バリアント) と `repair_frames` (修復の各試行) は
① 側では規定どおり保存される (`autorietveld.compare.compare_models` /
`insitu.repair.repair_isolated` が `group_context` で run ディレクトリを 1 つ決める) のに、
② が ``gpx_dir`` / ``save_gpx`` を受けていなかった。③ は JSON しか送れないので、

- 規定の**唯一の** opt-out (``save_gpx=False``) が届かない — 止めたつもりでデータ隣接へ書き続ける
- 明示 ``gpx_dir`` が届かない — 頼んだ場所ではなく env → データ隣接へ散らばる

どちらも返り値の Rwp/BIC には現れない (精密化結果は同じなので)。ここでは実 GSAS を回さず、
② の ``runner`` 注入シーム (① の既定 runner の代わりに呼ばれる) で**実際に効いた文脈**
(`gpxstore.active_context()` = エンジンが保存先を決めるのに読むもの) と引数を記録する。

既存の単発/系列/探索経路は `test_gpx_exposure.py` が見ている (このファイルは別の 2 ツール)。
"""

from __future__ import annotations

import os
import tempfile

import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.gpxstore import ENV_VAR, active_context
from tsumugin.mcp.compare_tools import compare_structure_models
from tsumugin.mcp.operando_diag_tools import repair_frames

_P = {"structure_path": "a.cif", "phase_name": "ph"}
_P2 = {"structure_path": "b.cif", "phase_name": "ow"}


def _gpx_path_from_context(data_stem: str) -> str:
    """エンジンと同じ規則で「この文脈なら保存される場所」を返す ("" = 保存されない)。"""
    ctx = active_context()
    if ctx is None or not ctx.enabled or not ctx.run_dir:
        return ""
    return os.path.join(ctx.run_dir, ctx.stem(data_stem=data_stem) + ".gpx")


def _result(rwp: float, *, n_phases: int = 1, valid: bool = True, gpx_path: str = ""):
    return AutoRietveldResult(
        stage_results=(
            StageResult(
                label="final", rwp=rwp, gof=rwp / 6.0, n_params=10 + 12 * n_phases,
                converged=True,
            ),
        ),
        final_rwp=rwp,
        final_gof=rwp / 6.0,
        refined_cells={"ph": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=valid),
        phase_fractions={"ph": 1.0},
        n_obs=2000,
        gpx_path=gpx_path,
    )


def _make_unwritable(monkeypatch, tmp_path) -> str:
    """根に run ディレクトリを作れない状況を作り、一時領域を tmp_path 配下へ向ける。"""

    def unwritable(root, base):
        raise PermissionError(13, "read-only", root)

    monkeypatch.setattr("tsumugin.gpxstore._make_unique_dir", unwritable)
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_root))
    return str(tmp_root)


# ---------------------------------------------------------------------------
# compare_structure_models — モデル比較の各バリアント
# ---------------------------------------------------------------------------


def _hist_in(tmp_path) -> dict:
    data = tmp_path / "data" / "d.xye"
    data.parent.mkdir(parents=True, exist_ok=True)
    return {
        "data_path": str(data),
        "instrument_path": "i.instprm",
        "radiation": "xray_lab",
        "geometry": "bragg_brentano",
        "data_format": "XYE",
    }


_VARIANTS = [
    {"name": "model5", "phases": [_P]},
    # 母数が多く Rwp は低いが物理妥当性を落とす = **棄却されるモデル**。その fit こそ残したい
    {"name": "model6", "phases": [_P, _P2]},
]


def _compare_recorder() -> tuple[list[dict], object]:
    """runner 注入シームに差す記録スタブ (① `compare_models` が各バリアントで呼ぶ)。"""
    calls: list[dict] = []

    def runner(histograms, phases, **kwargs):
        calls.append(
            {
                "gpx_dir": kwargs.get("gpx_dir", "<absent>"),
                "save_gpx": kwargs.get("save_gpx", "<absent>"),
                "ctx": active_context(),
            }
        )
        n = len(phases)
        return _result(
            8.0 if n == 2 else 11.0, n_phases=n, valid=(n == 1),
            gpx_path=_gpx_path_from_context("d"),
        )

    return calls, runner


def test_compare_honors_the_save_gpx_opt_out(tmp_path, monkeypatch):
    """★``save_gpx=False`` (規定の**唯一の** opt-out) が全バリアントへ届く。

    非トートロジー: 届かないと ① は既定どおりデータ隣接へ run ディレクトリを作って保存する —
    ΔBIC は同じなので「止めたつもりで書き続けている」ことに誰も気づけない。エンジンに届いた
    引数と文脈の両方を見る (文脈が enabled のままだと、文脈を読む runner が保存してしまう)。
    """
    # env を差したままだと env の根が優先され、データ隣接の不在は何も確かめない
    monkeypatch.delenv(ENV_VAR, raising=False)
    calls, runner = _compare_recorder()

    out = compare_structure_models([_hist_in(tmp_path)], _VARIANTS, runner=runner, save_gpx=False)

    assert "error" not in out, out.get("error")
    assert len(calls) == 2, "バリアントが全部走っていない (テストの前提崩れ)"
    for call in calls:
        assert call["save_gpx"] is False, call
        assert call["ctx"] is not None and call["ctx"].enabled is False, call
    assert not (tmp_path / "data" / "tsumugin_gpx").exists()
    assert [s["gpx_path"] for s in out["scores"]] == ["", ""]


def test_compare_honors_an_explicit_gpx_dir(tmp_path, monkeypatch):
    """★明示 ``gpx_dir`` が全バリアントの置き場所になり (env より強い)、1 実行 = 1 run。

    非トートロジー: 届かないと ① は env → データ隣接で根を決める — 成果物は**保存はされる**
    ので「保存されたか」だけを見るテストでは落ちない。どこに置かれたかを見る。
    """
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "env-root"))
    chosen = tmp_path / "chosen"
    calls, runner = _compare_recorder()

    out = compare_structure_models(
        [_hist_in(tmp_path)], _VARIANTS, runner=runner, gpx_dir=str(chosen)
    )

    assert "error" not in out, out.get("error")
    run_dirs = set()
    for call in calls:
        assert call["gpx_dir"] == str(chosen), call
        assert call["save_gpx"] is True, call
        ctx = call["ctx"]
        assert ctx is not None and ctx.enabled, call
        assert os.path.dirname(ctx.run_dir) == str(chosen), call
        run_dirs.add(ctx.run_dir)
    assert len(run_dirs) == 1, run_dirs
    assert not (tmp_path / "env-root").exists()


def test_compare_returns_a_handle_to_every_variant(tmp_path, monkeypatch):
    """★**棄却されたモデルも含めて**各バリアントの成果物パスが ``scores[]`` に載る。

    非トートロジー: 保存の目的は「棄却モデルがどう壊れていたか (実測 NaCuHCF model5 は
    Na>1 / O<0 に発散) を開いて確かめる」ことであり、② が ``best`` の名前と ΔBIC しか返さないと
    ③ はその fit に届かない (run ディレクトリの場所すら返らない)。
    """
    calls, runner = _compare_recorder()

    out = compare_structure_models(
        [_hist_in(tmp_path)], _VARIANTS, runner=runner, gpx_dir=str(tmp_path / "chosen")
    )

    by_name = {s["name"]: s for s in out["scores"]}
    assert out["best"] == "model5"  # model6 は BIC 有利だが妥当性で棄却される
    assert os.path.basename(by_name["model5"]["gpx_path"]) == "model_model5.gpx"
    assert os.path.basename(by_name["model6"]["gpx_path"]) == "model_model6.gpx"
    # 各スコアの行は**その**バリアントの fit を指す (BIC 昇順への並べ替えで取り違えない)
    assert {s["gpx_path"] for s in out["scores"]} == {
        os.path.join(calls[0]["ctx"].run_dir, "model_model5.gpx"),
        os.path.join(calls[0]["ctx"].run_dir, "model_model6.gpx"),
    }


def test_compare_says_when_artifacts_fell_back_to_temp(tmp_path, monkeypatch):
    """★頼まれた ``gpx_dir`` に書けず一時領域へ退避したら、返り値の ``warnings`` で言う。

    非トートロジー: 退避理由は run ディレクトリを解決した入口 (`compare_models`) でしか分からない
    — エンジンは解決済みの文脈を受け取るので ``m7_gpx_fallback`` を書かない。入口が理由を捨てると、
    ③ は「指定した場所に保存された」と読んだまま成果物は %TEMP% に置かれる (設計 §5)。
    """
    tmp_root = _make_unwritable(monkeypatch, tmp_path)
    _, runner = _compare_recorder()

    out = compare_structure_models(
        [_hist_in(tmp_path)], _VARIANTS, runner=runner, gpx_dir=str(tmp_path / "chosen")
    )

    assert "error" not in out, out.get("error")
    assert any("一時領域へ退避" in w for w in out["warnings"]), out["warnings"]
    assert all(s["gpx_path"].startswith(tmp_root) for s in out["scores"]), out["scores"]


# ---------------------------------------------------------------------------
# repair_frames — 修復の各試行 (採用されたものも棄却されたものも)
# ---------------------------------------------------------------------------


def _frames_in(tmp_path, n: int = 4) -> list[dict]:
    (tmp_path / "data").mkdir(exist_ok=True)
    return [
        {"data_path": str(tmp_path / "data" / f"f{i}.xye"), "axis_value": float(i),
         "data_format": "XYE"}
        for i in range(n)
    ]


def _series(frames: list[dict], rwps: list[float]) -> dict:
    return {
        "frames": [
            {
                "frame_index": i, "axis_value": f["axis_value"], "data_path": f["data_path"],
                "rwp": rwp, "gof": 1.1,
                "refined_cells": {"ph": [10.0, 10.0, 10.0, 90.0, 90.0, 90.0]},
                "phase_fractions": {"ph": 1.0}, "phase_names": ["ph"], "gpx_path": "",
            }
            for i, (f, rwp) in enumerate(zip(frames, rwps))
        ],
        "phase_names": ["ph"],
    }


#: フレーム 1 だけ Rwp が跳ねた系列 (両隣 0/2 は良好 → 左右とも近傍 warm-start を試せる)。
_SPIKE = [8.0, 20.0, 8.1, 8.2]


def _repair_recorder(rwp_after: float) -> tuple[list[dict], object]:
    """修復試行の runner (`insitu.engine.Runner` 同型) に差す記録スタブ。"""
    calls: list[dict] = []

    def runner(frame, phases, initial_cells, initial_fractions=None):
        ctx = active_context()
        calls.append({"ctx": ctx})
        return _result(rwp_after, gpx_path=_gpx_path_from_context("f"))

    return calls, runner


def test_repair_honors_the_save_gpx_opt_out(tmp_path, monkeypatch):
    """★``save_gpx=False`` が全修復試行 (左右とも) へ届き、どこにも書かない。

    非トートロジー: 修復の runner は 4 引数プロトコルなので保存指定は**引数では運べない**
    (設計 §4) — ① が入口で作る文脈 (`group_context`) が唯一の経路。② がそこへ渡さないと
    ① は既定 (env → データ隣接) で run ディレクトリを作り、全試行を保存する。
    """
    monkeypatch.delenv(ENV_VAR, raising=False)
    frames = _frames_in(tmp_path)
    calls, runner = _repair_recorder(rwp_after=8.0)

    out = repair_frames(
        _series(frames, _SPIKE), frames, [_P], target_frames=[1], runner=runner,
        save_gpx=False,
    )

    assert "error" not in out, out.get("error")
    assert len(calls) == 2, "左右の修復試行が走っていない (テストの前提崩れ)"
    for call in calls:
        assert call["ctx"] is not None and call["ctx"].enabled is False, call
    assert not (tmp_path / "data" / "tsumugin_gpx").exists()
    assert out["gpx_dir"] == ""
    assert out["repairs"][0]["gpx_path"] == ""


def test_repair_honors_an_explicit_gpx_dir(tmp_path, monkeypatch):
    """★明示 ``gpx_dir`` が全修復試行の置き場所になり、1 実行 = 1 run ディレクトリ。"""
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "env-root"))
    chosen = tmp_path / "chosen"
    frames = _frames_in(tmp_path)
    calls, runner = _repair_recorder(rwp_after=8.0)

    out = repair_frames(
        _series(frames, _SPIKE), frames, [_P], target_frames=[1], runner=runner,
        gpx_dir=str(chosen),
    )

    assert "error" not in out, out.get("error")
    run_dirs = {call["ctx"].run_dir for call in calls if call["ctx"] is not None}
    assert len(calls) == 2 and len(run_dirs) == 1, calls
    (run_dir,) = run_dirs
    assert os.path.dirname(run_dir) == str(chosen)
    assert not (tmp_path / "env-root").exists()
    # 実際の置き場所が返る (索引 manifest.jsonl と**採られなかった側**の試行はここにある)
    assert out["gpx_dir"] == run_dir


def test_repair_returns_a_handle_to_rejected_trials(tmp_path, monkeypatch):
    """★**棄却された修復**の fit にも返り値から届く (ledger 行の ``gpx_path``)。

    非トートロジー: 採用されなかったフレームは ``needs_model_revision`` (番号だけ) に入り、
    ``repairs[]`` には現れない。修復試行を保存する理由は「warm-start でなぜ直らなかったか」を
    開いて確かめるためなので (`insitu.repair` の規定コメント)、棄却行にパスが無いと
    保存した意味が無い。相追加トライアル (`m9_phaseid_trial`) と同じく台帳の行に載せる。
    """
    frames = _frames_in(tmp_path)
    _, runner = _repair_recorder(rwp_after=25.0)  # 元 (20.0) より悪い → 棄却

    out = repair_frames(
        _series(frames, _SPIKE), frames, [_P], target_frames=[1], runner=runner,
        gpx_dir=str(tmp_path / "chosen"),
    )

    assert out["repairs"] == [] and out["needs_model_revision"] == [1], out
    (row,) = [e for e in out["ledger_entries"] if e["kind"] == "insitu_repair_rejected"]
    assert os.path.basename(row["gpx_path"]) == f"f0001_repair_{row['source']}.gpx", row
    assert os.path.dirname(row["gpx_path"]) == out["gpx_dir"]


def test_repair_adopted_row_matches_the_repair_handle(tmp_path, monkeypatch):
    """採用行の台帳 ``gpx_path`` は ``repairs[].gpx_path`` と同じ fit を指す (数字とパスが同じ行)。"""
    frames = _frames_in(tmp_path)
    _, runner = _repair_recorder(rwp_after=8.0)

    out = repair_frames(
        _series(frames, _SPIKE), frames, [_P], target_frames=[1], runner=runner,
        gpx_dir=str(tmp_path / "chosen"),
    )

    (row,) = [e for e in out["ledger_entries"] if e["kind"] == "insitu_repair_adopted"]
    assert row["gpx_path"] == out["repairs"][0]["gpx_path"] != ""


def test_repair_says_when_artifacts_fell_back_to_temp(tmp_path, monkeypatch):
    """★頼まれた ``gpx_dir`` に書けず一時領域へ退避したら、台帳 (``ledger_entries``) で言う。

    非トートロジー: 退避理由は `repair_isolated` の入口でしか分からない (runner/エンジンは
    解決済みの文脈を受け取る)。系列 (`m9_gpx_fallback`) と同じ台帳の行で返す (設計 §5)。
    """
    tmp_root = _make_unwritable(monkeypatch, tmp_path)
    frames = _frames_in(tmp_path)
    _, runner = _repair_recorder(rwp_after=8.0)

    out = repair_frames(
        _series(frames, _SPIKE), frames, [_P], target_frames=[1], runner=runner,
        gpx_dir=str(tmp_path / "chosen"),
    )

    assert "error" not in out, out.get("error")
    fallbacks = [e for e in out["ledger_entries"] if e["kind"] == "m9_gpx_fallback"]
    assert len(fallbacks) == 1 and "一時領域へ退避" in fallbacks[0]["reason"], out["ledger_entries"]
    assert out["gpx_dir"].startswith(tmp_root)


def test_repair_with_nothing_to_repair_leaves_no_run_directory(tmp_path, monkeypatch):
    """修復対象が無い (自動検出で不連続ゼロ) なら run ディレクトリを作らない。

    ③ は健全な系列にも診断として `repair_frames` を呼ぶ。そのたびにデータ隣接へ空の
    ``run-<日時>/`` を撒くのは「後から探せる」(設計 §1) に対してノイズにしかならない
    (`gpxstore.series_context` が空入力で run を作らないのと同じ規律)。
    """
    monkeypatch.delenv(ENV_VAR, raising=False)
    frames = _frames_in(tmp_path)
    calls, runner = _repair_recorder(rwp_after=8.0)

    out = repair_frames(_series(frames, [8.0, 8.1, 8.0, 8.2]), frames, [_P], runner=runner)

    assert "error" not in out, out.get("error")
    assert out["discontinuities"] == [] and calls == []
    assert not (tmp_path / "data" / "tsumugin_gpx").exists()
    assert out["gpx_dir"] == ""


def test_repair_without_any_trial_leaves_no_run_directory(tmp_path, monkeypatch):
    """対象はあっても**試行が 1 つも走らない** (良好な近傍が無い) なら run ディレクトリを作らない。

    全フレームが対象 = 互いに warm-start 元から除外されるので、どのフレームにも良好な近傍が無く
    全部 ``insitu_repair_no_neighbour`` になる。入口で run を先に作ると、空のディレクトリを
    ``gpx_dir`` として ③ に渡す (開いても何も無い・索引も無い)。
    """
    monkeypatch.delenv(ENV_VAR, raising=False)
    frames = _frames_in(tmp_path, n=2)
    calls, runner = _repair_recorder(rwp_after=8.0)

    out = repair_frames(
        _series(frames, [20.0, 21.0]), frames, [_P], target_frames=[0, 1], runner=runner
    )

    assert "error" not in out, out.get("error")
    assert calls == [] and out["needs_model_revision"] == [0, 1]
    assert not (tmp_path / "data" / "tsumugin_gpx").exists()
    assert out["gpx_dir"] == ""


# ---------------------------------------------------------------------------
# ② 境界での型検査 — 入力スキーマは緩い object なので型は実処理側が守る
# ---------------------------------------------------------------------------


def _call(tool: str, tmp_path, **gpx_kwargs) -> tuple[dict, list[dict]]:
    """保存指定を受ける ② ツールを記録 runner 付きで呼ぶ。"""
    if tool == "compare_structure_models":
        calls, runner = _compare_recorder()
        out = compare_structure_models(
            [_hist_in(tmp_path)], _VARIANTS, runner=runner, **gpx_kwargs
        )
    else:
        frames = _frames_in(tmp_path)
        calls, runner = _repair_recorder(rwp_after=8.0)
        out = repair_frames(
            _series(frames, _SPIKE), frames, [_P], target_frames=[1], runner=runner,
            **gpx_kwargs,
        )
    return out, calls


_TOOLS = ["compare_structure_models", "repair_frames"]


@pytest.mark.parametrize("tool", _TOOLS)
@pytest.mark.parametrize(
    "bad",
    [{"save_gpx": "false"}, {"save_gpx": 0}, {"gpx_dir": 123}, {"gpx_dir": ["/a"]}],
    ids=["save-str", "save-int", "dir-int", "dir-list"],
)
def test_gpx_arguments_of_the_wrong_type_are_an_error(tool, bad, tmp_path):
    """★型の違う保存指定は error dict (黙って別の意味に読まない・② は例外を送出しない)。

    非トートロジー: ``"false"`` は truthy なので ① は**保存する**と読み、``0`` は falsy なので
    **止める**と読む — どちらも ③ の意図と無関係に決まる。``gpx_dir=123`` は ① の
    ``os.path.abspath`` で ``TypeError`` になり、② の境界を例外のまま越える。
    """
    out, calls = _call(tool, tmp_path, **bad)

    assert out.get("error_type") == "TypeError", out
    assert next(iter(bad)) in out["error"]
    assert calls == [], "型検査は精密化を始める前に行う"


@pytest.mark.parametrize("tool", _TOOLS)
def test_save_gpx_null_means_the_default_not_an_opt_out(tool, tmp_path):
    """★``save_gpx: null`` は**既定 (保存する)** — opt-out は明示 ``false`` だけ (規定)。

    非トートロジー: ``bool(None)`` は「保存しない」に倒れる。``gpx_dir`` の null は「既定」なので、
    ``save_gpx`` だけ null が既定の**逆**になると ③ は気づかずに保存を止める。
    """
    out, calls = _call(tool, tmp_path, save_gpx=None)

    assert "error" not in out, out
    assert calls, "精密化が走っていない (テストの前提崩れ)"
    for call in calls:
        assert call["ctx"] is not None and call["ctx"].enabled is True, call
