"""★規定「全解析で gpx を保存する」の**ファンアウト経路** — レシピ探索 / マルチスタート /
モデル比較 (GSAS 非依存の決定論テスト)。

この 3 つは「1 回の解析」の中で **N 回精密化する**。採用されるのは 1 つだけなので、

- 探索: 負けた候補の fit が無いと「なぜその手順が勝ったか」を後から見られない
- 収束確認: 別ベイスンへ落ちた開始点の fit が無いと**どんな解へ落ちたか**を確認できない
- モデル比較: 棄却されたモデル (例 NaCuHCF model5 の Na>1 発散) の fit が無いと
  ΔBIC の根拠を検算できない

**マルチスタートだけは別プロセス**で走るため ambient 文脈が届かない — 明示 ``gpx_context``
で運ぶ (ここを取り違えると「並列にすると保存されない」という気づきにくい穴になる)。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.compare import ModelVariant, compare_models
from tsumugin.autorietveld.confirm import optimize_then_confirm
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    ValidityReport,
)
from tsumugin.autorietveld.multistart import MultistartConfig, run_multistart_rietveld
from tsumugin.autorietveld.search import run_recipe_search
from tsumugin.gpxstore import active_context
from tsumugin.refine_loop.model_compare import run_model_comparison

_HIST = HistogramSpec(
    data_path="d.xye",
    instrument_path="i.instprm",
    radiation=Radiation.XRAY_LAB,
    geometry=Geometry.BRAGG_BRENTANO,
    data_format="XYE",
)
_PHASE = PhaseSpec(structure_path="a.cif", phase_name="ph")


def _result(rwp=9.0, cells=None):
    return AutoRietveldResult(
        stage_results=(), final_rwp=rwp, final_gof=1.0,
        refined_cells=cells or {"ph": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True), n_obs=1000,
    )


def test_recipe_search_labels_each_candidate(tmp_path, monkeypatch):
    """探索は候補ごとに ``candidate`` 役割 + 候補名で成果物を残す (負けた手順も)。"""
    seen: list[tuple[str, str]] = []

    def fake_engine(histograms, phases, **kwargs):
        ctx = active_context()
        seen.append((ctx.role, ctx.label) if ctx else ("", ""))
        return _result()

    monkeypatch.setattr("tsumugin.autorietveld.engine.run_auto_rietveld", fake_engine)
    run_recipe_search(
        [_HIST], [_PHASE], names=["default", "polish"], gpx_dir=str(tmp_path)
    )

    assert seen == [("candidate", "default"), ("candidate", "polish")]


def test_multistart_carries_the_context_across_processes(tmp_path, monkeypatch):
    """マルチスタートは**明示文脈**を各開始点へ渡す (別プロセスに ambient は届かない)。"""
    seen: list[dict] = []

    def fake_engine(histograms, phases, **kwargs):
        ctx = kwargs.get("gpx_context")
        seen.append({"role": ctx.role if ctx else "", "index": ctx.index if ctx else None})
        return _result()

    monkeypatch.setattr("tsumugin.autorietveld.engine.run_auto_rietveld", fake_engine)
    run_multistart_rietveld(
        [_HIST], [_PHASE], config=MultistartConfig(n_starts=3), jobs=1,
        gpx_dir=str(tmp_path),
    )

    assert [s["role"] for s in seen] == ["multistart"] * 3
    assert [s["index"] for s in seen] == [0, 1, 2]


def test_multistart_context_is_picklable():
    """明示文脈が pickle できること (ProcessPoolExecutor の payload に載る)。"""
    import pickle

    from tsumugin.gpxstore import GpxContext

    ctx = GpxContext(run_dir="/x", role="multistart", index=2)
    assert pickle.loads(pickle.dumps(ctx)) == ctx


def test_compare_models_labels_each_variant(tmp_path, monkeypatch):
    """モデル比較は各バリアントを ``model`` 役割 + バリアント名で残す (棄却モデルも)。"""
    seen: list[tuple[str, str]] = []

    def runner(histograms, phases, **kwargs):
        ctx = active_context()
        seen.append((ctx.role, ctx.label) if ctx else ("", ""))
        return _result()

    compare_models(
        [_HIST],
        [
            ModelVariant(name="model5", phases=(_PHASE,)),
            ModelVariant(name="model6", phases=(_PHASE,)),
        ],
        runner=runner,
        gpx_dir=str(tmp_path),
    )

    assert seen == [("model", "model5"), ("model", "model6")]


# ---------------------------------------------------------------------------
# 単一成果物パス (keep_*) はファンアウトの入口で拒む (構成は #225 のテストを採った)
# ---------------------------------------------------------------------------

_VARIANTS = (
    ModelVariant(name="model5", phases=(_PHASE,)),
    ModelVariant(name="model6", phases=(_PHASE,)),
)

#: ファンアウト入口 → 呼び方。精密化は全部 ``fake`` (engine の差し替え) を通る。
#: 合成入口 (モデル比較の上位 / 標準経路) も並べる — 下位の入口が拒んでも、合成側が
#: 先に run ディレクトリを作る / ``run_kwargs`` を剥がしてから渡す実装に変わればここで落ちる。
_FANOUT_ENTRIES = {
    "compare_models": lambda fake, **kw: compare_models([_HIST], _VARIANTS, runner=fake, **kw),
    "run_model_comparison": lambda fake, **kw: run_model_comparison(
        [_HIST], _VARIANTS, runner=fake, **kw
    ),
    "run_recipe_search": lambda fake, **kw: run_recipe_search(
        [_HIST], [_PHASE], names=["default", "polish"], **kw
    ),
    "run_multistart_rietveld": lambda fake, **kw: run_multistart_rietveld(
        [_HIST], [_PHASE], config=MultistartConfig(n_starts=3), jobs=1, **kw
    ),
    "optimize_then_confirm": lambda fake, **kw: optimize_then_confirm(
        [_HIST], [_PHASE], candidates=["default", "polish"], n_starts=3, jobs=1, **kw
    ),
}


#: 拒否を出す入口名 (既定は入口自身)。`run_model_comparison` は `compare_models` の薄い上位で、
#: 自前の処理を挟まないので下位に任せている。`optimize_then_confirm` は Phase A より前に
#: 自分で拒む — 名前で見分けないと「Phase A が拒んでくれる」に黙って退化しても気づけない。
_REJECTED_BY = {"run_model_comparison": "compare_models"}


@pytest.fixture
def engine_calls(monkeypatch):
    """engine を差し替え、精密化 1 回ごとに受け取った kwargs を記録する。"""
    calls: list[dict] = []

    def fake_engine(histograms, phases, **kwargs):
        calls.append(kwargs)
        return _result()

    monkeypatch.setattr("tsumugin.autorietveld.engine.run_auto_rietveld", fake_engine)
    return calls, fake_engine


@pytest.mark.parametrize("save_gpx", [True, False])
@pytest.mark.parametrize("key", ["keep_gpx", "keep_project"])
@pytest.mark.parametrize("entry", sorted(_FANOUT_ENTRIES))
def test_fanout_rejects_a_single_keep_path_before_refining(
    entry, key, save_gpx, engine_calls, tmp_path
):
    """★N 回精密化する入口は、成果物 **1 つ**のパス (``keep_*``) を精密化前に拒む。

    ``keep_*`` は `plan_output` でどの opt-out にも勝つ (2026-10-09)。透過すると N 回の精密化が
    同じパスへ上書きされ (マルチスタートは別プロセスが同時に書き、衝突は「発散」扱いになる)、
    候補ごとの成果物 (NFR-108) は 1 つも残らない — ``save_gpx=False`` を添えても書く。
    拒むのは**何も回す前** (回し終えてから投げると計算ごと失う) かつ**ディスクに触る前**
    (中身が空の run ディレクトリだけ残す、という痕跡を作らない)。
    """
    calls, fake = engine_calls
    target = tmp_path / "one.gpx"
    runs = tmp_path / "runs"

    with pytest.raises(ValueError, match=key) as excinfo:
        _FANOUT_ENTRIES[entry](fake, **{key: str(target)}, gpx_dir=str(runs), save_gpx=save_gpx)

    assert "gpx_dir" in str(excinfo.value)  # 代わりの指定方法を名指しする
    assert str(excinfo.value).startswith(_REJECTED_BY.get(entry, entry))  # 入口自身が拒む
    assert calls == [], f"拒む前に精密化が {len(calls)} 回走った (結果を捨てることになる)"
    assert not runs.exists(), "拒む前に run ディレクトリを作った"
    assert not target.exists()


@pytest.mark.parametrize("unset", [None, ""])
@pytest.mark.parametrize("entry", sorted(_FANOUT_ENTRIES))
def test_fanout_lets_an_unset_keep_gpx_through(entry, unset, engine_calls, tmp_path):
    """``None`` / ``""`` は `plan_output` が「指定なし」と読む値 — ファンアウト入口も拒まない。

    ``keep_gpx=project.gpx_path or None`` のような素直な転送を壊さないため、拒む範囲は
    「そのまま透過すると保存先が名指しのパスへ変わる値」に限る。
    """
    calls, fake = engine_calls

    _FANOUT_ENTRIES[entry](fake, keep_gpx=unset, gpx_dir=str(tmp_path))

    assert calls, "精密化が 1 回も走っていない"


def test_refinement_loop_labels_each_iteration(tmp_path):
    """M8 閉ループ: 1 ループ = run ディレクトリ 1 つ、反復ごとに ``iteration`` 役割で残す。

    棄却された反復も残る — 「その手を採らなかった理由」は Rwp の数字だけでは追えない。
    """
    from tsumugin.refine_loop.orchestrator import run_refinement_loop

    seen: list[tuple[str, int | None, str]] = []

    def runner(inp):
        ctx = active_context()
        seen.append((ctx.role, ctx.index, ctx.run_dir) if ctx else ("", None, ""))
        # 反復のたびに悪化させ、1 手で停止させる (ループ制御はここの主眼ではない)
        return _result(rwp=9.0 + len(seen))

    run_refinement_loop(
        [_HIST], [_PHASE], runner=runner, background_coeffs=6, gpx_dir=str(tmp_path)
    )

    assert [r for r, _, _ in seen] == ["iteration"] * len(seen)
    assert [i for _, i, _ in seen] == list(range(len(seen)))
    assert len({d for _, _, d in seen}) == 1, "反復ごとに run ディレクトリが分かれている"
