"""★規定「全解析で gpx を保存する」の ② 露出 (§4.5 到達可能性)。

① に保存機構があっても、② に (a) 置き場所を指定する引数と (b) 保存先を返すキーが無ければ、
③ にとってその機能は**存在しない**。特に MEM 系ツール (`mem_density` /
`mem_rietveld_iterate`) は「精密化済み gpx のパス」を入力に要求するので、
**その出所が ② の中に無いと呼び手が存在しない (dead on arrival)**。

ここで縛るのは「引数がエンジンへ届くこと」と「保存先が返り値に出ること」の 2 点。
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.gpxstore import ENV_VAR, active_context
from tsumugin.insitu.model import FrameRietveldResult, SequentialRietveldResult
from tsumugin.mcp.anchor_tools import anchored_sequential
from tsumugin.mcp.insitu_tools import sequential_rietveld
from tsumugin.mcp.rietveld_tools import auto_rietveld

_H = {
    "data_path": "d.xra",
    "instrument_path": "i.prm",
    "radiation": "xray_lab",
    "geometry": "bragg_brentano",
    "data_format": "GSAS",
}
_P = {"structure_path": "a.cif", "phase_name": "ph"}
_FRAMES = [
    {"data_path": "f0.xye", "axis_value": 300.0, "data_format": "XYE"},
    {"data_path": "f1.xye", "axis_value": 310.0, "data_format": "XYE"},
]


def _seq_result(gpx_dir: str) -> SequentialRietveldResult:
    return SequentialRietveldResult(
        frames=(
            FrameRietveldResult(
                frame_index=0, axis_value=300.0, data_path="f0.xye", rwp=9.0, gof=1.1,
                refined_cells={}, phase_fractions={}, phase_names=("ph",),
                gpx_path=f"{gpx_dir}/f0000_frame.gpx",
            ),
        ),
        phase_names=("ph",),
        gpx_dir=gpx_dir,
    )


def test_auto_rietveld_forwards_gpx_dir_to_the_engine(monkeypatch):
    """``auto_rietveld(gpx_dir=, save_gpx=)`` が既定 runner 経由でエンジンへ届く。"""
    captured: dict[str, object] = {}

    def fake_default_runner(seed, **kwargs):
        captured.update(kwargs)

        def run(inp):
            return AutoRietveldResult(
                stage_results=(), final_rwp=9.0, final_gof=1.0, refined_cells={},
                validity=ValidityReport(passed=True), gpx_path="/out/run/PbSO4.gpx",
            )

        return run

    monkeypatch.setattr(
        "tsumugin.mcp.rietveld_tools._default_gsas_runner", fake_default_runner
    )
    out = auto_rietveld([_H], [_P], gpx_dir="/chosen", save_gpx=True)

    assert captured["gpx_dir"] == "/chosen"
    assert captured["save_gpx"] is True
    # 保存先が ③ に返る = MEM 系ツールの入力の出所になる
    assert out["gpx_path"] == "/out/run/PbSO4.gpx"


def test_auto_rietveld_defaults_to_saving(monkeypatch):
    """★引数を渡さなくても ② は「保存する」でエンジンを呼ぶ (規定そのもの)。"""
    captured: dict[str, object] = {}

    def fake_default_runner(seed, **kwargs):
        captured.update(kwargs)
        return lambda inp: AutoRietveldResult(
            stage_results=(), final_rwp=9.0, final_gof=1.0, refined_cells={},
            validity=ValidityReport(passed=True),
        )

    monkeypatch.setattr(
        "tsumugin.mcp.rietveld_tools._default_gsas_runner", fake_default_runner
    )
    auto_rietveld([_H], [_P])

    assert captured["save_gpx"] is True
    assert captured["gpx_dir"] is None  # 既定の解決 (env → データ隣接) に委ねる


def test_sequential_rietveld_forwards_and_returns_gpx(monkeypatch):
    """系列: ``gpx_dir`` がエンジンへ届き、``gpx_dir``/``frames[].gpx_path`` が返る。"""
    captured: dict[str, object] = {}

    def fake_run(frames, phases, *, config=None, runner=None, phase_finder=None,
                 workdir=None, gpx_dir=None, save_gpx=True):
        captured["gpx_dir"] = gpx_dir
        captured["save_gpx"] = save_gpx
        return _seq_result("/series/run-1")

    monkeypatch.setattr("tsumugin.insitu.engine.run_sequential_rietveld", fake_run)
    out = sequential_rietveld(_FRAMES, [_P], gpx_dir="/series", runner=lambda *a, **k: None)

    assert captured == {"gpx_dir": "/series", "save_gpx": True}
    assert out["gpx_dir"] == "/series/run-1"
    assert out["frames"][0]["gpx_path"] == "/series/run-1/f0000_frame.gpx"


def test_anchored_sequential_forwards_and_returns_gpx(monkeypatch):
    """M10 双方向でも同じ 2 点 (引数がエンジンへ / 保存先が返り値へ)。"""
    captured: dict[str, object] = {}

    def fake_run(frames, base, *, runner=None, identifier=None, cfg=None, ledger=None,
                 charge_constraint=None, gpx_dir=None, save_gpx=True):
        captured["gpx_dir"] = gpx_dir
        captured["save_gpx"] = save_gpx
        return _seq_result("/anchored/run-1")

    monkeypatch.setattr("tsumugin.insitu.anchor.engine.run_anchored_sequential", fake_run)
    out = anchored_sequential(
        _FRAMES, [_P], gpx_dir="/anchored", save_gpx=False, runner=lambda *a, **k: None
    )

    assert captured == {"gpx_dir": "/anchored", "save_gpx": False}
    assert out["gpx_dir"] == "/anchored/run-1"
    assert out["frames"][0]["gpx_path"] == "/anchored/run-1/f0000_frame.gpx"


def test_repair_frames_returns_the_repaired_fit_path(monkeypatch, tmp_path):
    """修復した fit の成果物パスが ② に出る (修復は元フレームを置き換えるため別ハンドル)。

    `frames[i].gpx_path` は**修復前**の fit を指す。取り違えると ③ は「直したつもりの
    フレーム」に対して直す前の fit を開く/MEM を掛けることになる。
    """
    from tsumugin.insitu.repair import FrameRepair, RepairReport
    from tsumugin.mcp.operando_diag_tools import repair_frames

    def fake_repair(frames, seq, phases, runner, discontinuities, **kwargs):
        return RepairReport(
            repairs=(
                FrameRepair(
                    frame_index=1, rwp_before=12.0, rwp_after=8.0, source="L",
                    phase_fractions={"ph": 1.0}, gpx_path="/out/run/f0001_repair_L.gpx",
                ),
            ),
            needs_model_revision=(),
            systematic_hint=(),
        )

    monkeypatch.setattr("tsumugin.insitu.repair.repair_isolated", fake_repair)
    series = {
        "frames": [
            {
                "frame_index": i, "axis_value": 300.0 + 10 * i, "data_path": f"f{i}.xye",
                "rwp": 9.0, "gof": 1.1, "refined_cells": {}, "phase_fractions": {"ph": 1.0},
                "phase_names": ["ph"], "gpx_path": f"/out/run/f000{i}_frame.gpx",
            }
            for i in range(2)
        ],
        "phase_names": ["ph"],
    }
    out = repair_frames(
        series, _FRAMES, [_P], target_frames=[1], two_theta_limits=[10.0, 70.0],
        runner=lambda *a, **k: None,
    )

    assert out["repairs"][0]["gpx_path"] == "/out/run/f0001_repair_L.gpx"


def test_topas_backend_receives_the_same_gpx_arguments(monkeypatch):
    """★ ``backend="topas"`` でも**同じ引数名**で保存指示が届く (バックエンド中立の契約)。

    ② は保存の指定をバックエンドで呼び分けない。TOPAS では ``.gpx`` ではなく
    プロジェクト**ディレクトリ**が残り、返り値は ``project_path`` に出る。
    """
    captured: dict[str, object] = {}

    def fake_topas(histograms, phases, **kwargs):
        captured.update(kwargs)
        return AutoRietveldResult(
            stage_results=(), final_rwp=8.1, final_gof=1.2, refined_cells={},
            validity=ValidityReport(passed=True), backend="topas",
            project_path="/out/run/PBSO4",
        )

    monkeypatch.setattr("tsumugin.topas.engine.run_topas_rietveld", fake_topas)
    out = auto_rietveld([_H], [_P], backend="topas", gpx_dir="/chosen")

    assert captured["gpx_dir"] == "/chosen"
    assert captured["save_gpx"] is True
    assert out["project_path"] == "/out/run/PBSO4"
    assert out["gpx_path"] == ""  # TOPAS に .gpx は無い


# ---------------------------------------------------------------------------
# 探索 (`search`) / 収束確認 (`multistart`) 経路 — 1 呼び出しで N 回精密化する経路
# ---------------------------------------------------------------------------
#
# この 2 経路は単発経路と違い `_default_gsas_runner` を通らず、① の探索/収束確認が候補ごと・
# 開始点ごとに `run_auto_rietveld` を呼ぶ。そのため ② で受けた ``gpx_dir``/``save_gpx`` を
# ① へ**明示的に運ばない限り届かない** — 届かないと (a) ``save_gpx=False`` (唯一の opt-out) が
# 黙って無視されてデータ隣接へ書かれ、(b) 明示 ``gpx_dir`` が黙って無視されて成果物が
# 頼んでいない場所に散らばる。どちらも返り値には現れない (精密化結果は同じなので)。
#
# 実 GSAS を回さずに見るため、①の候補/開始点が呼ぶ `run_auto_rietveld` を差し替え、
# **実際に届いた引数**と ambient 文脈を記録する (`search_runner` を注入すると ① の既定 runner
# ごと迂回して `run_kwargs` が見えなくなるので、注入しない)。


def _selected_result() -> AutoRietveldResult:
    """探索で採用されうる (収束した段を持つ) 結果。"""
    return AutoRietveldResult(
        stage_results=(
            StageResult(label="S1", rwp=9.5, gof=1.5, n_params=30, converged=True),
        ),
        final_rwp=9.5,
        final_gof=1.5,
        refined_cells={"ph": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        n_obs=4000,
    )


def _record_engine_calls(monkeypatch) -> list[dict]:
    """①の候補/開始点が呼ぶ `run_auto_rietveld` を記録スタブへ差し替える。

    記録するのは「エンジンが保存先を決めるのに読む 3 つ」= 明示引数 ``gpx_dir``/``save_gpx``、
    明示文脈 ``gpx_context`` (マルチスタート) と ambient 文脈 (探索)。
    """
    calls: list[dict] = []

    def fake_engine(histograms, phases, **kwargs):
        explicit = kwargs.get("gpx_context")
        calls.append(
            {
                "gpx_dir": kwargs.get("gpx_dir", "<absent>"),
                "save_gpx": kwargs.get("save_gpx", "<absent>"),
                # エンジンと同じ優先順位 (明示 > ambient) で「実際に効く文脈」を採る
                "ctx": explicit if explicit is not None else active_context(),
            }
        )
        ctx = calls[-1]["ctx"]
        saved = ctx is not None and ctx.enabled and ctx.run_dir
        return dataclasses.replace(
            _selected_result(),
            gpx_path=os.path.join(ctx.run_dir, ctx.stem(data_stem="d") + ".gpx") if saved else "",
        )

    monkeypatch.setattr("tsumugin.autorietveld.engine.run_auto_rietveld", fake_engine)
    return calls


def _hist_in(tmp_path) -> dict:
    data = tmp_path / "data" / "d.xra"
    data.parent.mkdir(parents=True)
    return {**_H, "data_path": str(data)}


_SEARCH = {"search": ["default", "polish"]}
_MULTISTART = {"search": ["default"], "multistart": {"n_starts": 3, "jobs": 1}}


@pytest.mark.parametrize("route", [_SEARCH, _MULTISTART], ids=["search", "multistart"])
def test_search_routes_honor_the_save_gpx_opt_out(route, tmp_path, monkeypatch):
    """★``save_gpx=False`` (規定の**唯一の** opt-out) が全候補・全開始点へ届く。

    非トートロジー: 届かないと ① は既定どおり保存する — 返り値の Rwp は同じなので
    「止めたつもりで書き続けている」ことに誰も気づけない。エンジンに届いた引数と文脈の
    両方を見る (文脈が enabled のままだと、文脈を読む runner が保存してしまう)。
    """
    # 既定 (env なし) の置き場所 = データ隣接。opt-out が届かなければここに run ができる
    #   (env を差したままだと env の根が優先され、データ隣接の不在は何も確かめない)。
    monkeypatch.delenv(ENV_VAR, raising=False)
    calls = _record_engine_calls(monkeypatch)

    out = auto_rietveld([_hist_in(tmp_path)], [_P], save_gpx=False, **route)

    assert "error" not in out, out.get("error")
    assert calls, "候補/開始点が 1 つも走っていない (テストの前提崩れ)"
    for call in calls:
        assert call["save_gpx"] is False, call
        assert call["ctx"] is not None and call["ctx"].enabled is False, call
    # どこにも書かない: 既定の置き場所 (データ隣接) に run ディレクトリを作らない
    assert not (tmp_path / "data" / "tsumugin_gpx").exists()
    assert out["gpx_path"] == ""


@pytest.mark.parametrize("route", [_SEARCH, _MULTISTART], ids=["search", "multistart"])
def test_search_routes_honor_an_explicit_gpx_dir(route, tmp_path, monkeypatch):
    """★明示 ``gpx_dir`` が全候補・全開始点の置き場所になる (env より強い)。

    非トートロジー: 届かないと ① は env → データ隣接で根を決める — 成果物は**保存はされる**
    ので「保存されたか」だけを見るテストでは落ちない。どこに置かれたかを見る。
    """
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "env-root"))
    chosen = tmp_path / "chosen"
    calls = _record_engine_calls(monkeypatch)

    out = auto_rietveld([_hist_in(tmp_path)], [_P], gpx_dir=str(chosen), **route)

    assert "error" not in out, out.get("error")
    assert calls
    run_dirs = set()
    for call in calls:
        assert call["save_gpx"] is True, call
        ctx = call["ctx"]
        assert ctx is not None and ctx.enabled, call
        assert os.path.dirname(ctx.run_dir) == str(chosen), call
        run_dirs.add(ctx.run_dir)
    # 1 実行 = 1 run ディレクトリ (設計 §3)。収束確認は Phase A (探索) と Phase B (開始点) を
    #   含むが、1 回の ② 呼び出しなので**同じ** run ディレクトリに並ばなければ探せない。
    assert len(run_dirs) == 1, run_dirs
    assert not (tmp_path / "env-root").exists()


def test_multistart_route_names_every_artifact_by_role(tmp_path, monkeypatch):
    """★収束確認の成果物は役割名付きで残る — 候補は ``candidate``、開始点は ``multistart``。

    負けた候補・別ベイスンへ落ちた開始点こそ後から開きたい成果物なので、名前で区別できる
    ことを ② の経路で確かめる (① 単体のテストは ② が引数を落としても green のまま)。
    """
    calls = _record_engine_calls(monkeypatch)

    auto_rietveld(
        [_hist_in(tmp_path)], [_P], gpx_dir=str(tmp_path / "chosen"), **_MULTISTART
    )

    roles = [(c["ctx"].role, c["ctx"].index, c["ctx"].label) for c in calls]
    assert roles == [
        ("candidate", None, "default"),
        ("multistart", 0, ""),
        ("multistart", 1, ""),
        ("multistart", 2, ""),
    ]


@pytest.mark.parametrize("route", [_SEARCH, _MULTISTART], ids=["search", "multistart"])
def test_search_routes_return_a_handle_to_every_artifact(route, tmp_path, monkeypatch):
    """★負けた候補・各開始点の成果物パスが返り値に載る (§4.5 到達可能性)。

    非トートロジー: 返るのが採用 fit の ``gpx_path`` だけだと、保存の目的そのもの
    (「負けた候補/別ベイスンへ落ちた開始点がどんな解だったか」を開く・MEM に掛ける) に
    ③ が届かない。採用 fit の保存が失敗した (``gpx_path == ""``) ときは run ディレクトリすら
    辿れなくなる。
    """
    _record_engine_calls(monkeypatch)

    out = auto_rietveld(
        [_hist_in(tmp_path)], [_P], gpx_dir=str(tmp_path / "chosen"), **route
    )

    assert "error" not in out, out.get("error")
    assert [os.path.basename(c["gpx_path"]) for c in out["search"]["candidates"]] == [
        f"candidate_{name}.gpx" for name in route["search"]
    ]
    if "multistart" in route:
        starts = out["convergence"]["multistart"]["starts"]
        assert [os.path.basename(s["gpx_path"]) for s in starts] == [
            "f0000_multistart.gpx", "f0001_multistart.gpx", "f0002_multistart.gpx"
        ]


@pytest.mark.parametrize("route", [_SEARCH, _MULTISTART], ids=["search", "multistart"])
def test_search_routes_say_when_artifacts_fell_back_to_temp(route, tmp_path, monkeypatch):
    """★頼まれた ``gpx_dir`` に書けず一時領域へ退避したら、それを返り値の警告で言う。

    非トートロジー: 退避理由は run ディレクトリを解決した入口でしか分からない — エンジンは
    解決済みの文脈を受け取るので ``m7_gpx_fallback`` を書かない。入口が理由を捨てると、
    ③ は「指定した場所に保存された」と読んだまま、成果物は %TEMP% に置かれる
    (設計 §5「temp へ退避し理由を ledger」/「黙って保存を諦めない」)。
    """
    import tempfile

    def unwritable(root, base):
        raise PermissionError(13, "read-only", root)

    monkeypatch.setattr("tsumugin.gpxstore._make_unique_dir", unwritable)
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    _record_engine_calls(monkeypatch)

    out = auto_rietveld(
        [_hist_in(tmp_path)], [_P], gpx_dir=str(tmp_path / "chosen"), **route
    )

    assert "error" not in out, out.get("error")
    section = out["convergence"] if "multistart" in route else out["search"]
    assert any("一時領域へ退避" in w for w in section["warnings"]), section["warnings"]


# ---------------------------------------------------------------------------
# ② 境界での型検査 — 入力スキーマは緩い object なので型は実処理側が守る
# ---------------------------------------------------------------------------


def _call_tool_capturing(tool: str, monkeypatch, **gpx_kwargs) -> tuple[dict, dict]:
    """保存指定を受ける ② ツールを呼び、エンジン側へ届いた ``save_gpx``/``gpx_dir`` を返す。"""
    captured: dict[str, object] = {}

    def fake_default_runner(seed, **kwargs):
        captured.update(kwargs)
        return lambda inp: _selected_result()

    def fake_series(frames, phases, *args, gpx_dir=None, save_gpx=True, **kwargs):
        captured.update(gpx_dir=gpx_dir, save_gpx=save_gpx)
        return _seq_result("/series/run-1")

    monkeypatch.setattr("tsumugin.mcp.rietveld_tools._default_gsas_runner", fake_default_runner)
    monkeypatch.setattr("tsumugin.insitu.engine.run_sequential_rietveld", fake_series)
    monkeypatch.setattr("tsumugin.insitu.anchor.engine.run_anchored_sequential", fake_series)
    from tsumugin.mcp.rietveld_tools import refine_with_revisions

    stub = lambda *a, **k: None  # noqa: E731 — 系列ツールの runner 注入 (実行されない)
    calls = {
        "auto_rietveld": lambda: auto_rietveld([_H], [_P], **gpx_kwargs),
        "refine_with_revisions": lambda: refine_with_revisions([_H], [_P], [], **gpx_kwargs),
        "sequential_rietveld": lambda: sequential_rietveld(
            _FRAMES, [_P], runner=stub, **gpx_kwargs
        ),
        "anchored_sequential": lambda: anchored_sequential(
            _FRAMES, [_P], runner=stub, **gpx_kwargs
        ),
    }
    return calls[tool](), captured


_GPX_TOOLS = ["auto_rietveld", "refine_with_revisions", "sequential_rietveld", "anchored_sequential"]


@pytest.mark.parametrize("tool", _GPX_TOOLS)
@pytest.mark.parametrize(
    "bad",
    [{"save_gpx": "false"}, {"save_gpx": 0}, {"gpx_dir": 123}, {"gpx_dir": ["/a"]}],
    ids=["save-str", "save-int", "dir-int", "dir-list"],
)
def test_gpx_arguments_of_the_wrong_type_are_an_error(tool, bad, monkeypatch):
    """★型の違う保存指定は error dict (黙って別の意味に読まない)。

    非トートロジー: ``"false"`` は truthy なので ① は**保存する**と読み、``0`` は falsy なので
    **止める**と読む — どちらも ③ の意図と無関係に決まる。``gpx_dir=123`` は単発経路では
    精密化の後 (成果物の保存時) に ``TypeError`` が ② の境界を越える。
    """
    out, captured = _call_tool_capturing(tool, monkeypatch, **bad)

    assert out.get("error_type") == "TypeError", out
    assert next(iter(bad)) in out["error"]
    assert captured == {}, "型検査は精密化を始める前に行う"


@pytest.mark.parametrize("tool", _GPX_TOOLS)
def test_save_gpx_null_means_the_default_not_an_opt_out(tool, monkeypatch):
    """★``save_gpx: null`` は**既定 (保存する)** — opt-out は明示 ``false`` だけ (規定)。

    非トートロジー: ``bool(None)`` も ``not None`` も「保存しない」に倒れる。他の引数
    (``gpx_dir``/``search``/``stability``) の null はどれも「既定」を意味するので、
    ``save_gpx`` だけ null が既定の**逆**になると ③ は気づかずに保存を止める。
    """
    out, captured = _call_tool_capturing(tool, monkeypatch, save_gpx=None)

    assert "error" not in out, out
    assert captured["save_gpx"] is True
