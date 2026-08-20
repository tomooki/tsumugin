"""★規定「全解析で gpx を保存する」を**実 GSAS** で確かめる (T1 fluoroapatite)。

決定論テスト (`test_gpx_output.py`) は保存ヘルパの振る舞いしか見ない — engine がそれを
**呼んでいない**場合は緑のままになる。ここは実際に `run_auto_rietveld` を回し、

1. 何も指定しなくても .gpx が**観測データ隣接**に出来ること
2. `AutoRietveldResult.gpx_path` がそのファイルを指すこと (③ が MEM へ渡せる)
3. 索引 (manifest.jsonl) に Rwp 付きで 1 行残ること
4. `save_gpx=False` では 1 バイトも書かないこと (opt-out が本当に効く)

を確かめる。データはテストの tmp へ**コピーして**使う — 既定がデータ隣接なので、
追跡済みの `docs/benchmark/testdata/` を汚さないため。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.gpxstore import DEFAULT_DIR_NAME, ENV_VAR, read_manifest

_DATA = Path("docs/benchmark/testdata/m7/labdata")
_FILES = ("FAP.XRA", "FAP.EXP", "INST_XRY.PRM")

pytestmark = pytest.mark.gsas


def _data_present() -> bool:
    return all((_DATA / f).exists() for f in _FILES)


def _staged(tmp_path: Path) -> tuple[HistogramSpec, PhaseSpec]:
    """T1 データを tmp へコピーし、そこを指す spec を返す (既定の置き場所がここになる)。"""
    for f in _FILES:
        shutil.copyfile(_DATA / f, tmp_path / f)
    hist = HistogramSpec(
        data_path=str(tmp_path / "FAP.XRA"),
        instrument_path=str(tmp_path / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )
    phase = PhaseSpec(
        structure_path=str(tmp_path / "FAP.EXP"), phase_name="fap", format_hint="EXP"
    )
    return hist, phase


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_default_run_saves_gpx_next_to_the_data(tmp_path, monkeypatch):
    """既定 (引数なし) で観測データ隣接に .gpx が残り、結果と索引がそれを指す。"""
    monkeypatch.delenv(ENV_VAR, raising=False)  # 隔離を外して**本番の既定**を見る
    hist, phase = _staged(tmp_path)

    result = run_auto_rietveld([hist], [phase])

    saved = Path(result.gpx_path)
    assert saved.is_file() and saved.suffix == ".gpx", result.gpx_path
    assert saved.parent.parent == tmp_path / DEFAULT_DIR_NAME
    assert saved.name == "FAP.gpx"  # データ名から決まる (どのデータの精密化か分かる)
    assert saved.stat().st_size > 0

    entries = read_manifest(str(saved.parent))
    assert len(entries) == 1
    assert entries[0]["path"] == str(saved)
    assert entries[0]["phases"] == ["fap"]
    assert entries[0]["rwp"] == pytest.approx(result.final_rwp)


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_save_gpx_false_writes_nothing(tmp_path, monkeypatch):
    """opt-out (``save_gpx=False``) は本当に 1 バイトも書かない。"""
    monkeypatch.delenv(ENV_VAR, raising=False)
    hist, phase = _staged(tmp_path)

    result = run_auto_rietveld([hist], [phase], save_gpx=False)

    assert result.gpx_path == ""
    assert not (tmp_path / DEFAULT_DIR_NAME).exists()


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_gpx_dir_overrides_the_default_location(tmp_path, monkeypatch):
    """``gpx_dir`` を渡すとそこに出る (env より強い = ② から置き場所を指定できる)。"""
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "env-root"))
    hist, phase = _staged(tmp_path)
    target = tmp_path / "chosen"

    result = run_auto_rietveld([hist], [phase], gpx_dir=str(target))

    assert Path(result.gpx_path).parent.parent == target
    assert not (tmp_path / "env-root").exists()
