"""★規定「全解析で gpx を保存する」を**実 GSAS** で確かめる (T1 fluoroapatite)。

決定論テスト (`test_gpx_output.py`) は保存ヘルパの振る舞いしか見ない — engine がそれを
**呼んでいない**場合は緑のままになる。ここは実際に `run_auto_rietveld` を回し、

1. 何も指定しなくても .gpx が**観測データ隣接**に出来ること
2. `AutoRietveldResult.gpx_path` がそのファイルを指すこと (③ が MEM へ渡せる)
3. 索引 (manifest.jsonl) に Rwp 付きで 1 行残ること
4. `save_gpx=False` では 1 バイトも書かないこと (opt-out が本当に効く)
5. ただし明示 `keep_gpx` は `save_gpx=False` でもそのパスに残ること (止まるのは既定保存だけ)

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
    assert result.artifact_fallback_reason == ""  # 書ける場所なので退避していない

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
def test_explicit_keep_gpx_survives_save_gpx_false(tmp_path, monkeypatch):
    """★明示 ``keep_gpx`` は ``save_gpx=False`` でもそのパスへ残る (止まるのは既定保存だけ)。

    opt-out は「置き場所を tsumugin が決める保存」を止めるもので、名指しされた保存を黙って
    捨てるものではない (優先順位の正本は `gpxstore.plan_output`)。engine の配線を縛る。
    """
    monkeypatch.delenv(ENV_VAR, raising=False)
    hist, phase = _staged(tmp_path)
    target = tmp_path / "kept.gpx"

    result = run_auto_rietveld([hist], [phase], keep_gpx=str(target), save_gpx=False, max_cyc=1)

    assert result.gpx_path == str(target)
    assert target.is_file() and target.stat().st_size > 0
    assert not (tmp_path / DEFAULT_DIR_NAME).exists()  # 既定保存は止まったまま


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_gpx_dir_overrides_the_default_location(tmp_path, monkeypatch):
    """``gpx_dir`` を渡すとそこに出る (env より強い = ② から置き場所を指定できる)。"""
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "env-root"))
    hist, phase = _staged(tmp_path)
    target = tmp_path / "chosen"

    result = run_auto_rietveld([hist], [phase], gpx_dir=str(target))

    assert Path(result.gpx_path).parent.parent == target
    assert not (tmp_path / "env-root").exists()


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_fallback_to_temp_is_reported_on_the_result(tmp_path, unwritable_gpx_root):
    """★頼まれた根に書けず一時領域へ退避したら、理由を ``artifact_fallback_reason`` に載せる。

    非トートロジー: 退避はエンジン自身が `plan_output` で解決し、理由は ``m7_gpx_fallback``
    としてエンジンの台帳に書かれる。② の単発 `auto_rietveld` はその台帳を返さない (呼び出し側が
    台帳を渡さなければ `run_auto_rietveld` の私有の台帳になる) ので、**結果に載らなければ ③ に
    見えるのは一時領域を指す ``gpx_path`` だけ**になる。決定論テストは ② の写ししか見ないので、
    エンジンが実際に載せることはここで確かめる。
    """
    from tsumugin.store import Ledger

    hist, phase = _staged(tmp_path)
    ledger = Ledger()

    result = run_auto_rietveld(
        [hist], [phase], gpx_dir=str(tmp_path / "chosen"), ledger=ledger, max_cyc=1
    )

    assert Path(result.gpx_path).is_file(), result.gpx_path
    # 退避先 = `gpxstore` の一時 run ディレクトリ (エンジン自身の作業 temp ではない)
    assert Path(result.gpx_path).parent.parent == unwritable_gpx_root
    assert Path(result.gpx_path).parent.name.startswith("tsumugin-gpx-")
    assert "一時領域へ退避" in result.artifact_fallback_reason
    rows = [e.payload for e in ledger.entries if e.kind == "m7_gpx_fallback"]
    assert [r["reason"] for r in rows] == [result.artifact_fallback_reason]


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_no_fallback_reason_when_nothing_was_saved_at_the_fallback(
    tmp_path, unsavable_gpx_fallback
):
    """退避先にも保存できなかったら理由は載せない — 「一時領域に在る」と言うのは嘘になる。

    その失敗は台帳の ``m7_gpx_error`` の担当 (``gpx_path`` は "")。退避先を「書けない場所」
    (親が通常ファイル) に向け、退避は起きたが複製は失敗した状態を作る。
    """
    from tsumugin.store import Ledger

    hist, phase = _staged(tmp_path)
    ledger = Ledger()

    result = run_auto_rietveld(
        [hist], [phase], gpx_dir=str(tmp_path / "chosen"), ledger=ledger, max_cyc=1
    )

    assert result.gpx_path == ""
    assert result.artifact_fallback_reason == ""
    assert "m7_gpx_error" in [e.kind for e in ledger.entries]


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_layer2_auto_rietveld_says_the_artifact_fell_back(tmp_path, unwritable_gpx_root):
    """★② 越し (③ が実際に受け取る JSON) で退避理由が ``warnings`` に出る — 通しの検算。

    非トートロジー: 決定論テストは ② の写し (スタブ結果) と ① のエンジン (本テスト群の上) を
    別々に見るだけで、間の既定 runner (`_default_gsas_runner`) が結果を作り直す/差し替えると
    どちらも緑のまま ③ には再び %TEMP% の ``gpx_path`` しか届かなくなる。
    """
    from tsumugin.mcp.rietveld_tools import auto_rietveld

    hist, phase = _staged(tmp_path)

    out = auto_rietveld(
        [hist.to_dict()], [phase.to_dict()], gpx_dir=str(tmp_path / "chosen"), max_cyc=1
    )

    assert "error" not in out, out.get("error")
    assert Path(out["gpx_path"]).parent.parent == unwritable_gpx_root
    assert len(out["warnings"]) == 1, out["warnings"]
    assert out["warnings"][0].startswith("成果物の保存先: ")
    assert "一時領域へ退避" in out["warnings"][0]
