"""★規定「全解析で gpx を保存する」の engine 側配線 (GSAS 非依存の決定論テスト)。

実 GSAS を回さずに検証できる範囲を全部ここで縛る:

- 保存先の**方針** (既定で保存 / 明示 keep_gpx の非回帰 / save_gpx=False の opt-out)
- 保存の**副作用** (索引 manifest.jsonl 追記 + ledger 追記)
- 保存に失敗しても**精密化結果を捨てない** (成果物は便宜であって結果ではない)

実際に `run_auto_rietveld` がこれを呼ぶことは gated テスト
(`test_gpx_default_gsas.py`) が実データで確かめる — ここだけでは
「呼ばれていない」を検出できないため両方が要る。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld.engine import _save_gpx_artifact
from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.gpxstore import GpxContext, plan_output, read_manifest
from tsumugin.store import Ledger


class _FakeGpx:
    """`G2Project` の代役 — `save()` が呼ばれたかだけを見る。"""

    def __init__(self) -> None:
        self.saved = 0

    def save(self) -> None:
        self.saved += 1


def _hist(data_path: str) -> HistogramSpec:
    return HistogramSpec(
        data_path=data_path,
        instrument_path="inst.instprm",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XYE",
    )


def _phase(name: str) -> PhaseSpec:
    return PhaseSpec(structure_path=f"{name}.cif", phase_name=name)


def test_saved_artifact_is_copied_indexed_and_logged(tmp_path):
    """保存すると (1) ファイルが出来 (2) 索引に 1 行 (3) ledger に 1 件残る。"""
    src = tmp_path / "work" / "auto.gpx"
    src.parent.mkdir()
    src.write_bytes(b"GPXCONTENT")
    run_dir = tmp_path / "out"
    plan = plan_output(["/data/PbSO4.fxye"], gpx_dir=str(run_dir))
    ledger = Ledger()
    gpx = _FakeGpx()

    out = _save_gpx_artifact(
        gpx,
        str(src),
        plan,
        histograms=[_hist("/data/PbSO4.fxye")],
        phases=[_phase("PbSO4")],
        rwp=8.11,
        gof=1.2,
        ledger=ledger,
        context=None,
    )

    assert gpx.saved == 1, "複製前に gpx.save() を呼んでいない (未保存状態を複製している)"
    assert Path(out).read_bytes() == b"GPXCONTENT"
    entries = read_manifest(plan.run_dir)
    assert len(entries) == 1
    assert entries[0]["phases"] == ["PbSO4"]
    assert entries[0]["rwp"] == pytest.approx(8.11)
    kinds = [e.kind for e in ledger.entries]
    assert "m7_gpx_saved" in kinds


def test_context_role_reaches_the_manifest(tmp_path):
    """系列の役割 (フレーム/トライアル) が索引に残る — 後から「どの精密化か」を引けること。"""
    src = tmp_path / "auto.gpx"
    src.write_bytes(b"x")
    ctx = GpxContext(run_dir=str(tmp_path / "run"), role="trial", index=180, label="delta")
    plan = plan_output(["/data/f180.xrdml"], context=ctx)

    _save_gpx_artifact(
        _FakeGpx(), str(src), plan,
        histograms=[_hist("/data/f180.xrdml")], phases=[_phase("alpha"), _phase("delta")],
        rwp=30.19, gof=2.0, ledger=Ledger(), context=ctx,
    )

    entry = read_manifest(plan.run_dir)[0]
    assert entry["role"] == "trial" and entry["index"] == 180 and entry["label"] == "delta"


def test_explicit_keep_path_is_not_indexed(tmp_path):
    """明示パス (keep_gpx) は呼び出し側の取り決め — 索引を勝手に作らない (非回帰)。"""
    src = tmp_path / "auto.gpx"
    src.write_bytes(b"x")
    target = tmp_path / "workbench_out" / "refined.gpx"
    target.parent.mkdir()
    plan = plan_output(["/data/a.xye"], keep=str(target))

    out = _save_gpx_artifact(
        _FakeGpx(), str(src), plan, histograms=[_hist("/data/a.xye")],
        phases=[_phase("a")], rwp=1.0, gof=1.0, ledger=Ledger(), context=None,
    )

    assert out == str(target) and target.exists()
    assert not (target.parent / "manifest.jsonl").exists()


def test_default_save_failure_does_not_lose_the_refinement(tmp_path):
    """**既定保存**が失敗しても例外を出さず "" を返し、理由を ledger に残す。

    既定保存は**便宜**であって結果ではない。ディスクが一杯だからといって 8 段階回した
    精密化を丸ごと失うのは受け入れられない (一方、黙って無かったことにもしない)。
    """
    src = tmp_path / "auto.gpx"
    src.write_bytes(b"x")
    ledger = Ledger()
    plan = plan_output(["/data/a.xye"], gpx_dir=str(tmp_path / "out"))
    Path(plan.path).mkdir(parents=True)  # 同名のディレクトリを置いて複製を失敗させる

    out = _save_gpx_artifact(
        _FakeGpx(), str(src), plan,
        histograms=[_hist("/data/a.xye")], phases=[_phase("a")],
        rwp=1.0, gof=1.0, ledger=ledger, context=None,
    )

    assert out == ""
    assert "m7_gpx_error" in [e.kind for e in ledger.entries]


def test_explicit_keep_failure_is_loud(tmp_path):
    """明示 ``keep_gpx`` の保存失敗は**例外のまま**投げる (規定変更前と同じ)。

    握り潰すと呼び出し側 (workbench 等) は空の ``gpx_path`` を「保存しない設定」と
    区別できず、頼んだ保存が消えたことに気づけない。
    """
    plan = plan_output(["/data/a.xye"], keep=str(tmp_path / "missing-dir" / "x.gpx"))

    with pytest.raises(OSError):
        _save_gpx_artifact(
            _FakeGpx(), str(tmp_path / "nonexistent.gpx"), plan,
            histograms=[_hist("/data/a.xye")], phases=[_phase("a")],
            rwp=1.0, gof=1.0, ledger=Ledger(), context=None,
        )


def test_disabled_plan_saves_nothing(tmp_path):
    """``save_gpx=False`` 相当の計画では 1 バイトも書かない。"""
    src = tmp_path / "auto.gpx"
    src.write_bytes(b"x")
    plan = plan_output(["/data/a.xye"], save=False)
    gpx = _FakeGpx()

    out = _save_gpx_artifact(
        gpx, str(src), plan, histograms=[_hist("/data/a.xye")], phases=[_phase("a")],
        rwp=1.0, gof=1.0, ledger=Ledger(), context=None,
    )

    assert out == "" and gpx.saved == 0


def test_run_auto_rietveld_saves_by_default():
    """★ engine の既定が「保存する」であること (規定そのものの宣言)。

    既定値を False へ戻す/引数を消す変更でここが落ちる。実際に保存されることは
    gated テストが実データで確かめる。
    """
    import inspect

    from tsumugin.autorietveld.engine import run_auto_rietveld

    sig = inspect.signature(run_auto_rietveld)
    assert sig.parameters["save_gpx"].default is True
    assert sig.parameters["gpx_dir"].default is None
