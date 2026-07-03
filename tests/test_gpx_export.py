"""TASK-0008 .gpx 書き出し export_gpx の TDD Red フェーズテスト。

対象実装 (未実装):
- tsumugin.export.gpx.export_gpx(path, phases, two_theta, intensity, *,
  weights=None, wavelength=1.5406) -> str
- GSASIIBackend._build_project() 抽出リファクタ (refine / export_gpx で共有)
- tsumugin.export.__init__ への export_gpx re-export

マーカー方針:
- GSAS-II 依存ケースは @pytest.mark.gsas (conftest.py が未導入環境で自動 skip)。
  本環境は GSAS-II 導入済みのため実行される。
- 未導入経路ケース (TC-006-03 / TC-006-08) はマーカー無し + gsasii_available()
  による skip 分岐 (既存 test_backend_raises_when_unavailable と同一パターン)。

TC-006-12 (既存 contract test 群の非退行) は新規テストを追加せず、Green /
verify-complete フェーズで tests/test_gsasii_backend.py を走らせて担保する
(テストケース定義書 TC-006-12 の方針)。

tmp_path フィクスチャを使用し、永続 .gpx はテストごとに隔離された一時ディレクトリへ
書き出す (pytest tmp_path はテスト終了後に自動回収されるため afterEach 不要)。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tsumugin.backends.gsasii import GSASIIBackend, gsasii_available
from tsumugin.errors import GSASUnavailableError
from tsumugin.model import LatticeParams, PhaseInstance


def _phase(a: float = 4.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    # 【テストデータ準備】: test_gsasii_backend.py の _phase() 慣習を踏襲し、GSAS-II が
    # 確実に計算できる直方晶 1 相を作る (CIF 簡約モデル: P m m m・Ni 1 原子)。
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _grid() -> np.ndarray:
    # 【初期条件設定】: 標準的な 2θ グリッド (20-80°, 0.05° 刻み)。既存 contract test と同一。
    return np.arange(20.0, 80.0, 0.05)


def _reopen(path: str):
    # 【結果検証補助】: 書き出した .gpx を GSASIIscriptable (出力抑制済み) で再オープンする。
    from tsumugin.backends.gsasii import _g2sc

    return _g2sc().G2Project(path)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース
# ---------------------------------------------------------------------------


@pytest.mark.gsas
def test_reopened_gpx_phase_count_matches(tmp_path):
    # 【テスト目的】: 書き出した .gpx を再オープンでき、相数が保存時と一致することを確認する (TC-006-01a)
    # 【テスト内容】: export_gpx で永続 .gpx を生成 → G2Project で再オープン → phases() の長さを照合
    # 【期待される動作】: 有効な GSAS-II プロジェクトが永続パスに生成され相数が入力と等しい
    # 🔵 信頼性: acceptance-criteria TC-006-01 / 要件定義 §4.1 に明記
    from tsumugin.export.gpx import export_gpx  # Red: 未実装のため ImportError で失敗

    # 【テストデータ準備】: 直方晶 1 相 + 合成観測パターン (backend.simulate で生成)
    # 【前提条件確認】: @gsas マーカーにより GSAS-II 導入環境でのみ実行される
    backend = GSASIIBackend()
    tt = _grid()
    phases = (_phase(a=4.0, scale=1.0),)
    intensity = backend.simulate(phases, tt)
    path = str(tmp_path / "out.gpx")

    # 【実際の処理実行】: export_gpx(path, phases, tt, intensity) を呼び永続 .gpx を書き出す
    export_gpx(path, phases, tt, intensity)

    # 【結果検証】: 返却パスの .gpx を G2Project で再オープンし相数を照合する
    project = _reopen(path)
    # 【検証項目】: 再オープンした相数が入力相数と一致すること 🔵
    assert len(project.phases()) == len(phases)  # 【確認内容】: 書き出し完全性 (全相保存)


@pytest.mark.gsas
def test_reopened_phase_lattice_matches_input(tmp_path):
    # 【テスト目的】: 再オープンした相の格子定数 a/b/c が入力 LatticeParams と近似一致する (TC-006-01b)
    # 【テスト内容】: get_cell() の length_a/b/c を入力格子と pytest.approx で照合
    # 【期待される動作】: 書き出し時の格子が .gpx に正しく保存され再オープンで復元できる
    # 🔵 信頼性: acceptance-criteria TC-006-01 / 要件定義 §3.7 (相数・格子まで検証可能)
    from tsumugin.export.gpx import export_gpx

    backend = GSASIIBackend()
    tt = _grid()
    phases = (_phase(a=4.0, scale=1.0),)
    intensity = backend.simulate(phases, tt)
    path = str(tmp_path / "out.gpx")

    # 【処理内容】: _build_project による gpx 構築 → max cyc=0 do_refinements → save()
    export_gpx(path, phases, tt, intensity)

    # 【期待値確認】: 0 サイクル do_refinements は格子を変えないため書き出し値がそのまま復元される
    cell = _reopen(path).phases()[0].get_cell()  # _read_back と同じ length_* アクセス
    # 【検証項目】: 各相の格子 a/b/c が入力と近似一致すること 🔵
    assert cell["length_a"] == pytest.approx(4.0, abs=1e-3)  # 【確認内容】: 格子 a ラウンドトリップ
    assert cell["length_b"] == pytest.approx(4.0, abs=1e-3)  # 【確認内容】: 格子 b ラウンドトリップ
    assert cell["length_c"] == pytest.approx(4.0, abs=1e-3)  # 【確認内容】: 格子 c ラウンドトリップ


@pytest.mark.gsas
def test_gpx_contains_observed_histogram(tmp_path):
    # 【テスト目的】: .gpx にヒストグラム (観測 Yobs) が含まれ入力 intensity と整合する (TC-006-02)
    # 【テスト内容】: 再オープンした histograms() が非空で観測 Yobs が入力 intensity と一致
    # 【期待される動作】: add_powder_histogram 経由の観測データが .gpx に埋め込まれる
    # 🔵 信頼性: acceptance-criteria TC-006-02 / REQ-006 に明記
    from tsumugin.export.gpx import export_gpx

    backend = GSASIIBackend()
    tt = _grid()
    phases = (_phase(a=4.0, scale=1.0),)
    intensity = backend.simulate(phases, tt)
    path = str(tmp_path / "out.gpx")

    export_gpx(path, phases, tt, intensity)

    # 【結果検証】: 再オープンした project のヒストグラムと観測 Yobs を照合する
    project = _reopen(path)
    histograms = project.histograms()
    # 【検証項目】: ヒストグラムが少なくとも 1 つ含まれること 🔵
    assert len(histograms) >= 1  # 【確認内容】: 観測データが .gpx に保存されている
    yobs = np.asarray(histograms[0].getdata("Yobs"), dtype=float)
    # 【検証項目】: Yobs 配列長が入力 intensity と一致すること 🔵
    assert yobs.shape == intensity.shape  # 【確認内容】: 観測点数の保存完全性
    # 【検証項目】: Yobs 値が計算値ではなく入力観測値と整合すること 🔵
    assert yobs == pytest.approx(intensity, rel=1e-3, abs=1e-6)  # 【確認内容】: 観測強度の整合


@pytest.mark.gsas
def test_returns_written_path_string(tmp_path):
    # 【テスト目的】: 戻り値が書き出しパス str であり入力 path と一致する (TC-006-04)
    # 【テスト内容】: export_gpx の戻り値の型・値・ファイル実在を同時確認
    # 【期待される動作】: 書き出し成功時に確定した永続パスを文字列で返す
    # 🔵 信頼性: 要件定義 §2.2 出力仕様 / interfaces.py -> str に明記
    from tsumugin.export.gpx import export_gpx

    backend = GSASIIBackend()
    tt = _grid()
    phases = (_phase(a=4.0, scale=1.0),)
    intensity = backend.simulate(phases, tt)
    path = str(tmp_path / "out.gpx")

    result = export_gpx(path, phases, tt, intensity)

    # 【検証項目】: 戻り値が str 型であること 🔵
    assert isinstance(result, str)  # 【確認内容】: 戻り値契約 (str)
    # 【検証項目】: 戻り値が入力 path と一致すること 🔵
    assert result == path  # 【確認内容】: 返却パスが書き出し先と一致
    # 【検証項目】: 実ファイルが存在すること 🔵
    assert Path(result).exists()  # 【確認内容】: 永続 .gpx がファイルとして実在


@pytest.mark.gsas
def test_gpx_embeds_calculated_pattern(tmp_path):
    # 【テスト目的】: .gpx に計算パターン (Ycalc) が埋め込まれている (TC-006-05)
    # 【テスト内容】: 再オープンした .gpx の Ycalc が有限かつ全ゼロでないことを確認
    # 【期待される動作】: max cyc=0 → do_refinements([{}]) で Ycalc が計算され保存される
    # 🔵 信頼性: 要件定義 §3.5 / architecture.md D5 に明記
    from tsumugin.export.gpx import export_gpx

    backend = GSASIIBackend()
    tt = _grid()
    phases = (_phase(a=4.0, scale=1.0),)
    intensity = backend.simulate(phases, tt)
    path = str(tmp_path / "out.gpx")

    export_gpx(path, phases, tt, intensity)

    ycalc = np.asarray(_reopen(path).histograms()[0].getdata("Ycalc"), dtype=float)
    # 【検証項目】: Ycalc が全て有限値であること 🔵
    assert np.all(np.isfinite(ycalc))  # 【確認内容】: 計算パターンが数値的に健全
    # 【検証項目】: Ycalc が未計算の全ゼロでないこと 🔵
    assert np.any(ycalc > 0.0)  # 【確認内容】: 回折ピークを持つ計算曲線が存在


@pytest.mark.gsas
def test_multiple_phases_lattices_match(tmp_path):
    # 【テスト目的】: 複数相 (2 相) を書き出し再オープンで全相の格子が一致する (TC-006-06)
    # 【テスト内容】: 2 相を渡し相数 2 と各相の格子 a が入力と一致することを確認
    # 【期待される動作】: _add_phases が全相を追加し複数相が独立に永続化される
    # 🔵 信頼性: 入力仕様 (Sequence[PhaseInstance]) + TC-006-01 契約からの網羅拡張
    from tsumugin.export.gpx import export_gpx

    backend = GSASIIBackend()
    tt = _grid()
    phases = (_phase(a=4.0, ref="A"), _phase(a=5.0, ref="B"))
    intensity = backend.simulate(phases, tt)
    path = str(tmp_path / "out_multi.gpx")

    export_gpx(path, phases, tt, intensity)

    reopened = _reopen(path).phases()
    # 【検証項目】: 相数が 2 であること 🔵
    assert len(reopened) == 2  # 【確認内容】: 全相が保存されている
    # 【検証項目】: 相の順序が保持され各相の格子 a が取り違えられないこと 🔵
    assert reopened[0].get_cell()["length_a"] == pytest.approx(4.0, abs=1e-3)  # 相 A の a
    assert reopened[1].get_cell()["length_a"] == pytest.approx(5.0, abs=1e-3)  # 相 B の a


def test_export_gpx_is_reexported():
    # 【テスト目的】: export_gpx が tsumugin.export から re-export され import 可能 (TC-006-07)
    # 【テスト内容】: パッケージ経由・モジュール経由の双方で import でき callable であることを確認
    # 【期待される動作】: export/__init__.py に from .gpx import export_gpx が追加され __all__ に含まれる
    # 🔵 信頼性: note §3.3 / 要件定義 §5 に明記 (GSAS-II 導入状態に依存しないマーカー無しケース)
    import tsumugin.export as export_pkg
    from tsumugin.export import export_gpx as pkg_export_gpx
    from tsumugin.export.gpx import export_gpx as mod_export_gpx

    # 【検証項目】: パッケージ経由の export_gpx が callable であること 🔵
    assert callable(pkg_export_gpx)  # 【確認内容】: tsumugin.export.export_gpx が解決できる
    # 【検証項目】: モジュール経由の export_gpx が callable であること 🔵
    assert callable(mod_export_gpx)  # 【確認内容】: tsumugin.export.gpx.export_gpx が解決できる
    # 【検証項目】: __all__ に export_gpx が公開されていること 🔵
    assert "export_gpx" in export_pkg.__all__  # 【確認内容】: パッケージ公開面の配線


# ---------------------------------------------------------------------------
# 2. 異常系テストケース (GSAS-II 未導入経路 — 導入済み本環境では skip)
# ---------------------------------------------------------------------------


def test_raises_when_gsasii_unavailable(tmp_path):
    # 【テスト目的】: GSAS-II 未導入環境で export_gpx が GSASUnavailableError を送出する (TC-006-03)
    # 【テスト内容】: 書き出しに入る前に副作用ゼロで例外を送出することを確認
    # 【期待される動作】: gsasii_available() が False のとき明示的に例外化 (REQ-105)
    # 🟡 信頼性: acceptance-criteria TC-006-03。導入済み環境では skip されるため本環境では未実行
    if gsasii_available():
        pytest.skip("GSAS-II is installed; unavailable path not exercised")
    from tsumugin.export.gpx import export_gpx

    tt = _grid()
    phases = (_phase(a=4.0, scale=1.0),)
    intensity = np.ones_like(tt)
    path = str(tmp_path / "out.gpx")

    # 【期待値確認】: 未導入では書き出し処理に入る前に GSASUnavailableError を送出する
    with pytest.raises(GSASUnavailableError):
        export_gpx(path, phases, tt, intensity)


def test_no_side_effect_when_unavailable(tmp_path):
    # 【テスト目的】: 未導入経路は副作用ゼロで早期 raise しファイルを生成しない (TC-006-08)
    # 【テスト内容】: GSASUnavailableError 送出後に出力パスへファイルが残らないことを確認
    # 【期待される動作】: 判定が書き出し処理の前に行われ作りかけの .gpx を残さない (P2 非破壊)
    # 🟡 信頼性: 要件定義 §3.2。導入済み環境では skip されるため本環境では未実行
    if gsasii_available():
        pytest.skip("GSAS-II is installed; unavailable path not exercised")
    from tsumugin.export.gpx import export_gpx

    tt = _grid()
    phases = (_phase(a=4.0, scale=1.0),)
    intensity = np.ones_like(tt)
    path = str(tmp_path / "out.gpx")

    with pytest.raises(GSASUnavailableError):
        export_gpx(path, phases, tt, intensity)
    # 【検証項目】: 出力パスにファイルが生成されていないこと 🟡
    assert not Path(path).exists()  # 【確認内容】: エラー時のクリーンな状態保証 (冪等性)


# ---------------------------------------------------------------------------
# 3. 境界値テストケース
# ---------------------------------------------------------------------------


@pytest.mark.gsas
def test_single_phase_minimal(tmp_path):
    # 【テスト目的】: 単相 (最小の非空 phases=1) で正常に書き出せる (TC-006-09)
    # 【テスト内容】: 長さ 1 の非空 Sequence 下限で write→reopen→verify が通ることを確認
    # 【期待される動作】: 最小要素数でも相追加・書き出しが破綻しない
    # 🔵 信頼性: 要件定義 §2.1 (空でないこと) / TC-006-01 基本ケースと一致
    from tsumugin.export.gpx import export_gpx

    backend = GSASIIBackend()
    tt = _grid()
    phases = (_phase(a=4.0, scale=1.0),)  # 非空 Sequence の下限 (長さ 1)
    intensity = backend.simulate(phases, tt)
    path = str(tmp_path / "single.gpx")

    export_gpx(path, phases, tt, intensity)

    project = _reopen(path)
    # 【検証項目】: 単相でも相数が 1 であること 🔵
    assert len(project.phases()) == 1  # 【確認内容】: 非空下限境界での堅牢性
    # 【検証項目】: 単相の格子 a が入力と一致すること 🔵
    assert project.phases()[0].get_cell()["length_a"] == pytest.approx(4.0, abs=1e-3)


@pytest.mark.gsas
def test_gpx_reopenable_after_tempdir_exit(tmp_path):
    # 【テスト目的】: 作業一時ディレクトリ破棄後も永続 .gpx が有効に再オープンできる (TC-006-10)
    # 【テスト内容】: export_gpx 戻り後 (内部 TemporaryDirectory 脱出後) の再オープンが成立するか
    # 【期待される動作】: instprm/xye/cif 消滅後も .gpx が自己完結して再オープンできる
    # 🔵 信頼性: 要件定義 §3.4 / note §6 (TemporaryDirectory 消滅後の永続性) に明記
    from tsumugin.export.gpx import export_gpx

    backend = GSASIIBackend()
    tt = _grid()
    phases = (_phase(a=4.0, scale=1.0),)
    intensity = backend.simulate(phases, tt)
    path = str(tmp_path / "persistent.gpx")

    # 【実行タイミング】: export_gpx 完了 = 内部一時ディレクトリはすでに消滅している
    export_gpx(path, phases, tt, intensity)

    # 【期待値確認】: 補助ファイル消滅という極端条件下でも「後から」の再オープンが成立する
    project = _reopen(path)
    # 【検証項目】: 一時ディレクトリ破棄後も相数が一致すること 🔵
    assert len(project.phases()) == len(phases)  # 【確認内容】: 永続 .gpx の自己完結性
    # 【検証項目】: 一時ディレクトリ破棄後も格子が一致すること 🔵
    assert project.phases()[0].get_cell()["length_a"] == pytest.approx(4.0, abs=1e-3)


@pytest.mark.gsas
def test_export_with_and_without_weights(tmp_path):
    # 【テスト目的】: weights=None 既定と明示 weights の双方で書き出し成功する (TC-006-11)
    # 【テスト内容】: kw-only nullable 引数 weights の両分岐 (None / 明示配列) を実行担保
    # 【期待される動作】: _write_xye の重み分岐の双方が export 経路で機能し .gpx が有効
    # 🟡 信頼性: 入力仕様 §2.1 と _write_xye 既存分岐からの妥当な推測 (重み反映値は厳密検証しない)
    from tsumugin.export.gpx import export_gpx

    backend = GSASIIBackend()
    tt = _grid()
    phases = (_phase(a=4.0, scale=1.0),)
    intensity = backend.simulate(phases, tt)

    # ケースA: weights 未指定 (None → esd = sqrt(max(intensity, 1.0)) の既定挙動)
    path_a = str(tmp_path / "weights_none.gpx")
    result_a = export_gpx(path_a, phases, tt, intensity)
    project_a = _reopen(result_a)
    # 【検証項目】: 既定 (None) 経路で相数・格子が一致すること 🟡
    assert len(project_a.phases()) == len(phases)  # 【確認内容】: None 経路の書き出し完全性
    assert project_a.phases()[0].get_cell()["length_a"] == pytest.approx(4.0, abs=1e-3)

    # ケースB: 明示 weights (全 1 → esd = 1/sqrt(max(weights, 1e-12)) の分岐)
    path_b = str(tmp_path / "weights_explicit.gpx")
    result_b = export_gpx(path_b, phases, tt, intensity, weights=np.ones_like(intensity))
    project_b = _reopen(result_b)
    # 【検証項目】: 明示 weights 経路でも相数・格子が一致すること 🟡
    assert len(project_b.phases()) == len(phases)  # 【確認内容】: 明示重み経路の書き出し完全性
    assert project_b.phases()[0].get_cell()["length_a"] == pytest.approx(4.0, abs=1e-3)


# ---------------------------------------------------------------------------
# 4. リグレッション / リファクタ不変性テスト (完了条件⑤ / D-Q8)
# ---------------------------------------------------------------------------
#
# TC-006-12 (_build_project() 抽出後も既存 contract test 群が退行しない) は
# 新規テストを追加せず、Green / verify-complete フェーズで
# tests/test_gsasii_backend.py (@gsas 6 件 + unavailable 1 件 +
# available 判定 1 件) を走らせて担保する (テストケース定義書 TC-006-12 の方針)。


def test_build_project_helper_shared():
    # 【テスト目的】: gpx 構築が _build_project() 単一実装に統合されている (TC-006-13 / D-Q8)
    # 【テスト内容】: GSASIIBackend._build_project が属性として存在し callable であることを構造検証
    # 【期待される動作】: refine と export_gpx の gpx 構築が単一情報源に集約される
    # 🔵 信頼性: 要件定義 §4.5 / note §4.3 D-Q8 / 完了条件⑤ に明記
    # 【検証項目】: _build_project ヘルパが GSASIIBackend に存在すること 🔵
    assert hasattr(GSASIIBackend, "_build_project")  # 【確認内容】: 単一情報源リファクタの構造担保
    # 【検証項目】: _build_project が callable であること 🔵
    assert callable(GSASIIBackend._build_project)  # 【確認内容】: 共有ヘルパとして呼び出し可能
