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

from tsumugin.autorietveld.compare import ModelVariant, compare_models
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
